"""Live races between friends over /ws (plan §5 "Jogar com amigos", §8 M4): presence, invites, and two clients
streaming corpus logs on one shared road. The server simulates both runs, relays each one's accepted inputs to
the other no further than the receiver's own k + 24, and decides the race with run.verdict (or a forfeit).

Every message waits until the hub is done with it and with whatever it set off; then each player reads all it
got, and every op it gets is checked against its own last k right then."""

import asyncio
import contextlib
import copy
import json
import time

import anyio
import pytest

from jogo_de_carro.golden import REPLAYS
from jogo_de_carro.run import simulate
from jogo_server import hub, load
from test_ranked import HELLO, WS, Clock, closed, later, row, until
from test_ranked import honest as fin

WIN = json.loads((REPLAYS / "normal_shared_win.json").read_text(encoding="utf-8"))  # shared road, seed 1


def cut(log: dict, end: int) -> dict:
    return {**log, "end": end, "ev": [e for e in log["ev"] if e[0] < end]}


LONG = cut(WIN, 2400)  # alive for 20 s at least
NO_STEER = {**WIN, "ev": [e for e in WIN["ev"] if e[1] not in ("L", "R") or e[0] < 600]}
T = 1012  # NO_STEER crashes on its tick 1012 (checked in test_the_race_is_decided_at_the_crash)
CRASH = cut(NO_STEER, T)


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def make(make_site, clock, monkeypatch):
    """make(**config changes) -> a started Site on the test's clock, the corpus's seed and a counted hub."""
    monkeypatch.setattr(hub, "new_seed", lambda: WIN["seed"])
    handle = hub.Hub.handle

    async def counted(self, sock, text):  # the test waits for the hub to be done with each message
        await handle(self, sock, text)
        self.handled += 1

    monkeypatch.setattr(hub.Hub, "handle", counted)
    monkeypatch.setattr(hub.Hub, "handled", 0, raising=False)

    def make(**changes):
        site = make_site(clock=clock, **changes)
        site.players = []
        return site

    return make


@pytest.fixture
def s(make):
    return make()


def idle(s, cond=lambda: True) -> None:
    """Waits for cond and for the hub's spawned tasks (sweeps, presence, a lost socket's end); then every
    player reads what it got."""
    until(lambda: cond() and not s.hub.tasks)
    for p in s.players:
        p.read()


class Player:
    def __init__(self, s, nick: str, skin: str = "yellow") -> None:
        self.s, self.nick, self.skin = s, nick, skin
        self.client, self.uid = s.player(nick)
        self.got: list[dict] = []
        self.k = 0  # the last k sent
        self.delay = 0.0  # how far behind real time it plays
        self.m = self.code = None

    def connect(self, stack: contextlib.ExitStack) -> "Player":
        self.ws = stack.enter_context(self.client.websocket_connect(WS))
        self.s.players.append(self)
        self.send({**HELLO, "skin": self.skin})
        self.welcome = self.of("welcome")[0]
        return self

    def send(self, msg: dict) -> None:
        n = self.s.hub.handled
        self.ws.send_json(msg)
        self.k = msg["k"] if msg["t"] == "in" else self.k
        idle(self.s, lambda: self.s.hub.handled > n)

    def read(self) -> None:
        while self.code is None:
            try:
                m = self.ws.portal.call(self.ws._send_rx.receive_nowait)
            except anyio.WouldBlock:
                return
            if m["type"] == "websocket.close":
                self.code = m["code"]
                return
            msg = json.loads(m["text"])
            # the rival never shows ahead of my own last k + 24 (how its run ended may, with the result)
            if msg["t"] == "op" or (msg["t"] == "op_end" and self.m in self.s.hub.live):
                assert msg["m"] == self.m and msg["k"] <= self.k + hub.AHEAD, (msg, self.k)
            self.got.append(msg)

    def of(self, t: str) -> list[dict]:
        return [m for m in self.got if m["t"] == t]

    def result(self) -> dict | None:
        return next(iter(self.of("result")), None)


