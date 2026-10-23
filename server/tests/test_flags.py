"""The bot-likeness rule (plan §6.7) on logs from drivers that read the corridor and drivers that do not."""

import json
import random

import pytest

from jogo_de_carro.golden import REPLAYS
from jogo_de_carro.run import Run
from jogo_de_carro.settings import LANE_CENTERS, LANE_WIDTH, LANES, PLAYER_Y, PROTECT
from jogo_de_carro.world.autopilot import Bot, autopilot
from jogo_de_carro.world.world import Controls, World
from jogo_server import flags, hub


def play(mode: str, seed: int, drive, secs: float = 120) -> dict:
    """The log of a driver's run, as RaceScene would record it (held keys from the vertical control)."""
    run = Run(hub.assets(), mode, "yellow", seed, False)
    while run.outcome is None and run.tick < secs * 120:
        c = drive(run.world)
        run.play(c.steer, 1 if c.vertical < -0.5 else 2 if c.vertical > 0.5 else 0)
    run.stop("giveup")
    return run.log()


def features(log: dict) -> dict:
    """The features of a log, as the hub computes them while it verifies the run."""
    run = Run(hub.assets(), log["mode"], log["skin"], log["seed"], log["shared"])
    run.load(log["end"], log["ev"])
    watch = flags.Watch()
    watch.advance(run, log["end"])
    return watch.features([])


def reacting(seed: int):
    """A person who knows where to go: the corridor, but each move after 0.18 s plus an exponential 0.12 s."""
    rng, state = random.Random(seed), {"target": None, "at": 0.0}

    def drive(world: World) -> Controls:
        base = autopilot(world)
        target = world.spawner.corridor_lane(world.distance + (PLAYER_Y - world.player.y) + 4.0)
        if target != state["target"]:
            state["target"], state["at"] = target, world.elapsed + 0.18 + rng.expovariate(1 / 0.12)
        return base if world.elapsed >= state["at"] else Controls(0, base.vertical)

    return drive


def clear(world: World, lane: int) -> float:
    p, lo, hi = world.player, LANE_CENTERS[lane] - LANE_WIDTH / 2, LANE_CENTERS[lane] + LANE_WIDTH / 2
    gaps = [
        max(0.0, p.body.top - ob.body.bottom)
        for ob in world.obstacles
        if (lane in (ob.lane, getattr(ob, "to_lane", None)) or (ob.body.right > lo and ob.body.left < hi))
        and ob.body.top < p.body.bottom
    ]
    return min(gaps, default=float("inf"))


def screen_reader(world: World) -> Controls:
    """Reads only the screen, every 100 ms: dodges to the freer neighbouring lane when its own is blocked."""
    p = world.player
    if round(world.elapsed * 120) % 12 or p.changing_lane or clear(world, p.lane) > world.speed * 0.9:
        return Controls()
    options = [(clear(world, n), -abs(n - p.lane), n) for n in (p.lane - 1, p.lane + 1) if 0 <= n < LANES]
    free, _, lane = max(options)
    return Controls(steer=lane - p.lane) if free > clear(world, p.lane) else Controls()


@pytest.mark.parametrize(("mode", "seed"), [("facil", 1), ("normal", 2), ("dificil", 3)])
def test_corridor_bots_are_flagged(mode, seed):
    pilot = features(play(mode, seed, autopilot))
    assert pilot["adherence"] >= 0.99 and pilot["median"] == 0 and flags.flagged(pilot)
    bot = features(play(mode, seed, Bot(0.07, random.Random(seed))))
    assert bot["n"] >= 30 and bot["p10"] < 7 and flags.flagged(bot)


@pytest.mark.parametrize(("mode", "seed"), [("facil", 3), ("normal", 1)])
def test_human_like_play_is_not(mode, seed):
    person = features(play(mode, seed, reacting(seed)))
    assert (
        person["n"] >= 30 and person["p10"] >= 18 and not flags.flagged(person)
    )  # the reflex rule did apply
    screen = features(play(mode, seed, screen_reader))
    assert screen["adherence"] < 0.9 and not flags.flagged(screen)


def test_protected_ticks_do_not_count_for_adherence():
    """A corridor bot that leaves the corridor whenever a power makes it safe (plan §5.7) still adheres: only
    the ticks without a power or grace count."""

    def wander(world: World) -> Controls:
        p = world.player
        if p.power not in PROTECT:
            return autopilot(world)
        target = world.spawner.corridor_lane(world.distance + (PLAYER_Y - p.y) + 4.0)
        return Controls(steer=-1 if target > 1 else 1)  # to the far side

    assert features(play("normal", 3, wander))["adherence"] >= 0.99  # 0.90 if every tick counted


@pytest.mark.parametrize("path", sorted(REPLAYS.glob("*.json")), ids=lambda p: p.stem)
def test_the_corpus_is_flagged(path):
    """tests/test_run.py records the corpus by steering with the autopilot (no reaction time at all), so these
    are bot logs too: the hub tests switch the rule off to play them as honest runs."""
    f = features(json.loads(path.read_text(encoding="utf-8")))
    assert f["n"] >= 30 and f["p10"] == 0 and flags.flagged(f)


def test_lag_up_counts_a_sawtooth_not_a_server_stall():
    steady = [[k, round((k / 120 + 0.05) * 1000)] for k in range(12, 120 * 60, 12)]
    assert flags.lag_up(steady) < 0.05  # rounding to the ms

    def arrival(k: int) -> float:  # 1.5 s slower and back, every 10 s
        t = k / 120
        return t + 0.05 + (1.5 * (t % 10) / 2 if t % 10 < 2 else max(0.0, 1.5 - (t % 10 - 2)))

    saw = flags.lag_up([[k, round(arrival(k) * 1000)] for k in range(12, 120 * 60, 12)])
    assert 4 <= saw <= 9  # 1.5 s of rises every 10 s, a minute: 9, less the tops the per-second minima miss

    stuck = [[k, max(ms, 20_000) if 17_000 <= ms < 20_000 else ms] for k, ms in steady]  # 3 s backlog at 20 s
    assert flags.lag_up(stuck) < 0.05
    ended = [[k, 20_000 if ms >= 17_000 else ms] for k, ms in steady if ms < 18_000]  # it ended in the stall
    assert flags.lag_up(ended) < 0.05


def test_thresholds_come_from_the_environment(monkeypatch):
    f = {"n": 40, "p10": 20, "median": 30, "adherence": 0.9}
    assert not flags.flagged(f)
    monkeypatch.setenv("FLAG_MEDIAN", "31")
    assert flags.flagged(f)
