"""Ranked solo over /ws (plan §5, §6, §8 M3): the server simulates and paces every run, the client only sends
inputs. The hub's clock is the test's: time passes, and the hub's ticker runs, only when a test says so."""

import asyncio
import json
import time
import zlib

import pytest
from starlette.websockets import WebSocketDisconnect

from conftest import BASE, BUILD
from jogo_de_carro.golden import REPLAYS
from jogo_de_carro.run import simulate
from jogo_server import admin, hub, load
from jogo_server import app as site

WS = BASE.replace("https", "wss") + "/ws"  # the cookies' domain (TestClient defaults to ws://testserver)
HELLO = {"t": "hello", "build": BUILD, "py": "3.12.12", "pg": "2.5.7", "skin": "yellow"}
LOG = json.loads((REPLAYS / "normal_crash.json").read_text(encoding="utf-8"))  # crashes at 49.6 s


class Clock:
    t = 1000.0

    def __call__(self) -> float:
        return self.t


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def s(make_site, clock):
    return make_site(clock=clock)


@pytest.fixture(autouse=True)
def corpus_seed(monkeypatch):
    monkeypatch.setattr(hub, "new_seed", lambda: LOG["seed"])


@pytest.fixture
def no_bot_rule(monkeypatch):
    """The corpus is steered by the autopilot (tests/test_run.py), which the bot rule rightly flags."""
    monkeypatch.setenv("FLAG_ADHERENCE", "2")
    monkeypatch.setenv("FLAG_MIN_N", "1e9")


def stored(s, uid: int, mode: str, score: int, state: str = "ok", seconds: float = 180) -> None:
    """A finished run, stored as the hub stores one: inserted live, then ended (the board is kept on that)."""
    sql = "INSERT INTO runs(user_id, kind, mode, skin, seed, shared, build, started, state)"
    sql += " VALUES (?, 'solo', ?, 'yellow', 1, 0, ?, 0, 'live') RETURNING id"
    rid = s.db.execute(sql, (uid, mode, BUILD)).fetchone()[0]
    sql = "UPDATE runs SET score = ?, seconds = ?, state = ? WHERE id = ?"
    s.db.execute(sql, (score, seconds, state, rid))


@pytest.fixture
def board(s):
    """Ten players far ahead in Normal, so a run is not held for the top 10."""
    for i in range(10):
        stored(s, s.user(f"top{i}@x.test", f"top{i}"), "normal", 10**6 - i)


def later(s, clock: Clock, dt: float) -> None:
    """dt seconds pass on a healthy event loop: the ticker runs every 0.1 s."""
    while dt > 1e-9:
        step = min(hub.TICK_S, dt)
        clock.t, dt = clock.t + step, dt - step
        s.portal.call(s.hub.tick)


def until(cond) -> None:
    deadline = time.monotonic() + 5
    while not cond():
        assert time.monotonic() < deadline, "the hub never got to it"
        time.sleep(0.0002)


def closed(ws) -> int:
    with pytest.raises(WebSocketDisconnect) as e:
        ws.receive_json()
    return e.value.code


class Racer:
    """A client in ranked solo: hello, solo, ready, then a log's inputs every 12 ticks."""

    def __init__(self, s, clock: Clock, ws, mode: str = "normal", skin: str = "yellow") -> None:
        self.s, self.clock, self.ws = s, clock, ws
        ws.send_json({**HELLO, "skin": skin})
        assert ws.receive_json()["t"] == "welcome"
        ws.send_json({"t": "solo", "mode": mode})
        self.match = ws.receive_json()
        self.m = self.match["m"]
        ws.send_json({"t": "ready", "m": self.m})
        self.go = ws.receive_json()
        self.t0 = clock.t + hub.COUNTDOWN_S

    def play(self, log: dict, fin: dict | None = None, at=lambda k: k / 120 + 0.05, stall=()) -> dict:
        """Sends message k at(k) seconds after tick 0 (default: 50 ms after its last tick); stall: (k,
        seconds) the server's loop is stuck just before message k. Returns the result."""
        live = self.s.hub.live[self.m]
        for k, msg in load.messages(log, self.m, fin):
            if stall and k == stall[0]:
                self.clock.t += stall[1]  # no tick ran: the backlog arrives all at once
            later(self.s, self.clock, self.t0 + at(k) - self.clock.t)
            sent = len(live.arr)
            self.ws.send_json(msg)
            until(lambda: len(live.arr) > sent or self.m not in self.s.hub.live)  # noqa: B023
            if self.m not in self.s.hub.live:
                return self.ws.receive_json()
        raise AssertionError("the run never ended")


