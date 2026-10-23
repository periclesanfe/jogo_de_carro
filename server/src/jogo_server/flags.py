"""Bot-likeness of a ranked run (plan §6.7), from what only the server knows: the spawner's safe corridor.

A bot that reads the corridor (the seed gives it away) sits in it and moves the moment it moves; a person
reads the screen, anticipates some moves and reacts late to others. Features never leave the server; the
thresholds come from the environment (FLAG_*) so they can be tuned on beta logs without a deploy.

Not caught: a corridor reader that waits like a person (100-250 ms a move) and still never crashes, since the
spawner leaves 0.12 s of slack per planned move (plan §6.10). Not flagged is not "human": such a bot ranks at
once, top 10 included, until the admin rejects it (the owner took that risk over holding every top-10 run).
"""

import itertools
import os
import statistics

from jogo_de_carro.run import Run
from jogo_de_carro.settings import FIXED_DT, PLAYER_Y

RULE = {"min_n": 30, "p10": 7, "median": 12, "adherence": 0.99}  # FLAG_MIN_N, FLAG_P10... in the env win


class Watch:
    """Follows a Run tick by tick: the hub steps live runs through it, so the features cost no second sim."""

    def __init__(self) -> None:
        self.ticks = self.on = self.boost = 0
        self.target: int | None = None
        self.pending: tuple[int, int] | None = None  # (tick, lane) of a corridor move not followed yet
        self.react: list[int] = []

    def advance(self, run: Run, to: int) -> None:
        """run.advance(to), watching each tick."""
        world, player = run.world, run.world.player
        while run.outcome is None and run.tick < min(to, run.known):
            tick, lane, logged = run.tick, player.lane, len(run.ev)
            target = world.spawner.corridor_lane(world.distance + (PLAYER_Y - player.y) + 4.0)  # autopilot's
            self.ticks += 1
            self.on += lane == target
            if target != self.target:
                self.target, self.pending = target, ((tick, target) if target != lane else None)
            run.advance(tick + 1)
            self.boost += run.held == 1
            steer = next((v for t, v in run.ev[logged:] if v in ("L", "R")), None)
            if self.pending and steer and (self.pending[1] > lane) == (steer == "R"):
                self.react.append(tick - self.pending[0])
                self.pending = None

    def features(self, arr: list) -> dict:
        react = sorted(self.react)
        return {
            "adherence": self.on / max(1, self.ticks),
            "n": len(react),
            "p10": react[len(react) // 10] if react else None,
            "median": statistics.median(react) if react else None,
            "boost": self.boost / max(1, self.ticks),
            "lag_up": lag_up(arr),
        }


def lag_up(arr: list) -> float:
    """Seconds per minute the run fell behind real time in steps: per wall-clock second the least lag of its
    messages, then the sum of the rises. A sawtooth of slowing down and catching up under the 2 s limit
    adds up; a server stall does not (its backlog arrives at once, and the newest message sets the minimum).
    The last second is left out: a run that ends inside a stall has no newer message to set it.
    arr: [k, arrival ms after t0] per message."""
    least: dict[int, float] = {}
    for k, ms in arr:
        s = ms // 1000
        least[s] = min(least.get(s, 1e9), ms / 1000 - k * FIXED_DT)
    lags = [least[s] for s in sorted(least)][:-1]
    rises = sum(max(0.0, b - a) for a, b in itertools.pairwise(lags))
    minutes = max(1.0, len(least) / 60)  # wall-clock seconds with messages
    return round(rises / minutes, 3)


def flagged(f: dict) -> bool:
    """The rule for ranks 1-100: (n >= MIN_N and (p10 < P10 or median < MEDIAN)) or adherence >= ADHERENCE.
    lag_up is only recorded until it is calibrated on beta data."""
    r = {k: float(os.environ.get(f"FLAG_{k.upper()}") or v) for k, v in RULE.items()}
    return (f["n"] >= r["min_n"] and (f["p10"] < r["p10"] or f["median"] < r["median"])) or f[
        "adherence"
    ] >= r["adherence"]
