#!/usr/bin/env python3
"""The poller: reads the inverter, sanity-checks and stores metric values (stdlib only).

The poll walks the block plan — the cache's gold planner
(common/modbus/blocks.py) merges the profile's source ranges into as few
Modbus reads as possible, the read delay paces between blocks, a failed
block splits to its leaves (a bad register must not starve its pooled
neighbors) and the ok replies slice back into the sources. The per-block
tally feeds `show uplink`."""
import logging
import struct
import threading
import time
from collections import deque

from common.modbus import DeviceError, is_busy_error, ReplyTimeout
from common.modbus.blocks import BIT_READ_FUNCS, block_stat, build_blocks, span
from .expr import evaluate
from .statics import DIAG_BASE, DIAG_COUNT, DIAG_MAGIC, DIAG_MAX

logger = logging.getLogger('scraper')

HARD_SOURCES = ('pv-power', 'grid-power', 'battery-power', 'battery-soc')


def _words_for(typ):
    """The words one source read covers: bits and 16-bit types take one,
    the 32-bit quartet (both word orders) two."""
    return 1 if typ in ('bit', 'i16', 'u16') else 2


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
        self.wake = threading.Event()   # `request poll now` on the control server: the wait ends immediately
        # the poll plan (the cache's gold shape): the blocks, the per-block
        # tally (`show uplink`), the leaf -> source names map
        self.blocks = []
        self.block_stats = {}
        self.leaf_sources = {}
        self.plan_gen = 0
        self.rebuild_plan()

    def rebuild_plan(self):
        """(Re)build the poll plan from the resolved sources: the ranges
        merged into blocks per function code, the leaf -> source names map
        beside it. Runs at start and whenever the sources or the merge gap
        change (a live set modbus-profile/metrics-spec/metrics-prefix/modbus-merge-gap)."""
        with self.lock:
            ranges = []
            leaf_sources = {}
            for name, src in self.cfg['sources'].items():
                leaf = (src['fc'], src['register'], _words_for(src['type']))
                ranges.append(leaf)
                leaf_sources.setdefault(leaf, []).append(name)
            self.blocks = build_blocks(ranges, self.cfg.get('modbus_merge_gap', 8))
            self.leaf_sources = leaf_sources
            self.block_stats = {}
            self.plan_gen += 1
        logger.info('poll plan: %d block(s) over %d source(s)', len(self.blocks), len(leaf_sources))
        for i, (fc, start, count, leaves) in enumerate(self.blocks, 1):
            names = ', '.join(n for lf in leaves for n in leaf_sources.get(lf, ()))
            logger.info('  block %d: fc%d %d:%d [ %s ]', i, fc, start, count, names)

    def reload(self, cfg):
        """Apply a freshly resolved config (SIGHUP); the socket reconnects on the next poll."""
        with self.lock:
            old = self.cfg
            self.cfg = cfg
        self.client.apply(host=cfg['host'], port=cfg['modbus_port'],
                          unit=cfg['modbus_unit'], timeout=cfg['modbus_timeout'],
                          auth=cfg.get('auth'), auth_key=cfg.get('auth_key'))
        if (old['host'], old['modbus_port'], old['modbus_unit']) != (cfg['host'], cfg['modbus_port'], cfg['modbus_unit']):
            self.client.close()
        self.rebuild_plan()

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

    def _read_block(self, fc, start, count):
        """One plan block's read: FC1/FC2 unpack to 0/1 per address, FC3/FC4
        return words — the addresses are profile-space, the client's offset
        applies on the wire."""
        if fc in BIT_READ_FUNCS:
            return self.client.read_bits(start, count, fc=fc)
        return self.client.read_registers(start, count, fc=fc)

    def _decode(self, words, src):
        """The source's decode from its block-reply words: the profile's
        type ladder, then the gain (wire value = physical x gain)."""
        typ = src['type']
        if typ == 'bit':
            raw = words[0]
        elif typ in ('i16', 'u16'):
            raw = words[0]
            if typ == 'i16' and raw >= 0x8000:
                raw -= 0x10000
        elif typ in ('f32', 'f32swap'):
            w0, w1 = words[0], words[1]
            order = (w1, w0) if typ == 'f32swap' else (w0, w1)   # swap = the lo word first
            raw = struct.unpack('>f', struct.pack('>HH', *order))[0]
        else:                       # i32/u32 and the swapped word orders
            w0, w1 = words[0], words[1]
            if typ in ('i32swap', 'u32swap'):
                w0, w1 = w1, w0
            raw = struct.unpack('>i', struct.pack('>HH', w0, w1))[0]
            if typ in ('u32', 'u32swap') and raw < 0:
                raw += 0x100000000
        return raw / src['gain']

    def poll_once(self):
        cfg = self.cfg
        started = time.monotonic()
        delay = cfg.get('modbus_read_delay', 0.0)
        plan_gen = self.plan_gen
        pending = deque(self.blocks)
        done = []
        ok_words = {}               # leaf -> the block reply's words for the leaf
        failed = {}                 # leaf -> the terminal read exception
        retried = set()
        first = True
        paced = True   # the read delay paces a healthy device; failures sweep unpaced
        while pending:
            fc, start, count, leaves = pending.popleft()
            if first:
                first = False
            elif delay and paced:
                time.sleep(delay)
            t0 = time.monotonic()
            try:
                words = self._read_block(fc, start, count)
                block_stat(self.block_stats, (fc, start, count), time.monotonic() - t0)
                paced = True
                for lf in leaves:
                    ok_words[lf] = words[lf[1] - start: lf[1] - start + lf[2]]
                done.append((fc, start, count, leaves))
            except Exception as e:
                paced = False
                soft = is_busy_error(e) or isinstance(e, ReplyTimeout)
                if soft and (fc, start, count) not in retried:
                    # the device is alive and the session is healthy — wait
                    # a beat and retry the same query once per cycle ON THE
                    # SAME CONNECTION (a reconnect would only buy another
                    # lost first query): the dongle's 'not now' (exception
                    # 06) or its lost first query (a fresh session's first
                    # exchange draws silence — the mbpoll repro)
                    retried.add((fc, start, count))
                    if isinstance(e, ReplyTimeout):
                        logger.info('the device timed out waiting to retry fc%d %d:%d', fc, start, count)
                    else:
                        logger.info('the device is busy waiting to retry fc%d %d:%d', fc, start, count)
                    time.sleep(delay or 1.0)
                    pending.appendleft((fc, start, count, leaves))
                    continue
                if soft:
                    # still away: not an error — the cycle keeps its last
                    # words (no leaf poisoning, no split; the device, not
                    # the range, is the problem), the next cycle retries
                    block_stat(self.block_stats, (fc, start, count), time.monotonic() - t0, e)
                    logger.debug('the device is away fc%d %d:%d keeps last words', fc, start, count)
                    done.append((fc, start, count, leaves))
                elif isinstance(e, DeviceError) and len(leaves) > 1:
                    # the device's own shape answer (illegal function/address/
                    # value): the block straddles a map hole or exceeds the
                    # device's count — split in half, the halves re-queue this
                    # cycle. The split STAYS: it is the learned shape of the
                    # device, re-probing the merged block would only buy the
                    # same refusal (reload/restart rebuilds the plan).
                    mid = len(leaves) // 2
                    left, right = leaves[:mid], leaves[mid:]
                    logger.debug('splitting block fc%d %d:%d after failure (%s)', fc, start, count, e)
                    pending.appendleft((fc, right[0][1], span(right), right))
                    pending.appendleft((fc, left[0][1], span(left), left))
                else:
                    # transport or garbage: connection-scoped, the halves
                    # would learn nothing — the block stays WHOLE in the
                    # plan and the leaves fail honestly until the next good
                    # cycle re-polls the full block
                    block_stat(self.block_stats, (fc, start, count), time.monotonic() - t0, e)
                    for lf in leaves:
                        failed[lf] = e
                    done.append((fc, start, count, leaves))
        if plan_gen == self.plan_gen:   # the plan still owns the walk (no live rebuild mid-cycle)
            self.blocks = done
            live = {(fc, s, c) for fc, s, c, _ in done}
            self.block_stats = {k: v for k, v in self.block_stats.items() if k in live}
        # the sources decode off the ok replies; a failed leaf serving a
        # hard source fails the cycle, a soft one keeps its metric absent
        hard_err = None
        for lf, e in failed.items():
            for name in self.leaf_sources.get(lf, ()):
                if name in HARD_SOURCES:
                    if hard_err is None:
                        hard_err = e
                else:
                    logger.warning('read of %s (%s) failed, the metric stays absent (%s)',
                                   name, cfg['sources'][name]['metric'], e)
        if hard_err is not None:
            self._mark_up(False, hard_err)
            logger.debug('poll failed: %s', hard_err)
            self._account_cycle(started)
            return
        pv_raw = grid_raw = None
        batt_raw = 0
        soc = None
        extras = {}
        raws = {}                       # the expression input name (the spec key) -> the read
        for lf, words in ok_words.items():
            for name in self.leaf_sources.get(lf, ()):
                src = cfg['sources'][name]
                value = self._decode(words, src)
                if name == 'pv-power':
                    pv_raw = value
                elif name == 'grid-power':
                    grid_raw = value
                elif name == 'battery-power':
                    batt_raw = value
                elif name == 'battery-soc':
                    soc = value
                else:
                    extras[src['metric']] = value
                    key = self.spec.profile_inputs.get(name)
                    if key is not None:
                        raws[key] = value
        if pv_raw is None or grid_raw is None:
            # unreachable: build_sources refuses a spec without the power pair —
            # the guard keeps the power math honest all the same
            self._mark_up(False, 'the power sources did not poll')
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
        context = ' [poll: pv_raw=%d grid_raw=%d batt_raw=%d -> pv=%.0fW grid=%.0fW batt=%.0fW]' % (
            pv_raw, grid_raw, batt_raw, pv, grid, batt)
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
        diag = self._read_diag()   # the cache-diag probe rides the cycle's tail, outside the values lock
        with self.lock:
            self.error = err
            if err is None:
                metric = {pn: src['metric'] for pn, src in cfg['sources'].items()}
                values = {
                    metric['pv-power']: pv,
                    metric['grid-power']: grid,
                }
                if 'battery-power' in metric:
                    values[metric['battery-power']] = batt
                if 'battery-soc' in metric:
                    values[metric['battery-soc']] = soc
                values.update(extras)
                # the compute metrics: the spec's expressions over the poll's
                # reads — an unavailable input (a failed extras read, the
                # unbound soc) or a failed eval keeps the metric absent
                inputs = {'pv': pv, 'grid': grid, 'batt': batt}
                if soc is not None:
                    inputs['soc'] = soc
                inputs.update(raws)
                for name, (fn, when) in self.spec.compute.items():
                    try:
                        if when is not None and not evaluate(when, inputs):
                            continue
                        values[name] = evaluate(fn, inputs)
                    except Exception as e:
                        logger.warning('compute %s stays absent (%s)', name, e)
                if diag is not None:
                    values['scraper_cache_device_up'] = diag[1]
                    values['scraper_cache_age_seconds'] = min(diag[2], DIAG_MAX)
                    values['scraper_cache_uptime_seconds'] = diag[3]
                self.values = values
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
            interval = self.cfg['modbus_interval']
        # clamp: a huge interval would overflow time.sleep and kill the poll thread
        self.wake.wait(timeout=min(max(0.05, interval), 86400.0))
        self.wake.clear()

    def snapshot(self):
        with self.lock:
            return self.up, dict(self.values), self.last_poll, self.errors

    def error_state(self):
        with self.lock:
            return self.error
