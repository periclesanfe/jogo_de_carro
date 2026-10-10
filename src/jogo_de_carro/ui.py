"""Text helpers, panels and a focusable button menu (keyboard, mouse and gamepad)."""

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from functools import lru_cache

import pygame
import pygame.freetype

from .audio import Audio
from .input import Action
from .settings import ACCENT, INK, PANEL, WHITE
from .tween import approach, lerp

Color = tuple[int, int, int]
SHADOW = (8, 9, 18)


LINE_SAMPLE = "ÂÉÍÓÚÃÕÇgjpqy()"  # the tallest accents and deepest descenders of the UI's strings


@lru_cache(maxsize=32)
def font(size: int) -> pygame.freetype.Font:
    """pygame's default font through FreeType: pygame.font's renderer opens gaps inside words ("GAR AGEM")."""
    pygame.freetype.init()  # idempotent
    f = pygame.freetype.Font(None, size * 0.6875)  # same visual size as pygame.font.Font(None, size)
    f.kerning = False
    f.pad = True
    return f


@lru_cache(maxsize=1024)
def text(s: str, size: int, color: Color = WHITE) -> pygame.Surface:
    """Text in a line box shared by every string of this size, so "FÁCIL" and "NORMAL" sit level."""
    f = font(size)
    img, rect = f.render(s, color)
    line = f.get_rect(LINE_SAMPLE)  # rect.y is the height above the baseline
    out = pygame.Surface((img.get_width(), line.height + 2), pygame.SRCALPHA)
    out.blit(img, (0, line.y - rect.y))
    return out


@lru_cache(maxsize=256)
def outlined(s: str, size: int, color: Color = WHITE, outline: Color = INK, width: int = 3) -> pygame.Surface:
    """Text with a solid outline and a drop shadow, the house style for headings."""
    inner = text(s, size, color)
    edge = text(s, size, outline)
    shadow = text(s, size, SHADOW)
    w, h = inner.get_width() + width * 2, inner.get_height() + width * 2 + width
    out = pygame.Surface((w, h), pygame.SRCALPHA)
    shadow.set_alpha(160)
    out.blit(shadow, (width, width * 2))
    for dx in range(-width, width + 1):
        for dy in range(-width, width + 1):
            if dx * dx + dy * dy <= width * width:
                out.blit(edge, (width + dx, width + dy))
    out.blit(inner, (width, width))
    return out


