#!/usr/bin/env python3
"""The in-memory register cache and the poll block planner (stdlib only).

Registers live in two Modbus address spaces — FC3 (holding registers) and
FC4 (input registers) — cached separately: every address in this module is
an (fc, addr) tuple and every range an (fc, start, count) tuple. Blocks
never merge across function codes (a read can only serve one)."""
import threading
import time

from common.human import secs

from .statics import MAX_COUNT


def span(leaves):
    """The register count a group of ranges spans (same address space; the
    leaves are (fc, start, count) ranges)."""
    return leaves[-1][2] + leaves[-1][1] - leaves[0][1]


def build_blocks(ranges, merge_gap):
    """Merge sorted register ranges into as few read blocks as possible,
    per function code.

    Ranges are merged when they share the function code, the gap between
    them is at most merge_gap registers and the block stays within the
    Modbus read limit; 0 disables merging. Blocks may cover registers
    between the listed ranges — those are cached too. Returns
    (fc, start, count, leaves) tuples; the leaves are the (fc, start,
    count) ranges the block covers."""
    blocks = []
    for fc in (3, 4):
        fc_ranges = sorted(set(r for r in ranges if r[0] == fc))
        if not fc_ranges:
            continue
        start = end = None
        group = []
        for _, s, c in fc_ranges:
            e = s + c
            if start is None:
                start, end, group = s, e, [(fc, s, c)]
            elif s - end <= merge_gap and e - start <= MAX_COUNT:
                end = e
                group.append((fc, s, c))
            else:
                blocks.append((fc, start, end - start, tuple(group)))
                start, end, group = s, e, [(fc, s, c)]
        if start is not None:
            blocks.append((fc, start, end - start, tuple(group)))
    return blocks


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

    def describe_ttl(self):
        if not self.cache_ttl:
            return 'never expires'
        return 'for %s' % secs(self.cache_ttl)

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
