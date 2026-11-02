#!/usr/bin/env python3
"""Modbus TCP caching proxy for Huawei SUN2000 inverters (stdlib only).

The inverter (or its SDongle/EMMA) accepts only a single Modbus TCP client.
This proxy owns that one upstream connection: a background loop polls the
configured register ranges at a fixed interval while any number of clients
connect and are served FC3 reads from the in-memory cache. Reads outside the
cached ranges and every other function code are forwarded to the inverter
(serialized, one at a time).

Layout: lib/protocol (wire format), lib/config (settings + register map),
lib/upstream (inverter connection), lib/cache (register cache + block plan),
lib/proxy (poller + client handling), this file (CLI, logging, signals).
"""
import argparse
import logging
import os
import signal
import threading
import time

from lib.protocol import exception_frame
from lib.config import load_registers_file, parse_listen, resolve_config
from lib.upstream import Upstream
from lib.cache import Cache
from lib.proxy import Proxy

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

logger = logging.getLogger('modbus-cache')


class UtcFormatter(logging.Formatter):
    converter = staticmethod(time.gmtime)


def parse_args():
    ap = argparse.ArgumentParser(description='Modbus TCP caching proxy for Huawei SUN2000 inverters.')
    ap.add_argument('--config', default=os.path.join(SCRIPT_DIR, 'modbus_cache.ini'),
                    help='config file (default: modbus_cache.ini next to this script)')
    ap.add_argument('--host', help='inverter Modbus TCP address (default: config, $MODBUS_CACHE_HOST or 127.0.0.1)')
    ap.add_argument('--port', type=int, help='inverter Modbus TCP port (default: config, $MODBUS_CACHE_PORT or 5502)')
    ap.add_argument('--unit', type=int, help='Modbus unit id (default: config, $MODBUS_CACHE_UNIT or 1)')
    ap.add_argument('--timeout', type=float, help='Modbus connect/read timeout in seconds (default: config, $MODBUS_CACHE_TIMEOUT or 3)')
    ap.add_argument('--listen', help='listen address HOST:PORT (default: config, $MODBUS_CACHE_LISTEN or 0.0.0.0:15502)')
    ap.add_argument('--interval', type=float, help='seconds between cache polls (default: config, $MODBUS_CACHE_INTERVAL or 10)')
    ap.add_argument('--read-delay', type=float, help='seconds between consecutive inverter reads within a poll cycle, 0 = no delay (default: config, $MODBUS_CACHE_READ_DELAY or 0.05)')
    ap.add_argument('--merge-gap', type=int, help='max register gap when merging ranges into block reads, 0 = read ranges separately (default: config, $MODBUS_CACHE_MERGE_GAP or 8)')
    ap.add_argument('--registers-file', help='JSON register map {"registers": [{"name": ..., "start": N, "count": N}, ...]} (default: config, $MODBUS_CACHE_REGISTERS_FILE or registers.json next to this script)')
    ap.add_argument('--cache-ttl', type=float, help='per-register cache TTL: cached registers older than this are refetched from the inverter, 0 = never expire, serve last known values forever (default: config, $MODBUS_CACHE_TTL or 3x interval)')
    ap.add_argument('--allow-write', action='store_true', help='forward write requests (FC05/06/15/16) to the inverter; default: refuse them with a Modbus illegal-function exception')
    ap.add_argument('--local-time', action='store_true', help='log timestamps in the system time zone instead of UTC')
    ap.add_argument('--log-access', action='store_true', help='log client connects/disconnects at INFO instead of DEBUG')
    ap.add_argument('--log-level', choices=['DEBUG', 'INFO', 'WARNING', 'ERROR'],
                    help='log level (default: config, $MODBUS_CACHE_LOG_LEVEL or INFO)')
    return ap.parse_args()


