"""The garage (plan §3.3, E2): paid cars, bought with the wallet's coins at the server's price and owned on
the server only. A hello with a car the player does not own races with yellow (swapped, never refused), and a
car never changes a run: every one has yellow's hitbox."""

import contextlib

import pytest

import test_live
import test_ranked
import test_wallet
from jogo_de_carro.run import simulate
from jogo_de_carro.settings import PRICE
from jogo_server import admin, hub
from test_live import Player, befriend, match
from test_ranked import HELLO, LOG, WS, Racer, closed, honest, row

clock, make, s = test_live.clock, test_live.make, test_live.s  # the fixtures
board, no_bot_rule, corpus_seed = test_ranked.board, test_ranked.no_bot_rule, test_wallet.corpus_seed


def earn(s, uid: int, coins: int) -> int:
    """A paid run (a race's: off the board) of this many coins. Returns its id."""
    sql = "INSERT INTO runs(user_id, kind, mode, skin, seed, shared, build, started, state, coins)"
    sql += " VALUES (?, 'live', 'normal', 'yellow', 1, 1, 'x', 0, 'ok', ?) RETURNING id"
    return s.db.execute(sql, (uid, coins)).fetchone()[0]


def own(s, uid: int, skin: str) -> None:
    earn(s, uid, PRICE[skin])
    s.db.execute(hub.BUY, {"u": uid, "skin": skin, "price": PRICE[skin]})


def buy(ws, skin: str) -> dict:
    ws.send_json({"t": "buy", "skin": skin})
    return ws.receive_json()


def test_buying_a_car(s):
    """Charged once, at the server's price: a car owned already, or a wallet short of it, changes nothing. A
    refund is a DELETE from the garage."""
    c, uid = s.player("ana")
    earn(s, uid, PRICE["beetle"] + PRICE["moto"] - 1)
    left = PRICE["moto"] - 1
    with c.websocket_connect(WS) as ws:
        ws.send_json(HELLO)
        assert ws.receive_json()["owned"] == []
        for _ in range(2):
            assert buy(ws, "beetle") == {"t": "wallet", "coins": left, "owned": ["beetle"]}
        assert buy(ws, "moto") == {"t": "wallet", "coins": left, "owned": ["beetle"]}  # 1 coin short
        earn(s, uid, 1)
        assert buy(ws, "moto") == {"t": "wallet", "coins": 0, "owned": ["beetle", "moto"]}
    garage = [tuple(r) for r in s.db.execute("SELECT * FROM garage")]
    assert garage == [(uid, "beetle", PRICE["beetle"]), (uid, "moto", PRICE["moto"])]
    s.db.execute("DELETE FROM garage WHERE user_id = ? AND skin = 'beetle'", (uid,))
    with c.websocket_connect(WS) as ws:
        ws.send_json(HELLO)
        welcome = ws.receive_json()
    assert (welcome["coins"], welcome["owned"]) == (PRICE["beetle"], ["moto"])


def test_a_car_not_owned_races_as_yellow(s):
    """Bought mid-run, the run keeps yellow; the next hello's run has the car."""
    c, uid = s.player("ana")
    earn(s, uid, PRICE["beetle"])
    with c.websocket_connect(WS) as ws:
        ws.send_json({**HELLO, "skin": "beetle"})
        welcome = ws.receive_json()
        assert (welcome["skin"], welcome["coins"], welcome["owned"]) == ("yellow", PRICE["beetle"], [])
        ws.send_json({"t": "solo", "mode": "normal"})
        m = ws.receive_json()["m"]
        assert buy(ws, "beetle") == {"t": "wallet", "coins": 0, "owned": ["beetle"]}
        ws.send_json({"t": "ready", "m": m})
        assert ws.receive_json()["t"] == "go"
        assert (s.hub.live[m].run.skin, row(s, m)["skin"]) == ("yellow", "yellow")
        ws.send_json({"t": "leave", "m": m})
        assert ws.receive_json()["t"] == "result"
    with c.websocket_connect(WS) as ws:
        ws.send_json({**HELLO, "skin": "beetle"})
        assert ws.receive_json()["skin"] == "beetle"
        ws.send_json({"t": "solo", "mode": "normal"})
        assert row(s, ws.receive_json()["m"])["skin"] == "beetle"


