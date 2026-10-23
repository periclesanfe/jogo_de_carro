"""Races over the site's socket (net.py, plan §5): ranked runs, AMIGOS, invites and live races, with
stand-ins for pygbag's window and the server."""

import copy
import json
import platform
import random
from types import SimpleNamespace

import pygame
import pytest

from jogo_de_carro.app import NEW_BUILD, Game
from jogo_de_carro.net import _JS, Net
from jogo_de_carro.run import MAX_MESSAGE, MAX_STEP, Run
from jogo_de_carro.save import load
from jogo_de_carro.scenes import garage, online, race, results, title, versus
from jogo_de_carro.scenes.base import Transition
from jogo_de_carro.scenes.garage import KEYS, GarageScene
from jogo_de_carro.scenes.online import LOST, NO_RESULT, VERIFYING, AmigosScene, ConviteScene, WaitScene
from jogo_de_carro.scenes.race import NO_PAUSE, Outcome, Phase, RaceScene
from jogo_de_carro.scenes.results import VERDICTS, ResultsScene
from jogo_de_carro.scenes.title import TitleScene
from jogo_de_carro.scenes.versus import (
    CATCH_UP,
    HOLD_S,
    LAG,
    UNSTABLE,
    LiveScene,
    RecordingScene,
    VersusScene,
)
from jogo_de_carro.settings import FIXED_DT, FLAME, MODE_BY_KEY, MUTED
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
    server = Run(game.ctx.assets, "normal", "yellow", SEED, race.run.shared)
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
    window.reply(t="welcome", me={"id": 7, "nick": "pericles"}, friends=[], requests=0)
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


# --- AMIGOS, invites and live races (M4) ------------------------------------------------------------------

FRIENDS = [
    {"id": 42, "nick": "ana_42", "s": "menu"},
    {"id": 43, "nick": "bia", "s": "racing"},
    {"id": 44, "nick": "caio", "s": "off"},
]
ANA = {"id": 42, "nick": "ana_42"}
M = 77


def welcome(
    game: Game, window: Window, friends: list = FRIENDS, requests: int = 0, challenges: tuple = ()
) -> None:
    me = {"id": 7, "nick": "pericles"}
    friends, challenges = copy.deepcopy(friends), list(challenges)
    window.reply(t="welcome", me=me, friends=friends, requests=requests, challenges=challenges, coins=320)
    frames(game, 2)


def amigos(game: Game, window: Window, requests: int = 0, challenges: tuple = ()) -> AmigosScene:
    """AMIGOS from the title: its 5th item once the socket is up."""
    welcome(game, window, requests=requests, challenges=challenges)
    assert list(game.scenes.top.menu.labels) == [
        "JOGAR",
        "SKIN",
        "DIFICULDADE",
        "CONTRA O BOT",
        "AMIGOS",
        "SAIR",
    ]
    for _ in range(4):
        key(game, pygame.K_DOWN, 2)
    key(game, pygame.K_RETURN, 40)
    scene = game.scenes.top
    assert isinstance(scene, AmigosScene)
    return scene


def invited(game: Game, window: Window, id: str, mode: str = "facil", ttl: int = 30) -> None:
    window.reply(**{"t": "invited", "id": id, "from": ANA, "mode": mode, "ttl": ttl})
    frames(game, 1)


@pytest.fixture
def drawn(monkeypatch) -> list[str]:
    """Every string the online, versus, results, title and garage scenes draw."""
    seen: list[str] = []
    for module in (online, versus, results, title, garage):
        real = module.blit_text
        monkeypatch.setattr(
            module,
            "blit_text",
            lambda surface, s, *a, real=real, **k: (seen.append(s), real(surface, s, *a, **k))[1],
        )
    return seen


def buttons(scene: AmigosScene) -> list[tuple[str, str]]:
    return [(label, scene.rows[i].get("nick", scene.rows[i].get("from"))) for label, i in scene.actions]


def test_amigos_lists_every_friend_online_first_as_presence_changes(game, window, drawn):
    scene = amigos(game, window, requests=2)
    assert [row["nick"] for row in scene.rows] == ["ana_42", "bia", "caio"]  # in the menu, racing, off
    assert buttons(scene) == [
        ("CORRER AGORA", "ana_42"),  # only to a friend in the menu
        ("DESAFIAR", "ana_42"),  # to anyone
        ("DESAFIAR", "bia"),
        ("DESAFIAR", "caio"),
    ]
    assert "2 pedidos de amizade — veja no site" in drawn and "offline" in drawn
    key(game, pygame.K_DOWN, 2)
    key(game, pygame.K_RIGHT, 2)  # any arrow moves along the buttons
    assert buttons(scene)[scene.menu.index] == ("DESAFIAR", "bia")
    window.reply(t="presence", id=44, s="menu")
    window.reply(t="presence", id=99, s="menu")  # not a friend (yet): nothing to show
    frames(game, 2)
    assert [row["nick"] for row in scene.rows] == ["ana_42", "caio", "bia"]
    assert buttons(scene)[scene.menu.index] == ("DESAFIAR", "bia"), "the focus stays on its button"
    for id in (42, 43, 44):
        window.reply(t="presence", id=id, s="off")
    frames(game, 2)
    assert buttons(scene) == [("DESAFIAR", "ana_42"), ("DESAFIAR", "bia"), ("DESAFIAR", "caio")]
    welcome(game, window, friends=[])
    drawn.clear()
    frames(game, 2)
    assert scene.rows == [] and "Nenhum amigo ainda" in drawn
    key(game, pygame.K_ESCAPE, 40)
    title = game.scenes.top
    assert isinstance(title, TitleScene) and title.menu.labels[title.menu.index] == "AMIGOS"
    window.drop()  # AMIGOS goes: the focus goes to JOGAR, not onto SAIR
    frames(game, 1)
    assert title.menu.labels[title.menu.index] == "JOGAR" and "AMIGOS" not in title.menu.labels


