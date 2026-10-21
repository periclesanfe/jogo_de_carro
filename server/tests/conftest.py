import contextlib
import dataclasses
import os
import re
import time
from email.message import EmailMessage

import pytest

os.environ.setdefault("JOGO_DEV", "1")  # importing jogo_server.app builds its module-level app from the env

from starlette.testclient import TestClient

from jogo_server import app as site
from jogo_server import auth

BASE = "https://jogo.test"
BUILD = "0123456789abcdef0123456789abcdef01234567"


def config(tmp_path, **changes) -> site.Config:
    """Production settings (https, __Host- cookies, Origin check) on a temporary database and web root."""
    www = tmp_path / "www"
    (www / "jogo" / BUILD).mkdir(parents=True, exist_ok=True)
    (www / "current").write_text(BUILD + "\n")
    cfg = site.Config(
        dev=False,
        base=BASE,
        secret="s" * 32,
        db=str(tmp_path / "jogo.db"),
        www=www,
        google_id="",
        google_secret="",
        smtp_host="smtp.jogo.test",
        smtp_port=587,
        smtp_user="",
        smtp_password="",
        mail_from="Jogo de Carro <nao-responda@jogo.test>",
        admin_email="admin@jogo.test",
    )
    return dataclasses.replace(cfg, **changes)


class Site:
    def __init__(self, app) -> None:
        self.app = app
        self.outbox: list[tuple[str, EmailMessage]] = []  # (to, message) instead of SMTP
        app.state.send_mail = lambda *message: self.outbox.append(message)

    @property
    def db(self):
        return self.app.state.db

    def client(self, ip: str = "203.0.113.7") -> TestClient:
        return TestClient(
            self.app, base_url=BASE, headers={"origin": BASE}, client=(ip, 50000), follow_redirects=False
        )

    def user(
        self, email: str, nick: str | None = None, password: str | None = None, google_sub: str | None = None
    ) -> int:
        pw_hash = password and self.app.state.hasher.ph.hash(password)
        return self.db.execute(
            "INSERT INTO users(email, nick, pw_hash, google_sub, created) VALUES (?,?,?,?,?) RETURNING id",
            (email, nick, pw_hash, google_sub, time.time()),
        ).fetchone()[0]

    def login(self, client: TestClient, uid: int) -> None:
        client.cookies.set("__Host-sid", auth.new_session(self.db, uid), domain="jogo.test")

    def player(self, nick: str) -> tuple[TestClient, int]:
        uid = self.user(f"{nick}@x.test", nick)
        client = self.client()
        self.login(client, uid)
        return client, uid

    def link(self) -> str:
        """The token in the last email sent."""
        return re.search(r"/senha\?t=(\S+)", self.outbox[-1][1].get_body(("plain",)).get_content())[1]

    def count(self, sql: str, *args) -> int:
        return self.db.execute(f"SELECT count(*) FROM {sql}", args).fetchone()[0]


@pytest.fixture
def make_site(tmp_path, monkeypatch):
    """make_site(**config changes) -> a started Site (the startup golden check is tested on its own)."""
    monkeypatch.setattr(site, "check_runtime", lambda cfg, build: None)
    with contextlib.ExitStack() as stack:

        def make(**changes) -> Site:
            app = site.create_app(config(tmp_path, **changes))
            stack.enter_context(TestClient(app))  # runs the lifespan until the test ends
            return Site(app)

        yield make


@pytest.fixture
def s(make_site) -> Site:
    return make_site()
