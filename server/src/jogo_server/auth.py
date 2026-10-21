"""Accounts (plan §5): sessions, emailed links, password hashing, rate limits, nicknames, Google's rules.

An account exists only once its email (a link) or its Google account is proven; there is no unverified state.
"""

import asyncio
import hashlib
import ipaddress
import re
import secrets
import sqlite3
import time
from collections import deque
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

DAY = 86400.0
SESSION_TTL = 30 * DAY
RENEW_UNDER = 15 * DAY
LINK_TTL = 3600.0
EMAIL = re.compile(r"[^@\s]{1,64}@[^@\s]+\.[^@\s]+")
NICK = re.compile(r"[A-Za-z0-9_]{3,16}")
RESERVED = {"admin", "bot", "sistema", "moderador", "suporte"}


def digest(token: str) -> bytes:
    """What the database keeps of a cookie or a link: a leaked table opens no account."""
    return hashlib.sha256(token.encode()).digest()


def valid_email(email: str) -> bool:
    return len(email) <= 254 and EMAIL.fullmatch(email) is not None


def nick_problem(nick: str) -> str | None:
    if not NICK.fullmatch(nick):
        return "Use de 3 a 16 caracteres: letras sem acento, números ou _."
    if nick.casefold() in RESERVED:
        return "Esse apelido é reservado."
    return None


# --- sessions -------------------------------------------------------------------------------------------


def new_session(db: sqlite3.Connection, uid: int) -> str:
    token, now = secrets.token_urlsafe(32), time.time()
    db.execute("DELETE FROM sessions WHERE expires < ?", (now,))
    db.execute("INSERT INTO sessions VALUES (?, ?, ?)", (digest(token), uid, now + SESSION_TTL))
    return token


def session_user(db: sqlite3.Connection, token: str | None) -> tuple[sqlite3.Row | None, bool]:
    """The user behind a session cookie, and whether it was just renewed (under 15 of its 30 days left)."""
    if not token or len(token) > 64:
        return None, False
    now, sid = time.time(), digest(token)
    user = db.execute(
        "SELECT users.*, sessions.expires AS until FROM sessions JOIN users ON users.id = sessions.user_id"
        " WHERE sessions.id = ? AND sessions.expires > ? AND users.role != 'banned'",
        (sid, now),
    ).fetchone()
    if user is None or user["until"] - now >= RENEW_UNDER:
        return user, False
    db.execute("UPDATE sessions SET expires = ? WHERE id = ?", (now + SESSION_TTL, sid))
    return user, True


def end_sessions(db: sqlite3.Connection, uid: int) -> None:
    """Logs the user out everywhere and voids their emailed links. For a new password, "sair de todos", a ban
    and account deletion. In the server, app.end_sessions also closes the game's socket; a ban from the admin
    command reaches it at its next start (hub.on_solo checks the session)."""
    db.execute("DELETE FROM sessions WHERE user_id = ?", (uid,))
    db.execute("DELETE FROM tokens WHERE email = (SELECT email FROM users WHERE id = ?)", (uid,))


# --- emailed links (signup, forgotten password and "trocar senha" are one flow) -------------------------


def new_link(db: sqlite3.Connection, email: str) -> str:
    token, now = secrets.token_urlsafe(32), time.time()
    db.execute("DELETE FROM tokens WHERE expires < ?", (now,))
    db.execute("INSERT INTO tokens VALUES (?, ?, ?)", (digest(token), email, now + LINK_TTL))
    return token


def link_email(db: sqlite3.Connection, token: str) -> str | None:
    """The address a link was sent to, without using it up (GET /senha: mail scanners open links)."""
    if len(token) > 64:
        return None
    sql = "SELECT email FROM tokens WHERE id = ? AND expires > ?"
    row = db.execute(sql, (digest(token), time.time())).fetchone()
    return row["email"] if row else None


def use_link(db: sqlite3.Connection, token: str) -> str | None:
    if len(token) > 64:
        return None
    sql = "DELETE FROM tokens WHERE id = ? AND expires > ? RETURNING email"
    row = db.execute(sql, (digest(token), time.time())).fetchone()
    return row["email"] if row else None


# --- password hashing -----------------------------------------------------------------------------------


class Busy(Exception):
    """The hashing queue is full: 429."""


