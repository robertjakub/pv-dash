#!/usr/bin/env python3
import argparse
import configparser
import logging
import mimetypes
import os
import socket
import sys
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

logger = logging.getLogger('pv-server')
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))


class Server(ThreadingHTTPServer):
    daemon_threads = True

    def handle_error(self, request, client_address):
        exc = sys.exc_info()[1]
        if isinstance(exc, (ConnectionError, socket.timeout, TimeoutError)):
            logger.debug('client %s disconnected: %s', client_address, exc)
        else:
            logger.error('request handling error: %s', exc)
            logger.debug('traceback:', exc_info=True)


class Handler(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'
    upstream = 'http://localhost:9090'
    log_queries = False
    static_dir = os.path.join(SCRIPT_DIR, 'static')
    config_js = os.path.join(SCRIPT_DIR, 'config.js')
    prom_prefix = '/prom'
    upstream_ok = True
    _upstream_lock = threading.Lock()

    def do_GET(self):
        try:
            parts = urlsplit(self.path)
            prefix = self.prom_prefix.rstrip('/')
            if not prefix or parts.path == prefix or parts.path.startswith(prefix + '/'):
                self.proxy(parts)
            else:
                self.static(parts.path)
        except (BrokenPipeError, ConnectionResetError):
            logger.debug('client %s disconnected', self.address_string())
        except Exception as e:
            logger.error('unhandled error serving %s: %s', self.path, e)
            logger.debug('traceback:', exc_info=True)
            try:
                self.send_error(500, 'internal server error')
            except Exception:
                pass

    def proxy(self, parts):
        prefix = self.prom_prefix.rstrip('/')
        rest = parts.path[len(prefix):] if prefix else parts.path
        url = self.upstream.rstrip('/') + rest
        if parts.query:
            url += '?' + parts.query
        t0 = time.time()
        try:
            req = urllib.request.Request(url, headers={'Accept': 'application/json'})
            with urllib.request.urlopen(req, timeout=30) as r:
                status, body, ctype = r.status, r.read(), r.headers.get('Content-Type', 'application/json')
            self._mark_upstream(True, None)
        except urllib.error.HTTPError as e:
            status, body, ctype = e.code, e.read(), e.headers.get('Content-Type', 'text/plain')
            self._mark_upstream(True, e.code)
        except Exception as e:
            status, body, ctype = 502, ('proxy error: ' + str(e)).encode(), 'text/plain'
            self._mark_upstream(False, e)
            logger.debug('proxy %s: %s', url, e)
        self.relay(status, body, ctype)
        msg = 'GET %s -> %s (%d ms, %d bytes)' % (
            parts.path + ('?' + parts.query if parts.query else ''),
            status, (time.time() - t0) * 1000, len(body))
        if self.log_queries:
            logger.info(msg)
        else:
            logger.debug(msg)

    def relay(self, code, body, ctype):
        try:
            self.send_response(code)
            self.send_header('Content-Type', ctype)
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Cache-Control', 'no-cache, no-store, must-revalidate')
            self.send_header('Pragma', 'no-cache')
            self.end_headers()
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError, socket.timeout):
            logger.debug('client %s disconnected while sending %d', self.address_string(), code)

    def _mark_upstream(self, ok, detail):
        with self._upstream_lock:
            if Handler.upstream_ok == ok:
                return
            Handler.upstream_ok = ok
        if ok:
            logger.info('prometheus at %s is reachable again%s', self.upstream,
                        ' (HTTP %s)' % detail if detail is not None else '')
        else:
            logger.warning('prometheus at %s not available: %s (serving 502 until it recovers)', self.upstream, detail)

    def static(self, path):
        if path == '/':
            path = '/index.html'
        name = path.lstrip('/')
        if name == 'config.js' and self.config_js and os.path.isfile(self.config_js):
            self.serve_file(self.config_js)
            return
        fpath = os.path.realpath(os.path.join(self.static_dir, path.lstrip('/')))
        base = os.path.realpath(self.static_dir)
        if fpath != base and not fpath.startswith(base + os.sep):
            self.send_error(403)
            return
        if not os.path.isfile(fpath):
            self.send_error(404)
            return
        self.serve_file(fpath)

    def serve_file(self, fpath):
        try:
            ctype = mimetypes.guess_type(fpath)[0] or 'application/octet-stream'
            with open(fpath, 'rb') as f:
                body = f.read()
        except OSError as e:
            logger.error('cannot read %s: %s', fpath, e)
            self.send_error(500, 'cannot read file')
            return
        self.relay(200, body, ctype)

    def log_message(self, fmt, *args):
        logger.debug('%s - %s', self.address_string(), fmt % args)


