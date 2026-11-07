#!/usr/bin/env python3
"""The poller: reads the inverter, sanity-checks and stores metric values (stdlib only)."""
import logging
import threading
import time

from .statics import DIAG_BASE, DIAG_COUNT, DIAG_MAGIC, DIAG_MAX

logger = logging.getLogger('scraper')


class Scraper:
    """Holds the latest metric values; one poll thread refreshes them."""

    def __init__(self, cfg, client, spec):
        self.cfg = cfg
        self.client = client
        self.spec = spec
        self.lock = threading.Lock()
        self.values = {}
        self.error = None
        self.up = False
        self.last_poll = 0.0
        self.errors = 0
        # the poll-cycle latency (the slow-dongle gauges: scraper_poll_duration_*)
        self.poll_secs_last = 0.0
        self.poll_secs_sum = 0.0
        self.poll_secs_max = 0.0
        self.poll_count = 0
        self.wake = threading.Event()   # `poll now` on the control server: the wait ends immediately

    def reload(self, cfg):
        """Apply a freshly resolved config (SIGHUP); the socket reconnects on the next poll."""
        with self.lock:
            old = self.cfg
            self.cfg = cfg
        self.client.apply(host=cfg['host'], port=cfg['modbus_port'],
                          unit=cfg['modbus_unit'], timeout=cfg['timeout'],
                          auth=cfg.get('auth'), auth_key=cfg.get('auth_key'))
        if (old['host'], old['modbus_port'], old['modbus_unit']) != (cfg['host'], cfg['modbus_port'], cfg['modbus_unit']):
            self.client.close()

    def _mark_up(self, ok, err):
        with self.lock:
            was = self.up
            if ok:
                self.up = True
            else:
                self.up = False
                self.errors += 1
        if was != ok:
            if ok:
                logger.info('inverter %s:%d reachable', self.cfg['host'], self.cfg['modbus_port'])
            else:
                logger.warning('inverter %s:%d unreachable: %s', self.cfg['host'],
                               self.cfg['modbus_port'], err)

    def _read(self, profile_name):
        """Read one source: the profile-declared type and function code on
        the wire (fc 3 = holding, 4 = input), decoded by the profile's gain
        (wire value = physical x gain)."""
        src = self.cfg['sources'][profile_name]
        reg, typ, fc = src['register'], src['type'], src.get('fc', 3)
        if typ in ('i32', 'u32'):
            raw = self.client.read_i32(reg, fc=fc)
            if typ == 'u32' and raw < 0:
                raw += 0x100000000
        else:
            raw = self.client.read_registers(reg, 1, fc=fc)[0]
            if typ == 'i16' and raw >= 0x8000:
                raw -= 0x10000
        return raw / src['gain']

    def poll_once(self):
        cfg = self.cfg
        started = time.monotonic()
        try:
            pv_raw = self._read('pv-power')
            grid_raw = self._read('grid-power')
            battery = cfg['battery']
            batt_raw = self._read('battery-power') if battery else 0
            soc = self._read('battery-soc') if battery else None
            diag = self._read_diag()
        except Exception as e:
            self.client.close()
            self._mark_up(False, e)
            logger.debug('poll failed: %s', e)
            self._account_cycle(started)
            return
        self._account_cycle(started)
        pv, grid = pv_raw, grid_raw
        if cfg['grid_positive_import']:
            grid = -grid
        batt = batt_raw
        home = pv - batt - grid
        cap = cfg['max_kwp'] * 1000.0
        grid_cap = cfg['max_grid_kw'] * 1000.0
        discharge = max(-batt, 0.0)
        if battery:
            context = ' [poll: pv_raw=%d grid_raw=%d batt_raw=%d -> pv=%.0fW grid=%.0fW batt=%.0fW]' % (
                pv_raw, grid_raw, batt_raw, pv, grid, batt)
        else:
            context = ' [poll: pv_raw=%d grid_raw=%d -> pv=%.0fW grid=%.0fW]' % (pv_raw, grid_raw, pv, grid)
        pv_reg = cfg['sources']['pv-power']['register']
        grid_reg = cfg['sources']['grid-power']['register']
        err = None
        if pv < 0:
            err = 'PV power is negative: %.0f W (register %d raw %d)%s' % (
                pv, pv_reg, pv_raw, context)
        elif cfg['max_kwp'] > 0 and pv > cap:
            err = 'PV energy exceeds max_kwp: %.0f W > %.0f W (register %d raw %d)%s' % (
                pv, cap, pv_reg, pv_raw, context)
        elif cfg['max_kwp'] > 0 and grid > cap + discharge:
            err = 'Exported power exceeds max_kwp: %.0f W > %.0f W (register %d raw %d)%s' % (
                grid, cap + discharge, grid_reg, grid_raw, context)
        elif cfg['max_grid_kw'] > 0 and abs(grid) > grid_cap:
            err = 'Grid power exceeds max_grid_kw: %.0f W > %.0f W (register %d raw %d)%s' % (
                abs(grid), grid_cap, grid_reg, grid_raw, context)
        elif home < 0:
            err = 'Home power is negative: %.0f W (inconsistent readings)%s' % (home, context)
        with self.lock:
            self.error = err
            if err is None:
                metric = {pn: src['metric'] for pn, src in cfg['sources'].items()}
                prefix = cfg.get('metric_prefix') or 'huawei'
                self.values = {
                    metric['pv-power']: pv,
                    metric['grid-power']: grid,
                    '%s_grid_export_watts' % prefix: max(grid, 0.0),
                    '%s_grid_import_watts' % prefix: max(-grid, 0.0),
                    '%s_home_consumption_watts' % prefix: home,
                    'scraper_battery': 1 if battery else 0,
                }
                if battery and 'battery-power' in metric:
                    self.values[metric['battery-power']] = batt
                    self.values['%s_battery_charge_watts' % prefix] = max(batt, 0.0)
                    self.values['%s_battery_discharge_watts' % prefix] = max(-batt, 0.0)
                    self.values[metric['battery-soc']] = soc
                if diag is not None:
                    self.values['scraper_cache_device_up'] = diag[1]
                    self.values['scraper_cache_age_seconds'] = min(diag[2], DIAG_MAX)
                    self.values['scraper_cache_uptime_seconds'] = diag[3]
                self.last_poll = time.time()
            else:
                self.errors += 1
        if err is not None:
            logger.error('%s', err)
            return
        self._mark_up(True, None)
        logger.debug('poll ok: pv_raw=%d grid_raw=%d batt_raw=%d', pv_raw, grid_raw, batt_raw)

    def _account_cycle(self, started):
        """One poll cycle's latency: last/mean/max — the poll-latency gauges
        (a slow dongle shows up here before the freshness gap does)."""
        secs = time.monotonic() - started
        with self.lock:
            self.poll_secs_last = secs
            self.poll_secs_sum += secs
            self.poll_count += 1
            self.poll_secs_max = max(self.poll_secs_max, secs)

    def _read_diag(self):
        """Auto-detect a modbus-cache in front of the device (4 diag registers, magic-checked).

        Against the raw inverter this read just raises (undefined address), which is
        swallowed at DEBUG — the diag metrics then stay absent instead of lying.
        """
        try:
            words = self.client.read_registers(DIAG_BASE, DIAG_COUNT)
        except Exception as e:
            logger.debug('cache diag read: not available (%s)', e)
            return None
        if words[0] != DIAG_MAGIC:
            logger.debug('cache diag read: magic mismatch 0x%04x, ignoring', words[0])
            return None
        logger.debug('cache diag: device %s, cache age %ss, cache uptime %ss',
                     'up' if words[1] else 'DOWN',
                     'n/a' if words[2] == DIAG_MAX else words[2], words[3])
        return words

    def poll_loop(self):
        while True:
            try:
                self.poll_once()
            except Exception as e:
                logger.error('poll cycle crashed (%s), retrying next cycle', e)
            self.cfg_interval_wait()

    def cfg_interval_wait(self):
        with self.lock:
            interval = self.cfg['interval']
        # clamp: a huge interval would overflow time.sleep and kill the poll thread
        self.wake.wait(timeout=min(max(0.05, interval), 86400.0))
        self.wake.clear()

    def snapshot(self):
        with self.lock:
            return self.up, dict(self.values), self.last_poll, self.errors

    def error_state(self):
        with self.lock:
            return self.error