def honest(log: dict) -> dict:
    run = simulate(hub.assets(), log)
    return {"outcome": run.outcome, "score": run.score.total}


def row(s, m: int):
    return s.db.execute("SELECT * FROM runs WHERE id = ?", (m,)).fetchone()


# --- the whole flow ---------------------------------------------------------------------------------------


def test_honest_run_is_ok_with_the_servers_score(s, clock, board, no_bot_rule):
    c, _ = s.player("ana")
    with c.websocket_connect(WS) as ws:
        r = Racer(s, clock, ws)
        assert r.match == {"t": "match", "m": r.m, "kind": "solo", "mode": "normal", "op": None}  # no seed
        assert r.go == {"t": "go", "m": r.m, "seed": LOG["seed"]}  # the seed, only now
        res = r.play(LOG, fin=honest(LOG))
    want = simulate(hub.assets(), LOG)
    assert res == {
        "t": "result", "m": r.m, "run": r.m, "state": "ok", "why": None, "outcome": "crash",
        "score": want.score.total, "secs": round(want.seconds, 1), "rank": 11, "verdict": None, "op": None,
        "coins": want.score.coins, "wallet": want.score.coins,
    }  # fmt: skip
    db, score = row(s, r.m), want.score.total
    assert (db["state"], db["ticks"], db["score"], db["client_score"]) == ("ok", want.tick, score, score)
    stored = json.loads(zlib.decompress(db["log"]))
    assert stored["v"] == 1 and stored["ev"] == LOG["ev"]
    assert len(stored["arr"]) == -(-LOG["end"] // 12) and stored["arr"][0] == [12, 150]
    assert db["max_lag"] == pytest.approx(0.05, abs=0.01)
    assert json.loads(db["features"])["n"] > 0
    assert s.hub.live == {}


def test_altered_inputs_are_scored_by_the_server(s, clock, board, no_bot_rule):
    """Other inputs than the corpus's, the corpus's result claimed: the server's simulation decides, and
    ends the run at its own crash, before the claim even arrives."""
    altered = {**LOG, "ev": [e for e in LOG["ev"] if e[1] not in ("L", "R") or e[0] < 2000]}
    want = simulate(hub.assets(), altered)
    assert want.outcome == "crash" and want.tick < LOG["end"]
    c, _ = s.player("ana")
    with c.websocket_connect(WS) as ws:
        res = Racer(s, clock, ws).play(altered, fin=honest(LOG))
    assert (res["state"], res["outcome"], res["score"]) == ("ok", "crash", want.score.total)
    assert res["score"] != honest(LOG)["score"] and row(s, res["run"])["ticks"] == want.tick


def test_a_wrong_claim_is_a_desync(s, clock, board, no_bot_rule):
    c, _ = s.player("ana")
    with c.websocket_connect(WS) as ws:
        claim = {**honest(LOG), "score": honest(LOG)["score"] + 1000}
        res = Racer(s, clock, ws).play(LOG, fin=claim)
    assert (res["state"], res["why"], res["score"]) == ("ok", "desync", honest(LOG)["score"])
    assert row(s, res["run"])["client_score"] == claim["score"]
    assert s.client().get("/saude").json()["desync_24h"] == 1


def test_a_run_that_would_enter_the_top_10_waits_for_review(s, clock, no_bot_rule):
    c, _ = s.player("ana")
    with c.websocket_connect(WS) as ws:
        res = Racer(s, clock, ws).play(LOG, fin=honest(LOG))
    assert (res["state"], res["why"], res["rank"]) == ("review", "top10", None)
    site.review_mail(s.app.state)
    [(to, msg)] = s.outbox
    assert to == "admin@jogo.test" and "1 corrida(s) em análise" in msg["Subject"]
    assert s.client().get("/saude").json()["review"] == 1
    assert 'class="pos"' not in s.client().get("/ranking").text  # held: not on the board


def test_a_bot_like_run_in_ranks_11_to_100_waits_for_review(s, clock, board):
    c, _ = s.player("ana")
    with c.websocket_connect(WS) as ws:
        res = Racer(s, clock, ws).play(LOG, fin=honest(LOG))
    assert (res["state"], res["why"]) == ("review", "bot")


def test_one_run_in_review_per_player_and_mode(s, clock, no_bot_rule):
    """An empty board: a 0-point give-up is not held, and only the player's best run waits for review."""
    c, _ = s.player("ana")
    with c.websocket_connect(WS) as ws:
        r = Racer(s, clock, ws)
        ws.send_json({"t": "leave", "m": r.m})
        res = ws.receive_json()
        assert (res["state"], res["why"], res["score"], res["rank"]) == ("ok", None, 0, 1)
    results = []
    for end in (600, 300, 1200):  # the corpus run given up there
        cut = {**LOG, "end": end, "ev": [e for e in LOG["ev"] if e[0] < end]}
        with c.websocket_connect(WS) as ws:
            results.append(Racer(s, clock, ws).play(cut, fin=honest(cut)))
    assert 0 < results[1]["score"] < results[0]["score"] < results[2]["score"]
    assert [(r["state"], r["why"]) for r in results] == [
        ("review", "top10"), ("rejected", "substituida"), ("review", "top10"),
    ]  # fmt: skip
    assert [(row(s, r["run"])["state"], row(s, r["run"])["why"]) for r in results] == [
        ("rejected", "substituida"), ("rejected", "substituida"), ("review", "top10"),
    ]  # fmt: skip


# --- pacing ---------------------------------------------------------------------------------------------


@pytest.mark.parametrize(("speed", "why"), [(10.0, "adiantado"), (0.5, "ritmo")])
def test_pacing(s, clock, speed, why):
    c, _ = s.player("ana")
    with c.websocket_connect(WS) as ws:
        res = Racer(s, clock, ws).play(LOG, fin=honest(LOG), at=lambda k: k / 120 / speed + 0.05)
    assert (res["state"], res["why"], res["rank"]) == ("rejected", why, None)
    assert res["score"] < honest(LOG)["score"]  # cut off at its last accepted input
    assert row(s, res["run"])["state"] == "rejected"


@pytest.mark.parametrize("secs", [3.0, 7.0])  # 7 s: a backlog of 70 messages, over the rate limit's burst
def test_a_server_stall_is_not_the_players_lag(s, clock, board, no_bot_rule, secs):
    c, _ = s.player("ana")
    with c.websocket_connect(WS) as ws:
        res = Racer(s, clock, ws).play(LOG, fin=honest(LOG), stall=(2400, secs))  # stuck at 20 s
    assert (res["state"], res["why"]) == ("ok", None)
    assert s.hub.stall == pytest.approx(secs, abs=0.11)
    assert row(s, res["run"])["max_lag"] < 0.2


def test_a_stall_excuses_only_its_backlog(s, clock, board, no_bot_rule):
    """3 s stuck at 20 s, then the player drifts to 4.5 s behind real time: once the backlog is in, the stall
    no longer covers it."""
    c, _ = s.player("ana")
    with c.websocket_connect(WS) as ws:
        drift = lambda k: k / 120 + min(4.5, 0.05 + max(0, k - 2400) / 120 * 0.2)  # noqa: E731
        res = Racer(s, clock, ws).play(LOG, fin=honest(LOG), at=drift, stall=(2400, 3.0))
    assert (res["state"], res["why"]) == ("rejected", "ritmo")
    assert 2.0 < row(s, res["run"])["max_lag"] < 2.1


def test_silence_ends_the_run(s, clock):
    c, _ = s.player("ana")
    with c.websocket_connect(WS) as ws:
        Racer(s, clock, ws)
        later(s, clock, 5.5)
        res = ws.receive_json()
    assert (res["state"], res["why"], res["score"]) == ("rejected", "conexao", 0)


def test_ready_deadline(s, clock):
    c, _ = s.player("ana")
    with c.websocket_connect(WS) as ws:
        ws.send_json(HELLO)
        ws.receive_json()
        ws.send_json({"t": "solo", "mode": "dificil"})
        m = ws.receive_json()["m"]
        later(s, clock, 9.9)
        assert m in s.hub.live
        later(s, clock, 0.6)
        res = ws.receive_json()
        assert (res["m"], res["state"], res["why"], res["outcome"]) == (m, "rejected", "prazo", None)
        ws.send_json({"t": "ready", "m": m})  # too late: ignored, no seed
        ws.send_json({"t": "solo", "mode": "dificil"})
        assert ws.receive_json()["t"] == "match"
    assert row(s, m)["state"] == "rejected"


def test_leave_gives_up_or_uses_the_attempt(s, clock, board, no_bot_rule):
    c, _ = s.player("ana")
    with c.websocket_connect(WS) as ws:
        r = Racer(s, clock, ws)
        later(s, clock, 3)
        ws.send_json({"t": "in", "m": r.m, "k": 12, "ev": [[0, 1]]})
        ws.send_json({"t": "leave", "m": r.m})
        res = ws.receive_json()
        assert (res["state"], res["outcome"], res["secs"]) == ("ok", "giveup", 0.1)
        ws.send_json({"t": "solo", "mode": "normal"})
        m = ws.receive_json()["m"]
        ws.send_json({"t": "leave", "m": m})
        assert ws.receive_json()["why"] == "prazo"


# --- the trust boundary ---------------------------------------------------------------------------------


BAD = {
    "true k": lambda m: {"t": "in", "m": m, "k": True, "ev": []},  # JSON true is no int
    "true held": lambda m: {"t": "in", "m": m, "k": 12, "ev": [[0, True]]},
    "two steers a tick": lambda m: {"t": "in", "m": m, "k": 12, "ev": [[0, "L"], [0, "R"]]},
    "float k": lambda m: {"t": "in", "m": m, "k": 12.0, "ev": []},
    "string score": lambda m: {"t": "in", "m": m, "k": 12, "ev": [], "fin": {"outcome": "win", "score": "9"}},
    "huge score": lambda m: {"t": "in", "m": m, "k": 12, "ev": [], "fin": {"outcome": "win", "score": 2**63}},
    "score < 0": lambda m: {"t": "in", "m": m, "k": 12, "ev": [], "fin": {"outcome": "win", "score": -9}},
    "no new tick": lambda m: {"t": "in", "m": m, "k": 0, "ev": [], "fin": {"outcome": "giveup", "score": 0}},
    "k off the 12 ticks": lambda m: {"t": "in", "m": m, "k": 13, "ev": []},
    "extra field": lambda m: {"t": "in", "m": m, "k": 12, "ev": [], "x": 1},
    "too far": lambda m: {"t": "in", "m": m, "k": 241, "ev": []},
    "foreign m": lambda m: {"t": "in", "m": m + 1, "k": 12, "ev": []},
    "ready twice": lambda m: {"t": "ready", "m": m},
    "solo while racing": lambda m: {"t": "solo", "mode": "normal"},
    "hello twice": lambda m: HELLO,
    "unknown type": lambda m: {"t": "replay", "m": m},
    "not json": lambda m: "{not json",
    "deep": lambda m: "[" * 100_000,
    "binary": lambda m: b"{}",
    "too big": lambda m: " " * (16 * 1024 + 1),
}


@pytest.mark.parametrize("bad", BAD.values(), ids=BAD.keys())
def test_garbage_voids_the_run_and_closes_1008(s, clock, bad):
    c, _ = s.player("ana")
    with c.websocket_connect(WS) as ws:
        r = Racer(s, clock, ws)
        later(s, clock, 2.25 + 0.15)
        msg = bad(r.m)
        if isinstance(msg, bytes):
            ws.send_bytes(msg)
        elif isinstance(msg, str):
            ws.send_text(msg)
        else:
            ws.send_json(msg)
        res = ws.receive_json()
        assert (res["t"], res["state"], res["why"]) == ("result", "rejected", "invalido")
        assert ws.receive_json()["code"] == "bad"
        assert closed(ws) == 1008
    assert row(s, r.m)["why"] == "invalido" and s.hub.socks == {}


def test_inputs_before_go_and_a_foreign_ready_close_1008(s, clock):
    c, _ = s.player("ana")
    with c.websocket_connect(WS) as ws:
        ws.send_json(HELLO)
        ws.receive_json()
        ws.send_json({"t": "solo", "mode": "normal"})
        m = ws.receive_json()["m"]
        ws.send_json({"t": "in", "m": m, "k": 12, "ev": []})
        assert ws.receive_json()["why"] == "invalido"
        assert ws.receive_json()["code"] == "bad"
        assert closed(ws) == 1008
    c, _ = s.player("bia")
    with c.websocket_connect(WS) as ws:
        ws.send_json(HELLO)
        ws.receive_json()
        ws.send_json({"t": "ready", "m": m})  # someone else's run
        assert ws.receive_json()["code"] == "bad"
        assert closed(ws) == 1008


def test_message_rate_limit(s, clock):
    c, _ = s.player("ana")
    with c.websocket_connect(WS) as ws:
        ws.send_json(HELLO)
        ws.receive_json()
        ws.send_json({"t": "solo", "mode": "normal"})
        m = ws.receive_json()["m"]
        ws.send_json({"t": "leave", "m": m})
        ws.receive_json()
        later(s, clock, 3)  # the bucket refills
        for _ in range(hub.BURST):
            ws.send_json({"t": "leave", "m": m})  # harmless once the run is over
        ws.send_json({"t": "leave", "m": m})
        assert ws.receive_json()["code"] == "bad"
        assert closed(ws) == 1008


# --- who may connect, and when ----------------------------------------------------------------------------


def test_handshake_refusals(s):
    evil = {"origin": "https://evil.test"}
    with pytest.raises(WebSocketDisconnect) as e, s.client().websocket_connect(WS, headers=evil):
        pass
    assert e.value.code == 1008  # refused before accept(): uvicorn answers the handshake with 403

    c, uid = s.player("ana")
    with pytest.raises(WebSocketDisconnect), c.websocket_connect(WS, headers={"origin": "null"}):
        pass

    for client, text in ((s.client(), "Entre no site"), (c, "apelido")):
        if client is c:
            s.db.execute("UPDATE users SET nick = NULL WHERE id = ?", (uid,))
        with client.websocket_connect(WS) as ws:  # the page works logged out: play offline
            err = ws.receive_json()
            assert err["t"] == "error" and err["code"] == "login" and text in err["msg"]
            assert closed(ws) == 1008
    assert s.hub.socks == {}


def test_version_mismatch(s):
    c, _ = s.player("ana")
    for field, value in (("build", "f" * 40), ("py", "3.14.0"), ("pg", "2.5.8")):
        with c.websocket_connect(WS) as ws:
            ws.send_json({**HELLO, field: value})
            assert ws.receive_json() == {"t": "error", "code": "version", "msg": hub.REFUSED["version"]}
            assert closed(ws) == 1008


def test_a_second_socket_closes_the_first(s, clock):
    c, uid = s.player("ana")
    with c.websocket_connect(WS) as one:
        r = Racer(s, clock, one)
        with c.websocket_connect(WS) as two:
            assert one.receive_json() == {"t": "error", "code": "busy", "msg": hub.REFUSED["busy"]}
            assert closed(one) == 1008
            two.send_json(HELLO)
            assert two.receive_json()["t"] == "welcome"
            assert list(s.hub.socks) == [uid] and s.hub.socks[uid].skin == "yellow"
    assert (row(s, r.m)["state"], row(s, r.m)["why"]) == ("rejected", "conexao")


def test_ending_sessions_closes_the_socket(s, clock):
    c, _ = s.player("ana")
    with c.websocket_connect(WS) as ws:
        r = Racer(s, clock, ws)
        assert c.post("/conta/sair-todos").status_code == 303
        err = ws.receive_json()
        assert err["code"] == "login" and "sessão" in err["msg"]
        assert closed(ws) == 1008
    assert row(s, r.m)["why"] == "conexao"


def test_a_ban_from_the_admin_command_stops_the_next_start(s, clock):
    c, uid = s.player("ana")
    with c.websocket_connect(WS) as ws:
        ws.send_json(HELLO)
        ws.receive_json()
        s.db.execute("UPDATE users SET role = 'banned' WHERE id = ?", (uid,))
        ws.send_json({"t": "solo", "mode": "normal"})
        assert ws.receive_json()["code"] == "login"
        assert closed(ws) == 1008


def test_drain_admission_and_start_limit(make_site, clock, monkeypatch, tmp_path):
    s = make_site(clock=clock, max_ativas=1)
    a, _ = s.player("ana")
    b, _ = s.player("bia")
    with a.websocket_connect(WS) as wa, b.websocket_connect(WS) as wb:
        for ws in (wa, wb):
            ws.send_json(HELLO)
            ws.receive_json()
        (tmp_path / "drain").touch()
        wa.send_json({"t": "solo", "mode": "normal"})
        assert wa.receive_json() == {"t": "error", "code": "drain", "msg": hub.REFUSED["drain"]}
        (tmp_path / "drain").unlink()
        wa.send_json({"t": "solo", "mode": "normal"})
        m = wa.receive_json()["m"]
        wb.send_json({"t": "solo", "mode": "normal"})
        assert wb.receive_json()["code"] == "full"  # the socket stays open
        assert s.client().get("/saude").json()["ativas"] == 1
        monkeypatch.setattr(hub, "STARTS", 1)
        wa.send_json({"t": "leave", "m": m})
        wa.receive_json()
        wa.send_json({"t": "solo", "mode": "normal"})
        assert wa.receive_json()["code"] == "rate"


def test_a_restart_rejects_live_runs(s, clock):
    uid = s.user("ana@x.test", "ana")
    sql = "INSERT INTO runs(user_id, kind, mode, skin, seed, shared, build, started, state)"
    sql += " VALUES (?, 'solo', 'normal', 'yellow', 1, 0, ?, 0, 'live') RETURNING id"
    rid = s.db.execute(sql, (uid, BUILD)).fetchone()[0]
    hub.Hub(s.app.state, clock)
    assert (row(s, rid)["state"], row(s, rid)["why"]) == ("rejected", "reinicio")


# --- the board --------------------------------------------------------------------------------------------


def test_ranking_pages(s, board):
    uid = s.user("eu@x.test", "eu")
    for mode, score, state in (
        ("normal", 5, "ok"),
        ("normal", 7, "ok"),
        ("normal", 99**5, "review"),
        ("facil", 3, "ok"),
    ):
        stored(s, uid, mode, score, state, 83.4)
    s.db.execute("UPDATE users SET role = 'banned' WHERE nick = 'top9'")
    r = s.client().get("/ranking?modo=normal")
    assert r.status_code == 200 and r.text.count('class="pos"') == 10  # top9 banned, eu once with its best
    assert r.text.index("top0") < r.text.index("top8") < r.text.index(">eu<") and "1:23" in r.text
    assert "Você:" not in r.text
    c = s.client()
    s.login(c, uid)
    assert "Você: <b>#10</b>" in c.get("/ranking?modo=normal").text
    assert "Ninguém no ranking Difícil" in c.get("/ranking?modo=dificil").text
    assert c.get("/ranking?modo=x").status_code == 404
    home = s.client().get("/").text
    assert home.count('class="pos"') == 10 + 1 and "Ninguém ainda" in home  # Normal's top 10 and Fácil's one
    s.db.execute("DELETE FROM bests")
    assert "top0" in s.client().get("/").text  # cached for 10 s


# --- review tooling ---------------------------------------------------------------------------------------


def test_review_tooling(s, clock, capsys, monkeypatch, no_bot_rule):
    monkeypatch.setenv("JOGO_DB", s.app.state.cfg.db)
    c, uid = s.player("ana")
    with c.websocket_connect(WS) as ws:
        res = Racer(s, clock, ws).play(LOG, fin=honest(LOG))
    run = str(res["run"])
    assert admin.main(["revisar"]) == 0
    out = capsys.readouterr().out
    assert f"{run} ana" in out and "top10" in out and "1 em análise" in out

    assert admin.main(["export", run]) == 0
    assert json.loads(capsys.readouterr().out) == LOG  # what --replay shows the reviewer

    assert admin.main(["aprovar", run]) == 0 and admin.main(["aprovar", run]) == 1
    assert "ana" in s.client().get("/ranking").text
    assert admin.main(["rejeitar", run]) == 0 and row(s, res["run"])["state"] == "rejected"
    assert hub.board(s.db, "normal") == []  # out of the board again

    s.db.execute("UPDATE runs SET state = 'review' WHERE id = ?", (res["run"],))
    assert admin.main(["banir", "ANA"]) == 0 and admin.main(["banir", "ninguem"]) == 1
    assert s.db.execute("SELECT role FROM users WHERE id = ?", (uid,)).fetchone()[0] == "banned"
    assert s.count("sessions WHERE user_id = ?", uid) == 0 and row(s, res["run"])["state"] == "rejected"
    assert admin.main(["export", "x"]) == 2 and "revisar" in capsys.readouterr().err


def test_load_tool(monkeypatch, capsys):
    monkeypatch.setattr(hub, "new_seed", hub.new_seed)  # load.main replaces it: put it back afterwards
    asyncio.run(load.main(2, 0.5))
    out = capsys.readouterr().out
    assert "2 corridas" in out and "atraso do loop" in out and "review/top10': 2" in out