def befriend(s, *players: Player) -> None:
    for i, p in enumerate(players):
        for q in players[i + 1 :]:
            a, b = sorted((p.uid, q.uid))
            s.db.execute("INSERT INTO friends(a, b, asked_by, accepted) VALUES (?, ?, ?, 1)", (a, b, a))


def friends(s, stack, *names: str) -> list[Player]:
    """Players who are all friends, in the game ("ana", or "ana:red" for her car)."""
    players = [Player(s, *name.split(":")) for name in names]
    befriend(s, *players)
    return [p.connect(stack) for p in players]


def invite(a: Player, b: Player, mode: str = "normal") -> str:
    a.send({"t": "invite", "to": b.uid, "mode": mode})
    return a.of("waiting")[-1]["id"]


def match(a: Player, b: Player, mode: str = "normal") -> None:
    b.send({"t": "invite_reply", "id": invite(a, b, mode), "ok": True})
    for p in (a, b):
        p.m = p.of("match")[-1]["m"]


def go(s, clock, a: Player, b: Player) -> float:
    """Both ready: returns the loop time of tick 0."""
    match(a, b)
    for p in (a, b):
        p.send({"t": "ready", "m": p.m})
    return clock.t + hub.COUNTDOWN_S


def race(s, clock, t0: float, *plays: tuple[Player, dict, dict | None]) -> tuple:
    """Each (player, log, fin) sends its log's messages, k at t0 + k/120 + 0.05 + its delay (at one time, in
    the order given) until all have their result. Returns who sent the message that decided the race, and its
    k."""
    steps = sorted(
        (t0 + k / 120 + 0.05 + p.delay, i, k, p, msg)
        for i, (p, log, f) in enumerate(plays)
        for k, msg in load.messages(log, p.m, f)
    )
    for at, _, k, p, msg in steps:
        if p.result() or k <= p.k:  # over, or sent already
            continue
        later(s, clock, at - clock.t)
        p.send(msg)
        if all(q.result() for q, _, _ in plays):
            return p.nick, k
    return None, None


def ops(p: Player) -> list[tuple[int, list]]:
    return [(m["k"], m["ev"]) for m in p.of("op")]


def sent(p: Player, log: dict, f: dict | None = None, upto: int = 10**9) -> list[tuple[int, list]]:
    return [(k, msg["ev"]) for k, msg in load.messages(log, p.m, f) if k <= upto]


def the_match(s, p: Player):
    return s.db.execute("SELECT * FROM matches WHERE id = ?", (row(s, p.m)["match_id"],)).fetchone()


# --- presence -----------------------------------------------------------------------------------------------


def test_presence(s):
    with contextlib.ExitStack() as stack:
        ana, bia, caio, duda = (Player(s, n) for n in ("ana", "bia", "caio", "duda"))
        befriend(s, ana, bia)
        x, y = sorted((ana.uid, duda.uid))
        s.db.execute("INSERT INTO friends(a, b, asked_by) VALUES (?, ?, ?)", (x, y, duda.uid))  # asked ana
        ana.connect(stack)
        assert ana.welcome == {
            "t": "welcome", "me": {"id": ana.uid, "nick": "ana"},
            "friends": [{"id": bia.uid, "nick": "bia", "s": "off"}], "requests": 1,
        }  # fmt: skip
        bia.connect(stack)
        assert bia.welcome["friends"] == [{"id": ana.uid, "nick": "ana", "s": "menu"}]
        assert bia.welcome["requests"] == 0
        caio.connect(stack)  # no friend
        duda.connect(stack)  # asked, not accepted yet
        assert duda.welcome["friends"] == [] and duda.welcome["requests"] == 0
        bia.send({"t": "solo", "mode": "normal"})
        bia.send({"t": "leave", "m": bia.of("match")[0]["m"]})
        bia.ws.close()
        idle(s, lambda: bia.uid not in s.hub.socks)
        statuses = [(m["id"], m["s"]) for m in ana.of("presence")]
        assert statuses == [(bia.uid, s_) for s_ in ("menu", "racing", "menu", "off")]
        assert bia.of("presence") == caio.of("presence") == duda.of("presence") == []