def setup_logging(cfg):
    root = logging.getLogger()
    root.setLevel(getattr(logging, cfg['level'], logging.INFO))
    fmt = '%(levelname)-7s %(message)s' if os.environ.get('JOURNAL_STREAM') \
        else '%(asctime)s %(levelname)-7s %(message)s'
    handler = logging.StreamHandler()
    handler.setFormatter(UtcFormatter(fmt) if not cfg['local_time'] else logging.Formatter(fmt))
    root.addHandler(handler)


def install_signal_handlers(proxy, cache, args):
    if hasattr(signal, 'SIGHUP'):
        reload_requested = threading.Event()

        def on_hup(signum, frame):
            reload_requested.set()

        def watch_reload():
            while True:
                reload_requested.wait()
                reload_requested.clear()
                logger.info('SIGHUP: reload requested')
                try:
                    proxy.config = resolve_config(args, SCRIPT_DIR)
                    proxy.reload()
                except (Exception, SystemExit) as e:
                    logger.error('SIGHUP: reload failed (%s), keeping the previous settings', e)

        signal.signal(signal.SIGHUP, on_hup)
        threading.Thread(target=watch_reload, daemon=True).start()
    if hasattr(signal, 'SIGUSR1'):
        clean_requested = threading.Event()

        def on_usr1(signum, frame):
            clean_requested.set()

        def watch_clean():
            while True:
                clean_requested.wait()
                clean_requested.clear()
                dropped = cache.clear()
                proxy.poll_wake.set()
                logger.info('SIGUSR1: cache cleared (%d register(s) dropped), repolling now', dropped)

        signal.signal(signal.SIGUSR1, on_usr1)
        threading.Thread(target=watch_clean, daemon=True).start()
    if hasattr(signal, 'SIGTERM'):
        stop_signal = []

        def on_stop(signum, frame):
            stop_signal.append(signum)

        def watch_stop():
            while not stop_signal:
                time.sleep(0.2)
            sig = signal.Signals(stop_signal[0]).name
            logger.info('shutdown: %s received, closing the listener', sig)
            try:
                proxy.listen_sock.close()
            except OSError:
                pass
            for h in logging.getLogger().handlers:
                h.flush()
            os._exit(0)

        signal.signal(signal.SIGTERM, on_stop)
        signal.signal(signal.SIGINT, on_stop)
        threading.Thread(target=watch_stop, daemon=True).start()


def main():
    args = parse_args()
    cfg = resolve_config(args, SCRIPT_DIR)
    ranges, range_names = load_registers_file(cfg['registers_file'])

    setup_logging(cfg)

    listen_host, listen_port = parse_listen(cfg['listen'])
    upstream = Upstream(cfg['host'], cfg['port'], cfg['unit'], cfg['timeout'])
    cache = Cache(ranges, cfg['cache_ttl'], range_names)
    proxy = Proxy(upstream, cache, cfg['read_delay'], cfg['merge_gap'], cfg['interval'],
                  cfg['registers_file'], cfg)
    logger.info('caching %d range(s) from %s (%s:%d unit %d) every %gs, %gs between reads, merge gap %d, cache ttl %gs, write support %s, client access log at %s; serving Modbus TCP on %s:%d (config: %s, log level: %s, log time: %s)',
                len(ranges), cfg['registers_file'], cfg['host'], cfg['port'], cfg['unit'], cfg['interval'],
                cfg['read_delay'], cfg['merge_gap'], cfg['cache_ttl'],
                'ENABLED' if proxy.allow_write else 'disabled (write requests are refused)',
                'INFO' if proxy.log_access else 'DEBUG',
                listen_host, listen_port, args.config, cfg['level'],
                'local' if cfg['local_time'] else 'UTC')
    proxy.log_map()
    install_signal_handlers(proxy, cache, args)
    try:
        threading.Thread(target=proxy.poll_loop, daemon=True).start()
        proxy.serve(listen_host, listen_port)
    except KeyboardInterrupt:
        logger.info('stopped')
    except OSError as e:
        logger.error('cannot serve on %s:%d: %s', listen_host, listen_port, e)
        raise SystemExit(1)
    finally:
        upstream.close()


if __name__ == '__main__':
    main()
