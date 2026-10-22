"""Run: RaceScene steps through it, logs replay exactly, feed() rejects junk, shared roads, bots, verdict."""

import json
import random
import re
import subprocess
import sys

import pygame
import pytest

from jogo_de_carro.app import Game
from jogo_de_carro.assets import Assets
from jogo_de_carro.golden import REPLAYS, digest
from jogo_de_carro.run import MAX_EVENTS, BadInput, Run, simulate, verdict
from jogo_de_carro.scenes.base import Transition
from jogo_de_carro.scenes.race import Phase, RaceScene
from jogo_de_carro.settings import CARS, DIFICIL, FACIL, FIXED_DT, MODES, PRICE
from jogo_de_carro.world.autopilot import BOT_LEVELS, Bot, autopilot
from jogo_de_carro.world.world import Controls

HELD = [set(), {pygame.K_w}, {pygame.K_w}, {pygame.K_s}, {pygame.K_w, pygame.K_s}]  # W+S: no boost
# The golden corpus: REPLAYS/<name>.json is race(game, *CORPUS[name]).run.log(), which JOGO_RECORD=<dir> also
# writes; re-record it when test_replay_corpus says so (a rules change, or a change to race()).
CORPUS = {
    "facil_win": ("facil", False, 1, 0, None),
    "normal_crash": ("normal", False, 2, 0.003, None),
    "dificil_win": ("dificil", False, 2, 0, None),
    "infinito_trunks_giveup": ("infinito", False, 7, 0, 200),  # the most trunks of seeds 1-8
    "normal_shared_win": ("normal", True, 1, 0, None),
}


@pytest.fixture(scope="module")
def game(tmp_path_factory):
    return Game(save_path=tmp_path_factory.mktemp("run") / "save.json", seed=5)


@pytest.fixture(scope="module")
def assets(game):
    return game.ctx.assets


def load(name: str) -> dict:
    return json.loads((REPLAYS / f"{name}.json").read_text(encoding="utf-8"))


def post(kind: int, key: int) -> None:
    pygame.event.post(pygame.event.Event(kind, key=key, mod=0, unicode="", scancode=0))


def race(game: Game, mode: str, shared: bool, seed: int, sloppy: float, give_up_s: float | None) -> RaceScene:
    """Play a RaceScene with keyboard events like a human: the autopilot's lane changes, some random ones,
    and stretches of W, S and W+S; give up after ``give_up_s``."""
    game.ctx.save.mode = mode
    scene = RaceScene(game.ctx, seed=seed, shared_road=shared)
    game.scenes.switch(scene, Transition.NONE)
    rng, held, want = random.Random(seed), set(), set()
    while game.scenes.top is scene:
        world = scene.world
        if scene.phase is Phase.RACING:
            steer = rng.choice((-1, 1)) if rng.random() < sloppy else autopilot(world).steer
            if steer and not world.player.changing_lane and not scene.steer:
                key = pygame.K_LEFT if steer < 0 else pygame.K_RIGHT
                post(pygame.KEYDOWN, key)
                post(pygame.KEYUP, key)
            if rng.random() < 0.03:
                want = rng.choice(HELD)
            for key in held - want:
                post(pygame.KEYUP, key)
            for key in want - held:
                post(pygame.KEYDOWN, key)
            held = want
            if give_up_s and world.elapsed >= give_up_s:
                post(pygame.KEYDOWN, pygame.K_r)
        for event in pygame.event.get():
            game.handle(event)
        for _ in range(2):  # a 60 fps frame: two fixed steps
            if game.scenes.top is scene:
                game.scenes.update(FIXED_DT)
    for key in held:
        post(pygame.KEYUP, key)
    pygame.event.get()
    return scene


def same(a: Run, b: Run) -> bool:
    return (a.outcome, a.tick, a.score, a.seconds) == (b.outcome, b.tick, b.score, b.seconds)


@pytest.mark.parametrize("shared", [False, True], ids=["solo", "shared"])
@pytest.mark.parametrize("mode", [m.key for m in MODES])
def test_race_scene_replays_from_its_log(game, assets, mode, shared):
    scene = race(game, mode, shared, seed=len(mode) + shared, sloppy=0.003, give_up_s=30)
    run, log = scene.run, scene.run.log()
    assert run.outcome in ("crash", "giveup") and log["ev"]
    assert same(simulate(assets, log), run)
    replay = RaceScene(game.ctx, run.seed, shared)  # what --replay does
    replay.run.load(log["end"], log["ev"])
    game.scenes.switch(replay, Transition.NONE)
    while game.scenes.top is replay:
        game.scenes.update(FIXED_DT)
    assert same(replay.run, run)


