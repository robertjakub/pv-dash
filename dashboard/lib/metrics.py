#!/usr/bin/env python3
"""The dashboard's own Prometheus endpoint: a small /metrics on its own
port, gated (off by default, the bearer token mandatory beyond loopback —
the F13 posture, the scraper's refusal the family's golden shape). Serves
the dashboard's
self-observability in the Prometheus text format: the uptime, the request
counters by status, the proxied Prometheus query total, the active clients
from the family gate and the configured upstream — not the PV values (the
page and the proxy already serve those, F21's auth story aside). Ahead of
the caps the metrics/acl gate checks the peer IP at accept (the cache's
metrics/acl reading): a client off the ACL is closed without a reply —
nothing was parsed to answer, the caps never see the peer. The gated
endpoint skeleton (the 401/404/503, the caps, the thread start/stop) is the
family's common/metrics_server."""
import logging
import time

from common.config import acl_admits
from common.metrics_server import MetricsServer as _MetricsServer
from common.metrics_server import describe_metrics
from common.version import version_string


class MetricsServer(_MetricsServer):
    """A tiny Prometheus text-endpoint for the dashboard itself. The master
    switch is the live `metrics enable` setting (default off); the bind
    address is --metrics-listen HOST:PORT. Caps: --metrics-max-clients
    (immediate 503 past it), --metrics-client-timeout (0 = the built-in 5 s
    slowloris cap), --metrics-max-conn-per-ip; 0 = no per-IP limit."""

    REALM = 'dashboard'
    LOG_NAME = 'dashboard'

    def __init__(self, httpd, control, listen, token=None, started=0.0, max_clients=64,
                 client_timeout=5.0, max_per_ip=0, acl=None):
        super().__init__(listen, token=token, started=started, max_clients=max_clients,
                         client_timeout=client_timeout, max_per_ip=max_per_ip)
        self.httpd = httpd
        self.control = control
        self.metrics_acl = acl   # the gate when no control server exists (the control owns the state otherwise)

    def acl_allows(self, ip):
        """The accept-time metrics/acl gate: the gate reads through the
        control per connection — one live state, the set/unset swap needs
        no push here (the cache's metrics.py reading); control-less (the
        control-port 0 edge) the ctor's copy stands, and no set surface
        exists to move it."""
        gate = self.control.metrics_acl if self.control is not None else self.metrics_acl
        return acl_admits(gate, ip)

    def acl_refused(self, request, client_address):
        logging.getLogger(self.LOG_NAME).info('connection rejected: %s:%d not on the metrics ACL',
                                              *client_address[:2])
        self._http._refuse_close(request)

    def render(self):
        h = self.httpd
        now = time.monotonic()
        counts = getattr(h, 'status_counts', None) or {}
        gate = getattr(h, 'gate', None)
        rows = [
            '# HELP dashboard_uptime_seconds The dashboard process uptime.',
            '# TYPE dashboard_uptime_seconds gauge',
            'dashboard_uptime_seconds %d' % int(now - (self.started or now)),
            '# HELP dashboard_version_info The dashboard version (value is always 1).',
            '# TYPE dashboard_version_info gauge',
            'dashboard_version_info{version="%s"} 1' % version_string(),
            '# HELP dashboard_requests_total HTTP requests served, by status class.',
            '# TYPE dashboard_requests_total counter',
            'dashboard_requests_total{status="2xx"} %d' % counts.get('2xx', 0),
            'dashboard_requests_total{status="4xx"} %d' % counts.get('4xx', 0),
            'dashboard_requests_total{status="5xx"} %d' % counts.get('5xx', 0),
            '# HELP dashboard_prom_queries_total Proxied Prometheus queries.',
            '# TYPE dashboard_prom_queries_total counter',
            'dashboard_prom_queries_total %d' % counts.get('prom', 0),
            '# HELP dashboard_upstream_ok 1 = the last proxied query reached the Prometheus upstream.',
            '# TYPE dashboard_upstream_ok gauge',
            'dashboard_upstream_ok %d' % (1 if getattr(h, 'upstream_ok', True) else 0),
            '# HELP dashboard_clients Active HTTP clients (the family gate).',
            '# TYPE dashboard_clients gauge',
            'dashboard_clients %d' % (gate.total() if gate else 0),
            '# HELP dashboard_max_clients The configured total client cap (0 = unlimited).',
            '# TYPE dashboard_max_clients gauge',
            'dashboard_max_clients %d' % (getattr(gate, 'max_total', 0) or 0),
        ]
        if gate is not None and getattr(gate, 'max_per_ip', 0):
            rows += [
                '# HELP dashboard_max_conn_per_ip The configured per-IP client cap.',
                '# TYPE dashboard_max_conn_per_ip gauge',
                'dashboard_max_conn_per_ip %d' % h.gate.max_per_ip,
            ]
        return '\n'.join(rows) + '\n'
