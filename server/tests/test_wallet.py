"""The wallet (plan §2, E1): the coins of a player's paid runs, as the server simulated them, never a count
from the client. Derived, never stored: each result says what its run paid and the balance right after it."""

import contextlib
import json

import pytest

import test_live
import test_ranked
from jogo_de_carro.run import simulate
from jogo_server import admin, db, hub
from jogo_server import app as site
from test_challenge import first, play
from test_live import CRASH, LONG, WIN, T, cut, friends, go, idle, race
from test_ranked import HELLO, LOG, WS, Racer, honest, row

clock, make, s = test_live.clock, test_live.make, test_live.s  # the fixtures
board, no_bot_rule = test_ranked.board, test_ranked.no_bot_rule


@pytest.fixture
def corpus_seed(make, monkeypatch):
    """A ranked run plays the corpus's crash, on its seed (make's is the shared road's)."""
    monkeypatch.setattr(hub, "new_seed", lambda: LOG["seed"])


def coins(log: dict) -> int:
    return simulate(hub.assets(), log).score.coins


# --- ranked -----------------------------------------------------------------------------------------------


def test_a_ranked_run_pays_the_servers_count(s, clock, board, no_bot_rule, corpus_seed):
    """A wrong claim (desync) pays the same: the server's count; the next welcome carries the balance."""
    c, _ = s.player("ana")
    want = coins(LOG)
    for i, why in enumerate((None, "desync")):
        with c.websocket_connect(WS) as ws:
            res = Racer(s, clock, ws).play(LOG, fin={**honest(LOG), "score": 1} if why else honest(LOG))
        assert (res["state"], res["why"], res["coins"], res["wallet"]) == ("ok", why, want, want * (i + 1))
        assert row(s, res["run"])["coins"] == want
    with c.websocket_connect(WS) as ws:
        ws.send_json(HELLO)
        assert ws.receive_json()["coins"] == 2 * want


CUT_OFF = {  # 20 s into the corpus run, then 3 s behind real time, ahead of it, or keys that do not exist
    "ritmo": (LOG, lambda k: k / 120 + 0.05 + 3 * (k > 2400)),
    "adiantado": (LOG, lambda k: min(k, 2400) / 120 + 0.05),
    "invalido": (
        {**LOG, "ev": sorted([*LOG["ev"], [2400, 5]], key=lambda e: e[0])},
        lambda k: k / 120 + 0.05,
    ),
}


@pytest.mark.parametrize("why", CUT_OFF)
def test_a_run_the_hub_rejects_pays_nothing(s, clock, corpus_seed, why):
    log, at = CUT_OFF[why]
    c, _ = s.player("ana")
    with c.websocket_connect(WS) as ws:
        res = Racer(s, clock, ws).play(log, fin=honest(LOG), at=at)
    assert (res["state"], res["why"], res["coins"], res["wallet"]) == ("rejected", why, 0, 0)
    r = row(s, res["run"])
    assert r["coins"] == coins(cut(LOG, r["ticks"])) > 0  # kept all the same (audit)


def test_a_lost_connection_pays(s, clock, corpus_seed):
    """Silent for 6 s, 20 s in: its inputs were accepted, and dropping out gains nothing over leaving."""
    c, _ = s.player("ana")
    with c.websocket_connect(WS) as ws:
        res = Racer(s, clock, ws).play(LOG, at=lambda k: k / 120 + 0.05 + 6 * (k > 2400))
    assert (res["state"], res["why"], row(s, res["run"])["ticks"]) == ("rejected", "conexao", 2400)
    assert res["coins"] == res["wallet"] == coins(cut(LOG, 2400)) > 0


def test_prazo_and_a_restart_pay_nothing(s, clock, corpus_seed):
    c, uid = s.player("ana")
    with c.websocket_connect(WS) as ws:
        ws.send_json(HELLO)
        ws.receive_json()
        ws.send_json({"t": "solo", "mode": "normal"})
        ws.send_json({"t": "leave", "m": ws.receive_json()["m"]})  # before go
        res = ws.receive_json()
    assert (res["why"], res["coins"], res["wallet"]) == ("prazo", 0, 0)
    sql = "INSERT INTO runs(user_id, kind, mode, skin, seed, shared, build, started, state, coins)"
    s.db.execute(sql + " VALUES (?, 'solo', 'normal', 'yellow', 1, 0, 'x', 0, 'live', 9)", (uid,))
    hub.Hub(s.app.state, clock)  # drops the run in progress (its coins, were any counted so far)
    assert hub.wallet(s.db, uid) == 0


def test_review_pays_until_the_admin_rejects_it(s, clock, no_bot_rule, corpus_seed, monkeypatch):
    """An empty board: a run given up at 5 s waits for review, then the whole run replaces it there
    (substituida: still paid); the admin rejects that one and its coins leave the wallet."""
    monkeypatch.setenv("JOGO_DB", s.app.state.cfg.db)
    c, uid = s.player("ana")
    short = cut(LOG, 600)
    results = []
    for log in (short, LOG):
        with c.websocket_connect(WS) as ws:
            results.append(Racer(s, clock, ws).play(log, fin=honest(log)))
    assert [(r["state"], r["why"], r["coins"], r["wallet"]) for r in results] == [
        ("review", "top10", coins(short), coins(short)),
        ("review", "top10", coins(LOG), coins(short) + coins(LOG)),
    ]  # fmt: skip
    assert row(s, results[0]["run"])["why"] == "substituida" and hub.wallet(s.db, uid) == results[1]["wallet"]
    assert admin.main(["rejeitar", str(results[1]["run"])]) == 0
    assert hub.wallet(s.db, uid) == coins(short)