def test_race_scene_win_replays(game, assets):
    scene = race(game, FACIL.key, False, seed=14, sloppy=0.0, give_up_s=None)
    assert scene.run.outcome == "win"
    assert same(simulate(assets, scene.run.log()), scene.run)


@pytest.mark.parametrize("path", sorted(REPLAYS.glob("*.json")), ids=lambda p: p.stem)
def test_replay_corpus(game, assets, path):
    log = json.loads(path.read_text(encoding="utf-8"))
    assert race(game, *CORPUS[path.stem]).run.log() == log, "re-record it"
    run = simulate(assets, log)
    assert run.outcome == path.stem.split("_")[-1]
    assert run.log() == log  # simulating re-logs exactly the inputs it was fed
    if log["mode"] == DIFICIL.key:  # the win is decided by the clock, never by a tick count
        ticks, elapsed = 0, 0.0
        while elapsed < DIFICIL.win_s:
            ticks, elapsed = ticks + 1, elapsed + FIXED_DT
        assert run.tick == ticks == 32401 != round(DIFICIL.win_s / FIXED_DT)


@pytest.mark.parametrize("name", ["normal_crash", "normal_shared_win"])
def test_feeding_batches_equals_the_whole_log(assets, name):
    log = load(name)
    run = Run(assets, log["mode"], log["skin"], log["seed"], log["shared"])
    ev, i = log["ev"], 0
    for k in range(12, log["end"] + 12, 12):  # a client sends its inputs every 12 ticks
        k, j = min(k, log["end"]), i
        while j < len(ev) and ev[j][0] < k:
            j += 1
        run.feed(k, ev[i:j])
        i = j
        run.advance(k - 24)  # a versus client draws its rival 24 ticks late
    run.advance(log["end"])
    run.stop("giveup")
    assert same(run, simulate(assets, log)) and run.log() == log


def test_feed_rejects_junk(assets):
    run = Run(assets, "normal", "yellow", 1, False)
    run.feed(12, [[0, 1], [3, "L"], [5, 0], [5, "R"], [11, 3]])
    good = [[12, 1], [12, "R"], [15, 2], [16, "L"], [20, 0]]  # valid for k=24 after held 3
    junk: list[tuple[object, object]] = [
        (True, good),
        (24.0, good),
        ("24", good),
        (None, good),
        (12, []),  # k must move forward
        (12 + 241, []),
        (2**70, good),
        (24, None),
        (24, {"0": "L"}),
        (24, "LR"),
        (24, [[12, "L"]] * 2),  # two lane changes in one tick
        (24, [[12, 1], [12, 2]]),  # two held changes in one tick
        (24, [[12, 3]]),  # held is already 3
        (24, [[13, "L"], [12, "R"]]),  # ticks go backwards
        (24, [[11, "L"]]),  # before prev_k
        (24, [[24, "L"]]),  # not before k
        (24, [[t, 1 + t % 2] for t in range(12, 24)] * 6),  # 72 events
    ]
    events = [
        [12.0, "L"], [True, "L"], ["12", "L"], [None, "L"], [12, "X"], [12, "l"], [12, True], [12, False],
        [12, 1.0], [12, 4], [12, -1], [12, None], [12, ["L"]], [12], [12, "L", 1], "L", None, {}, 12, [],
    ]  # fmt: skip
    rng = random.Random(0)
    for _ in range(300):  # a valid message with one bad event spliced in
        ev = [list(e) for e in good]
        ev.insert(rng.randrange(len(ev) + 1), rng.choice(events))
        junk.append((24, ev))
    for k, ev in junk:
        with pytest.raises(BadInput):
            run.feed(k, ev)
        assert run.known == 12 and len(run._fed) == 5, "a rejected message changes nothing"
    run.feed(24, good)
    run.advance(24)
    assert run.tick == 24 and run.log()["ev"][-5:] == good

    log = load("normal_crash")
    bad = [{"mode": "x"}, {"mode": ["normal"]}, {"skin": "nope"}, {"skin": ["yellow"]}, {"seed": 1.5}]
    bad += [{"seed": -2}, {"seed": True}]
    bad += [{"shared": 0}, {"ev": "LR"}, {"ev": {"0": "L"}}, {"end": 10**9}]
    for change in bad:
        with pytest.raises(BadInput):
            simulate(assets, log | change)


