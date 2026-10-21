"""Accounts (plan §5): the emailed link, login, sessions, CSRF, rate limits, the hashing budget, nicknames,
Google, deletion, /jogar, /saude and the startup check."""

import asyncio
import threading
import time
import timeit
from urllib.parse import parse_qs, urlsplit

import pytest
from argon2 import PasswordHasher
from authlib.integrations.base_client import OAuthError
from starlette.testclient import TestClient

from conftest import BASE, BUILD, config
from jogo_server import app as site
from jogo_server import auth

PASSWORD = "segredo123"


def cookie_of(response, name: str = "__Host-sid") -> str:
    return next(c for c in response.headers.get_list("set-cookie") if c.startswith(name + "="))


# --- the emailed link -----------------------------------------------------------------------------------


def test_link_flow_creates_the_account_and_logs_in(s):
    c = s.client()
    r = c.post("/cadastro", data={"email": "ana@x.test"})
    assert r.status_code == 200 and "Se o e-mail puder ser usado" in r.text
    [(to, subject, body)] = s.outbox
    assert to == "ana@x.test" and f"{BASE}/senha?t=" in body and "senha" in subject
    token = s.link()
    assert s.count("users") == 0  # nothing exists until the link is used

    for _ in range(2):  # opening the link (or a mail scanner opening it) spends nothing
        r = c.get("/senha", params={"t": token})
        assert r.status_code == 200 and "Defina sua senha" in r.text and "ana@x.test" in r.text
    assert s.count("tokens") == 1

    for senha, senha2, why in ((PASSWORD, "outra12345", "não são iguais"), ("curta", "curta", "de 8 a 128")):
        r = c.post("/senha", data={"t": token, "senha": senha, "senha2": senha2})
        assert r.status_code == 400 and why in r.text
    assert s.count("tokens") == 1  # a form error keeps the link

    r = c.post("/senha", data={"t": token, "senha": PASSWORD, "senha2": PASSWORD})
    assert r.status_code == 303 and r.headers["location"] == "/apelido"
    user = s.db.execute("SELECT * FROM users").fetchone()
    assert (
        user["email"] == "ana@x.test"
        and user["pw_hash"].startswith("$argon2id$")
        and ",p=1$" in user["pw_hash"]
    )
    assert s.count("tokens") == 0
    assert c.get("/conta").status_code == 200  # logged in

    # single use
    assert c.get("/senha", params={"t": token}).status_code == 400
    r = c.post("/senha", data={"t": token, "senha": "outra-senha", "senha2": "outra-senha"})
    assert r.status_code == 400 and "Link inválido" in r.text


def test_link_expires_after_an_hour(s):
    c = s.client()
    c.post("/esqueci", data={"email": "ana@x.test"})
    [expires] = s.db.execute("SELECT expires FROM tokens").fetchone()
    assert expires == pytest.approx(time.time() + 3600, abs=5)
    s.db.execute("UPDATE tokens SET expires = ?", (time.time() - 1,))
    token = s.link()
    assert c.get("/senha", params={"t": token}).status_code == 400
    assert c.post("/senha", data={"t": token, "senha": PASSWORD, "senha2": PASSWORD}).status_code == 400
    assert s.count("users") == 0


def test_same_reply_for_known_and_unknown_emails(s):
    s.user("ana@x.test", "ana", PASSWORD)
    s.user("gil@x.test", "gil", google_sub="g-1")
    c = s.client()
    for path in ("/cadastro", "/esqueci"):
        known, unknown = (c.post(path, data={"email": e}) for e in ("ana@x.test", "bia@x.test"))
        assert (known.status_code, known.text) == (unknown.status_code, unknown.text) == (200, known.text)
    assert [to for to, *_ in s.outbox] == ["ana@x.test", "bia@x.test"] * 2  # one link handler for all

    replies = set()
    for email in ("ana@x.test", "bia@x.test", "gil@x.test"):  # wrong password, unknown, Google only
        r = c.post("/entrar", data={"email": email, "senha": "nao-e-essa"})
        replies.add((r.status_code, r.text.replace(email, "EMAIL")))
    [(status, text)] = replies
    assert status == 400 and "E-mail ou senha incorretos" in text


