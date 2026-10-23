"""Procedural scrolling road: the biome's ground and roadside props beside gravel shoulders, asphalt and lane
dashes, which are the same in every biome."""

import functools
import math
import random
from dataclasses import dataclass

import pygame

from ..assets import Assets
from ..settings import HEIGHT, LANE_WIDTH, LANES, PLAYER_Y, PX_PER_METER, ROAD_LEFT, ROAD_RIGHT, SCALE, WIDTH

# The ground is painted on a native-resolution grid and scaled x3. Native column i covers screen
# x = 3*i - 2 .. 3*i, which puts the road edges (400, 880) and lane lines exactly on native pixels.
NATIVE_W, NATIVE_H = 428, 192
TILE_H = NATIVE_H * SCALE  # 576: the ground repeats every 576 px
X_SHIFT = -2

Color = tuple[int, int, int]


@dataclass(frozen=True)
class Biome:
    key: str
    name: str
    field: tuple[Color, Color, Color, Color]  # the ground, its dark and light speckles, the light ones' tips
    verge: tuple[Color, Color]  # the strip along the shoulders, and its outer edge
    props: tuple[tuple[str, tuple[int, ...], int, int], ...]  # (sprite, its frames, weight, margin to road)
    cracks: Color | None = None
    paved: bool = False  # paving slabs, and a straight kerb for a verge


# The road changes biome every 1 km, in this order, and a race of i km unlocks biome i as the scenery races
# start in; a second batch (Floresta, Praia) is only more rows.
BIOMES: tuple[Biome, ...] = (
    Biome(
        "campo",
        "Campo",
        ((58, 134, 70), (42, 108, 62), (92, 170, 78), (130, 196, 92)),
        ((150, 110, 74), (116, 82, 58)),
        # trees stay away from the road so their canopies never cover it; flowers may come closer
        (
            ("tree", (0, 1), 42, 40),
            ("bush", (0, 1), 28, 0),
            ("flowers", (0, 1, 2), 15, -30),
            ("rock_small", (0,), 15, 0),
        ),
    ),
    Biome(
        "deserto",
        "Deserto",
        ((222, 186, 124), (200, 160, 100), (236, 206, 148), (246, 224, 176)),
        ((190, 132, 72), (150, 100, 56)),
        (("cactus", (0, 1), 45, 0), ("bush", (2,), 25, 0), ("rock_small", (0,), 30, 0)),
        cracks=(178, 130, 84),
    ),
    Biome(
        "neve",
        "Neve",
        ((226, 234, 242), (186, 200, 218), (244, 248, 252), (255, 255, 255)),
        ((112, 92, 74), (82, 66, 56)),
        (("pine", (1,), 45, 40), ("bush", (3,), 40, 0), ("snowman", (0,), 15, 0)),
    ),
    Biome(
        "cidade",
        "Cidade à noite",
        ((84, 80, 86), (66, 62, 70), (98, 94, 100), (110, 106, 112)),
        ((170, 170, 166), (118, 118, 122)),
        (("building", (0, 1), 70, 40), ("bush", (0, 1), 30, 0)),  # bushes: flower beds
        paved=True,
    ),
    Biome(
        "vulcao",
        "Vulcão",
        ((48, 40, 42), (34, 28, 30), (68, 58, 58), (88, 74, 72)),
        ((78, 56, 50), (52, 38, 36)),
        (("basalt", (0, 1), 60, 0), ("lava", (0,), 30, 0), ("rock_small", (0,), 10, 0)),
        cracks=(150, 44, 26),  # dimmer than the lava pools, so the pools stay the bright accents
    ),
)
FLAT = ("flowers", "lava")  # lie on the ground: no shadow
TALL = ("tree", "pine", "building")  # drawn over the other props