@lru_cache(maxsize=32)
def gradient_text(s: str, size: int, top: Color, bottom: Color, outline: Color = INK) -> pygame.Surface:
    """Outlined heading whose fill fades vertically from ``top`` to ``bottom``."""
    fill = text(s, size, WHITE).copy()
    h = fill.get_height()
    ramp = pygame.Surface((1, h))
    for y in range(h):
        k = y / max(1, h - 1)
        ramp.set_at((0, y), [round(lerp(a, b, k)) for a, b in zip(top, bottom, strict=True)])
    fill.blit(pygame.transform.scale(ramp, fill.get_size()), (0, 0), special_flags=pygame.BLEND_RGB_MULT)
    width = max(3, size // 18)
    out = outlined(s, size, WHITE, outline, width).copy()
    out.blit(fill, (width, width))
    return out


def blit_text(
    surface: pygame.Surface,
    s: str,
    size: int,
    pos: tuple[float, float],
    color: Color = WHITE,
    anchor: str = "center",
    shadow: bool = True,
    alpha: int = 255,
) -> pygame.Rect:
    img = text(s, size, color)
    rect = img.get_rect()  # every line of a size shares one box, so any anchor keeps the baselines level
    setattr(rect, anchor, (round(pos[0]), round(pos[1])))
    if shadow:
        sh = text(s, size, SHADOW)
        sh.set_alpha(alpha * 0.6)
        surface.blit(sh, rect.move(0, max(2, size // 16)))
    img.set_alpha(alpha)
    surface.blit(img, rect)
    img.set_alpha(255)
    return rect


def blit_scaled(
    surface: pygame.Surface, img: pygame.Surface, center: tuple[float, float], scale: float, alpha: int = 255
) -> None:
    if scale <= 0.01 or alpha <= 0:
        return
    if abs(scale - 1) > 0.01:
        img = pygame.transform.smoothscale_by(img, scale)
    img.set_alpha(alpha)
    surface.blit(img, img.get_rect(center=(round(center[0]), round(center[1]))))
    img.set_alpha(255)


def blit_pop(
    surface: pygame.Surface,
    label: str,
    size: int,
    color: Color,
    center: tuple[float, float],
    scale: float,
    alpha: int = 255,
    width: int = 3,
    peak: float = 1.1,
) -> None:
    """Outlined text that pops up to ``peak`` x without blur: above 1x it shrinks a peak-size render."""
    if scale > 1.01:
        img = outlined(label, round(size * peak), color, width=round(width * peak))
        scale /= peak
    else:
        img = outlined(label, size, color, width=width)
    blit_scaled(surface, img, center, scale, alpha)


@lru_cache(maxsize=1)
def _layer(size: tuple[int, int]) -> pygame.Surface:
    return pygame.Surface(size, pygame.SRCALPHA)


def faded(
    surface: pygame.Surface,
    alpha: float,
    draw: Callable[[pygame.Surface], None],
    offset: tuple[int, int] = (0, 0),
) -> None:
    """Fade (and shift) a whole group: ``draw`` paints onto a clear layer that is blitted with ``alpha``."""
    if alpha >= 255 and offset == (0, 0):
        draw(surface)
        return
    if alpha <= 0:
        return
    layer = _layer(surface.get_size())
    layer.fill((0, 0, 0, 0))
    draw(layer)
    layer.set_alpha(round(min(alpha, 255)))
    surface.blit(layer, offset)


@lru_cache(maxsize=128)
def _panel_surface(
    size: tuple[int, int], color: Color, alpha: int, radius: int, border: Color | None
) -> pygame.Surface:
    surf = pygame.Surface(size, pygame.SRCALPHA)
    pygame.draw.rect(surf, (*color, alpha), surf.get_rect(), border_radius=radius)
    if border:
        pygame.draw.rect(surf, (*border, 255), surf.get_rect(), width=2, border_radius=radius)
    return surf


def panel(
    surface: pygame.Surface,
    rect: pygame.Rect,
    color: Color = PANEL,
    alpha: float = 215,
    radius: int = 14,
    border: Color | None = None,
) -> None:
    surface.blit(_panel_surface(rect.size, color, _level(alpha), radius, border), rect)


def _level(alpha: float) -> int:
    """Snap an (often animated) alpha to 18 levels, so the surface caches stay small."""
    return min(255, 15 * round(alpha / 15))


def glow(radius: int, color: Color, strength: float = 120) -> pygame.Surface:
    """Soft radial glow (alpha falls off quadratically). Cached and shared: undo any set_alpha you do."""
    return _glow(radius, color, _level(strength))


@lru_cache(maxsize=512)
def _glow(radius: int, color: Color, strength: int) -> pygame.Surface:
    surf = pygame.Surface((radius * 2, radius * 2), pygame.SRCALPHA)
    for r in range(radius, 0, -2):
        a = strength * (1 - r / radius) ** 2
        pygame.draw.circle(surf, (*color, round(a)), (radius, radius), r)
    return surf


def clock_text(seconds: float) -> str:
    """mm:ss, the original game's score format."""
    s = int(seconds)
    return f"{s // 60:02d}:{s % 60:02d}"


def mix(a: Color, b: Color, k: float) -> Color:
    return (round(lerp(a[0], b[0], k)), round(lerp(a[1], b[1], k)), round(lerp(a[2], b[2], k)))


@dataclass
class Button:
    label: str
    rect: pygame.Rect
    size: int = 34
    focus: float = 0.0  # animated 0..1

    def update(self, dt: float, focused: bool) -> None:
        self.focus = approach(self.focus, 1.0 if focused else 0.0, 16.0, dt)

    def draw(self, surface: pygame.Surface) -> None:
        k = self.focus
        rect = self.rect.inflate(round(14 * k), round(6 * k))
        radius = rect.height // 2
        if k > 0.05:
            g = glow(self.rect.width // 2 + 30, ACCENT, 60 * k)
            surface.blit(pygame.transform.scale(g, (rect.width + 60, rect.height + 50)), rect.inflate(60, 50))
        panel(surface, rect, PANEL, 225, radius, border=(60, 64, 92))
        focused = k > 0.5
        if k > 0.02:  # a solid accent pill fades in over the dark one (mixing the RGB looks muddy)
            panel(surface, rect, ACCENT, 255 * k, radius, border=INK if focused else None)
        blit_text(surface, self.label, self.size, rect.center, INK if focused else WHITE, shadow=not focused)


@dataclass
class Menu:
    """Vertical list of buttons; returns the chosen index from ``handle``."""

    labels: Sequence[str]
    center: tuple[int, int]
    audio: Audio | None = None
    size: tuple[int, int] = (360, 56)
    gap: int = 14
    index: int = 0
    horizontal: bool = False
    buttons: list[Button] = field(init=False)

    def __post_init__(self) -> None:
        w, h = self.size
        n = len(self.labels)
        if self.horizontal:
            left = self.center[0] - (n * (w + self.gap) - self.gap) // 2
            rects = [pygame.Rect(left + i * (w + self.gap), self.center[1] - h // 2, w, h) for i in range(n)]
        else:
            top = self.center[1] - (n * (h + self.gap) - self.gap) // 2
            rects = [pygame.Rect(self.center[0] - w // 2, top + i * (h + self.gap), w, h) for i in range(n)]
        self.buttons = [Button(label, rect) for label, rect in zip(self.labels, rects, strict=True)]

    def _move(self, step: int) -> None:
        self.index = (self.index + step) % len(self.buttons)
        if self.audio:
            self.audio.play("ui_move", 0.6)

    def handle(self, action: Action | None, event: pygame.Event) -> int | None:
        back, forward = (Action.LEFT, Action.RIGHT) if self.horizontal else (Action.UP, Action.DOWN)
        if action is back:
            self._move(-1)
        elif action is forward:
            self._move(1)
        elif action is Action.CONFIRM:
            return self.index
        elif event.type in (pygame.MOUSEMOTION, pygame.MOUSEBUTTONDOWN):
            for i, button in enumerate(self.buttons):
                if button.rect.collidepoint(event.pos):
                    if i != self.index:
                        self.index = i
                        if self.audio:
                            self.audio.play("ui_move", 0.4)
                    if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                        return i
        return None

    def update(self, dt: float) -> None:
        for i, button in enumerate(self.buttons):
            button.update(dt, i == self.index)

    def draw(self, surface: pygame.Surface) -> None:
        for button in self.buttons:
            button.draw(surface)