def test_reset_link_sets_a_new_password_and_ends_other_sessions(s):
    uid = s.user("ana@x.test", "ana", PASSWORD)
    phone = s.client()
    s.login(phone, uid)
    c = s.client()
    c.post("/esqueci", data={"email": "ANA@x.test"})
    r = c.post("/senha", data={"t": s.link(), "senha": "nova-senha-1", "senha2": "nova-senha-1"})
    assert r.status_code == 303 and r.headers["location"] == "/"
    assert phone.get("/conta").headers["location"] == "/entrar"
    assert s.count("users") == 1 and s.count("sessions") == 1
    assert c.post("/entrar", data={"email": "ana@x.test", "senha": "nova-senha-1"}).status_code == 303


@pytest.mark.parametrize("rehash", [False, True])
def test_a_login_checked_before_a_reset_does_not_outlive_it(s, rehash):
    """A login with the old password whose check finishes while the owner resets it neither logs in nor (when
    the stored hash needs a rehash) writes the old password back over the new one."""
    s.user("ana@x.test", "ana", PASSWORD)
    if rehash:  # made under older parameters
        s.db.execute(
            "UPDATE users SET pw_hash = ?", (PasswordHasher(time_cost=2, parallelism=1).hash(PASSWORD),)
        )
    hasher, checked, release = s.app.state.hasher, threading.Event(), threading.Event()
    verify = hasher.verify

    async def verify_then_wait(pw_hash, password):  # the old password passes, then waits behind the reset
        ok = await verify(pw_hash, password)
        checked.set()
        await asyncio.to_thread(release.wait)
        return ok

    hasher.verify = verify_then_wait
    replies = []
    old = threading.Thread(
        target=lambda: replies.append(
            s.client("198.51.100.66").post("/entrar", data={"email": "ana@x.test", "senha": PASSWORD})
        )
    )
    old.start()
    assert checked.wait(10)
    hasher.verify = verify
    c = s.client()
    c.post("/esqueci", data={"email": "ana@x.test"})
    assert (
        c.post("/senha", data={"t": s.link(), "senha": "nova-senha-1", "senha2": "nova-senha-1"}).status_code
        == 303
    )
    release.set()
    old.join(10)
    assert replies[0].status_code == 400 and s.count("sessions") == 1  # the reset's own
    assert s.client().post("/entrar", data={"email": "ana@x.test", "senha": PASSWORD}).status_code == 400
    assert (
        s.client().post("/entrar", data={"email": "ana@x.test", "senha": "nova-senha-1"}).status_code == 303
    )


def test_signup_without_smtp_says_email_is_unavailable(make_site):
    s = make_site(smtp_host="")
    c = s.client()
    r = c.get("/cadastro")
    assert "E-mail indisponível" in r.text and "<fieldset disabled>" in r.text
    r = c.post("/cadastro", data={"email": "ana@x.test"})
    assert r.status_code == 503 and "E-mail indisponível" in r.text
    assert not s.outbox and s.count("tokens") == 0


# --- login, sessions ------------------------------------------------------------------------------------


def test_login_sets_a_fresh_locked_down_cookie(s):
    uid = s.user("ana@x.test", "ana", PASSWORD)
    c = s.client()
    s.login(c, uid)
    old = c.cookies["__Host-sid"]
    r = c.post("/entrar", data={"email": "Ana@X.test", "senha": PASSWORD})
    assert r.status_code == 303 and r.headers["location"] == "/"
    cookie = cookie_of(r)
    flags = {f.strip().split("=")[0].lower(): f.strip() for f in cookie.split(";")[1:]}
    assert flags.keys() == {"httponly", "max-age", "path", "samesite", "secure"}  # no Domain
    assert (
        flags["max-age"] == "Max-Age=2592000"
        and flags["path"] == "Path=/"
        and flags["samesite"].lower() == "samesite=lax"
    )
    new = cookie.split(";")[0].split("=", 1)[1]
    assert new != old and len(new) >= 43
    [sid] = s.db.execute("SELECT id FROM sessions").fetchone()
    assert sid == auth.digest(new)  # rotated, and only the hash is stored


def test_session_renews_under_15_days_left(s):
    c, _ = s.player("ana")
    s.db.execute("UPDATE sessions SET expires = ?", (time.time() + 20 * auth.DAY,))
    assert "set-cookie" not in c.get("/").headers
    s.db.execute("UPDATE sessions SET expires = ?", (time.time() + 10 * auth.DAY,))
    assert "Max-Age=2592000" in cookie_of(c.get("/"))
    [expires] = s.db.execute("SELECT expires FROM sessions").fetchone()
    assert expires > time.time() + 29 * auth.DAY


