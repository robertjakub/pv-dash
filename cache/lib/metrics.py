#!/usr/bin/env python3
"""The cache's own Prometheus endpoint: a small /metrics on its own port,
gated (off by default, and the bearer token is mandatory when on).
Serves the cache's self-observability in the
Prometheus text format: the hit/miss counters, the poll health and age, the
poll-cycle durations, the client count, the uplink session counters and the
per-block poll latency/errors — without depending on the scraper's
`scraper_cache_*` export path. Requests need
`Authorization: Bearer <token>` (the same scheme the scraper speaks).
The gated endpoint skeleton (the 401/404/503, the caps, the thread
start/stop) is the family's common/metrics_server."""
import logging
import time

from common.config import acl_admits
from common.metrics_server import MetricsServer as _MetricsServer
from common.metrics_server import describe_metrics

logger = logging.getLogger('modbus-cache')


class MetricsServer(_MetricsServer):
    """A tiny Prometheus text-endpoint for the cache itself. The master
    switch is the live `metrics-server` setting (default off); the bind
    address is --metrics-listen HOST:PORT. Caps (F13 round):
    --metrics-max-clients (immediate 503 past it), --metrics-client-timeout
    (0 = the built-in 5 s slowloris cap), --metrics-max-conn-per-ip; 0 = no
    per-IP limit. Beside the caps the metrics/acl gate checks the peer IP
    at accept (the acl/connect reading, the scraper's metrics/acl shape):
    a client off the ACL is closed without a reply — nothing was parsed to
    answer. The gate reads through the proxy per connection: one live
    state, the set/unset swap needs no push here."""

    REALM = 'modbus-cache'
    LOG_NAME = 'modbus-cache'

    def __init__(self, proxy, listen, token=None, started=0.0, max_clients=64,
                 client_timeout=5.0, max_per_ip=0):
        super().__init__(listen, token=token, started=started, max_clients=max_clients,
                         client_timeout=client_timeout, max_per_ip=max_per_ip)
        self.proxy = proxy

    def acl_allows(self, ip):
        return acl_admits(self.proxy.metrics_acl, ip)

    def acl_refused(self, request, client_address):
        logger.info('connection rejected: %s:%d not on the metrics ACL', *client_address[:2])
        self._http.shutdown_request(request)

    def snapshot(self):
        p = self.proxy
        c = p.cache
        now = time.monotonic()
        with c.lock:
            words = len(c.regs)
            oldest = max((time.time() - t for t in c.ts.values()), default=None)
        fc3 = sum(1 for r in c.ranges if r[0] == 3)
        fc4 = len(c.ranges) - fc3
        mean = p.poll_secs_sum / p.poll_count if p.poll_count else 0.0
        u = p.upstream
        blocks = []
        for fc, start, count, _leaves in p.blocks:
            s = p.block_stats.get((fc, start, count))
            blocks.append((fc, start, count,
                           None if s is None else (s['last'], s['sum'] / s['ok_n'] if s['ok_n'] else None,
                                                   s['max'], s['fails'], s['last_err'])))
        return {
            'uptime': int(now - (p.started or now)),
            'hits': p.cache_hits, 'misses': p.cache_misses,
            'poll_up': 1 if p.poll_ok else 0,
            'last_poll_age': None if p.last_ok is None else max(0, int(now - p.last_ok)),
            'words': words, 'ranges': len(c.ranges), 'fc4': fc4,
            'oldest': oldest, 'clients': p.client_count,
            'poll_last': p.poll_secs_last, 'poll_mean': mean, 'poll_max': p.poll_secs_max,
            'uplink_up': 1 if u.sock is not None else 0,
            'uplink_connects': u.connects, 'uplink_exchanges': u.exchanges,
            'uplink_errors': u.errors, 'uplink_bytes_in': u.bytes_in, 'uplink_bytes_out': u.bytes_out,
            'uplink_err_age': None if u.last_error_at is None else now - u.last_error_at,
            'uplink_blocks': blocks,
        }

    def render(self):
        st = self.snapshot()
        rows = [
            '# HELP modbus_cache_uptime_seconds The modbus-cache process uptime.',
            '# TYPE modbus_cache_uptime_seconds gauge',
            'modbus_cache_uptime_seconds %d' % st['uptime'],
            '# HELP modbus_cache_poll_up 1 = the last poll cycle talked to the device.',
            '# TYPE modbus_cache_poll_up gauge',
            'modbus_cache_poll_up %d' % st['poll_up'],
            '# HELP modbus_cache_hits_total Cache hits (reads served without the device).',
            '# TYPE modbus_cache_hits_total counter',
            'modbus_cache_hits_total %d' % st['hits'],
            '# HELP modbus_cache_misses_total Cache misses (reads forwarded to the device).',
            '# TYPE modbus_cache_misses_total counter',
            'modbus_cache_misses_total %d' % st['misses'],
            '# HELP modbus_cache_ranges The register ranges in the map (fc3/fc4 labels).',
            '# TYPE modbus_cache_ranges gauge',
            'modbus_cache_ranges{fc="3"} %d' % (st['ranges'] - st['fc4']),
            'modbus_cache_ranges{fc="4"} %d' % st['fc4'],
            '# HELP modbus_cache_words Cached register words.',
            '# TYPE modbus_cache_words gauge',
            'modbus_cache_words %d' % st['words'],
            '# HELP modbus_cache_clients Connected Modbus clients.',
            '# TYPE modbus_cache_clients gauge',
            'modbus_cache_clients %d' % st['clients'],
            '# HELP modbus_cache_poll_duration_seconds The last poll cycle duration.',
            '# TYPE modbus_cache_poll_duration_seconds gauge',
            'modbus_cache_poll_duration_seconds %g' % st['poll_last'],
            '# HELP modbus_cache_poll_duration_mean_seconds The mean poll cycle duration.',
            '# TYPE modbus_cache_poll_duration_mean_seconds gauge',
            'modbus_cache_poll_duration_mean_seconds %g' % st['poll_mean'],
            '# HELP modbus_cache_poll_duration_max_seconds The longest poll cycle duration so far.',
            '# TYPE modbus_cache_poll_duration_max_seconds gauge',
            'modbus_cache_poll_duration_max_seconds %g' % st['poll_max'],
        ]
        if st['last_poll_age'] is not None:
            rows += [
                '# HELP modbus_cache_last_poll_age_seconds Seconds since the last successful poll cycle.',
                '# TYPE modbus_cache_last_poll_age_seconds gauge',
                'modbus_cache_last_poll_age_seconds %d' % st['last_poll_age'],
            ]
        if st['oldest'] is not None:
            rows += [
                '# HELP modbus_cache_age_seconds The age of the oldest cached word.',
                '# TYPE modbus_cache_age_seconds gauge',
                'modbus_cache_age_seconds %g' % st['oldest'],
            ]
        rows += [
            '# HELP modbus_cache_uplink_up 1 = the upstream socket to the inverter is connected.',
            '# TYPE modbus_cache_uplink_up gauge',
            'modbus_cache_uplink_up %d' % st['uplink_up'],
            '# HELP modbus_cache_uplink_connects_total Successful upstream connects (2 = one reconnect).',
            '# TYPE modbus_cache_uplink_connects_total counter',
            'modbus_cache_uplink_connects_total %d' % st['uplink_connects'],
            '# HELP modbus_cache_uplink_exchanges_total Completed upstream request/reply exchanges.',
            '# TYPE modbus_cache_uplink_exchanges_total counter',
            'modbus_cache_uplink_exchanges_total %d' % st['uplink_exchanges'],
            '# HELP modbus_cache_uplink_errors_total Failed upstream exchanges (timeout, reset, refused, bad frame).',
            '# TYPE modbus_cache_uplink_errors_total counter',
            'modbus_cache_uplink_errors_total %d' % st['uplink_errors'],
            '# HELP modbus_cache_uplink_bytes_total Upstream bytes by direction.',
            '# TYPE modbus_cache_uplink_bytes_total counter',
            'modbus_cache_uplink_bytes_total{dir="in"} %d' % st['uplink_bytes_in'],
            'modbus_cache_uplink_bytes_total{dir="out"} %d' % st['uplink_bytes_out'],
        ]
        if st['uplink_err_age'] is not None:
            rows += [
                '# HELP modbus_cache_uplink_last_error_age_seconds Seconds since the last upstream error.',
                '# TYPE modbus_cache_uplink_last_error_age_seconds gauge',
                'modbus_cache_uplink_last_error_age_seconds %g' % st['uplink_err_age'],
            ]
        rows += [
            '# HELP modbus_cache_uplink_block_up 1 = the poll block\'s last attempt succeeded.',
            '# TYPE modbus_cache_uplink_block_up gauge',
            '# HELP modbus_cache_uplink_block_latency_seconds The block\'s last poll round-trip (absent while failing).',
            '# TYPE modbus_cache_uplink_block_latency_seconds gauge',
            '# HELP modbus_cache_uplink_block_latency_mean_seconds The block\'s mean poll round-trip (ok attempts).',
            '# TYPE modbus_cache_uplink_block_latency_mean_seconds gauge',
            '# HELP modbus_cache_uplink_block_latency_max_seconds The block\'s longest poll round-trip so far.',
            '# TYPE modbus_cache_uplink_block_latency_max_seconds gauge',
            '# HELP modbus_cache_uplink_block_fails_total Failed poll attempts of the block.',
            '# TYPE modbus_cache_uplink_block_fails_total counter',
        ]
        for fc, start, count, s in st['uplink_blocks']:
            label = '{fc="%d",start="%d",count="%d"}' % (fc, start, count)
            if s is None:                      # the plan block has not been polled yet
                rows.append('modbus_cache_uplink_block_up%s 0' % label)
                continue
            last, mean_b, max_b, fails, last_err = s
            rows.append('modbus_cache_uplink_block_up%s %d' % (label, 1 if last_err is None else 0))
            rows.append('modbus_cache_uplink_block_fails_total%s %d' % (label, fails))
            if last_err is None:
                rows.append('modbus_cache_uplink_block_latency_seconds%s %g' % (label, last))
                rows.append('modbus_cache_uplink_block_latency_mean_seconds%s %g' % (label, mean_b))
                rows.append('modbus_cache_uplink_block_latency_max_seconds%s %g' % (label, max_b))
        return '\n'.join(rows) + '\n'
