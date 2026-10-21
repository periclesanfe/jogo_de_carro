"""The match hub (plan §5, §6): the one WebSocket, /ws, and ranked solo runs verified live.

JSON text frames. Any frame that is not exactly one of these, or comes out of place, voids the run in
progress (invalido) and closes the socket with 1008:

    C→S {"t":"hello","build":"<tree>","py":"3.12.12","pg":"2.5.7","skin":"yellow"}      first, and once
    S→C {"t":"welcome","me":{"id":7,"nick":"pericles"}}
      | {"t":"error","code":"login|version|busy|bad","msg":"<pt-BR>"}, then the socket closes
    C→S {"t":"solo","mode":"normal"}
    S→C {"t":"match","m":901,"kind":"solo","mode":"normal","op":null}     no seed yet
      | {"t":"error","code":"full|drain|rate","msg":"<pt-BR>"}                       the socket stays open
    C→S {"t":"ready","m":901}                       within 10 s, or the attempt is used up (prazo)
    S→C {"t":"go","m":901,"seed":6004799503160661}  the seed, at last; tick 0 is 2.25 s later
    C→S {"t":"in","m":901,"k":1452,"ev":[[1440,"R"],[1446,1]]}      inputs for ticks [previous k, k)
    C→S {"t":"in","m":901,"k":7321,"ev":[...],"fin":{"outcome":"crash|win|giveup","score":2210}}
    C→S {"t":"leave","m":901}                   gives up at the last k sent (before go: the attempt is used)
    S→C {"t":"result","m":901,"run":901,"state":"ok|review|rejected","why":null|"top10|bot|desync|adiantado|
         ritmo|invalido|conexao|prazo|substituida","outcome":"crash|win|giveup"|null,"score":2210|null,"secs":12.1|null,
         "rank":37|null,"verdict":null,"op":null}

m is the run's id. Messages for a run that is already over (inputs in flight when the result went out) are
ignored; any other m is a violation. k is a multiple of 12 but with fin. Only the server's simulation scores:
fin is only compared (desync).
"""

import asyncio
import contextlib
import itertools
import json
import logging
import secrets
import sqlite3
import time
import zlib
from array import array
from collections import deque
from dataclasses import dataclass, field
from functools import cache
from typing import Any

from starlette.websockets import WebSocket

from jogo_de_carro.assets import Assets
from jogo_de_carro.run import BadInput, Run
from jogo_de_carro.settings import FIXED_DT, MODE_BY_KEY, SKINS

from . import auth, flags

RUNTIME = ("3.12.12", "2.5.7")  # the browser's Python and pygame-ce: the server simulates on the same
READY_S = 10.0  # to answer match with ready
COUNTDOWN_S = 2.25  # go to tick 0: the game's 3-2-1
EARLY_S, LATE_S = -0.25, 2.0  # pacing: ahead of real time is impossible honestly; behind is a pause
SILENCE_S = 5.0  # no input for this long: the connection is gone
TICK_S, STALL_S, SWEEP_LAG_S = 0.1, 0.05, 0.5
CREDIT_S = 3.0  # a server stall excuses lateness this long after it: its backlog drains in moments
REPORT = 12  # ticks per input message, as RaceScene sends them (fin: wherever the run ended)
MAX_FRAME = 16 * 1024
RATE, BURST = 30, 60  # messages a second; a stall's backlog gets RATE more per second of the stall
STARTS = 60  # ranked starts an hour
REFUSED = {
    "login": "Entre no site para jogar online.",
    "nick": "Escolha seu apelido no site para jogar online.",
    "ended": "Sua sessão foi encerrada. Entre de novo no site.",
    "busy": "Aberto em outra aba",
    "version": "Nova versão do jogo: recarregue a página.",
    "bad": "Mensagem inválida.",
    "full": "Servidor cheio, tente em instantes",  # these four are the game's waiting screen's heading
    "drain": "Servidor atualizando, tente em 1 min",
    "rate": "Corridas demais, tente mais tarde",
}
# each message's fields: a JSON type (exactly: true is no int), or the strings allowed
SHAPES: dict[str, dict[str, Any]] = {
    "hello": {"build": str, "py": str, "pg": str, "skin": SKINS},
    "solo": {"mode": tuple(MODE_BY_KEY)},
    "ready": {"m": int},
    "in": {"m": int, "k": int, "ev": list},
    "leave": {"m": int},
}
FIN = {"outcome": ("crash", "win", "giveup"), "score": int}
log = logging.getLogger("jogo")


