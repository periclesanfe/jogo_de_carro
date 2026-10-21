"""Ranked runs over the site's socket (net.py, plan §5), with stand-ins for pygbag's window and the server."""

import json
import platform
import random
from types import SimpleNamespace

import pygame
import pytest

from jogo_de_carro.app import NEW_BUILD, Game
from jogo_de_carro.net import _JS, Net
from jogo_de_carro.run import MAX_MESSAGE, MAX_STEP, Run
from jogo_de_carro.scenes.base import Transition
from jogo_de_carro.scenes.online import LOST, NO_RESULT, VERIFYING, WaitScene
from jogo_de_carro.scenes.race import NO_PAUSE, Phase, RaceScene
from jogo_de_carro.scenes.results import ResultsScene
from jogo_de_carro.scenes.title import TitleScene
from jogo_de_carro.settings import FIXED_DT
from jogo_de_carro.world.autopilot import autopilot

FRAME = 1 / 60
SEED = 6004799503160661


class Queue(list):
    """A JS array, as pygbag hands it over."""

    @property
    def length(self) -> int:
        return len(self)

    def shift(self) -> str:
        return self.pop(0)


class Socket:
    def __init__(self) -> None:
        self.readyState, self.sent = 0, []

    def send(self, data: str) -> None:
        assert self.readyState == 1, "sent before the socket opened"
        self.sent.append(json.loads(data))

    def close(self) -> None:
        self.readyState = 3


class Storage(dict):
    def getItem(self, key):
        return self.get(key)

    def setItem(self, key, value):
        self[key] = value


class Window:
    """pygbag's window as net.py drives it (two constant scripts), plus the server's side of the socket."""

    def __init__(self) -> None:
        self.jq, self.jws, self.sockets = Queue(), None, []
        self.location, self.sessionStorage = SimpleNamespace(href="/jogo/x/index.html"), Storage()

    def eval(self, js: str) -> None:
        if js == "window.jopen()":
            if self.jws:
                self.jws.close()
            self.jq, self.jws = Queue(), Socket()
            self.sockets.append(self.jws)
        else:
            assert js == _JS, "only constant scripts: no data goes into eval"

    def accept(self) -> None:
        self.jws.readyState = 1

    def reply(self, **msg) -> None:
        self.jq.append(json.dumps(msg))

    def drop(self) -> None:
        self.jws.readyState = 3
        self.jq.append('{"t":"closed"}')

    @property
    def sent(self) -> list[dict]:
        return self.jws.sent


@pytest.fixture
def window(monkeypatch):
    window = Window()
    monkeypatch.setattr(platform, "window", window, raising=False)
    return window


@pytest.fixture
def game(tmp_path, window):
    game = Game(save_path=tmp_path / "save.json", seed=3, net=Net())
    window.accept()
    game.ctx.save.mode = "normal"
    until(game, lambda: not game.scenes.busy, 2)  # the title fades in
    return game


def frames(game: Game, n: int) -> None:
    for _ in range(n):
        game.step(FRAME)


def key(game: Game, k: int, wait: int = 20) -> None:
    pygame.event.post(pygame.event.Event(pygame.KEYDOWN, key=k, mod=0, unicode="", scancode=0))
    pygame.event.post(pygame.event.Event(pygame.KEYUP, key=k, mod=0, unicode="", scancode=0))
    frames(game, wait)


def until(game: Game, condition, seconds: float) -> None:
    for _ in range(int(seconds / FRAME)):
        if condition():
            return
        game.step(FRAME)
    raise AssertionError(f"condition not met within {seconds}s (top scene: {game.scenes.top})")


def jogar(game: Game, window: Window, m: int = 901) -> RaceScene:
    """JOGAR from the title, the server's match and go: the ranked race, as created at go."""
    key(game, pygame.K_RETURN, 10)
    assert isinstance(game.scenes.top, WaitScene)
    assert window.sent[-1] == {"t": "solo", "mode": "normal"}
    window.reply(t="match", m=m, kind="solo", mode="normal", op=None)
    frames(game, 1)
    assert window.sent[-1] == {"t": "ready", "m": m} and game.scenes.top.label == "Preparando…"
    window.reply(t="go", m=m, seed=SEED)
    frames(game, 1)
    race = game.scenes.top
    assert isinstance(race, RaceScene) and (race.online, race.seed, race.realtime) == (m, SEED, True)
    return race