def test_expired_or_banned_sessions_are_logged_out(s):
    c, _ = s.player("ana")
    s.db.execute("UPDATE users SET role = 'banned'")
    assert c.get("/conta").headers["location"] == "/entrar"
    s.db.execute("UPDATE users SET role = 'player'")
    s.db.execute("UPDATE sessions SET expires = ?", (time.time() - 1,))
    assert c.get("/conta").headers["location"] == "/entrar"


def test_sair_and_sair_de_todos_os_aparelhos(s):
    uid = s.user("ana@x.test", "ana")
    laptop, phone, tablet = s.client(), s.client(), s.client()
    for c in (laptop, phone, tablet):
        s.login(c, uid)
    auth.new_link(s.db, "ana@x.test")
    r = tablet.post("/sair")
    assert r.status_code == 303 and "Secure" in cookie_of(r) and s.count("sessions") == 2
    r = laptop.post("/conta/sair-todos")
    assert r.status_code == 303 and r.headers["location"] == "/"
    assert phone.get("/conta").headers["location"] == "/entrar"
    assert s.count("sessions") == 0 and s.count("tokens") == 0  # end_sessions voids links too


@pytest.mark.parametrize("origin", [None, "https://evil.test", "http://jogo.test", "null"])
def test_cross_origin_posts_are_refused(s, origin):
    c, _ = s.player("ana")
    del c.headers["origin"]
    if origin:
        c.headers["origin"] = origin
    assert c.post("/cadastro", data={"email": "ana@x.test"}).status_code == 403
    assert c.post("/conta/excluir", data={"confirmar": "ana"}).status_code == 403
    assert c.post("/conta/sair-todos").status_code == 403
    assert not s.outbox and s.count("users") == 1 and s.count("sessions") == 1


def test_pages_are_escaped_and_carry_security_headers(s):
    r = s.client().post("/entrar", data={"email": "<script>x</script>@a.b", "senha": "x"})
    assert "<script>x" not in r.text and "&lt;script&gt;x" in r.text
    assert r.headers["content-security-policy"] == site.CSP
    assert "form-action 'self'" in site.CSP and "frame-ancestors 'none'" in site.CSP
    assert r.headers["referrer-policy"] == "same-origin" and r.headers["cache-control"] == "no-store"
    assert r.headers["strict-transport-security"] == "max-age=63072000"


# --- rate limits and the hashing budget -----------------------------------------------------------------


def test_login_limit_per_ip_and_email(s):
    s.user("ana@x.test", "ana", PASSWORD)
    c = s.client()
    for _ in range(10):
        assert c.post("/entrar", data={"email": "ana@x.test", "senha": "errada"}).status_code == 400
    r = c.post("/entrar", data={"email": "ANA@x.test", "senha": PASSWORD})
    assert r.status_code == 429 and "Muitas tentativas" in r.text
    other_ip = s.client("198.51.100.1")
    assert other_ip.post("/entrar", data={"email": "ana@x.test", "senha": PASSWORD}).status_code == 303


def test_link_limits_count_ipv6_per_64(s):
    home = s.client("2001:db8:1:2::1")
    for i in range(10):
        assert home.post("/cadastro", data={"email": f"p{i}@x.test"}).status_code == 200
    neighbour = s.client("2001:db8:1:2:ffff:1:2:3")  # same /64: the same subscriber
    assert neighbour.post("/cadastro", data={"email": "q@x.test"}).status_code == 429
    assert s.client("2001:db8:1:3::1").post("/cadastro", data={"email": "q@x.test"}).status_code == 200
    # 20 an hour for a whole /48 (what a tunnel broker hands out), however many /64s it rotates through
    for i in range(9):
        assert (
            s.client("2001:db8:1:3::1").post("/cadastro", data={"email": f"r{i}@x.test"}).status_code == 200
        )
    assert s.client("2001:db8:1:4::1").post("/cadastro", data={"email": "q@x.test"}).status_code == 429
    assert s.client("2001:db8:2::1").post("/cadastro", data={"email": "q@x.test"}).status_code == 200
    assert len(s.outbox) == 21