def load_config(path):
    cfg = configparser.ConfigParser()
    try:
        if os.path.isfile(path):
            cfg.read(path)
    except (configparser.Error, OSError) as e:
        logger.error('cannot read config file %s: %s (using defaults)', path, e)
    if not cfg.has_section('server'):
        cfg.add_section('server')
    return cfg['server']


def main():
    ap = argparse.ArgumentParser(description='Static file server with a Prometheus proxy at /prom')
    ap.add_argument('--config', default=os.path.join(SCRIPT_DIR, 'server.ini'),
                    help='server config file (default: server.ini next to this script)')
    ap.add_argument('--port', type=int, help='listen port (default: config file, $PORT or 8080)')
    ap.add_argument('--bind', help='address to bind (default: config file, $BIND or 0.0.0.0)')
    ap.add_argument('--static-dir', help='directory to serve (default: config file or the script directory)')
    ap.add_argument('--config-js', help='config.js to serve at /config.js (default: config file, $CONFIG_JS or config.js next to this script)')
    ap.add_argument('--prom-prefix', help='path under which Prometheus is proxied (default: config file or /prom); empty string proxies everything')
    ap.add_argument('--upstream', help='upstream Prometheus URL (default: config file, $PROM_URL or http://localhost:9090)')
    ap.add_argument('--log-level', choices=['DEBUG', 'INFO', 'WARNING', 'ERROR'],
                    help='log level (default: config file or INFO); DEBUG logs every request')
    ap.add_argument('--log-queries', action='store_true', default=None,
                    help='log proxied Prometheus queries at INFO level')
    args = ap.parse_args()

    cfg = load_config(args.config)
    try:
        port = args.port or int(cfg.get('port', os.environ.get('PORT', 8080)))
    except ValueError as e:
        logger.error('invalid port in config: %s (using 8080)', e)
        port = 8080
    bind = args.bind or os.environ.get('BIND') or cfg.get('bind', '0.0.0.0')
    static_dir = args.static_dir or cfg.get('static_dir') or os.environ.get('STATIC_DIR') or os.path.join(SCRIPT_DIR, 'static')
    if not os.path.isabs(static_dir):
        static_dir = os.path.join(SCRIPT_DIR, static_dir)
    static_dir = os.path.realpath(static_dir)
    config_js = args.config_js or os.environ.get('CONFIG_JS') or cfg.get('config_js') or os.path.join(SCRIPT_DIR, 'config.js')
    config_js = os.path.realpath(config_js if os.path.isabs(config_js) else os.path.join(SCRIPT_DIR, config_js))
    prom_prefix = (args.prom_prefix if args.prom_prefix is not None
                   else os.environ.get('PROM_PREFIX', cfg.get('prom_prefix', '/prom'))).rstrip('/')
    upstream = args.upstream or os.environ.get('PROM_URL') or cfg.get('upstream', 'http://localhost:9090')
    level = (args.log_level or cfg.get('log_level', 'INFO')).upper()
    try:
        log_queries = args.log_queries if args.log_queries is not None else cfg.getboolean('log_queries', fallback=False)
    except ValueError as e:
        logger.error('invalid log_queries in config: %s (using false)', e)
        log_queries = False

    logging.basicConfig(level=getattr(logging, level, logging.INFO),
                        format='%(asctime)s %(levelname)-7s %(message)s')
    Handler.upstream = upstream
    Handler.log_queries = log_queries
    Handler.static_dir = static_dir
    Handler.config_js = config_js
    Handler.prom_prefix = prom_prefix

    logger.info('serving %s on http://%s:%d (proxy: %s/* -> %s, config.js: %s, log level: %s%s)',
                static_dir, bind, port, prom_prefix or '/', upstream, config_js, level,
                ', query logging on' if log_queries else '')
    try:
        Server((bind, port), Handler).serve_forever()
    except KeyboardInterrupt:
        logger.info('stopped')
    except OSError as e:
        logger.error('cannot bind %s:%d: %s', bind, port, e)
        sys.exit(1)


if __name__ == '__main__':
    main()