def drive(race: RaceScene, seed: int) -> None:
    """A sloppy autopilot through the keys' path: lane changes and held keys go into the input log."""
    rng = random.Random(seed)

    def controls() -> tuple[int, int]:
        steer = autopilot(race.world).steer if rng.random() > 0.01 else rng.choice((-1, 1))
        return steer, rng.choice((0, 1, 1, 2, 3)) if rng.random() < 0.02 else race.run.held

    race._controls = controls


def inputs(window: Window) -> list[dict]:
    return [m for m in window.sent if m["t"] == "in"]


def check_stream(game: Game, race: RaceScene, ins: list[dict]) -> Run:
    """What the server gets: k always moving on, every 12 ticks until fin, the whole log; fed like the server
    feeds it, it is this run."""
    ks = [m["k"] for m in ins]
    assert all(0 < b - a <= MAX_STEP for a, b in zip([0, *ks], ks, strict=False))
    assert all(k % 12 == 0 for k in ks[:-1]) and ks[-1] == race.run.tick
    assert all(m["m"] == race.online and len(m["ev"]) <= MAX_MESSAGE for m in ins)
    assert [e for m in ins for e in m["ev"]] == race.run.log()["ev"]
    assert [("fin" in m) for m in ins] == [False] * (len(ins) - 1) + [True]
    assert ins[-1]["fin"] == {"outcome": race.run.outcome, "score": race.run.score.total}
    server = Run(game.ctx.assets, "normal", "yellow", SEED, False)
    for m in ins:
        server.feed(m["k"], m["ev"])
        server.advance(m["k"])
    server.stop(ins[-1]["fin"]["outcome"])
    assert (server.outcome, server.tick, server.score) == (race.run.outcome, race.run.tick, race.run.score)
    return server


def test_hello_goes_first_and_nothing_is_sent_before_the_socket_opens(window):
    net = Net()
    net.connect("pink")
    net.send({"t": "solo", "mode": "facil"})
    assert net.poll() == [] and window.sent == []
    window.accept()
    window.reply(t="welcome", me={"id": 7, "nick": "pericles"}, friends=[], challenges=[], requests=0)
    assert net.poll()[0]["t"] == "welcome" and net.me == {"id": 7, "nick": "pericles"}
    hello, solo = window.sent
    assert hello == {
        "t": "hello",
        "build": "dev",
        "py": hello["py"],
        "pg": pygame.version.ver,
        "skin": "pink",
    }
    assert hello["py"].count(".") == 2 and solo == {"t": "solo", "mode": "facil"}
    window.drop()
    assert net.poll() == [{"t": "closed"}] and not net.up
    net.send({"t": "solo", "mode": "facil"})  # dropped: its socket is gone
    net.connect("pink")
    window.accept()
    net.poll()
    assert [m["t"] for m in window.sent] == ["hello"] and len(window.sockets) == 2


def test_a_ranked_run_streams_its_inputs_and_shows_the_official_line(game, window):
    assert [m["t"] for m in window.sent] == ["hello"]
    race = jogar(game, window)
    drive(race, 1)
    game.time_scale = 20.0
    until(game, lambda: race.phase in (Phase.CRASHED, Phase.WON) or race.world.elapsed > 40, 10)
    if race.phase is Phase.RACING:
        key(game, pygame.K_r, 1)
    until(game, lambda: isinstance(game.scenes.top, ResultsScene), 10)
    ins = inputs(window)
    assert len(ins) > 20
    check_stream(game, race, ins)
    results = game.scenes.top
    assert results.stats.official == VERIFYING
    frames(game, 30)
    window.reply(t="result", m=901, run=5531, state="ok", why=None, outcome=race.run.outcome, rank=37)
    frames(game, 30)
    assert results.stats.official == "✓ #37 no ranking Normal"
    key(game, pygame.K_RETURN, 10)  # JOGAR DE NOVO: another ranked run
    assert isinstance(game.scenes.top, WaitScene) and window.sent[-1] == {"t": "solo", "mode": "normal"}


