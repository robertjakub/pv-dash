#!/usr/bin/env python3
"""The cache's own Prometheus endpoint: a small /metrics on its own port,
gated (off by default, the bearer token mandatory beyond loopback — the
F13 posture, the scraper's refusal the family's golden shape).
Serves the cache's self-observability in the
Prometheus text format: the hit/miss counters, the poll health and age, the
poll-cycle durations, the client count, the uplink session counters and the
per-block poll latency/errors — without depending on the scraper's
`scraper_cache_*` export path. Requests need
`Authorization: Bearer <token>` (the same scheme the scraper speaks).
The gated endpoint skeleton (the 401/404/503, the caps, the thread
start/stop) is the family's common/metrics_server."""
import time

from common.settings.config import acl_admits
from common.serve.metrics_server import MetricsServer as _MetricsServer
from common.serve.metrics_server import describe_metrics, metric


class MetricsServer(_MetricsServer):
    """A tiny Prometheus text-endpoint for the cache itself. The master
    switch is the live `metrics-server` setting (default off); the bind
    address is --metrics-listen HOST:PORT. Caps (F13 round):
    --metrics-max-clients (immediate 503 past it), --metrics-client-timeout
    (0 = the built-in 5 s slowloris cap), --metrics-max-conn-per-ip; 0 = no
    per-IP limit. Ahead of the caps the metrics/acl gate checks the peer
    IP at accept (the acl/connect reading, the scraper's metrics/acl
    shape): a client off the ACL is closed without a reply — nothing was
    parsed to answer, the caps never see the peer. The gate reads through
    the proxy per connection: one live state, the set/clear swap needs no
    push here."""

    REALM = 'modbus-cache'
    LOG_NAME = 'modbus-cache'

    def __init__(self, proxy, listen, token=None, started=0.0, max_clients=64,
                 client_timeout=5.0, max_per_ip=0):
        super().__init__(listen, token=token, started=started, max_clients=max_clients,
                         client_timeout=client_timeout, max_per_ip=max_per_ip)
        self.proxy = proxy

    def acl_allows(self, ip):
        return acl_admits(self.proxy.metrics_acl, ip)

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
            'write_refused': p.write_refused,
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
            *metric('modbus_cache_uptime_seconds', 'The modbus-cache process uptime.', 'gauge',
                    '%d' % st['uptime']),
            *metric('modbus_cache_poll_up', '1 = the last poll cycle talked to the device.', 'gauge',
                    '%d' % st['poll_up']),
            *metric('modbus_cache_hits_total', 'Cache hits (reads served without the device).', 'counter',
                    '%d' % st['hits']),
            *metric('modbus_cache_misses_total', 'Cache misses (reads forwarded to the device).', 'counter',
                    '%d' % st['misses']),
            *metric('modbus_cache_write_refused_total',
                    'Writes the gate refused (allow-write off, the write ACL, the register allow-list, a malformed frame) — each refusal is a WRITE-REFUSED audit event.',
                    'counter', '%d' % st['write_refused']),
            *metric('modbus_cache_ranges', 'The register ranges in the map (fc3/fc4 labels).', 'gauge',
                    ('fc="3"', '%d' % (st['ranges'] - st['fc4'])), ('fc="4"', '%d' % st['fc4'])),
            *metric('modbus_cache_words', 'Cached register words.', 'gauge', '%d' % st['words']),
            *metric('modbus_cache_clients', 'Connected Modbus clients.', 'gauge', '%d' % st['clients']),
            *metric('modbus_cache_poll_duration_seconds', 'The last poll cycle duration.', 'gauge',
                    '%g' % st['poll_last']),
            *metric('modbus_cache_poll_duration_mean_seconds', 'The mean poll cycle duration.', 'gauge',
                    '%g' % st['poll_mean']),
            *metric('modbus_cache_poll_duration_max_seconds', 'The longest poll cycle duration so far.', 'gauge',
                    '%g' % st['poll_max']),
        ]
        if st['last_poll_age'] is not None:
            rows += metric('modbus_cache_last_poll_age_seconds',
                           'Seconds since the last successful poll cycle.', 'gauge',
                           '%d' % st['last_poll_age'])
        if st['oldest'] is not None:
            rows += metric('modbus_cache_age_seconds', 'The age of the oldest cached word.', 'gauge',
                           '%g' % st['oldest'])
        rows += [
            *metric('modbus_cache_uplink_up', '1 = the upstream socket to the inverter is connected.', 'gauge',
                    '%d' % st['uplink_up']),
            *metric('modbus_cache_uplink_connects_total', 'Successful upstream connects (2 = one reconnect).',
                    'counter', '%d' % st['uplink_connects']),
            *metric('modbus_cache_uplink_exchanges_total', 'Completed upstream request/reply exchanges.',
                    'counter', '%d' % st['uplink_exchanges']),
            *metric('modbus_cache_uplink_errors_total', 'Failed upstream exchanges (timeout, reset, refused, bad frame).',
                    'counter', '%d' % st['uplink_errors']),
            *metric('modbus_cache_uplink_bytes_total', 'Upstream bytes by direction.', 'counter',
                    ('dir="in"', '%d' % st['uplink_bytes_in']), ('dir="out"', '%d' % st['uplink_bytes_out'])),
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