@cache
def assets() -> Assets:
    return Assets()


def new_seed() -> int:
    return secrets.randbits(53)  # exact in a JS number, should a client ever parse it as one


def fits(v: Any, want: Any) -> bool:
    """v is exactly what want describes: a type, a tuple of allowed strings, or a dict of all its fields."""
    if isinstance(want, dict):
        return type(v) is dict and v.keys() == want.keys() and all(fits(v[k], w) for k, w in want.items())
    if isinstance(want, tuple):
        return type(v) is str and v in want
    return type(v) is want


def parse(text: str) -> dict | None:
    try:
        d = json.loads(text)
    except (ValueError, RecursionError):
        return None
    t = d.get("t") if type(d) is dict else None
    shape = SHAPES.get(t) if type(t) is str else None
    if shape and t == "in" and "fin" in d:
        shape = {**shape, "fin": FIN}
    if not (shape and fits(d, {"t": str, **shape})):
        return None
    return d if 0 <= d.get("fin", {}).get("score", 0) < 2**53 else None  # it is stored: SQLite holds 64 bits


async def refuse(ws: WebSocket, code: str | None) -> None:
    """Says why, if anything ("nick" and "ended" are logins too, to the game), and closes with 1008."""
    if code:
        msg = {"t": "error", "code": "login" if code in ("nick", "ended") else code, "msg": REFUSED[code]}
        with contextlib.suppress(Exception):
            await asyncio.wait_for(ws.send_text(json.dumps(msg)), 1)
    with contextlib.suppress(Exception):
        await asyncio.wait_for(ws.close(1008), 1)


# --- the board ------------------------------------------------------------------------------------------


def board(db: sqlite3.Connection, mode: str) -> list[sqlite3.Row]:
    """Every player's best ranked run in a mode (the table bests), best first (the earlier wins a tie); no
    banned players."""
    return db.execute(
        "SELECT user_id, nick, score, seconds FROM bests JOIN users ON users.id = user_id"
        " WHERE mode = ? AND role != 'banned' ORDER BY score DESC, run_id",
        (mode,),
    ).fetchall()


BEST = "SELECT max(score) FROM bests WHERE mode = ? AND user_id = ?"
HELD = "SELECT max(score) FROM runs WHERE state = 'review' AND mode = ? AND user_id = ?"
SUPERSEDE = "UPDATE runs SET state = 'rejected', why = 'substituida' WHERE state = 'review' AND mode = ?"
SUPERSEDE += " AND user_id = ?"


def place(db: sqlite3.Connection, uid: int, mode: str, score: int) -> int:
    """Where a best of `score` stands on the board, fresh: 1 + the other players with a best as good or
    better (a tie goes to the earlier run, so to them)."""
    sql = (
        "SELECT count(*) FROM bests JOIN users ON users.id = user_id"
        " WHERE mode = ? AND score >= ? AND user_id != ? AND role != 'banned'"
    )
    return db.execute(sql, (mode, score, uid)).fetchone()[0] + 1


# --- sockets and runs -----------------------------------------------------------------------------------


@dataclass(eq=False)
class Sock:
    ws: WebSocket
    uid: int
    nick: str
    token: str  # the session cookie, checked again at each start: a ban or "sair de todos" ends play
    at: float  # the rate limit's clock
    tokens: float = BURST
    skin: str | None = None  # from hello
    m: int | None = None  # the socket's current run
    live: "Live | None" = None
    closed: bool = False


