"""The match hub (plan §5, §6): the one WebSocket, /ws, ranked solo runs, live races and challenges between
friends, every run verified live.

JSON text frames. Any frame that is not exactly one of these, or comes out of place, voids the run in
progress (invalido) and closes the socket with 1008:

    C→S {"t":"hello","build":"<tree>","py":"3.12.12","pg":"2.5.7","skin":"yellow"}      first, and once
    S→C {"t":"welcome","me":{"id":7,"nick":"pericles"},"requests":2,     requests: friend requests to answer
         "friends":[{"id":42,"nick":"ana_42","s":"off|menu|racing"}],
         "challenges":[{"id":77,"from":"ana_42","mode":"normal","secs":83.2,"score":5321}],    open, to me
         "coins":320}     my wallet: the coins of my paid runs (PAID)
      | {"t":"error","code":"login|version|busy|bad|rate","msg":"<pt-BR>"}, then the socket closes (rate: 20
         sockets a minute, each one's presence goes to every friend)
    S→C {"t":"presence","id":42,"s":"off|menu|racing"}      a friend's new status (menu: said hello, no run;
         racing: a run in progress, an old tab's race not decided yet included)
    C→S {"t":"solo","mode":"normal"}
    S→C {"t":"match","m":901,"kind":"solo","mode":"normal","op":null}     no seed yet
      | {"t":"error","code":"full|drain|rate|racing","msg":"<pt-BR>"}    the socket stays open (racing: an old
         tab's race is not decided yet)
    C→S {"t":"invite","to":42,"mode":"normal"}      to a friend in the menu; at most 10 every 10 min
    S→C {"t":"waiting","id":"i_9f2c…"}               always, then invited goes to them, or invite_gone to me
      | {"t":"error","code":"drain|rate|racing","msg":"<pt-BR>"}
         an invite to the one whose invite to me is open (same mode) crosses it: a yes to theirs (waiting with
         its id, then as invite_reply ok)
    S→C {"t":"invited","id":"i_9f2c…","from":{"id":7,"nick":"pericles"},"mode":"normal","ttl":30}
    C→S {"t":"invite_reply","id":"i_9f2c…","ok":true}       the one invited only
    C→S {"t":"invite_cancel","id":"i_9f2c…"}                the one who invited only
    S→C {"t":"invite_gone","id":"i_9f2c…","why":"declined|expired|cancelled|offline|busy"}
    S→C {"t":"match","m":903,"kind":"live","mode":"normal","op":{"nick":"ana_42","skin":"red"}}  to both, on
         ok | {"t":"error","code":"full|drain",...} to both
    C→S {"t":"challenge","to":42,"mode":"normal"}   to a friend, online or not; at most 10 open
    S→C {"t":"match","m":904,"kind":"challenge","mode":"normal","op":null}     then as solo, on a shared road
      | {"t":"error","code":"drain|full|racing|rate|friend","msg":"<pt-BR>"}   (rate: starts, or 10 open)
    S→C {"t":"challenge_new","id":77,"from":"ana_42","mode":"normal","secs":83.2,"score":5321}   to the
         friend, once the challenger's run is ok: it is open for 7 days
    C→S {"t":"challenge_play","id":77}               the friend only (anyone else's: a violation), once
    S→C {"t":"match","m":905,"kind":"challenge","mode":"normal","op":{"nick":"ana_42","skin":"red"}}  no seed
      | {"t":"error","code":"drain|full|racing|gone","msg":"<pt-BR>"}    gone: played, expired, void or none
         then as a live race: the stored run's inputs come as op (the messages it was sent in), gated by my
         own k, then its op_end; it is decided against the stored run; any forfeit (prazo included) loses
    S→C {"t":"challenge_done","id":77,"verdict":"win|loss|draw","op":{"nick":"bia","score":4100,"secs":61.0}}
         to the challenger, if in the game (verdict: theirs; score and secs null: the friend never started)
    C→S {"t":"ready","m":901}                       within 10 s, or the attempt is used up (prazo)
    S→C {"t":"go","m":901,"seed":6004799503160661}  the seed, at last; tick 0 is 2.25 s later (a race: to both
         at once, one seed)
    C→S {"t":"in","m":901,"k":1452,"ev":[[1440,"R"],[1446,1]]}      inputs for ticks [previous k, k)
    C→S {"t":"in","m":901,"k":7321,"ev":[...],"fin":{"outcome":"crash|win|giveup","score":2210}}
    S→C {"t":"op","m":903,"k":1452,"ev":[...]}      a race: the rival's accepted inputs, message by message,
         each once my own last k + 24 >= its k
    S→C {"t":"op_end","m":903,"k":7321,"why":"crash|win|giveup|conexao|ritmo|adiantado|invalido"}   likewise,
         or right before the result once the race is over; k: the rival's ticks simulated
    C→S {"t":"leave","m":901}                   gives up at the last k sent (before go: the attempt is used)
    S→C {"t":"result","m":901,"run":901,"state":"ok|review|rejected","why":null|"top10|bot|desync|adiantado|
         ritmo|invalido|conexao|prazo|substituida|anulada","outcome":"crash|win|giveup|decided"|null,
         "score":2210|null,"secs":12.1|null,"rank":37|null,"verdict":null|"win|loss|draw",
         "op":null|{"nick":"ana_42","score":5321,"secs":83.2},"coins":37,"wallet":357}   coins: what this run
         paid (0: none), as the server simulated it, never the client's count; wallet: my balance right after

m is the player's own run id (in a live race too). Messages for a run that is already over (inputs in flight
when the result went out) are ignored; any other m is a violation, and so is a reply to (or cancel of) someone
else's invite. k is a multiple of 12 but with fin. Only the server's simulation scores: fin is only compared
(desync).

A live race is decided by run.verdict after every step, or at once by a forfeit (give-up, leave, 5 s of
silence, a lost socket, pacing, a bad frame: that player loses; a give-up past the end of a rival's run that
ended first wins, by run.verdict); then both get their result together. The run
still going then ends with outcome "decided". A pair that misses its ready deadline (or loses a player before
go) is void: the late one's why is prazo (conexao), the other's anulada. Live runs never rank nor wait for
review. A handler never awaits the other player's socket while the race is on: its slowness would be this
player's lateness (pacing).

A challenge is a matches row: racing (the challenger's run), open, playing_b (the friend's one attempt), then
done, expired (7 days, marked when read) or void. The challenger's run rejected before go (prazo: no seed
seen) voids it; after go it is a forfeit, as in a race: the friend wins without playing, so a run going badly
cannot be thrown away and tried again. Void too: a restart, the admin rejecting any ok run of a match (trigger
runs_void; a race's too), a ban (the open ones), an unfriending (the pair's open ones); a deleted challenger
takes it along. The friend's run is decided against the stored one as against a live rival that has ended, so
early; voided meanwhile, the result has no verdict. The friend's turn holds two MAX_ATIVAS places: the
recording is in memory too. Challenge runs never rank nor wait for review either.
"""