# --- invites ------------------------------------------------------------------------------------------------


def test_invite_accept_and_go(s, clock):
    with contextlib.ExitStack() as stack:
        ana, bia = friends(s, stack, "ana", "bia:red")
        iid = invite(ana, bia, "dificil")
        assert iid.startswith("i_") and ana.got[-1] == {"t": "waiting", "id": iid}
        assert bia.got[-1] == {
            "t": "invited", "id": iid, "from": {"id": ana.uid, "nick": "ana"}, "mode": "dificil", "ttl": 30,
        }  # fmt: skip
        bia.send({"t": "invite_reply", "id": iid, "ok": True})
        for p, op in ((ana, {"nick": "bia", "skin": "red"}), (bia, {"nick": "ana", "skin": "yellow"})):
            [m] = p.of("match")
            assert m == {"t": "match", "m": m["m"], "kind": "live", "mode": "dificil", "op": op}  # no seed
            p.m = m["m"]
        assert ana.m != bia.m
        ana.send({"t": "ready", "m": ana.m})
        assert ana.of("go") == bia.of("go") == []  # waits for both
        bia.send({"t": "ready", "m": bia.m})
        for p in (ana, bia):
            assert p.of("go") == [{"t": "go", "m": p.m, "seed": WIN["seed"]}]  # one road
        a, b = s.hub.live[ana.m], s.hub.live[bia.m]
        assert a.t0 == b.t0 and a.run.shared and (a.run.world.rival, b.run.world.rival) == ("red", "yellow")
        mt = the_match(s, ana)
        for p in (ana, bia):
            r = row(s, p.m)
            assert (r["kind"], r["match_id"], r["shared"], r["seed"], r["state"], r["skin"]) == (
                "live", mt["id"], 1, WIN["seed"], "live", p.skin,
            )  # fmt: skip
        assert (mt["kind"], mt["mode"], mt["state"]) == ("live", "dificil", "racing")
        assert (mt["a"], mt["b"]) == (ana.uid, bia.uid)  # who invited first
        assert s.client().get("/saude").json()["ativas"] == 2
        assert (ana.of("presence")[-1]["s"], bia.of("presence")[-1]["s"]) == ("racing", "racing")


def gone(p: Player, iid: str) -> list[str]:
    return [m["why"] for m in p.of("invite_gone") if m["id"] == iid]


def test_decline_cancel_expire(s, clock):
    with contextlib.ExitStack() as stack:
        ana, bia = friends(s, stack, "ana", "bia")
        iid = invite(ana, bia)
        bia.send({"t": "invite_reply", "id": iid, "ok": False})
        assert gone(ana, iid) == ["declined"] and gone(bia, iid) == []

        iid = invite(ana, bia)
        ana.send({"t": "invite_cancel", "id": iid})
        assert gone(bia, iid) == ["cancelled"] and gone(ana, iid) == []
        bia.send({"t": "invite_reply", "id": iid, "ok": True})  # crossed the cancel: ignored
        assert bia.code is None and bia.of("match") == []

        iid = invite(ana, bia)
        later(s, clock, 29.9)
        idle(s)
        assert gone(ana, iid) == []
        later(s, clock, 0.6)
        idle(s)
        assert gone(ana, iid) == gone(bia, iid) == ["expired"]

        iid = invite(ana, bia)
        again = invite(ana, bia)  # a new invite replaces the old one
        assert gone(bia, iid) == ["cancelled"] and [m["id"] for m in bia.of("invited")][-1] == again
        assert list(s.hub.invites) == [again]


