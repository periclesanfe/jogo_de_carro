"""Skin picker: an endless carousel of the six cars on a turntable."""

import math

import pygame

from ..input import Action
from ..settings import ACCENT, HEIGHT, MUTED, SKIN_NAMES, SKINS, WHITE, WIDTH
from ..tween import approach
from ..ui import blit_text, glow, outlined, panel
from .base import Context, MenuScene, Transition, menu_hint

CENTER = (WIDTH // 2, 330)
ARROWS = (pygame.Rect(0, 0, 48, 48), pygame.Rect(0, 0, 48, 48))
ARROWS[0].center = (CENTER[0] - 172, CENTER[1])
ARROWS[1].center = (CENTER[0] + 172, CENTER[1])
DISC_R = 135


def slot_x(d: float) -> float:
    """Horizontal position of a car ``d`` slots away from the centre (wider gap next to the centre)."""
    a = abs(d)
    offset = 250 * a if a <= 1 else 250 + 175 * (a - 1)
    return CENTER[0] + math.copysign(offset, d)


class GarageScene(MenuScene):
    dim, blur = 70, True

    def __init__(self, ctx: Context) -> None:
        super().__init__(ctx)
        self.target = SKINS.index(ctx.save.skin)  # unbounded; the skin is target % len(SKINS)
        self.pos = float(self.target)
        self.t = 0.0

    @property
    def skin(self) -> str:
        return SKINS[self.target % len(SKINS)]

    def _move(self, step: int) -> None:
        self.target += step
        self.ctx.audio.play("ui_move", 0.6)

    def _leave(self, confirm: bool) -> None:
        from .title import TitleScene

        if confirm:
            self.ctx.save.skin = self.skin
            self.ctx.persist()
            self.ctx.audio.play("ui_select")
        else:
            self.ctx.audio.play("ui_back")
        self.ctx.scenes.switch(TitleScene(self.ctx, focus=1), Transition.SLIDE_RIGHT)

    def handle(self, action: Action | None, event: pygame.Event) -> None:
        if action is Action.LEFT:
            self._move(-1)
        elif action is Action.RIGHT:
            self._move(1)
        elif action is Action.CONFIRM:
            self._leave(confirm=True)
        elif action is Action.BACK:
            self._leave(confirm=False)
        elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if ARROWS[0].collidepoint(event.pos):
                self._move(-1)
            elif ARROWS[1].collidepoint(event.pos):
                self._move(1)
            elif abs(event.pos[0] - CENTER[0]) < 80 and abs(event.pos[1] - CENTER[1]) < 130:
                self._leave(confirm=True)
            elif abs(event.pos[1] - CENTER[1]) < 120:
                self._move(-1 if event.pos[0] < CENTER[0] else 1)

    def update(self, dt: float) -> None:
        super().update(dt)
        self.t += dt
        self.pos = approach(self.pos, self.target, 12.0, dt)

    def draw_ui(self, surface: pygame.Surface) -> None:
        heading = outlined("GARAGEM", 80, WHITE, width=4)
        surface.blit(heading, heading.get_rect(center=(WIDTH // 2, 74)))
        blit_text(surface, "Escolha o seu carro", 28, (WIDTH // 2, 126), MUTED)

        self._draw_turntable(surface)
        for rect, direction in zip(ARROWS, (-1, 1), strict=True):  # under the cars that slide past them
            panel(surface, rect, alpha=210, radius=24)
            cx, cy = rect.center
            pts = [(cx + 8 * direction, cy), (cx - 6 * direction, cy - 11), (cx - 6 * direction, cy + 11)]
            pygame.draw.polygon(surface, WHITE, pts)

        base = math.floor(self.pos)
        slots = sorted(range(base - 3, base + 5), key=lambda k: -abs(k - self.pos))  # far cars first
        for k in slots:
            self._draw_car(surface, k)

        name = outlined(SKIN_NAMES[self.skin].upper(), 72, ACCENT, width=4)
        surface.blit(name, name.get_rect(center=(WIDTH // 2, 548)))
        best = self.ctx.save.best_by_skin.get(self.skin, 0)
        current = " · SELECIONADO" if self.skin == self.ctx.save.skin else ""
        blit_text(surface, f"Recorde com este carro: {best}{current}", 28, (WIDTH // 2, 600), WHITE)
        blit_text(surface, menu_hint(self.ctx), 24, (WIDTH // 2, HEIGHT - 40), MUTED)

    def _draw_turntable(self, surface: pygame.Surface) -> None:
        """Seen from above, like the cars: a dark disc with a slowly turning ring of ticks."""
        halo = glow(DISC_R + 60, ACCENT, 45)
        surface.blit(halo, halo.get_rect(center=CENTER))
        pygame.draw.circle(surface, (14, 16, 28), CENTER, DISC_R)
        pygame.draw.circle(surface, (44, 48, 70), CENTER, DISC_R - 16, 2)
        for i in range(36):
            a = self.t * 0.5 + i * math.tau / 36
            c, s = math.cos(a), math.sin(a)
            r0, r1 = DISC_R - 12, DISC_R - 4
            color = ACCENT if i % 3 == 0 else (120, 104, 60)
            pygame.draw.line(
                surface,
                color,
                (CENTER[0] + c * r0, CENTER[1] + s * r0),
                (CENTER[0] + c * r1, CENTER[1] + s * r1),
                2,
            )
        pygame.draw.circle(surface, ACCENT, CENTER, DISC_R, 3)

    def _draw_car(self, surface: pygame.Surface, k: int) -> None:
        d = k - self.pos
        if abs(d) > 2.6:
            return
        skin = SKINS[k % len(SKINS)]
        native = self.ctx.assets.native(f"car_{skin}")
        frame = native[int(self.t * 6) % len(native)] if abs(d) < 0.5 else native[0]
        scale = max(3.0, 6.0 - 2.0 * abs(d))  # whole numbers at rest: 6x in the middle, 4x and 3x beside
        img = pygame.transform.scale_by(frame, math.ceil(scale))
        if scale % 1:  # sliding: shrink a whole-pixel render smoothly, nearest would give uneven columns
            img = pygame.transform.smoothscale_by(img, scale / math.ceil(scale))
        bob = math.sin(self.t * 2.5) * 4 * max(0.0, 1 - abs(d))
        center = (round(slot_x(d)), round(CENTER[1] + bob + 18 * min(1, abs(d))))
        if abs(d) < 0.5:
            shadow = pygame.mask.from_surface(img).to_surface(
                setcolor=(0, 0, 0, 110), unsetcolor=(0, 0, 0, 0)
            )
            surface.blit(shadow, shadow.get_rect(center=(center[0] + 10, center[1] + 14)))
        img.set_alpha(round(255 * max(0.0, 1 - 0.45 * abs(d))))
        surface.blit(img, img.get_rect(center=center))
