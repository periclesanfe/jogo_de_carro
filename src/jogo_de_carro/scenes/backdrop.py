"""The endless demo drive shown behind the menus (attract mode)."""

import random

import pygame

from ..settings import CARS, HEIGHT, NORMAL, SKINS, WIDTH
from ..world.autopilot import autopilot
from ..world.world import World
from .base import Context


class Backdrop:
    def __init__(self, ctx: Context) -> None:
        self.world = World(ctx.assets, NORMAL, ctx.save.skin, random.Random(ctx.rng.random()), attract=True)
        self._buffer = pygame.Surface((WIDTH, HEIGHT))
        self._shade = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
        for y in range(HEIGHT):  # darker at the top (headings) and the bottom (footer text)
            alpha = round(150 - 60 * min(1.0, y / (HEIGHT * 0.6)) + 110 * max(0.0, (y - HEIGHT + 150) / 150))
            pygame.draw.line(self._shade, (10, 12, 28, alpha), (0, y), (WIDTH, y))

    @classmethod
    def shared(cls, ctx: Context) -> "Backdrop":
        if ctx.backdrop is None:
            ctx.backdrop = cls(ctx)
            for _ in range(240):  # warm up so traffic is already on screen
                ctx.backdrop.update(1 / 60)
        ctx.backdrop.world.player.skin = ctx.save.skin if ctx.save.skin in CARS else SKINS[0]
        return ctx.backdrop

    def update(self, dt: float) -> None:
        self.world.update(dt, autopilot(self.world))

    def draw(self, surface: pygame.Surface, extra_dim: int = 0, blur: bool = False) -> None:
        if blur:  # cheap depth-of-field: blur at quarter resolution, scale back up
            self.world.draw(self._buffer)
            small = pygame.transform.box_blur(pygame.transform.smoothscale(self._buffer, (320, 180)), 4)
            pygame.transform.smoothscale(small, (WIDTH, HEIGHT), surface)
        else:
            self.world.draw(surface)
        surface.blit(self._shade, (0, 0))
        if extra_dim:
            surface.fill((255 - 2 * extra_dim,) * 3, special_flags=pygame.BLEND_RGB_MULT)
