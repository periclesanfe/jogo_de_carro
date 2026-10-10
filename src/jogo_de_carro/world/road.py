"""Procedural scrolling road: grass verges, gravel shoulders, asphalt, lane dashes and roadside props."""

import math
import random
from dataclasses import dataclass

import pygame

from ..assets import Assets
from ..settings import HEIGHT, LANE_WIDTH, LANES, ROAD_LEFT, ROAD_RIGHT, SCALE, WIDTH

# The ground is painted on a native-resolution grid and scaled x3. Native column i covers screen
# x = 3*i - 2 .. 3*i, which puts the road edges (400, 880) and lane lines exactly on native pixels.
NATIVE_W, NATIVE_H = 428, 192
TILE_H = NATIVE_H * SCALE  # 576: the ground repeats every 576 px
X_SHIFT = -2


def _col(x: int) -> int:
    return (x - X_SHIFT) // SCALE


GRASS = (58, 134, 70)
GRASS_DARK = (42, 108, 62)
GRASS_LIGHT = (92, 170, 78)
GRASS_TIP = (130, 196, 92)
DIRT = (150, 110, 74)
DIRT_DARK = (116, 82, 58)
GRAVEL = (122, 118, 116)
GRAVEL_DARK = (92, 88, 92)
EDGE_LINE = (232, 232, 224)
DASH = (240, 196, 64)
DASH_SHADE = (196, 150, 48)


def build_ground(assets: Assets, rng: random.Random) -> pygame.Surface:
    g = pygame.Surface((NATIVE_W, NATIVE_H))
    g.fill(GRASS)
    road_l, road_r = _col(ROAD_LEFT), _col(ROAD_RIGHT)  # 134, 294
    for _ in range(1900):  # grass speckles and tufts (wrapped vertically so the tile repeats)
        x, y = rng.randrange(NATIVE_W), rng.randrange(NATIVE_H)
        color = rng.choice((GRASS_DARK, GRASS_DARK, GRASS_LIGHT))
        g.set_at((x, y), color)
        if color is GRASS_LIGHT and rng.random() < 0.4:
            g.set_at((x, (y - 1) % NATIVE_H), GRASS_TIP)
    for y in range(NATIVE_H):
        # wavy dirt verge; the wobble uses periods that divide the tile height so it tiles seamlessly
        wobble = round(1.5 + 1.2 * _wave(y, 3) + 0.8 * _wave(y + 17, 8))
        for side, edge, step in ((0, road_l - 5, -1), (1, road_r + 5, 1)):
            width = 3 + wobble + side
            for k in range(width):
                x = edge + step * k
                g.set_at((x, y), DIRT_DARK if k == width - 1 or rng.random() < 0.08 else DIRT)
        for x in range(road_l - 5, road_l):  # gravel shoulders
            g.set_at((x, y), GRAVEL_DARK if rng.random() < 0.12 else GRAVEL)
        for x in range(road_r, road_r + 5):
            g.set_at((x, y), GRAVEL_DARK if rng.random() < 0.12 else GRAVEL)
    tile = assets.native("road_tile")[0]
    for y in range(0, NATIVE_H, tile.get_height()):
        g.blit(tile, (road_l, y))
    pygame.draw.line(g, EDGE_LINE, (road_l + 1, 0), (road_l + 1, NATIVE_H))
    pygame.draw.line(g, EDGE_LINE, (road_r - 2, 0), (road_r - 2, NATIVE_H))
    for lane in range(1, LANES):
        x = _col(ROAD_LEFT + lane * LANE_WIDTH)
        for y in range(0, NATIVE_H, 24):
            g.fill(DASH, (x - 1, y + 2, 2, 11))
            g.fill(DASH_SHADE, (x - 1, y + 12, 2, 1))
    return pygame.transform.scale_by(g, SCALE)


def _wave(y: int, cycles: int) -> float:
    return math.sin(y / NATIVE_H * cycles * math.tau)


