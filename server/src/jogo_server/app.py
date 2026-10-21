"""The site (plan §4/§5): landing page, accounts, friends, the ranking, /jogar, /saude and the game's /ws
(hub.py). One uvicorn worker: rate limits, the hashing queue, sockets and runs in progress live in this
process; everything else is in SQLite.

    uvicorn jogo_server.app:app   (settings in the environment: see the README's "Servidor")
"""

import asyncio
import functools
import hashlib
import logging
import os
import re
import secrets
import sqlite3
import time
from collections.abc import Awaitable, Callable
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path

from authlib.integrations.starlette_client import OAuth, StarletteOAuth2App
from starlette.applications import Starlette
from starlette.datastructures import FormData
from starlette.middleware import Middleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.sessions import SessionMiddleware
from starlette.requests import HTTPConnection, Request
from starlette.responses import FileResponse, JSONResponse, PlainTextResponse, RedirectResponse, Response
from starlette.routing import Mount, Route, WebSocketRoute
from starlette.staticfiles import StaticFiles
from starlette.templating import Jinja2Templates
from starlette.websockets import WebSocket

import jogo_de_carro
from jogo_de_carro.settings import MODE_BY_KEY, MODES

from . import auth, db, hub, mail

HERE = Path(__file__).parent
ICON = Path(jogo_de_carro.__file__).parent / "assets" / "icon.png"
CSS_VERSION = hashlib.sha256((HERE / "static" / "site.css").read_bytes()).hexdigest()[:10]  # busts caches
TOO_MANY = "Muitas tentativas. Tente de novo em instantes."
CSP = "default-src 'self'; frame-ancestors 'none'; form-action 'self'; base-uri 'none'"
HTML_HEADERS = {
    "Content-Security-Policy": CSP,
    # /senha?t=… never leaks to another site; not no-referrer: Chrome then sends "Origin: null" on our forms
    "Referrer-Policy": "same-origin",
    "X-Content-Type-Options": "nosniff",
    "Cache-Control": "no-store",  # pages are personal; Back after "Sair" must not show them
    # https only, from the first visit on (browsers ignore it over http: dev is unaffected); not
    # includeSubDomains: other sites share pericles.dev.br
    "Strict-Transport-Security": "max-age=63072000",
}
log = logging.getLogger("jogo")


@dataclass(frozen=True)
class Config:
    dev: bool  # JOGO_DEV=1: plain http on localhost, no runtime check
    base: str  # https://DOMAIN: every link we send, and the only Origin a POST may come from
    secret: str
    db: str
    www: Path
    google_id: str
    google_secret: str
    smtp_host: str
    smtp_port: int
    smtp_user: str
    smtp_password: str
    mail_from: str
    admin_email: str
    max_ativas: int = 100  # runs in progress at most (set from python -m jogo_server.load)
    # while this file exists no run starts: jogo-deploy creates it and waits for /saude's ativas == 0 (the
    # tests and load.py use their own)
    drain: Path = Path("/srv/jogo/cache/drain")

    @property
    def cookie(self) -> str:
        return "sid" if self.dev else "__Host-sid"  # __Host-: Secure, Path=/, no Domain, or browsers drop it

    @property
    def mail(self) -> bool:
        return bool(self.smtp_host and self.mail_from)

    @classmethod
    def from_env(cls) -> "Config":
        env = os.environ.get
        dev = env("JOGO_DEV") == "1"
        domain = env("DOMAIN") or ("localhost:8090" if dev else "")
        secret = env("SESSION_SECRET") or (secrets.token_urlsafe(32) if dev else "")
        if not re.fullmatch(r"[a-z0-9.-]+(:[0-9]+)?", domain) or len(secret) < 32:
            raise RuntimeError("defina DOMAIN e SESSION_SECRET (32 caracteres ou mais), veja /etc/jogo/env")
        return cls(
            dev=dev,
            base=("http://" if dev else "https://") + domain,
            secret=secret,
            db=env("JOGO_DB") or "/var/lib/jogo/jogo.db",
            www=Path(env("JOGO_WWW") or "/srv/jogo/www"),
            google_id=env("GOOGLE_CLIENT_ID", ""),
            google_secret=env("GOOGLE_CLIENT_SECRET", ""),
            smtp_host=env("SMTP_HOST", ""),
            smtp_port=int(env("SMTP_PORT") or 587),
            smtp_user=env("SMTP_USER", ""),
            smtp_password=env("SMTP_PASSWORD", ""),
            mail_from=env("MAIL_FROM", ""),
            admin_email=env("ADMIN_EMAIL", ""),
            max_ativas=int(env("MAX_ATIVAS") or 100),
        )


