"""Pause overlay: Continuar / Reiniciar / Menu."""

from collections.abc import Callable

import pygame

from ..input import Action
from ..settings import HEIGHT, MUTED, WHITE, WIDTH
from ..tween import out_cubic
from ..ui import Menu, blit_text, outlined, panel
from .base import Context, Scene, Transition


def blurred(frame: pygame.Surface) -> pygame.Surface:
    """Frosted-glass backdrop: blurred, a little desaturated and darkened (multiply keeps the hues)."""
    out = pygame.transform.box_blur(pygame.transform.smoothscale_by(frame, 0.5), 3)
    out = pygame.transform.smoothscale(out, frame.get_size())
    gray = pygame.transform.grayscale(out)
    gray.set_alpha(110)
    out.blit(gray, (0, 0))
    out.fill((150, 154, 176), special_flags=pygame.BLEND_RGB_MULT)
    return out


class PauseScene(Scene):
    def __init__(self, ctx: Context, frame: pygame.Surface, again: Callable[[], Scene]) -> None:
        super().__init__(ctx)
        self.frame = frame
        self.again = again  # REINICIAR: a fresh race of the same kind
        self.background = blurred(frame)
        self.menu = Menu(["CONTINUAR", "REINICIAR", "MENU"], (WIDTH // 2, HEIGHT // 2 + 50), ctx.audio)
        self.t = 0.0

    def enter(self) -> None:
        self.ctx.audio.pause_music(True)

    def handle(self, action: Action | None, event: pygame.Event) -> None:
        if action in (Action.BACK, Action.PAUSE):
            self._resume()
            return
        choice = self.menu.handle(action, event)
        if choice is None:
            return
        self.ctx.audio.play("ui_select")
        if choice == 0:
            self._resume()
        elif choice == 1:
            self.ctx.scenes.switch(self.again(), Transition.FADE)
        else:
            from .title import TitleScene

            self.ctx.scenes.switch(TitleScene(self.ctx), Transition.FADE)

    def _resume(self) -> None:
        self.ctx.scenes.pop()

    def update(self, dt: float) -> None:
        self.t += dt
        self.menu.update(dt)

    def draw(self, surface: pygame.Surface) -> None:
        k = out_cubic(min(1.0, self.t / 0.2))
        surface.blit(self.frame, (0, 0))
        self.background.set_alpha(round(255 * k))
        surface.blit(self.background, (0, 0))
        box = pygame.Rect(0, 0, 460, 400)
        box.center = (WIDTH // 2, HEIGHT // 2 + round(30 * (1 - k)))
        panel(surface, box, alpha=round(225 * k), radius=22, border=(60, 64, 92))
        title = outlined("PAUSADO", 76, WHITE)
        surface.blit(title, title.get_rect(center=(WIDTH // 2, box.y + 64)))
        self.menu.draw(surface)
        back = "B" if self.ctx.input.using_pad else "ESC"
        blit_text(surface, f"{back} para voltar à corrida", 24, (WIDTH // 2, box.bottom + 30), MUTED)