def test_link_limits_per_mailbox_hourly_and_daily(s):
    now = 0.0
    s.app.state.limits = auth.Limits(lambda: now)
    for i, email in enumerate(("ana@x.test", "Ana+1@x.test", "ana+2@X.test")):  # +tags reach the same inbox
        assert s.client(f"198.51.100.{i}").post("/esqueci", data={"email": email}).status_code == 200
    assert s.client("198.51.100.9").post("/esqueci", data={"email": "ana+3@x.test"}).status_code == 429
    assert (
        auth.mailbox("V.I.Tima+x@GMail.com") == "vitima@gmail.com"
        and auth.mailbox("a.b@x.test") == "a.b@x.test"
    )
    for i in range(47):  # 50 an hour in all
        r = s.client(f"203.0.113.{i // 10}").post("/cadastro", data={"email": f"p{i}@x.test"})
        assert r.status_code == 200
    assert s.client("192.0.2.1").post("/cadastro", data={"email": "z@x.test"}).status_code == 429
    for hour in range(1, 6):  # and 280 a day, under the relay's free quota (300)
        now = hour * 3600.0
        for i in range(50 if hour < 5 else 30):
            r = s.client(f"203.0.113.{i // 10}").post("/cadastro", data={"email": f"h{hour}-{i}@x.test"})
            assert r.status_code == 200
    assert s.client("192.0.2.1").post("/cadastro", data={"email": "z@x.test"}).status_code == 429
    assert len(s.outbox) == 280


def test_client_ip_keys():
    assert auth.client_ip("203.0.113.7") == ("203.0.113.7", "203.0.113.7")
    assert auth.client_ip("2001:db8:1:2:3:4:5:6") == ("2001:db8:1:2::/64", "2001:db8:1::/48")
    assert auth.client_ip("::ffff:203.0.113.7") == ("203.0.113.7", "203.0.113.7")
    assert auth.client_ip(None) == ("?", "?")


def test_limits_forget_expired_keys_and_cost_the_same_with_many():
    now = 0.0
    limits = auth.Limits(lambda: now)
    for i in range(150_000):
        assert limits.allow((f"login:{i}", 10, 900), ("login-ip:x", 10**6, 3600))
    assert not limits.allow(("login:0", 1, 900)) and len(limits.hits) == 150_001  # a refusal stores nothing

    def cost() -> float:
        return min(timeit.repeat(lambda: limits.allow(("k", 10**6, 900)), number=1, repeat=5))

    now = 30.0
    assert cost() < 1e-3  # no work proportional to the keys on a request
    now = 2 * 3600.0
    limits.allow(("k", 10**6, 900))  # the minute's sweep
    assert list(limits.hits) == ["k"] and cost() < 1e-3


def test_full_hash_queue_gives_429_and_keeps_the_link(s):
    s.user("ana@x.test", "ana", PASSWORD)
    c = s.client()
    c.post("/esqueci", data={"email": "ana@x.test"})
    s.app.state.hasher.pending = auth.Hasher.LIMIT
    assert c.post("/entrar", data={"email": "ana@x.test", "senha": PASSWORD}).status_code == 429
    r = c.post("/senha", data={"t": s.link(), "senha": PASSWORD, "senha2": PASSWORD})
    assert r.status_code == 429 and s.count("tokens") == 1
    s.app.state.hasher.pending = 0
    assert c.post("/senha", data={"t": s.link(), "senha": PASSWORD, "senha2": PASSWORD}).status_code == 303


def test_hasher_queue_cap_and_parameters():
    async def main():
        h = auth.Hasher()
        gate = threading.Event()
        waiting = [asyncio.ensure_future(h.run(gate.wait)) for _ in range(h.LIMIT)]
        await asyncio.sleep(0)  # all 8 queued on the one thread
        with pytest.raises(auth.Busy):
            await h.run(time.time)
        gate.set()
        await asyncio.gather(*waiting)
        assert h.pending == 0 and await h.verify(await h.hash("x" * 8), "x" * 8)
        assert not await h.verify(None, "")  # unknown account: the dummy hash, never True
        return h

    h = asyncio.run(main())
    assert (h.ph.parallelism, h.ph.time_cost, h.ph.memory_cost, h.pool._max_workers) == (1, 3, 65536, 1)


# --- nickname, /jogar, /saude ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("nick", "ok"),
    [
        *[("ana_42", True), ("ABC", True), ("ab", False), ("a" * 17, False), ("ana maria", False)],
        *[("joão", False), ("ana\n", False), ("Admin", False), ("BOT", False), ("sistema", False)],
    ],
)
def test_nick_rules(nick, ok):
    assert (auth.nick_problem(nick) is None) is ok