import asyncio
import bisect
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
from operator import itemgetter
from types import SimpleNamespace
from typing import Any

from starlette.websockets import WebSocket

from jogo_de_carro.assets import Assets
from jogo_de_carro.run import BadInput, Run, verdict
from jogo_de_carro.settings import FIXED_DT, MODE_BY_KEY, SKINS

from . import auth, db, flags

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
INVITES, INVITES_S = 10, 600.0  # invites per player, every 10 min
INVITE_S = 30.0  # an invite waits this long for its answer
SOCKETS = 20  # sockets per player a minute: each one's presence goes to every friend in the game
AHEAD = 24  # a rival's inputs reach a player up to this many ticks past the player's own last k
CHALLENGES, CHALLENGE_S = 10, 7 * 86400.0  # open challenges per challenger at most; how long one stays open
VERDICTS = {1: "win", 0: "draw", -1: "loss"}
REFUSED = {
    "login": "Entre no site para jogar online.",
    "nick": "Escolha seu apelido no site para jogar online.",
    "ended": "Sua sessão foi encerrada. Entre de novo no site.",
    "busy": "Aberto em outra aba",
    "version": "Nova versão do jogo: recarregue a página.",
    "bad": "Mensagem inválida.",
    "full": "Servidor cheio, tente em instantes",  # these are the game's waiting screen's heading
    "drain": "Servidor atualizando, tente em 1 min",
    "rate": "Corridas demais, tente mais tarde",
    "racing": "Sua corrida anterior ainda não acabou",
    "invites": "Convites demais, tente em alguns minutos",
    "sockets": "Conexões demais, tente em 1 min",
    "friend": "Só dá para desafiar amigos",
    "challenges": "Você já tem 10 desafios em aberto",
    "gone": "Esse desafio não está mais disponível",
}
CODES = {"nick": "login", "ended": "login", "invites": "rate", "sockets": "rate", "challenges": "rate"}
# each message's fields: a JSON type (exactly: true is no int), or the strings allowed
SHAPES: dict[str, dict[str, Any]] = {
    "hello": {"build": str, "py": str, "pg": str, "skin": SKINS},
    "solo": {"mode": tuple(MODE_BY_KEY)},
    "invite": {"to": int, "mode": tuple(MODE_BY_KEY)},
    "invite_reply": {"id": str, "ok": bool},
    "invite_cancel": {"id": str},
    "challenge": {"to": int, "mode": tuple(MODE_BY_KEY)},
    "challenge_play": {"id": int},
    "ready": {"m": int},
    "in": {"m": int, "k": int, "ev": list},
    "leave": {"m": int},
}
FRIEND = "SELECT 1 FROM friends WHERE a = ? AND b = ? AND accepted"  # (a, b) sorted
OPEN = "SELECT count(*) FROM matches WHERE a = ? AND kind = 'challenge'"
OPEN += " AND state IN ('racing', 'open', 'playing_b')"  # a challenger's, not over yet
OFFERS = (  # the challenges open to a player (b), with the challenger's run: offer()'s arguments
    "SELECT matches.id, nick, matches.mode, seconds, score FROM matches"
    " JOIN runs ON match_id = matches.id AND user_id = a JOIN users ON users.id = a"
    " WHERE b = ? AND matches.state = 'open' ORDER BY matches.id"
)
FIN = {"outcome": ("crash", "win", "giveup"), "score": int}
# the runs whose coins count (plan §2.2): never a reward for winning, which pairs of accounts could farm
PAID = "(state IN ('ok', 'review') OR why IN ('substituida', 'conexao'))"
# the wallet, derived: no ledger (an admin rejection takes a run's coins back by itself)
# ponytail: a SUM over the runs_user index; keep it in users only if a profile shows its cost
BALANCE = f"(SELECT coalesce(sum(coins), 0) FROM runs WHERE user_id = :u AND {PAID})"
log = logging.getLogger("jogo")


