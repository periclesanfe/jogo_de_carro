"""Mode picker: one card per difficulty with its goal, intensity and best results."""

import pygame

from ..input import Action
from ..settings import ACCENT, HEIGHT, MODES, MUTED, PANEL, WHITE, WIDTH, Difficulty
from ..tween import approach
from ..ui import blit_text, clock_text, glow, mix, outlined, panel
from ..world.difficulty import blocked_cap
from .base import Context, MenuScene, Transition, menu_hint

CARD = (250, 400)
SPACING = 282
CARD_Y = 380


def card_rect(i: int, lift: float = 0.0) -> pygame.Rect:
    rect = pygame.Rect(0, 0, *CARD)
    rect.center = (round(WIDTH / 2 + (i - 1.5) * SPACING), round(CARD_Y - lift))
    return rect


def _speed_bars(mode: Difficulty) -> int:
    return max(1, min(5, round((mode.max_speed - 400) / 140) + 1))


class DifficultyScene(MenuScene):
    dim, blur = 30, True

    def __init__(self, ctx: Context) -> None:
        super().__init__(ctx)
        self.index = next(i for i, m in enumerate(MODES) if m.key == ctx.save.mode)
        self.focus = [1.0 if i == self.index else 0.0 for i in range(len(MODES))]

    def _leave(self, confirm: bool) -> None:
        from .title import TitleScene

        if confirm:
            self.ctx.save.mode = MODES[self.index].key
            self.ctx.persist()
            self.ctx.audio.play("ui_select")
        else:
            self.ctx.audio.play("ui_back")
        self.ctx.scenes.switch(TitleScene(self.ctx, focus=2), Transition.SLIDE_RIGHT)

    def _select(self, i: int) -> None:
        if i != self.index:
            self.index = i
            self.ctx.audio.play("ui_move", 0.6)

    def handle(self, action: Action | None, event: pygame.Event) -> None:
        if action is Action.LEFT:
            self._select((self.index - 1) % len(MODES))
        elif action is Action.RIGHT:
            self._select((self.index + 1) % len(MODES))
        elif action is Action.CONFIRM:
            self._leave(confirm=True)
        elif action is Action.BACK:
            self._leave(confirm=False)
        elif event.type in (pygame.MOUSEMOTION, pygame.MOUSEBUTTONDOWN):
            for i in range(len(MODES)):
                if card_rect(i).collidepoint(event.pos):
                    self._select(i)
                    if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                        self._leave(confirm=True)

    def update(self, dt: float) -> None:
        super().update(dt)
        for i in range(len(MODES)):
            self.focus[i] = approach(self.focus[i], 1.0 if i == self.index else 0.0, 14.0, dt)

    def draw_ui(self, surface: pygame.Surface) -> None:
        heading = outlined("DIFICULDADE", 80, WHITE, width=4)
        surface.blit(heading, heading.get_rect(center=(WIDTH // 2, 74)))
        blit_text(surface, "Sobreviva até a meta para vencer", 28, (WIDTH // 2, 126), MUTED)
        for i, mode in enumerate(MODES):
            self._draw_card(surface, i, mode)
        blit_text(surface, menu_hint(self.ctx), 24, (WIDTH // 2, HEIGHT - 40), MUTED)

    def _draw_card(self, surface: pygame.Surface, i: int, mode: Difficulty) -> None:
        save = self.ctx.save
        k = self.focus[i]
        rect = card_rect(i, 18 * k)
        if k > 0.05:
            halo = glow(200, mode.color, 80 * k)
            surface.blit(
                pygame.transform.scale(halo, (rect.width + 120, rect.height + 120)), rect.inflate(120, 120)
            )
        tint = round(k * 8) / 8  # a few steps are enough, and keep the panel cache small
        panel(
            surface,
            rect,
            mix(PANEL, (34, 38, 58), tint),
            235,
            radius=18,
            border=mix((60, 64, 92), mode.color, tint),
        )
        header = pygame.Rect(rect.x, rect.y, rect.width, 74)
        pygame.draw.rect(surface, mode.color, header, border_top_left_radius=18, border_top_right_radius=18)
        name = outlined(mode.name.upper(), 46, WHITE, width=3)
        surface.blit(name, name.get_rect(center=header.center))
        if mode.key == save.mode:
            badge = pygame.Rect(0, 0, 76, 24)
            badge.center = (rect.centerx, header.bottom)
            pygame.draw.rect(surface, ACCENT, badge, border_radius=12)
            blit_text(surface, "ATUAL", 22, badge.center, (26, 28, 44), shadow=False)

        x, y = rect.x + 22, header.bottom + 26
        blit_text(surface, "META", 24, (x, y - 2), MUTED, anchor="topleft", shadow=False)
        goal = "SEM FIM" if mode.win_s is None else clock_text(mode.win_s)
        blit_text(surface, goal, 46, (x, y + 20), WHITE, anchor="topleft")
        self._bars(surface, "VELOCIDADE", _speed_bars(mode), 5, x, y + 80, mode.color)
        self._bars(surface, "OBSTÁCULOS", blocked_cap(mode, 1e9), 4, x, y + 130, mode.color)
        blit_text(surface, "RECORDE", 24, (x, y + 182), MUTED, anchor="topleft", shadow=False)
        blit_text(surface, f"{save.best.get(mode.key, 0)}", 40, (x, y + 204), ACCENT, anchor="topleft")
        best_time = save.best_time.get(mode.key)
        if best_time:
            blit_text(
                surface, clock_text(best_time), 26, (rect.right - 22, y + 214), WHITE, anchor="topright"
            )
        blit_text(surface, mode.description, 24, (rect.centerx, rect.bottom - 26), mix(MUTED, WHITE, k))

    @staticmethod
    def _bars(
        surface: pygame.Surface, label: str, n: int, total: int, x: int, y: int, color: tuple[int, int, int]
    ) -> None:
        blit_text(surface, label, 24, (x, y - 2), MUTED, anchor="topleft", shadow=False)
        for b in range(total):
            cell = pygame.Rect(x + b * 42, y + 22, 36, 12)
            pygame.draw.rect(surface, color if b < n else (52, 56, 80), cell, border_radius=4)