def test_apelido_is_unique_ignoring_case_and_permanent(s):
    s.user("bia@x.test", "Pericles")
    uid = s.user("ana@x.test")
    c = s.client()
    s.login(c, uid)
    assert c.get("/").status_code == 200 and "Escolher apelido" in c.get("/").text
    r = c.post("/apelido", data={"apelido": "suporte"})
    assert r.status_code == 400 and "reservado" in r.text
    r = c.post("/apelido", data={"apelido": "pericles"})
    assert r.status_code == 400 and "em uso" in r.text
    assert c.post("/apelido", data={"apelido": "ana_42"}).headers["location"] == "/"
    assert c.get("/apelido").headers["location"] == "/conta"
    assert c.post("/apelido", data={"apelido": "outro"}).headers["location"] == "/conta"
    assert s.db.execute("SELECT nick FROM users WHERE id = ?", (uid,)).fetchone()[0] == "ana_42"


def test_jogar_needs_a_session_and_a_nickname(s):
    c = s.client()
    assert c.get("/jogar").headers["location"] == "/entrar"
    uid = s.user("ana@x.test")
    s.login(c, uid)
    assert c.get("/jogar").headers["location"] == "/apelido"
    s.db.execute("UPDATE users SET nick = 'ana'")
    r = c.get("/jogar")
    assert r.status_code == 302 and r.headers["location"] == f"/jogo/{BUILD}/"


def test_saude(s):
    assert s.client().get("/saude").json() == {"build": BUILD, "golden": True}


def test_startup_refuses_a_golden_mismatch(tmp_path):
    cfg = config(tmp_path)
    (cfg.www / "jogo" / BUILD / "golden.txt").write_text("0" * 64 + "\n")
    with pytest.raises(RuntimeError, match="recusado"), TestClient(site.create_app(cfg)):
        pass  # the real check: this runtime's versions and golden.digest() against the build's golden.txt


def test_startup_passes_when_golden_matches_and_dev_skips_it(tmp_path, monkeypatch):
    from jogo_de_carro import golden

    monkeypatch.setattr(golden, "digest", lambda: "f" * 64)
    cfg = config(tmp_path)
    (cfg.www / "jogo" / BUILD / "golden.txt").write_text("f" * 64 + "\n")
    with TestClient(site.create_app(cfg), base_url=BASE) as c:
        assert c.get("/saude").json() == {"build": BUILD, "golden": True}

    (cfg.www / "jogo" / BUILD / "golden.txt").write_text("0" * 64 + "\n")
    dev = config(tmp_path, dev=True, base="http://localhost:8090")
    with TestClient(site.create_app(dev), base_url=dev.base, headers={"origin": dev.base}) as c:
        assert c.get("/saude").json() == {"build": BUILD, "golden": False}
        r = c.post("/cadastro", data={"email": "ana@x.test"})  # dev: http origin, plain cookie names
        assert r.status_code == 200

    (cfg.www / "current").write_text("../../etc\n")
    with pytest.raises(RuntimeError, match="build inválido"), TestClient(site.create_app(cfg)):
        pass


# --- Google ---------------------------------------------------------------------------------------------


@pytest.fixture
def g(make_site, monkeypatch):
    """A site with a Google client whose token exchange returns ``g.userinfo`` (or raises it)."""
    g = make_site(google_id="cid.apps.googleusercontent.com", google_secret="csecret")
    g.userinfo = None

    async def exchange(request):
        if isinstance(g.userinfo, Exception):
            raise g.userinfo
        return {"access_token": "a", **({"userinfo": g.userinfo} if g.userinfo is not None else {})}

    monkeypatch.setattr(g.app.state.google, "authorize_access_token", exchange)
    return g


def google_login(g, info, client=None):
    g.userinfo = info
    return (client or g.client()).get("/auth/google/callback", params={"code": "c", "state": "s"})


GMAIL = {"sub": "g-1", "email": "ana@gmail.com", "email_verified": True, "name": "Ana"}


def test_google_is_hidden_without_a_client(s, g):
    assert "Entrar com Google" not in s.client().get("/entrar").text
    assert s.client().get("/auth/google").status_code == 404
    assert s.client().get("/auth/google/callback").status_code == 404
    assert "Entrar com Google" in g.client().get("/entrar").text


