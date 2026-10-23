"""The player's car: tweened lane changes with tilt, smooth vertical control, powers and crash spin."""

import math
from dataclasses import dataclass, field
from functools import lru_cache

import pygame

from ..assets import Assets
from ..particles import LINE
from ..settings import (
    FLAME,
    GOLD,
    HITBOX_SHRINK,
    LANE_CENTERS,
    LANE_CHANGE_TIME,
    LANES,
    LAVENDER,
    PLAYER_MAX_VY,
    PLAYER_VY_RESPONSE,
    PLAYER_Y,
    PLAYER_Y_MAX,
    PLAYER_Y_MIN,
    POWERS,
    PROTECT,
    START_LANE,
    TILT_DEG,
    WHITE,
    Item,
)
from ..tween import approach, clamp, lerp, out_cubic
from ..ui import glow

SHADOW_OFFSET = (7, 10)
GRACE = 0.9  # seconds of blinking invulnerability after a hit was saved or a protecting power ran out


@lru_cache(maxsize=64)
def ghostly(img: pygame.Surface) -> pygame.Surface:
    """FANTASMA's car: a lavender-washed, see-through copy of a rotated sprite, cached and shared as it is."""
    img = img.copy()
    img.fill((70, 50, 110), special_flags=pygame.BLEND_RGB_ADD)
    img.set_alpha(160)
    return img


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
    power: Item | None = None  # the one power on (POWERS), for power_t more real seconds
    power_t: float = 0.0
    lives: int = 0  # an extra life (VIDA EXTRA): the next hit only breaks it
    grace: float = 0.0  # brief invulnerability (GRACE)
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
        self.grace = max(0.0, self.grace - dt)
        self.power_t = max(0.0, self.power_t - dt)
        if self.power and not self.power_t:
            if self.power in PROTECT:
                self.grace = GRACE
            self.power = None
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
        self.crashed, self.power, self.power_t = True, None, 0.0
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
        ghost = self.power is Item.GHOST
        if not ghost:  # a ghost casts no shadow
            shadow = self.assets.shadow(self.sprite, frame)
            if round(angle) % 360:
                shadow = pygame.transform.rotate(shadow, round(angle))
            surface.blit(shadow, shadow.get_rect(center=(cx + SHADOW_OFFSET[0], cy + SHADOW_OFFSET[1])))
        if self.grace > 0 and self.power not in PROTECT and int(self.clock * 20) % 2:
            return  # flicker while invulnerable
        if ghost:  # a lavender-washed, see-through car in a glow
            halo = glow(90, LAVENDER, 60)
            surface.blit(halo, halo.get_rect(center=(round(cx), round(cy))))
            img = ghostly(img)
        elif self.power is Item.TURBO:
            self._draw_turbo(surface, cx, cy)
        surface.blit(img, img.get_rect(center=(round(cx), round(cy))))
        if self.power is Item.SHIELD:
            self._draw_halo(surface, cx, cy, POWERS[Item.SHIELD].colour)
        elif self.power is Item.STAR:  # the classic invincibility flash: no yellow shield on a yellow car
            self._draw_halo(surface, cx, cy, (GOLD, WHITE, FLAME)[int(self.clock * 12) % 3])

    def _draw_turbo(self, surface: pygame.Surface, cx: float, cy: float) -> None:
        """Streaks rushing past beside the car and a flame from both exhaust pipes, from the clock alone."""
        n = self.clock * 30  # a streak every 1/30 s, 0.4 s from 260 px ahead down to the car
        for k in range(int(n) - 11, int(n) + 1):
            life = (n - k) / 12
            x = cx + (1 if k % 2 else -1) * (40 + k * 7 % 21)
            LINE.set_alpha(round((60 + k * 13 % 50) * min(1.0, 2 - 2 * life)))
            surface.blit(LINE, (3 * round(x / 3), cy - 260 + 260 * life), (0, 0, 3, 50 + k * 17 % 60))
        for dx in (-14, 14):  # flickering at 30 Hz, each pipe out of step with the other
            tip = cy + 70 + 6 * ((int(self.clock * 30) + dx) % 3)
            pygame.draw.line(surface, FLAME, (cx + dx, cy + 56), (cx + dx, tip), 5)
            pygame.draw.line(surface, (255, 200, 80), (cx + dx, cy + 56), (cx + dx, tip - 8), 3)

    def _draw_halo(self, surface: pygame.Surface, cx: float, cy: float, colour: tuple[int, int, int]) -> None:
        if self.power_t < 2.0 and int(self.clock * 8) % 2:
            return  # blink when about to expire
        pulse = 0.5 + 0.5 * math.sin(self.clock * 6)
        halo = glow(90, colour, round(70 + 50 * pulse))
        surface.blit(halo, halo.get_rect(center=(round(cx), round(cy))))
        ring = pygame.Rect(0, 0, 104 + 6 * pulse, 148 + 6 * pulse)
        ring.center = (round(cx), round(cy))
        pygame.draw.ellipse(surface, colour, ring, 3)