def expire(db: sqlite3.Connection) -> None:
    """Open challenges past their 7 days are expired: run before any read of them."""
    db.execute("UPDATE matches SET state = 'expired' WHERE state = 'open' AND expires <= ?", (time.time(),))


def wallet(db: sqlite3.Connection, uid: int) -> int:
    """The player's coins (0 for a deleted account)."""
    return db.execute(f"SELECT {BALANCE}", {"u": uid}).fetchone()[0]


def offer(mid: int, nick: str, mode: str, secs: float, score: int) -> dict:
    """A challenge open to the friend, as welcome and challenge_new list it."""
    return {"id": mid, "from": nick, "mode": mode, "secs": round(secs, 1), "score": score}


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
    if any(type(v) is int and not -(2**63) <= v < 2**63 for v in d.values()):  # SQLite holds 64 bits: an id
        return None  # (to, id) is looked up
    return d if 0 <= d.get("fin", {}).get("score", 0) < 2**53 else None  # it is stored


def error(code: str) -> dict:
    """A refusal: why, in pt-BR, under the code the game knows (CODES: "nick" and "ended" are logins too)."""
    return {"t": "error", "code": CODES.get(code, code), "msg": REFUSED[code]}


async def refuse(ws: WebSocket, code: str | None) -> None:
    """Says why, if anything, and closes with 1008."""
    if code:
        with contextlib.suppress(Exception):
            await asyncio.wait_for(ws.send_text(json.dumps(error(code))), 1)
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

# a new run's or match's id, past those the hub holds (?): SQLite gives the highest out again once its row is
# deleted, and an account deleted mid-race leaves its run, and the race's match, to be ended by their ids
NEW_ID = "max(coalesce(max(id), 0), ?) + 1"


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
    invite: "Invite | None" = None  # the one invite it takes part in, either side
    closed: bool = False
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)  # sends go out one at a time, in call order


@dataclass(eq=False)
class Invite:
    id: str
    a: Sock  # who invited
    b: Sock  # who was invited
    mode: str
    expires: float


@dataclass(eq=False)
class Live:
    id: int
    sock: Sock
    mode: str
    seed: int
    deadline: float  # for ready
    match: int | None = None  # a live race or a challenge: the matches row
    kind: str = "solo"  # solo | live | challenge
    op: "Live | None" = field(default=None, repr=False)  # a live race: the rival's run
    rec: Any = None  # a challenge's friend's turn: the stored run raced, as run.verdict reads a Run
    ready: bool = False
    run: Run | None = None  # from go
    t0: float = 0.0  # loop time of tick 0
    stall0: float = 0.0
    heard: float = 0.0
    max_lag: float = 0.0
    fin: dict | None = None
    gone: str | None = None  # a live race: this run is over (op_end's why), the race maybe not yet
    inbox: deque = field(default_factory=deque)  # a live race: the rival's op/op_end, until this k allows
    arr: array = field(default_factory=lambda: array("i"))  # k, ms after t0, per input message (flat)
    watch: flags.Watch = field(default_factory=flags.Watch)


