"""The shared Modbus-TCP accept ladder and session opener — one
implementation for the family's two Modbus faces (the cache and the fake
inverter; the scraper and dashboard are HTTP faces and stay out). A face is
any object carrying the small protocol below; the ladder enforces the gate
order family-wide — the client timeout, the per-IP gate, the connect ACL,
the max-clients cap, the count under the lock, the daemon thread — so the
refusal texts and logs are identical at both faces by construction, not by
convention.

The face protocol (plain attributes + hooks):
  conn_gate        common.connlimit.ConnGate — the per-IP gate (counts always,
                   enforces only when capped)
  max_clients      int, 0 = no limit
  client_timeout   float seconds, 0 = never (set on every admitted socket)
  client_count     int — the live session count, guarded by client_lock
  client_lock      threading.Lock also guarding the clients dict
  clients          dict 'ip:port' -> {'since': monotonic, 'requests': n,
                                     'audited': n} (the cache's periodic
                   REQUESTS tally reads 'audited')
  stopping         bool — the signal box flips it before closing the listener
  max_pdu          the face's read_frame cap
  log              the face's logger (every ladder line lands in the
                   daemon's own log domain)
  access(...)      the level-aware log fn (the cache: info/debug by
                   log-access; the fake: info)
  listening(host, port)   the face's rich startup line, logged after listen
  allowed(ip)             the connect-ACL verdict (acl_admits on the face's
                          live-swappable list)
  suite_key()             the suite-handshake key when the scheme is on,
                          else None
  on_frame()              the per-iteration hook (the fake's request counter)
  on_session()            the per-session hook (the fake's connection counter)
  malformed(addr, err)    the read_frame ModbusError policy — the cache
                          answers malformed PDUs in-band inside its frame
                          delegate and stays silent here; the fake logs and
                          closes. Either way the session ends.
  frame(client, txn, proto, unit, pdu, addr)   the face's dispatch
  on_disconnect(key, entry)  the unwind hook (the cache's REQUESTS event)
"""
import socket
import threading
import time

from .protocol import ModbusError, auth_handshake_server, read_frame


def serve_modbus(face, host, port, backlog=128):
    """Bind, listen and run the accept ladder until face.stopping. The
    backlog sits above every face's client limit — a connect burst past a
    short backlog gets RST on macOS/BSD before the client ever sends (the
    control-plane lesson, listen(64)). Bind errors propagate: the bins turn
    them into the clean 'cannot serve' failure."""
    srv = socket.socket()
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind((host, port))
    srv.listen(backlog)
    face.listen_sock = srv
    face.listen_addr = (host, port)
    face.listening(host, port)
    while True:
        try:
            client, addr = srv.accept()
        except (OSError, RuntimeError) as e:
            if face.stopping:
                return   # the signal box closed the listener; it logs the shutdown
            face.log.error('accept failed (%s), retrying', e)
            time.sleep(0.1)
            continue
        admitted = False
        try:
            if face.client_timeout:
                client.settimeout(face.client_timeout)
            ok, _why = face.conn_gate.admit(addr[0])   # counts always; enforces only when capped
            if not ok:
                face.log.info('connection refused: per-IP limit of %d reached (%s:%d)',
                              face.conn_gate.max_per_ip, *addr[:2])
            elif not face.allowed(addr[0]):
                face.conn_gate.release(addr[0])
                face.log.info('connection rejected: %s:%d not on the connect ACL', *addr[:2])
            elif face.max_clients and face.client_count >= face.max_clients:
                face.conn_gate.release(addr[0])
                face.log.info('connection refused: client limit of %d reached (%s:%d)',
                              face.max_clients, *addr[:2])
            else:
                with face.client_lock:
                    face.client_count += 1
                admitted = True
                threading.Thread(target=_session, args=(face, client, addr), daemon=True).start()
        except (OSError, RuntimeError) as e:
            face.log.error('connection from %s:%d failed before serving (%s)', addr[0], addr[1], e)
            if admitted:
                with face.client_lock:
                    face.client_count -= 1
                face.conn_gate.release(addr[0])
                admitted = False
        finally:
            if not admitted:
                client.close()


def _session(face, client, addr):
    """The session opener + the shared frame loop: register, the suite
    handshake, the face's dispatch per frame, the standard unwind."""
    face.access('client connected: %s:%d', *addr[:2])
    face.on_session()
    key = '%s:%d' % addr[:2]
    with face.client_lock:
        face.clients[key] = {'since': time.monotonic(), 'requests': 0, 'audited': 0}
    try:
        auth_key = face.suite_key()
        if auth_key:
            # the suite auth (when enabled) gates the Modbus loop: the
            # client speaks the handshake first, and one that cannot prove
            # the key is dropped before it ever sees a frame
            try:
                proved = auth_handshake_server(client, auth_key)
            except (ConnectionError, OSError) as e:
                face.log.info('suite auth with %s:%d died mid-handshake (%s)', addr[0], addr[1], e)
                return
            if not proved:
                face.log.info('suite auth failed for %s:%d, closing', *addr[:2])
                return
            face.access('client %s:%d passed the suite handshake', *addr[:2])
        while True:
            face.on_frame()
            try:
                txn, proto, length, unit, pdu = read_frame(client, face.max_pdu)
            except ModbusError as e:
                face.malformed(addr, e)
                break
            with face.client_lock:
                entry = face.clients.get(key)
                if entry:
                    entry['requests'] += 1
            face.frame(client, txn, proto, unit, pdu, addr)
    except (ConnectionError, OSError) as e:
        face.access('client %s:%d disconnected (%s)', *addr[:2], e)
    except Exception as e:
        face.log.error('error handling %s:%d: %s', *addr[:2], e)
    finally:
        with face.client_lock:
            face.client_count -= 1
            entry = face.clients.pop(key, None)
        face.conn_gate.release(addr[0])
        client.close()
        face.on_disconnect(key, entry)
