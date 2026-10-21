"""Challenges between friends over /ws (plan §5 "Desafiar amigo", §8 M5): the challenger plays a run on the
shared road; once it is ok the friend gets one attempt, raced against the stored run, whose inputs reach them
through the same gate as a live rival's (Player checks every op against its own k + 24 as it arrives). Plus
/partidas."""

import contextlib
import re
import time

import pytest

import test_live
from jogo_de_carro.run import simulate
from jogo_server import admin, hub
from test_live import CRASH, LONG, WIN, Player, T, befriend, cut, friends, heard, idle, ops, race, sent
from test_ranked import honest as fin
from test_ranked import later, row

clock, make, s = test_live.clock, test_live.make, test_live.s  # the fixtures

CRASH_FIN = fin(CRASH)
DAYS_7 = 7 * 86400


def challenge(a: Player, b: Player, mode: str = "normal") -> dict:
    a.send({"t": "challenge", "to": b.uid, "mode": mode})
    return a.got[-1]


def first(s, clock, a: Player, b: Player, log: dict | None = CRASH, f: dict | None = CRASH_FIN) -> int:
    """a challenges b and plays log (no log: gives up right after go; no fin: gives up at its end). Returns
    the match id."""
    a.got.clear()
    a.m = challenge(a, b)["m"]
    a.send({"t": "ready", "m": a.m})
    if log:
        race(s, clock, clock.t + hub.COUNTDOWN_S, (a, log, f))
    if a.result() is None:
        a.send({"t": "leave", "m": a.m})
    return row(s, a.m)["match_id"]


def play(s, clock, b: Player, mid: int) -> float:
    """b takes their turn and is ready: returns the loop time of tick 0."""
    b.send({"t": "challenge_play", "id": mid})
    b.m = b.of("match")[-1]["m"]
    b.send({"t": "ready", "m": b.m})
    return clock.t + hub.COUNTDOWN_S


def the_match(s, mid: int):
    return s.db.execute("SELECT * FROM matches WHERE id = ?", (mid,)).fetchone()


def dones(p: Player) -> list[dict]:
    return p.of("challenge_done")


# --- the whole flow -----------------------------------------------------------------------------------------