@dataclass(eq=False)
class Live:
    id: int
    sock: Sock
    mode: str
    seed: int
    deadline: float  # for ready
    run: Run | None = None  # from go
    t0: float = 0.0  # loop time of tick 0
    stall0: float = 0.0
    heard: float = 0.0
    max_lag: float = 0.0
    fin: dict | None = None
    arr: array = field(default_factory=lambda: array("i"))  # k, ms after t0, per input message (flat)
    watch: flags.Watch = field(default_factory=flags.Watch)


class Hub:
    def __init__(self, state: Any, clock: Any = None) -> None:
        self.state, self.db, self.cfg = state, state.db, state.cfg
        self.clock = clock or asyncio.get_running_loop().time  # monotonic; tests inject their own
        self.socks: dict[int, Sock] = {}  # user id -> their one socket
        self.live: dict[int, Live] = {}  # run id -> run in progress
        self.tasks: set[asyncio.Task] = set()
        self.stall = self.loop_lag = 0.0
        self.ticked, self.ticks = self.clock(), 0
        self.marks = deque([(self.ticked, 0.0)])  # (tick, self.stall): the last CREDIT_S s, and one older
        sql = "UPDATE runs SET state = 'rejected', why = 'reinicio', ended = ? WHERE state = 'live'"
        self.db.execute(sql, (time.time(),))  # a restart dropped them

    # --- the clock: a server stall is never the player's lag ------------------------------------------

    def stalled(self, now: float) -> float:
        """Seconds the event loop has been stuck since startup, a stall still going on included: the ticker
        should run every 0.1 s, so whatever it oversleeps by more than 50 ms is the server's."""
        over = now - self.ticked - TICK_S
        return self.stall + (over if over > STALL_S else 0.0)

    def credit(self, now: float, since: float = 0.0) -> float:
        """The stall of the last CREDIT_S seconds (and after `since`, a stalled() value): what the backlog it
        piled up is late by. Then it lapses: an honest client is on time again within moments."""
        base = next((stall for t, stall in reversed(self.marks) if t <= now - CREDIT_S), self.marks[0][1])
        return self.stalled(now) - max(since, base)

    def tick(self) -> None:
        now = self.clock()
        over = now - self.ticked - TICK_S
        self.loop_lag = max(0.0, over)
        if over > STALL_S:
            self.stall += over
        self.ticked, self.ticks = now, self.ticks + 1
        self.marks.append((now, self.stall))
        while self.marks[1][0] <= now - CREDIT_S:
            self.marks.popleft()
        if self.ticks % 5 == 0 and over <= SWEEP_LAG_S:  # right after a stall the backlog goes first
            self.spawn(self.sweep(now))  # its sends may wait: the ticker itself must only ever sleep

    async def ticker(self) -> None:
        while True:
            await asyncio.sleep(TICK_S)
            self.tick()

    def spawn(self, coro: Any) -> None:
        task = asyncio.get_running_loop().create_task(coro)
        self.tasks.add(task)  # the loop keeps only a weak reference
        task.add_done_callback(self.tasks.discard)

    async def sweep(self, now: float) -> None:
        for live in list(self.live.values()):
            if self.live.get(live.id) is not live:  # ended while this sweep awaited a send
                continue
            if live.run is None and now > live.deadline:
                await self.finish(live, "prazo")
            elif live.run is not None and now - live.heard > SILENCE_S:
                await self.finish(live, "conexao")

    # --- the socket ---------------------------------------------------------------------------------------

    async def serve(self, ws: WebSocket, token: str | None) -> None:
        """After the Origin check (app.ws). The page can be opened logged out: the error tells the game to
        play offline."""
        user = auth.session_user(self.db, token)[0]
        await ws.accept()
        if user is None or not user["nick"]:
            return await refuse(ws, "login" if user is None else "nick")
        old = self.socks.get(user["id"])
        sock = self.socks[user["id"]] = Sock(ws, user["id"], user["nick"], token or "", self.clock())
        if old:
            await self.close(old, "busy")
        try:
            while not sock.closed:
                msg = await ws.receive()
                if msg["type"] == "websocket.disconnect":
                    break
                await self.handle(sock, msg.get("text"))
        finally:
            self.forget(sock)

    def forget(self, sock: Sock) -> None:
        sock.closed = True
        if self.socks.get(sock.uid) is sock:
            del self.socks[sock.uid]
        if sock.live:
            self.end(sock.live, "conexao")

    async def close(self, sock: Sock, code: str | None = None) -> None:
        if not sock.closed:
            self.forget(sock)
            await refuse(sock.ws, code)

    def kick(self, uid: int) -> None:
        """Closes the user's socket: their sessions just ended (app.end_sessions)."""
        if sock := self.socks.get(uid):
            self.spawn(self.close(sock, "ended"))

    async def send(self, sock: Sock, msg: dict) -> None:
        if sock.closed:
            return
        try:
            await asyncio.wait_for(sock.ws.send_text(json.dumps(msg)), 1)
        except Exception:  # gone, or not reading: it cannot hold the hub up
            await self.close(sock)

    async def violate(self, sock: Sock) -> None:
        if sock.live:
            await self.finish(sock.live, "invalido")
        await self.close(sock, "bad")

    async def handle(self, sock: Sock, text: str | None) -> None:
        now = self.clock()
        sock.tokens = min(BURST + RATE * self.credit(now), sock.tokens + (now - sock.at) * RATE) - 1
        sock.at = now
        ok = sock.tokens >= 0 and text is not None and len(text) <= MAX_FRAME  # None: a binary frame
        d = parse(text) if ok else None
        if d is None or (d["t"] == "hello") != (sock.skin is None) or d.get("m", sock.m) != sock.m:
            return await self.violate(sock)
        await getattr(self, "on_" + d["t"])(sock, d, now)

    # --- messages -----------------------------------------------------------------------------------------

    async def on_hello(self, sock: Sock, d: dict, now: float) -> None:
        if (d["build"], d["py"], d["pg"]) != (self.state.build, *RUNTIME):
            return await self.close(sock, "version")
        sock.skin = d["skin"]
        await self.send(sock, {"t": "welcome", "me": {"id": sock.uid, "nick": sock.nick}})

    async def on_solo(self, sock: Sock, d: dict, now: float) -> None:
        if sock.live:  # one run at a time
            return await self.violate(sock)
        if auth.session_user(self.db, sock.token)[0] is None:  # logged out everywhere, or banned
            return await self.close(sock, "ended")
        if self.cfg.drain.exists():
            code = "drain"
        elif len(self.live) >= self.cfg.max_ativas:
            code = "full"
        elif not self.state.limits.allow((f"solo:{sock.uid}", STARTS, 3600)):
            code = "rate"
        else:
            seed, mode = new_seed(), d["mode"]
            rid = self.db.execute(
                "INSERT INTO runs(user_id, kind, mode, skin, seed, shared, build, started, state)"
                " VALUES (?, 'solo', ?, ?, ?, 0, ?, ?, 'live') RETURNING id",
                (sock.uid, mode, sock.skin, seed, self.state.build, time.time()),
            ).fetchone()[0]
            sock.m, sock.live = rid, Live(rid, sock, mode, seed, now + READY_S)
            self.live[rid] = sock.live
            return await self.send(sock, {"t": "match", "m": rid, "kind": "solo", "mode": mode, "op": None})
        await self.send(sock, {"t": "error", "code": code, "msg": REFUSED[code]})

    async def on_ready(self, sock: Sock, d: dict, now: float) -> None:
        live = sock.live
        if live is None:  # too late: already rejected (prazo)
            return
        if live.run is not None:
            return await self.violate(sock)
        live.run = Run(assets(), live.mode, sock.skin, live.seed, False)
        live.t0, live.stall0, live.heard = now + COUNTDOWN_S, self.stalled(now), now
        await self.send(sock, {"t": "go", "m": live.id, "seed": live.seed})

    async def on_in(self, sock: Sock, d: dict, now: float) -> None:
        live = sock.live
        if live is None:  # over: inputs that were in flight
            return
        run, k = live.run, d["k"]
        if run is None or (k % REPORT and "fin" not in d):  # inputs before go, or off the 12-tick grid
            return await self.violate(sock)
        try:
            run.feed(k, d["ev"])
        except BadInput:
            return await self.violate(sock)
        since = now - live.t0
        live.arr.extend((k, round(since * 1000)))
        lag = since - k * FIXED_DT
        late = lag - self.credit(now, live.stall0)  # minus a server stall whose backlog this may be
        live.heard, live.max_lag = now, max(live.max_lag, late)
        if lag < EARLY_S:  # a stall only ever makes a message later, so this one needs no compensation
            return await self.finish(live, "adiantado")
        if late > LATE_S:
            return await self.finish(live, "ritmo")
        live.watch.advance(run, k)
        if run.outcome or "fin" in d:
            live.fin = d.get("fin")
            await self.finish(live)

    async def on_leave(self, sock: Sock, d: dict, now: float) -> None:
        if sock.live:
            await self.finish(sock.live, None if sock.live.run else "prazo")

    # --- the end of a run -----------------------------------------------------------------------------

    async def finish(self, live: Live, why: str | None = None) -> None:
        await self.send(live.sock, self.end(live, why))

    def end(self, live: Live, why: str | None = None) -> dict:
        """Stores the run as the server simulated it and returns its result. why: a rejection."""
        del self.live[live.id]
        live.sock.live = None
        run, uid, fin = live.run, live.sock.uid, live.fin
        row: dict[str, Any] = {"ended": time.time(), "state": "rejected" if why else "ok"}
        out = {"outcome": None, "score": None, "secs": None, "rank": None}
        if run is not None:
            run.stop("giveup")  # not over by its last input: given up (or cut off) there
            arr = list(itertools.batched(live.arr, 2))  # [k, ms] pairs
            score, f = run.score.total, live.watch.features(arr)
            if not why:
                best = self.db.execute(BEST, (live.mode, uid)).fetchone()[0]
                held = self.db.execute(HELD, (live.mode, uid)).fetchone()[0]  # the player's run in review
                at = place(self.db, uid, live.mode, score) if best is None or score > best else None
                if at and held is not None and score <= held:
                    row["state"], why = "rejected", "substituida"  # one run in review per player and mode
                elif at and at <= 10 and score:
                    row["state"], why = "review", "top10"
                elif at and at <= 100 and flags.flagged(f):
                    row["state"], why = "review", "bot"
                elif fin and (fin["outcome"], fin["score"]) != (run.outcome, score):
                    why = "desync"  # the server's numbers stand; the log is kept to find out why
                if at and held is not None and row["state"] != "rejected":  # better: it replaces that one
                    self.db.execute(SUPERSEDE, (live.mode, uid))
            log_json = json.dumps({"v": 1, "ev": run.ev, "arr": arr}, separators=(",", ":"))
            row |= {
                "ticks": run.tick,
                "outcome": run.outcome,
                "score": score,
                "seconds": run.seconds,
                "client_score": fin and fin["score"],
                "max_lag": round(live.max_lag, 3),
                "features": json.dumps(f),
                "log": zlib.compress(log_json.encode()),
            }
            out = {"outcome": run.outcome, "score": score, "secs": round(run.seconds, 1), "rank": None}
            if row["state"] == "ok":
                out["rank"] = at or place(self.db, uid, live.mode, best)
        row["why"] = why
        sets = ", ".join(f"{column} = ?" for column in row)  # the columns are the literals above
        self.db.execute(f"UPDATE runs SET {sets} WHERE id = ?", (*row.values(), live.id))
        state = row["state"]
        log.info("corrida %d %s %s %s max_lag %.2f", live.id, live.mode, state, why, live.max_lag)
        out |= {"verdict": None, "op": None}  # versus only (M4)
        return {"t": "result", "m": live.id, "run": live.id, "state": state, "why": why, **out}
