"""Traffic: cars, vans and trucks driving the same way, slower than you; some change lanes."""

from dataclasses import dataclass

import pygame

from ..settings import LANE_CENTERS
from ..tween import in_out_cubic, lerp
from .obstacles import SHADOW_OFFSET, Obstacle

BLINK_TIME = 0.8
MOVE_TIME = 0.6
TURN_TILT = 7.0


@dataclass
class Traffic(Obstacle):
    own_speed: float = 0.0
    to_lane: int | None = None
    turn_y: float = 0.0
    blink_time: float = BLINK_TIME
    phase: str = "cruise"  # cruise -> blink -> move -> cruise
    timer: float = 0.0
    tilt: float = 0.0

    @property
    def signalling(self) -> bool:
        return self.phase in ("blink", "move")

    def update(self, dt: float, speed: float) -> None:
        self.y += (speed - self.own_speed) * dt
        self.anim = (self.anim + dt * max(self.own_speed, 120.0) / 30) % 2
        if self.to_lane is None:
            return
        self.timer += dt
        if self.phase == "cruise" and self.y >= self.turn_y:
            self.phase, self.timer = "blink", 0.0
        elif self.phase == "blink" and self.timer >= self.blink_time:
            self.phase, self.timer = "move", 0.0
        elif self.phase == "move":
            k = min(1.0, self.timer / MOVE_TIME)
            self.x = lerp(LANE_CENTERS[self.lane], LANE_CENTERS[self.to_lane], in_out_cubic(k))
            direction = 1 if self.to_lane > self.lane else -1
            self.tilt = -TURN_TILT * direction * (1 - abs(2 * k - 1))
            if k >= 1.0:
                self.lane, self.to_lane, self.phase, self.tilt = self.to_lane, None, "cruise", 0.0

    def draw(self, surface: pygame.Surface, offset: tuple[float, float] = (0, 0)) -> None:
        x, y = self.x + offset[0], self.y + offset[1]
        frame = int(self.anim)
        shadow = self.assets.shadow(self.sprite, frame)
        surface.blit(shadow, shadow.get_rect(center=(x + SHADOW_OFFSET[0], y + SHADOW_OFFSET[1])))
        img = self.assets.rotated(self.sprite, frame, self.tilt)
        surface.blit(img, img.get_rect(center=(round(x), round(y))))
        if self.signalling and self.to_lane is not None:
            self._draw_blinkers(surface, x, y)

    def _draw_blinkers(self, surface: pygame.Surface, x: float, y: float) -> None:
        on = int(self.timer * 6) % 2 == 0
        light = self.assets.frame("blinker", 0 if on else 1)
        body = self.assets.bounds(self.sprite)
        side = 1 if self.to_lane > self.lane else -1
        bx = x + side * (body.width / 2 - 3)
        for by in (y - body.height / 2 + 9, y + body.height / 2 - 9):
            surface.blit(light, light.get_rect(center=(round(bx), round(by))))
