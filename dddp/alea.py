#!/usr/bin/env python
"""
Alea PRNG.

This implementation of Alea defaults to a more secure initial internal state.
>>> r1, r2 = Alea(), Alea()
>>> assert r1.state != r2.state, 'r1: %r, r2: %r' % (r1.state, r2.state)

>>> random = Alea("my", 3, "seeds")
>>> (random.s0, random.s1, random.s2)
(0.23922116006724536, 0.6147655111271888, 0.3493568613193929)

>>> random()
0.30802189325913787

>>> random()
0.5190450621303171

>>> random()
0.43635262292809784


>>> random = Alea("my", 3, "seeds")
>>> random()
0.30802189325913787

>>> random = Alea("my", 3, "seeds")

>>> random.random_string(17, UNMISTAKABLE)
'JYRduBwQtjpeCkqP7'

>>> random.random_string(17, UNMISTAKABLE)
'HLxYtpZBtSain84zj'

>>> random.random_string(17, UNMISTAKABLE)
's9XrbWaDC4yCL5NCW'

>>> random.random_string(17, UNMISTAKABLE)
'SCiymgNnZpwda9vSH'

>>> random.random_string(17, UNMISTAKABLE)
'hui3ThSoZrFrdFDTT'


>>> random = Alea("my", 3, "seeds")

>>> random.random_string(43, BASE64)
'tHBM5k8z4TZOmU0zgsv9H4ZIl4CJSXic_T3iF2KFJnm'

"""

from math import floor
import os
import random
import time

UNMISTAKABLE = '23456789ABCDEFGHJKLMNPQRSTWXYZabcdefghijkmnopqrstuvwxyz'
BASE64 = 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_'


class Mash(object):

    """
    `Mash` hasing algorithm.

    >>> mash = Mash()
    >>> mash(' ')
    0.8633289230056107
    >>> mash(' ')
    0.15019597788341343
    >>> mash(' ')
    0.9176952994894236
    """

    def __init__(self):
        """Initialise state."""
        self.n = 0xefc8249d

    def __call__(self, data):
        """Return mash, updating internal state."""
        data = bytes(data)
        for byte in bytes(data):
            self.n += ord(byte)
            h = 0.02519603282416938 * self.n
            self.n = floor(h)
            h -= self.n
            h *= self.n
            self.n = floor(h)
            h -= self.n
            self.n += h * 0x100000000
        res = self.n * 2.3283064365386963e-10  # 2^-32
        return res


class Alea(object):

    """Alea stateful PRNG."""

    c = None
    s0 = None
    s1 = None
    s2 = None

    def __init__(self, *args):
        """Initialise Alea state from seeds (args)."""
        self.seed(args)

    def seed(self, values):
        """Seed internal state from supplied values."""
        if not values:
            # Meteor uses epoch seconds as the seed if no args supplied, we use
            # a much more secure seed by default to avoid hash collisions.
            seed_ids = [int, str, random, self, values, self.__class__]
            random.shuffle(seed_ids)
            values = map(id, seed_ids) + [time.time(), os.urandom(512)]

        mash = Mash()
        self.c = 1
        self.s0 = mash(' ')
        self.s1 = mash(' ')
        self.s2 = mash(' ')

        for val in values:
            self.s0 -= mash(val)
            if self.s0 < 0:
                self.s0 += 1
            self.s1 -= mash(val)
            if self.s1 < 0:
                self.s1 += 1
            self.s2 -= mash(val)
            if self.s2 < 0:
                self.s2 += 1

    @property
    def state(self):
        """Return internal state, useful for testing."""
        return {'c': self.c, 's0': self.s0, 's1': self.s1, 's2': self.s2}

    def __call__(self):
        """Get the next psuedo random number, updating state."""
        t = 2091639 * self.s0 + self.c * 2.3283064365386963e-10  # 2^-32
        self.c = floor(t)
        self.s0 = self.s1
        self.s1 = self.s2
        self.s2 = t - self.c
        return self.s2

    def choice(self, seq):
        """Choose an element from the sequence `seq`."""
        return seq[int(self() * len(seq))]

    def random_string(self, length, alphabet):
        """Return string of `length` elements chosen from `alphabet`."""
        return ''.join(
            self.choice(alphabet) for n in range(length)
        )

    def hex_string(self, digits):
        """Return a hex string of `digits` length."""
        return self.random_string(digits, '0123456789abcdef')


if __name__ == '__main__':
    import doctest
    doctest.testmod()