# --- startup --------------------------------------------------------------------------------------------


def current_build(cfg: Config) -> str:
    """The build players get: $JOGO_WWW/current, written by jogo-deploy ("dev": a local build without one)."""
    path = cfg.www / "current"
    if cfg.dev and not path.exists():
        return "dev"
    build = path.read_text(encoding="utf-8").strip()
    if not re.fullmatch(r"[0-9a-f]{40}|dev", build):
        raise RuntimeError(f"{path}: build inválido {build!r}")
    return build


def check_runtime(cfg: Config, build: str) -> None:
    """Refuse to start unless this CPU and runtime simulate exactly like the browser that runs the build."""
    import platform

    os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
    import pygame

    from jogo_de_carro import golden

    want = (cfg.www / "jogo" / build / "golden.txt").read_text(encoding="utf-8").strip()
    got = (platform.python_version(), pygame.version.ver, golden.digest())
    if got != (*hub.RUNTIME, want):
        raise RuntimeError(f"recusado: Python {got[0]}, pygame-ce {got[1]}, golden {got[2]} (build: {want})")


@asynccontextmanager
async def lifespan(app: Starlette):
    # uvicorn logs each WebSocket it accepts, with the player's address, at INFO (even with --no-access-log):
    # keep its loggers quieter, whatever the unit's flags
    for name in ("uvicorn.error", "uvicorn.access"):
        logging.getLogger(name).setLevel(logging.WARNING)
    if not log.handlers:  # uvicorn configures only its own loggers; ours prints one line per finished run
        log.addHandler(logging.StreamHandler())
        log.setLevel(logging.INFO)
        log.propagate = False
    cfg = app.state.cfg
    app.state.build = current_build(cfg)
    app.state.golden = False  # in dev nothing was checked
    if not cfg.dev:
        check_runtime(cfg, app.state.build)
        app.state.golden = True
    app.state.db = db.connect(cfg.db)
    app.state.hasher = auth.Hasher()
    app.state.limits = auth.Limits()
    clock = getattr(app.state, "clock", None)  # tests drive the hub's clock and its ticks by hand
    app.state.hub = hub.Hub(app.state, clock)
    tasks = [asyncio.create_task(remind(app.state))]
    if clock is None:
        tasks.append(asyncio.create_task(app.state.hub.ticker()))
    log.warning("pronto: build %s em %s", app.state.build, cfg.base)
    yield
    for task in tasks:
        task.cancel()
    app.state.db.close()


def review_mail(state) -> None:
    """Emails ADMIN_EMAIL how many runs wait for review, if any do."""
    n = state.db.execute("SELECT count(*) FROM runs WHERE state = 'review'").fetchone()[0]
    if n and state.cfg.admin_email and state.cfg.mail:
        state.send_mail(state.cfg.admin_email, mail.review_message(state.cfg.base, n))


async def remind(state) -> None:
    while True:  # at startup, then hourly: one email an hour at most while the queue is not empty
        review_mail(state)
        await asyncio.sleep(3600)


# --- every request --------------------------------------------------------------------------------------


def same_origin(conn: HTTPConnection) -> bool:
    """CSRF (with SameSite=Lax): a POST, or the game's WebSocket, must come from our own pages."""
    return conn.headers.get("origin") == conn.app.state.cfg.base