def build_vignette() -> pygame.Surface:
    small = pygame.Surface((32, 18), pygame.SRCALPHA)
    for y in range(18):
        for x in range(32):
            dx, dy = (x - 15.5) / 16, (y - 8.5) / 9
            d = min(1.0, (dx * dx + dy * dy) ** 0.5)
            small.set_at((x, y), (6, 8, 20, round(150 * max(0.0, d - 0.55) / 0.45)))
    return pygame.transform.smoothscale(small, (WIDTH, HEIGHT))


@dataclass
class Prop:
    sprite: str
    frame: int
    x: float
    y: float
    flip: bool = False
    shadow: bool = True


LEFT_VERGE = (16, ROAD_LEFT - 70)
RIGHT_VERGE = (ROAD_RIGHT + 70, WIDTH - 16)
LAMP_SPACING = 420


class Road:
    def __init__(self, assets: Assets, rng: random.Random) -> None:
        self.assets = assets
        self.rng = rng
        self.ground = build_ground(assets, random.Random(2022))
        self.vignette = build_vignette()
        self.scroll = 0.0
        self.props: list[Prop] = []
        self._until_prop = [0.0, 0.0]
        self._until_lamp = 0.0
        self._lamp_side = 0
        for _ in range(HEIGHT // 8):  # pre-populate so the first frame is not bare
            self.update(8.0)

    def update(self, px: float) -> None:
        self.scroll = (self.scroll + px) % TILE_H
        for prop in self.props:
            prop.y += px
        self.props = [p for p in self.props if p.y < HEIGHT + 120]
        for side in (0, 1):
            self._until_prop[side] -= px
            while self._until_prop[side] <= 0:
                self._spawn_prop(side, -100 - self._until_prop[side])
                self._until_prop[side] += self.rng.uniform(52, 150)
        self._until_lamp -= px
        if self._until_lamp <= 0:
            left = self._lamp_side == 0
            x = ROAD_LEFT - 34 if left else ROAD_RIGHT + 34
            self.props.append(Prop("lamp", 0, x, -120 - self._until_lamp, flip=not left))
            self._lamp_side ^= 1
            self._until_lamp += LAMP_SPACING / 2

    def _spawn_prop(self, side: int, y: float) -> None:
        r = self.rng
        lo, hi = LEFT_VERGE if side == 0 else RIGHT_VERGE
        roll = r.random()
        if roll < 0.42:
            # trees stay away from the road so their canopies never cover it
            x = r.uniform(lo, hi - 40) if side == 0 else r.uniform(lo + 40, hi)
            self.props.append(Prop("tree", r.randrange(2), x, y, flip=r.random() < 0.5))
        elif roll < 0.7:
            self.props.append(Prop("bush", r.randrange(2), r.uniform(lo, hi), y, flip=r.random() < 0.5))
        elif roll < 0.85:
            self.props.append(
                Prop("flowers", r.randrange(3), r.uniform(lo, hi + 30 * (1 - 2 * side)), y, shadow=False)
            )
        else:
            self.props.append(Prop("rock_small", 0, r.uniform(lo, hi), y, flip=r.random() < 0.5))

    def draw(self, surface: pygame.Surface, offset: tuple[float, float] = (0, 0)) -> None:
        ox, oy = round(offset[0]), round(offset[1])
        y = round(self.scroll) - TILE_H + oy
        while y < HEIGHT:
            surface.blit(self.ground, (X_SHIFT + ox, y))
            y += TILE_H
        props = sorted(self.props, key=lambda p: (p.sprite == "tree", p.y))
        for prop in props:
            if prop.shadow:
                shadow = self.assets.shadow(prop.sprite, prop.frame)
                surface.blit(shadow, shadow.get_rect(center=(prop.x + ox + 8, prop.y + oy + 10)))
        for prop in props:
            img = self.assets.rotated(prop.sprite, prop.frame, 0, prop.flip)
            surface.blit(img, img.get_rect(center=(round(prop.x) + ox, round(prop.y) + oy)))