def test_an_invite_waits_and_esc_cancels_it(game, window):
    amigos(game, window)
    key(game, pygame.K_RETURN, 40)  # CORRER AGORA with ana_42, in the menu's mode
    wait = game.scenes.top
    assert isinstance(wait, WaitScene) and wait.label == "Aguardando ana_42…"
    assert window.sent[-1] == {"t": "invite", "to": 42, "mode": "normal"}
    window.reply(t="waiting", id="i_1")
    frames(game, 1)
    key(game, pygame.K_ESCAPE, 40)
    assert window.sent[-1] == {"t": "invite_cancel", "id": "i_1"} and isinstance(game.scenes.top, AmigosScene)

    key(game, pygame.K_RETURN, 40)  # turned down: the reason stays up, and Esc has nothing to cancel
    window.reply(t="waiting", id="i_2")
    window.reply(t="invite_gone", id="i_2", why="declined")
    frames(game, 1)
    wait, sent = game.scenes.top, len(window.sent)
    assert wait.refused and wait.label == "ana_42 recusou o convite"
    key(game, pygame.K_ESCAPE, 40)
    assert len(window.sent) == sent

    key(game, pygame.K_RETURN, 40)  # Esc before the server's waiting: the invite is cancelled when it comes
    key(game, pygame.K_ESCAPE, 1)
    window.reply(t="waiting", id="i_3")
    frames(game, 1)
    assert window.sent[-1] == {"t": "invite_cancel", "id": "i_3"}

    game.scenes.switch(WaitScene(game.ctx), Transition.NONE)  # JOGAR: a ranked run takes no live match
    assert window.sent[-1] == {"t": "solo", "mode": "normal"}
    window.reply(t="match", m=5, kind="live", mode="normal", op={"nick": "ana_42", "skin": "red"})
    frames(game, 1)
    assert window.sent[-1] == {"t": "leave", "m": 5} and game.scenes.top.m is None


def test_an_invite_comes_in_over_the_menus(game, window, drawn):
    welcome(game, window)
    title = game.scenes.top
    invited(game, window, "i_9")
    convite = game.scenes.top
    assert isinstance(convite, ConviteScene) and convite.below is title
    frames(game, 1)
    assert "ana_42 te chamou para correr (Fácil)" in drawn
    key(game, pygame.K_ESCAPE, 2)  # RECUSAR
    assert window.sent[-1] == {"t": "invite_reply", "id": "i_9", "ok": False} and game.scenes.top is title

    invited(game, window, "i_10")
    window.reply(t="invite_gone", id="i_10", why="cancelled")
    frames(game, 1)
    assert game.scenes.top is title and game._toast[0] == "ana_42 cancelou o convite"
    invited(game, window, "i_11", ttl=1)  # unanswered
    frames(game, 70)
    assert game.scenes.top is title and game._toast[0] == "O convite expirou"

    invited(game, window, "i_12")
    button = game.scenes.top.menu.buttons[0].rect.center  # ACEITAR, with the mouse
    pygame.event.post(pygame.event.Event(pygame.MOUSEMOTION, pos=button, rel=(0, 0), buttons=(0, 0, 0)))
    pygame.event.post(pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=button, button=1))
    frames(game, 2)
    wait = game.scenes.top
    assert isinstance(wait, WaitScene) and (wait.label, wait.mode.key) == ("Preparando…", "facil")
    assert window.sent[-1] == {"t": "invite_reply", "id": "i_12", "ok": True}
    invited(game, window, "i_13")
    assert game.scenes.top is wait, "never over a wait"
    window.reply(t="match", m=M, kind="live", mode="facil", op={"nick": "ana_42", "skin": "red"})
    void = {"state": "rejected", "why": "anulada", "outcome": None, "score": None, "secs": None}
    window.reply(t="result", m=M, run=M, **void, rank=None, verdict=None, op=None)  # she was not ready
    frames(game, 1)
    assert wait.refused and wait.label == "Corrida anulada"

    bot = VersusScene(game.ctx, "medio")
    game.scenes.switch(bot, Transition.NONE)
    invited(game, window, "i_14")
    assert game.scenes.top is bot, "never over a race"


