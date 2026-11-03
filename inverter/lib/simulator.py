#!/usr/bin/env python3
"""The simulated day (or frozen/static) values: curves, runtime overrides
(value pins, the grid setpoint balanced by the battery), the battery state
machine wiring and the profile-driven register assembly."""
import math
import random
import threading
import time

from .battery import BATT_DISCHARGE_CAP, BATT_GRID_MARGIN_W, BATT_MAX_W, BATT_STANDBY_W, BatteryMachine
from .profile import load_profile, resolve_profile

SUNRISE, SUNSET = 6.0, 18.0

# Cloud state machines (Ornstein-Uhlenbeck: mean-reverting random walk over
# the simulated clock — time-lapse jumps move the clouds, a frozen clock
# freezes them): mode -> (mean, theta/h, sigma/sqrt(h), lo, hi)
CLOUD_MACHINES = {
    'autumn': (0.45, 2.5, 0.60, 0.05, 0.95),   # passing clouds, quick swings
    'spring': (0.25, 2.0, 0.50, 0.02, 0.80),   # fair-weather cumulus, brief dips
    'winter': (0.75, 0.8, 0.35, 0.10, 1.00),   # heavy overcast spells, slow breaks
}

# lifetime meter totals the demo starts from (kWh)
METER_EXPORT_KWH = 12500.0
METER_IMPORT_KWH = 9800.0

# Runtime-controllable knobs (see the control server): None = follow the
# simulation, a number = pinned. `cloud` scales PV (0 = clear, 1 = dark);
# `grid` pins the grid setpoint and the battery balances to hold it.
OVERRIDE_KEYS = ('pv', 'load', 'batt', 'grid', 'soc', 'cloud')


def bell(t, center, width):
    return math.exp(-((t - center) ** 2) / (2.0 * width * width))