def test_offline_and_busy(s, clock):
    with contextlib.ExitStack() as stack:
        ana, bia, caio = friends(s, stack, "ana", "bia", "caio")
        duda, eva = Player(s, "duda"), Player(s, "eva").connect(stack)
        befriend(s, ana, duda)
        for to in (duda, eva, ana):  # not connected; not a friend; herself
            assert gone(ana, invite(ana, to)) == ["offline"]
        assert ana.of("invited") == eva.of("invited") == []

        iid = invite(ana, bia)
        assert gone(caio, invite(caio, bia)) == ["busy"]  # bia has an invite open
        assert gone(caio, invite(caio, ana)) == ["busy"]  # and so has ana
        bia.ws.close()
        idle(s, lambda: bia.uid not in s.hub.socks)
        assert gone(ana, iid) == ["offline"] and s.hub.invites == {}

        caio.send({"t": "solo", "mode": "normal"})
        assert gone(ana, invite(ana, caio)) == ["busy"]  # racing

        caio.send({"t": "leave", "m": caio.of("match")[0]["m"]})
        iid = invite(ana, caio)
        caio.send({"t": "solo", "mode": "normal"})  # rather races alone
        assert gone(ana, iid) == ["declined"] and s.hub.invites == {}


@pytest.mark.parametrize("who", ["inviter replies", "invited cancels", "a third player replies"])
def test_only_the_invited_replies_and_only_the_inviter_cancels(s, clock, who):
    with contextlib.ExitStack() as stack:
        ana, bia, caio = friends(s, stack, "ana", "bia", "caio")
        iid = invite(ana, bia)
        bad, msg = {
            "inviter replies": (ana, {"t": "invite_reply", "id": iid, "ok": True}),
            "invited cancels": (bia, {"t": "invite_cancel", "id": iid}),
            "a third player replies": (caio, {"t": "invite_reply", "id": iid, "ok": True}),
        }[who]
        bad.send(msg)
        assert bad.got[-1]["code"] == "bad" and bad.code == 1008
        if bad is caio:  # nothing happened to the invite
            bia.send({"t": "invite_reply", "id": iid, "ok": True})
            assert ana.of("match") and bia.of("match")
        else:
            other = bia if bad is ana else ana
            assert gone(other, iid) == ["offline"] and s.hub.invites == {}


def test_invite_rate_limit(s):
    with contextlib.ExitStack() as stack:
        ana, bia = friends(s, stack, "ana", "bia")
        for _ in range(hub.INVITES):
            iid = invite(ana, bia)
        ana.send({"t": "invite", "to": bia.uid, "mode": "normal"})
        assert ana.got[-1] == {"t": "error", "code": "rate", "msg": hub.REFUSED["invites"]}
        assert list(s.hub.invites) == [iid] and ana.code is None


def test_drain_and_admission(make, tmp_path):
    s = make(max_ativas=2)
    with contextlib.ExitStack() as stack:
        ana, bia, caio = friends(s, stack, "ana", "bia", "caio")
        (tmp_path / "drain").touch()
        ana.send({"t": "invite", "to": bia.uid, "mode": "normal"})
        assert ana.got[-1] == {"t": "error", "code": "drain", "msg": hub.REFUSED["drain"]}
        (tmp_path / "drain").unlink()
        iid = invite(ana, bia)
        (tmp_path / "drain").touch()  # an update starts while bia thinks
        bia.send({"t": "invite_reply", "id": iid, "ok": True})
        for p in (ana, bia):
            assert p.got[-1] == {"t": "error", "code": "drain", "msg": hub.REFUSED["drain"]}
            assert p.code is None  # the socket stays open
        assert s.count("runs") == s.count("matches") == 0
        (tmp_path / "drain").unlink()

        caio.send({"t": "solo", "mode": "normal"})  # 1 of 2 runs
        iid = invite(ana, bia)
        bia.send({"t": "invite_reply", "id": iid, "ok": True})
        assert ana.got[-1]["code"] == bia.got[-1]["code"] == "full"
        caio.send({"t": "leave", "m": caio.of("match")[0]["m"]})
        match(ana, bia)
        assert s.client().get("/saude").json()["ativas"] == 2


# --- the race -----------------------------------------------------------------------------------------------


