#!/usr/bin/env python3
"""Concurrent-connection gate shared by the serving surfaces (docs/SECURITY.md
F11/F13): a total client cap and a per-peer-IP cap, both 0 = no limit. The
servers call admit(ip) at accept and release(ip) when the connection is
done — refusals never count. One implementation for the family: the Modbus
listeners (modbus-cache, modbus-fake-inverter) and the HTTP /metrics
endpoints (the cache's and the fake's own, the scraper's exposition).
GatedHTTPServer is the HTTP shape: gate at process_request, release when
the handler thread is done, a gate_refused hook for the 503 + the log line.
Stdlib only."""
import http.server
import socket
import threading
import time


def rate_limit_503(body):
    """The 503 refusal reply's header block around the tool's one-line
    body (the byte string both serving tools send their rate-limited
    peers; the scraper's and dashboard's bodies differ by the
    '# rate limited: ' prefix — the regtests pin each)."""
    return (b'HTTP/1.1 503 Service Unavailable\r\n'
            b'Content-Type: text/plain; charset=utf-8\r\n'
            b'Cache-Control: no-store\r\n'
            b'Connection: close\r\n\r\n' + body)


def limits_words(max_clients, client_timeout, max_conn_per_ip):
    """The caps' start-log words (the family's one rendering): each cap
    speaks only when it is set (0 = unlimited / off)."""
    return (['max-clients %d' % max_clients] if max_clients else []) + \
           (['client-timeout %gs' % client_timeout] if client_timeout else []) + \
           (['max-conn-per-ip %d' % max_conn_per_ip] if max_conn_per_ip else [])


class ConnGate:
    """ admit(ip) -> (ok, reason): False with reason 'total' or 'per-ip' past
    the caps; release(ip) after serving (or after a refused admit that was
    never counted — releasing a refused ip is harmless, the count floors at
    zero). Thread-safe: every surface accepts from one loop and serves on
    many threads."""

    def __init__(self, max_total=0, max_per_ip=0):
        self.max_total = max(0, int(max_total or 0))
        self.max_per_ip = max(0, int(max_per_ip or 0))
        self._lock = threading.Lock()
        self._total = 0
        self._per_ip = {}

    def admit(self, ip):
        with self._lock:
            if self.max_total and self._total >= self.max_total:
                return False, 'total'
            n = self._per_ip.get(ip, 0) + 1
            if self.max_per_ip and n > self.max_per_ip:
                return False, 'per-ip'
            self._per_ip[ip] = n
            self._total += 1
            return True, ''

    def release(self, ip):
        with self._lock:
            self._total = max(0, self._total - 1)
            n = self._per_ip.get(ip, 1) - 1
            if n <= 0:
                self._per_ip.pop(ip, None)
            else:
                self._per_ip[ip] = n

    def total(self):
        """The concurrent-connection count right now (the connections
        line, inspect)."""
        with self._lock:
            return self._total

    def snapshot(self):
        """(total, {peer ip: count}) right now (show connections)."""
        with self._lock:
            return self._total, dict(self._per_ip)


class GatedHTTPServer(http.server.ThreadingHTTPServer):
    """ThreadingHTTPServer + a ConnGate: admit at process_request (the
    refused peer gets gate_refused — reply 503 and log, the default closes
    silently), release when the handler thread is done. Subclasses call
    setup_gate() on the instance after construction (before serve_forever)
    and may override gate_refused. Ahead of the caps an acl_allows hook
    runs at the same point: a subclass overrides it with the live IP gate
    (the scraper's metrics/acl) and the refused peer is handed to
    acl_refused — the caps never see the peer, the refusal never counted."""
    daemon_threads = True
    allow_reuse_address = True
    gate = None
    RATE_LIMIT_503 = None   # the refusal reply a subclass opts into (the header
                            # block is rate_limit_503(); the body line is the tool's)
    gate_log = None         # the logger the rejection line rides (None = silent)

    def setup_gate(self, max_total=0, max_per_ip=0):
        self.gate = ConnGate(max_total, max_per_ip)

    def _refuse_close(self, request):
        """The refused connection's close: the refusal answers before any
        handler read the request — the peer's bytes sit unread in the
        kernel buffer, and a close() over unread data fires a TCP RST that
        can overtake the refusal reply in the client's receive buffer (the
        client reads the reset, the reply lost — the suite's 503-order
        check flaked exactly so). Half-close first so the reply drains,
        then drain what the peer sent (bounded: a short quiet-gap timeout
        and a byte cap — a hostile peer must not pin the accept loop),
        then close: FIN, not RST."""
        try:
            request.shutdown(socket.SHUT_WR)
        except OSError:
            pass
        try:
            request.settimeout(0.2)
            deadline = time.monotonic() + 0.5
            drained = 0
            while drained < 1048576 and time.monotonic() < deadline:
                chunk = request.recv(65536)
                if not chunk:
                    break
                drained += len(chunk)
        except OSError:
            pass   # the quiet-gap timeout (the peer sent nothing more)
        try:
            request.close()
        except OSError:
            pass

    def gate_refused(self, request, client_address, why):
        if self.gate_log:
            self.gate_log.info('rejected %s: too many concurrent clients (%s, max %d/%d)',
                               client_address, why, self.gate.max_total, self.gate.max_per_ip)
        if self.RATE_LIMIT_503:
            try:
                request.sendall(self.RATE_LIMIT_503)
            except OSError:
                pass
        self._refuse_close(request)

    def acl_allows(self, ip):
        """The connection-ACL hook: the default admits every peer (no
        ACL); the subclasses with an IP knob override with the live gate
        (common/settings/config.py acl_admits on the resolved value)."""
        return True

    def acl_refused(self, request, client_address):
        """The ACL-rejected peer: the default closes without a reply (the
        accept-check reading — nothing was parsed to answer). The close is
        the refusal discipline (_refuse_close) — no reply, but a clean FIN:
        the unread request bytes must not RST the peer mid-read."""
        self._refuse_close(request)

    def process_request(self, request, client_address):
        if not self.acl_allows(client_address[0]):
            self.acl_refused(request, client_address)   # the caps never see the peer
            return
        ok, why = self.gate.admit(client_address[0])
        if not ok:
            self.gate_refused(request, client_address, why)
            return
        try:
            super().process_request(request, client_address)
        except Exception:
            self.gate.release(client_address[0])   # the thread never started
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self.gate.release(client_address[0])
