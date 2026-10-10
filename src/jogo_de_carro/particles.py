"""Lightweight particle system: sparks, smoke, dust, confetti, debris and speed lines."""

import math
import random
from dataclasses import dataclass
from enum import Enum, auto

import pygame

from .settings import HEIGHT, WIDTH
from .ui import glow

Color = tuple[int, int, int]
MAX_PARTICLES = 700
CONFETTI_COLORS = (
    (255, 205, 60),
    (247, 118, 34),
    (65, 220, 240),
    (99, 199, 77),
    (240, 90, 160),
    (244, 244, 244),
)


LINE = pygame.Surface((3, 120))  # speed line: blitted in part, faded with set_alpha
LINE.fill((255, 255, 255))


class Style(Enum):
    SPARK = auto()  # bright streak along its velocity
    PUFF = auto()  # soft growing disc (smoke, dust, exhaust)
    CONFETTI = auto()  # tumbling paper rectangle
    SQUARE = auto()  # pixel debris / sparkle
    LINE = auto()  # speed line


@dataclass(slots=True)
class Particle:
    x: float
    y: float
    vx: float
    vy: float
    ttl: float
    size: float
    color: Color
    style: Style
    grow: float = 0.0
    drag: float = 0.0
    gravity: float = 0.0
    spin: float = 0.0
    angle: float = 0.0
    alpha: float = 255.0
    on_road: bool = True  # scrolls down with the world
    life: float = 0.0


