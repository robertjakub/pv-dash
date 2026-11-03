#!/usr/bin/env python3
"""The simulated day (or frozen/static) values: curves, runtime overrides,
the battery machine wiring and the register-map assembly."""
import math
import random
import threading
import time

from .battery import BATT_GRID_MARGIN_W, BATT_MAX_W, BATT_STANDBY_W, BatteryMachine
from .profile import load_profile, resolve_profile

SUNRISE, SUNSET = 6.0, 18.0

# Cloud state machines (Ornstein-Uhlenbeck: mean-reverting random walk over
# the simulated clock — time-lapse jumps move the clouds, a frozen clock
# freezes them): mode -> (mean, theta/h, sigma/sqrt(h), lo, hi)
CLOUD_MACHINES = {
    'autumn': (0.45, 2.5, 0.60, 0.05, 0.95),   # passing clouds, quick swings
    'winter': (0.75, 0.8, 0.35, 0.10, 1.00),   # heavy overcast spells, slow breaks
}

# lifetime meter totals the demo starts from (kWh)
METER_EXPORT_KWH = 12500.0
METER_IMPORT_KWH = 9800.0

# Runtime-controllable knobs (see the control server): None = follow the
# simulation, a number = pinned. `cloud` scales PV (0 = clear, 1 = dark).
OVERRIDE_KEYS = ('pv', 'load', 'batt', 'soc', 'cloud')


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
        self.cloud_mode = None          # None = clear sky; 'autumn'/'winter' = the machine
        self._cloud_rng = random.Random(seed)
        self._cloud_value = 0.0
        self._cloud_t = None

    def set_profile(self, profile_map):
        """Swap the register map (SIGHUP); clients serving from the old map
        see the new one on the next poll."""
        with self._lock:
            self.profile = profile_map

    def set_cloud_mode(self, mode):
        """Enter a cloud state machine (autumn/winter) or None for a clear sky."""
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
        return 'auto'

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
        cloud = ov['cloud'] if ov['cloud'] is not None else self._cloud(t)
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

    def values(self):
        """Named physical values for the current tick — the profile decides
        which register (and encoding) each one lands on; a None value (e.g.
        the battery block with --battery off) is simply not served."""
        pv_w, home_w, batt_w, soc, _cloud, ov = self.effective()
        t = self.clock()
        # the device-status codes come from the profile's value map (the
        # entry's desc); the sun2000 defaults keep the classic semantics
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
            if t <= SUNRISE:
                day_kwh = 0.0
            elif t < SUNSET:
                day_kwh = (self.peak_w / 1000.0) * (SUNSET - SUNRISE) / math.pi * (1 - math.cos(math.pi * (t - SUNRISE) / (SUNSET - SUNRISE)))
            else:
                day_kwh = 2.0 * (self.peak_w / 1000.0) * (SUNSET - SUNRISE) / math.pi
            total_kwh = 18200.0 + day_kwh
            pv_frac = pv_w / self.peak_w if self.peak_w else 0.0
            export_day = self.integrate_kwh(lambda u: max(self.pv(u) - self.batt(u) - self.home(u), 0.0), 0.0, t)
            import_day = self.integrate_kwh(lambda u: max(self.home(u) + self.batt(u) - self.pv(u), 0.0), 0.0, t)
            charge_d = self.integrate_kwh(lambda u: max(self.batt(u), 0.0), 0.0, t)
            discharge_d = self.integrate_kwh(lambda u: max(-self.batt(u), 0.0), 0.0, t)
            charge_t, discharge_t = 500.0 + charge_d, discharge_d
            v_string = 420.0 - 40.0 * pv_frac
            status = float(sm.get('on-grid', 512) if pv_w > 0 else sm.get('standby', 40960))
        i_string = pv_w / 2.0 / max(v_string, 1.0)     # per-string current
        i_out = pv_w / 3.0 / 230.0                     # output phase current
        i_meter = abs(grid_w) / 3.0 / 230.0            # meter phase current
        v = {
            'pv-power': pv_w, 'pv-limit': pv_w, 'pv-dc-total': pv_w,
            'device-status': status,
            'device-temperature': self.temperature(t),
            'device-reactive-power': 0.0, 'device-power-factor': 1.0,
            'device-insulation': 970.0, 'grid-frequency': 50.0,
            'yield-total': total_kwh, 'yield-day': day_kwh,
            'grid-power': grid_w,
            'string-1-voltage': v_string, 'string-2-voltage': v_string,
            'string-1-current': i_string, 'string-2-current': i_string,
            'output-power-a': 4000.0, 'output-power-b': 4000.0, 'output-power-c': 4000.0,
            'output-voltage-a': 230.0, 'output-voltage-b': 230.0, 'output-voltage-c': 230.0,
            'output-current-a': i_out, 'output-current-b': i_out, 'output-current-c': i_out,
            'meter-status': 1.0, 'meter-mode': 1.0,
            'meter-voltage-a': 230.0, 'meter-voltage-b': 230.0, 'meter-voltage-c': 230.0,
            'meter-current-a': i_meter, 'meter-current-b': i_meter, 'meter-current-c': i_meter,
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