@pytest.mark.parametrize("ticks", [24, 30])
def test_a_give_up_always_moves_k_on(game, window, ticks):
    race = jogar(game, window)
    while race.run.tick < ticks:
        race.update(FIXED_DT)
    key(game, pygame.K_r, 1)
    ins = inputs(window)
    assert [m["k"] for m in ins[-2:]] == ([24, 25] if ticks == 24 else [24, 30])  # 24 was sent already
    assert ins[-1]["fin"]["outcome"] == "giveup"
    check_stream(game, race, ins)
    window.reply(t="result", m=901, state="review", why="top10", rank=None)
    frames(game, 1)
    assert game.scenes.top.stats.official == "Em análise — entra no ranking após revisão"


def test_no_pause_online_and_the_frame_cap_is_a_second(game, window):
    race = jogar(game, window)
    until(game, lambda: race.phase is Phase.RACING, 4)
    for k in (pygame.K_ESCAPE, pygame.K_p):
        game._toast = ("", 0.0)
        key(game, k, 1)
        assert game.scenes.top is race and game._toast[0] == NO_PAUSE
    pygame.event.post(pygame.event.Event(pygame.WINDOWFOCUSLOST))
    frames(game, 1)
    assert game.scenes.top is race and race.phase is Phase.RACING
    race.world.invulnerable = True
    tick = race.run.tick
    game.step(0.5)  # a long frame: the run keeps the wall clock's pace
    assert 59 <= race.run.tick - tick <= 61

    offline = RaceScene(game.ctx)
    game.scenes.switch(offline, Transition.NONE)
    until(game, lambda: offline.phase is Phase.RACING, 4)
    tick = offline.run.tick
    game.step(0.5)  # offline, as before: long hitches are not simulated
    assert not offline.realtime and 11 <= offline.run.tick - tick <= 13
    key(game, pygame.K_ESCAPE, 1)
    assert game.scenes.top is not offline  # pauses


def test_a_result_while_racing_ends_the_run(game, window):
    race = jogar(game, window)
    race.world.invulnerable = True
    until(game, lambda: race.phase is Phase.RACING and race.run.tick > 100, 4)
    sent = len(window.sent)
    window.reply(t="result", m=901, state="rejected", why="ritmo", outcome=None, rank=None)
    frames(game, 1)
    stats = game.scenes.top.stats
    assert stats.official == "Corrida invalidada: ritmo irregular" and stats.reason
    assert len(window.sent) == sent, "the server decided: no fin"


def test_a_dropped_socket_ends_the_run_and_reopens_after_the_race(game, window):
    race = jogar(game, window)
    race.world.invulnerable = True
    until(game, lambda: race.phase is Phase.RACING, 4)
    window.drop()
    frames(game, 1)
    stats = game.scenes.top.stats
    assert (stats.reason, stats.official) == ("Conexão perdida", LOST)
    frames(game, round(2.2 / FRAME))  # out of the race, it reconnects by itself
    window.accept()
    frames(game, 1)
    assert len(window.sockets) == 2 and [m["t"] for m in window.sent] == ["hello"]


def test_a_dropped_socket_before_the_result(game, window):
    race = jogar(game, window)  # nobody steers: it crashes
    game.time_scale = 20.0
    until(game, lambda: race.phase is Phase.CRASHED, 10)
    assert check_stream(game, race, inputs(window)).outcome == "crash"
    window.drop()
    until(game, lambda: isinstance(game.scenes.top, ResultsScene), 10)
    assert game.scenes.top.stats.official == NO_RESULT


