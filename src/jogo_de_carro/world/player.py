"""The player's car: tweened lane changes with tilt, smooth vertical control, shield and crash spin."""

import math
from dataclasses import dataclass, field

import pygame

from ..assets import Assets
from ..settings import (
    CYAN,
    HITBOX_SHRINK,
    LANE_CENTERS,
    LANE_CHANGE_TIME,
    LANES,
    PLAYER_MAX_VY,
    PLAYER_VY_RESPONSE,
    PLAYER_Y,
    PLAYER_Y_MAX,
    PLAYER_Y_MIN,
    START_LANE,
    TILT_DEG,
)
from ..tween import approach, clamp, lerp, out_cubic
from ..ui import glow

SHADOW_OFFSET = (7, 10)


@dataclass
class Player:
    assets: Assets
    skin: str
    lane: int = START_LANE
    x: float = float(LANE_CENTERS[START_LANE])
    y: float = float(PLAYER_Y)
    vy: float = 0.0
    tilt: float = 0.0
    spin: float = 0.0  # current crash rotation (deg)
    spin_speed: float = 0.0
    shield: float = 0.0  # seconds of shield left
    grace: float = 0.0  # brief invulnerability after the shield breaks
    crashed: bool = False
    bounded: bool = True  # False lets the victory lap drive off the screen
    anim: float = 0.0
    clock: float = 0.0
    steer_age: float = math.inf  # seconds since the last lane change started
    _from_x: float = field(default=float(LANE_CENTERS[START_LANE]), repr=False)
    _lane_t: float = field(default=1.0, repr=False)

    @property
    def sprite(self) -> str:
        return f"car_{self.skin}"

    @property
    def changing_lane(self) -> bool:
        return self._lane_t < 1.0

    def steer(self, direction: int) -> bool:
        """Start a lane change; returns False when already at the road edge."""
        target = self.lane + direction
        if self.crashed or not 0 <= target < LANES:
            return False
        self.lane = target
        self._from_x, self._lane_t = self.x, 0.0
        self.tilt = -TILT_DEG * direction
        self.steer_age = 0.0
        return True

    def update(self, dt: float, vertical: float, speed: float) -> None:
        self.clock += dt
        self.steer_age += dt
        if self._lane_t < 1.0:
            self._lane_t = min(1.0, self._lane_t + dt / LANE_CHANGE_TIME)
            self.x = lerp(self._from_x, LANE_CENTERS[self.lane], out_cubic(self._lane_t))
        self.tilt = approach(self.tilt, 0.0, 18.0, dt)  # settles with the lane-change tween
        self.shield = max(0.0, self.shield - dt)
        self.grace = max(0.0, self.grace - dt)
        if self.crashed:
            self.spin += self.spin_speed * dt
            self.spin_speed = approach(self.spin_speed, 0.0, 2.2, dt)
            self.vy = approach(self.vy, 0.0, 4.0, dt)
        else:
            self.vy = approach(self.vy, vertical * PLAYER_MAX_VY, PLAYER_VY_RESPONSE, dt)
            self.anim += dt * speed / 30
        self.y += self.vy * dt
        if self.bounded and not self.crashed and not PLAYER_Y_MIN <= self.y <= PLAYER_Y_MAX:
            self.y = clamp(self.y, PLAYER_Y_MIN, PLAYER_Y_MAX)
            self.vy = 0.0

    def crash(self, direction: float) -> None:
        self.crashed = True
        self.spin_speed = 720.0 * (1 if direction >= 0 else -1)
        self.vy = 160.0

    # --- geometry ------------------------------------------------------------------------------------

    @property
    def rect(self) -> pygame.Rect:
        return self.assets.frame(self.sprite).get_rect(center=(round(self.x), round(self.y)))

    @property
    def mask(self) -> pygame.Mask:
        return self.assets.mask(self.sprite, 0, HITBOX_SHRINK)

    @property
    def body(self) -> pygame.Rect:
        """Visible car body (used for near-miss distances)."""
        return self.assets.bounds(self.sprite).move(self.rect.topleft)

    # --- drawing -------------------------------------------------------------------------------------

    def draw(self, surface: pygame.Surface, offset: tuple[float, float] = (0, 0)) -> None:
        frame = int(self.anim) % 2
        angle = self.tilt + self.spin
        if self.spin:  # 5-degree steps keep the cache of rotated sprites small
            angle = 5 * round(angle / 5)
        img = self.assets.rotated(self.sprite, frame, angle)
        cx, cy = self.x + offset[0], self.y + offset[1]
        shadow = self.assets.shadow(self.sprite, frame)
        if round(angle) % 360:
            shadow = pygame.transform.rotate(shadow, round(angle))
        surface.blit(shadow, shadow.get_rect(center=(cx + SHADOW_OFFSET[0], cy + SHADOW_OFFSET[1])))
        if self.grace > 0 and int(self.clock * 20) % 2:
            return  # flicker while invulnerable
        surface.blit(img, img.get_rect(center=(round(cx), round(cy))))
        if self.shield > 0:
            self._draw_shield(surface, cx, cy)

    def _draw_shield(self, surface: pygame.Surface, cx: float, cy: float) -> None:
        if self.shield < 2.0 and int(self.clock * 8) % 2:
            return  # blink when about to expire
        pulse = 0.5 + 0.5 * math.sin(self.clock * 6)
        halo = glow(90, CYAN, round(70 + 50 * pulse))
        surface.blit(halo, halo.get_rect(center=(round(cx), round(cy))))
        ring = pygame.Rect(0, 0, 104 + 6 * pulse, 148 + 6 * pulse)
        ring.center = (round(cx), round(cy))
        pygame.draw.ellipse(surface, CYAN, ring, 3)
