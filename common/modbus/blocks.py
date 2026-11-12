"""The poll block planner, hoisted from the cache (the family's gold):
merge sorted address ranges into as few Modbus reads as possible (stdlib
only). Every address is a (fc, addr) tuple and every range an
(fc, start, count) tuple — a cached bit is a word 0/1 like any other.
Blocks never merge across function codes (a read can only serve one)."""
from .protocol import PROTOCOL

MAX_COUNT = PROTOCOL['max_count']              # max registers per FC3/FC4 read
MAX_BITS = PROTOCOL['max_bits']                # max bits per FC1/FC2 read (the Modbus spec's 0x7D0)
READ_FUNCS = tuple(PROTOCOL['read_funcs'])     # FC1 (coils), FC2 (discrete), FC3 (holding), FC4 (input)
BIT_READ_FUNCS = (1, 2)                        # the bit-shaped reads (packed 8 per byte, LSB first)


def span(leaves):
    """The register count a group of ranges spans (same address space; the
    leaves are (fc, start, count) ranges)."""
    return leaves[-1][2] + leaves[-1][1] - leaves[0][1]


def build_blocks(ranges, merge_gap):
    """Merge sorted address ranges into as few read blocks as possible,
    per function code.

    Ranges are merged when they share the function code, the gap between
    them is at most merge_gap addresses and the block stays within the
    Modbus read limit (125 registers on FC3/FC4, 2000 bits on FC1/FC2);
    0 disables merging. Blocks may cover addresses between the listed
    ranges — those are cached too. Returns (fc, start, count, leaves)
    tuples; the leaves are the (fc, start, count) ranges the block
    covers."""
    blocks = []
    for fc in READ_FUNCS:
        fc_ranges = sorted(set(r for r in ranges if r[0] == fc))
        cap = MAX_BITS if fc in BIT_READ_FUNCS else MAX_COUNT
        if not fc_ranges:
            continue
        start = end = None
        group = []
        for _, s, c in fc_ranges:
            e = s + c
            if start is None:
                start, end, group = s, e, [(fc, s, c)]
            elif s - end <= merge_gap and e - start <= cap:
                end = e
                group.append((fc, s, c))
            else:
                blocks.append((fc, start, end - start, tuple(group)))
                start, end, group = s, e, [(fc, s, c)]
        if start is not None:
            blocks.append((fc, start, end - start, tuple(group)))
    return blocks