@pytest.mark.parametrize("code", ["full", "drain", "rate"])
def test_refusals_show_why_and_esc_goes_back(game, window, code):
    key(game, pygame.K_RETURN, 10)
    window.reply(t="error", code=code, msg=f"Recusado: {code}")
    window.drop()
    frames(game, 1)
    wait = game.scenes.top
    assert isinstance(wait, WaitScene) and wait.label == f"Recusado: {code}"  # the server's words
    frames(game, round(2.2 / FRAME))
    assert len(window.sockets) == 2, "reopened after 2 s"
    key(game, pygame.K_ESCAPE, 40)
    assert isinstance(game.scenes.top, TitleScene)


def test_logged_out_plays_offline(game, window):
    key(game, pygame.K_RETURN, 1)
    window.reply(t="error", code="login", msg="Entre no site para jogar online.")
    window.drop()
    frames(game, 1)
    race = game.scenes.top
    assert game.ctx.net is None and game._toast[0] == "Entre no site para jogar online."
    assert isinstance(race, RaceScene) and race.online is None and not race.realtime and race.official is None
    frames(game, round(3 / FRAME))
    assert len(window.sockets) == 1, "no new socket"


def test_a_new_build_is_fetched_once(game, window, tmp_path):
    key(game, pygame.K_RETURN, 1)
    window.reply(t="error", code="version", msg="Nova versão")
    window.drop()
    frames(game, 1)
    assert game.scenes.top.label == NEW_BUILD and window.location.href == "/jogo/x/index.html"
    frames(game, round(2.1 / FRAME))
    assert window.location.href == "/jogar" and len(window.sockets) == 1  # /jogar hands out the new build

    window.location.href = "/jogo/x/index.html"  # the same build again: its runtime is what differs
    again = Game(save_path=tmp_path / "again.json", seed=3, net=Net())
    window.accept()
    window.reply(t="error", code="version", msg="Nova versão")
    window.drop()
    frames(again, round(2.2 / FRAME))
    assert window.location.href == "/jogo/x/index.html" and again.ctx.net is None, "no reload loop: offline"


def test_another_tab_is_not_fought_and_a_new_car_gets_a_new_hello(game, window):
    window.reply(t="error", code="busy", msg="Aberto em outra aba")
    window.drop()
    frames(game, 1)
    assert game._toast[0] == "Aberto em outra aba"
    frames(game, round(3 / FRAME))
    assert len(window.sockets) == 1, "no new socket by itself: the other tab would lose its own"
    game.ctx.save.skin = "red"
    key(game, pygame.K_RETURN, 1)  # JOGAR takes the socket back, with the car chosen now
    window.accept()
    frames(game, 1)
    assert len(window.sockets) == 2 and [m["t"] for m in window.sent] == ["hello", "solo"]
    assert window.sent[0]["skin"] == "red"


def test_cancelling_leaves_the_match(game, window):
    key(game, pygame.K_RETURN, 30)
    key(game, pygame.K_ESCAPE, 1)  # before the match
    window.reply(t="match", m=5, kind="solo", mode="normal", op=None)
    frames(game, 1)
    assert window.sent[-1] == {"t": "leave", "m": 5}
    until(game, lambda: not game.scenes.busy, 2)
    key(game, pygame.K_RETURN, 30)
    window.reply(t="match", m=6, kind="solo", mode="normal", op=None)
    frames(game, 1)
    key(game, pygame.K_ESCAPE, 1)  # after it
    assert window.sent[-2:] == [{"t": "ready", "m": 6}, {"t": "leave", "m": 6}]
    window.reply(t="go", m=6, seed=SEED)
    frames(game, 30)
    assert isinstance(game.scenes.top, TitleScene)


def test_the_desktop_plays_offline(tmp_path):
    game = Game(save_path=tmp_path / "save.json", seed=3)
    until(game, lambda: not game.scenes.busy, 2)
    key(game, pygame.K_RETURN, 10)  # JOGAR
    race = game.scenes.top
    assert (
        game.ctx.net is None and isinstance(race, RaceScene) and not race.realtime and race.official is None
    )