def test_google_redirect_uses_domain_pkce_and_a_short_secure_cookie(g):
    g.app.state.google.server_metadata.update(
        {"authorization_endpoint": "https://accounts.google.com/o/oauth2/v2/auth", "_loaded_at": 1}
    )
    c = TestClient(g.app, base_url="https://evil.test", follow_redirects=False)  # a spoofed Host
    r = c.get("/auth/google")
    url = urlsplit(r.headers["location"])
    q = parse_qs(url.query)
    assert r.status_code == 302 and url.netloc == "accounts.google.com"
    assert q["redirect_uri"] == [f"{BASE}/auth/google/callback"] and q["scope"] == ["openid email profile"]
    assert q["code_challenge_method"] == ["S256"] and q["code_challenge"] and q["state"] and q["nonce"]
    cookie = cookie_of(r, "__Host-g").lower()
    assert all(flag in cookie for flag in ("max-age=600", "secure", "httponly", "path=/", "samesite=lax"))


def test_google_creates_a_gmail_account_then_logs_it_in_by_sub(g):
    r = google_login(g, GMAIL)
    assert r.status_code == 303 and r.headers["location"] == "/apelido" and cookie_of(r)
    user = g.db.execute("SELECT * FROM users").fetchone()
    assert (user["email"], user["google_sub"], user["pw_hash"]) == ("ana@gmail.com", "g-1", None)
    g.db.execute("UPDATE users SET nick = 'ana'")
    r = google_login(g, {**GMAIL, "email": "ana.nova@gmail.com"})  # the sub is the account, not the email
    assert r.headers["location"] == "/" and g.count("users") == 1


def test_google_workspace_domain_with_hd_is_accepted(g):
    assert google_login(g, {**GMAIL, "email": "ana@escola.edu.br", "hd": "escola.edu.br"}).status_code == 303


@pytest.mark.parametrize(
    "info",
    [
        {**GMAIL, "email": "ana@outlook.com"},  # Google is not the authority for this address
        {**GMAIL, "email_verified": False},
        {**GMAIL, "email_verified": "true"},
        {"email": "ana@gmail.com", "email_verified": True},  # no sub
        {},
        None,  # no userinfo (no id_token): fail closed
        OAuthError("access_denied"),
    ],
)
def test_google_refusals_create_and_link_nothing(g, info):
    existing = g.user("ana@outlook.com", "ana", PASSWORD)
    r = google_login(g, info)
    assert r.status_code == 400 and "set-cookie" not in r.headers
    assert g.count("users") == 1 and g.count("sessions") == 0
    assert g.db.execute("SELECT google_sub FROM users WHERE id = ?", (existing,)).fetchone()[0] is None


def test_google_links_an_existing_account_by_email(g):
    uid = g.user("ana@gmail.com", "ana", PASSWORD)
    r = google_login(g, GMAIL)
    assert r.status_code == 303 and r.headers["location"] == "/"
    user = g.db.execute("SELECT * FROM users").fetchone()
    assert (user["id"], user["google_sub"]) == (uid, "g-1") and user["pw_hash"]


def test_google_never_relinks_an_account_to_another_sub(g):
    g.user("ana@gmail.com", "ana", google_sub="g-1")
    r = google_login(g, {**GMAIL, "sub": "g-2"})
    assert r.status_code == 400 and "outra conta Google" in r.text and g.count("sessions") == 0


# --- deletion -------------------------------------------------------------------------------------------


def test_excluir_conta_needs_the_nickname_and_cascades(s):
    c, ana = s.player("ana")
    bia = s.user("bia@x.test", "bia")
    s.db.execute("INSERT INTO friends(a, b, asked_by, accepted) VALUES (?, ?, ?, 1)", (ana, bia, ana))
    s.login(s.client(), ana)  # another device
    auth.new_link(s.db, "ana@x.test")
    r = c.post("/conta/excluir", data={"confirmar": "bia"})
    assert r.status_code == 400 and s.count("users WHERE id = ?", ana) == 1
    r = c.post("/conta/excluir", data={"confirmar": " ANA "})
    assert r.status_code == 200 and "Conta excluída" in r.text and "Secure" in cookie_of(r)
    assert s.count("users WHERE id = ?", ana) == 0 and s.count("sessions") == 0
    assert s.count("friends") == 0 and s.count("tokens") == 0 and s.count("users") == 1