def test_the_race_is_decided_at_the_crash(s, clock):
    """bia crashes on tick T (off the 12-tick grid): ana wins with her first message past it, not before,
    and each has seen exactly the other's accepted inputs, in order."""
    crashed = simulate(hub.assets(), NO_STEER)
    assert (crashed.outcome, crashed.tick) == ("crash", T) and T % hub.REPORT
    with contextlib.ExitStack() as stack:
        ana, bia = friends(s, stack, "ana", "bia:red")
        t0 = go(s, clock, ana, bia)
        assert race(s, clock, t0, (bia, CRASH, fin(CRASH)), (ana, LONG, None)) == ("ana", T - T % 12 + 12)
        a, b = ana.result(), bia.result()
    won = simulate(hub.assets(), cut(WIN, 1020))
    mine, hers = (won.score.total, round(won.seconds, 1)), (crashed.score.total, round(crashed.seconds, 1))
    assert a == {
        "t": "result", "m": ana.m, "run": ana.m, "state": "ok", "why": None, "outcome": "decided",
        "score": mine[0], "secs": mine[1], "rank": None, "verdict": "win",
        "op": {"nick": "bia", "score": hers[0], "secs": hers[1]},
    }  # fmt: skip
    assert b == {
        "t": "result", "m": bia.m, "run": bia.m, "state": "ok", "why": None, "outcome": "crash",
        "score": hers[0], "secs": hers[1], "rank": None, "verdict": "loss",
        "op": {"nick": "ana", "score": mine[0], "secs": mine[1]},
    }  # fmt: skip
    assert ops(ana) == sent(bia, CRASH, fin(CRASH))  # every one of bia's messages, in order
    assert ana.of("op_end") == [{"t": "op_end", "m": ana.m, "k": T, "why": "crash"}]
    assert ops(bia) == sent(ana, LONG, upto=1020) and bia.of("op_end") == []
    assert ana.got.index(ana.of("op_end")[0]) < ana.got.index(a)  # the end, then the result
    ra, rb = row(s, ana.m), row(s, bia.m)
    assert (ra["state"], ra["ticks"], ra["outcome"]) == ("ok", 1020, "decided")
    assert (rb["state"], rb["ticks"], rb["outcome"], rb["client_score"]) == ("ok", T, "crash", hers[0])
    mt = the_match(s, ana)
    assert (mt["state"], mt["winner"]) == ("done", ana.uid)
    assert s.hub.live == {} and hub.board(s.db, "normal") == []  # never on the board
    assert s.count("runs WHERE state = 'review'") == 0  # nor in review
    assert (ana.of("presence")[-1]["s"], bia.of("presence")[-1]["s"]) == ("menu", "menu")


def test_the_rival_never_shows_ahead(s, clock):
    """ana plays 1 s behind real time (within pacing): bia's inputs reach her only up to her own k + 24
    (Player checks every op as it arrives), and all of them once she catches up."""
    with contextlib.ExitStack() as stack:
        ana, bia = friends(s, stack, "ana", "bia")
        t0 = go(s, clock, ana, bia)
        ana.delay = 1.0
        race(s, clock, t0, (bia, cut(WIN, 1200), None), (ana, cut(WIN, 1080), None))
        assert (ana.k, bia.k, ops(ana)[-1][0]) == (1080, 1200, 1104)
        assert ops(bia) == sent(ana, cut(WIN, 1080))  # ahead, bia gets all of ana's at once
        race(s, clock, t0, (ana, cut(WIN, 1200), None))
        assert ops(ana) == sent(bia, cut(WIN, 1200)) and ana.result() is None


def test_same_crash_is_a_draw(s, clock):
    with contextlib.ExitStack() as stack:
        ana, bia = friends(s, stack, "ana", "bia")
        t0 = go(s, clock, ana, bia)
        assert race(s, clock, t0, (ana, CRASH, fin(CRASH)), (bia, CRASH, fin(CRASH))) == ("bia", T)
    assert ana.result()["verdict"] == bia.result()["verdict"] == "draw"
    assert ana.of("op_end")[0]["why"] == bia.of("op_end")[0]["why"] == "crash"
    mt = the_match(s, ana)
    assert (mt["state"], mt["winner"]) == ("done", None)