def biome_at(start: int, meters: float) -> int:
    """The biome ``meters`` into a race that started in biome ``start`` (behind the start line too)."""
    return (start + int(max(0.0, meters) // 1000)) % len(BIOMES)


def _col(x: int) -> int:
    return (x - X_SHIFT) // SCALE


GRAVEL = (122, 118, 116)
GRAVEL_DARK = (92, 88, 92)
EDGE_LINE = (232, 232, 224)
DASH = (240, 196, 64)
DASH_SHADE = (196, 150, 48)


def build_ground(assets: Assets, biome: Biome, rng: random.Random) -> pygame.Surface:
    base, dark, light, tip = biome.field
    verge, verge_edge = biome.verge
    g = pygame.Surface((NATIVE_W, NATIVE_H))
    g.fill(base)
    road_l, road_r = _col(ROAD_LEFT), _col(ROAD_RIGHT)  # 134, 294
    for _ in range(1900):  # speckles and tufts (wrapped vertically so the tile repeats)
        x, y = rng.randrange(NATIVE_W), rng.randrange(NATIVE_H)
        color = rng.choice((dark, dark, light))
        g.set_at((x, y), color)
        if color is light and rng.random() < 0.4:
            g.set_at((x, (y - 1) % NATIVE_H), tip)
    if biome.cracks:  # a jittered grid, most knots joined: dried mud, or lava under a crust
        n, rows = NATIVE_W // 24 + 1, NATIVE_H // 24  # 24 divides the tile height, so the cracks tile
        knots = [
            [(i * 24 + rng.randrange(24), j * 24 + rng.randrange(24)) for j in range(rows)]
            for i in range(n + 1)
        ]
        for column in knots:
            column.append((column[0][0], column[0][1] + NATIVE_H))  # its first knot again, a tile down
        for i in range(n):
            for j in range(rows):
                x, y = knots[i][j]
                for ex, ey in (knots[i][j + 1], knots[i + 1][j]):  # the knot below, the knot to the right
                    if rng.random() < 0.75:
                        for dy in (0, -NATIVE_H):  # what runs off the bottom comes in at the top
                            pygame.draw.line(g, biome.cracks, (x, y + dy), (ex, ey + dy))
    if biome.paved:  # slab joints: 16 divides the tile height
        for x in range(0, NATIVE_W, 16):
            g.fill(dark, (x, 0, 1, NATIVE_H))
        for y in range(0, NATIVE_H, 16):
            g.fill(dark, (0, y, NATIVE_W, 1))
    for y in range(NATIVE_H):
        # wavy verge; the wobble uses periods that divide the tile height so it tiles seamlessly
        wobble = 1 if biome.paved else round(1.5 + 1.2 * _wave(y, 3) + 0.8 * _wave(y + 17, 8))
        for side, edge, step in ((0, road_l - 5, -1), (1, road_r + 5, 1)):
            width = 3 + wobble + side
            for k in range(width):
                x = edge + step * k
                g.set_at((x, y), verge_edge if k == width - 1 or rng.random() < 0.08 else verge)
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


# ponytail: every biome's ground stays built, ~3 MB each once scaled (app.py builds them at start-up); if the
# wasm runs short of memory, lru_cache(2), building the next biome's before the road reaches it
@functools.lru_cache(maxsize=len(BIOMES))  # the game has one Assets (the tests make one per Game)
def ground(assets: Assets, biome: int) -> pygame.Surface:
    """One ground tile per biome for every Road (it is only ever blitted): a World costs ~20 KB, not 6 MB."""
    return build_ground(assets, BIOMES[biome], random.Random(2022))


def _wave(y: int, cycles: int) -> float:
    return math.sin(y / NATIVE_H * cycles * math.tau)


@functools.cache
def build_vignette() -> pygame.Surface:
    small = pygame.Surface((32, 18), pygame.SRCALPHA)
    for y in range(18):
        for x in range(32):
            dx, dy = (x - 15.5) / 16, (y - 8.5) / 9
            d = min(1.0, (dx * dx + dy * dy) ** 0.5)
            small.set_at((x, y), (6, 8, 20, round(150 * max(0.0, d - 0.55) / 0.45)))
    return pygame.transform.smoothscale(small, (WIDTH, HEIGHT))


@functools.cache
def build_lamp_pool() -> pygame.Surface:
    """The faint warm light round a street lamp's foot, on paving at night; it ends before the gravel."""
    pool = pygame.Surface((44, 72), pygame.SRCALPHA)  # long along the pavement, narrow across it
    for y in range(72):
        for x in range(44):
            d = math.hypot((x - 21.5) / 22, (y - 35.5) / 36)
            pool.set_at((x, y), (255, 200, 120, round(35 * min(1.0, 1.6 * max(0.0, 1 - d)))))
    return pool


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
        self.vignette = build_vignette()
        self.restart(0)

    def restart(self, biome: int) -> None:
        """Start the road over in a biome: the scenery chosen for a race, or a preview in the garage."""
        self.start, self.px = biome, 0.0
        self.props: list[Prop] = []
        self._until_prop = [0.0, 0.0]
        self._until_lamp = 0.0
        self._lamp_side = 0
        for _ in range(HEIGHT // 8):  # pre-populate so the first frame is not bare
            self.update(8.0)
        self.px = 0.0  # px: how far the road has scrolled; the start line is at the car

    def biome(self, y: float) -> int:
        """The biome of the road at screen row y."""
        return biome_at(self.start, (self.px + PLAYER_Y - y) / PX_PER_METER)

    def update(self, px: float) -> None:
        self.px += px
        for prop in self.props:
            prop.y += px
        self.props = [p for p in self.props if p.y < HEIGHT + 120]
        for side in (0, 1):
            self._until_prop[side] -= px
            while self._until_prop[side] <= 0:
                self._spawn_prop(side, -100 - self._until_prop[side])
                # a roof and its shadow are 126 px tall: the next prop starts clear of it (no stacked roofs)
                roof = 74 if self.props[-1].sprite == "building" else 0
                self._until_prop[side] += self.rng.uniform(52, 150) + roof
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
        props = BIOMES[self.biome(y)].props
        sprite, frames, _, margin = r.choices(props, [p[2] for p in props])[0]
        x = r.uniform(lo, hi - margin) if side == 0 else r.uniform(lo + margin, hi)
        self.props.append(Prop(sprite, r.choice(frames), x, y, r.random() < 0.5, sprite not in FLAT))

    def draw(self, surface: pygame.Surface, offset: tuple[float, float] = (0, 0)) -> None:
        ox, oy = round(offset[0]), round(offset[1])
        # the tiles keep step with px: a biome is 25 whole tiles (1 km), so each tile is all one biome
        y = round(self.px + PLAYER_Y) % TILE_H - TILE_H
        while y + oy < HEIGHT:
            surface.blit(ground(self.assets, self.biome(y + TILE_H / 2)), (X_SHIFT + ox, y + oy))
            y += TILE_H
        props = sorted(self.props, key=lambda p: (p.sprite in TALL, p.y))
        for prop in props:
            if prop.sprite == "lamp" and BIOMES[self.biome(prop.y)].paved:
                pool = build_lamp_pool()
                foot = (prop.x + (5 if prop.flip else -5) + ox, prop.y + 34 + oy)
                surface.blit(pool, pool.get_rect(center=foot))
            if prop.shadow:
                shadow = self.assets.shadow(prop.sprite, prop.frame)
                surface.blit(shadow, shadow.get_rect(center=(prop.x + ox + 8, prop.y + oy + 10)))
        for prop in props:
            img = self.assets.rotated(prop.sprite, prop.frame, 0, prop.flip)
            surface.blit(img, img.get_rect(center=(round(prop.x) + ox, round(prop.y) + oy)))