def test_a_challenge_from_start_to_end(s, clock):
    """ana crashes on tick T; bia, raced against the stored run, wins with her first message past it. bia gets
    no seed before go and ana's inputs only through the gate; ana hears of it and sees it on /partidas."""
    crashed = simulate(hub.assets(), CRASH)
    hers = (crashed.score.total, round(crashed.seconds, 1))
    with contextlib.ExitStack() as stack:
        ana, bia = friends(s, stack, "ana", "bia:red")
        mid = first(s, clock, ana, bia)
        assert ana.of("match") == [
            {"t": "match", "m": ana.m, "kind": "challenge", "mode": "normal", "op": None}
        ]
        assert ana.result() == {
            "t": "result", "m": ana.m, "run": ana.m, "state": "ok", "why": None, "outcome": "crash",
            "score": hers[0], "secs": hers[1], "rank": None, "verdict": None, "op": None,
        }  # fmt: skip
        r, mt = row(s, ana.m), the_match(s, mid)
        assert (r["kind"], r["shared"], r["state"], r["match_id"]) == ("challenge", 1, "ok", mid)
        assert (mt["kind"], mt["a"], mt["b"], mt["state"], mt["winner"]) == (
            "challenge",
            ana.uid,
            bia.uid,
            "open",
            None,
        )
        assert abs(mt["expires"] - (time.time() + DAYS_7)) < 60
        heard(bia, lambda m: m["t"] == "challenge_new")
        assert bia.of("challenge_new") == [
            {
                "t": "challenge_new",
                "id": mid,
                "from": "ana",
                "mode": "normal",
                "secs": hers[1],
                "score": hers[0],
            }
        ]
        assert hub.board(s.db, "normal") == [] and s.count("runs WHERE state = 'review'") == 0

        bia.send({"t": "challenge_play", "id": mid})
        bia.m = bia.of("match")[0]["m"]
        op = {"nick": "ana", "skin": "yellow"}
        assert bia.of("match") == [
            {"t": "match", "m": bia.m, "kind": "challenge", "mode": "normal", "op": op}
        ]
        assert the_match(s, mid)["state"] == "playing_b"
        bia.send({"t": "ready", "m": bia.m})
        assert bia.of("go") == [{"t": "go", "m": bia.m, "seed": WIN["seed"]}]  # the seed, only now
        assert bia.of("op") == []  # nothing of ana's before her own first inputs
        live = s.hub.live[bia.m]
        assert live.run.shared and live.run.world.rival == "yellow"
        t0 = clock.t + hub.COUNTDOWN_S
        race(s, clock, t0, (bia, cut(WIN, 12), None))
        assert [k for k, _ in ops(bia)] == [12, 24, 36]  # never the whole recording at once
        assert race(s, clock, t0, (bia, LONG, None)) == ("bia", T - T % 12 + 12)  # early: ana's run is over
        heard(ana, lambda m: m["t"] == "challenge_done")
        bia.send({"t": "challenge_play", "id": mid})  # one attempt
        assert bia.got[-1] == hub.error("gone") and bia.code is None

    won = simulate(hub.assets(), cut(WIN, 1020))
    mine = (won.score.total, round(won.seconds, 1))
    assert bia.result() == {
        "t": "result", "m": bia.m, "run": bia.m, "state": "ok", "why": None, "outcome": "decided",
        "score": mine[0], "secs": mine[1], "rank": None, "verdict": "win",
        "op": {"nick": "ana", "score": hers[0], "secs": hers[1]},
    }  # fmt: skip
    assert ops(bia) == sent(ana, CRASH, CRASH_FIN)  # the messages ana sent, as she sent them
    assert bia.of("op_end") == [{"t": "op_end", "m": bia.m, "k": T, "why": "crash"}]
    assert bia.got.index(bia.of("op_end")[0]) < bia.got.index(bia.result())
    assert dones(ana) == [
        {
            "t": "challenge_done",
            "id": mid,
            "verdict": "loss",
            "op": {"nick": "bia", "score": mine[0], "secs": mine[1]},
        }
    ]
    rb, mt = row(s, bia.m), the_match(s, mid)
    assert (rb["kind"], rb["match_id"], rb["seed"], rb["shared"], rb["state"], rb["ticks"]) == (
        "challenge", mid, WIN["seed"], 1, "ok", 1020,
    )  # fmt: skip
    assert (mt["state"], mt["winner"]) == ("done", bia.uid)
    assert hub.board(s.db, "normal") == [] and s.hub.live == {}

    page = ana.client.get("/partidas")
    assert page.status_code == 200
    assert "Derrota" in page.text and "0 vitórias · 1 derrota · 0 empates" in page.text
    assert f"{hers[0]:,} × {mine[0]:,}".replace(",", ".") in page.text


def test_crashing_first_loses_and_never_sees_the_rest(s, clock):
    """ana gives up at tick 1200 and closes the game; bia crashes on tick T: she loses at once, has seen ana's
    inputs only up to her own k + 24, then how ana's run ended."""
    with contextlib.ExitStack() as stack:
        ana, bia = friends(s, stack, "ana", "bia")
        mid = first(s, clock, ana, bia, cut(WIN, 1200), None)
        assert (row(s, ana.m)["outcome"], row(s, ana.m)["ticks"]) == ("giveup", 1200)
        ana.ws.close()  # offline: nothing to tell her, it is stored
        idle(s, lambda: ana.uid not in s.hub.socks)
        t0 = play(s, clock, bia, mid)
        assert race(s, clock, t0, (bia, CRASH, CRASH_FIN)) == ("bia", T)
    res = bia.result()
    assert (res["verdict"], res["state"], res["outcome"], res["op"]["nick"]) == ("loss", "ok", "crash", "ana")
    whole = sent(ana, cut(WIN, 1200))
    assert ops(bia) == sent(ana, cut(WIN, 1200), upto=T + hub.AHEAD) and len(ops(bia)) < len(whole)
    [end] = bia.of("op_end")
    assert end == {"t": "op_end", "m": bia.m, "k": 1200, "why": "giveup"}
    assert bia.got.index(end) == bia.got.index(res) - 1
    assert (the_match(s, mid)["state"], the_match(s, mid)["winner"]) == ("done", ana.uid)