def test_feed_caps_events_per_run(assets):
    run = Run(assets, "normal", "yellow", 1, False)
    k = 0
    with pytest.raises(BadInput, match="too many events"):
        while True:  # 64 alternating held changes per message, until the run's events are used up
            run.feed(k + 64, [[t, 1 + t % 2] for t in range(k, k + 64)])
            k += 64
    assert k == MAX_EVENTS - MAX_EVENTS % 64


def test_play_ignores_input_past_the_event_cap(assets, monkeypatch):
    monkeypatch.setattr("jogo_de_carro.run.MAX_EVENTS", 51)
    run = Run(assets, "normal", "yellow", 1, False)
    for t in range(60):  # a lane change and a held change on every tick
        run.play(1 - 2 * (t % 2), 1 + t % 2)
    run.stop("giveup")
    assert len(run.ev) == 51 and same(simulate(assets, run.log()), run)  # the server would take it


def test_boost_needs_up_alone(assets):
    both, up = Run(assets, "normal", "yellow", 1, False), Run(assets, "normal", "yellow", 1, False)
    for _ in range(120):
        both.play(0, 3)
        up.play(0, 1)
    assert both.score.distance_points == both.score.meters < up.score.distance_points


def test_every_car_races_alike(game):
    """A car is only a look: each races with car_yellow's hitbox and body, even drawn as thin as can be."""
    assets = Assets()
    thin = pygame.Surface((24, 40), pygame.SRCALPHA)
    thin.fill((200, 40, 40), (10, 2, 4, 36))
    for key in PRICE:
        assets._native[f"car_{key}"] = [thin, thin]
    for name in CORPUS:
        log = load(name)
        run = simulate(assets, log)
        for key in CARS if name == "normal_crash" else ("moto",):  # every car on the short one
            assert same(simulate(assets, log | {"skin": key}), run), (name, key)
    for key in CARS:
        assert assets.bounds(f"car_{key}") == assets.bounds("car_yellow")


@pytest.mark.parametrize("mode", [m.key for m in MODES])
def test_shared_road_is_the_same_for_every_driver(assets, mode):
    def placements(driver, skin: str, shared: bool) -> list:
        run = Run(assets, mode, skin, 99, shared, driver)
        run.world.invulnerable = True
        out, spawn = [], run.world._spawn
        run.world._spawn = lambda p: (out.append(p), spawn(p))
        run.advance(20 * 120)
        return out

    def keep_lane(world):
        return Controls()

    def hug_left(world):
        return Controls(steer=-1 if world.player.lane else 0, vertical=1.0)

    road = placements(autopilot, "yellow", True)
    assert len(road) > 30
    assert placements(keep_lane, "red", True) == road == placements(hug_left, "white", True)
    assert placements(keep_lane, "red", False) != placements(hug_left, "red", False)  # solo: it follows you


def test_bot_levels_are_ordered(assets):
    def survived(level: str, seed: int) -> int:
        run = Run(assets, "normal", "yellow", seed, True, Bot(BOT_LEVELS[level], random.Random(seed ^ 0xB07)))
        run.advance(60 * 120)
        return run.tick

    seeds = range(6)
    assert sum(survived("facil", s) for s in seeds) < sum(survived("dificil", s) for s in seeds)


def test_verdict(assets):
    def run(outcome: str | None, tick: int, score: int = 0) -> Run:
        r = Run(assets, "normal", "yellow", 1, True)
        r.outcome, r.tick, r.score.bonus = outcome, tick, score
        return r

    cases = [
        (run("crash", 100), run(None, 100), None),  # the other may still give up on tick 100
        (run("crash", 100), run(None, 101), -1),
        (run("crash", 100), run("giveup", 90), 1),
        (run("crash", 100, 5), run("crash", 100, 3), 1),
        (run("crash", 100, 5), run("crash", 100, 5), 0),
        (run("win", 21600, 1), run("crash", 21600, 9), 1),
        (run("win", 21600, 1), run(None, 500), None),
        (run("win", 21600, 1), run("win", 21600, 9), -1),
        (run(None, 5), run(None, 5), None),
    ]
    for a, b, want in cases:
        assert verdict(a, b) == want and verdict(b, a) == (None if want is None else -want)


def test_golden_needs_no_display(game):
    out = subprocess.run(
        [sys.executable, "-m", "jogo_de_carro.golden"], capture_output=True, text=True, check=True
    ).stdout
    match = re.search(r"^GOLDEN ([0-9a-f]{64})$", out, re.M)
    assert match and match[1] == digest()  # this process has a display: the masks do not depend on it