def test_a_rival_sees_the_car_raced(s):
    with contextlib.ExitStack() as stack:
        ana, bia = Player(s, "ana", "tank"), Player(s, "bia", "tank")
        befriend(s, ana, bia)
        own(s, ana.uid, "tank")
        for p in (ana, bia):
            p.connect(stack)
        assert (ana.welcome["skin"], bia.welcome["skin"]) == ("tank", "yellow")
        match(ana, bia)
        assert ana.of("match")[-1]["op"] == {"nick": "bia", "skin": "yellow"}
        assert bia.of("match")[-1]["op"] == {"nick": "ana", "skin": "tank"}
        assert (row(s, ana.m)["skin"], row(s, bia.m)["skin"]) == ("tank", "yellow")


def test_a_ranked_run_in_a_paid_car(s, clock, board, no_bot_rule, corpus_seed):
    """The corpus run (in yellow) played in a tank: ok, and scored as in yellow."""
    c, uid = s.player("ana")
    own(s, uid, "tank")
    with c.websocket_connect(WS) as ws:
        res = Racer(s, clock, ws, skin="tank").play(LOG, fin=honest(LOG))
    want = simulate(hub.assets(), LOG)
    assert (res["state"], res["why"], res["outcome"]) == ("ok", None, "crash")
    assert (res["score"], res["coins"]) == (want.score.total, want.score.coins)
    assert (row(s, res["run"])["skin"], row(s, res["run"])["ticks"]) == ("tank", want.tick)


def test_a_debt_buys_nothing(s, monkeypatch):
    """The admin rejects the run whose coins bought a car: the car stays, and the wallet, below 0, buys
    nothing until runs pay the debt back."""
    monkeypatch.setenv("JOGO_DB", s.app.state.cfg.db)
    c, uid = s.player("ana")
    rid = earn(s, uid, PRICE["beetle"])
    with c.websocket_connect(WS) as ws:
        ws.send_json(HELLO)
        ws.receive_json()
        assert buy(ws, "beetle") == {"t": "wallet", "coins": 0, "owned": ["beetle"]}
        assert admin.main(["rejeitar", str(rid)]) == 0
        assert buy(ws, "moto") == {"t": "wallet", "coins": -PRICE["beetle"], "owned": ["beetle"]}
        earn(s, uid, PRICE["moto"])  # it alone would pay for it
        assert buy(ws, "moto")["owned"] == ["beetle"]


@pytest.mark.parametrize("bad", ["free", "unknown", "priced", "before hello"])
def test_a_buy_of_no_paid_car_is_a_bad_frame(s, bad):
    """Only a paid car, after hello, with no price: the price is the server's."""
    c, uid = s.player("ana")
    earn(s, uid, 10**6)
    change = {"free": {"skin": "yellow"}, "unknown": {"skin": "dragon"}, "priced": {"price": 1}}
    with c.websocket_connect(WS) as ws:
        if bad != "before hello":
            ws.send_json(HELLO)
            ws.receive_json()
        ws.send_json({"t": "buy", "skin": "beetle", **change.get(bad, {})})
        assert ws.receive_json() == hub.error("bad") and closed(ws) == 1008
    assert s.count("garage") == 0


def test_a_buy_after_the_session_ended_buys_nothing(s):
    """A ban (admin banir ends the sessions from outside the hub) reaches the socket at its next buy too."""
    c, uid = s.player("ana")
    earn(s, uid, PRICE["beetle"])
    with c.websocket_connect(WS) as ws:
        ws.send_json(HELLO)
        ws.receive_json()
        s.db.execute("DELETE FROM sessions WHERE user_id = ?", (uid,))
        assert buy(ws, "beetle") == hub.error("ended")
    assert s.count("garage") == 0