class Simulator:
    def __init__(self, peak_w, static, frozen_time, battery=False, battery_kwh=6.9,
                 profile=None, seed=None):
        self.peak_w = peak_w
        self.static = static
        self.frozen_time = frozen_time
        self.battery = battery
        self.battery_kwh = battery_kwh
        self._lock = threading.Lock()
        self._overrides = {k: None for k in OVERRIDE_KEYS}
        self.batt_machine = BatteryMachine()
        self.profile = profile if profile is not None else load_profile(resolve_profile('sun2000'))
        self.cloud_mode = None          # None = clear sky; 'autumn'/'spring'/'winter' = the machine
        self.batt_state = None          # None = the machine decides; 'charging'/'discharging' = forced
        self.mppt = 'both'              # which PV strings feed the MPPTs: both | east | west | none
        self.grid_voltage = 230.0       # nominal phase voltage (V); the machine wanders +-10 %
        self.utc = True                 # the state machines integrate over the UTC clock (configurable)
        self._cloud_rng = random.Random(seed)
        self._cloud_value = 0.0
        self._cloud_t = None
        self._grid_v_rng = random.Random(seed)
        self._grid_v = [0.0, 0.0, 0.0]  # per-phase deviation from the nominal (fraction)
        self._grid_v_t = None
        self._home_shares = [1 / 3, 1 / 3, 1 / 3]   # the unbalanced home: the per-phase load shares
        self._home_t = None

    def set_profile(self, profile_map):
        """Swap the inverter profile (SIGHUP); clients serving from the old map
        see the new one on the next poll."""
        with self._lock:
            self.profile = profile_map

    def set_cloud_mode(self, mode):
        """Enter a cloud state machine (autumn/spring/winter) or None for a clear sky."""
        if mode is not None and mode not in CLOUD_MACHINES:
            raise KeyError(mode)
        with self._lock:
            self.cloud_mode = mode
            self._cloud_t = None        # re-anchor: the next tick starts fresh

    def cloud_display(self):
        """What `cloud=` shows in status: 'auto', a pinned factor, or the
        machine mode with its current factor."""
        ov = self.overrides()
        if ov['cloud'] is not None:
            return '%g' % ov['cloud']
        if self.cloud_mode:
            return '%s(%0.2f)' % (self.cloud_mode, self._cloud_value)
        return 'clear'

    def _cloud(self, t):
        """The effective cloud factor: a pinned scalar, or the mode's machine
        integrating over the simulated clock (dt = 0 when frozen -> static)."""
        ov = self.overrides()
        if ov['cloud'] is not None:
            return ov['cloud']
        if not self.cloud_mode:
            return 0.0
        mean, theta, sigma, lo, hi = CLOUD_MACHINES[self.cloud_mode]
        with self._lock:
            if self._cloud_t is None:
                self._cloud_value, self._cloud_t = mean, t   # start at the mean
            dt = t - self._cloud_t
            if dt > 0:
                c = self._cloud_value + theta * (mean - self._cloud_value) * dt \
                    + sigma * math.sqrt(dt) * self._cloud_rng.gauss(0.0, 1.0)
                self._cloud_value = min(hi, max(lo, c))
                self._cloud_t = t
            return self._cloud_value

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
        """Release every pin, leave the cloud machine and re-seed the battery
        from the simulated day."""
        with self._lock:
            n = sum(1 for v in self._overrides.values() if v is not None)
            for k in self._overrides:
                self._overrides[k] = None
        self.cloud_mode = None
        self._cloud_t = None
        self.batt_machine.reset()
        return n

    def freeze(self, t):
        """Pin the simulated clock (HH:MM float hours) or None for the real clock."""
        with self._lock:
            self.frozen_time = t

    # ---- curves

    def _home_phase_shares(self, t):
        """The unbalanced home: three mean-reverting walks around 1/3 per
        phase (clamped to 0.22..0.44, renormalised), integrating with the
        simulated clock — the per-phase meter currents really differ."""
        with self._lock:
            if self._home_t is None:
                self._home_t = t
            dt = t - self._home_t
            self._home_t = t
            if dt > 0:
                sh = [min(0.44, max(0.22, sh + 0.8 * (1 / 3 - sh) * dt
                                     + 0.02 * math.sqrt(dt) * self._grid_v_rng.gauss(0.0, 1.0)))
                      for sh in self._home_shares]
                total = sum(sh)
                self._home_shares = [s / total for s in sh]
            return list(self._home_shares)

    def home_phases(self, t, home_w):
        """The per-phase home power: the load split by the asymmetric shares."""
        return [home_w * sh for sh in self._home_phase_shares(t)]

    def _grid_voltages(self, t):
        """The per-phase grid voltage state machine: three independent
        mean-reverting walks around the nominal (the phases wander
        differently — an unbalanced grid), clamped to ±10 %. It integrates
        with the simulated clock: the time-lapse jumps move it, a frozen
        clock freezes it."""
        with self._lock:
            if self._grid_v_t is None:
                self._grid_v_t = t      # anchor on first use
            dt = t - self._grid_v_t
            self._grid_v_t = t          # re-anchor even on a backward jump (the battery's semantics)
            if dt > 0:
                self._grid_v_t = t
                self._grid_v = [
                    min(0.10, max(-0.10, w + 1.0 * (0.0 - w) * dt
                                  + 0.03 * math.sqrt(dt) * self._grid_v_rng.gauss(0.0, 1.0)))
                    for w in self._grid_v]
            return [self.grid_voltage * (1.0 + w) for w in self._grid_v]

    def clock(self):
        """The simulated clock the state machines integrate over: UTC by
        default (--timezone / set timezone local for the wall clock)."""
        if self.frozen_time is not None:
            return self.frozen_time
        lt = time.gmtime() if self.utc else time.localtime()
        return lt.tm_hour + lt.tm_min / 60.0

    def pv_string(self, t, which):
        """One string's sine bell over the simulated clock: the east array
        (string-1) peaks late morning (06:00-16:00), the west array (string-2)
        early afternoon (08:00-18:00). Each carries half the array."""
        half = self.peak_w / 2.0
        lo, hi = (6.0, 16.0) if which == 'east' else (8.0, 18.0)
        if lo < t < hi:
            return half * math.sin(math.pi * (t - lo) / (hi - lo))
        return 0.0

    def pv(self, t):
        """Total PV across the enabled strings (the `mppt` setting)."""
        east = self.pv_string(t, 'east') if self.mppt in ('both', 'east') else 0.0
        west = self.pv_string(t, 'west') if self.mppt in ('both', 'west') else 0.0
        return east + west

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

    # ---- register map (profile-driven)

    def effective(self):
        """Effective (pv_w, load_w, batt_w, soc, cloud, overrides) after pins —
        the single source of truth for the register map and the control status.
        The battery decision order: the batt pin > the battery-state force >
        the grid setpoint balance > the machine's own decision."""
        ov = self.overrides()
        t = self.clock()
        cloud = ov['cloud'] if ov['cloud'] is not None else self._cloud(t)
        if self.static:
            pv = ov['pv'] if ov['pv'] is not None else 4000.0 * (1.0 - cloud) * (
                1.0 if self.mppt == 'both' else 0.5 if self.mppt in ('east', 'west') else 0.0)
            load = ov['load'] if ov['load'] is not None else 4300.0
            # the classic static demo charges at 1200 W; a grid setpoint
            # re-balances the battery instead
            batt = ov['batt'] if ov['batt'] is not None else (
                self._batt_clamp(self._forced_batt(1200.0 if ov['grid'] is None
                                                   else self._grid_balanced(pv, load, ov)), t)
                if self.battery else 0.0)
            soc = ov['soc'] if ov['soc'] is not None else (65.0 if self.battery else None)
        else:
            pv = ov['pv'] if ov['pv'] is not None else self.pv(t) * (1.0 - cloud)
            load = ov['load'] if ov['load'] is not None else self.home(t)
            soc = ov['soc'] if ov['soc'] is not None else self._tick_soc(t, pv, load, ov)
            batt = ov['batt'] if ov['batt'] is not None else (
                0.0 if not self.battery or soc is None else
                self._batt_clamp(self._forced_batt(self._grid_balanced(pv, load, ov, soc)), t))
        return pv, load, batt, soc, cloud, ov

    def _grid_balanced(self, pv_w, load_w, ov, soc=None):
        """The grid-setpoint decision: the battery charges/discharges whatever
        holds the grid at the pinned W (set grid 0 = zero-export). Clamped to
        the battery's power range; the machine's SoC bounds still apply via
        the tick (a full battery lets the residual spill to the grid)."""
        if ov['grid'] is None:
            return BatteryMachine.decide(pv_w, load_w, soc) if soc is not None else 0.0
        want = pv_w - load_w - ov['grid']
        return min(BATT_MAX_W, max(-BATT_MAX_W, want))

    def _batt_ceiling(self, t):
        """The realistic battery power ceiling at simulated time t: the
        rating derated by the site temperature (the deep cold and the heat
        limit the cells)."""
        temp = self.temperature(t)
        if temp < 0:
            f = 0.5          # the deep cold: half power
        elif temp < 10:
            f = 0.8
        elif temp > 50:
            f = 0.7          # the heat: the cells protect themselves
        elif temp > 40:
            f = 0.9
        else:
            f = 1.0
        return BATT_MAX_W * f

    def _batt_clamp(self, w, t):
        """Clamp a battery power to what the hardware can do: the charge at
        the derated rating, the discharge at 80 % of it (a 10 kW battery
        outputs at most 8 kW to the home)."""
        ceil = self._batt_ceiling(t)
        return min(ceil, max(-ceil * BATT_DISCHARGE_CAP, w))

    def _forced_batt(self, decided=0.0):
        """The battery-state force: charging/discharging at full power, or the
        machine's own decision when unset (auto)."""
        if self.batt_state == 'charging':
            return BATT_MAX_W
        if self.batt_state == 'discharging':
            return -BATT_MAX_W
        return decided

    def _tick_soc(self, t, pv_w, load_w, ov):
        """Stateful SoC: seed from the curve on first use, then integrate the
        effective battery power (the pin integrates the pin, the state force
        and the grid balance too — the SoC always follows what is served)."""
        m = self.batt_machine
        if m.soc is None and self.battery:
            m.seed(self.curve_soc(t))
        forced = None
        if self.batt_state:
            forced = self._forced_batt()
        elif ov['batt'] is not None:
            forced = ov['batt']
        elif ov['grid'] is not None:
            forced = self._grid_balanced(pv_w, load_w, ov, m.soc)
        if forced is not None:
            forced = self._batt_clamp(forced, t)
        return m.tick(t, pv_w, load_w, self.battery_kwh, self.battery, forced)

    def values(self):
        """Named physical values for the current tick — the profile decides
        which register (and encoding) each one lands on; a None value (e.g.
        the battery block with --battery off) is simply not served."""
        pv_w, home_w, batt_w, soc, _cloud, ov = self.effective()
        t = self.clock()
        # the device-status codes come from the profile's value map (the
        # entry's desc); the default profile keeps the classic semantics
        sm = self.profile.status_map or {'on-grid': 512, 'standby': 40960}
        if self.static:
            # the classic static demo: PV 4000 W, battery charging 1200 W at
            # 65 %, exporting 1500 W (home derives to 4300 W); overrides pin
            # the individual terms, the grid then follows the balance
            pinned = any(ov[k] is not None for k in ('pv', 'load', 'batt'))
            grid_w = pv_w - batt_w - home_w if pinned else -1500.0
            day_kwh, total_kwh = 12.42, 18212.42
            export_day = import_day = 0.0
            charge_t, discharge_t, charge_d, discharge_d = 250.0, 180.0, 12.34, 8.9
            v_string = 405.0
            status = float(sm.get('on-grid', 512))
        else:
            grid_w = pv_w - batt_w - home_w
            day_kwh = self.integrate_kwh(self.pv, 0.0, t)   # the actual (mppt-aware) curve
            total_kwh = 18200.0 + day_kwh
            pv_frac = pv_w / self.peak_w if self.peak_w else 0.0
            export_day = self.integrate_kwh(lambda u: max(self.pv(u) - self.batt(u) - self.home(u), 0.0), 0.0, t)
            import_day = self.integrate_kwh(lambda u: max(self.home(u) + self.batt(u) - self.pv(u), 0.0), 0.0, t)
            charge_d = self.integrate_kwh(lambda u: max(self.batt(u), 0.0), 0.0, t)
            discharge_d = self.integrate_kwh(lambda u: max(-self.batt(u), 0.0), 0.0, t)
            charge_t, discharge_t = 500.0 + charge_d, discharge_d
            v_string = 420.0 - 40.0 * pv_frac
            status = float(sm.get('on-grid', 512) if pv_w > 0 else sm.get('standby', 40960))
        east_on = self.mppt in ('both', 'east')
        west_on = self.mppt in ('both', 'west')
        if self.static:
            east_w = pv_w / 2.0 if self.mppt == 'both' else (pv_w if east_on else 0.0)
            west_w = pv_w / 2.0 if self.mppt == 'both' else (pv_w if west_on else 0.0)
        else:
            east_w = self.pv_string(t, 'east') if east_on else 0.0
            west_w = self.pv_string(t, 'west') if west_on else 0.0
        i_string = pv_w / 2.0 / max(v_string, 1.0)     # per-string current
        v_phases = self._grid_voltages(t)              # the grid machine's per-phase voltages
        home_phases = self.home_phases(t, home_w)      # the unbalanced home split
        # the inverter injects balanced thirds; the home draws its asymmetric
        # shares; the net per-phase power flows through the meter
        net_phases = [pv_w / 3.0 - batt_w / 3.0 - h for h in home_phases]
        i_out = [pv_w / 3.0 / max(v, 1.0) for v in v_phases]      # output phase currents
        i_meter = [abs(net) / max(v, 1.0) for net, v in zip(net_phases, v_phases)]
        v = {
            'pv-power': pv_w, 'pv-limit': pv_w, 'pv-dc-total': pv_w,
            'device-status': status,
            'device-temperature': self.temperature(t),
            'device-reactive-power': 0.0, 'device-power-factor': 1.0,
            'device-insulation': 970.0, 'grid-frequency': 50.0,
            'yield-total': total_kwh, 'yield-day': day_kwh,
            'grid-power': grid_w,
            'string-1-voltage': v_string if east_on else 0.0,
            'string-1-current': east_w / max(v_string, 1.0),
            'string-2-voltage': v_string if west_on else 0.0,
            'string-2-current': west_w / max(v_string, 1.0),
            'output-power-a': 4000.0, 'output-power-b': 4000.0, 'output-power-c': 4000.0,
            'output-voltage-a': v_phases[0], 'output-voltage-b': v_phases[1], 'output-voltage-c': v_phases[2],
            'output-current-a': i_out[0], 'output-current-b': i_out[1], 'output-current-c': i_out[2],
            'meter-status': 1.0, 'meter-mode': 1.0,
            'meter-voltage-a': v_phases[0], 'meter-voltage-b': v_phases[1], 'meter-voltage-c': v_phases[2],
            'meter-current-a': i_meter[0], 'meter-current-b': i_meter[1], 'meter-current-c': i_meter[2],
            'meter-reactive-power': 0.0, 'meter-power-factor': 1.0, 'meter-frequency': 50.0,
            'meter-export': METER_EXPORT_KWH + export_day,
            'meter-import': METER_IMPORT_KWH + import_day,
            'meter-power-a': grid_w / 3.0, 'meter-power-b': grid_w / 3.0, 'meter-power-c': grid_w / 3.0,
        }
        if self.battery:
            v.update({'battery-power': batt_w, 'battery-efficiency': 0.0,
                      'battery-soc': soc, 'battery-soc-reserve': soc,
                      'battery-charge-total': charge_t, 'battery-discharge-total': discharge_t,
                      'battery-charge-today': charge_d, 'battery-discharge-today': discharge_d})
        return v

    def registers(self):
        """The wire register map: the profile maps the named values (above)
        onto addresses and encodings. The 65000-65003 diagnostics block is
        not a device register — the cache synthesizes it and discovers the
        device family by the 0xCAFE magic — so the fake always mocks it."""
        regs = {}
        self.profile.encode(regs, self.values())
        for i, w in enumerate((0xCAFE, 1, 7, 4242)):
            regs[65000 + i] = w
        return regs