@pytest.mark.parametrize("how", ["deadline", "leave", "close", "silence", "pacing", "bad"])
def test_a_forfeit_is_a_loss(s, clock, how):
    """bia, challenged while offline, finds it in her welcome; then misses the ready deadline, leaves before
    go, closes the game, goes silent after go, sends inputs far too early or a bad frame: she loses, and the
    attempt is used up."""
    crashed = simulate(hub.assets(), CRASH)
    hers = {"nick": "ana", "score": crashed.score.total, "secs": round(crashed.seconds, 1)}
    with contextlib.ExitStack() as stack:
        ana, bia = Player(s, "ana").connect(stack), Player(s, "bia")
        befriend(s, ana, bia)
        mid = first(s, clock, ana, bia)
        bia.connect(stack)
        offer = {"id": mid, "from": "ana", "mode": "normal", "secs": hers["secs"], "score": hers["score"]}
        assert bia.welcome["challenges"] == [offer]
        bia.send({"t": "challenge_play", "id": mid})
        bia.m = bia.of("match")[0]["m"]
        if how == "deadline":
            later(s, clock, hub.READY_S + 0.6)
            idle(s)
        elif how == "leave":
            bia.send({"t": "leave", "m": bia.m})
        elif how == "close":
            bia.ws.close()
        else:
            bia.send({"t": "ready", "m": bia.m})
            if how == "silence":
                later(s, clock, hub.SILENCE_S + 0.6)
                idle(s)
            else:  # 2 s of inputs at once; JSON true is no input
                bia.send(
                    {
                        "t": "in",
                        "m": bia.m,
                        "k": 240 if how == "pacing" else 12,
                        "ev": [] if how == "pacing" else [[0, True]],
                    }
                )
        heard(ana, lambda m: m["t"] == "challenge_done")
        if how not in ("close", "bad"):
            bia.send({"t": "challenge_play", "id": mid})  # once only
            assert bia.got[-1] == hub.error("gone") and bia.code is None
    why = {
        "deadline": "prazo",
        "leave": "prazo",
        "close": "conexao",
        "silence": "conexao",
        "pacing": "adiantado",
    }
    why = why.get(how, "invalido")
    b = row(s, bia.m)
    assert (b["state"], b["why"]) == ("rejected", why)
    assert (the_match(s, mid)["state"], the_match(s, mid)["winner"]) == ("done", ana.uid)
    assert [d["verdict"] for d in dones(ana)] == ["win"]
    if how in ("deadline", "leave", "close"):
        assert bia.of("op") == bia.of("op_end") == []  # before go, nothing of ana's run
    if how in ("deadline", "leave"):
        assert bia.result() == {
            "t": "result", "m": bia.m, "run": bia.m, "state": "rejected", "why": "prazo",
            "outcome": None, "score": None, "secs": None, "rank": None, "verdict": "loss", "op": hers,
        }  # fmt: skip
        assert bia.of("go") == []
    elif how == "silence":  # at tick 0: ana's inputs up to tick 24 only, then how her run ended
        assert (bia.result()["verdict"], bia.result()["why"]) == ("loss", "conexao")
        assert [k for k, _ in ops(bia)] == [12, 24] and bia.of("op_end")[0]["k"] == T
    elif how in ("pacing", "bad"):
        assert (bia.result()["verdict"], bia.result()["why"]) == ("loss", why)
        assert bia.code == (1008 if how == "bad" else None)


def test_only_the_challenged_friend_plays(s, clock):
    with contextlib.ExitStack() as stack:
        ana, bia, caio = friends(s, stack, "ana", "bia", "caio")
        mid = first(s, clock, ana, bia, None)
        bia.send({"t": "challenge_play", "id": mid + 1})  # no such challenge
        assert bia.got[-1] == hub.error("gone") and bia.code is None
        for p in (caio, ana):  # a third friend; the challenger herself
            p.send({"t": "challenge_play", "id": mid})
            assert (p.got[-1]["code"], p.code) == ("bad", 1008)
        assert the_match(s, mid)["state"] == "open"
        bia.send({"t": "challenge_play", "id": mid})
        assert bia.of("match")[0]["op"]["nick"] == "ana"


