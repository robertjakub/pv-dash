#!/usr/bin/env python3
"""Concurrent-connection gate shared by the serving surfaces (docs/AUDIT.md
F11/F13): a total client cap and a per-peer-IP cap, both 0 = no limit. The
servers call admit(ip) at accept and release(ip) when the connection is
done — refusals never count. One implementation for the family: the Modbus
listeners (modbus-cache, modbus-fake-inverter) and the HTTP /metrics
endpoints (the cache's and the fake's own, the scraper's exposition).
GatedHTTPServer is the HTTP shape: gate at process_request, release when
the handler thread is done, a gate_refused hook for the 503 + the log line.
Stdlib only."""
import http.server
import threading


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
        """The concurrent-connection count right now (show status)."""
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
    and may override gate_refused. Beside the caps an acl_allows hook
    runs at the same point: a subclass overrides it with the live IP gate
    (the scraper's metrics/acl) and the refused peer is handed to
    acl_refused — the cap slot released, the refusal never counted."""
    daemon_threads = True
    allow_reuse_address = True
    gate = None

    def setup_gate(self, max_total=0, max_per_ip=0):
        self.gate = ConnGate(max_total, max_per_ip)

    def gate_refused(self, request, client_address, why):
        self.shutdown_request(request)

    def acl_allows(self, ip):
        """The connection-ACL hook: the default admits every peer (no
        ACL); the subclasses with an IP knob override with the live gate
        (common/config.py acl_admits on the resolved value)."""
        return True

    def acl_refused(self, request, client_address):
        """The ACL-rejected peer: the default closes without a reply (the
        accept-check reading — nothing was parsed to answer)."""
        self.shutdown_request(request)

    def process_request(self, request, client_address):
        ok, why = self.gate.admit(client_address[0])
        if not ok:
            self.gate_refused(request, client_address, why)
            return
        if not self.acl_allows(client_address[0]):
            self.gate.release(client_address[0])   # the refusal never counts
            self.acl_refused(request, client_address)
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
