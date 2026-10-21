"""Main menu over the attract-mode drive: Jogar, Skin, Dificuldade, Contra o bot, Sair (Site on the web)."""

import math

import pygame

from .. import __version__
from ..input import Action
from ..settings import ACCENT, FLAME, MUTED, SKIN_NAMES, WHITE, WIDTH
from ..ui import Menu, blit_text, glow, gradient_text, panel, text
from .base import WEB, Context, MenuScene, Transition

CREDITS = "IFAL 2022 · Adenilson · Eduardo · Erimaiken · Ingrid · Péricles"


def to_site() -> None:
    """The web build's SAIR: a page cannot close itself, so it goes back to the site's home page."""
    import platform  # pygbag's: the browser's window

    platform.window.location.href = "/"


class TitleScene(MenuScene):
    def __init__(self, ctx: Context, focus: int = 0) -> None:
        super().__init__(ctx)
        # new items go before SAIR, so the indices the other menus return to (focus=) keep their meaning
        labels = ["JOGAR", "SKIN", "DIFICULDADE", "CONTRA O BOT", "SITE" if WEB else "SAIR"]
        self.menu = Menu(labels, (WIDTH // 2, 412), ctx.audio, index=focus)
        self.logo = gradient_text("JOGO DE CARRO", 104, (255, 230, 120), FLAME)
        self.icon = pygame.transform.scale_by(ctx.assets.icon(), 2)
        self.clock = 0.0

    def enter(self) -> None:
        self.ctx.audio.music("menu")

    def handle(self, action: Action | None, event: pygame.Event) -> None:
        if action is Action.BACK:
            self.menu.index = 4  # SAIR / SITE
            self.ctx.audio.play("ui_back")
            return
        choice = self.menu.handle(action, event)
        if choice is None:
            return
        self.ctx.audio.play("ui_select")
        scenes = self.ctx.scenes
        if choice == 0:
            from .online import play

            scenes.switch(play(self.ctx), Transition.FADE)  # ranked when logged in to the site
        elif choice == 1:
            from .garage import GarageScene

            scenes.switch(GarageScene(self.ctx), Transition.SLIDE_LEFT)
        elif choice == 2:
            from .difficulty import DifficultyScene

            scenes.switch(DifficultyScene(self.ctx), Transition.SLIDE_LEFT)
        elif choice == 3:
            from .versus import BotScene

            scenes.switch(BotScene(self.ctx), Transition.SLIDE_LEFT)
        elif WEB:
            to_site()
        else:
            self.ctx.quit()

    def update(self, dt: float) -> None:
        super().update(dt)
        self.clock += dt
        self.menu.update(dt)

    def draw_ui(self, surface: pygame.Surface) -> None:
        self._draw_logo(surface)
        self.menu.draw(surface)
        self._draw_footer(surface)

    def _draw_logo(self, surface: pygame.Surface) -> None:
        bob = math.sin(self.clock * 1.8) * 5
        total = self.icon.get_width() + 18 + self.logo.get_width()
        x = WIDTH // 2 - total // 2
        cy = 128 + bob
        halo = glow(110, FLAME, 70)
        surface.blit(halo, halo.get_rect(center=(x + self.icon.get_width() // 2, cy)))
        surface.blit(self.icon, self.icon.get_rect(midleft=(x, cy - 4 * math.sin(self.clock * 3.1))))
        surface.blit(self.logo, self.logo.get_rect(midleft=(x + self.icon.get_width() + 18, cy)))
        blit_text(surface, "desvie · colete · sobreviva", 30, (WIDTH // 2, cy + 70), ACCENT)

    def _draw_footer(self, surface: pygame.Surface) -> None:
        save, mode = self.ctx.save, self.ctx.mode
        chips = [
            f"Carro: {SKIN_NAMES[save.skin]}",
            f"Modo: {mode.name}",
            f"Recorde: {save.best.get(mode.key, 0)}",
        ]
        x = 24
        for chip in chips:
            w = 24 + text(chip, 26).get_width()
            rect = pygame.Rect(x, 640, w, 34)
            panel(surface, rect, alpha=190, radius=17)
            blit_text(surface, chip, 26, rect.center, WHITE, shadow=False)
            x += w + 10
        pad = self.ctx.input.using_pad
        if pad:
            hint = "D-PAD navegar · A confirmar"
        else:
            hint = "SETAS navegar · ENTER confirmar" + ("" if WEB else " · F11 tela cheia") + " · M som"
        blit_text(surface, hint, 24, (WIDTH - 24, 657), MUTED, anchor="midright")
        blit_text(surface, f"{CREDITS} · v{__version__}", 24, (WIDTH // 2, 701), MUTED)
