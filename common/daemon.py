#!/usr/bin/env python3
"""The daemon-bin scaffolding the family's entry scripts shared as
near-copies (stdlib only): the log setup, the default config path, the
SIGHUP/SIGTERM watcher threads, the restart-marked state fold, the ops-verb
policy check and the dump-posture log line — one implementation here, the
bins keep their main(), their describe() and their reload bodies. The
fake's signal machine (the SignalBox env layer) and the cache's
os._exit-restart shape stay their own — this module serves the
resolve-and-serve shape."""
import logging
import os
import signal
import threading
import time

from common.logutil import UtcFormatter

logger = logging.getLogger('daemon')


def setup_logging(cfg):
    """The root logger from the resolved config: the level knob, the
    JOURNAL_STREAM shape (no timestamps — journald stamps) and the
    local-time option."""
    root = logging.getLogger()
    root.setLevel(getattr(logging, cfg['level'], logging.INFO))
    fmt = '%(levelname)-7s %(message)s' if os.environ.get('JOURNAL_STREAM') \
        else '%(asctime)s %(levelname)-7s %(message)s'
    handler = logging.StreamHandler()
    handler.setFormatter(UtcFormatter(fmt) if not cfg['local_time'] else logging.Formatter(fmt))
    root.addHandler(handler)


def next_to_script(script_dir, name):
    """The flattened package layout first (the file next to the script),
    then the dev checkout's subproject root (the parent of bin/)."""
    for base in (script_dir, os.path.dirname(script_dir)):
        cand = os.path.join(base, name)
        if os.path.exists(cand):
            return cand
    return os.path.join(script_dir, name)


def default_config_path(script_dir, conf):
    """$CONFIG wins (the docker config volume); then a user's config
    script next to the script (the flattened package layout); then the
    dev checkout's sample at the subproject root."""
    env = os.environ.get('CONFIG')
    if env and env.strip():
        return env.strip()
    return next_to_script(script_dir, conf)


def install_signal_handlers(apply_reload=None, graceful_stop=None):
    """The two watcher threads: SIGHUP re-resolves and re-applies (the
    shared apply_reload — the bin's reload body), SIGTERM/SIGINT run the
    graceful stop once (the signal name as the reason). The handlers ride
    the main-thread signal discipline; the watchers keep the handlers'
    work off the signal frame."""
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
                    summary = apply_reload()
                    logger.info('SIGHUP: applied (%s)', summary)
                except (Exception, SystemExit) as e:
                    logger.error('SIGHUP: reload failed (%s), keeping the previous settings', e)

        signal.signal(signal.SIGHUP, on_hup)
        threading.Thread(target=watch_reload, daemon=True).start()
    if hasattr(signal, 'SIGTERM'):
        stop_signal = []

        def on_stop(signum, frame):
            stop_signal.append(signum)

        def watch_stop():
            while not stop_signal:
                time.sleep(0.2)
            graceful_stop(signal.Signals(stop_signal[0]).name)

        signal.signal(signal.SIGTERM, on_stop)
        signal.signal(signal.SIGINT, on_stop)
        threading.Thread(target=watch_stop, daemon=True).start()


def apply_restart_state(target, config_path, dump_key, server, extra=None):
    """The restart-marked overrides fold into the startup config BEFORE
    the start's dump-restore decision — the piece that makes the restart
    note true (the execv'd reload applies what the sets recorded).
    `server` is the tool's ControlServer class: the fold reads the
    registry through it (the subclass-name trap — the common base's
    SETTINGS is empty, the fold would fold nothing). `dump/restore-on-start`
    folds everywhere (the dict — or vars(args) — key restore_on_start);
    `extra` maps the tool's own restart-marked branches (the cache's
    listen/upstream folds) to fn(target, pending)."""
    for name, pending in server.fold_restart_state(config_path, dump_key).items():
        if name == 'dump/restore-on-start':
            target['restore_on_start'] = str(pending).strip() in ('on', 'true', '1', 'yes')
        elif extra and name in extra:
            extra[name](target, pending)
        logger.info('reload: the startup-only override %s=%s folds into the startup config', name, pending)


def parse_ops_verbs(raw, known, rc=2, label='--control-ops-verbs'):
    """The ops policy's csv -> the verb frozenset; empty or an unknown
    verb refuses the start (the ops policy needs at least one verb the
    grammar speaks). The default policy is the family's show,clear."""
    ops_verbs = frozenset(v.strip().lower() for v in (raw or 'show,clear').split(',') if v.strip())
    unknown = sorted(v for v in ops_verbs if v not in known)
    if not ops_verbs or unknown:
        logger.error('%s: %s (the ops policy needs at least one verb the grammar speaks: %s)',
                     label, ', '.join(unknown) if unknown else 'empty', ', '.join(sorted(known)))
        raise SystemExit(rc)
    return ops_verbs


def log_state_dumps(dump_path, dump_key, restore_on_start=False):
    """The start's dump-posture line + the unsealed-dump warning (the
    family text; the cache's interval-bearing variant keeps its own)."""
    logger.info('state dumps: %s',
                'off' if not dump_path
                else '%s (request dump, the graceful shutdown%s%s)'
                % (dump_path, ', sealed' if dump_key else '',
                   ', restore on start' if restore_on_start else ''))
    if dump_path and not dump_key:
        logger.warning('the state dump %s is not sealed (the integrity hash only — plaintext at rest): '
                       'set dump/key (--dump-key, $DUMP_KEY or set dump-key, a file: reference works) '
                       'to encrypt it', dump_path)