# --- between friends --------------------------------------------------------------------------------------


@pytest.mark.parametrize("how", ["close", "pacing", "deleted"])
def test_a_race_pays_both_up_to_where_it_stopped(s, clock, how):
    """bia drops out 10 s in, 12 ticks ahead of ana: ana's run is decided there and pays that far. bia's pays
    if she lost the connection, not if she broke the pace; deleting her account takes hers along, not ana's
    (trigger matches_keep_runs)."""
    with contextlib.ExitStack() as stack:
        ana, bia = friends(s, stack, "ana", "bia")
        race(s, clock, go(s, clock, ana, bia), (bia, cut(WIN, 1200), None), (ana, cut(WIN, 1188), None))
        if how == "close":
            bia.ws.close()
        elif how == "pacing":
            bia.send({"t": "in", "m": bia.m, "k": 1440, "ev": []})  # 2 s of inputs at once
        else:
            assert bia.client.post("/conta/excluir", data={"confirmar": "bia"}).status_code == 200
        idle(s, lambda: ana.m not in s.hub.live)
    mine = coins(cut(WIN, 1188))
    assert (ana.result()["outcome"], ana.result()["coins"], ana.result()["wallet"]) == ("decided", mine, mine)
    paid = {"close": coins(cut(WIN, 1200)), "pacing": 0, "deleted": 0}[how]
    assert hub.wallet(s.db, bia.uid) == paid
    if how == "pacing":
        assert (bia.result()["why"], bia.result()["coins"], bia.result()["wallet"]) == ("adiantado", 0, 0)
    if how == "deleted":
        assert row(s, bia.m) is None and row(s, ana.m)["match_id"] is None and s.count("matches") == 0


def test_a_deleted_accounts_ids_are_not_given_out_while_its_race_goes_on(s, clock):
    """bia deletes her account mid-race, and caio challenges dani before the hub has ended her run: SQLite
    would give caio's run her run's id and his challenge the race's (the highest, both gone), and ending her
    run would then write it, coins included, over his, and the race's verdict over his challenge."""
    with contextlib.ExitStack() as stack:
        ana, bia, caio, dani = friends(s, stack, "ana", "bia", "caio", "dani")
        race(s, clock, go(s, clock, ana, bia), (bia, cut(WIN, 1200), None), (ana, cut(WIN, 1188), None))
        mid = row(s, bia.m)["match_id"]
        highest = s.db.execute("SELECT max(runs.id), max(matches.id) FROM runs, matches").fetchone()
        assert (bia.m, mid) == tuple(highest)

        async def delete_then_challenge() -> None:  # one step of the loop, ahead of the task kick spawns
            with db.tx(s.db):  # excluir's
                site.end_sessions(s.app.state, bia.uid)
                s.db.execute("DELETE FROM users WHERE id = ?", (bia.uid,))
            msg = {"t": "challenge", "to": dani.uid, "mode": "normal"}
            await s.hub.handle(s.hub.socks[caio.uid], json.dumps(msg))

        s.portal.call(delete_then_challenge)
        idle(s)
        ana.send({"t": "leave", "m": ana.m})  # (her race is over: nothing)
        caio.m = caio.of("match")[-1]["m"]
        r = row(s, caio.m)
        assert (caio.m, r["user_id"], r["state"], r["coins"]) == (bia.m + 1, caio.uid, "live", None)
        assert [tuple(m) for m in s.db.execute("SELECT id, state FROM matches")] == [(mid + 1, "racing")]
    mine = coins(cut(WIN, 1188))
    assert (ana.result()["verdict"], ana.result()["coins"], ana.result()["wallet"]) == (None, mine, mine)
    assert hub.wallet(s.db, caio.uid) == 0


def test_a_challenge_pays_both_and_outlives_the_challenger(s, clock):
    """bia's challenge, played by ana: both paid. Then bia deletes her account: the match goes with it, ana's
    run and its coins stay, and bia's wallet is 0."""
    with contextlib.ExitStack() as stack:
        ana, bia = friends(s, stack, "ana", "bia")
        mid = first(s, clock, bia, ana)  # bia crashes on tick T
        race(s, clock, play(s, clock, ana, mid), (ana, LONG, None))  # ana wins with her first message past it
        hers, mine = coins(CRASH), coins(cut(WIN, T - T % 12 + 12))
        assert (bia.result()["coins"], bia.result()["wallet"]) == (hers, hers)
        assert (ana.result()["verdict"], ana.result()["coins"], ana.result()["wallet"]) == ("win", mine, mine)
        assert bia.client.post("/conta/excluir", data={"confirmar": "bia"}).status_code == 200
    assert s.count("matches") == 0 and row(s, ana.m)["match_id"] is None
    assert (hub.wallet(s.db, ana.uid), hub.wallet(s.db, bia.uid)) == (mine, 0)