class Particles:
    def __init__(self, rng: random.Random) -> None:
        self.rng = rng
        self.items: list[Particle] = []

    def add(self, p: Particle) -> None:
        if len(self.items) < MAX_PARTICLES:
            self.items.append(p)

    def clear(self) -> None:
        self.items.clear()

    def update(self, dt: float, scroll: float) -> None:
        alive = []
        for p in self.items:
            p.life += dt
            if p.life >= p.ttl:
                continue
            if p.drag:
                k = math.exp(-p.drag * dt)
                p.vx *= k
                p.vy *= k
            p.vy += p.gravity * dt
            p.x += p.vx * dt
            p.y += p.vy * dt + (scroll if p.on_road else 0.0)
            p.size = max(0.0, p.size + p.grow * dt)
            p.angle += p.spin * dt
            if -80 < p.y < HEIGHT + 80:
                alive.append(p)
        self.items = alive

    def draw(self, surface: pygame.Surface, offset: tuple[float, float] = (0, 0)) -> None:
        ox, oy = offset
        for p in self.items:
            fade = 1.0 - p.life / p.ttl
            x, y = p.x + ox, p.y + oy
            if p.style is Style.PUFF:
                r = max(1, round(p.size))
                img = glow(r, p.color, 255)
                img.set_alpha(round(p.alpha * fade))
                surface.blit(img, (x - r, y - r))
                img.set_alpha(255)
            elif p.style is Style.SPARK:
                length = 0.035 * fade
                end = (x - p.vx * length, y - p.vy * length)
                pygame.draw.line(surface, p.color, (x, y), end, max(1, round(p.size * fade)))
            elif p.style is Style.LINE:  # 3 px wide, on the pixel-art grid
                LINE.set_alpha(round(p.alpha * min(1.0, fade * 2)))
                surface.blit(LINE, (3 * round(x / 3), y), (0, 0, 3, round(p.size)))
            elif p.style is Style.SQUARE:
                s = max(1, round(p.size * (0.4 + 0.6 * fade)))
                surface.fill(p.color, (round(x) - s // 2, round(y) - s // 2, s, s))
            else:  # confetti: a rectangle tumbling in 3D, faked by squashing its width with cos(angle)
                w = p.size * abs(math.cos(p.angle)) + 1
                h = p.size * 1.6
                c, s = math.cos(p.angle * 0.7), math.sin(p.angle * 0.7)
                pts = [(x + dx * c - dy * s, y + dx * s + dy * c) for dx, dy in _corners(w, h)]
                pygame.draw.polygon(surface, p.color, pts)

    # --- emitters ------------------------------------------------------------------------------------

    def sparks(self, x: float, y: float, n: int = 30, speed: float = 520.0) -> None:
        r = self.rng
        for _ in range(n):
            a = r.uniform(0, math.tau)
            v = r.uniform(0.3, 1.0) * speed
            color = r.choice(((255, 240, 160), (255, 200, 60), (255, 140, 40)))
            self.add(
                Particle(
                    x,
                    y,
                    math.cos(a) * v,
                    math.sin(a) * v,
                    r.uniform(0.25, 0.6),
                    3,
                    color,
                    Style.SPARK,
                    drag=3.0,
                    gravity=300,
                )
            )

    def smoke(self, x: float, y: float, n: int = 12, dark: bool = True) -> None:
        r = self.rng
        for _ in range(n):
            shade = r.choice((42, 58)) if dark else r.choice((160, 186))
            self.add(
                Particle(
                    x + r.uniform(-20, 20),
                    y + r.uniform(-20, 20),
                    r.uniform(-40, 40),
                    r.uniform(-90, -20),
                    r.uniform(0.8, 1.6),
                    r.uniform(10, 18),
                    (shade,) * 3,
                    Style.PUFF,
                    grow=r.uniform(20, 40),
                    drag=1.2,
                    alpha=170,
                )
            )

    def dust(self, x: float, y: float, n: int = 6, color: Color = (200, 180, 140)) -> None:
        r = self.rng
        for _ in range(n):
            self.add(
                Particle(
                    x + r.uniform(-6, 6),
                    y,
                    r.uniform(-60, 60),
                    r.uniform(20, 80),
                    r.uniform(0.3, 0.6),
                    r.uniform(4, 7),
                    color,
                    Style.PUFF,
                    grow=18,
                    drag=4,
                    alpha=140,
                )
            )

    def exhaust(self, x: float, y: float) -> None:
        r = self.rng
        self.add(
            Particle(
                x + r.uniform(-2, 2),
                y,
                r.uniform(-12, 12),
                r.uniform(40, 90),
                r.uniform(0.25, 0.45),
                r.uniform(3, 5),
                (190, 190, 200),
                Style.PUFF,
                grow=14,
                drag=2,
                alpha=90,
            )
        )

    def burst(self, x: float, y: float, color: Color, n: int = 10, speed: float = 220.0) -> None:
        r = self.rng
        for _ in range(n):
            a = r.uniform(0, math.tau)
            v = r.uniform(0.4, 1.0) * speed
            self.add(
                Particle(
                    x,
                    y,
                    math.cos(a) * v,
                    math.sin(a) * v,
                    r.uniform(0.25, 0.55),
                    r.choice((3, 6)),
                    color,
                    Style.SQUARE,
                    drag=5,
                )
            )

    def debris(self, x: float, y: float, colors: tuple[Color, ...], n: int = 14) -> None:
        r = self.rng
        for _ in range(n):
            a = r.uniform(0, math.tau)
            v = r.uniform(120, 420)
            self.add(
                Particle(
                    x,
                    y,
                    math.cos(a) * v,
                    math.sin(a) * v,
                    r.uniform(0.5, 1.0),
                    r.choice((6, 9)),
                    r.choice(colors),
                    Style.SQUARE,
                    drag=3.5,
                )
            )

    def confetti(self, n: int = 120, x: float | None = None, y: float = -20.0) -> None:
        r = self.rng
        for _ in range(n):
            cx = r.uniform(0, WIDTH) if x is None else x
            self.add(
                Particle(
                    cx,
                    y + r.uniform(-60, 0),
                    r.uniform(-160, 160),
                    r.uniform(60, 260),
                    r.uniform(2.2, 4.0),
                    r.uniform(5, 9),
                    r.choice(CONFETTI_COLORS),
                    Style.CONFETTI,
                    drag=0.9,
                    gravity=160,
                    spin=r.uniform(-9, 9),
                    on_road=False,
                )
            )

    def cannon(self, x: float, y: float, direction: int, n: int = 70) -> None:
        """Confetti shot upwards from a corner; ``direction`` +1 aims right, -1 aims left."""
        r = self.rng
        for _ in range(n):
            a = math.radians(r.uniform(-80, -50))
            v = r.uniform(500, 900)
            self.add(
                Particle(
                    x,
                    y,
                    direction * math.cos(a) * v,
                    math.sin(a) * v,
                    r.uniform(2.0, 3.2),
                    r.uniform(5, 9),
                    r.choice(CONFETTI_COLORS),
                    Style.CONFETTI,
                    drag=1.6,
                    gravity=420,
                    spin=r.uniform(-12, 12),
                    on_road=False,
                )
            )

    def speed_line(self, x: float, speed: float) -> None:
        r = self.rng
        self.add(
            Particle(
                x,
                -60,
                0,
                speed * 1.6,
                0.5,
                r.uniform(40, 120),
                (255, 255, 255),
                Style.LINE,
                alpha=r.uniform(30, 60),
                on_road=False,
            )
        )


def _corners(w: float, h: float) -> tuple[tuple[float, float], ...]:
    return ((-w / 2, -h / 2), (w / 2, -h / 2), (w / 2, h / 2), (-w / 2, h / 2))
