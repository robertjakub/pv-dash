#!/usr/bin/env python3
"""The dashboard's own Prometheus endpoint: a small /metrics on its own
port, gated (off by default, and the bearer token is mandatory when on —
the F6 posture the cache's endpoint set). Serves the dashboard's
self-observability in the Prometheus text format: the uptime, the request
counters by status, the proxied Prometheus query total, the active clients
from the family gate and the configured upstream — not the PV values (the
page and the proxy already serve those, F21's auth story aside)."""
import hmac
import http.server
import threading
import time

from common.connlimit import GatedHTTPServer
from common.version import version_string

METRICS_503 = (b'HTTP/1.1 503 Service Unavailable\r\n'
               b'Content-Type: text/plain; charset=utf-8\r\n'
               b'Cache-Control: no-store\r\n'
               b'Connection: close\r\n\r\n'
               b'# rate limited: too many concurrent clients\n')


def describe_metrics(listen, token, max_clients=0, max_per_ip=0):
    """The status/inspect one-liner for the endpoint state."""
    host, port = listen
    return '%s:%d%s, clients %s, per-ip %s' % (
        host, port, ' (bearer token)' if token else '',
        max_clients or 'none', max_per_ip or 'none')


class MetricsServer:
    """A tiny Prometheus text-endpoint for the dashboard itself. The master
    switch is the live `metrics-server` setting (default off); the bind
    address is --metrics-listen HOST:PORT. Caps: --metrics-max-clients
    (immediate 503 past it), --metrics-client-timeout (0 = the built-in 5 s
    slowloris cap), --metrics-max-conn-per-ip; 0 = no per-IP limit."""

    def __init__(self, httpd, listen, token=None, started=0.0, max_clients=64,
                 client_timeout=5.0, max_per_ip=0):
        self.httpd = httpd
        self.listen = listen            # (host, port)
        self.token = token
        self.started = started
        self.max_clients = max(0, int(max_clients or 0))
        self.client_timeout = max(0.0, float(client_timeout or 0.0))
        self.max_per_ip = max(0, int(max_per_ip or 0))
        self._http = None

    def render(self):
        import logging
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

    class _Handler(http.server.BaseHTTPRequestHandler):
        timeout = 5   # a silent peer cannot pin a handler thread (slowloris)

        def log_message(self, *a):
            pass

        def do_GET(self):
            srv = self.server.metrics_server
            if srv.token:
                auth = self.headers.get('Authorization', '')
                want = 'Bearer ' + srv.token
                if not hmac.compare_digest(auth, want):
                    self.send_response(401)
                    self.send_header('WWW-Authenticate', 'Bearer realm="dashboard"')
                    self.end_headers()
                    self.wfile.write(b'401 unauthorized\n')
                    return
            if self.path.split('?')[0] != '/metrics':
                self.send_response(404)
                self.end_headers()
                self.wfile.write(b'404 not found (try /metrics)\n')
                return
            body = srv.render().encode()
            self.send_response(200)
            self.send_header('Content-Type', 'text/plain; version=0.0.4; charset=utf-8')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    def serve(self):
        self.started = self.started or time.monotonic()
        self._Handler.timeout = self.client_timeout or 5   # 0 = the built-in slowloris cap

        class Server(GatedHTTPServer):
            def gate_refused(httpd, request, client_address, why):
                logging.getLogger('dashboard').info(
                    'metrics: rejected %s: too many concurrent clients (%s, max %d/%d)',
                    client_address, why, httpd.gate.max_total, httpd.gate.max_per_ip)
                try:
                    request.sendall(METRICS_503)
                except OSError:
                    pass
                httpd.shutdown_request(request)

        httpd = Server(self.listen, self._Handler)
        httpd.setup_gate(self.max_clients, self.max_per_ip)
        httpd.metrics_server = self
        self._http = httpd
        httpd.serve_forever()

    def stop(self):
        """Stop the serving loop and close the socket (the live
        `set metrics-server off`); a second stop is a no-op."""
        httpd, self._http = self._http, None
        if not httpd:
            return
        httpd.shutdown()
        httpd.server_close()

    def start(self):
        threading.Thread(target=self.serve, daemon=True).start()
