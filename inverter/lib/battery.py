#!/usr/bin/env python3
"""The battery state machine: charges the PV surplus (keeping a grid margin),
covers the home deficit from storage, never leaves its SoC bounds. The SoC is
stateful — it integrates the effective battery power with the simulated clock
(charge efficiency 95 %, self-discharge 0.01 %/h), so freezing/jumping the
clock is the time-lapse control and the %SoC really moves while the battery
charges/discharges."""
import threading

from .statics import BATT_CHARGE_EFF, BATT_DISCHARGE_CAP, BATT_GRID_MARGIN_W, \
    BATT_MAX_TICK_H, BATT_MAX_W, BATT_RESERVE_SOC, BATT_SELF_DISCH_H, BATT_STANDBY_W


class BatteryMachine:
    """SoC state + decision + clock integration (thread-safe; the control
    server and the Modbus pollers run in their own threads)."""

    def __init__(self):
        self._lock = threading.Lock()
        self.soc = None          # % state; None = unseeded (first tick seeds from the curve)
        self.last_tick = None    # simulated clock of the previous tick

    def seed(self, soc):
        """Pin a starting SoC (the control server's `set soc`); unpinning resumes here."""
        with self._lock:
            self.soc = soc

    def reset(self):
        """Drop the state; the next tick re-seeds from the simulated day."""
        with self._lock:
            self.soc = None
            self.last_tick = None

    @staticmethod
    def decide(pv_w, load_w, soc):
        """What the machine wants right now: +charge / −discharge / 0 hold."""
        surplus = pv_w - load_w
        if surplus > BATT_GRID_MARGIN_W:
            return 0.0 if soc >= 100.0 else min(surplus - BATT_GRID_MARGIN_W, BATT_MAX_W)
        deficit = -surplus
        if deficit > BATT_STANDBY_W:
            return 0.0 if soc <= BATT_RESERVE_SOC else -min(deficit - BATT_STANDBY_W, BATT_MAX_W)
        return 0.0

    @staticmethod
    def curve_soc(net_kwh, kwh):
        """The simulated day's SoC (used for seeding/reset)."""
        return min(100.0, max(5.0, 50.0 + net_kwh / kwh * 100.0))

    def tick(self, t, pv_w, load_w, kwh, enabled, forced_w=None):
        """Advance the SoC to simulated time t and return it. forced_w pins the
        power (the control server's battery-state force). Clock jumps integrate
        the effective power (time-lapse); going back in time, or a step wider
        than BATT_MAX_TICK_H, skips the integration (no free energy, no
        laptop-sleep monsters)."""
        with self._lock:
            if not enabled or self.soc is None:
                self.last_tick = t
                return self.soc
            if self.last_tick is None:      # just seeded: start integrating from here
                self.last_tick = t
                return self.soc
            dt_h = t - self.last_tick
            self.last_tick = t
            if dt_h <= 0 or dt_h > BATT_MAX_TICK_H:
                return self.soc
            w = self.decide(pv_w, load_w, self.soc) if forced_w is None else forced_w
            stored = w * (BATT_CHARGE_EFF if w > 0 else 1.0)   # the charge losses
            d_soc = stored * dt_h / (kwh * 10.0) - BATT_SELF_DISCH_H * dt_h
            new = min(100.0, max(0.0, self.soc + d_soc))
            if d_soc < 0:
                new = max(new, BATT_RESERVE_SOC)
            self.soc = new
            return self.soc