def test_only_friends_are_challenged(s):
    with contextlib.ExitStack() as stack:
        ana, caio = Player(s, "ana").connect(stack), Player(s, "caio").connect(stack)
        duda = Player(s, "duda")
        x, y = sorted((ana.uid, duda.uid))
        s.db.execute("INSERT INTO friends(a, b, asked_by) VALUES (?, ?, ?)", (x, y, ana.uid))  # not accepted
        for to in (caio, duda, ana):  # not a friend; asked only; herself
            assert challenge(ana, to) == hub.error("friend") and ana.code is None
        assert s.count("matches") == s.count("runs") == 0
        ana.send({"t": "challenge", "to": 2**63, "mode": "normal"})  # an id SQLite cannot hold
        assert (ana.got[-1]["code"], ana.code) == ("bad", 1008)


def test_ten_open_challenges_at_most(s, clock):
    with contextlib.ExitStack() as stack:
        ana, bia = friends(s, stack, "ana", "bia")
        mids = [first(s, clock, ana, bia, None) for _ in range(hub.CHALLENGES)]
        assert [m["id"] for m in bia.of("challenge_new")] == mids
        assert challenge(ana, bia) == {"t": "error", "code": "rate", "msg": hub.REFUSED["challenges"]}
        assert ana.code is None and s.count("matches") == hub.CHALLENGES
        bia.send({"t": "challenge_play", "id": mids[0]})
        bia.send({"t": "leave", "m": bia.of("match")[0]["m"]})  # played (and lost): one less open
        assert challenge(ana, bia)["t"] == "match"


def test_drain(s, clock, tmp_path):
    with contextlib.ExitStack() as stack:
        ana, bia = friends(s, stack, "ana", "bia")
        mid = first(s, clock, ana, bia, None)
        (tmp_path / "drain").touch()
        assert challenge(ana, bia) == hub.error("drain")
        bia.send({"t": "challenge_play", "id": mid})
        assert bia.got[-1] == hub.error("drain") and bia.code is None
        assert the_match(s, mid)["state"] == "open"  # the attempt is not used up
        (tmp_path / "drain").unlink()
        bia.send({"t": "challenge_play", "id": mid})
        assert bia.of("match")[0]["kind"] == "challenge"


def test_expiry(s, clock):
    """7 days: marked when read (a challenge_play, a welcome, /partidas)."""
    with contextlib.ExitStack() as stack:
        ana, bia = friends(s, stack, "ana", "bia")
        mid = first(s, clock, ana, bia, None)
        s.db.execute("UPDATE matches SET expires = ? WHERE id = ?", (time.time() - 1, mid))
        bia.send({"t": "challenge_play", "id": mid})
        assert bia.got[-1] == hub.error("gone") and the_match(s, mid)["state"] == "expired"
        assert "Expirou" in bia.client.get("/partidas").text


@pytest.mark.parametrize("how", ["prazo", "admin, open", "admin, playing", "deleted"])
def test_the_challengers_run_rejected_voids_it(s, clock, monkeypatch, how):
    """Before go (no seed seen), or by the admin (any ok run of a match: trigger runs_void), or her account
    deleted: the challenge is void."""
    monkeypatch.setenv("JOGO_DB", s.app.state.cfg.db)
    with contextlib.ExitStack() as stack:
        ana, bia = friends(s, stack, "ana", "bia")
        if how == "prazo":
            ana.m = challenge(ana, bia)["m"]
            ana.send({"t": "leave", "m": ana.m})  # before ready
            mid = row(s, ana.m)["match_id"]
            assert (ana.result()["why"], bia.of("challenge_new")) == ("prazo", [])
        else:
            mid = first(s, clock, ana, bia)
            if how == "deleted":
                assert ana.client.post("/conta/excluir", data={"confirmar": "ana"}).status_code == 200
            elif how == "admin, open":
                assert admin.main(["rejeitar", str(ana.m)]) == 0
            else:
                t0 = play(s, clock, bia, mid)
                race(s, clock, t0, (bia, cut(WIN, 120), None))
                assert admin.main(["rejeitar", str(ana.m)]) == 0  # while bia races it
                race(s, clock, t0, (bia, LONG, None))
                assert (bia.result()["verdict"], bia.result()["op"], bia.result()["state"]) == (
                    None,
                    None,
                    "ok",
                )
        idle(s)
        assert dones(ana) == []
        if how != "admin, playing":
            bia.send({"t": "challenge_play", "id": mid})
            assert bia.got[-1] == hub.error("gone")
    mt = the_match(s, mid)
    assert mt is None if how == "deleted" else (mt["state"], mt["winner"]) == ("void", None)
    if how == "prazo":  # never offered to bia: not on her page
        assert "Desafio ·" not in bia.client.get("/partidas").text


