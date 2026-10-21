"""Browser-only link to the site's same-origin ``/ws`` (§5 of docs/web-platform-plan.md); the HttpOnly session
cookie rides along by itself.

The socket and its inbox live in JS (pygbag 0.9.3 never fires Python callbacks set on JS objects); the Game
polls the inbox once per frame. The JS is constant: no data is ever formatted into ``eval``. A closed socket
puts ``{"t": "closed"}`` in the inbox; the Game decides whether to open a new one.
"""

import json
import platform  # pygbag's: exposes the page's ``window``
import sys

import pygame

try:
    from ._build import BUILD  # written into the web build by tools/web_build.py
except ImportError:
    BUILD = "dev"

_JS = """
window.jq = [];
window.jopen = () => {
  if (window.jws) window.jws.close();  // a new hello (another car) replaces the socket
  window.jq = [];
  const ws = new WebSocket((location.protocol === 'https:' ? 'wss' : 'ws') + '://' + location.host + '/ws');
  ws.onmessage = (e) => { if (window.jws === ws) window.jq.push(e.data); };
  ws.onclose = () => { if (window.jws === ws) window.jq.push('{"t":"closed"}'); };
  window.jws = ws;
};
"""
CLOSED = "closed"


class Net:
    def __init__(self) -> None:
        platform.window.eval(_JS)
        self.up = False  # a socket is open or opening
        self.skin = ""  # the car its hello named
        self.error: str | None = None  # the last error code the server sent on it
        self.me: dict | None = None  # {"id", "nick"} once welcomed
        self.friends: dict[int, dict] = {}  # id -> {"id", "nick", "s": "menu|racing|off"}, kept by presence
        self.requests = 0  # friend requests waiting on the site
        self.challenges: list[dict] = []  # received, open: {"id", "from", "mode", "secs", "score"}
        self._out: list[str] = []

    def connect(self, skin: str) -> None:
        """A new socket (any open one is closed); its hello goes first."""
        py = ".".join(map(str, sys.version_info[:3]))
        hello = {"t": "hello", "build": BUILD, "py": py, "pg": pygame.version.ver, "skin": skin}
        self.up, self.skin, self.error, self.me = True, skin, None, None
        self.friends, self.challenges = {}, []
        self._out = [json.dumps(hello)]
        platform.window.eval("window.jopen()")

    def send(self, d: dict) -> None:
        """Sent once the socket is open; dropped when it is closed (its match is over)."""
        if self.up:
            self._out.append(json.dumps(d))
            self._flush()

    def poll(self) -> list[dict]:
        self._flush()
        q, msgs = platform.window.jq, []
        while int(q.length):
            msg = json.loads(str(q.shift()))
            if msg.get("t") == CLOSED:
                self.up, self._out = False, []
            elif msg.get("t") == "error":
                self.error = msg.get("code")
            elif msg.get("t") == "welcome":
                self.me, self.requests = msg.get("me"), msg.get("requests", 0)
                self.friends = {f["id"]: f for f in msg.get("friends", [])}
                self.challenges = list(msg.get("challenges", []))
            elif msg.get("t") == "challenge_new":
                self.challenges.append(msg)
            elif msg.get("t") == "presence" and msg.get("id") in self.friends:
                self.friends[msg["id"]]["s"] = msg.get("s")
            msgs.append(msg)
        return msgs

    def reload(self) -> bool:
        """A new build is out: the site's /jogar hands it out (this page's URL names this build for good).
        Once per build: refused again after that, the runtime itself differs, and reloading would loop."""
        store = platform.window.sessionStorage
        if store.getItem("jogo-recarregou") == BUILD:
            return False
        store.setItem("jogo-recarregou", BUILD)
        platform.window.location.href = "/jogar"
        return True

    def _flush(self) -> None:
        if not self._out:
            return
        ws = platform.window.jws
        while self._out and int(ws.readyState) == 1:
            ws.send(self._out.pop(0))
