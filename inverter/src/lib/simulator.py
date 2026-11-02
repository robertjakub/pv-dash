#!/usr/bin/env python3
"""The simulated day (or frozen/static) values: curves, runtime overrides,
the battery machine wiring and the register-map assembly."""
import math
import threading
import time

from .battery import BATT_GRID_MARGIN_W, BATT_MAX_W, BATT_STANDBY_W, BatteryMachine
from .registers import (METER_EXPORT_KWH, METER_IMPORT_KWH, battery_regs, diag_regs,
                        meter_regs, output_regs, put_i32, string_regs)

SUNRISE, SUNSET = 6.0, 18.0

# Runtime-controllable knobs (see the control server): None = follow the
# simulation, a number = pinned. `cloud` scales PV (0 = clear, 1 = dark).
OVERRIDE_KEYS = ('pv', 'load', 'batt', 'soc', 'cloud')


def bell(t, center, width):
    return math.exp(-((t - center) ** 2) / (2.0 * width * width))


class Simulator:
    def __init__(self, peak_w, static, frozen_time, battery=False, battery_kwh=6.9):
        self.peak_w = peak_w
        self.static = static
        self.frozen_time = frozen_time
        self.battery = battery
        self.battery_kwh = battery_kwh
        self._lock = threading.Lock()
        self._overrides = {k: None for k in OVERRIDE_KEYS}
        self.batt_machine = BatteryMachine()

    # ---- runtime control (thread-safe; the control server runs in its own thread)

    def override(self, key, value):
        """Pin a knob (or None to follow the simulation again)."""
        if key not in OVERRIDE_KEYS:
            raise KeyError(key)
        if value is not None:
            value = float(value)
            if not math.isfinite(value):
                raise ValueError('value must be finite, got %r' % value)
        if key == 'cloud':
            value = min(1.0, max(0.0, value)) if value is not None else None
        if key == 'soc':
            value = min(100.0, max(0.0, value)) if value is not None else None
            if value is not None:
                self.batt_machine.seed(value)
        with self._lock:
            self._overrides[key] = value

    def overrides(self):
        with self._lock:
            return dict(self._overrides)

    def reset_overrides(self):
        """Release every pin and re-seed the battery from the simulated day."""
        with self._lock:
            n = sum(1 for v in self._overrides.values() if v is not None)
            for k in self._overrides:
                self._overrides[k] = None
        self.batt_machine.reset()
        return n

    def freeze(self, t):
        """Pin the simulated clock (HH:MM float hours) or None for the real clock."""
        with self._lock:
            self.frozen_time = t

    # ---- curves

    def clock(self):
        if self.frozen_time is not None:
            return self.frozen_time
        lt = time.localtime()
        return lt.tm_hour + lt.tm_min / 60.0

    def pv(self, t):
        if SUNRISE < t < SUNSET:
            return self.peak_w * math.sin(math.pi * (t - SUNRISE) / (SUNSET - SUNRISE))
        return 0.0

    def home(self, t):
        return 250.0 + 700.0 * bell(t, 7.5, 1.0) + 400.0 * bell(t, 13.0, 1.5) + 1400.0 * bell(t, 19.0, 1.8)

    def batt(self, t):
        """The simulated day's battery plan (drives the day energy counters)."""
        if not self.battery:
            return 0.0
        surplus = self.pv(t) - self.home(t)
        if SUNRISE < t < SUNSET and surplus > BATT_GRID_MARGIN_W:
            return min(surplus - BATT_GRID_MARGIN_W, BATT_MAX_W)
        if 18.0 <= t < 23.0:
            return -min(self.home(t) - BATT_STANDBY_W, BATT_MAX_W)
        return 0.0

    def curve_soc(self, t):
        """The simulated day's SoC at time t (seeding/reset anchor)."""
        if not self.battery:
            return None
        net_kwh = self.integrate_kwh(self.batt, 0.0, t)
        return BatteryMachine.curve_soc(net_kwh, self.battery_kwh)

    def temperature(self, t):
        """Panel/array temperature °C: day-warm ambient + sun heating (stateless)."""
        if self.static:
            return 28.0
        ambient = 18.0 + 8.0 * math.sin(math.pi * max(0.0, min(t - 9.0, 12.0)) / 12.0)
        pv_frac = self.pv(t) / self.peak_w if self.peak_w else 0.0
        return ambient + 22.0 * pv_frac

    def integrate_kwh(self, fn, t0, t1):
        step = 2.0 / 60.0
        total, u = 0.0, t0
        while u < t1:
            u2 = min(u + step, t1)
            total += 0.5 * (fn(u) + fn(u2)) * (u2 - u)
            u = u2
        return total / 1000.0

    # ---- register map

    def effective(self):
        """Effective (pv_w, load_w, batt_w, soc, cloud, overrides) after pins —
        the single source of truth for the register map and the control status."""
        ov = self.overrides()
        t = self.clock()
        cloud = ov['cloud'] if ov['cloud'] is not None else 0.0
        if self.static:
            pv = ov['pv'] if ov['pv'] is not None else 4000.0 * (1.0 - cloud)
            load = ov['load'] if ov['load'] is not None else 4300.0
            batt = ov['batt'] if ov['batt'] is not None else (1200.0 if self.battery else 0.0)
            soc = ov['soc'] if ov['soc'] is not None else (65.0 if self.battery else None)
        else:
            pv = ov['pv'] if ov['pv'] is not None else self.pv(t) * (1.0 - cloud)
            load = ov['load'] if ov['load'] is not None else self.home(t)
            soc = ov['soc'] if ov['soc'] is not None else self._tick_soc(t, pv, load)
            batt = ov['batt'] if ov['batt'] is not None else (
                0.0 if not self.battery or soc is None else BatteryMachine.decide(pv, load, soc))
        return pv, load, batt, soc, cloud, ov

    def _tick_soc(self, t, pv_w, load_w):
        """Stateful SoC: seed from the curve on first use, then integrate."""
        m = self.batt_machine
        if m.soc is None and self.battery:
            m.seed(self.curve_soc(t))
        return m.tick(t, pv_w, load_w, self.battery_kwh, self.battery)

    def registers(self):
        ov = self.overrides()
        t = self.clock()
        pv_w, home_w, batt_w, soc, _cloud, ov = self.effective()
        if self.static:
            # the classic static demo: PV 4000 W, battery charging 1200 W at
            # 65 %, exporting 1500 W (home derives to 4300 W); overrides pin
            # the individual terms, the grid then follows the balance
            pinned = any(ov[k] is not None for k in ('pv', 'load', 'batt'))
            grid_w = pv_w - batt_w - home_w if pinned else -1500.0
            regs = {}
            put_i32(regs, 32064, pv_w)
            put_i32(regs, 32080, pv_w)
            put_i32(regs, 32106, 1821242)
            put_i32(regs, 32114, 1242)
            put_i32(regs, 37113, grid_w)
            regs[32087] = int(round(self.temperature(t) * 10))
            regs[32089] = 512
            string_regs(regs, pv_w, 405.0)
            output_regs(regs, pv_w)
            regs[32085] = 5000
            if self.battery:
                battery_regs(regs, batt_w, soc, 25000, 18000, 1234, 890)
            meter_regs(regs, grid_w, METER_EXPORT_KWH, METER_IMPORT_KWH)
            diag_regs(regs)
            return regs
        grid_w = pv_w - batt_w - home_w
        if t <= SUNRISE:
            day_kwh = 0.0
        elif t < SUNSET:
            day_kwh = (self.peak_w / 1000.0) * (SUNSET - SUNRISE) / math.pi * (1 - math.cos(math.pi * (t - SUNRISE) / (SUNSET - SUNRISE)))
        else:
            day_kwh = 2.0 * (self.peak_w / 1000.0) * (SUNSET - SUNRISE) / math.pi
        pv_frac = pv_w / self.peak_w if self.peak_w else 0.0
        export_day = self.integrate_kwh(lambda u: max(self.pv(u) - self.batt(u) - self.home(u), 0.0), 0.0, t)
        import_day = self.integrate_kwh(lambda u: max(self.home(u) + self.batt(u) - self.pv(u), 0.0), 0.0, t)
        regs = {}
        put_i32(regs, 32064, pv_w)
        put_i32(regs, 32080, pv_w)
        put_i32(regs, 32106, (18200.0 + day_kwh) * 100)
        put_i32(regs, 32114, day_kwh * 100)
        put_i32(regs, 37113, grid_w)
        regs[32087] = int(round(self.temperature(t) * 10))
        regs[32089] = 512 if pv_w > 0 else 40960
        string_regs(regs, pv_w, 420.0 - 40.0 * pv_frac)
        output_regs(regs, pv_w)
        regs[32085] = 5000
        if self.battery:
            battery_regs(regs, batt_w, soc,
                         int((50000.0 + self.integrate_kwh(lambda u: max(self.batt(u), 0.0), 0.0, t) * 100)),
                         int(self.integrate_kwh(lambda u: max(-self.batt(u), 0.0), 0.0, t) * 100),
                         int(self.integrate_kwh(lambda u: max(self.batt(u), 0.0), 0.0, t) * 100),
                         int(self.integrate_kwh(lambda u: max(-self.batt(u), 0.0), 0.0, t) * 100))
        meter_regs(regs, grid_w, METER_EXPORT_KWH + export_day, METER_IMPORT_KWH + import_day)
        diag_regs(regs)
        return regs