class Hasher:
    """Argon2id (64 MiB, t=3) on one thread. Hashing is the dearest thing a stranger can make us do, so with
    8 hashes already waiting or running the next request gets 429 instead of a place in the queue."""

    LIMIT = 8

    def __init__(self) -> None:
        self.ph = PasswordHasher(parallelism=1)
        self.pool = ThreadPoolExecutor(1, "argon2")
        self.pending = 0
        self.dummy = self.ph.hash(secrets.token_hex(16))  # unknown and Google-only accounts cost the same

    async def run(self, fn: Callable[..., Any], *args: Any) -> Any:
        if self.pending >= self.LIMIT:
            raise Busy
        self.pending += 1  # only the event loop's thread touches it
        try:
            return await asyncio.get_running_loop().run_in_executor(self.pool, fn, *args)
        finally:
            self.pending -= 1

    async def hash(self, password: str) -> str:
        return await self.run(self.ph.hash, password)

    async def verify(self, pw_hash: str | None, password: str) -> bool:
        def check() -> bool:
            try:
                return self.ph.verify(pw_hash or self.dummy, password) and pw_hash is not None
            except (VerificationError, InvalidHashError):
                return False

        return await self.run(check)


# --- rate limits ----------------------------------------------------------------------------------------


def client_ip(host: str | None) -> tuple[str, str]:
    """The rate-limit keys for an address (uvicorn takes it from the proxy's X-Forwarded-For): the subscriber
    and their network. IPv6: the /64 one subscriber usually gets and the /48 a site or a free tunnel broker
    hands out (ponytail: a carrier may put many players in one /48; they share its "-net" limits)."""
    try:
        ip = ipaddress.ip_address(host or "")
    except ValueError:
        return host or "?", host or "?"
    if ip.version == 6 and ip.ipv4_mapped is None:
        sub, net = (str(ipaddress.ip_network(f"{ip}/{bits}", strict=False)) for bits in (64, 48))
        return sub, net
    return (str(getattr(ip, "ipv4_mapped", None) or ip),) * 2


def mailbox(email: str) -> str:
    """The inbox an address reaches, for the per-address limit: no +tag, and Gmail ignores dots."""
    local, _, domain = email.casefold().rpartition("@")
    local = local.split("+")[0]
    return (local.replace(".", "") if domain in ("gmail.com", "googlemail.com") else local) + "@" + domain


class Limits:
    """Sliding windows in this process's memory. ponytail: they reset on restart; fine for damping abuse."""

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self.clock = clock
        self.hits: dict[str, tuple[float, deque[float]]] = {}  # key: (its window, its hits)
        self.sweep_at = 0.0

    def allow(self, *rules: tuple[str, int, float]) -> bool:
        """(key, at most, per seconds) each; counts the attempt in all of them only if all allow it."""
        now = self.clock()
        if now >= self.sweep_at:  # once a minute, forget the keys whose own window has passed
            self.sweep_at = now + 60
            self.hits = {k: (s, q) for k, (s, q) in self.hits.items() if q and q[-1] > now - s}
        for key, limit, seconds in rules:
            q = self.hits.get(key, (0, ()))[1]  # a refused attempt stores nothing
            while q and q[0] <= now - seconds:
                q.popleft()
            if len(q) >= limit:
                return False
        for key, _, seconds in rules:
            self.hits.setdefault(key, (seconds, deque()))[1].append(now)
        return True


# --- Google ---------------------------------------------------------------------------------------------


def google_account(db: sqlite3.Connection, info: dict | None) -> tuple[sqlite3.Row | None, str | None]:
    """The account a Google login opens, or why it opens none. A known Google account logs in. Otherwise only
    an address Google is the authority for (verified, and gmail.com or a Workspace domain, "hd") may link to
    the account with that email or create one: anything else could be someone else's address."""
    if not info or not isinstance(info.get("sub"), str) or not isinstance(info.get("email"), str):
        return None, "O Google não confirmou sua conta. Tente de novo."
    if user := db.execute("SELECT * FROM users WHERE google_sub = ?", (info["sub"],)).fetchone():
        return user, None
    email = info["email"]
    proven = info.get("email_verified") is True and (email.lower().endswith("@gmail.com") or info.get("hd"))
    if not (proven and valid_email(email)):
        return None, "Para este e-mail, entre com e-mail e senha."
    user = db.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
    if user and user["google_sub"]:
        return None, "Este e-mail já está ligado a outra conta Google."
    if user:
        db.execute("UPDATE users SET google_sub = ? WHERE id = ?", (info["sub"], user["id"]))
    else:
        sql = "INSERT INTO users(email, google_sub, created) VALUES (?, ?, ?)"
        db.execute(sql, (email, info["sub"], time.time()))
    return db.execute("SELECT * FROM users WHERE google_sub = ?", (info["sub"],)).fetchone(), None
