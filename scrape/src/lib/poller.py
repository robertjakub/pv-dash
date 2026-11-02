#!/usr/bin/env python3
"""The poller: reads the inverter, sanity-checks and stores metric values (stdlib only)."""
import logging
import threading
import time

from .protocol import DIAG_BASE, DIAG_COUNT, DIAG_MAGIC, DIAG_MAX

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

    def reload(self, cfg):
        """Apply a freshly resolved config (SIGHUP); the socket reconnects on the next poll."""
        with self.lock:
            old = self.cfg
            self.cfg = cfg
        self.client.apply(host=cfg['host'], port=cfg['modbus_port'],
                          unit=cfg['unit'], timeout=cfg['timeout'])
        if (old['host'], old['modbus_port'], old['unit']) != (cfg['host'], cfg['modbus_port'], cfg['unit']):
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

    def poll_once(self):
        cfg = self.cfg
        try:
            pv_raw = self.client.read_i32(cfg['pv_register'])
            grid_raw = self.client.read_i32(cfg['grid_register'])
            battery = cfg['battery']
            batt_raw = self.client.read_i32(cfg['battery_register']) if battery else 0
            soc = self.client.read_registers(cfg['battery_soc_register'], 1)[0] / 10.0 if battery else None
            diag = self._read_diag()
        except Exception as e:
            self.client.close()
            self._mark_up(False, e)
            logger.debug('poll failed: %s', e)
            return
        pv = pv_raw * cfg['scale']
        grid = grid_raw * cfg['grid_scale']
        if cfg['grid_positive_import']:
            grid = -grid
        batt = batt_raw * cfg['scale']
        home = pv - batt - grid
        cap = cfg['max_kwp'] * 1000.0
        grid_cap = cfg['max_grid_kw'] * 1000.0
        discharge = max(-batt, 0.0)
        if battery:
            context = ' [poll: pv_raw=%d grid_raw=%d batt_raw=%d -> pv=%.0fW grid=%.0fW batt=%.0fW]' % (
                pv_raw, grid_raw, batt_raw, pv, grid, batt)
        else:
            context = ' [poll: pv_raw=%d grid_raw=%d -> pv=%.0fW grid=%.0fW]' % (pv_raw, grid_raw, pv, grid)
        err = None
        if pv < 0:
            err = 'PV power is negative: %.0f W (register %d raw %d)%s' % (
                pv, cfg['pv_register'], pv_raw, context)
        elif cfg['max_kwp'] > 0 and pv > cap:
            err = 'PV energy exceeds max_kwp: %.0f W > %.0f W (register %d raw %d)%s' % (
                pv, cap, cfg['pv_register'], pv_raw, context)
        elif cfg['max_kwp'] > 0 and grid > cap + discharge:
            err = 'Exported power exceeds max_kwp: %.0f W > %.0f W (register %d raw %d)%s' % (
                grid, cap + discharge, cfg['grid_register'], grid_raw, context)
        elif cfg['max_grid_kw'] > 0 and abs(grid) > grid_cap:
            err = 'Grid power exceeds max_grid_kw: %.0f W > %.0f W (register %d raw %d)%s' % (
                abs(grid), grid_cap, cfg['grid_register'], grid_raw, context)
        elif home < 0:
            err = 'Home power is negative: %.0f W (inconsistent readings)%s' % (home, context)
        with self.lock:
            self.error = err
            if err is None:
                names = self.spec.names
                self.values = {
                    names['pv']: pv,
                    names['grid']: grid,
                    names['export']: max(grid, 0.0),
                    names['import']: max(-grid, 0.0),
                    names['home']: home,
                    names['battery']: 1 if battery else 0,
                }
                if battery:
                    self.values[names['batt_net']] = batt
                    self.values[names['batt_charge']] = max(batt, 0.0)
                    self.values[names['batt_discharge']] = max(-batt, 0.0)
                    self.values[names['batt_soc']] = soc
                if diag is not None:
                    self.values[names['cache_device_up']] = diag[1]
                    self.values[names['cache_age']] = min(diag[2], DIAG_MAX)
                    self.values[names['cache_uptime']] = diag[3]
                self.last_poll = time.time()
            else:
                self.errors += 1
        if err is not None:
            logger.error('%s', err)
            return
        self._mark_up(True, None)
        logger.debug('poll ok: pv_raw=%d grid_raw=%d batt_raw=%d', pv_raw, grid_raw, batt_raw)

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
        time.sleep(min(max(0.05, interval), 86400.0))

    def snapshot(self):
        with self.lock:
            return self.up, dict(self.values), self.last_poll, self.errors

    def error_state(self):
        with self.lock:
            return self.error
