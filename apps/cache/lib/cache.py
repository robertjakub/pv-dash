#!/usr/bin/env python3
"""The in-memory cache and the poll block planner (stdlib only).

Four Modbus address spaces — FC1 (coils), FC2 (discrete inputs), FC3
(holding registers) and FC4 (input registers) — cached separately: every
address in this module is an (fc, addr) tuple and every range an
(fc, start, count) tuple. A cached bit is a word 0/1 like any other. Blocks
never merge across function codes (a read can only serve one)."""
import threading
import time


from common.modbus.blocks import build_blocks, span   # the family's one planner (hoisted)
from .statics import BIT_READ_FUNCS, MAX_BITS, MAX_COUNT, READ_FUNCS


class Cache:
    def __init__(self, ranges, cache_ttl, names=None, ttls=None):
        self.ranges = ranges
        self.cache_ttl = cache_ttl
        self.lock = threading.Lock()
        self.regs = {}     # (fc, addr) -> word
        self.ts = {}       # (fc, addr) -> stamp
        self.names = names or {}   # (fc, start, count) -> name
        self.ttls = ttls or {}     # (fc, start, count) -> per-entry ttl override
        self.word_ttl = {}         # (fc, addr) -> the entry ttl (absent = the global ttl)
        for (fc, start, count), ttl in self.ttls.items():
            for a in range(start, start + count):
                self.word_ttl[(fc, a)] = ttl
        self.range_ok = {r: None for r in ranges}
        self.leaf_errors = {}      # (fc, start, count) -> exception code
        self.map_version = 0

    def update_map(self, ranges, names, ttls=None):
        """Swap the register map: prune removed entries, reset poll status."""
        with self.lock:
            allowed = set()
            for fc, start, count in ranges:
                allowed.update((fc, a) for a in range(start, start + count))
            self.regs = {a: w for a, w in self.regs.items() if a in allowed}
            self.ts = {a: t for a, t in self.ts.items() if a in allowed}
            self.ranges = ranges
            self.names = names
            self.ttls = ttls or {}
            self.word_ttl = {(fc, a): ttl for (fc, start, count), ttl in self.ttls.items()
                             for a in range(start, start + count)}
            self.range_ok = {r: None for r in ranges}
            self.leaf_errors = {}
            self.map_version += 1

    def covers(self, fc, addr, count):
        """True when every requested register is cached and not expired —
        the entry's own ttl when the profile set one, the global otherwise."""
        with self.lock:
            now = time.time()
            for a in range(addr, addr + count):
                if (fc, a) not in self.regs:
                    return False
                ttl = self.word_ttl.get((fc, a))
                if ttl is None:
                    ttl = self.cache_ttl
                if ttl and now - self.ts[(fc, a)] > ttl:
                    return False
            return True

    def words(self, fc, addr, count):
        with self.lock:
            return [self.regs[(fc, a)] for a in range(addr, addr + count)]

    def store(self, fc, addr, words, map_version=None):
        with self.lock:
            if map_version is not None and map_version != self.map_version:
                return False
            now = time.time()
            for i, w in enumerate(words):
                self.regs[(fc, addr + i)] = w
                self.ts[(fc, addr + i)] = now
            return True

    def clear(self):
        """Drop all cached values and poll-status errors; next reads go live."""
        with self.lock:
            dropped = len(self.regs)
            self.regs = {}
            self.ts = {}
            self.leaf_errors = {}
            return dropped

    def snapshot(self):
        """The cache contents for a state dump: ({(fc, addr): word},
        {(fc, addr): stamp})."""
        with self.lock:
            return dict(self.regs), dict(self.ts)

    def restore(self, words, stamps):
        """Write-behind restore: put the dumped words (+ their original
        stamps, so the freshness carries over) back into the cache as they
        were — the poll ranges and the on-demand entries alike; their ttl
        bounds any staleness and the next map swap prunes what the profile
        no longer names. Returns the restored word count."""
        with self.lock:
            for key, word in words.items():
                self.regs[key] = word
                self.ts[key] = stamps.get(key, time.time())
            return len(words)

    def invalidate(self, fc, addr, count):
        """Write-through: drop exactly the cached words a write touched
        (per-register, not the whole cache); the next read of them goes to
        the device and the poller refills them. Returns the dropped count."""
        with self.lock:
            dropped = 0
            for a in range(addr, addr + count):
                if self.regs.pop((fc, a), None) is not None:
                    dropped += 1
                self.ts.pop((fc, a), None)
            return dropped

    def set_leaf_error(self, leaf, code):
        with self.lock:
            self.leaf_errors[leaf] = code

    def clear_leaf_error(self, leaf):
        with self.lock:
            self.leaf_errors.pop(leaf, None)

    def failed_leaf(self, fc, addr, count):
        """Modbus exception code of a failed poll covering any requested register."""
        with self.lock:
            for (lf, start, length), code in self.leaf_errors.items():
                if lf == fc and start < addr + count and addr < start + length:
                    return code
        return None

    def entries(self):
        """Per-range dump for `show cache all`: (fc, start, count, cached word
        count, values (int or None per register), oldest age in s or None,
        poll error code or None, the entry's effective ttl)."""
        with self.lock:
            now = time.time()
            out = []
            for (fc, start, count) in self.ranges:
                values = [self.regs.get((fc, a)) for a in range(start, start + count)]
                words = sum(1 for v in values if v is not None)
                ages = [now - self.ts[(fc, a)] for a in range(start, start + count)
                        if (fc, a) in self.ts]
                oldest = max(ages) if ages else None
                ttl = self.ttls.get((fc, start, count))
                out.append((fc, start, count, words, values, oldest,
                            self.leaf_errors.get((fc, start, count)), ttl))
            return out
