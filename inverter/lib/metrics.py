#!/usr/bin/env python3
"""The fake's own Prometheus endpoint: a small /metrics on its own port,
gated (off by default). Serves the simulator's state and the server's
counters in the Prometheus text format. With --metrics-token set, requests
need `Authorization: Bearer <token>` (the same scheme the scraper speaks
when it pulls token-protected exporters)."""
import hmac
import http.server
import json
import threading


class MetricsServer:
    """A tiny Prometheus text-endpoint for the fake itself. None of the
    real-device semantics — the self-observability: the pv/load/grid/battery
    watts, the SoC, the machines' readings, the poll/connection counters."""

    def __init__(self, simulator, chaos, fake, control, port, token=None, started=0.0):
        self.simulator = simulator
        self.chaos = chaos
        self.fake = fake
        self.control = control
        self.port = port
        self.token = token
        self.started = started
        self._http = None

    def snapshot(self):
        sim = self.simulator
        pv_w, load_w, batt_w, soc, cloud, _ov = sim.effective()
        t = sim.clock()
        v_phases = sim._grid_voltages(t)
        return {
            'pv_w': pv_w, 'load_w': load_w, 'grid_w': pv_w - batt_w - load_w,
            'batt_w': batt_w, 'soc': soc, 'cloud': sim.cloud_display(),
            'mppt': sim.mppt, 'grid_voltage': sim.grid_voltage,
            'grid_frequency': sim.grid_frequency_value(t),
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
        httpd = http.server.ThreadingHTTPServer(('127.0.0.1', self.port), self._Handler)
        httpd.metrics_server = self
        self._http = httpd
        httpd.serve_forever()

    def start(self):
        threading.Thread(target=self.serve, daemon=True).start()
