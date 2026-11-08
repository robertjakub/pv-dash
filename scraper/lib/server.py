#!/usr/bin/env python3
"""The Prometheus exposition endpoint (stdlib only)."""
import hmac
import logging
import sys
from http.server import BaseHTTPRequestHandler

from common.config import acl_admits
from common.connlimit import GatedHTTPServer

logger = logging.getLogger('scraper')

RATE_LIMIT_503 = (b'HTTP/1.1 503 Service Unavailable\r\n'
                  b'Content-Type: text/plain; charset=utf-8\r\n'
                  b'Cache-Control: no-store\r\n'
                  b'Connection: close\r\n\r\n'
                  b'# rate limited: too many concurrent clients\n')


class Handler(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'
    scraper = None
    log_access = False
    auth_token = None

    def authorized(self):
        if not self.auth_token:
            return True
        scheme, _, cred = self.headers.get('Authorization', '').partition(' ')
        if scheme.lower() != 'bearer':
            return False
        return hmac.compare_digest(cred.strip().encode(), self.auth_token.encode())

    def do_GET(self):
        if not self.authorized():
            logger.warning('unauthorized %s request for %s (bearer token missing or invalid)',
                           self.address_string(), self.path)
            self.relay(401, b'unauthorized\n', 'text/plain; charset=utf-8', www_auth=True)
            return
        path = self.path.split('?', 1)[0]
        try:
            if path == '/metrics':
                if self.scraper.error_state():
                    self.relay(503, b'# Error collecting metrics from inverter\n', 'text/plain; charset=utf-8')
                else:
                    self.relay(200, self.exposition(), 'text/plain; version=0.0.4; charset=utf-8')
            elif path == '/':
                self.relay(200, b'modbus-scraper: see /metrics\n', 'text/plain; charset=utf-8')
            else:
                self.relay(404, b'not found\n', 'text/plain; charset=utf-8')
        except (BrokenPipeError, ConnectionResetError):
            logger.debug('client %s disconnected', self.address_string())
        except Exception as e:
            logger.error('unhandled error serving %s: %s', self.path, e)
            try:
                self.relay(500, b'internal server error\n', 'text/plain; charset=utf-8')
            except Exception:
                pass

    def exposition(self):
        spec = self.scraper.spec
        up, values, last_poll, errors = self.scraper.snapshot()
        # the poll gauges render from the spec (scraper_* in the bundled
        # sectioned spec; the legacy flat specs keep their huawei_* names)
        up_name = 'scraper_up' if 'scraper_up' in spec.help else 'huawei_up'
        errors_name = 'scraper_modbus_errors_total' if 'scraper_modbus_errors_total' in spec.help \
            else 'huawei_modbus_errors_total'
        last_name = 'scraper_last_poll_timestamp_seconds' if 'scraper_last_poll_timestamp_seconds' in spec.help \
            else 'huawei_last_poll_timestamp_seconds'

        def fmt(v):
            return '%d' % round(v) if float(v).is_integer() else '%.3f' % v

        lines = [
            '# HELP %s %s' % (up_name, spec.help[up_name]),
            '# TYPE %s %s' % (up_name, spec.type[up_name]),
            '%s %d' % (up_name, int(up)),
            '# HELP %s %s' % (errors_name, spec.help[errors_name]),
            '# TYPE %s %s' % (errors_name, spec.type[errors_name]),
            '%s %d' % (errors_name, errors),
            '# HELP %s %s' % (last_name, spec.help[last_name]),
            '# TYPE %s %s' % (last_name, spec.type[last_name]),
            '%s %.3f' % (last_name, last_poll),
        ]
        # the poll-latency gauges (last/mean/max) — present in the bundled spec
        s = self.scraper
        for name in ('scraper_poll_duration_seconds', 'scraper_poll_duration_mean_seconds',
                     'scraper_poll_duration_max_seconds'):
            if name not in spec.help:
                continue
            v = {'scraper_poll_duration_seconds': s.poll_secs_last,
                 'scraper_poll_duration_mean_seconds': s.poll_secs_sum / s.poll_count if s.poll_count else 0.0,
                 'scraper_poll_duration_max_seconds': s.poll_secs_max}[name]
            lines.append('# HELP %s %s' % (name, spec.help[name]))
            lines.append('# TYPE %s %s' % (name, spec.type[name]))
            lines.append('%s %s' % (name, fmt(v)))
        for name in sorted(values):
            lines.append('# HELP %s %s' % (name, spec.help.get(name, name)))
            lines.append('# TYPE %s %s' % (name, spec.type.get(name, 'gauge')))
            lines.append('%s %s' % (name, fmt(values[name])))
        return ('\n'.join(lines) + '\n').encode()

    def relay(self, status, body, ctype, www_auth=False):
        self.send_response(status)
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        if www_auth:
            self.send_header('WWW-Authenticate', 'Bearer realm="metrics"')
        self.end_headers()
        self.wfile.write(body)
        if self.log_access:
            logger.info('%s - "%s %s" %d %d bytes', self.address_string(),
                        self.command, self.path, status, len(body))

    def log_message(self, fmt, *args):
        logger.debug('%s - %s', self.address_string(), fmt % args)


class Server(GatedHTTPServer):
    """The exposition server behind the connection caps (F13 round):
    --max-clients (total) and --max-conn-per-ip — past either, an immediate
    503; 0 = unlimited. setup_gate() runs before bind. Ahead of the caps
    the metrics/acl gate checks the peer IP at accept (the modbus-cache
    connect-ACL reading): a client off the ACL is closed without a reply
    — nothing was parsed to answer, the caps never see the peer."""

    metrics_acl = None   # the live gate: None = any, () = none, the networks tuple, IPGate (the file chain)

    def acl_allows(self, ip):
        return acl_admits(self.metrics_acl, ip)

    def acl_refused(self, request, client_address):
        logger.info('connection rejected: %s:%d not on the metrics ACL', *client_address[:2])
        self.shutdown_request(request)

    def gate_refused(self, request, client_address, why):
        logger.info('rejected %s: too many concurrent clients (%s, max %d/%d)',
                    client_address, why, self.gate.max_total, self.gate.max_per_ip)
        try:
            request.sendall(RATE_LIMIT_503)
        except OSError:
            pass
        self.shutdown_request(request)

    def handle_error(self, request, client_address):
        """ThreadingMixIn's default prints a full traceback per reset client — one line instead."""
        exc = sys.exc_info()[1]
        if isinstance(exc, OSError):
            logger.debug('client %s: %s: %s', client_address, type(exc).__name__, exc)
        else:
            logger.error('unhandled error serving %s: %s: %s', client_address,
                         type(exc).__name__, exc)
