#!/usr/bin/env python3
"""The gated Prometheus text-endpoint skeleton, one implementation for the
family: the bearer-token 401, the /metrics-only 404, the connlimit gate
with its immediate 503, the thread start and the live stop. The tool
subclasses MetricsServer with its snapshot()/render() (and its own
constructor state); the 401 realm and the gate-refusal logger name are
class attributes. Stdlib only."""
import hmac
import http.server
import logging
import threading
import time

from common.connlimit import GatedHTTPServer

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
    """A tiny Prometheus text-endpoint for a tool itself. The master switch
    is the live `metrics-server` setting (default off); the bind address is
    --metrics-listen HOST:PORT. Caps (F13 round): --metrics-max-clients
    (immediate 503 past it), --metrics-client-timeout (0 = the built-in 5 s
    slowloris cap), --metrics-max-conn-per-ip; 0 = no per-IP limit."""

    REALM = 'metrics'      # the 401 realm — the subclass names its tool
    LOG_NAME = 'metrics'   # the gate-refusal logger — the subclass names its tool

    def __init__(self, listen, token=None, started=0.0, max_clients=64,
                 client_timeout=5.0, max_per_ip=0):
        self.listen = listen            # (host, port)
        self.token = token
        self.started = started
        self.max_clients = max(0, int(max_clients or 0))
        self.client_timeout = max(0.0, float(client_timeout or 0.0))
        self.max_per_ip = max(0, int(max_per_ip or 0))
        self._http = None

    def snapshot(self):
        """The metric values — the tool's."""
        raise NotImplementedError

    def render(self):
        """The Prometheus text — the tool's."""
        raise NotImplementedError

    class _Handler(http.server.BaseHTTPRequestHandler):
        timeout = 5   # a silent peer cannot pin a handler thread (slowloris)

        def log_message(self, *a):
            pass   # the access logging = the scraper's job; the exporter stays quiet

        def do_GET(self):
            srv = self.server.metrics_server
            if srv.token:
                auth = self.headers.get('Authorization', '')
                want = 'Bearer ' + srv.token
                if not hmac.compare_digest(auth, want):
                    self.send_response(401)
                    self.send_header('WWW-Authenticate', 'Bearer realm="%s"' % srv.REALM)
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
                logging.getLogger(httpd.metrics_server.LOG_NAME).info(
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