async def guard(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
    if request.method == "POST" and not same_origin(request):
        request.state.user = None  # the page renders logged out: the session is not even read
        return notice(request, "Não permitido", "Origem não permitida.", 403)
    cfg = request.app.state.cfg
    request.state.user, renewed = auth.session_user(request.app.state.db, request.cookies.get(cfg.cookie))
    response = await call_next(request)
    if renewed and not any(k == b"set-cookie" for k, _ in response.raw_headers):  # a login/logout wins
        set_session(response, cfg, request.cookies[cfg.cookie])
    return response


def set_session(response: Response, cfg: Config, token: str) -> None:
    response.set_cookie(
        cfg.cookie, token, max_age=int(auth.SESSION_TTL), httponly=True, secure=not cfg.dev, samesite="lax"
    )


def site(request: Request) -> dict:
    state = request.app.state
    google, mail_ok = state.google is not None, state.cfg.mail
    return {"user": request.state.user, "google": google, "mail": mail_ok, "css": CSS_VERSION}


templates = Jinja2Templates(directory=HERE / "templates", context_processors=[site])  # *.html: autoescaped


def page(request: Request, name: str, status: int = 200, **context: object) -> Response:
    return templates.TemplateResponse(request, name, context, status_code=status, headers=HTML_HEADERS)


def notice(request: Request, title: str, text: str, status: int = 200) -> Response:
    return page(request, "aviso.html", status, titulo=title, texto=text)


def go(url: str) -> Response:
    return RedirectResponse(url, 303)


def field(form: FormData, name: str) -> str:
    value = form.get(name)
    return value if isinstance(value, str) else ""


def account(need_nick: bool = True):
    """Pages for logged-in players; most also need the nickname chosen."""

    def wrap(endpoint: Callable[[Request, sqlite3.Row], Awaitable[Response]]):
        @functools.wraps(endpoint)
        async def run(request: Request) -> Response:
            user = request.state.user
            if user is None:
                return go("/entrar")
            if need_nick and not user["nick"]:
                return go("/apelido")
            return await endpoint(request, user)

        return run

    return wrap


def drop_session(request: Request) -> None:
    """Ends the session the browser came with, if any."""
    if sid := request.cookies.get(request.app.state.cfg.cookie):
        request.app.state.db.execute("DELETE FROM sessions WHERE id = ?", (auth.digest(sid),))


def login(request: Request, user: sqlite3.Row) -> Response:
    """A fresh session (never the one the browser came with) and on to the nickname or the home page."""
    state, cfg = request.app.state, request.app.state.cfg
    drop_session(request)
    response = go("/" if user["nick"] else "/apelido")
    set_session(response, cfg, auth.new_session(state.db, user["id"]))
    return response


def end_sessions(state, uid: int) -> None:
    """Logs the user out everywhere, their open game included (a new password, "sair de todos", deletion)."""
    auth.end_sessions(state.db, uid)
    state.hub.kick(uid)


def logged_out(cfg: Config, response: Response | None = None) -> Response:
    response = response or go("/")
    response.delete_cookie(cfg.cookie, secure=not cfg.dev, httponly=True, samesite="lax")
    return response


def send_link(request: Request, email: str) -> bool:
    """Emails a link that sets the password (creating the account on first use). False: rate limited."""
    state = request.app.state
    ip, net = auth.client_ip(request.client and request.client.host)
    if not state.limits.allow(
        (f"link:{auth.mailbox(email)}", 3, 3600),
        (f"link-ip:{ip}", 10, 3600),
        (f"link-net:{net}", 20, 3600),
        ("link", 50, 3600),
        ("link-day", 280, auth.DAY),  # under the relay's free 300 a day: past it, mail would silently drop
    ):
        return False
    if not state.db.execute("SELECT 1 FROM users WHERE email = ? AND role = 'banned'", (email,)).fetchone():
        state.send_mail(email, mail.link_message(state.cfg.base, auth.new_link(state.db, email)))
    return True


# --- pages ----------------------------------------------------------------------------------------------


def ranking(state, mode: str) -> list[sqlite3.Row]:
    """The whole board of a mode, cached 10 s: the pages are public. ponytail: the whole board in memory, for
    "você: #N"; fine to some 100k players a mode."""
    hit = state.boards.get(mode)
    if hit is None or hit[0] < time.monotonic():
        hit = state.boards[mode] = (time.monotonic() + 10, hub.board(state.db, mode))
    return hit[1]


async def home(request: Request) -> Response:
    tops = [(m, ranking(request.app.state, m.key)[:10]) for m in MODES]
    return page(request, "index.html", tops=tops)


async def ranking_page(request: Request) -> Response:
    modo = request.query_params.get("modo", "normal")
    if modo not in MODE_BY_KEY:
        return PlainTextResponse("Não encontrado.", 404)
    linhas, user = ranking(request.app.state, modo), request.state.user
    voce = next((n for n, r in enumerate(linhas, 1) if user and r["user_id"] == user["id"]), None)
    return page(request, "ranking.html", modos=MODES, modo=MODE_BY_KEY[modo], linhas=linhas[:100], voce=voce)


async def entrar(request: Request) -> Response:
    if request.method == "GET":
        return page(request, "entrar.html")
    state = request.app.state
    form = await request.form()
    email, password = field(form, "email").strip(), field(form, "senha")
    ip, net = auth.client_ip(request.client and request.client.host)
    if not state.limits.allow(
        (f"login:{ip}:{email[:254].casefold()}", 10, 900),  # [:254]: not validated yet, keep the key small
        (f"login-ip:{ip}", 50, 3600),
        (f"login-net:{net}", 300, 3600),
    ):
        return page(request, "entrar.html", 429, erro=TOO_MANY, email=email)
    user = None
    if auth.valid_email(email) and len(password) <= 128:
        user = state.db.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
    checked = user and user["pw_hash"]
    try:
        ok = await state.hasher.verify(checked, password[:128])
        if ok and state.hasher.ph.check_needs_rehash(checked):
            pw_hash = await state.hasher.hash(password)
            sql = "UPDATE users SET pw_hash = ? WHERE id = ? AND pw_hash = ?"  # not over a newer password
            if state.db.execute(sql, (pw_hash, user["id"], checked)).rowcount:
                checked = pw_hash
    except auth.Busy:
        return page(request, "entrar.html", 429, erro=TOO_MANY, email=email)
    # The password may have changed while we hashed (a reset, which also ended every session): log in only if
    # the hash we checked is still the account's. Nothing awaits between this and login().
    sql = "SELECT 1 FROM users WHERE id = ? AND pw_hash = ?"
    if ok and state.db.execute(sql, (user["id"], checked)).fetchone() is None:
        ok = False
    if not ok:
        return page(request, "entrar.html", 400, erro="E-mail ou senha incorretos.", email=email)
    return login(request, user)


async def pedir_link(request: Request) -> Response:
    """/cadastro and /esqueci: one form, one handler, and always the same reply."""
    title = "Criar conta" if request.url.path == "/cadastro" else "Esqueci a senha"
    if request.method == "GET":
        return page(request, "link.html", titulo=title)
    if not request.app.state.cfg.mail:
        return page(request, "link.html", 503, titulo=title)
    email = field(await request.form(), "email").strip()
    if not auth.valid_email(email):
        return page(request, "link.html", 400, titulo=title, email=email, erro="Confira o e-mail.")
    if not send_link(request, email):
        return page(request, "link.html", 429, titulo=title, email=email, erro=TOO_MANY)
    return page(request, "link.html", titulo=title, enviado=True)


async def senha(request: Request) -> Response:
    """GET only shows the form (mail scanners open links); POST uses the link up, sets the password, ends
    every other session and logs in."""
    state = request.app.state
    if request.method == "GET":
        token = request.query_params.get("t", "")
        email = auth.link_email(state.db, token)
        return page(request, "senha.html", 200 if email else 400, t=token, email=email)
    form = await request.form()
    token, password = field(form, "t"), field(form, "senha")
    if not (email := auth.link_email(state.db, token)):
        return page(request, "senha.html", 400)
    erro = None
    if password != field(form, "senha2"):
        erro = "As duas senhas não são iguais."
    elif not 8 <= len(password) <= 128:
        erro = "A senha precisa ter de 8 a 128 caracteres."
    if erro:
        return page(request, "senha.html", 400, t=token, email=email, erro=erro)
    try:
        pw_hash = await state.hasher.hash(password)  # before using the link up: a 429 must not spend it
    except auth.Busy:
        return page(request, "senha.html", 429, t=token, email=email, erro=TOO_MANY)
    with db.tx(state.db):
        if not (email := auth.use_link(state.db, token)):  # someone used it while we hashed
            return page(request, "senha.html", 400)
        user = state.db.execute(
            "INSERT INTO users(email, pw_hash, created) VALUES (?, ?, ?)"
            " ON CONFLICT(email) DO UPDATE SET pw_hash = excluded.pw_hash RETURNING *",
            (email, pw_hash, time.time()),
        ).fetchone()
        end_sessions(state, user["id"])
    return login(request, user)


@account(need_nick=False)
async def apelido(request: Request, user: sqlite3.Row) -> Response:
    if user["nick"]:
        return go("/conta")  # permanent once chosen
    if request.method == "GET":
        return page(request, "apelido.html")
    nick = field(await request.form(), "apelido").strip()
    erro = auth.nick_problem(nick)
    if not erro:
        try:
            request.app.state.db.execute(
                "UPDATE users SET nick = ? WHERE id = ? AND nick IS NULL", (nick, user["id"])
            )
        except sqlite3.IntegrityError:
            erro = "Esse apelido já está em uso."
    if erro:
        return page(request, "apelido.html", 400, erro=erro, apelido=nick)
    return go("/")


@account(need_nick=False)
async def conta(request: Request, user: sqlite3.Row) -> Response:
    return page(request, "conta.html")


@account(need_nick=False)
async def trocar_senha(request: Request, user: sqlite3.Row) -> Response:
    if not request.app.state.cfg.mail:
        return page(request, "conta.html", 503, erro="O envio de e-mail está indisponível no momento.")
    if not send_link(request, user["email"]):
        return page(request, "conta.html", 429, erro=TOO_MANY)
    return notice(request, "Link enviado", f"Enviamos para {user['email']} um link para trocar a senha.")


async def sair(request: Request) -> Response:
    drop_session(request)
    return logged_out(request.app.state.cfg)


@account(need_nick=False)
async def sair_todos(request: Request, user: sqlite3.Row) -> Response:
    end_sessions(request.app.state, user["id"])
    return logged_out(request.app.state.cfg)


@account(need_nick=False)
async def excluir(request: Request, user: sqlite3.Row) -> Response:
    """Deletes the account and, by cascade, everything tied to it (LGPD)."""
    typed = field(await request.form(), "confirmar").strip()
    if typed.casefold() != (user["nick"] or user["email"]).casefold():
        return page(request, "conta.html", 400, erro="O texto digitado não confere.")
    state = request.app.state
    with db.tx(state.db):
        end_sessions(state, user["id"])
        state.db.execute("DELETE FROM users WHERE id = ?", (user["id"],))
    request.state.user = None
    return logged_out(
        state.cfg, notice(request, "Conta excluída", "Sua conta e tudo ligado a ela foram apagados.")
    )


# only the one asked accepts
ACCEPT = "UPDATE friends SET accepted = 1 WHERE a = ? AND b = ? AND asked_by != ?"


@account()
async def amigos(request: Request, user: sqlite3.Row) -> Response:
    state, me = request.app.state, user["id"]
    erro, status = None, 200
    if request.method == "POST":
        nick = field(await request.form(), "apelido").strip()
        other = state.db.execute("SELECT id FROM users WHERE nick = ?", (nick,)).fetchone()
        if other is None:
            erro, status = "Ninguém com esse apelido.", 400
        elif other["id"] == me:
            erro, status = "Esse apelido é o seu.", 400
        elif not state.limits.allow((f"amigo:{me}", 30, auth.DAY)):
            erro, status = "Pedidos demais hoje. Tente amanhã.", 429
        else:
            a, b = sorted((me, other["id"]))
            state.db.execute("INSERT OR IGNORE INTO friends(a, b, asked_by) VALUES (?, ?, ?)", (a, b, me))
            state.db.execute(ACCEPT, (a, b, me))  # asking someone who already asked you is accepting
            return go("/amigos")
    lista = state.db.execute(auth.FRIENDS, {"me": me}).fetchall()
    return page(request, "amigos.html", status, erro=erro, lista=lista)


@account()
async def amigo(request: Request, user: sqlite3.Row) -> Response:
    """aceitar a request someone sent me; recusar or remover any friendship or request of mine."""
    acao, other = request.path_params["acao"], request.path_params["id"]
    me, conn = user["id"], request.app.state.db
    if acao not in ("aceitar", "recusar", "remover") or not 0 < other < 2**63:  # {id:int} takes any digits
        return PlainTextResponse("Não encontrado.", 404)
    a, b = sorted((me, other))
    if acao == "aceitar":
        conn.execute(ACCEPT, (a, b, me))
    else:
        conn.execute("DELETE FROM friends WHERE a = ? AND b = ?", (a, b))
    return go("/amigos")


async def privacidade(request: Request) -> Response:
    return page(request, "privacidade.html", contato=request.app.state.cfg.admin_email)


@account()
async def jogar(request: Request, user: sqlite3.Row) -> Response:
    return RedirectResponse(f"/jogo/{request.app.state.build}/", 302)


async def saude(request: Request) -> Response:
    state = request.app.state
    review = state.db.execute("SELECT count(*) FROM runs WHERE state = 'review'").fetchone()[0]
    sql = "SELECT count(*) FROM runs WHERE why = 'desync' AND ended > ?"
    desync = state.db.execute(sql, (time.time() - auth.DAY,)).fetchone()[0]
    return JSONResponse(
        {
            "build": state.build,
            "golden": state.golden,
            "ativas": len(state.hub.live),
            "loop_lag_ms": round(state.hub.loop_lag * 1000),
            "review": review,
            "desync_24h": desync,
        }
    )


async def ws(websocket: WebSocket) -> None:
    if not same_origin(websocket):  # cross-site WebSocket hijacking: HTTP middleware never sees this
        await websocket.close(1008)  # before accept(): the handshake gets 403
        return
    state = websocket.app.state
    await state.hub.serve(websocket, websocket.cookies.get(state.cfg.cookie))


# --- Google ---------------------------------------------------------------------------------------------


def google_client(cfg: Config) -> StarletteOAuth2App | None:
    if not cfg.google_id:
        return None  # no client yet: the button is hidden
    return OAuth().register(
        "google",
        client_id=cfg.google_id,
        client_secret=cfg.google_secret,
        server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
        client_kwargs={"scope": "openid email profile", "code_challenge_method": "S256"},
    )


async def google_start(request: Request) -> Response:
    # state, nonce and the PKCE verifier wait in the short-lived signed cookie (SessionMiddleware)
    redirect = request.app.state.cfg.base + "/auth/google/callback"
    return await request.app.state.google.authorize_redirect(request, redirect)


async def google_back(request: Request) -> Response:
    try:
        token = await request.app.state.google.authorize_access_token(
            request
        )  # checks state, nonce, id_token
    except Exception as e:  # fail closed: whatever went wrong, nobody logs in
        log.warning("login Google recusado: %s", type(e).__name__)
        return notice(request, "Não deu certo", "Não foi possível entrar com o Google. Tente de novo.", 400)
    with db.tx(request.app.state.db):
        user, erro = auth.google_account(request.app.state.db, token.get("userinfo"))
    if erro:
        return notice(request, "Não deu certo", erro, 400)
    return login(request, user)


# --- the app --------------------------------------------------------------------------------------------


def create_app(cfg: Config | None = None) -> Starlette:
    cfg = cfg or Config.from_env()
    routes = [
        Route("/", home),
        Route("/entrar", entrar, methods=["GET", "POST"]),
        Route("/cadastro", pedir_link, methods=["GET", "POST"]),
        Route("/esqueci", pedir_link, methods=["GET", "POST"]),
        Route("/senha", senha, methods=["GET", "POST"]),
        Route("/apelido", apelido, methods=["GET", "POST"]),
        Route("/conta", conta),
        Route("/conta/senha", trocar_senha, methods=["POST"]),
        Route("/conta/sair-todos", sair_todos, methods=["POST"]),
        Route("/conta/excluir", excluir, methods=["POST"]),
        Route("/sair", sair, methods=["POST"]),
        Route("/amigos", amigos, methods=["GET", "POST"]),
        Route("/amigos/{id:int}/{acao}", amigo, methods=["POST"]),
        Route("/privacidade", privacidade),
        Route("/jogar", jogar),
        Route("/saude", saude),
        Route("/ranking", ranking_page),
        WebSocketRoute("/ws", ws),
        Route("/icone.png", lambda request: FileResponse(ICON)),
        Mount("/static", StaticFiles(directory=HERE / "static")),
    ]
    if cfg.google_id:  # no client yet: the button is hidden and these are 404
        routes += [Route("/auth/google", google_start), Route("/auth/google/callback", google_back)]
    if cfg.dev:  # one process serves the whole local site; in production nginx serves these
        routes += [
            Mount("/jogo", StaticFiles(directory=cfg.www / "jogo", html=True, check_dir=False)),
            Mount("/cdn", StaticFiles(directory=cfg.www / "cdn", check_dir=False)),
        ]
    middleware = [
        Middleware(BaseHTTPMiddleware, dispatch=guard),
        Middleware(  # holds only Google's state, nonce and PKCE verifier, for 10 minutes
            SessionMiddleware,
            secret_key=cfg.secret,
            session_cookie="g" if cfg.dev else "__Host-g",
            max_age=600,
            https_only=not cfg.dev,
        ),
    ]
    app = Starlette(routes=routes, middleware=middleware, lifespan=lifespan, max_body_size=64 * 1024)
    app.state.cfg = cfg
    app.state.boards = {}  # ranking(): mode -> (expires, board)
    app.state.google = google_client(cfg)
    mail_pool = ThreadPoolExecutor(2, "mail")
    app.state.send_mail = lambda to, msg: mail_pool.submit(mail.send, cfg, to, msg)
    return app


app = create_app()