@pytest.mark.parametrize("how", ["close", "bad"])
def test_the_challenger_cannot_throw_a_bad_run_away(s, clock, how):
    """After go her run rejected by the hub (her client knows of a crash before the server: she closes the
    tab before the message holding it, or sends a bad frame) is a forfeit: bia wins without playing, and a
    fresh challenge is a new loss to risk, not a free retry."""
    with contextlib.ExitStack() as stack:
        ana, bia = friends(s, stack, "ana", "bia")
        ana.m = challenge(ana, bia)["m"]
        ana.send({"t": "ready", "m": ana.m})
        race(s, clock, clock.t + hub.COUNTDOWN_S, (ana, cut(CRASH, T - T % 12), None))  # all but the crash's
        assert ana.result() is None
        if how == "close":
            ana.ws.close()
            idle(s, lambda: ana.uid not in s.hub.socks)
        else:
            ana.send({"t": "in", "m": ana.m, "k": T - T % 12 + 12, "ev": [[T, True]]})
        mid = row(s, ana.m)["match_id"]
        assert (row(s, ana.m)["state"], row(s, ana.m)["why"]) == (
            "rejected",
            "conexao" if how == "close" else "invalido",
        )
        assert (the_match(s, mid)["state"], the_match(s, mid)["winner"]) == ("done", bia.uid)
        assert bia.of("challenge_new") == []
    text = bia.client.get("/partidas").text
    assert "Vitória" in text and "1 vitória · 0 derrotas" in text


def test_admin_rejecting_the_friends_run_voids_it(s, clock, monkeypatch):
    monkeypatch.setenv("JOGO_DB", s.app.state.cfg.db)
    with contextlib.ExitStack() as stack:
        ana, bia = friends(s, stack, "ana", "bia")
        mid = first(s, clock, ana, bia)
        race(s, clock, play(s, clock, bia, mid), (bia, LONG, None))
        assert bia.result()["verdict"] == "win"
    assert admin.main(["rejeitar", str(bia.m)]) == 0
    assert (the_match(s, mid)["state"], the_match(s, mid)["winner"]) == ("void", None)
    assert "1 vitória" not in bia.client.get("/partidas").text


def test_a_ban_or_an_unfriending_voids_the_open_ones(s, clock, monkeypatch):
    monkeypatch.setenv("JOGO_DB", s.app.state.cfg.db)
    with contextlib.ExitStack() as stack:
        ana, bia, caio = friends(s, stack, "ana", "bia", "caio")
        banned, unfriended = first(s, clock, ana, bia, None), first(s, clock, caio, bia, None)
        kept = first(s, clock, caio, ana, None)
        assert admin.main(["banir", "ana"]) == 0
        assert bia.client.post(f"/amigos/{caio.uid}/remover").status_code == 303
        for mid in (banned, unfriended):
            bia.send({"t": "challenge_play", "id": mid})
            assert bia.got[-1] == hub.error("gone") and the_match(s, mid)["state"] == "void"
        assert the_match(s, kept)["state"] == "open"


def test_a_friends_turn_holds_two_places(make, clock):
    """The recording is in memory too, as much as a run: MAX_ATIVAS counts it."""
    s = make(max_ativas=3)
    with contextlib.ExitStack() as stack:
        ana, bia, caio = friends(s, stack, "ana", "bia", "caio")
        mid = first(s, clock, ana, bia, None)
        caio.send({"t": "solo", "mode": "normal"})  # 1 of 3
        ana.send({"t": "solo", "mode": "normal"})  # 2 of 3
        bia.send({"t": "challenge_play", "id": mid})
        assert bia.got[-1] == hub.error("full") and the_match(s, mid)["state"] == "open"
        ana.send({"t": "leave", "m": ana.of("match")[-1]["m"]})
        bia.send({"t": "challenge_play", "id": mid})
        assert bia.of("match")[-1]["kind"] == "challenge"
        ana.send({"t": "solo", "mode": "normal"})  # 4 of 3
        assert ana.got[-1] == hub.error("full")