def her_inputs(game: Game, ticks: int) -> Run:
    """ana_42's run: the autopilot on the shared road, toggling UP every 3 ticks (many events)."""
    run = Run(game.ctx.assets, "facil", "red", SEED, True, rival="yellow")
    while run.tick < ticks:
        run.play(autopilot(run.world).steer, (run.tick // 3) % 2)
    assert run.outcome is None
    return run


def op(her: Run, a: int, b: int) -> dict:
    """What the server relays of her inputs for the ticks [a, b)."""
    return {"t": "op", "m": M, "k": b, "ev": [e for e in her.ev if a <= e[0] < b]}


def live(game: Game, window: Window) -> LiveScene:
    """ana_42 invites (Fácil, while the menu is on Normal); ACEITAR, the server's match and go."""
    welcome(game, window)
    game.ctx.save.skin = "blue"  # changed after the hello: the race keeps the car the server knows
    invited(game, window, "i_1")
    key(game, pygame.K_RETURN, 2)  # ACEITAR
    assert window.sent[-1] == {"t": "invite_reply", "id": "i_1", "ok": True}
    window.reply(t="match", m=M, kind="live", mode="facil", op={"nick": "ana_42", "skin": "red"})
    frames(game, 1)
    assert window.sent[-1] == {"t": "ready", "m": M} and game.scenes.top.label == "Preparando…"
    window.reply(t="go", m=M, seed=SEED)
    frames(game, 1)
    race = game.scenes.top
    assert isinstance(race, LiveScene) and race.realtime and len(window.sockets) == 1
    assert (race.online, race.seed, race.mode.key) == (M, SEED, "facil")
    assert (race.run.skin, race.rival.skin, race.rival.shared, race.run.shared) == (
        "yellow",
        "red",
        True,
        True,
    )
    while race.phase is Phase.COUNTDOWN:
        race.update(FIXED_DT)
    return race


def tick(race: LiveScene, her: Run | None = None) -> int:
    """One of my ticks, then her inputs, if they come on time (her messages every 12 ticks, as mine);
    how far she moved."""
    before = race.rival.tick
    race.update(FIXED_DT)
    assert race.rival.tick <= max(0, race.ticks - LAG), "never shown ahead of the gate"
    if her and race.ticks % 12 == 0 and race.rival.known < race.ticks <= her.tick:
        race.on_net(op(her, race.rival.known, race.ticks))
    return race.rival.tick - before


def test_the_live_rival_runs_24_ticks_behind_and_catches_up_gently(game, window):
    race = live(game, window)
    race.world.invulnerable = True
    her = her_inputs(game, 900)
    while race.ticks < 300:  # on time: exactly LAG ticks behind me
        tick(race, her)
        assert race.rival.tick == max(0, race.ticks - LAG)
    assert race.rival.known == 300

    while race.ticks < 384:  # her inputs stop coming: she stands where they end
        tick(race)
        assert not race.unstable
    tick(race)
    assert race.ticks - LAG - race.rival.tick > UNSTABLE and race.state() == ("conexão instável", FLAME)
    race.draw(game.screen)
    while race.ticks < 400:
        tick(race)

    for k in range(312, 432, 12):  # then a burst, up to my last k + 24
        race.on_net(op(her, k - 12, k))
    moved = [tick(race) for _ in range(30)]
    assert race.lag == UNSTABLE, "after 100 ticks without her inputs, she is drawn further back"
    assert max(moved) == CATCH_UP and moved[-1] == 1 and race.rival.tick == race.ticks - race.lag
    assert not race.unstable

    race.on_net(op(her, 420, 700))  # one late batch, longer and fuller than a client may send
    for junk in (
        op(her, 600, 650),
        {"t": "op", "m": M, "k": 800, "ev": [[750, "X"]]},
        {**op(her, 700, 720), "m": 5},
    ):
        race.on_net(junk)  # stale, malformed, another match: ignored
    assert race.rival.known == 700
    while race.ticks < 760:
        tick(race)
    assert race.rival.tick == 700

    race.on_net(op(her, 700, 900))
    race.on_net({"t": "op_end", "m": M, "k": 900, "why": "ritmo"})  # she fell behind: a forfeit
    while race.ticks < 1000:
        tick(race)
    rival = race.rival
    assert (rival.tick, rival.outcome) == (900, "ritmo") and race.state() == ("SAIU", MUTED)
    assert (rival.score, rival.world.distance) == (her.score, her.world.distance), "replayed exactly"
    race.draw(game.screen)

    sent = len(inputs(window))
    assert all(m["m"] == M and m["k"] % 12 == 0 for m in inputs(window))
    there = dict(race.kept)[996]  # my score where the server decided (8.3 s), not where my run got to
    assert there != race.run.score
    result = {
        "t": "result",
        "m": M,
        "run": M,
        "state": "ok",
        "why": None,
        "outcome": "decided",
        "score": 1,
        "secs": 8.3,
    }
    race.on_net(
        {**result, "rank": None, "verdict": "win", "op": {"nick": "ana_42", "score": 90, "secs": 7.5}}
    )
    assert race.phase is Phase.WON and race.banner[0] == "VITÓRIA!"
    until(game, lambda: isinstance(game.scenes.top, ResultsScene), 4)
    stats = game.scenes.top.stats
    assert (VERDICTS[stats.verdict][0], stats.reason) == ("VOCÊ VENCEU!", "ana_42 ficou para trás aos 0:07")
    assert (stats.seconds, stats.score) == (8.3, there), "the server's numbers, as her card shows them"
    assert stats.rival == "ana_42: 90 pontos · ficou para trás aos 0:07" and stats.official is None
    assert len(inputs(window)) == sent, "the result ended my run: nothing more to send"
    assert game.scenes.top.menu.labels[0] == "REVANCHE"
    frames(game, 30)
    key(game, pygame.K_RETURN, 10)  # REVANCHE: a new invite, same friend and mode
    wait = game.scenes.top
    assert isinstance(wait, WaitScene) and wait.label == "Aguardando ana_42…"
    window.accept()  # with the car chosen meanwhile, so on a new socket
    frames(game, 1)
    assert [m["t"] for m in window.sent] == ["hello", "invite"] and window.sent[0]["skin"] == "blue"
    assert window.sent[-1] == {"t": "invite", "to": 42, "mode": "facil"}


def test_crashing_first_waits_for_the_result(game, window):
    race = live(game, window)  # nobody steers me: a crash
    her = her_inputs(game, 3000)
    invited(game, window, "i_4")  # held over the race...
    window.reply(t="invite_gone", id="i_4", why="cancelled")  # ...and over before it ends: never shown
    while race.over is None:
        tick(race, her)
    assert race.over is Outcome.CRASH and game.scenes.top is race
    assert inputs(window)[-1]["fin"] == {"outcome": "crash", "score": race.run.score.total}
    at = race.rival.tick
    for _ in range(60):
        tick(race, her)
    assert race.rival.tick == at + 60 and game.scenes.top is race, "she drives on until the server decides"
    result = {"t": "result", "m": M, "run": 1, "state": "ok", "why": None, "outcome": "crash", "score": 5}
    race.on_net(
        {
            **result,
            "secs": race.run.seconds,
            "rank": None,
            "verdict": "loss",
            "op": {"nick": "ana_42", "score": 9, "secs": 13.0},
        }
    )
    stats = game.scenes.top.stats
    assert (VERDICTS[stats.verdict][0], stats.rival) == ("VOCÊ PERDEU", "ana_42: 9 pontos")
    assert stats.reason == f"Você bateu aos 0:{int(race.run.seconds):02d}"
    frames(game, 2)
    assert isinstance(game.scenes.top, ResultsScene)


def test_after_the_result_the_rival_drives_on_for_show(game, window):
    """The result comes during my crash's slow motion: she won, so she cruises on (no more of her inputs
    will come), instead of standing still on her half."""
    race = live(game, window)  # nobody steers me: a crash
    her = her_inputs(game, 3000)
    while race.phase is not Phase.CRASHED:
        tick(race, her)
    result = {"t": "result", "m": M, "run": M, "state": "ok", "why": None, "outcome": "crash", "score": 5}
    race.on_net({**result, "secs": 1.0, "rank": None, "verdict": "loss", "op": {"nick": "ana_42"}})
    for _ in range(40):
        tick(race)
    rival, distance = race.rival, race.rival.world.distance
    for _ in range(10):
        tick(race)
    assert rival.tick == rival.known and rival.outcome is None and rival.world.distance > distance
    assert rival.world.invulnerable and game.scenes.top is race


def test_a_late_rival_is_drawn_smoothly_further_back(game, window):
    """Her inputs reach me 36 ticks late (about 75 ms each way): she is drawn 48 ticks behind, a tick at a
    time, instead of stopping and jumping at each batch."""
    race = live(game, window)
    race.world.invulnerable = True
    her = her_inputs(game, 700)
    moved = []
    while race.ticks < 600:
        before = race.rival.tick
        race.update(FIXED_DT)
        if race.ticks % 12 == 0 and race.ticks > 36:
            race.on_net(op(her, race.rival.known, race.ticks - 36))
        moved.append(race.rival.tick - before)
    assert race.lag == 36 + 12 and set(moved[100:]) == {1} and not race.unstable
    race.on_net({"t": "op_end", "m": M, "k": 700, "why": "giveup"})  # past my gate: sent with the result
    result = {"t": "result", "m": M, "run": M, "state": "ok", "why": None, "outcome": "decided", "score": 5}
    race.on_net({**result, "secs": 5.0, "rank": None, "verdict": "win", "op": {"nick": "ana_42"}})
    for _ in range(30):
        tick(race)
    assert (race.rival.tick, race.rival.outcome) == (564, "giveup") and race.state() == ("DESISTIU", MUTED)


def test_live_races_end_without_a_result(game, window):
    race = live(game, window)
    while race.over is None:
        tick(race)
    invited(game, window, "i_6")  # held while the race waits for its result
    assert game.scenes.top is race
    race.waited = HOLD_S  # the server never answered
    tick(race)
    assert game.scenes.top.stats.reason == "O servidor não respondeu"
    frames(game, 1)  # the results are up: now the invite
    convite = game.scenes.top
    assert isinstance(convite, ConviteScene) and convite.id == "i_6" and convite.left < 30
    key(game, pygame.K_ESCAPE, 2)  # RECUSAR
    assert window.sent[-1] == {"t": "invite_reply", "id": "i_6", "ok": False}

    race = live(game, window)
    race.world.invulnerable = True
    tick(race)
    window.drop()
    frames(game, 1)
    stats = game.scenes.top.stats
    assert (stats.verdict, stats.reason, stats.official) == (None, "Conexão perdida", LOST)


def test_a_forfeit_card_shows_the_servers_numbers(game, window):
    """The server cut my run off (5 s of silence) after my client ran on (a frozen tab resumes with a 1 s
    frame): my card shows the server's numbers, as the rival's does."""
    race = live(game, window)
    race.world.invulnerable = True
    while race.run.tick < 1560:  # my client got to 13 s...
        race.update(FIXED_DT)
    there = dict(race.kept)[1464]  # ...the server stopped me at my last k it heard, 12.2 s
    assert there.total != race.run.score.total
    race.on_net(
        {
            "t": "result",
            "m": M,
            "run": M,
            "state": "rejected",
            "why": "conexao",
            "outcome": "giveup",
            "score": there.total,
            "secs": 12.2,
            "rank": None,
            "verdict": "loss",
            "op": {"nick": "ana_42", "score": 953, "secs": 18.6},
        }
    )
    until(game, lambda: isinstance(game.scenes.top, ResultsScene), 4)
    stats = game.scenes.top.stats
    assert stats.reason == "Você perdeu: conexão perdida"
    assert (stats.seconds, stats.score.total) == (12.2, there.total)


# --- Desafiar amigo (M5) ----------------------------------------------------------------------------------

CHALLENGE = {"id": M, "from": "ana_42", "mode": "facil", "secs": 62.4, "score": 2845}


def test_received_challenges_are_listed_first(game, window, drawn):
    scene = amigos(game, window, challenges=[CHALLENGE])
    window.reply(t="challenge_new", id=78, **{"from": "bia"}, mode="dificil", secs=125.0, score=12)
    drawn.clear()
    frames(game, 2)
    assert [c["id"] for c in game.ctx.net.challenges] == [M, 78]
    assert buttons(scene)[:3] == [("JOGAR", "ana_42"), ("JOGAR", "bia"), ("CORRER AGORA", "ana_42")]
    assert "DESAFIOS RECEBIDOS" in drawn
    assert "ana_42 fez 2.845 em 1:02 (Fácil)" in drawn and "bia fez 12 em 2:05 (Difícil)" in drawn
    welcome(game, window)  # a new socket's welcome is the whole list
    assert game.ctx.net.challenges == [] and buttons(scene)[0] == ("CORRER AGORA", "ana_42")


def test_a_challenge_is_a_ranked_like_run_on_the_versus_road(game, window, tmp_path):
    """DESAFIAR: the challenge, then my run alone on the versus road as a ranked run is played (no pause, R
    gives up); the server's result says it was sent."""
    amigos(game, window)
    key(game, pygame.K_DOWN, 2)
    key(game, pygame.K_RETURN, 40)  # DESAFIAR ana_42, in the menu's mode
    wait = game.scenes.top
    assert isinstance(wait, WaitScene) and window.sent[-1] == {"t": "challenge", "to": 42, "mode": "normal"}
    window.reply(t="match", m=901, kind="challenge", mode="normal", op=None)
    frames(game, 1)
    assert window.sent[-1] == {"t": "ready", "m": 901} and wait.label == "Preparando…"
    window.reply(t="go", m=901, seed=SEED)
    frames(game, 1)
    race = game.scenes.top
    assert type(race) is RaceScene and race.run.shared and (race.online, race.seed) == (901, SEED)
    assert race.realtime and race.to == "ana_42" and race.mode.key == "normal"
    drive(race, 2)
    until(game, lambda: race.phase is Phase.RACING and race.run.tick > 300, 8)
    key(game, pygame.K_ESCAPE, 1)
    assert game.scenes.top is race and game._toast[0] == NO_PAUSE
    key(game, pygame.K_r, 1)  # gives up
    results = game.scenes.top
    assert isinstance(results, ResultsScene) and results.stats.official == VERIFYING
    check_stream(game, race, inputs(window))
    assert game.ctx.save.races == 0, "the versus road sets no record"
    window.reply(t="result", m=901, run=901, state="ok", why=None, outcome="giveup", rank=None)
    frames(game, 1)
    assert results.stats.official == "✓ Desafio enviado a ana_42"
    assert results.menu.labels[0] == "AMIGOS"
    frames(game, 30)
    key(game, pygame.K_RETURN, 40)
    assert isinstance(game.scenes.top, AmigosScene)


def test_the_result_line_of_a_challenge(game, window):
    """Sent once ok; rejected after go it is lost (the friend wins, no second try), a lost socket too."""
    normal = MODE_BY_KEY["normal"]
    assert online.official({"state": "ok", "why": None}, normal, "ana_42") == "✓ Desafio enviado a ana_42"
    rejected = {"state": "rejected", "why": "ritmo"}
    assert online.official(rejected, normal, "ana_42") == "Desafio perdido: ritmo irregular"
    race = RaceScene(game.ctx, SEED, True, online=901, mode="normal", skin="yellow", to="ana_42")
    game.scenes.switch(race, Transition.NONE)
    window.drop()
    frames(game, 1)
    assert game.scenes.top.stats.official == online.CHALLENGE_LOST == "Desafio perdido: conexão perdida"


def test_a_challenge_shows_no_record(game, window, monkeypatch):
    """Its road is the versus road: neither the HUD nor the results card speak of the solo record."""
    seen: list[str] = []
    for module in (race, results):
        real = module.blit_text
        monkeypatch.setattr(
            module,
            "blit_text",
            lambda surface, s, *a, real=real, **k: (seen.append(s), real(surface, s, *a, **k))[1],
        )
    game.ctx.save.best["normal"] = 50
    scene = RaceScene(game.ctx, SEED, True, online=901, mode="normal", skin="yellow", to="ana_42")
    game.scenes.switch(scene, Transition.NONE)
    frames(game, 360)  # the countdown and a few seconds of racing
    window.drop()
    frames(game, 120)
    assert isinstance(game.scenes.top, ResultsScene) and "PONTOS" in seen
    assert not [s for s in seen if "RECORDE" in s.upper()]


def test_jogar_races_the_recorded_run_as_the_server_streams_it(game, window, drawn):
    scene = amigos(game, window, challenges=[CHALLENGE])
    game.ctx.save.skin = "blue"  # changed after the hello: playing keeps the socket, and its car
    key(game, pygame.K_RETURN, 40)  # JOGAR
    wait = game.scenes.top
    assert isinstance(wait, WaitScene) and window.sent[-1] == {"t": "challenge_play", "id": M}
    assert wait.label == "Preparando…" and game.ctx.net.challenges == [], "one attempt: it is used"
    wait.draw(game.screen)
    assert "ESC desistir (conta como derrota)" in drawn
    window.reply(t="match", m=M, kind="challenge", mode="facil", op={"nick": "ana_42", "skin": "red"})
    frames(game, 1)
    assert window.sent[-1] == {"t": "ready", "m": M} and len(window.sockets) == 1
    window.reply(t="go", m=M, seed=SEED)
    frames(game, 1)
    race = game.scenes.top
    assert isinstance(race, RecordingScene) and race.realtime
    assert (race.mode.key, race.run.skin, race.rival.skin, race.run.shared) == (
        "facil",
        "yellow",
        "red",
        True,
    )
    while race.phase is Phase.COUNTDOWN:
        race.update(FIXED_DT)
    race.world.invulnerable = True
    her = her_inputs(game, 600)  # her run, as stored: given up at tick 600
    while race.ticks < 650:
        tick(race, her)  # streamed up to my k + 24, as a live rival's
    race.on_net({"t": "op_end", "m": M, "k": 600, "why": "giveup"})
    tick(race)
    assert (race.rival.tick, race.rival.outcome, race.rival.score) == (600, "giveup", her.score)
    drawn.clear()
    race.draw(game.screen)
    assert "GRAVAÇÃO" in drawn and "AO VIVO" not in drawn and "DESISTIU" in drawn
    result = {"t": "result", "m": M, "run": M, "state": "ok", "why": None, "outcome": "decided", "score": 9}
    race.on_net(
        {**result, "secs": 5.4, "rank": None, "verdict": "win", "op": {"nick": "ana_42", "score": 50}}
    )
    until(game, lambda: isinstance(game.scenes.top, ResultsScene), 4)
    stats = game.scenes.top.stats
    assert (VERDICTS[stats.verdict][0], stats.reason) == ("VOCÊ VENCEU!", "ana_42 desistiu aos 0:05")
    assert game.scenes.top.menu.labels[0] == "AMIGOS"
    frames(game, 30)
    key(game, pygame.K_RETURN, 40)
    assert isinstance(game.scenes.top, AmigosScene) and buttons(game.scenes.top)[0][0] != "JOGAR"
    assert scene is not game.scenes.top


def test_missing_the_ready_deadline_loses_the_challenge(game, window):
    amigos(game, window, challenges=[CHALLENGE])
    key(game, pygame.K_RETURN, 40)  # JOGAR
    window.reply(t="match", m=M, kind="challenge", mode="facil", op={"nick": "ana_42", "skin": "red"})
    lost = {"state": "rejected", "why": "prazo", "outcome": None, "score": None, "secs": None, "rank": None}
    window.reply(t="result", m=M, run=M, **lost, verdict="loss", op={"nick": "ana_42", "score": 2845})
    frames(game, 1)
    wait = game.scenes.top
    assert isinstance(wait, WaitScene) and wait.refused and wait.label == "Desafio perdido: prazo esgotado"


@pytest.mark.parametrize(("button", "code"), [("JOGAR", "drain"), ("JOGAR", "gone"), ("DESAFIAR", "friend")])
def test_challenge_refusals_show_the_servers_words(game, window, button, code):
    scene = amigos(game, window, challenges=[CHALLENGE])
    scene.menu.index = [label for label, _ in scene.actions].index(button)
    key(game, pygame.K_RETURN, 40)
    window.reply(t="error", code=code, msg=f"Recusado: {code}")  # expired, played, too many open, drain...
    frames(game, 1)
    wait = game.scenes.top
    assert isinstance(wait, WaitScene) and wait.refused and wait.label == f"Recusado: {code}"
    key(game, pygame.K_ESCAPE, 40)
    assert isinstance(game.scenes.top, AmigosScene)
    # JOGAR's attempt is used up only once the server took it (gone: played, expired or void)
    kept = button == "DESAFIAR" or code != "gone"
    assert game.ctx.net.challenges == ([CHALLENGE] if kept else [])


def test_the_challenger_hears_how_it_went_on_the_menus(game, window):
    welcome(game, window)
    window.reply(t="challenge_done", id=M, verdict="loss", op={"nick": "ana_42", "score": 4100, "secs": 61.0})
    frames(game, 1)
    assert game._toast[0] == "ana_42 aceitou seu desafio: você perdeu"
    game._toast = ("", 0.0)
    window.reply(t="challenge_done", id=M, verdict=None, op=None)  # junk: nothing to tell
    frames(game, 1)
    assert game._toast[0] == ""

    bot = VersusScene(game.ctx, "medio")
    game.scenes.switch(bot, Transition.NONE)
    window.reply(t="challenge_done", id=79, verdict="win", op={"nick": "bia", "score": 12, "secs": 3.1})
    frames(game, 30)
    assert game._toast[0] == "", "never over a race"
    game.scenes.switch(TitleScene(game.ctx), Transition.NONE)
    frames(game, 1)
    assert game._toast[0] == "bia aceitou seu desafio: você venceu"


def recording(game: Game, window: Window) -> RecordingScene:
    """JOGAR on ana_42's challenge (Fácil): the server's match and go, through the countdown."""
    amigos(game, window, challenges=[CHALLENGE])
    key(game, pygame.K_RETURN, 40)
    window.reply(t="match", m=M, kind="challenge", mode="facil", op={"nick": "ana_42", "skin": "red"})
    frames(game, 1)
    window.reply(t="go", m=M, seed=SEED)
    frames(game, 1)
    race = game.scenes.top
    assert isinstance(race, RecordingScene)
    while race.phase is Phase.COUNTDOWN:
        race.update(FIXED_DT)
    return race


def test_a_recording_that_ends_past_my_crash_drives_on(game, window):
    """I crash first: the server sends how her recorded run ended (a crash at 0:16, far past my gate) with the
    result. She is not stopped where her inputs got to, as a live rival who forfeited is: she drives on, and
    only the card says how her run ended."""
    race = recording(game, window)  # nobody steers me: a crash
    her = her_inputs(game, 3000)
    while race.phase is not Phase.CRASHED:
        tick(race, her)
    race.on_net({"t": "op_end", "m": M, "k": 2031, "why": "crash"})
    lost = {
        "state": "ok",
        "why": None,
        "outcome": "crash",
        "score": 5,
        "secs": race.run.seconds,
        "rank": None,
    }
    race.on_net(
        {
            "t": "result",
            "m": M,
            "run": M,
            **lost,
            "verdict": "loss",
            "op": {"nick": "ana_42", "score": 649, "secs": 16.9},
        }
    )
    for _ in range(40):
        tick(race)
    rival, distance = race.rival, race.rival.world.distance
    tick(race)
    assert rival.outcome is None and rival.world.distance > distance and race.state() is None
    until(game, lambda: isinstance(game.scenes.top, ResultsScene), 4)
    assert game.scenes.top.stats.rival == "ana_42: 649 pontos · bateu aos 0:16"


def test_amigos_scrolls_to_every_row(game, window, drawn):
    """4 challenges and 10 offline friends: 7 rows at a time, a hint for the rest; every button is reached."""
    friends = [{"id": 100 + i, "nick": f"amigo{i:02d}", "s": "off"} for i in range(10)]
    challenges = [{**CHALLENGE, "id": 80 + i} for i in range(4)]
    welcome(game, window, friends=friends, challenges=challenges)
    game.scenes.switch(AmigosScene(game.ctx), Transition.NONE)
    frames(game, 2)
    scene = game.scenes.top
    assert [label for label, _ in scene.actions] == ["JOGAR"] * 4 + ["DESAFIAR"] * 10
    scene.draw(game.screen)
    assert "↓ mais 7" in drawn
    for n in range(len(scene.actions)):
        assert scene.menu.index == n and scene.top <= scene.actions[n][1] < scene.top + online.ROWS
        assert game.screen.get_rect().contains(scene.menu.buttons[n].rect), "the focused button shows"
        key(game, pygame.K_DOWN, 2)
    key(game, pygame.K_UP, 2)
    drawn.clear()
    scene.draw(game.screen)
    assert "↑ mais 7" in drawn and "amigo09" in drawn and "amigo02" not in drawn
    key(game, pygame.K_RETURN, 40)
    assert window.sent[-1] == {"t": "challenge", "to": 109, "mode": "normal"}


def test_jogar_with_the_socket_down(game, window):
    """JOGAR in the 2 s before the socket reopens: a new socket, whose welcome still lists the challenge being
    played. Refused before its attempt, it is listed once; the socket lost after the match: lost, it says."""
    amigos(game, window, challenges=[CHALLENGE])
    window.drop()
    frames(game, 1)
    key(game, pygame.K_RETURN, 40)  # JOGAR
    window.accept()
    frames(game, 1)
    assert [m["t"] for m in window.sent] == ["hello", "challenge_play"]
    welcome(game, window, challenges=[CHALLENGE])
    assert game.ctx.net.challenges == []
    window.reply(t="error", code="drain", msg="Servidor atualizando, tente em 1 min")
    frames(game, 1)
    assert game.ctx.net.challenges == [CHALLENGE]
    key(game, pygame.K_ESCAPE, 40)
    key(game, pygame.K_RETURN, 40)  # JOGAR again
    window.reply(t="match", m=M, kind="challenge", mode="facil", op={"nick": "ana_42", "skin": "red"})
    frames(game, 1)
    window.drop()
    frames(game, 1)
    assert game.scenes.top.label == "Desafio perdido: conexão perdida"


# --- Carteira (E1) ----------------------------------------------------------------------------------------


def test_the_wallet_is_the_servers_number(window):
    """net.coins is welcome's coins, then each result's wallet as it comes (never added up here); a new socket
    has none until its welcome."""
    net = Net()
    net.connect("yellow")
    window.accept()
    window.reply(t="welcome", me={"id": 7, "nick": "pericles"}, friends=[], requests=0, coins=320)
    net.poll()
    assert net.coins == 320
    window.reply(t="result", m=5, state="ok", why=None, rank=3, coins=37, wallet=300)  # a rejection meanwhile
    net.poll()
    assert net.coins == 300
    net.connect("yellow")
    assert net.coins is None


def test_the_title_shows_the_wallet_once_the_server_said_it(game, window, drawn):
    frames(game, 2)
    before = set(drawn)
    window.reply(t="welcome", me={"id": 7, "nick": "pericles"}, friends=[], requests=0, coins=4321)
    drawn.clear()
    frames(game, 2)
    assert set(drawn) ^ before == {"4.321"}, "the chip, and nothing else, once the balance came"


def test_the_results_say_what_the_run_paid(game, window, drawn):
    """The server's numbers on the official line: what the run paid (0 too) and the wallet after it."""
    assert online.paid({"coins": 1, "wallet": 321}) == "+1 moeda · carteira 321"
    race = jogar(game, window)
    until(game, lambda: race.phase is Phase.RACING, 4)
    key(game, pygame.K_r, 1)  # gives up
    results = game.scenes.top
    paid = {"coins": 37, "wallet": 357}
    window.reply(t="result", m=901, run=1, state="ok", why=None, outcome="giveup", rank=37, **paid)
    drawn.clear()
    frames(game, 30)
    assert results.stats.wallet == "+37 moedas · carteira 357" and game.ctx.net.coins == 357
    assert "#37 no ranking Normal · +37 moedas · carteira 357" in drawn  # its ✓ is drawn apart

    race = jogar(game, window, 902)  # JOGAR DE NOVO; the server stops it while racing: it paid nothing
    race.world.invulnerable = True
    until(game, lambda: race.phase is Phase.RACING, 4)
    window.reply(t="result", m=902, run=2, state="rejected", why="ritmo", rank=None, coins=0, wallet=357)
    frames(game, 1)
    assert game.scenes.top.stats.wallet == "+0 moedas · carteira 357"


def test_a_live_race_card_says_what_it_paid(game, window):
    race = live(game, window)
    race.world.invulnerable = True
    tick(race)
    result = {"t": "result", "m": M, "run": M, "state": "ok", "why": None, "outcome": "decided", "score": 1}
    window.reply(**result, secs=None, rank=None, verdict="win", op={"nick": "ana_42"}, coins=12, wallet=332)
    until(game, lambda: isinstance(game.scenes.top, ResultsScene), 4)
    assert game.scenes.top.stats.wallet == "+12 moedas · carteira 332" and game.ctx.net.coins == 332


def test_offline_races_on_the_web_say_coins_need_the_site(game, monkeypatch, drawn):
    """Offline on the web (logged out, or the bot) nothing is paid, and the card says so; the desktop does
    not speak of a wallet."""
    for web in (False, True):
        monkeypatch.setattr(race, "WEB", web)
        for scene in (RaceScene(game.ctx), VersusScene(game.ctx, "medio")):
            game.scenes.switch(scene, Transition.NONE)
            scene.finish(Outcome.GAVE_UP)
            drawn.clear()
            frames(game, 2)
            assert game.scenes.top.stats.wallet == (online.NO_COINS if web else "")
            assert (online.NO_COINS in drawn) == web


# --- Garagem e loja (E2) ----------------------------------------------------------------------------------


def garage_at(game: Game, key: str) -> GarageScene:
    scene = GarageScene(game.ctx)
    scene.target = KEYS.index(key)
    game.scenes.switch(scene, Transition.NONE)
    frames(game, 2)
    return scene


def test_the_server_names_the_car_it_races_with(game, window):
    """welcome's skin is the car the server races with, yellow for a car the account does not own: the save
    takes it too, so JOGAR keeps the socket; welcome lists the cars the account owns."""
    game.ctx.save.skin = "tank"
    game.ctx.persist()
    game.ctx.net.connect("tank")
    window.accept()
    me = {"id": 7, "nick": "pericles"}
    window.reply(t="welcome", me=me, friends=[], requests=0, coins=320, skin="yellow", owned=["beetle"])
    frames(game, 2)
    net = game.ctx.net
    assert (net.skin, game.ctx.save.skin, net.owned) == ("yellow", "yellow", ["beetle"])
    assert load(game.ctx.save_path).skin == "yellow"
    key(game, pygame.K_RETURN, 1)  # JOGAR
    assert len(window.sockets) == 2 and window.sent[-1] == {"t": "solo", "mode": "normal"}


def test_a_car_chosen_before_the_welcome_stays_chosen(game, window):
    """A welcome answers the hello that went out: a car picked since then stays (JOGAR takes it to a new
    socket), and a paid car the account owns is picked like a free one."""
    garage_at(game, "blue")  # the hello named yellow; its welcome is on the way
    key(game, pygame.K_RETURN)
    me = {"id": 7, "nick": "pericles"}
    window.reply(t="welcome", me=me, friends=[], requests=0, coins=0, skin="yellow", owned=["beetle"])
    frames(game, 2)
    assert game.ctx.save.skin == "blue" == load(game.ctx.save_path).skin
    scene = garage_at(game, "beetle")
    assert not scene.locked("beetle")
    key(game, pygame.K_RETURN)
    assert game.ctx.save.skin == "beetle"
    until(game, lambda: not game.scenes.busy, 2)
    key(game, pygame.K_UP, 2)
    key(game, pygame.K_RETURN, 1)  # JOGAR
    window.accept()
    frames(game, 1)
    assert len(window.sockets) == 2 and window.sent[0]["skin"] == "beetle"


def test_a_locked_car_is_never_chosen_offline(tmp_path, monkeypatch, drawn):
    """Offline every paid car is locked but the one already chosen: ENTER picks nothing, and the line says
    where to buy it."""
    game = Game(save_path=tmp_path / "save.json", seed=3)
    for web, line in ((False, "Disponível na versão online"), (True, "Entre no site para comprar")):
        monkeypatch.setattr(garage, "WEB", web)
        scene = garage_at(game, "beetle")
        key(game, pygame.K_RETURN)
        assert game.scenes.top is scene and game.ctx.save.skin == "yellow" and line in drawn
    game.ctx.save.skin = "beetle"  # chosen online before: still its own
    drawn.clear()
    garage_at(game, "beetle")
    assert "Recorde com este carro: 0 · SELECIONADO" in drawn
    key(game, pygame.K_RETURN)
    assert isinstance(game.scenes.top, TitleScene) and game.ctx.save.skin == "beetle"


def test_the_garage_sells_a_car_on_the_second_enter(game, window, monkeypatch, drawn):
    monkeypatch.setattr(garage, "WEB", True)
    played, popped = [], []
    monkeypatch.setattr(game.ctx.audio, "play", lambda name, *a: played.append(name))
    monkeypatch.setattr(garage, "blit_pop", lambda surface, label, *a, **k: popped.append(label))
    me = {"id": 7, "nick": "pericles"}
    window.reply(t="welcome", me=me, friends=[], requests=0, coins=1640, skin="yellow", owned=["beetle"])
    scene = garage_at(game, "bat")
    assert "Faltam 6.360 moedas" in drawn
    key(game, pygame.K_RETURN, 2)
    key(game, pygame.K_RETURN, 2)  # too dear: nothing to confirm
    scene.target = KEYS.index("sedan67")
    drawn.clear()
    frames(game, 2)
    assert "1.500 moedas · você tem 1.640" in drawn
    key(game, pygame.K_RETURN, 2)
    assert "ENTER de novo para comprar por 1.500" in drawn
    key(game, pygame.K_RIGHT, 2)
    key(game, pygame.K_LEFT, 2)  # moving on asks again
    key(game, pygame.K_RETURN, 2)
    assert not [m for m in window.sent if m["t"] == "buy"] and game.scenes.top is scene
    key(game, pygame.K_RETURN, 2)
    assert [m for m in window.sent if m["t"] == "buy"] == [{"t": "buy", "skin": "sedan67"}]
    assert scene.locked("sedan67") and game.ctx.save.skin == "yellow" and "record" not in played

    key(game, pygame.K_RETURN, 2)  # asks again while the answer is on its way
    window.reply(t="wallet", coins=1640, owned=["beetle"])  # not bought: nothing to celebrate, ask anew
    frames(game, 2)
    assert game.ctx.save.skin == "yellow" and "record" not in played and not popped and scene.armed is None
    key(game, pygame.K_RETURN, 2)
    key(game, pygame.K_RETURN, 2)
    key(game, pygame.K_RIGHT, 2)  # the answer finds the carousel on another car

    window.reply(t="wallet", coins=140, owned=["beetle", "sedan67"])
    frames(game, 2)
    assert (game.ctx.net.coins, game.ctx.net.owned) == (140, ["beetle", "sedan67"])
    assert game.ctx.save.skin == "sedan67" == load(game.ctx.save_path).skin
    assert "record" in played and scene.particles.items and "LIBERADO!" in popped
    key(game, pygame.K_LEFT, 2)
    assert game.scenes.top is scene and "Recorde com este carro: 0 · SELECIONADO" in drawn
    popped.clear()
    drawn.clear()
    key(game, pygame.K_DOWN, 2)  # LIBERADO! is the car's: the sceneries keep their tabs
    assert scene.unlocked and not popped and "CENÁRIOS" in drawn


def test_the_garage_says_what_stops_a_buy(game, window, monkeypatch, drawn):
    """One coin short, and a dropped socket: it keeps its last wallet, but a buy could not go out."""
    monkeypatch.setattr(garage, "WEB", True)
    me = {"id": 7, "nick": "pericles"}
    window.reply(t="welcome", me=me, friends=[], requests=0, coins=1499, skin="yellow", owned=[])
    garage_at(game, "sedan67")
    assert "Falta 1 moeda" in drawn
    window.drop()
    scene = garage_at(game, "jdm94")  # 800: in the wallet
    key(game, pygame.K_RETURN, 2)
    key(game, pygame.K_RETURN, 2)
    assert "Sem conexão com o servidor" in drawn and scene.armed is None and scene.buying is None
