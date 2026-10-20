"""Easing functions and a tiny tween helper (all times in seconds)."""

import math
from collections.abc import Callable
from dataclasses import dataclass

from .settings import FIXED_DT

Ease = Callable[[float], float]


def linear(t: float) -> float:
    return t


# The cubes are plain products: ``x ** 3`` calls libm's pow, which may round differently in the browser (musl,
# inside the wasm) and on the server (glibc), and these eases move the cars, so they decide collisions.
def out_cubic(t: float) -> float:
    u = 1 - t
    return 1 - u * u * u


def in_cubic(t: float) -> float:
    return t**3


def in_out_cubic(t: float) -> float:
    u = -2 * t + 2
    return 4 * t * t * t if t < 0.5 else 1 - u * u * u / 2


def out_back(t: float) -> float:
    c1 = 1.70158
    return 1 + (c1 + 1) * (t - 1) ** 3 + c1 * (t - 1) ** 2


def out_elastic(t: float) -> float:
    if t in (0.0, 1.0):
        return t
    return 2 ** (-10 * t) * math.sin((t * 10 - 0.75) * (2 * math.pi / 3)) + 1


def lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


def clamp(x: float, lo: float, hi: float) -> float:
    return lo if x < lo else hi if x > hi else x


# exp(-rate * FIXED_DT) for the rates the World uses, correctly rounded: the fixed-step simulation never calls
# libm's exp, so the browser and the server agree to the bit (tests/test_rules.py re-derives them).
STEP_DECAY = {
    1.8: float.fromhex("0x1.f8609796fd127p-1"),
    2.2: float.fromhex("0x1.f6b2e81e69db5p-1"),
    4.0: float.fromhex("0x1.ef36f2df78404p-1"),
    9.0: float.fromhex("0x1.db0131b9b7607p-1"),
    18.0: float.fromhex("0x1.b8aeb7444dce0p-1"),
}


def approach(current: float, target: float, rate: float, dt: float) -> float:
    """Frame-rate independent exponential smoothing towards target (rate in 1/s)."""
    k = STEP_DECAY[rate] if dt == FIXED_DT and rate in STEP_DECAY else math.exp(-rate * dt)
    return target + (current - target) * k


@dataclass
class Tween:
    start: float
    end: float
    duration: float
    ease: Ease = out_cubic
    elapsed: float = 0.0

    def update(self, dt: float) -> float:
        self.elapsed = min(self.elapsed + dt, self.duration)
        return self.value

    @property
    def progress(self) -> float:
        return 1.0 if self.duration <= 0 else self.elapsed / self.duration

    @property
    def value(self) -> float:
        return lerp(self.start, self.end, self.ease(self.progress))

    @property
    def done(self) -> bool:
        return self.elapsed >= self.duration