def test_giving_up_just_past_the_recordings_end_wins(s, clock):
    """ana crashed on tick T; bia's give-up a few ticks later (before her next report) outlasted her."""
    with contextlib.ExitStack() as stack:
        ana, bia = friends(s, stack, "ana", "bia")
        mid = first(s, clock, ana, bia)
        mine = cut(WIN, T + 3)
        race(s, clock, play(s, clock, bia, mid), (bia, mine, fin(mine)))
        heard(ana, lambda m: m["t"] == "challenge_done")
    assert (bia.result()["verdict"], bia.result()["outcome"]) == ("win", "giveup")
    assert (the_match(s, mid)["winner"], dones(ana)[0]["verdict"]) == (bia.uid, "loss")


def test_a_restart_voids_a_turn_in_progress(s, clock):
    with contextlib.ExitStack() as stack:
        ana, bia = friends(s, stack, "ana", "bia")
        mid = first(s, clock, ana, bia, None)
        play(s, clock, bia, mid)
        ana.send({"t": "challenge", "to": bia.uid, "mode": "normal"})  # her own run, not played yet
        hub.Hub(s.app.state, clock)
        assert the_match(s, mid)["state"] == "void" and row(s, bia.m)["why"] == "reinicio"
        assert the_match(s, mid + 1)["state"] == "void"


# --- /partidas ----------------------------------------------------------------------------------------------


def test_partidas(s):
    ana, bia, caio, duda, zeca = (s.player(n) for n in ("ana", "bia", "caio", "duda", "zeca"))
    me, b, c, d, z = ana[1], bia[1], caio[1], duda[1], zeca[1]
    now = time.time()

    def match(kind, a, b_, state, winner=None, scores=(None, None), expires=None) -> None:
        sql = "INSERT INTO matches(kind, mode, seed, a, b, state, winner, created, expires)"
        sql += " VALUES (?, 'normal', 123456789, ?, ?, ?, ?, ?, ?) RETURNING id"
        mid = s.db.execute(sql, (kind, a, b_, state, winner, now, expires)).fetchone()[0]
        for uid, score in zip((a, b_), scores, strict=True):
            sql = "INSERT INTO runs(user_id, kind, match_id, mode, skin, seed, shared, build, started, state,"
            sql += " score) VALUES (?, ?, ?, 'normal', 'yellow', 123456789, 1, 'x', 0, 'ok', ?)"
            s.db.execute(sql, (uid, kind, mid, score))

    match("live", me, b, "done", me, (1234, 567))
    match("challenge", b, me, "done", b)
    match("live", b, me, "done")  # a draw
    match("challenge", me, b, "void")
    match("challenge", me, c, "open", expires=now + 3600)  # waiting for caio
    match("challenge", c, me, "open", scores=(4321, None), expires=now + 3600)  # my turn
    match("challenge", c, me, "open", expires=now - 1)  # expired, not marked yet
    match("live", d, me, "done")  # only draws with duda
    match("live", b, z, "done", b)  # not mine
    match("challenge", c, me, "racing")  # caio is playing his run: not offered to me yet
    s.db.execute(
        "INSERT INTO runs(user_id, kind, mode, skin, seed, shared, build, started, state, why, score,"
        " seconds, ended) VALUES (?, 'solo', 'dificil', 'yellow', 1, 0, 'x', 0, 'review', 'top10', 98765,"
        " 125.4, ?)",
        (me, now),
    )

    page = ana[0].get("/partidas")
    assert page.status_code == 200 and '<a href="/partidas">' in page.text
    text = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", page.text))
    assert (
        "bia 1 vitória · 1 derrota · 1 empate" in text and "caio 0 vitórias" not in text
    )  # decided ones only
    assert "duda 0 vitórias · 0 derrotas · 1 empate" in text
    assert "Vitória" in text and "1.234 × 567" in text and "Empate" in text and "Anulada" in text
    assert "Esperando caio" in text and "Sua vez" in text and "Expirou" in text and "zeca" not in text
    assert "Em andamento" not in text
    assert "Em análise" in text and "Difícil" in text and "98.765" in text and "2:05" in text
    assert "123456789" not in page.text  # never the seed
    assert re.search(r"Desafio · Normal · \d\d/\d\d/\d{4} \d\d:\d\d", text)

    assert s.client().get("/partidas").headers["location"] == "/entrar"
    nameless = s.client()
    s.login(nameless, s.user("x@x.test"))
    assert nameless.get("/partidas").headers["location"] == "/apelido"
