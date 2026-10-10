"""Static road hazards (stone, pothole, cone) and the rolling trunk."""

import math
from dataclasses import dataclass, field

import pygame

from ..assets import Assets
from ..settings import LANE_CENTERS, Kind
from ..tween import clamp, in_out_cubic, lerp

SHADOW_OFFSET = (6, 8)
OBSTACLE_HITBOX = (0.9, 0.92)
TRUNK_ROLL = (60.0, 560.0)  # the trunk rolls between these distances below its spawn point


@dataclass
class Obstacle:
    assets: Assets
    kind: Kind
    sprite: str
    lane: int
    x: float
    y: float
    spawn_y: float = 0.0
    min_gap: float = math.inf  # closest horizontal distance to the player while side by side
    dodged: bool = False  # the player steered while side by side (a near miss needs it)
    passed: bool = False
    flat: bool = False  # drawn under cars, no shadow
    anim: float = 0.0
    _mask: pygame.Mask | None = field(default=None, repr=False)

    def update(self, dt: float, speed: float) -> None:
        self.y += speed * dt

    @property
    def frame(self) -> pygame.Surface:
        return self.assets.frame(self.sprite, int(self.anim))

    @property
    def rect(self) -> pygame.Rect:
        return self.frame.get_rect(center=(round(self.x), round(self.y)))

    @property
    def mask(self) -> pygame.Mask:
        if self._mask is None:
            if self.kind is Kind.POTHOLE:  # only the hole itself hurts, not the cracked rim
                w, h = self.frame.get_size()
                hole = pygame.Surface((w, h), pygame.SRCALPHA)
                pygame.draw.ellipse(
                    hole, (0, 0, 0), pygame.Rect(0, 0, w * 0.5, h * 0.5).move(w * 0.25, h * 0.25)
                )
                self._mask = pygame.mask.from_surface(hole)
            else:
                self._mask = self.assets.mask(self.sprite, 0, OBSTACLE_HITBOX)
        return self._mask

    @property
    def body(self) -> pygame.Rect:
        return self.assets.bounds(self.sprite).move(self.rect.topleft)

    def draw(self, surface: pygame.Surface, offset: tuple[float, float] = (0, 0)) -> None:
        x, y = self.x + offset[0], self.y + offset[1]
        if not self.flat:
            shadow = self.assets.shadow(self.sprite, int(self.anim) % len(self.assets.frames(self.sprite)))
            surface.blit(shadow, shadow.get_rect(center=(x + SHADOW_OFFSET[0], y + SHADOW_OFFSET[1])))
        img = self.frame
        surface.blit(img, img.get_rect(center=(round(x), round(y))))


@dataclass
class Trunk(Obstacle):
    to_lane: int = 0

    def update(self, dt: float, speed: float) -> None:
        old_x = self.x
        self.y += speed * dt
        k = clamp((self.y - self.spawn_y - TRUNK_ROLL[0]) / (TRUNK_ROLL[1] - TRUNK_ROLL[0]), 0.0, 1.0)
        self.x = lerp(LANE_CENTERS[self.lane], LANE_CENTERS[self.to_lane], in_out_cubic(k))
        # one frame per ~9 px rolled; reversed when rolling left
        self.anim = (self.anim + (self.x - old_x) / 9.0) % 4
