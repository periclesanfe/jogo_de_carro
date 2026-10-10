"""Coins and the shield power-up."""

import math
from dataclasses import dataclass

import pygame

from ..assets import Assets
from ..settings import ACCENT, CYAN, Item
from ..ui import glow


@dataclass
class Pickup:
    assets: Assets
    item: Item
    x: float
    y: float
    anim: float = 0.0
    clock: float = 0.0

    def __post_init__(self) -> None:
        self.anim = (self.x + self.y) * 0.03  # neighbouring coins spin out of phase: a ripple, not a blink

    def update(self, dt: float, speed: float) -> None:
        self.y += speed * dt
        self.clock += dt
        self.anim += dt * (12 if self.item is Item.COIN else 6)

    @property
    def rect(self) -> pygame.Rect:
        return self.assets.frame(self.item.value).get_rect(center=(round(self.x), round(self.y)))

    def draw(self, surface: pygame.Surface, offset: tuple[float, float] = (0, 0)) -> None:
        bob = math.sin(self.clock * 5 + self.y * 0.02) * 3
        cx, cy = self.x + offset[0], self.y + offset[1] + bob
        is_coin = self.item is Item.COIN
        halo = glow(28 if is_coin else 46, ACCENT if is_coin else CYAN, 70 if is_coin else 110)
        surface.blit(halo, halo.get_rect(center=(round(cx), round(cy))))
        img = self.assets.frame(self.item.value, int(self.anim))
        surface.blit(img, img.get_rect(center=(round(cx), round(cy))))
