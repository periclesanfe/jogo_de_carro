"""The Game: window, fixed-step async main loop, scene stack and global keys (F11, M)."""

import asyncio
import contextlib
import os
import random
from pathlib import Path

import pygame

from .assets import Assets
from .audio import Audio
from .input import Action, Input
from .save import default_save_path, load
from .scenes.base import WEB, Context, SceneManager, Transition
from .scenes.title import TitleScene
from .settings import FIXED_DT, FPS, HEIGHT, MUTED, TITLE, WIDTH
from .ui import blit_text, panel

MAX_FRAME = 0.1  # longer hitches are not simulated (e.g. the window was dragged)
TOAST_TIME = 1.4


class Game:
    def __init__(
        self,
        *,
        save_path: Path | None = None,
        seed: int | None = None,
        autopilot: bool = False,
        time_scale: float = 1.0,
        strict_assets: bool | None = None,
    ) -> None:
        pygame.init()
        pygame.display.set_caption(TITLE)
        self.screen = self._open_window()
        assets = Assets(strict=strict_assets)
        assets.preload()
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
        )
        self.scenes = SceneManager(self.screen)
        self.ctx.scenes = self.scenes
        self.screen.fill((0, 0, 0))
        self.scenes.switch(TitleScene(self.ctx), Transition.FADE)
        self.clock = pygame.time.Clock()
        self.time_scale = time_scale  # >1 fast-forwards the simulation (tests, demos)
        self.running = True
        self._accumulator = 0.0
        self._toast = ("", 0.0)

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
                self._toast = ("SOM DESLIGADO" if muted else "SOM LIGADO", TOAST_TIME)
            else:
                self.scenes.handle(action, event)
        if not actions:
            self.scenes.handle(None, event)

    def step(self, frame_dt: float) -> None:
        """Process input, advance the simulation in fixed steps and draw one frame."""
        for event in pygame.event.get():
            self.handle(event)
        self._accumulator += min(frame_dt, MAX_FRAME) * self.time_scale
        while self._accumulator >= FIXED_DT and self.running:
            self.scenes.update(FIXED_DT)
            self._accumulator -= FIXED_DT
        self._toast = (self._toast[0], self._toast[1] - frame_dt)
        self.scenes.draw(self.screen)
        self._draw_toast()
        pygame.display.flip()

    def _draw_toast(self) -> None:
        label, left = self._toast
        if left <= 0:
            return
        rect = pygame.Rect(0, 0, 260, 44)
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