def test_silence_forfeits(s, clock):
    with contextlib.ExitStack() as stack:
        ana, bia = friends(s, stack, "ana", "bia")
        t0 = go(s, clock, ana, bia)
        who, k = race(s, clock, t0, (ana, LONG, None), (bia, cut(WIN, 600), None))  # bia stops at 5 s
    assert who == "ana" and 1200 < k <= 1272  # bia's last message + 5 s, and the sweeper's next pass
    a, b = ana.result(), bia.result()
    assert (a["verdict"], a["state"], a["outcome"]) == ("win", "ok", "decided")
    assert (b["verdict"], b["state"], b["why"], b["outcome"]) == ("loss", "rejected", "conexao", "giveup")
    assert ana.of("op_end") == [{"t": "op_end", "m": ana.m, "k": 600, "why": "conexao"}]


@pytest.mark.parametrize("how", ["leave", "close", "kick", "pacing"])
def test_a_forfeit_ends_the_race(s, clock, how):
    """5 s into the race bia gives up, loses her socket, is logged out everywhere, or sends inputs far too
    early: she loses at once, whoever was ahead."""
    with contextlib.ExitStack() as stack:
        ana, bia = friends(s, stack, "ana", "bia")
        t0 = go(s, clock, ana, bia)
        race(s, clock, t0, (bia, cut(WIN, 600), None), (ana, cut(WIN, 588), None))  # ana is behind
        assert ana.result() is None
        if how == "leave":
            bia.send({"t": "leave", "m": bia.m})
        elif how == "close":
            bia.ws.close()
        elif how == "kick":
            assert bia.client.post("/conta/sair-todos").status_code == 303
        else:
            msg = dict(load.messages(cut(WIN, 840), bia.m))[840]
            bia.send(msg)  # 2 s of inputs at once: adiantado
        idle(s, lambda: ana.m not in s.hub.live)  # the race is over
    why = {"leave": "giveup", "close": "conexao", "kick": "conexao", "pacing": "adiantado"}[how]
    assert ana.of("op_end") == [{"t": "op_end", "m": ana.m, "k": 600, "why": why}]
    assert ops(ana) == sent(bia, cut(WIN, 600))  # the early message never reached her
    a = ana.result()
    assert (a["verdict"], a["state"], a["outcome"], a["op"]["nick"]) == ("win", "ok", "decided", "bia")
    b = row(s, bia.m)
    assert (b["state"], b["why"], b["outcome"], b["ticks"]) == (
        "ok" if how == "leave" else "rejected", None if how == "leave" else why, "giveup", 600,
    )  # fmt: skip
    if how in ("leave", "pacing"):
        assert (bia.result()["verdict"], bia.result()["why"]) == ("loss", b["why"])
    assert the_match(s, ana)["winner"] == ana.uid and s.hub.live == {}


@pytest.mark.parametrize("how", ["deadline", "leave"])
def test_a_race_that_never_starts_is_void(s, clock, how):
    with contextlib.ExitStack() as stack:
        ana, bia = friends(s, stack, "ana", "bia")
        match(ana, bia)
        ana.send({"t": "ready", "m": ana.m})
        if how == "deadline":
            later(s, clock, hub.READY_S + 0.6)
            idle(s)
        else:
            bia.send({"t": "leave", "m": bia.m})
        bia.send({"t": "ready", "m": bia.m})  # too late: ignored, no seed
    for p, why in ((ana, "anulada"), (bia, "prazo")):
        assert p.result() == {
            "t": "result", "m": p.m, "run": p.m, "state": "rejected", "why": why,
            "outcome": None, "score": None, "secs": None, "rank": None, "verdict": None, "op": None,
        }  # fmt: skip
        assert p.of("go") == []
    assert the_match(s, ana)["state"] == "void" and s.hub.live == {}


