#!/usr/bin/env python3
"""The fake's own Prometheus endpoint: a small /metrics, gated (the
`metrics-server` setting, default off). Serves the simulator's state and
the server's counters in the Prometheus text format. With --metrics-token
set, requests need `Authorization: Bearer <token>` (the same scheme the
scraper speaks when it pulls token-protected exporters). The bind address
is --metrics-listen HOST:PORT (0.0.0.0 serves every interface — mind the
values, the fake is a demo). Caps: --metrics-max-clients (immediate 503
past it), --metrics-client-timeout (0 = the built-in 5 s cap),
--metrics-max-conn-per-ip (0 = no limit). Ahead of the caps the
metrics/acl gate checks the peer IP at accept (the cache's metrics/acl
reading): a client off the ACL is closed without a reply — nothing was
parsed to answer, the caps never see the peer. The gated endpoint
skeleton (the 401/404/503, the caps, the thread start/stop) is the
family's common/metrics_server."""
import logging
import time

from common.config import acl_admits
from common.metrics_server import MetricsServer as _MetricsServer
from common.metrics_server import describe_metrics

logger = logging.getLogger('fake-inverter')


class MetricsServer(_MetricsServer):
    """A tiny Prometheus text-endpoint for the fake itself. None of the
    real-device semantics — the self-observability: the pv/load/grid/battery
    watts, the SoC, the machines' readings, the poll/connection counters."""

    REALM = 'fake-inverter'
    LOG_NAME = 'fake-inverter'

    def __init__(self, simulator, chaos, fake, control, listen, token=None, started=0.0,
                 max_clients=64, client_timeout=5.0, max_per_ip=0):
        super().__init__(listen, token=token, started=started, max_clients=max_clients,
                         client_timeout=client_timeout, max_per_ip=max_per_ip)
        self.simulator = simulator
        self.chaos = chaos
        self.fake = fake
        self.control = control

    def acl_allows(self, ip):
        """The accept-time metrics/acl gate: the gate reads through the
        fake per connection — one live state, the set/unset swap needs no
        push here (the cache's metrics.py reading)."""
        return acl_admits(self.fake.metrics_acl, ip)

    def acl_refused(self, request, client_address):
        logger.info('connection rejected: %s:%d not on the metrics ACL', *client_address[:2])
        self._http._refuse_close(request)

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
            '# HELP fake_inverter_soc_percent The battery state of charge.',
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
        return time.monotonic() - (self.started or time.monotonic())
