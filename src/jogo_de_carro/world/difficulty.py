"""Difficulty curves as pure functions of (mode, seconds since the start)."""

from ..settings import Difficulty, Kind

RAMP_ROWS_S = 150.0  # row spacing tightens from row_time[0] to row_time[1] over this many seconds
BLOCKED_STEP_S = 25.0  # one more lane may be blocked every this many seconds, up to the mode cap
MIN_ROW_GAP = 300.0


def speed_at(mode: Difficulty, t: float) -> float:
    """World speed in px/s: base + ramp * t^0.8, capped at max_speed."""
    return min(mode.max_speed, mode.base_speed + mode.ramp * max(t, 0.0) ** 0.8)


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