def test_a_third_player_cannot_touch_the_race(s, clock):
    with contextlib.ExitStack() as stack:
        ana, bia = friends(s, stack, "ana", "bia")
        t0 = go(s, clock, ana, bia)
        race(s, clock, t0, (ana, cut(WIN, 120), None), (bia, cut(WIN, 120), None))
        for i, msg in enumerate((
            {"t": "in", "m": ana.m, "k": 132, "ev": []},
            {"t": "ready", "m": bia.m},
            {"t": "leave", "m": ana.m},
            {"t": "invite", "to": ana.uid, "mode": "normal"},  # not a violation: just not available
        )):  # fmt: skip
            intruder = Player(s, f"intruso{i}").connect(stack)
            befriend(s, intruder, ana)
            intruder.send(msg)
            want = (None, None) if i == 3 else (1008, "bad")
            assert (intruder.code, intruder.got[-1].get("code")) == want
        assert ana.result() is bia.result() is None and len(s.hub.live) == 2
        assert race(s, clock, t0, (bia, CRASH, fin(CRASH)), (ana, LONG, None))[0] == "ana"
    assert ana.result()["verdict"] == "win" and gone(intruder, intruder.of("waiting")[0]["id"]) == ["busy"]


def test_a_restart_voids_races(s, clock):
    with contextlib.ExitStack() as stack:
        ana, bia = friends(s, stack, "ana", "bia")
        match(ana, bia)
        hub.Hub(s.app.state, clock)
        assert the_match(s, ana)["state"] == "void" and row(s, ana.m)["why"] == "reinicio"


def test_a_banned_player_starts_no_race(s):
    with contextlib.ExitStack() as stack:
        ana, bia = friends(s, stack, "ana", "bia")
        iid = invite(ana, bia)
        s.db.execute("UPDATE users SET role = 'banned' WHERE id = ?", (ana.uid,))  # the admin command's ban
        bia.send({"t": "invite_reply", "id": iid, "ok": True})
        assert (ana.got[-1]["code"], ana.code) == ("login", 1008)
        assert gone(bia, iid) == ["offline"] and bia.of("match") == [] and s.count("runs") == 0


# --- what the review found (M4) -------------------------------------------------------------------------


def test_invites_that_cross_are_a_yes(s):
    """Both press REVANCHE at once: the second invite is a yes to the first, not a no."""
    with contextlib.ExitStack() as stack:
        ana, bia = friends(s, stack, "ana", "bia")
        iid = invite(ana, bia)
        bia.send({"t": "invite", "to": ana.uid, "mode": "normal"})
        assert bia.of("waiting") == [{"t": "waiting", "id": iid}] and gone(ana, iid) == gone(bia, iid) == []
        assert ana.of("match")[0]["kind"] == bia.of("match")[0]["kind"] == "live" and len(s.hub.live) == 2


def test_an_invite_from_an_ex_friend_starts_nothing(s):
    with contextlib.ExitStack() as stack:
        ana, bia = friends(s, stack, "ana", "bia")
        iid = invite(ana, bia)
        assert ana.client.post(f"/amigos/{bia.uid}/remover").status_code == 303
        bia.send({"t": "invite_reply", "id": iid, "ok": True})
        assert gone(ana, iid) == gone(bia, iid) == ["offline"] and bia.of("match") == []
        assert s.count("runs") == 0


