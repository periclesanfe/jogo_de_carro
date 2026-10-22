"""Main menu over the attract-mode drive: Jogar, Skin, Dificuldade, Contra o bot, Amigos (logged in to the
site), Sair (Site on the web)."""

import math

import pygame

from .. import __version__
from ..input import Action
from ..settings import ACCENT, CARS, FLAME, MUTED, WHITE, WIDTH
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
        self.menu = self._menu(focus)
        self.logo = gradient_text("JOGO DE CARRO", 104, (255, 230, 120), FLAME)
        self.icon = pygame.transform.scale_by(ctx.assets.icon(), 2)
        self.clock = 0.0

    def _labels(self) -> list[str]:
        # new items go before SAIR, so the indices the other menus return to (focus=) keep their meaning
        net = self.ctx.net
        friends = ["AMIGOS"] if net and net.up else []  # the site's socket: hidden offline and on the desktop
        return ["JOGAR", "SKIN", "DIFICULDADE", "CONTRA O BOT", *friends, "SITE" if WEB else "SAIR"]

    def _menu(self, focus: int) -> Menu:
        labels = self._labels()
        n = len(labels)  # six buttons close up a little to clear the logo and the footer
        center = (WIDTH // 2, 412 + 10 * (n - 5))
        return Menu(labels, center, self.ctx.audio, gap=14 - 4 * (n - 5), index=min(focus, n - 1))

    def enter(self) -> None:
        self.ctx.audio.music("menu")

    def handle(self, action: Action | None, event: pygame.Event) -> None:
        if action is Action.BACK:
            self.menu.index = len(self.menu.buttons) - 1  # SAIR / SITE
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
        elif self.menu.labels[choice] == "AMIGOS":
            from .online import AmigosScene

            scenes.switch(AmigosScene(self.ctx), Transition.SLIDE_LEFT)
        elif WEB:
            to_site()
        else:
            self.ctx.quit()

    def update(self, dt: float) -> None:
        super().update(dt)
        self.clock += dt
        if (labels := self._labels()) != self.menu.labels:  # the socket came up, or went: the focus stays on
            focused = self.menu.labels[self.menu.index]  # its item, or goes to JOGAR (never onto SAIR / SITE)
            self.menu = self._menu(labels.index(focused) if focused in labels else 0)
        self.menu.update(dt)

    def draw_ui(self, surface: pygame.Surface) -> None:
        self._draw_logo(surface)
        self.menu.draw(surface)
        self._draw_footer(surface)
        self._draw_wallet(surface)

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

    def _draw_wallet(self, surface: pygame.Surface) -> None:
        """The wallet as the server last said it, top right: online only (offline and desktop have none)."""
        net = self.ctx.net
        if not net or net.coins is None:
            return
        label = f"{net.coins:,}".replace(",", ".")  # 46.900
        rect = pygame.Rect(0, 20, 68 + text(label, 30).get_width(), 44)
        rect.right = WIDTH - 24
        panel(surface, rect, alpha=190, radius=22)
        coin = self.ctx.assets.frame("coin")
        surface.blit(coin, coin.get_rect(midleft=(rect.x + 6, rect.centery)))
        blit_text(
            surface, label, 30, (rect.right - 18, rect.centery), ACCENT, anchor="midright", shadow=False
        )

    def _draw_footer(self, surface: pygame.Surface) -> None:
        save, mode = self.ctx.save, self.ctx.mode
        chips = [
            f"Carro: {CARS[save.skin][0]}",
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