class Hub:
    def __init__(self, state: Any, clock: Any = None) -> None:
        self.state, self.db, self.cfg = state, state.db, state.cfg
        self.clock = clock or asyncio.get_running_loop().time  # monotonic; tests inject their own
        self.socks: dict[int, Sock] = {}  # user id -> their one socket
        self.live: dict[int, Live] = {}  # run id -> run in progress (both runs of a live race)
        self.invites: dict[str, Invite] = {}
        self.said: dict[int, str] = {}  # user id -> the status their friends last heard (none: off)
        self.tasks: set[asyncio.Task] = set()
        self.stall = self.loop_lag = 0.0
        self.ticked, self.ticks = self.clock(), 0
        self.marks = deque([(self.ticked, 0.0)])  # (tick, self.stall): the last CREDIT_S s, and one older
        sql = "UPDATE runs SET state = 'rejected', why = 'reinicio', ended = ? WHERE state = 'live'"
        self.db.execute(sql, (time.time(),))  # a restart dropped them
        self.db.execute("UPDATE matches SET state = 'void' WHERE state IN ('racing', 'playing_b')")

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
            if live.run is None and now > live.deadline and not live.ready:  # (a ready rival is not late)
                await self.finish(live, "prazo")
            elif live.run is not None and not live.gone and now - live.heard > SILENCE_S:
                await self.finish(live, "conexao")
        for inv in list(self.invites.values()):
            if now > inv.expires and self.invites.get(inv.id) is inv:
                other, msg = self.withdraw(inv.a, "expired")
                await asyncio.gather(self.send(inv.a, msg), self.send(other, msg))

    # --- the socket ---------------------------------------------------------------------------------------

    async def serve(self, ws: WebSocket, token: str | None) -> None:
        """After the Origin check (app.ws). The page can be opened logged out: the error tells the game to
        play offline."""
        user = auth.session_user(self.db, token)[0]
        await ws.accept()
        if user is None or not user["nick"]:
            return await refuse(ws, "login" if user is None else "nick")
        if not self.state.limits.allow((f"ws:{user['id']}", SOCKETS, 60)):  # (and the old tab stays)
            return await refuse(ws, "sockets")
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
        if sock.closed:  # closed by the hub, then its loop ends
            return
        sock.closed = True
        if self.socks.get(sock.uid) is sock:
            del self.socks[sock.uid]
        if sock.invite:
            self.spawn(self.send(*self.withdraw(sock, "offline")))
        if sock.live and (sock.live.op or sock.live.rec):
            self.spawn(self.finish(sock.live, "conexao"))  # the rival (the challenger) must hear of it
        elif sock.live:
            self.end(sock.live, "conexao")
        self.announce(sock.uid)  # (a race undecided: still racing, so nothing yet)

    async def close(self, sock: Sock, code: str | None = None) -> None:
        if not sock.closed:
            self.forget(sock)
            await refuse(sock.ws, code)

    def kick(self, uid: int) -> None:
        """Closes the user's socket: their sessions just ended (app.end_sessions). Forgotten now, so the
        friends to tell are read before an account deletion's cascade."""
        if sock := self.socks.get(uid):
            self.forget(sock)
            self.spawn(refuse(sock.ws, "ended"))

    async def send(self, sock: Sock, msg: dict) -> None:
        async with sock.lock:  # a rival's inputs come from several tasks and must arrive in order
            if sock.closed:
                return
            try:
                await asyncio.wait_for(sock.ws.send_text(json.dumps(msg)), 1)
            except Exception:  # gone, or not reading: it cannot hold the hub up
                await self.close(sock)

    async def signed_in(self, sock: Sock) -> bool:
        """Checked at each start: a ban from the admin command reaches no socket."""
        if auth.session_user(self.db, sock.token)[0] is None:  # logged out everywhere, or banned
            await self.close(sock, "ended")
            return False
        return True

    def racing(self, *uids: int) -> bool:
        """One of these players has a run in progress: maybe an old tab's, over but its race undecided."""
        return any(x.sock.uid in uids for x in self.live.values())  # MAX_ATIVAS at most

    def refusal(self, runs: int, *uids: int) -> str | None:
        """Why `runs` more runs (for these players: one each at a time) cannot start now, if they cannot."""
        if self.cfg.drain.exists():
            return "drain"
        if self.racing(*uids):
            return "racing"
        held = len(self.live) + sum(x.rec is not None for x in self.live.values())  # a friend's turn: 2
        return "full" if held + runs > self.cfg.max_ativas else None

    # --- friends ----------------------------------------------------------------------------------------

    def status(self, uid: int) -> str:
        if self.racing(uid):
            return "racing"
        sock = self.socks.get(uid)
        return "off" if sock is None or sock.skin is None else "menu"

    def announce(self, uid: int) -> None:
        """Tells the player's friends in the game what the player is doing now, if that changed (an old tab's
        race undecided, a new tab's hello says nothing). Whom is read now (a deletion's cascade may come
        next); the sends go out as tasks, in order."""
        msg = {"t": "presence", "id": uid, "s": self.status(uid)}
        if msg["s"] == self.said.get(uid, "off"):
            return
        if msg["s"] == "off":
            del self.said[uid]
        else:
            self.said[uid] = msg["s"]
        for friend in self.db.execute(auth.FRIENDS, {"me": uid}).fetchall():
            if friend["accepted"] and (sock := self.socks.get(friend["id"])) and sock.skin:
                self.spawn(self.send(sock, msg))

    def withdraw(self, sock: Sock, why: str) -> tuple[Sock, dict]:
        """Ends the invite sock takes part in: returns whom to tell, and what."""
        inv = sock.invite
        assert inv is not None
        del self.invites[inv.id]
        inv.a.invite = inv.b.invite = None
        return inv.b if sock is inv.a else inv.a, {"t": "invite_gone", "id": inv.id, "why": why}

    async def walk_away(self, sock: Sock) -> None:
        """Starting something else ends the player's invite: cancelled, or declined if it was theirs."""
        if inv := sock.invite:
            await self.send(*self.withdraw(sock, "cancelled" if sock is inv.a else "declined"))

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
        rows = self.db.execute(auth.FRIENDS, {"me": sock.uid}).fetchall()
        friends = [
            {"id": f["id"], "nick": f["nick"], "s": self.status(f["id"])} for f in rows if f["accepted"]
        ]
        requests = sum(not (f["accepted"] or f["mine"]) for f in rows)  # the ones asked of me
        me = {"id": sock.uid, "nick": sock.nick}
        expire(self.db)
        challenges = [offer(*r) for r in self.db.execute(OFFERS, (sock.uid,))]
        welcome = {"t": "welcome", "me": me, "friends": friends, "requests": requests}
        await self.send(sock, {**welcome, "challenges": challenges, "coins": wallet(self.db, sock.uid)})
        self.announce(sock.uid)

    def start(
        self, sock: Sock, mode: str, seed: int, now: float, match: int | None = None, kind: str = "solo"
    ) -> Live:
        """A new run, stored live until its result, waiting for ready."""
        row = (sock.uid, kind, match, mode, sock.skin, seed, kind != "solo", self.state.build, time.time())
        rid = self.db.execute(
            "INSERT INTO runs(id, user_id, kind, match_id, mode, skin, seed, shared, build, started, state)"
            f" SELECT {NEW_ID}, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'live' FROM runs RETURNING id",
            (max(self.live, default=0), *row),
        ).fetchone()[0]
        sock.m, sock.live = rid, Live(rid, sock, mode, seed, now + READY_S, match, kind)
        self.live[rid] = sock.live
        self.announce(sock.uid)
        return sock.live

    def new_match(self, kind: str, mode: str, seed: int, a: int, b: int) -> int:
        held = max((x.match or 0 for x in self.live.values()), default=0)
        sql = "INSERT INTO matches(id, kind, mode, seed, a, b, state, created)"
        sql += f" SELECT {NEW_ID}, ?, ?, ?, ?, ?, 'racing', ? FROM matches RETURNING id"
        return self.db.execute(sql, (held, kind, mode, seed, a, b, time.time())).fetchone()[0]

    async def on_solo(self, sock: Sock, d: dict, now: float) -> None:
        """A ranked run; or (challenge, to a friend) the challenger's run: as solo, but on the shared road and
        never ranked; once it is ok, the friend's turn (on_challenge_play)."""
        if sock.live:  # one run at a time
            return await self.violate(sock)
        if not await self.signed_in(sock):
            return
        await self.walk_away(sock)
        to, code = d.get("to"), self.refusal(1, sock.uid)
        if code is None and to is not None:
            expire(self.db)
            if not self.db.execute(FRIEND, sorted((sock.uid, to))).fetchone():
                code = "friend"  # (themselves too)
            elif self.db.execute(OPEN, (sock.uid,)).fetchone()[0] >= CHALLENGES:
                code = "challenges"
        if code is None and not self.state.limits.allow((f"solo:{sock.uid}", STARTS, 3600)):  # either kind
            code = "rate"
        if code:
            return await self.send(sock, error(code))
        seed, kind = new_seed(), d["t"]  # solo | challenge
        with db.tx(self.db):
            mid = None if to is None else self.new_match(kind, d["mode"], seed, sock.uid, to)
            live = self.start(sock, d["mode"], seed, now, mid, kind)
        await self.send(sock, {"t": "match", "m": live.id, "kind": kind, "mode": live.mode, "op": None})

    on_challenge = on_solo

    async def on_challenge_play(self, sock: Sock, d: dict, now: float) -> None:
        """The friend's one attempt: the stored run comes to them as a live rival's inputs would, message by
        message, never past their own k + AHEAD (flush), so they never hold the whole of it."""
        if sock.live:
            return await self.violate(sock)
        mt = self.db.execute(
            "SELECT b FROM matches WHERE id = ? AND kind = 'challenge'", (d["id"],)
        ).fetchone()
        if mt and mt["b"] != sock.uid:  # someone else's (the challenger's own included)
            return await self.violate(sock)
        if not await self.signed_in(sock):
            return
        await self.walk_away(sock)
        expire(self.db)
        mt, code = None, self.refusal(2, sock.uid)  # the recording, in memory, takes a place too
        if not code:  # the attempt is used up here (only challenges are ever open), whatever happens next
            sql = (
                "UPDATE matches SET state = 'playing_b' WHERE id = ? AND b = ? AND state = 'open' RETURNING *"
            )
            mt = self.db.execute(sql, (d["id"], sock.uid)).fetchone()
        if not mt:
            return await self.send(sock, error(code or "gone"))  # played, expired, void, or no such
        sql = "SELECT runs.*, nick FROM runs JOIN users ON users.id = user_id WHERE match_id = ?"
        a = self.db.execute(sql + " AND user_id = ?", (mt["id"], mt["a"])).fetchone()  # ok: or it is void
        live = self.start(sock, mt["mode"], mt["seed"], now, mt["id"], "challenge")
        score = SimpleNamespace(total=a["score"])
        live.rec = SimpleNamespace(uid=a["user_id"], nick=a["nick"], skin=a["skin"], outcome=a["outcome"],
                                   tick=a["ticks"], score=score, secs=round(a["seconds"], 1))  # fmt: skip
        stored = json.loads(zlib.decompress(a["log"]))
        ev, i = stored["ev"], 0
        for k, _ in stored["arr"]:  # its messages' k: its inputs, as they were sent (as simulated)
            j = bisect.bisect_left(ev, k, i, key=itemgetter(0))
            live.inbox.append({"t": "op", "m": live.id, "k": k, "ev": ev[i:j]})
            i = j
        live.inbox.append({"t": "op_end", "m": live.id, "k": a["ticks"], "why": a["outcome"]})
        op = {"nick": a["nick"], "skin": a["skin"]}
        await self.send(sock, {"t": "match", "m": live.id, "kind": "challenge", "mode": live.mode, "op": op})

    async def on_invite(self, sock: Sock, d: dict, now: float) -> None:
        if sock.live:
            return await self.violate(sock)
        inv = sock.invite
        if inv and inv.b is sock and (inv.a.uid, inv.mode) == (d["to"], d["mode"]):  # crossed theirs: a yes
            await self.send(sock, {"t": "waiting", "id": inv.id})  # (both pressed REVANCHE)
            return await self.accept(inv, now)
        if not await self.signed_in(sock):
            return
        if code := self.refusal(0, sock.uid):  # an open invite holds no place
            return await self.send(sock, error(code))
        if not self.state.limits.allow((f"invite:{sock.uid}", INVITES, INVITES_S)):
            return await self.send(sock, error("invites"))
        await self.walk_away(sock)  # one invite at a time: a new one replaces it
        iid, to = "i_" + secrets.token_hex(8), self.socks.get(d["to"])  # no socket: offline, whoever it is
        why, pair = None, sorted((sock.uid, d["to"]))
        if to is None or to.skin is None or not self.db.execute(FRIEND, pair).fetchone():
            why = "offline"  # not a friend looks the same: nobody's status leaks
        elif to.invite or self.status(to.uid) == "racing":
            why = "busy"
        else:
            self.invites[iid] = sock.invite = to.invite = Invite(iid, sock, to, d["mode"], now + INVITE_S)
        await self.send(sock, {"t": "waiting", "id": iid})
        if why:
            return await self.send(sock, {"t": "invite_gone", "id": iid, "why": why})
        fr, mode = {"id": sock.uid, "nick": sock.nick}, d["mode"]
        await self.send(to, {"t": "invited", "id": iid, "from": fr, "mode": mode, "ttl": round(INVITE_S)})

    # an invite id that is gone is ignored (the message crossed its end); someone else's is a violation

    async def on_invite_cancel(self, sock: Sock, d: dict, now: float) -> None:
        inv = self.invites.get(d["id"])
        if inv and inv.a is not sock:
            return await self.violate(sock)
        if inv:
            await self.send(*self.withdraw(sock, "cancelled"))

    async def on_invite_reply(self, sock: Sock, d: dict, now: float) -> None:
        inv = self.invites.get(d["id"])
        if inv and inv.b is not sock:
            return await self.violate(sock)
        if inv is None:
            return
        if not d["ok"]:
            return await self.send(*self.withdraw(sock, "declined"))
        await self.accept(inv, now)

    async def accept(self, inv: Invite, now: float) -> None:
        """The invited said yes (a reply, or an invite back that crossed this one): the race, if it may."""
        self.withdraw(inv.b, "")  # the match says so
        gone = {"t": "invite_gone", "id": inv.id, "why": "offline"}
        for x, other in ((inv.b, inv.a), (inv.a, inv.b)):  # both still logged in, neither banned
            if not await self.signed_in(x):
                return await self.send(other, gone)
        pair = (inv.a, inv.b)
        if not self.db.execute(FRIEND, sorted(x.uid for x in pair)).fetchone():  # unfriended meanwhile
            await asyncio.gather(*(self.send(x, gone) for x in pair))
            return
        if code := self.refusal(2, *(x.uid for x in pair)):
            await asyncio.gather(*(self.send(x, error(code)) for x in pair))
            return
        seed = new_seed()  # one road for both
        with db.tx(self.db):
            mid = self.new_match("live", inv.mode, seed, inv.a.uid, inv.b.uid)
            a, b = (self.start(x, inv.mode, seed, now, mid, "live") for x in pair)
        a.op, b.op = b, a
        for x, y in ((a, b), (b, a)):
            op = {"nick": y.sock.nick, "skin": y.sock.skin}
            await self.send(x.sock, {"t": "match", "m": x.id, "kind": "live", "mode": x.mode, "op": op})

    async def on_ready(self, sock: Sock, d: dict, now: float) -> None:
        live = sock.live
        if live is None:  # too late: already rejected (prazo)
            return
        if live.ready:
            return await self.violate(sock)
        live.ready = True
        both = (live,) if live.op is None else (live, live.op)
        if not all(x.ready and not x.sock.closed for x in both):  # a lost socket: its end voids the match
            return
        for x in both:  # a race: the shared road, both started at once on one clock
            rival = x.op.sock.skin if x.op else x.rec and x.rec.skin  # traffic never wears it
            x.run = Run(assets(), x.mode, x.sock.skin, x.seed, x.kind != "solo", rival=rival)
            x.t0, x.stall0, x.heard = now + COUNTDOWN_S, self.stalled(now), now
            self.spawn(self.send(x.sock, {"t": "go", "m": x.id, "seed": x.seed}))  # both, next iteration

    async def on_in(self, sock: Sock, d: dict, now: float) -> None:
        live = sock.live
        if live is None or live.gone:  # over: inputs that were in flight
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
        if live.op:  # the rival gets these inputs as accepted, once its own k allows (flush)
            live.op.inbox.append({"t": "op", "m": live.op.id, "k": k, "ev": [[t, v] for t, v in d["ev"]]})
        if run.outcome or "fin" in d:
            live.fin = d.get("fin")
            await self.finish(live)
        elif live.op or live.rec:
            await self.decide(live)

    async def on_leave(self, sock: Sock, d: dict, now: float) -> None:
        if sock.live and not sock.live.gone:
            await self.finish(sock.live, None if sock.live.run else "prazo")

    # --- the end of a run -----------------------------------------------------------------------------

    async def finish(self, live: Live, why: str | None = None) -> None:
        """Ends a run (why: a rejection). Solo (a challenger's run too): its result. A race before go: void.
        In a race: the run stops there, the rival hears of it (op_end), and the verdict may end both. A
        challenge's friend: the verdict against the stored run (before go: a loss, as any forfeit)."""
        b = live.op
        if b is None and live.rec is None:
            return await self.send(live.sock, self.end(live, why))
        if self.live.get(live.id) is not live or live.gone:  # the race is over, or this run is
            return
        if live.run is None and b:
            late = not b.ready and self.clock() > b.deadline
            return await self.settle(live, why, "prazo" if late else "anulada", None)
        if live.run:
            live.run.stop("giveup")  # not over by itself: given up (or cut off) here, a forfeit
        live.gone = why or live.run.outcome  # (no run: why is prazo, conexao or invalido)
        if b:
            b.inbox.append({"t": "op_end", "m": b.id, "k": live.run.tick, "why": live.gone})
        await self.decide(live, why)

    async def flush(self, live: Live) -> None:
        """Sends a player the rival's inputs they may see: those for ticks before their own last k + AHEAD."""
        while live.inbox and live.inbox[0]["k"] <= live.run.known + AHEAD:
            await self.send(live.sock, live.inbox.popleft())

    async def decide(self, a: Live, why: str | None = None) -> None:
        """After every step of a's: who won, if anyone yet. A forfeit (cut off or rejected: a crash or a win
        is a result, for run.verdict) loses at once, so b's would have ended the race already; a give-up too,
        unless the rival's run had ended before it (a fin a few ticks past their crash: run.verdict)."""
        b = a.op
        v = -1 if a.gone not in (None, "crash", "win", "giveup") else verdict(a.run, b.run if b else a.rec)
        if v is None and a.gone == "giveup":
            v = -1
        if v is None:
            await self.flush(a)
            if b:
                self.spawn(self.flush(b))  # (a pop, then a wait on the FIFO lock: the order holds)
        else:
            await self.settle(a, why, None, v)

    async def settle(self, a: Live, wa: str | None, wb: str | None, v: int | None) -> None:
        """Ends both runs of a race and its match, a's verdict v (None: void) and each one's why. A
        challenge: a is the friend's run, raced against the stored one (rec); the challenger hears of it if in
        the game."""
        b, rec = a.op, a.rec
        them = b.sock if b else rec  # .uid, .nick
        for x in (a, b):
            if x and x.run:
                x.run.stop("decided")  # still going: the race ends here
        winner = a.sock.uid if v == 1 else them.uid if v == -1 else None  # done and None: a draw
        sql = "UPDATE matches SET state = ?, winner = ? WHERE id = ? AND state IN ('racing', 'playing_b')"
        if not self.db.execute(sql, ("void" if v is None else "done", winner, a.match)).rowcount:
            v = None  # a challenge voided meanwhile: the admin rejected its stored run, or its account went
        ra = self.end(a, wa)
        rb = self.end(b, wb) if b else {"score": rec.score.total, "secs": rec.secs}
        if v is not None:
            ra["verdict"], rb["verdict"] = VERDICTS[v], VERDICTS[-v]
            ra["op"] = {"nick": them.nick, "score": rb["score"], "secs": rb["secs"]}
            rb["op"] = {"nick": a.sock.nick, "score": ra["score"], "secs": ra["secs"]}

        async def tell(x: Live, result: dict) -> None:
            if x.run:  # (before go nothing of the rival's, a stored run's inbox included)
                await self.flush(x)  # what it may see of the rival first, then the end
                if x.inbox and x.inbox[-1]["t"] == "op_end":  # past the gate, but the race is over: how
                    await self.send(x.sock, x.inbox.pop())  # theirs ended (ops past the gate are dropped)
            await self.send(x.sock, result)

        if rec and v is not None and (sock := self.socks.get(rec.uid)) and sock.skin:
            done = {"t": "challenge_done", "id": a.match, "verdict": rb["verdict"], "op": rb["op"]}
            self.spawn(self.send(sock, done))
        await asyncio.gather(tell(a, ra), *([tell(b, rb)] if b else []))

    def end(self, live: Live, why: str | None = None) -> dict:
        """Stores the run as the server simulated it and returns its result. why: a rejection."""
        del self.live[live.id]
        live.sock.live = None
        self.announce(live.sock.uid)
        run, uid, fin = live.run, live.sock.uid, live.fin
        row: dict[str, Any] = {"ended": time.time(), "state": "rejected" if why else "ok"}
        out = {"outcome": None, "score": None, "secs": None, "rank": None}
        if run is not None:
            run.stop("giveup")  # not over by its last input: given up (or cut off) there
            arr = list(itertools.batched(live.arr, 2))  # [k, ms] pairs
            score, f = run.score.total, live.watch.features(arr)
            if not why and live.kind == "solo":  # ranked: the board, and its holds
                best = self.db.execute(BEST, (live.mode, uid)).fetchone()[0]
                held = self.db.execute(HELD, (live.mode, uid)).fetchone()[0]  # the player's run in review
                at = place(self.db, uid, live.mode, score) if best is None or score > best else None
                if at and held is not None and score <= held:
                    row["state"], why = "rejected", "substituida"  # one run in review per player and mode
                elif at and at <= 10 and score:
                    row["state"], why = "review", "top10"
                elif at and at <= 100 and flags.flagged(f):
                    row["state"], why = "review", "bot"
                if at and held is not None and row["state"] != "rejected":  # better: it replaces that one
                    self.db.execute(SUPERSEDE, (live.mode, uid))
            if not why and fin and (fin["outcome"], fin["score"]) != (run.outcome, score):
                why = "desync"  # the server's numbers stand; the log is kept to find out why
            log_json = json.dumps({"v": 1, "ev": run.ev, "arr": arr}, separators=(",", ":"))
            row |= {
                "ticks": run.tick,
                "outcome": run.outcome,
                "score": score,
                "coins": run.score.coins,
                "seconds": run.seconds,
                "client_score": fin and fin["score"],
                "max_lag": round(live.max_lag, 3),
                "features": json.dumps(f),
                "log": zlib.compress(log_json.encode()),
            }
            out = {"outcome": run.outcome, "score": score, "secs": round(run.seconds, 1), "rank": None}
            if row["state"] == "ok" and live.kind == "solo":
                out["rank"] = at or place(self.db, uid, live.mode, best)
        row["why"] = why
        sets = ", ".join(f"{column} = ?" for column in row)  # the columns are the literals above
        self.db.execute(f"UPDATE runs SET {sets} WHERE id = ?", (*row.values(), live.id))
        state = row["state"]
        if live.kind == "challenge" and live.rec is None:  # a challenger's: the friend's turn, or no turn
            if state == "ok":
                sql = "UPDATE matches SET state = 'open', expires = ? WHERE id = ? AND state = 'racing'"
                b = self.db.execute(sql + " RETURNING b", (time.time() + CHALLENGE_S, live.match)).fetchone()
                if b and (to := self.socks.get(b[0])) and to.skin:
                    new = offer(live.match, live.sock.nick, live.mode, out["secs"], out["score"])
                    self.spawn(self.send(to, {"t": "challenge_new", **new}))
            else:  # before go nothing was seen: void; after it, a forfeit (no redoing a bad run): theirs
                ends = "state = 'void'" if run is None else "state = 'done', winner = b"
                self.db.execute(f"UPDATE matches SET {ends} WHERE id = ? AND state = 'racing'", (live.match,))
        kind = {"solo": "ranqueada", "live": "ao vivo", "challenge": "desafio"}[live.kind]
        log.info("corrida %d %s %s %s %s max_lag %.2f", live.id, kind, live.mode, state, why, live.max_lag)
        out |= {"verdict": None, "op": None}  # a race: settle() fills them
        sql = f"SELECT coalesce(sum(coins), 0) FROM runs WHERE id = ? AND {PAID}"  # (no row: account deleted)
        out |= {"coins": self.db.execute(sql, (live.id,)).fetchone()[0], "wallet": wallet(self.db, uid)}
        return {"t": "result", "m": live.id, "run": live.id, "state": state, "why": why, **out}