def test_a_crash_ahead_stays_hidden_until_the_race_is_decided(s, clock):
    """bia crashes past ana's gate, closes the game and opens it again: ana hears of none of it (no presence,
    no op_end) before her own run passes the crash, and bia's new tab starts nothing meanwhile."""
    with contextlib.ExitStack() as stack:
        ana, bia = friends(s, stack, "ana", "bia")
        t0 = go(s, clock, ana, bia)
        race(s, clock, t0, (bia, CRASH, fin(CRASH)), (ana, cut(WIN, 840), None))
        seen = len(ana.got)
        bia.ws.close()
        idle(s, lambda: bia.uid not in s.hub.socks)
        tab = copy.copy(bia)  # her account, a new socket
        tab.got, tab.code = [], None
        tab.connect(stack)
        assert [f["s"] for f in tab.welcome["friends"]] == ["racing"]
        for msg in ({"t": "solo", "mode": "normal"}, {"t": "invite", "to": ana.uid, "mode": "normal"}):
            tab.send(msg)
            assert tab.got[-1] == hub.error("racing") and tab.code is None  # one run per player
        assert ana.got[seen:] == [] and len(s.hub.live) == 2 and s.hub.status(bia.uid) == "racing"
        race(s, clock, t0, (ana, LONG, None))
    assert ana.result()["verdict"] == "win" and ana.of("op_end")[0]["why"] == "crash"
    assert ana.of("presence")[-1] == {"t": "presence", "id": bia.uid, "s": "menu"}  # her new tab


def test_a_forfeit_past_the_gate_still_says_how(s, clock):
    """bia gives up 60 ticks ahead of ana: her last inputs never reach ana, but how her run ended comes with
    the result."""
    with contextlib.ExitStack() as stack:
        ana, bia = friends(s, stack, "ana", "bia")
        t0 = go(s, clock, ana, bia)
        race(s, clock, t0, (bia, cut(WIN, 600), None), (ana, cut(WIN, 540), None))
        bia.send({"t": "leave", "m": bia.m})
    assert ops(ana) == sent(bia, cut(WIN, 600), upto=540 + hub.AHEAD)
    [end] = ana.of("op_end")
    assert end == {"t": "op_end", "m": ana.m, "k": 600, "why": "giveup"}
    assert ana.got.index(end) == ana.got.index(ana.result()) - 1 and ana.result()["verdict"] == "win"


def test_a_slow_rival_socket_is_not_my_lateness(s, clock):
    """bia's socket takes 0.5 s per send: ana's inputs are handled at once all the same, as the hub never
    awaits the rival's socket in her handler (it would be her lateness, for pacing)."""
    with contextlib.ExitStack() as stack:
        ana, bia = friends(s, stack, "ana", "bia")
        t0 = go(s, clock, ana, bia)
        race(s, clock, t0, (bia, cut(WIN, 600), None), (ana, cut(WIN, 588), None))
        ws = s.hub.socks[bia.uid].ws
        real = ws.send_text

        async def slow(text: str) -> None:
            await asyncio.sleep(0.5)
            await real(text)

        ws.send_text = slow
        n, start = s.hub.handled, time.monotonic()
        ana.k = 600
        ana.ws.send_json(dict(load.messages(LONG, ana.m))[600])
        until(lambda: s.hub.handled > n)
        assert time.monotonic() - start < 0.3
        idle(s)
        assert ops(bia)[-1][0] == 600 and bia.code is None


def test_presence_reaches_friends_of_a_deleted_account(s):
    with contextlib.ExitStack() as stack:
        ana, bia = friends(s, stack, "ana", "bia")
        assert bia.client.post("/conta/excluir", data={"confirmar": "bia"}).status_code == 200
        idle(s, lambda: bia.uid not in s.hub.socks)
        assert ana.of("presence")[-1] == {"t": "presence", "id": bia.uid, "s": "off"}


def test_sockets_a_minute_are_limited(s):
    """Each socket's hello and close tell every friend: one account cannot flood them."""
    with contextlib.ExitStack() as stack:
        [ana] = friends(s, stack, "ana")
        for i in range(hub.SOCKETS - 1):  # ana's first one counts; the last one stays open
            ws = stack.enter_context(ana.client.websocket_connect(WS))
            ws.send_json(HELLO)
            assert ws.receive_json()["t"] == "welcome"
            if i < hub.SOCKETS - 2:
                ws.close()
        kept = s.hub.socks[ana.uid]
        with ana.client.websocket_connect(WS) as ws:
            ws.send_json(HELLO)
            assert ws.receive_json() == {"t": "error", "code": "rate", "msg": hub.REFUSED["sockets"]}
            assert closed(ws) == 1008
        assert s.hub.socks[ana.uid] is kept  # the open one stays
