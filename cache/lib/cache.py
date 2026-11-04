#!/usr/bin/env python3
"""The in-memory register cache and the poll block planner (stdlib only)."""
import threading
import time


def span(leaves):
    return leaves[-1][0] + leaves[-1][1] - leaves[0][0]


def build_blocks(ranges, merge_gap):
    """Merge sorted register ranges into as few read blocks as possible.

    Ranges are merged when the gap between them is at most merge_gap
    registers and the block stays within the Modbus read limit; 0 disables
    merging. Blocks may cover registers between the listed ranges — those
    are cached too.
    """
    blocks = []
    start = end = None
    group = []
    for s, c in sorted(set(ranges)):
        e = s + c
        if start is None:
            start, end, group = s, e, [(s, c)]
        elif s - end <= merge_gap and e - start <= 125:
            end = e
            group.append((s, c))
        else:
            blocks.append((start, end - start, tuple(group)))
            start, end, group = s, e, [(s, c)]
    if start is not None:
        blocks.append((start, end - start, tuple(group)))
    return blocks


class Cache:
    def __init__(self, ranges, cache_ttl, names=None):
        self.ranges = ranges
        self.cache_ttl = cache_ttl
        self.lock = threading.Lock()
        self.regs = {}
        self.ts = {}
        self.names = names or {}
        self.range_ok = {r: None for r in ranges}
        self.leaf_errors = {}
        self.map_version = 0

    def update_map(self, ranges, names):
        """Swap the register map: prune removed entries, reset poll status."""
        with self.lock:
            allowed = set()
            for start, count in ranges:
                allowed.update(range(start, start + count))
            self.regs = {a: w for a, w in self.regs.items() if a in allowed}
            self.ts = {a: t for a, t in self.ts.items() if a in allowed}
            self.ranges = ranges
            self.names = names
            self.range_ok = {r: None for r in ranges}
            self.leaf_errors = {}
            self.map_version += 1

    def covers(self, addr, count):
        """True when every requested register is cached and not expired."""
        with self.lock:
            now = time.time()
            for a in range(addr, addr + count):
                if a not in self.regs:
                    return False
                if self.cache_ttl and now - self.ts[a] > self.cache_ttl:
                    return False
            return True

    def describe_ttl(self):
        if not self.cache_ttl:
            return 'never expires'
        return 'for %gs' % self.cache_ttl

    def words(self, addr, count):
        with self.lock:
            return [self.regs[a] for a in range(addr, addr + count)]

    def store(self, addr, words, map_version=None):
        with self.lock:
            if map_version is not None and map_version != self.map_version:
                return False
            now = time.time()
            for i, w in enumerate(words):
                self.regs[addr + i] = w
                self.ts[addr + i] = now
            return True

    def clear(self):
        """Drop all cached values and poll-status errors; next reads go live."""
        with self.lock:
            dropped = len(self.regs)
            self.regs = {}
            self.ts = {}
            self.leaf_errors = {}
            return dropped

    def set_leaf_error(self, leaf, code):
        with self.lock:
            self.leaf_errors[leaf] = code

    def clear_leaf_error(self, leaf):
        with self.lock:
            self.leaf_errors.pop(leaf, None)

    def failed_leaf(self, addr, count):
        """Modbus exception code of a failed poll covering any requested register."""
        with self.lock:
            for (start, length), code in self.leaf_errors.items():
                if start < addr + count and addr < start + length:
                    return code
        return None
