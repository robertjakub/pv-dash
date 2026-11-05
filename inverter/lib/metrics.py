#!/usr/bin/env python3
"""The fake's own Prometheus endpoint: a small /metrics on its own port,
gated (off by default). Serves the simulator's state and the server's
counters in the Prometheus text format. With --metrics-token set, requests
need `Authorization: Bearer <token>` (the same scheme the scraper speaks
when it pulls token-protected exporters). Caps (F13 round):
--metrics-max-clients (immediate 503 past it), --metrics-client-timeout
(0 = the built-in 5 s cap), --metrics-max-conn-per-ip (0 = no limit)."""
import hmac
import http.server
import logging
import threading

from common.connlimit import GatedHTTPServer

logger = logging.getLogger('fake-inverter')

METRICS_503 = (b'HTTP/1.1 503 Service Unavailable\r\n'
               b'Content-Type: text/plain; charset=utf-8\r\n'
               b'Cache-Control: no-store\r\n'
               b'Connection: close\r\n\r\n'
               b'# rate limited: too many concurrent clients\n')


class MetricsServer:
    """A tiny Prometheus text-endpoint for the fake itself. None of the
    real-device semantics — the self-observability: the pv/load/grid/battery
    watts, the SoC, the machines' readings, the poll/connection counters."""

    def __init__(self, simulator, chaos, fake, control, port, token=None, started=0.0,
                 max_clients=64, client_timeout=5.0, max_per_ip=0):
        self.simulator = simulator
        self.chaos = chaos
        self.fake = fake
        self.control = control
        self.port = port
        self.token = token
        self.started = started
        self.max_clients = max(0, int(max_clients or 0))
        self.client_timeout = max(0.0, float(client_timeout or 0.0))
        self.max_per_ip = max(0, int(max_per_ip or 0))
        self._http = None

    def snapshot(self):
        sim = self.simulator
        pv_w, load_w, batt_w, soc, cloud, _ov = sim.effective()
        t = sim.clock()
        v_phases = sim._grid_voltages(t)
        return {
            'pv_w': pv_w, 'load_w': load_w,
            'grid_w': 0.0 if sim.outage_active() else pv_w - batt_w - load_w,
            'batt_w': batt_w, 'soc': soc, 'cloud': sim.cloud_display(),
            'mppt': sim.mppt, 'grid_voltage': sim.grid_voltage,
            'grid_frequency': sim.grid_frequency_value(t),
            'time_scale': sim.time_scale, 'grid_outage': 1.0 if sim.outage_active() else 0.0,
            'v_phases': v_phases,
            'conns': self.fake.conns, 'requests': self.fake.requests,
            'chaos_hits': self.chaos.hits, 'strict': self.fake.strict,
        }

    def render(self):
        st = self.snapshot()
        rows = [
            '# HELP fake_inverter_uptime_seconds The fake-inverter process uptime.',
            '# TYPE fake_inverter_uptime_seconds gauge',
            'fake_inverter_uptime_seconds %d' % int(self._uptime()),
            '# HELP fake_inverter_time_scale The simulated clock speed (N× real time).',
            '# TYPE fake_inverter_time_scale gauge',
            'fake_inverter_time_scale %g' % st['time_scale'],
            '# HELP fake_inverter_grid_outage 1 = the simulated grid is down (the outage machine).',
            '# TYPE fake_inverter_grid_outage gauge',
            'fake_inverter_grid_outage %g' % st['grid_outage'],
            '# HELP fake_inverter_power_watts The simulated powers: pv, load, grid (+export), battery (+charge).',
            '# TYPE fake_inverter_power_watts gauge',
            'fake_inverter_power_watts{kind="pv"} %g' % st['pv_w'],
            'fake_inverter_power_watts{kind="load"} %g' % st['load_w'],
            'fake_inverter_power_watts{kind="grid"} %g' % st['grid_w'],
            'fake_inverter_power_watts{kind="battery"} %g' % st['batt_w'],
            '# HELP fake_inverter_soc_percent The battery state of charge (absent with the battery off).',
            '# TYPE fake_inverter_soc_percent gauge',
        ]
        if st['soc'] is not None:
            rows.append('fake_inverter_soc_percent %g' % st['soc'])
        rows += [
            '# HELP fake_inverter_grid_phase_volts The per-phase grid voltage machine.',
            '# TYPE fake_inverter_grid_phase_volts gauge',
        ]
        rows += ['fake_inverter_grid_phase_volts{phase="%s"} %g' % (p, v)
                 for p, v in zip('abc', st['v_phases'])]
        rows += [
            '# HELP fake_inverter_grid_frequency_hz The grid frequency machine.',
            '# TYPE fake_inverter_grid_hz gauge',
            'fake_inverter_grid_hz %g' % st['grid_frequency'],
            '# HELP fake_inverter_chaos_hits_total The hostile-reply chaos counter.',
            '# TYPE fake_inverter_chaos_hits_total counter',
            'fake_inverter_chaos_hits_total %d' % st['chaos_hits'],
            '# HELP fake_inverter_modbus_requests_total The Modbus requests served.',
            '# TYPE fake_inverter_modbus_requests_total counter',
            'fake_inverter_modbus_requests_total %d' % st['requests'],
            '# HELP fake_inverter_modbus_connections_total The Modbus connections accepted.',
            '# TYPE fake_inverter_modbus_connections_total counter',
            'fake_inverter_modbus_connections_total %d' % st['conns'],
        ]
        return '\n'.join(rows) + '\n'

    def _uptime(self):
        import time
        return time.monotonic() - (self.started or time.monotonic())

    class _Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass   # the access logging = the scraper's job; the fake stays quiet

        def do_GET(self):
            srv = self.server.metrics_server
            if srv.token:
                auth = self.headers.get('Authorization', '')
                want = 'Bearer ' + srv.token
                if not hmac.compare_digest(auth, want):
                    self.send_response(401)
                    self.send_header('WWW-Authenticate', 'Bearer realm="fake-inverter"')
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
        import time
        self.started = self.started or time.monotonic()
        self._Handler.timeout = self.client_timeout or 5   # 0 = the built-in slowloris cap

        class Server(GatedHTTPServer):
            def gate_refused(httpd, request, client_address, why):
                logger.info('metrics: rejected %s: too many concurrent clients (%s, max %d/%d)',
                            client_address, why, httpd.gate.max_total, httpd.gate.max_per_ip)
                try:
                    request.sendall(METRICS_503)
                except OSError:
                    pass
                httpd.shutdown_request(request)

        httpd = Server(('127.0.0.1', self.port), self._Handler)
        httpd.setup_gate(self.max_clients, self.max_per_ip)
        httpd.metrics_server = self
        self._http = httpd
        httpd.serve_forever()

    def start(self):
        threading.Thread(target=self.serve, daemon=True).start()
