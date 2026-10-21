"""Difficulty curves as pure functions of (mode, seconds since the start)."""

from dataclasses import replace

from ..settings import VERSUS_ROWS, Difficulty, Kind

RAMP_ROWS_S = 150.0  # row spacing tightens from row_time[0] to row_time[1] over this many seconds
BLOCKED_STEP_S = 25.0  # one more lane may be blocked every this many seconds, up to the mode cap
MIN_ROW_GAP = 300.0


def speed_at(mode: Difficulty, t: float) -> float:
    """World speed in px/s: base + ramp * t^0.8, capped at max_speed."""
    return min(mode.max_speed, mode.base_speed + mode.ramp * pow_08(t))


def versus_rows(mode: Difficulty) -> Difficulty:
    """The mode on a shared road, which ignores the player's lane: rows spaced out to stay as survivable."""
    return replace(mode, row_time=tuple(t * VERSUS_ROWS for t in mode.row_time))


def pow_08(t: float) -> float:
    """t^0.8 for 1e-60 < t <= 1e60 (0 below and for NaN, clamped above), using only + - * /: the fifth root
    of t^4 by Newton's method. Out of that range t^4 underflows or overflows.

    The speed decides every position, so it must be the same bits in the browser and on the server; libm's pow
    is not (musl in the wasm, glibc on the server), while IEEE + - * / are. Within 1 ULP of the exact t^(4/5)
    (``t ** 0.8`` differs from that by up to 5 ULP, as the double 0.8 is not 4/5).
    ponytail: ~11 Newton steps (~1.7 us) from a crude start; seed it from a table if it shows in a profile.
    """
    if not t > 1e-60:
        return 0.0
    t = min(t, 1e60)
    t2 = t * t
    x = t2 * t2
    y = 0.8 * t + 0.2  # >= t^0.8 (weighted AM-GM), so the steps only decrease ...
    while True:
        y2 = y * y
        nxt = y - (y - x / (y2 * y2)) / 5
        if nxt >= y:  # ... until rounding stops them: the same step count everywhere
            return y
        y = nxt


def blocked_cap(mode: Difficulty, t: float) -> int:
    if mode.late_blocked and t >= mode.late_blocked[0]:
        return mode.late_blocked[1]
    return mode.max_blocked


def max_blocked_at(mode: Difficulty, t: float) -> int:
    """How many lanes a single row may block: starts at 2 (or the cap) and grows to the mode cap."""
    return min(blocked_cap(mode, t), 2 + int(max(t, 0.0) // BLOCKED_STEP_S))


def unlocked_kinds(mode: Difficulty, t: float) -> list[Kind]:
    return [kind for kind, at in mode.unlocks if t >= at]


def row_gap(mode: Difficulty, t: float, speed: float) -> float:
    """Distance in px between obstacle rows."""
    k = min(max(t, 0.0) / RAMP_ROWS_S, 1.0)
    seconds = mode.row_time[0] + (mode.row_time[1] - mode.row_time[0]) * k
    return max(MIN_ROW_GAP, speed * seconds)
