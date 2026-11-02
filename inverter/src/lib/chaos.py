#!/usr/bin/env python3
"""Optional chaos injection: a seeded dice layer the server consults per request."""
import random

MODES = ('garbage', 'short', 'lying', 'txn', 'unit', 'stall', 'dropout', 'exception')


class Chaos:
    """With probability `p`, a request is answered hostile and the connection dropped."""

    def __init__(self, probability, seed=None):
        self.p = max(0.0, min(1.0, float(probability)))
        self.seed = seed
        self.rng = random.Random(seed)
        self.hits = 0

    def hit(self):
        return self.p > 0.0 and self.rng.random() < self.p

    def mode(self):
        self.hits += 1
        return self.rng.choice(MODES)

    def set_probability(self, p):
        self.p = max(0.0, min(1.0, float(p)))

    def reseed(self, seed=None):
        self.seed = seed
        self.rng = random.Random(seed)
