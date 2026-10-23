"""The Game: window, fixed-step async main loop, scene stack, global keys (F11, M) and the site's messages."""

import asyncio
import contextlib
import os
import random
from pathlib import Path

import pygame

from .assets import Assets
from .audio import Audio
from .input import Action, Input
from .net import Net
from .save import default_save_path, load
from .scenes.base import WEB, Context, SceneManager, Transition
from .scenes.online import ConviteScene, WaitScene
from .scenes.race import RaceScene
from .scenes.title import TitleScene
from .scenes.versus import LiveScene, RecordingScene
from .settings import FIXED_DT, FPS, HEIGHT, MUTED, PRICE, TITLE, WIDTH
from .ui import blit_text, panel, text
from .world.road import BIOMES, ground

MAX_FRAME = 0.1  # longer hitches are not simulated (e.g. the window was dragged)
REALTIME_FRAME = 1.0  # ...except online, where the run must keep the server's clock (it allows 2 s of lag)
TOAST_TIME = 1.4
RETRY = 2.0  # seconds before a closed socket is opened again (only outside races)
NEW_BUILD = "Nova versão — recarregue"
FINAL = ("login", "version", "busy")  # the server's refusals after which no socket reopens by itself
DONE = {"win": "você venceu", "loss": "você perdeu", "draw": "deu empate"}  # challenge_done: my verdict


class Game:
    def __init__(
        self,
        *,
        save_path: Path | None = None,
        seed: int | None = None,
        autopilot: bool = False,
        time_scale: float = 1.0,
        strict_assets: bool | None = None,
        net: Net | None = None,
    ) -> None:
        pygame.init()
        pygame.display.set_caption(TITLE)
        self.screen = self._open_window()
        assets = Assets(strict=strict_assets)
        assets.preload()
        for biome in range(len(BIOMES)):  # behind the web's loading screen: one built mid-race would hitch
            ground(assets, biome)
        pygame.display.set_icon(assets.icon())
        save_path = save_path or default_save_path()
        save = load(save_path)
        self.ctx = Context(
            assets=assets,
            audio=Audio(assets, muted=save.muted),
            input=Input(),
            save=save,
            save_path=save_path,
            rng=random.Random(seed),
            quit=self.quit,
            autopilot=autopilot,
            net=net,
        )
        self.scenes = SceneManager(self.screen)
        self.ctx.scenes = self.scenes
        self.ctx.toast = self.toast
        self.screen.fill((0, 0, 0))
        self.scenes.switch(TitleScene(self.ctx), Transition.FADE)
        self.clock = pygame.time.Clock()
        self.time_scale = time_scale  # >1 fast-forwards the simulation (tests, demos)
        self.running = True
        self._accumulator = 0.0
        self._toast = ("", 0.0)
        self._retry: float | None = None  # a closed socket opens again when this runs out
        self._reload: float | None = None  # a new build: the page reloads when this runs out
        self._invite: tuple[dict, float] | None = None  # an invite held over a race or a wait, and its age
        self._done: list[str] = []  # how my challenges went, toasted once no race nor wait is up
        if net:
            net.connect(save.skin)

    @staticmethod
    def _open_window() -> pygame.Surface:
        if os.environ.get("SDL_VIDEODRIVER") == "dummy":  # headless: no renderer, so no scaling/vsync
            return pygame.display.set_mode((WIDTH, HEIGHT))
        # on the web the page's CSS scales the canvas (tools/web_build.py); RESIZABLE would resize SDL's
        # buffer to the CSS size, and SCALED's integer scaling would then letterbox the game in it, or crop it
        flags = pygame.SCALED if WEB else pygame.SCALED | pygame.RESIZABLE
        for kwargs in ({"flags": flags, "vsync": 1}, {"flags": flags}):
            with contextlib.suppress(pygame.error):
                return pygame.display.set_mode((WIDTH, HEIGHT), **kwargs)
        return pygame.display.set_mode((WIDTH, HEIGHT))  # no renderer (e.g. a VM): plain, unscaled window

    def quit(self) -> None:
        self.running = False

    def handle(self, event: pygame.Event) -> None:
        if event.type == pygame.QUIT:
            self.quit()
            return
        actions = self.ctx.input.translate(event)
        for action in actions:
            if action is Action.FULLSCREEN:
                with contextlib.suppress(pygame.error):  # e.g. headless
                    pygame.display.toggle_fullscreen()
            elif action is Action.MUTE:
                muted = self.ctx.audio.toggle_mute()
                self.ctx.save.muted = muted
                self.ctx.persist()
                self.toast("SOM DESLIGADO" if muted else "SOM LIGADO")
            else:
                self.scenes.handle(action, event)
        if not actions:
            self.scenes.handle(None, event)

    def step(self, frame_dt: float) -> None:
        """Process input, advance the simulation in fixed steps and draw one frame."""
        for event in pygame.event.get():
            self.handle(event)
        self._network(frame_dt)
        cap = REALTIME_FRAME if self.scenes.top.realtime else MAX_FRAME
        self._accumulator += min(frame_dt, cap) * self.time_scale
        while self._accumulator >= FIXED_DT and self.running:
            self.scenes.update(FIXED_DT)
            self._accumulator -= FIXED_DT
        self._toast = (self._toast[0], self._toast[1] - frame_dt)
        self.scenes.draw(self.screen)
        self._draw_toast()
        pygame.display.flip()

    def toast(self, label: str, seconds: float = TOAST_TIME) -> None:
        self._toast = (label, seconds)

    def _network(self, frame_dt: float) -> None:
        """The site's messages, and the timers that reopen the socket or reload the page."""
        net = self.ctx.net
        if not net:
            return
        for msg in net.poll():
            self._route(net, msg)
        if self._invite:  # shown once no race (its last seconds included) nor wait is up, if still on
            msg, age = self._invite
            left = float(msg.get("ttl") or 30) - age
            if left <= 0:
                self._invite = None
            elif not (self._racing() or isinstance(self.scenes.top, (WaitScene, ConviteScene))):
                self._invite = None
                self.scenes.push(ConviteScene(self.ctx, {**msg, "ttl": left}))
            else:
                self._invite = (msg, age + frame_dt)
        free = not (self._racing() or isinstance(self.scenes.top, WaitScene))
        if self._done and free and self._toast[1] <= 0:
            self.toast(self._done.pop(0), 3.0)
        if self._retry is not None and not self._racing():  # a bot race or a paused one is left alone
            self._retry -= frame_dt
            if self._retry <= 0:
                self._retry = None
                if not net.up:
                    net.connect(self.ctx.save.skin)
        if self._reload is not None:
            self._reload -= frame_dt
            if self._reload <= 0:
                self._reload = None
                if not net.reload():  # it did not help before: offline play
                    self.ctx.net = None

    def _racing(self) -> bool:
        return any(isinstance(s, RaceScene) for s in self.scenes.stack)

    def _route(self, net: Net, msg: dict) -> None:
        """match, go, waiting, invited and errors are the Game's; everything else goes to the top scene."""
        t, top = msg.get("t"), self.scenes.top
        waiting = isinstance(top, WaitScene) and not top.refused
        if t == "match":
            if waiting and top.m is None and msg.get("kind") == top.kind:
                top.m, top.match, top.label = msg["m"], msg, "Preparando…"
                net.send({"t": "ready", "m": msg["m"]})
            else:  # cancelled meanwhile
                net.send({"t": "leave", "m": msg["m"]})
        elif t == "go":
            if waiting and top.m == msg["m"] and top.match:  # the race starts now: its countdown syncs it
                m, mode, seed = msg["m"], top.match["mode"], msg["seed"]
                if top.ask["t"] == "challenge":  # my run, alone on the versus road, for the friend to race
                    to = top.friend["nick"]
                    race: RaceScene = RaceScene(
                        self.ctx, seed, True, online=m, mode=mode, skin=net.skin, to=to
                    )
                elif top.friend:  # a live race, or the friend's recorded one
                    live = RecordingScene if top.ask["t"] == "challenge_play" else LiveScene
                    race = live(self.ctx, top.match, top.friend, seed)
                else:
                    race = RaceScene(self.ctx, seed, online=m)
                self.scenes.switch(race, Transition.NONE)
        elif t == "waiting":  # my invite is out
            if waiting and top.ask["t"] == "invite" and top.invite is None:
                top.invite = msg["id"]
            else:  # cancelled meanwhile
                net.send({"t": "invite_cancel", "id": msg["id"]})
        elif t == "invited":  # held over a race or a wait (see _network): unanswered, it expires
            self._invite = (msg, 0.0)
        elif t == "challenge_done" and msg.get("verdict") in DONE:  # a friend raced my recorded run
            nick = (msg.get("op") or {}).get("nick") or "Seu amigo"
            self._done.append(f"{nick} aceitou seu desafio: {DONE[msg['verdict']]}")
        elif t == "error" and msg.get("code") == "version":
            self._reload = 2.0
            self._refused(NEW_BUILD, 2.0)
        elif t == "error" and msg.get("code") == "login":  # the page was opened logged out: offline play
            self.ctx.net = None
            self.toast(str(msg.get("msg") or "Sem login: jogando offline"))
            if waiting:  # JOGAR plays offline; a live race has no offline rival
                offline = RaceScene(self.ctx) if top.kind == "solo" else TitleScene(self.ctx)
                self.scenes.switch(offline, Transition.FADE)
        elif t == "error":  # full, drain, rate, busy...: the server's own words
            if waiting and top.play and msg.get("code") != "gone":  # refused before its attempt: still open
                net.challenges.insert(0, top.play)
            self._refused(str(msg.get("msg") or f"Erro do servidor: {msg.get('code')}"))
        else:
            if t == "closed":
                self._retry = None if net.error in FINAL else RETRY
            if t == "welcome" and self.ctx.save.skin in PRICE and self.ctx.save.skin not in net.owned:
                self.ctx.save.skin = net.skin  # yellow, as the server races it (a car it may race, picked
                self.ctx.persist()  # since the hello went out, stays: JOGAR takes it to a new socket)
            held = self._invite and self._invite[0].get("id")
            if t in ("closed", "welcome") or (t == "invite_gone" and msg.get("id") == held):
                self._invite = None  # it is over, or was on the socket before
            top.on_net(msg)

    def _refused(self, label: str, seconds: float = TOAST_TIME) -> None:
        top = self.scenes.top
        if isinstance(top, WaitScene):
            top.say(label)
        else:
            self.toast(label, seconds)

    def _draw_toast(self) -> None:
        label, left = self._toast
        if left <= 0:
            return
        rect = pygame.Rect(0, 0, max(260, text(label, 26).get_width() + 48), 44)
        rect.midbottom = (WIDTH // 2, HEIGHT - 20)
        panel(self.screen, rect, alpha=round(220 * min(1.0, left * 3)), radius=22)
        blit_text(
            self.screen, label, 26, rect.center, MUTED, shadow=False, alpha=round(255 * min(1.0, left * 3))
        )

    async def run(self) -> None:
        """Main loop; yields to the event loop every frame so a pygbag (web) build can run it."""
        while self.running:
            self.step(self.clock.tick(FPS) / 1000)
            await asyncio.sleep(0)
