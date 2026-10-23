"""Generate every sprite, sound and music file of the game (the SPEC asset manifest).

    python -I tools/make_assets.py

Stdlib + pygame only and fully deterministic (string-seeded RNGs, one per asset). Writes
src/jogo_de_carro/assets/ plus two review images in tools/ (contact_sheet.png, audio_waveforms.png),
then validates everything it wrote.
"""

from __future__ import annotations

import array
import math
import os
import random
import sys
import time
import wave
from collections.abc import Callable, Sequence
from functools import lru_cache
from pathlib import Path

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
os.environ["PYGAME_HIDE_SUPPORT_PROMPT"] = "1"
import pygame

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "src" / "jogo_de_carro" / "assets"
TOOLS = ROOT / "tools"

Color = tuple[int, ...]
Surf = pygame.Surface

# name -> (frames, frame_w, frame_h). Everything is transparent except the road tile. The cars (car_<key>,
# one per CAR_DESIGNS key) join it further down.
SPRITES: dict[str, tuple[int, int, int]] = {
    "truck": (2, 28, 64),
    "van": (2, 26, 48),
    "stone": (1, 24, 22),
    "pothole": (1, 30, 20),
    "trunk": (4, 44, 18),
    "cone": (1, 14, 16),
    "coin": (8, 12, 12),
    "shield": (4, 16, 16),
    "star": (4, 16, 16),
    "ghost": (4, 16, 16),
    "turbo": (4, 16, 16),
    "slow": (4, 16, 16),
    "life": (4, 16, 16),
    "tree": (2, 32, 32),
    "bush": (4, 16, 12),
    "lamp": (1, 10, 28),
    "rock_small": (1, 10, 8),
    "flowers": (3, 8, 6),
    "cactus": (2, 14, 26),
    "pine": (2, 20, 32),
    "snowman": (1, 12, 16),
    "building": (2, 40, 40),
    "basalt": (2, 14, 10),
    "lava": (1, 24, 14),
    "blinker": (2, 6, 6),
    "road_tile": (1, 160, 64),
}
OPAQUE = {"road_tile"}
SOUNDS = (
    "coin", "crash", "near_miss", "countdown", "go", "shield_up", "shield_break",
    "ui_move", "ui_select", "ui_back", "record", "lane_change",
)  # fmt: skip
LOOPS = {"menu": (100, 12), "race": (128, 16)}  # name -> (bpm, bars)

# ---------------------------------------------------------------------------------------------
# Pixel helpers
# ---------------------------------------------------------------------------------------------
OUT = (26, 28, 44)
SHADOW = (10, 12, 24)
N4 = ((1, 0), (-1, 0), (0, 1), (0, -1))


def _unit(x: float, y: float, z: float) -> tuple[float, float, float]:
    n = math.sqrt(x * x + y * y + z * z) or 1.0
    return x / n, y / n, z / n


LX, LY, LZ = _unit(-0.55, -0.7, 0.75)  # light from the upper-left


def new(w: int, h: int) -> Surf:
    return pygame.Surface((w, h), pygame.SRCALPHA)


def put(s: Surf, x: int, y: int, c: Color) -> None:
    if 0 <= x < s.get_width() and 0 <= y < s.get_height():
        s.set_at((x, y), c)


def solid(s: Surf, x: int, y: int) -> bool:
    return 0 <= x < s.get_width() and 0 <= y < s.get_height() and s.get_at((x, y))[3] > 127


def outline(s: Surf, c: Color = OUT) -> Surf:
    w, h = s.get_size()
    edge = [
        (x, y)
        for y in range(h)
        for x in range(w)
        if not solid(s, x, y) and any(solid(s, x + dx, y + dy) for dx, dy in N4)
    ]
    for p in edge:
        s.set_at(p, c)
    return s


def with_shadow(s: Surf, dx: int = 1, dy: int = 1, alpha: int = 80) -> Surf:
    """Soft drop shadow (alpha < 128, so it stays out of pygame collision masks)."""
    w, h = s.get_size()
    out = new(w, h)
    for y in range(h):
        for x in range(w):
            if solid(s, x - dx, y - dy) and not solid(s, x, y):
                out.set_at((x, y), (*SHADOW, alpha))
    out.blit(s, (0, 0))
    return out


def strip(frames: Sequence[Surf]) -> Surf:
    w, h = frames[0].get_size()
    out = new(w * len(frames), h)
    for i, f in enumerate(frames):
        out.blit(f, (i * w, 0))
    return out


def expand(keys: dict[int, int], y0: int, y1: int) -> dict[int, int]:
    """Piecewise-constant row table: {row: value} holds until the next key."""
    out, cur = {}, 0
    for y in range(y0, y1 + 1):
        cur = keys.get(y, cur)
        out[y] = cur
    return out


def art(rows: Sequence[str], legend: dict[str, Color]) -> Surf:
    s = new(len(rows[0]), len(rows))
    for y, row in enumerate(rows):
        for x, ch in enumerate(row):
            if ch in legend:
                s.set_at((x, y), legend[ch])
    return s


def blob(
    w: int,
    h: int,
    balls: Sequence[tuple[float, float, float, float, float]],
    ramp: Sequence[Color],
    seed: str,
    *,
    jitter: float = 0.06,
    facets: int = 0,
    bump: float = 0.4,
    speckle: float = 0.0,
    edge: Color | None = OUT,
) -> Surf:
    """Shade a union of ellipsoids (cx, cy, rx, ry, z) lit from the upper-left.

    Facets: Voronoi cells shaded flat (one tilted normal per cell) give chiselled low-poly rock.
    Balls occluded by a higher neighbour toward the light get a cast shadow, which separates
    foliage clumps and boulders.
    """
    rng = random.Random(seed)
    cells = [
        (rng.uniform(0, w), rng.uniform(0, h), rng.uniform(-bump, bump), rng.uniform(-bump, bump))
        for _ in range(facets)
    ]
    hit: dict[tuple[int, int], tuple[float, int, float, float, float]] = {}
    for y in range(h):
        for x in range(w):
            best = None
            for i, (cx, cy, rx, ry, z) in enumerate(balls):
                dx, dy = (x + 0.5 - cx) / rx, (y + 0.5 - cy) / ry
                d2 = dx * dx + dy * dy
                if d2 < 1:
                    nz = math.sqrt(1 - d2)
                    top = z + nz * min(rx, ry)
                    if best is None or top > best[0]:
                        best = (top, i, dx, dy, nz)
            if best:
                hit[x, y] = best
    s, k = new(w, h), len(ramp)
    flat = {}  # cell -> normal at its seed (only seeds that land on the rock)
    for ci, (sx, sy, bx, by) in enumerate(cells):
        h0 = hit.get((int(sx), int(sy)))
        if h0:
            flat[ci] = (h0[1], _unit(h0[2] + bx, h0[3] + by, h0[4]))
    for (x, y), (top, i, nx, ny, nz) in sorted(hit.items()):
        mine = [ci for ci, (bi, _) in flat.items() if bi == i]
        if mine:
            ci = min(mine, key=lambda c: (cells[c][0] - x) ** 2 + (cells[c][1] - y) ** 2)
            nx, ny, nz = flat[ci][1]
        nx, ny, nz = _unit(nx, ny, nz)
        lum = nx * LX + ny * LY + nz * LZ + rng.uniform(-jitter, jitter)
        for ox, oy in ((-1, -1), (0, -1), (-1, 0)):
            o = hit.get((x + ox, y + oy))
            if o and o[1] != i and o[0] > top + 0.6:
                lum -= 0.32
                break
        idx = max(0, min(k - 1, int((lum + 0.12) / 1.02 * k)))
        if speckle and rng.random() < speckle:
            idx = max(0, min(k - 1, idx + rng.choice((-1, 1))))
        s.set_at((x, y), ramp[idx])
    return outline(s, edge) if edge else s


# ---------------------------------------------------------------------------------------------
# Vehicles (top-down, nose up)
# ---------------------------------------------------------------------------------------------
TIRE = [(36, 36, 48), (78, 78, 94)]  # groove, tread block
GLASS = [(20, 28, 50), (38, 56, 94), (84, 122, 176), (200, 228, 255)]
GLASS_CYAN = [(14, 58, 72), (28, 112, 128), (90, 204, 212), (214, 255, 250)]
HEAD = [(255, 206, 110), (255, 250, 226)]
TAIL = [(120, 14, 34), (220, 40, 58), (255, 132, 120)]
CAR_RAMPS = {
    "yellow": [(156, 84, 22), (218, 140, 18), (250, 188, 32), (255, 222, 96), (255, 246, 194)],
    "black": [(36, 38, 54), (50, 54, 74), (70, 76, 100), (110, 118, 148), (176, 186, 214)],
    "blue": [(20, 40, 110), (30, 72, 168), (48, 112, 222), (100, 164, 252), (196, 228, 255)],
    "pink": [(118, 20, 92), (182, 38, 136), (232, 72, 172), (255, 132, 206), (255, 208, 238)],
    "red": [(100, 14, 30), (162, 24, 40), (214, 46, 52), (246, 98, 84), (255, 180, 156)],
    "white": [(112, 120, 144), (168, 176, 198), (214, 220, 234), (240, 244, 252), (255, 255, 255)],
}
WHITE = CAR_RAMPS["white"]
TRUCK_CAB = [(142, 60, 18), (204, 96, 26), (242, 140, 40), (255, 186, 92), (255, 228, 176)]
TRUCK_BOX = [(112, 110, 116), (164, 162, 166), (206, 204, 204), (232, 230, 226), (252, 250, 244)]
VAN = [(18, 84, 86), (28, 128, 124), (52, 176, 156), (110, 222, 190), (196, 250, 226)]
POLICE_RED = [(150, 20, 36), (240, 52, 60), (255, 150, 140)]
POLICE_BLUE = [(24, 46, 150), (52, 110, 250), (150, 200, 255)]

# geometry per body style; insets are pixels in from the widest body columns (3 .. w-4)
STYLES: dict[str, dict] = {
    "sport": dict(
        insets={1: 5, 2: 3, 3: 1, 4: 0, 15: 1, 24: 0, 37: 1, 38: 3},
        wheels=[(6, 12), (27, 33)],
        ws=(12, 15), roof=(16, 22), rear=(23, 25), glass_in=2, roof_in=4, head=2,
    ),
    "sedan": dict(
        insets={1: 3, 2: 1, 3: 0, 15: 1, 26: 0, 37: 1, 38: 2},
        wheels=[(6, 12), (28, 34)],
        ws=(11, 14), roof=(15, 24), rear=(25, 27), glass_in=2, roof_in=3, head=2,
    ),
    "jeep": dict(
        insets={1: 1, 2: 0, 38: 1},
        wheels=[(5, 12), (28, 35)],
        ws=(10, 12), roof=(13, 32), rear=None, glass_in=2, roof_in=2, head=1,
    ),
    "ambulance": dict(
        insets={1: 2, 2: 1, 3: 0},
        wheels=[(5, 11), (29, 35)],
        ws=(7, 9), roof=(10, 37), rear=None, glass_in=2, roof_in=1, head=2,
    ),
}  # fmt: skip


def hline(s: Surf, x0: int, x1: int, y: int, c: Color) -> None:
    for x in range(x0, x1 + 1):
        put(s, x, y, c)


def vehicle(
    w: int,
    h: int,
    rows: tuple[int, int],
    style: dict,
    ramp: Sequence[Color],
    frame: int,
    deco: Callable[[Surf, dict], None] | None = None,
    glass: Sequence[Color] = GLASS,
) -> Surf:
    s = new(w, h)
    top, bot = rows
    ins = expand(style["insets"], top, bot)
    x0 = {y: 3 + ins[y] for y in ins}
    x1 = {y: w - 4 - ins[y] for y in ins}
    for wy0, wy1 in style["wheels"]:  # tread rows swap between frames -> rolling wheels
        for y in range(wy0, wy1 + 1):
            tread = TIRE[(y + frame) % 2]
            end = y in (wy0, wy1)
            for x in (1, 2, w - 3, w - 2):
                if not (end and x in (1, w - 2)):
                    s.set_at((x, y), tread)
            for x in (3, w - 4):
                s.set_at((x, y), TIRE[0])
    for y in range(top, bot + 1):
        for x in range(x0[y], x1[y] + 1):
            i = 3 if x == x0[y] else 1 if x == x1[y] else 2
            if y == top:
                i = min(4, i + 1)
            elif y == bot:
                i = 0
            elif y == bot - 1:
                i = min(i, 1)
            s.set_at((x, y), ramp[i])
    ws0, ws1 = style["ws"]
    r0, r1 = style["roof"]
    gi, ri = style["glass_in"], style["roof_in"]
    # hood highlight streak
    for y in range(top + 2, ws0 - 1):
        put(s, x0[y] + 2, y, ramp[3])
    put(s, x0[top + 2] + 2, top + 2, ramp[4])
    put(s, x0[top + 2] + 3, top + 2, ramp[3])
    # windshield trapezoid with a diagonal reflection
    n = ws1 - ws0 + 1
    for j, y in enumerate(range(ws0, ws1 + 1)):
        inset = gi + round(j * (ri - 1 - gi) / max(1, n - 1))
        gx0, gx1 = 3 + inset, w - 4 - inset
        for x in range(gx0, gx1 + 1):
            u = x - gx0
            c = glass[2] if u + j in (2, 3) else glass[0] if x == gx1 or j == 0 else glass[1]
            s.set_at((x, y), c)
        if j == 1:
            s.set_at((gx0 + 1, y), glass[3])
    # roof + side windows
    rx0, rx1 = 3 + ri, w - 4 - ri
    for y in range(r0, r1 + 1):
        for x in range(rx0, rx1 + 1):
            i = 3 if x < rx1 else 2
            if y == r1:
                i = 2
            s.set_at((x, y), ramp[i])
        if r0 < y < r1:
            s.set_at((rx0 - 1, y), glass[2] if y < r0 + 3 else glass[1])
            s.set_at((rx1 + 1, y), glass[0])
    hline(s, rx0, rx0 + 1, r0, ramp[4])
    put(s, rx0, r0 + 1, ramp[4])
    # rear glass
    if style["rear"]:
        g0, g1 = style["rear"]
        n = g1 - g0 + 1
        for j, y in enumerate(range(g0, g1 + 1)):
            inset = ri - 1 - round(j * (ri - 1 - gi) / max(1, n - 1))
            for x in range(3 + inset, w - 3 - inset):
                s.set_at((x, y), glass[1] if x == 3 + inset + 1 and j < n - 1 else glass[0])
    # mirrors
    for y in (ws0, ws0 + 1):
        put(s, x0[y] - 1, y, ramp[3])
        put(s, x1[y] + 1, y, ramp[1])
    # headlights + tail lights
    hy = style["head"]
    for x, y, c in (
        (x0[hy] + 1, hy, HEAD[1]), (x0[hy] + 2, hy, HEAD[1]), (x0[hy] + 3, hy, HEAD[0]),
        (x0[hy + 1] + 1, hy + 1, HEAD[0]), (x0[hy + 1] + 2, hy + 1, HEAD[0]),
    ):  # fmt: skip
        put(s, x, y, c)
        put(s, w - 1 - x, y, c)
    ty = bot - 1
    for x, c in ((x0[ty] + 1, TAIL[2]), (x0[ty] + 2, TAIL[1]), (x0[ty] + 3, TAIL[1])):
        put(s, x, ty, c)
        put(s, w - 1 - x, ty, c)
        if x0[bot] <= x <= x1[bot]:
            put(s, x, bot, TAIL[0])
            put(s, w - 1 - x, bot, TAIL[0])
    if deco:
        deco(s, dict(x0=x0, x1=x1, top=top, bot=bot, rx0=rx0, rx1=rx1, r0=r0, r1=r1, ws=(ws0, ws1), w=w))
    return outline(s)


def deco_sport(s: Surf, g: dict) -> None:  # yellow: hood scoop, engine slats, rear wing
    r = CAR_RAMPS["yellow"]
    hline(s, 10, 13, 5, OUT)  # hood scoop: dark intake facing forward
    for y in (6, 7, 8):
        hline(s, 10, 13, y, r[2])
        put(s, 10, y, r[3])
        put(s, 13, y, r[1])
    for y in range(27, 33, 2):
        hline(s, 9, 14, y, r[0])
    for x in range(g["x0"][35] - 2, g["x1"][35] + 3):
        put(s, x, 34, r[4] if x < 8 else r[3] if x < 12 else r[2])
        put(s, x, 35, r[0])


def deco_stripes(s: Surf, g: dict) -> None:  # black: twin silver racing stripes
    rows = [y for y in range(g["top"] + 1, g["bot"] - 1) if not (g["ws"][0] <= y < g["r0"])]
    for y in rows:
        if 25 <= y <= 27:  # rear glass
            continue
        light = g["r0"] <= y <= g["r1"]
        put(s, 10, y, (236, 238, 246) if light else (190, 196, 212))
        put(s, 13, y, (236, 238, 246) if light else (170, 176, 194))


def deco_police(s: Surf, g: dict) -> None:  # blue: white roof + doors, red/blue light bar
    for y in range(g["r0"], g["r1"] + 1):
        for x in range(g["rx0"], g["rx1"] + 1):
            s.set_at((x, y), WHITE[3] if x < g["rx1"] else WHITE[1])
    for y in range(g["ws"][0], 28):
        s.set_at((g["x0"][y], y), WHITE[3])
        s.set_at((g["x0"][y] + 1, y), WHITE[2])
        s.set_at((g["x1"][y], y), WHITE[1])
        s.set_at((g["x1"][y] - 1, y), WHITE[2])
    y = g["r0"] + 3
    for x in range(g["rx0"], g["rx1"] + 1):
        mid = (g["rx0"] + g["rx1"]) / 2
        ramp = POLICE_RED if x < mid else POLICE_BLUE
        put(s, x, y, ramp[2] if x in (g["rx0"], round(mid)) else ramp[1])
        put(s, x, y + 1, ramp[0])
    put(s, 11, y, OUT)
    put(s, 12, y, OUT)
    put(s, 11, y + 1, OUT)
    put(s, 12, y + 1, OUT)


def deco_convertible(s: Surf, g: dict) -> None:  # pink: open cockpit with two seats
    inner, seat, seat_d = (64, 24, 60), (255, 222, 236), (214, 150, 186)
    for y in range(16, 24):
        for x in range(6, 18):
            s.set_at((x, y), inner)
    for sx in (7, 13):
        for y in range(18, 23):
            for x in range(sx, sx + 4):
                s.set_at((x, y), seat if x < sx + 3 and y < 22 else seat_d)
        hline(s, sx + 1, sx + 2, 23, seat)
    hline(s, 7, 9, 16, (40, 40, 52))  # steering wheel
    for y in (24, 25):
        for x in range(6, 18):
            s.set_at((x, y), CAR_RAMPS["pink"][3 if x in (8, 9, 14, 15) else 2])


def deco_jeep(s: Surf, g: dict) -> None:  # red: grille, flares, roof rack, spare wheel
    for x in range(8, 16, 2):
        put(s, x, 2, OUT)
    for wy0, wy1 in STYLES["jeep"]["wheels"]:
        for y in range(wy0 - 1, wy1 + 2):
            s.set_at((g["x0"][y], y), (66, 66, 80))
            s.set_at((g["x1"][y], y), (40, 40, 52))
    hardtop = [(34, 36, 50), (50, 54, 72), (70, 76, 98), (112, 120, 150)]
    for y in range(g["r0"], g["r1"] + 1):
        for x in range(g["rx0"], g["rx1"] + 1):
            i = 3 if y == g["r0"] else 2 if x == g["rx0"] else 0 if x == g["rx1"] else 1
            s.set_at((x, y), hardtop[i])
    for y in range(g["r0"] + 4, g["r1"] - 2, 6):  # roof-rack crossbars
        hline(s, g["rx0"] + 1, g["rx1"] - 1, y, (168, 174, 190))
        hline(s, g["rx0"] + 1, g["rx1"] - 1, y + 1, (24, 26, 36))
    for y in range(34, 39):
        for x in range(8, 16):
            d = math.hypot(x + 0.5 - 12, (y + 0.5 - 36.5) * 1.25)
            if d < 4:
                put(s, x, y, (120, 124, 140) if d < 1.6 else TIRE[1] if d < 2.6 and x < 12 else TIRE[0])


def deco_ambulance(s: Surf, g: dict) -> None:  # white: red side stripes, light bar, blue cross
    red = [(170, 26, 40), (236, 64, 70)]
    for y in range(3, g["bot"]):
        s.set_at((g["x0"][y], y), red[1])
        s.set_at((g["x1"][y], y), red[0])
    for x in range(6, 18):
        ramp = POLICE_RED if x < 12 else POLICE_BLUE
        put(s, x, 11, ramp[2] if x in (6, 12) else ramp[1])
        put(s, x, 12, ramp[0])
    blue, blue_l = (40, 104, 220), (120, 176, 255)
    for y in range(21, 30):
        for x in range(8, 16):
            if 10 <= x <= 13 or 23 <= y <= 26:
                edge = (x in (8, 10) and not (23 <= y <= 26 and x == 10)) or (
                    y in (21, 23) and not (10 <= x <= 13 and y == 23)
                )
                put(s, x, y, blue_l if edge else blue)
    for y in range(33, 38):
        put(s, 11, y, WHITE[1])


def deco_truck(s: Surf, g: dict) -> None:  # orange cab + corrugated cargo box
    w = g["w"]
    for y in (17, 18):
        for x in range(w):
            s.set_at((x, y), (0, 0, 0, 0))
        hline(s, 11, 16, y, (50, 50, 62))
    for y in range(19, 63):
        for x in range(3, w - 3):
            i = 3 if x == 3 else 1 if x == w - 4 else 2
            if y == 19:
                i = 4
            elif y >= 61:
                i = 0 if y == 62 else 1
            elif (y - 19) % 4 == 3:
                i = max(0, i - 1)
            s.set_at((x, y), TRUCK_BOX[i])
    for y in range(22, 25):
        hline(s, 5, w - 7, y, VAN[2] if y < 24 else VAN[1])
    for x, c in ((4, TAIL[2]), (5, TAIL[1]), (w - 6, TAIL[1]), (w - 5, TAIL[2])):
        put(s, x, 61, c)
    for y in range(57, 63):
        put(s, w // 2 - 1, y, TRUCK_BOX[0])
    for y in range(8, 12):  # air deflector on the cab roof
        hline(s, g["rx0"], g["rx1"] - 1, y, TRUCK_CAB[3] if y < 10 else TRUCK_CAB[2])


def deco_van(s: Surf, g: dict) -> None:  # teal delivery van: roof ribs + vent
    for y in range(g["r0"] + 4, g["r1"] - 1, 5):
        hline(s, g["rx0"], g["rx1"], y, VAN[1])
    for y in range(22, 26):
        hline(s, 10, 15, y, VAN[0] if y == 25 else (196, 204, 214) if y > 22 else (236, 240, 246))
    for y in range(41, 46):
        put(s, 12, y, VAN[0])


# Shop cars on vehicle() (route A): pearl Herbie 53, Bumblebee, Mach 5; 3x5 race digits
CAR_RAMPS["beetle"] = [(122, 122, 142), (180, 180, 198), (224, 224, 234), (244, 243, 248), (255, 255, 255)]
CAR_RAMPS["robot_camaro"] = [(150, 100, 0), (222, 168, 0), (255, 212, 18), (255, 236, 102), (255, 252, 204)]
CAR_RAMPS["racer5"] = WHITE
BEETLE_RED, BEETLE_BLUE = (214, 36, 44), (34, 70, 182)

STYLES["beetle"] = dict(  # round nose and tail, fenders bulging 2 px out of the cabin
    insets={1: 6, 2: 4, 3: 2, 4: 1, 5: 0, 13: 1, 14: 2, 25: 1, 26: 0, 35: 1, 36: 2, 37: 3, 38: 5},
    wheels=[(6, 12), (28, 34)],
    ws=(12, 14), roof=(15, 23), rear=(24, 25), glass_in=3, roof_in=4, head=3,
)  # fmt: skip

# 3x5 race-number font (Herbie, Mach 5, Mean Machine, SAMU)
DIGITS = {
    "0": ("###", "#.#", "#.#", "#.#", "###"), "1": (".#.", "##.", ".#.", ".#.", "###"),
    "2": ("###", "..#", "###", "#..", "###"), "3": ("###", "..#", "###", "..#", "###"),
    "4": ("#.#", "#.#", "###", "..#", "..#"), "5": ("###", "#..", "###", "..#", "###"),
    "6": ("###", "#..", "###", "#.#", "###"), "7": ("###", "..#", "..#", ".#.", ".#."),
    "8": ("###", "#.#", "###", "#.#", "###"), "9": ("###", "#.#", "###", "..#", "###"),
}  # fmt: skip


def digits(s: Surf, x: int, y: int, text: str, c: Color) -> None:
    for i, ch in enumerate(text):
        s.blit(art(DIGITS[ch], {"#": c}), (x + 4 * i, y))


BEETLE_ROUNDEL = (  # Herbie's "53" plate: thin grey ring, white field, 1 px margin round 7x5 of digits
    "..ooooooo..", ".o.......o.", "o.........o", "o.........o", "o.........o",
    "o.........o", "o.........o", ".o.......o.", "..ooooooo..",
)  # fmt: skip


def beetle_disc(s: Surf, x: int, y: int, w: int, h: int, c: Color) -> None:
    """Filled ellipse in the box (x, y, w, h): roundels for race numbers."""
    for py in range(y, y + h):
        for px in range(x, x + w):
            if ((px + 0.5 - x - w / 2) / (w / 2)) ** 2 + ((py + 0.5 - y - h / 2) / (h / 2)) ** 2 < 1.1:
                put(s, px, py, c)


def deco_beetle(s: Surf, g: dict) -> None:  # Herbie: fenders, RWB stripe, "53" roundels, louvres
    r = CAR_RAMPS["beetle"]
    # repaint the panels by column: fender | crease | lid | crease | fender (fender tops catch the light)
    shade = {3: 3, 4: 4, 5: 1, 6: 3, 17: 1, 18: 1, 19: 3, 20: 1}
    for y in range(g["top"], g["bot"] + 1):
        for x in range(g["x0"][y], g["x1"][y] + 1):
            if g["ws"][0] <= y <= 25 and 5 <= x <= 18:  # cabin: leave glass and roof alone
                continue
            i = shade.get(x, 2)
            if y == g["top"]:  # nose row lit, last two rows in shade, as vehicle() does
                i = min(4, i + 1)
            elif y >= g["bot"] - 1:
                i = 0 if y == g["bot"] else min(i, 1)
            put(s, x, y, r[i])
    for x in (6, 7, 16, 17):  # small, rounded rear window; round the roof dome's corners
        put(s, x, 24, r[3] if x < 12 else r[1])
        put(s, x, 25, r[3] if x < 12 else r[1])
    for x, y in ((7, 15), (16, 15), (7, 23), (16, 23)):
        put(s, x, y, GLASS[1])
    for x, y, c in ((5, 3, HEAD[1]), (4, 4, HEAD[1]), (5, 4, HEAD[0])):  # round headlamps on the fenders
        put(s, x, y, c)
        put(s, 23 - x, y, c)
    for x, y in ((4, 35), (5, 36)):  # small tail lamps on the rear fenders
        put(s, x, y, TAIL[1])
        put(s, 23 - x, y, TAIL[1])
    for y in range(1, 39):  # stripe: red, white, blue, left of centre, over everything but glass
        if g["ws"][0] <= y <= g["ws"][1] or 24 <= y <= 25:
            continue
        for x, c in ((8, BEETLE_RED), (9, BEETLE_RED), (10, r[4]), (11, BEETLE_BLUE), (12, BEETLE_BLUE)):
            if s.get_at((x, y))[3]:
                put(s, x, y, c)
    for y in (26, 28):  # engine-lid louvres either side of the stripe
        hline(s, 6, 7, y, r[0])
        hline(s, 13, 16, y, r[0])
    for y in (2, 29):  # "53" in a ringed white roundel on the front lid and the engine lid
        s.blit(art(BEETLE_ROUNDEL, {"o": r[0], ".": r[4]}), (6, y))
        digits(s, 8, y + 2, "53", OUT)


def deco_robot_camaro(s: Surf, g: dict) -> None:  # Bumblebee: twin black stripes, red Autobot face
    for y in range(g["top"] + 1, g["bot"]):
        if g["ws"][0] <= y < g["r0"] or 23 <= y <= 25:  # not over the glass
            continue
        for x in (8, 9, 14, 15):
            put(s, x, y, (20, 20, 28) if x in (8, 14) else (44, 44, 56))
    for x, y in ((10, 3), (13, 3), (10, 4), (11, 4), (12, 4), (13, 4), (11, 5), (12, 5)):
        put(s, x, y, (226, 30, 40))


def deco_racer5(s: Surf, g: dict) -> None:  # Mach 5: pointed nose, red M on the hood, 5 in a red disc
    r = CAR_RAMPS["racer5"]
    for y, half in ((1, 1), (2, 2), (3, 3), (4, 4), (5, 6)):  # carve a long beak between the fenders
        for x in range(g["x0"][y], g["x1"][y] + 1):
            if not 12 - half <= x < 12 + half:
                s.set_at((x, y), (0, 0, 0, 0))
            else:
                put(s, x, y, r[3] if x == 12 - half else r[1] if x == 11 + half else r[2])
    for x, c in ((4, HEAD[1]), (5, HEAD[0])):  # lamps on the fender fronts
        put(s, x, 6, c)
        put(s, 23 - x, 6, c)
    s.blit(art(("#....#", "##..##", "#.##.#", "#....#"), {"#": BEETLE_RED}), (9, 6))
    beetle_disc(s, 8, 28, 7, 7, BEETLE_RED)
    digits(s, 10, 29, "5", r[4])


# Shop cars on vehicle(): gloss-black Charger R/T 70, Impala 67, Batmobile 89, taxi
CAR_RAMPS["muscle70"] = [(10, 10, 18), (24, 26, 38), (40, 44, 62), (66, 74, 100), (214, 224, 248)]
CAR_RAMPS["sedan67"] = [(14, 14, 18), (28, 28, 36), (44, 44, 56), (68, 70, 86), (196, 198, 212)]
CAR_RAMPS["bat"] = [(8, 8, 14), (20, 22, 32), (34, 38, 52), (66, 74, 98), (138, 150, 182)]
CAR_RAMPS["taxi"] = [(168, 98, 6), (228, 160, 0), (255, 204, 0), (255, 232, 88), (255, 250, 196)]
CLEAR = (0, 0, 0, 0)

STYLES["classic"] = dict(  # long hood, short roof, long boxy trunk (Impala 67)
    insets={1: 1, 2: 0, 17: 1, 28: 0, 38: 1},
    wheels=[(5, 11), (29, 35)],
    ws=(13, 16), roof=(17, 23), rear=(24, 27), glass_in=2, roof_in=3, head=2,
)  # fmt: skip


def deco_muscle70(s: Surf, g: dict) -> None:  # Charger R/T: chrome loop, black grille, blower, tail stripe
    r = CAR_RAMPS["muscle70"]
    hline(s, g["x0"][1], g["x1"][1], 1, CHROME[3])
    for y in (2, 3):  # hidden headlights: the grille fills the whole nose
        hline(s, g["x0"][y], g["x1"][y], y, CHROME[2])
        hline(s, g["x0"][y] + 1, g["x1"][y] - 1, y, OUT)
    put(s, 11, 2, CHROME[1])
    put(s, 12, 2, CHROME[1])
    # chrome blower through the hood: a wide open scoop over a narrower ribbed case and its shadow
    blower = ("444442", "3oooo1", "222221", ".3221.", ".3331.", ".3221.", ".0000.")
    s.blit(art(blower, dict(zip("01234", CHROME, strict=True), o=OUT)), (9, 4))
    for y in range(4, 10):  # gloss reflections down both front fenders
        put(s, 5, y, r[3])
        put(s, 18, y, r[2])
    for y, c in ((31, (244, 244, 250)), (32, (196, 200, 214))):  # bumblebee stripe round the tail
        hline(s, g["x0"][y], g["x1"][y], y, c)
    for x, y in ((5, 34), (6, 34), (5, 35)):  # gloss glint on the trunk
        put(s, x, y, r[3])


def deco_sedan67(s: Surf, g: dict) -> None:  # Impala 67: chrome nose, quad lamps, 3 tail lights a side
    r = CAR_RAMPS["sedan67"]
    hline(s, g["x0"][1], g["x1"][1], 1, CHROME[3])
    for x in range(g["x0"][2], g["x1"][2] + 1):
        put(s, x, 2, CHROME[2] if x in (3, 20) else OUT)
    for x in (4, 6, 17, 19):  # quad headlights
        put(s, x, 2, HEAD[1])
    hline(s, 8, 15, 2, CHROME[1])
    for y in range(3, 12):  # hood centre crease, caught by the light
        put(s, 11, y, r[3])
        put(s, 12, y, r[1])
    for y in (36, 37):
        hline(s, 3, 20, y, CHROME[3] if y == 36 else CHROME[2])
        for x in (4, 6, 8, 15, 17, 19):
            put(s, x, y, TAIL[2] if y == 36 else TAIL[1])
    hline(s, 4, 19, 38, CHROME[2])


BAT_FIN = (  # left rear quarter, cols 0-6 from row 20: ridge sweeping out, scalloped wing, '.' cut away
    "     R ", "     R ", "    Rw ", "    Rw ", "   Rww ", "   Rww ", "  Rwww ", "  Rwww ",
    " Rwwww ", " Rwwww ", " wRwww ", " .wRww ", " wwRww ", " Rwwww ", " .wRww ", " wwRww ",
    " Rwwww ", " Rw.   ", " R.    ",
)  # fmt: skip


AFTERBURNER = [(255, 255, 236), (255, 232, 140), (255, 150, 40), (220, 64, 26)]  # white core -> red tip
AFTERBURNER_LEN = (2, 4, 1, 3)  # rows of flame per frame: it gutters and roars


def afterburner(s: Surf, x0: int, x1: int, y: int, frame: int) -> None:
    """A flame from a nozzle across x0..x1, from row y down to the sprite's edge, hotter at the root."""
    n = AFTERBURNER_LEN[frame]
    for j in range(min(n, 40 - y)):
        inset = (j * (x1 - x0 + 1)) // (2 * n + 1)
        for x in range(x0 + inset, x1 - inset + 1):
            core = x1 - x0 > 1 and x0 + inset < x < x1 - inset
            put(s, x, y + j, AFTERBURNER[min(3, j * 4 // n + (0 if core else 1))])


def deco_bat(
    s: Surf, g: dict, frame: int
) -> None:  # 1989 Batmobile: turbine nose, canopy, bat fins, afterburner
    r = CAR_RAMPS["bat"]
    cyber_panel(s, g, 2, 37, r)  # one smooth hull: no cabin, no lamps
    hline(s, 6, 17, 1, CLEAR)  # the turbine pokes out alone at the front
    for y in range(3, 22):  # long fender pods either side of a low centre channel
        put(s, 5, y, r[3])
        put(s, 6, y, r[3])
        put(s, 18, y, r[1])
        put(s, 7, y, r[1])
        put(s, 17, y, r[3])
    turbine = art(
        [".MMMM.", "MdbddM", "MbHHdM", "MddbdM", ".MMMM."],
        {"M": METAL[3], "b": METAL[1], "d": (16, 16, 24), "H": METAL[0]},
    )
    s.blit(turbine, (9, 1))
    canopy = [(11, 12), (10, 13), (9, 14), (9, 14), (9, 14), (9, 14), (9, 14), (9, 14), (10, 13)]
    for j, (a, b) in enumerate(canopy):
        for x in range(a, b + 1):
            c = GLASS[3] if x - a + j == 3 else GLASS[2] if x == a else GLASS[0] if x == b else GLASS[1]
            s.set_at((x, 14 + j), c)
    for y in range(26, 36, 2):  # engine-deck slats
        hline(s, 7, 16, y, r[0])
    legend = {"R": (r[4], r[4]), "w": (r[3], r[2]), ".": (CLEAR, CLEAR)}  # (left, right): crests lit on both
    for j, row in enumerate(BAT_FIN):
        for x, ch in enumerate(row):
            if ch in legend:
                s.set_at((x, 20 + j), legend[ch][0])
                s.set_at((23 - x, 20 + j), legend[ch][1])
    hline(s, 5, 18, 38, CLEAR)
    s.blit(art(["oMMo", "M..M"], {"o": OUT, "M": METAL[1]}), (10, 36))
    afterburner(s, 11, 12, 37, frame)


def draw_bat(frame: int) -> Surf:  # the afterburner roars and gutters over 4 frames
    deco = lambda s, g: deco_bat(s, g, frame)  # noqa: E731
    return vehicle(24, 40, (1, 38), STYLES["sedan"], CAR_RAMPS["bat"], frame, deco)


def deco_taxi(s: Surf, g: dict) -> None:  # yellow cab: roof sign + checker band
    for y in range(16, 20):  # 4x2 sign with a dark frame
        hline(s, 9, 14, y, OUT)
    hline(s, 10, 13, 17, (255, 255, 236))
    hline(s, 10, 13, 18, (232, 210, 150))
    for y in (22, 23):
        for x in range(g["rx0"], g["rx1"] + 1):
            put(s, x, y, OUT if (x + y) % 2 else (246, 246, 250))


# Shop cars on vehicle(): turquoise Mystery Machine, Cybertruck, Optimus Prime
CAR_RAMPS["mystery_van"] = [(14, 74, 100), (22, 116, 146), (40, 160, 186), (84, 200, 214), (180, 240, 246)]
MYSTERY_VAN_GREEN = [(34, 100, 30), (62, 150, 38), (110, 196, 54), (170, 232, 96)]
CAR_RAMPS["cyber"] = [(74, 80, 90), (122, 128, 138), (162, 168, 176), (198, 202, 208), (232, 235, 238)]
CAR_RAMPS["robot_truck"] = [(110, 14, 24), (176, 22, 32), (226, 40, 44), (252, 100, 86), (255, 176, 154)]
ROBOT_TRUCK_BLUE = [(16, 30, 92), (28, 58, 156), (46, 98, 214), (100, 154, 248), (184, 216, 255)]

# box: a forward-control van, flat windshield right behind a short rounded nose
STYLES["box"] = dict(
    insets={1: 3, 2: 1, 3: 0, 37: 1, 38: 3},
    wheels=[(5, 11), (29, 35)],
    ws=(6, 8), roof=(9, 36), rear=None, glass_in=1, roof_in=1, head=2,
)  # fmt: skip


def cyber_panel(s: Surf, g: dict, y0: int, y1: int, ramp: Sequence[Color]) -> None:
    """Repaint body rows y0..y1 with the house shading: lit left edge, dark right edge."""
    for y in range(y0, y1 + 1):
        a, b = g["x0"][y], g["x1"][y]
        for x in range(a, b + 1):
            s.set_at((x, y), ramp[3 if x == a else 1 if x == b else 2])


MYSTERY_VAN_FLOWER = (".oo.oo.", "ooo.ooo", ".ooYoo.", "...Y...", ".ooYoo.", "ooo.ooo", ".oo.oo.")
MYSTERY_VAN_SPARE = (".TTTt.", "TgOOgt", "tgOOgt", ".tttt.")  # front spare: green cover, orange flower


def mystery_van_flower(s: Surf, cx: int, cy: int) -> None:  # four orange petals round a yellow heart
    for j, line in enumerate(MYSTERY_VAN_FLOWER):
        for i, ch in enumerate(line):
            if ch != ".":
                c = GOLD[3] if ch == "Y" else ORANGE[3] if i + j < 6 else ORANGE[2]
                put(s, cx + i - 3, cy + j - 3, c)


def deco_mystery_van(s: Surf, g: dict) -> None:  # turquoise van, green skirt, orange flowers, front spare
    gr = MYSTERY_VAN_GREEN
    cyber_panel(s, g, 1, g["ws"][0] - 1, gr)  # the green lower body shows at the nose, flanks and tail
    cyber_panel(s, g, g["r1"], g["bot"], gr)
    for y in range(g["r0"] + 4, g["r1"]):  # behind the cab windows
        for x, c in ((3, gr[3]), (4, gr[2]), (19, gr[2]), (20, gr[1])):
            s.set_at((x, y), c)
    for cx, cy in ((9, 16), (14, 24), (9, 32)):
        mystery_van_flower(s, cx, cy)
    s.blit(art(MYSTERY_VAN_SPARE, {"T": TIRE[1], "t": TIRE[0], "g": gr[2], "O": ORANGE[2]}), (9, 1))
    for x, y, c in ((5, 2, HEAD[1]), (6, 2, HEAD[0]), (4, 3, HEAD[0])):  # round headlamps
        put(s, x, y, c)
        put(s, 23 - x, y, c)


def deco_cyber(s: Surf, g: dict) -> None:  # two-tone steel split at the ridge, glass strip, LED bars
    r = CAR_RAMPS["cyber"]
    dark = r[:1] + r[:4]  # the rear slope: the same steel one step darker
    cyber_panel(s, g, 1, 18, r)
    cyber_panel(s, g, 20, 38, dark)
    for x, y in ((4, 1), (19, 1), (3, 2), (20, 2), (3, 37), (20, 37), (4, 38), (19, 38)):  # chamfered corners
        s.set_at((x, y), (0, 0, 0, 0))
    for x, y in ((6, 5), (7, 4), (8, 3), (7, 5)):  # glint on the hood
        put(s, x, y, r[4])
    for y in range(9, 19):  # black glass; the side windows lean in toward the ridge
        k = (y - 9) // 3
        hline(s, g["x0"][y] + 1 + k, g["x1"][y] - 1 - k, y, (18, 20, 26))
    for i in range(3):
        put(s, 7 + i, 11 + i, (70, 76, 92))  # reflection
    hline(s, g["x0"][19], g["x1"][19], 19, r[4])  # the ridge, halfway back
    for y in range(22, 36, 3):  # tonneau slats
        hline(s, 6, 17, y, dark[1])
    hline(s, 5, 18, 2, r[0])  # dark seam under the LED bar
    hline(s, 5, 18, 1, HEAD[1])
    put(s, 4, 2, HEAD[0])
    put(s, 19, 2, HEAD[0])
    hline(s, 4, 19, 37, TAIL[1])
    put(s, 4, 37, TAIL[2])
    put(s, 19, 37, TAIL[2])
    for wy0, wy1 in STYLES["jeep"]["wheels"]:  # angular black arches
        for y in range(wy0 - 1, wy1 + 2):
            s.set_at((g["x0"][y], y), (66, 68, 80))
            s.set_at((g["x1"][y], y), (40, 42, 52))
            if wy0 < y < wy1:
                s.set_at((g["x0"][y] + 1, y), (54, 56, 68))
                s.set_at((g["x1"][y] - 1, y), (40, 42, 52))


def deco_robot_truck(s: Surf, g: dict) -> None:  # red cab, chrome grille + stacks, blue rear, fifth wheel
    c, r = CHROME, CAR_RAMPS["robot_truck"]
    cyber_panel(s, g, 1, 19, r)
    cyber_panel(s, g, 21, 38, ROBOT_TRUCK_BLUE)
    hline(s, g["x0"][1], g["x1"][1], 1, c[3])  # bumper, headlamps at its ends
    for x in (4, 5, 18, 19):
        put(s, x, 1, HEAD[1])
    for y in range(2, 7):  # full-width chrome grille
        for x in range(g["x0"][y] + 1, g["x1"][y]):
            s.set_at((x, y), c[4] if y == 2 else c[3] if x % 2 else c[1])
    for y in range(8, 11):  # two-pane windshield
        hline(s, 5, 18, y, GLASS[0] if y == 8 else GLASS[1])
        hline(s, 11, 12, y, r[2])
    put(s, 6, 9, GLASS[3])
    put(s, 14, 9, GLASS[2])
    for x in range(6, 18, 3):  # amber cab-roof marker lights
        put(s, x, 12, HEAD[0])
    hline(s, g["x0"][20], g["x1"][20], 20, OUT)  # back wall of the cab
    for x0 in (1, 21):  # exhaust stacks behind the cab, open tops
        for y in range(14, 24):
            s.set_at((x0, y), OUT if y == 14 else c[3])
            s.set_at((x0 + 1, y), OUT if y == 14 else c[1])
    for y in range(25, 37):  # fifth-wheel plate, its slot flaring open to the rear
        for x in range(6, 18):
            d = math.hypot(x + 0.5 - 12, y + 0.5 - 30)
            slot = y > 30 and abs(x + 0.5 - 12) < 1 + (y - 30) / 3
            if d < 5:
                put(s, x, y, OUT if slot else c[3] if d < 2 else c[2] if x < 12 else c[1])
    for x in (4, 5, 18, 19):  # tail lights
        put(s, x, 37, TAIL[1])
    for x in (1, 2, 21, 22):  # mud flaps behind the drive wheels
        s.set_at((x, 37), OUT)


# Shop cars drawn whole (route B): moto, RC buggy, Flintstones car, tank, F1, monster truck
MOTO_JACKET = [(22, 30, 62), (34, 50, 100), (52, 76, 140), (88, 120, 190), (150, 180, 230)]  # blue leathers
RC_BUGGY = [(26, 92, 24), (46, 140, 30), (90, 192, 40), (156, 228, 72), (222, 252, 160)]
RC_BUGGY_HUB = [(24, 56, 150), (50, 116, 236), (150, 200, 255)]
MONSTER = [(56, 24, 96), (92, 40, 150), (132, 64, 200), (176, 112, 236), (226, 190, 255)]
MONSTER_FLAME = {"R": (214, 44, 24), "O": (255, 136, 28), "Y": (255, 228, 96)}
TANK = [(44, 52, 24), (72, 84, 36), (104, 118, 50), (140, 154, 74), (188, 198, 118)]
FORMULA = [(110, 8, 16), (180, 16, 24), (228, 30, 32), (255, 88, 72), (255, 172, 152)]
STONE_AGE_HIDE = [(150, 84, 26), (206, 130, 42), (238, 174, 66), (255, 212, 116), (255, 238, 180)]


def tank_box(s: Surf, x0: int, y0: int, x1: int, y1: int, ramp: Sequence[Color]) -> None:
    """Panel in the house shading: lit left column and top row, dark right column and bottom row."""
    for y in range(y0, y1 + 1):
        for x in range(x0, x1 + 1):
            i = 3 if x == x0 else 1 if x == x1 else 2
            i = i + 1 if y == y0 else 0 if y == y1 else i
            s.set_at((x, y), ramp[min(i, len(ramp) - 1)])  # short ramps (METAL, TAIL) top out early


def tank_tread(s: Surf, x0: int, y0: int, x1: int, y1: int, frame: int, c: Sequence[Color] = TIRE) -> None:
    """Tyre or track from above: tread bands that move one band per frame, so it rolls."""
    for y in range(y0, y1 + 1):
        for x in range(x0, x1 + 1):
            if x1 - x0 > 1 and y in (y0, y1) and x in (x0, x1):
                continue  # rounded corners
            s.set_at((x, y), c[0] if x == x1 else c[(y + frame) % 2])


def formula_body(s: Surf, half: dict[int, int], y0: int, y1: int, ramp: Sequence[Color]) -> None:
    """Symmetric body from a {row: half-width} table, shaded like vehicle() does."""
    hw = expand(half, y0, y1)
    for y in range(y0, y1 + 1):
        for x in range(12 - hw[y], 12 + hw[y]):
            i = 3 if x == 12 - hw[y] else 1 if x == 11 + hw[y] else 2
            s.set_at((x, y), ramp[min(4, i + 1) if y == y0 else 0 if y == y1 else i])


MOTO_ART = (
    "........................",
    "........................",
    "........................",
    "........................",
    "........................",
    "..........CwPc..........",
    "...CM.....CPRc.....Mc...",
    "...Mn.....CyYc.....cn...",
    "....c....nMMMMn....c....",
    "...jKKCCCMMMMMMcccKKj...",
    "....KK....PwRr....KK....",
    ".....KK..PwwRRr..KK.....",
    ".....KK..PwRRRr..KK.....",
    ".....KK..PRRRRr..KK.....",
    "......KK.PRRRRr.KK......",
    "......KK.PRRRRr.KK......",
    "......KK.gvVvvg.KK......",
    "......KK.HI!HHh.KK......",
    "......KK.IIIHHh.KK......",
    "......JKKIIHHHhKKk......",
    "......JKKHHHHhhKKk......",
    "......JKKKhhhgKKKk......",
    "......JKKKKKKKKKKk......",
    ".......JKKKKKKKKk.......",
    "........JKKKKKKk........",
    "........jKKKKKKj........",
    "...LLLb..jjjjjj..LLLb...",
    "...LBBb..ojjjjo..LBBb...",
    "...LBBb..jkkkkj.CLBBb...",
    "...xxxx..jkkkkj.Cxxxx...",
    "...LBBb..jjjjjj.CLBBb...",
    "...LBBb...PRRr..CLBBb...",
    "...bbbx...PRRr..cbbbx...",
    "..........tTTt..c.......",
    "................n.......",
)


def draw_moto(frame: int) -> Surf:  # wheels in line, red tank, white helmet, bars + mirrors, saddlebags
    legend = {"v": GLASS[0], "V": GLASS[2], "y": HEAD[1], "Y": HEAD[0], "t": TAIL[1], "T": TAIL[2], "o": OUT}
    for keys, ramp in (
        ("drRPw", CAR_RAMPS["red"]), ("jkKJ", MOTO_JACKET), ("ghHI!", CAR_RAMPS["white"]),
        ("ncMC", CHROME), ("xbBL", BARK),
    ):  # fmt: skip
        legend |= dict(zip(keys, ramp, strict=False))  # dark -> light; a short key skips the top tones
    s = new(24, 40)
    tank_tread(s, 11, 1, 12, 10, frame)
    tank_tread(s, 10, 30, 13, 38, frame)  # fat rear tyre
    s.blit(art(MOTO_ART, legend), (0, 0))
    return outline(s)


def rc_buggy_wheel(s: Surf, x0: int, y0: int, w: int, h: int, frame: int, hub: Sequence[Color]) -> None:
    """Big knobbly tyre: rolling tread, notches on the outer side, a round hub in the middle."""
    tank_tread(s, x0, y0, x0 + w - 1, y0 + h - 1, frame)
    out = x0 if x0 < 12 else x0 + w - 1
    for y in range(y0 + 1, y0 + h - 1):
        if (y + frame) % 2:
            s.set_at((out, y), (0, 0, 0, 0))  # the outline() pass fills these -> knobs
    rim = art((".hh.", "hHLh", "hHHh", ".hh."), dict(zip("hHL", hub, strict=True)))
    s.blit(rim, (x0 + (w - 4) // 2, y0 + h // 2 - 2))


RC_BUGGY_LOGO = ("##...##", "#.#.#..", "##..#..", "#.#.#..", "#.#..##")  # "RC" on the hood


def draw_rc_buggy(frame: int) -> Surf:  # green open buggy, black wheels with blue hubs, red-tipped antenna
    s, g = new(24, 40), RC_BUGGY
    for x, y, h in ((1, 3, 11), (18, 3, 11), (1, 23, 13), (18, 23, 13)):
        rc_buggy_wheel(s, x, y, 5, h, frame, RC_BUGGY_HUB)
    for y in (6, 10, 27, 32):  # suspension arms
        hline(s, 6, 17, y, METAL[0])
    formula_body(s, {3: 4, 10: 5, 23: 4, 34: 3}, 3, 35, g)
    hline(s, 7, 16, 2, METAL[1])  # front bumper
    s.blit(art(RC_BUGGY_LOGO, {"#": (250, 252, 240)}), (8, 5))
    tank_box(s, 9, 12, 14, 20, (g[0], g[0], g[0], g[1], g[1]))  # open cockpit
    tank_box(s, 10, 15, 13, 19, CAR_RAMPS["black"])  # seat
    for y in range(11, 22):  # black roll cage
        put(s, 8, y, OUT)
        put(s, 15, y, OUT)
    for y in (11, 21, 22):
        hline(s, 8, 15, y, OUT)
    for y in range(24, 32, 2):  # engine fins
        hline(s, 10, 13, y, METAL[3])
        hline(s, 10, 13, y + 1, METAL[1])
    for y in range(23, 37):  # silver whip antenna, bent back by the wind
        put(s, 14 + (y - 23) // 5, y, CHROME[3])
    tank_box(s, 16, 36, 17, 37, TAIL)
    return outline(s)


MONSTER_STYLE = dict(  # a pickup cab on the body only; the giant wheels come from rc_buggy_wheel
    insets={1: 1, 2: 0, 30: 1}, wheels=[],
    ws=(10, 12), roof=(13, 19), rear=(20, 20), glass_in=1, roof_in=2, head=1,
)  # fmt: skip
MONSTER_FLAMES = ("YYYYYYYY", "OYYYYYYO", "OYOYYOYO", "ROORROOR", "RO.RR.OR", "R..R...R", "R.......")


def monster_deco(s: Surf, g: dict) -> None:  # hood flames + pickup bed
    s.blit(art(MONSTER_FLAMES, MONSTER_FLAME), (4, 2))
    tank_box(s, 4, 22, 11, 29, CAR_RAMPS["black"])


def draw_monster(frame: int) -> Surf:  # jeep on huge wheels out of the corners, flames on the hood
    s = new(24, 40)
    for x, y in ((1, 1), (15, 1), (1, 23), (15, 23)):
        rc_buggy_wheel(s, x, y, 8, 16, frame, CHROME[1:4])
    s.blit(vehicle(16, 32, (1, 30), MONSTER_STYLE, MONSTER, frame, monster_deco), (4, 4))
    return outline(s)


def draw_stone_age(frame: int) -> Surf:  # stone rollers, log frame, leopard-print canopy
    s, rng = new(24, 40), random.Random("stone_age")
    for y0, y1 in ((2, 8), (29, 38)):  # stone drums: lit top, shaded bottom, grooves roll round
        for y in range(y0, y1 + 1):
            for x in range(2, 22):
                if (y in (y0, y1) and x in (2, 3, 20, 21)) or (y in (y0 + 1, y1 - 1) and x in (2, 21)):
                    continue  # rounded ends
                i = 4 if y == y0 else 0 if y == y1 else 3 if y < y0 + 3 else 2 if y < y1 - 2 else 1
                if (y + 2 * frame) % 4 == 0 and y0 < y < y1:
                    i = 0
                s.set_at((x, y), STONE[max(0, i - (rng.random() < 0.15))])
        for x in (1, 22):  # wooden axle ends
            put(s, x, (y0 + y1) // 2, BARK[3])
    for x in (4, 17):  # side logs ride over the drums: bark grain, sawn ends with rings
        tank_box(s, x, 1, x + 2, 37, BARK)
        for y in range(4, 36, 3):
            put(s, x + 1, y, BARK[1])
        for y in (1, 37):
            hline(s, x, x + 2, y, BARK[4])
            put(s, x + 1, y, BARK[2])
    for y in (11, 26):  # cross logs
        tank_box(s, 4, y, 19, y + 1, BARK)
    for y in range(13, 26):  # canopy, scalloped front and back
        for x in range(5, 19):
            if not (y in (13, 25) and x % 2):
                s.set_at((x, y), STONE_AGE_HIDE[3 if x == 5 or y == 13 else 1 if x == 18 else 2])
    for gy in range(14, 24, 4):  # leopard rosettes on a jittered grid
        for gx in range(6, 17, 4):
            spot = rng.choice((("dd", "d."), (".d", "dd"), ("d.d", ".d."), ("dd", ".d")))
            x, y = gx + rng.randint(0, 1) + (gy // 4) % 2, gy + rng.randint(0, 1)
            s.blit(art(spot, {"d": (64, 34, 16)}), (x, y))
    return outline(s)


def draw_tank(frame: int) -> Surf:  # tracks, olive hull, round turret, gun to row 0, white star
    s = new(24, 40)
    for x in (1, 18):
        tank_tread(s, x, 2, x + 4, 38, frame, (METAL[0], METAL[2]))
    tank_box(s, 6, 3, 17, 38, TANK)
    hline(s, 7, 16, 4, TANK[4])  # glacis plate catches the light
    for y in range(33, 37, 2):  # engine grille
        hline(s, 8, 15, y, TANK[0])
    turret = (TANK[0], TANK[1], TANK[2], TANK[2], TANK[3])  # darker than the hull: cast steel, not a ball
    s.blit(blob(16, 15, [(8, 7.5, 7, 6.5, 0)], turret, "turret", jitter=0), (4, 11))  # room for its ring
    tank_box(s, 13, 18, 15, 20, TANK)  # hatch
    tank_box(s, 10, 0, 13, 2, TANK)  # muzzle brake
    tank_box(s, 9, 11, 14, 13, TANK)  # mantlet
    for y in range(3, 11):
        put(s, 11, y, TANK[3])
        put(s, 12, y, TANK[1])
    star = ("...#...", "...#...", "#######", ".#####.", "..###..", ".##.##.", ".#...#.")
    s.blit(art(star, {"#": (240, 240, 232)}), (9, 25))
    return outline(s)


def draw_formula(frame: int) -> Surf:  # narrow red nose, wide wings, four exposed wheels
    s, cab = new(24, 40), CAR_RAMPS["black"]
    for x0, y0, x1, y1 in ((1, 6, 4, 12), (19, 6, 22, 12), (1, 26, 5, 35), (18, 26, 22, 35)):
        tank_tread(s, x0, y0, x1, y1, frame)
    for y in (8, 10, 29, 32):  # wishbones
        hline(s, 5, 18, y, METAL[0])
    formula_body(s, {2: 1, 7: 2, 14: 3, 16: 6, 25: 5, 27: 3, 31: 2}, 2, 34, FORMULA)
    tank_box(s, 1, 1, 22, 3, FORMULA)  # front wing
    tank_box(s, 3, 35, 20, 38, FORMULA)  # rear wing
    for x in (1, 22):
        tank_box(s, x, 1, x, 4, cab)  # endplates
    for x in (3, 20):
        tank_box(s, x, 34, x, 38, cab)
    tank_box(s, 10, 15, 13, 20, cab)  # cockpit
    s.blit(blob(4, 4, [(2, 2, 2, 2, 0)], CAR_RAMPS["yellow"], "helmet", jitter=0, edge=None), (10, 16))
    hline(s, 10, 13, 14, METAL[2])  # halo
    hline(s, 10, 13, 21, OUT)  # airbox
    return outline(s)


# Shop cars on vehicle() (g5): Gol bolinha, Chevette, Fiat 147, Uno with a ladder, Opala SS, Brasilia
CAR_RAMPS["gol_bolinha"] = [(70, 78, 96), (124, 132, 150), (172, 178, 192), (214, 218, 228), (246, 248, 252)]
CAR_RAMPS["chevette"] = [(122, 90, 54), (174, 138, 92), (210, 180, 132), (234, 212, 170), (252, 240, 212)]
CAR_RAMPS["fiat147"] = [(170, 92, 30), (226, 140, 56), (250, 180, 96), (255, 210, 146), (255, 238, 204)]
CAR_RAMPS["uno_escada"] = WHITE
CAR_RAMPS["opala"] = [(12, 40, 26), (22, 70, 42), (36, 104, 62), (70, 148, 94), (160, 214, 170)]
CAR_RAMPS["brasilia"] = [(170, 140, 0), (226, 196, 10), (252, 230, 50), (255, 244, 130), (255, 252, 214)]
G5_BLACK = [(28, 30, 40), (54, 56, 70)]  # plastic bumpers and grilles: shade, lit
UNO_ESCADA_ALU = [(96, 102, 118), (150, 156, 172), (196, 202, 214), (236, 240, 248)]

STYLES["g5_hatch"] = dict(  # Gol G2: round bubble nose and tail, long roof
    insets={1: 5, 2: 3, 3: 1, 4: 0, 32: 1, 34: 2, 36: 3, 37: 4, 38: 6},
    wheels=[(6, 12), (27, 33)],
    ws=(11, 14), roof=(15, 28), rear=None, glass_in=2, roof_in=3, head=3,
)  # fmt: skip
STYLES["g5_notch"] = dict(  # Chevette: square three-box sedan, nose raked to a point
    insets={1: 3, 2: 1, 3: 0, 38: 1},
    wheels=[(6, 12), (28, 34)],
    ws=(11, 14), roof=(15, 24), rear=(25, 27), glass_in=2, roof_in=3, head=2,
)  # fmt: skip
STYLES["g5_box"] = dict(  # Fiat 147 / Uno: short square nose, tall long cabin, upright hatch
    insets={1: 1, 2: 0, 38: 1},
    wheels=[(5, 11), (28, 34)],
    ws=(8, 11), roof=(12, 31), rear=(32, 34), glass_in=1, roof_in=4, head=2,
)  # fmt: skip
STYLES["g5_wagon"] = dict(  # Brasilia: short front lid, long flat roof, big upright rear glass
    insets={1: 1, 2: 0, 38: 1},
    wheels=[(5, 11), (28, 34)],
    ws=(9, 12), roof=(13, 30), rear=None, glass_in=2, roof_in=3, head=2,
)  # fmt: skip


def g5_side_glass(s: Surf, x: int, y0: int, y1: int, pillars: Sequence[int], body: Color, lit: bool) -> None:
    """A column of side glass from y0 to y1, cut by body-colour pillars."""
    for y in range(y0, y1 + 1):
        put(s, x, y, body if y in pillars else GLASS[(2 if y < y0 + 3 else 1) if lit else 0])


def deco_gol_bolinha(s: Surf, g: dict) -> None:  # silver bubble: rounded flanks, oval hatch glass, VW badge
    r = CAR_RAMPS["gol_bolinha"]
    for y in range(4, 35):  # rounded flanks: a second lit column, a second shaded one
        put(s, g["x0"][y] + 1, y, r[3])
        put(s, g["x1"][y] - 1, y, r[1])
    for x, y in ((6, 15), (17, 15), (6, 28), (17, 28)):  # round the roof's corners into the glass
        put(s, x, y, GLASS[1])
    for y, half in ((29, 4), (30, 5), (31, 5), (32, 4)):  # oval hatch window
        for x in range(12 - half, 12 + half):
            put(s, x, y, GLASS[1] if x == 12 - half + 1 and y < 32 else GLASS[0])
    hline(s, 8, 15, 4, r[1])  # slim grille between the wrap-round lamps, badge in the middle
    s.blit(art((".cc.", "cddc", ".cc."), {"c": CHROME[3], "d": r[0]}), (10, 3))
    for x, y, c in ((5, 3, HEAD[1]), (6, 3, HEAD[1]), (7, 3, HEAD[0]), (4, 4, HEAD[1]), (5, 4, HEAD[0])):
        put(s, x, y, c)
        put(s, 23 - x, y, c)
    for x in range(6, 18):  # tail lamps wrap the round tail, plate between
        put(s, x, 35, TAIL[2] if x in (6, 17) else TAIL[1] if x in (7, 8, 15, 16) else r[1])


def deco_chevette(s: Surf, g: dict) -> None:  # beige: raked nose, split grille, bowtie, chrome bumpers
    r = CAR_RAMPS["chevette"]
    for y in (1, 2):  # the raked nose panel faces the sky: lit
        for x in range(g["x0"][y], g["x1"][y] + 1):
            put(s, x, y, r[4] if x < 12 else r[3])
    for y in (3, 4):  # two grille halves either side of the body-colour centre bar
        for x0, x1 in ((4, 10), (13, 19)):
            hline(s, x0, x1, y, OUT if y == 3 else G5_BLACK[1])
        hline(s, 11, 12, y, r[3] if y == 3 else r[2])
    for x in (4, 5, 18, 19):  # square lamps at the grille ends
        put(s, x, 3, HEAD[1])
        put(s, x, 4, HEAD[0])
    s.blit(art((".gggg", "GGGG."), {"g": GOLD[3], "G": GOLD[2]}), (10, 3))  # slanted bowtie in the split
    for y in range(8, 11):  # bonnet crease
        put(s, 11, y, r[3])
        put(s, 12, y, r[1])
    hline(s, 5, 18, 28, r[1])  # trunk lid seam
    for x in (4, 5, 6, 17, 18, 19):  # square tail lamps
        put(s, x, 36, TAIL[1])
        put(s, x, 37, TAIL[0])
    hline(s, g["x0"][38], g["x1"][38], 38, CHROME[2])


def deco_fiat147(s: Surf, g: dict) -> None:  # pale orange box: two-column glasshouse, black plastic ends
    r = CAR_RAMPS["fiat147"]
    for x, lit, c in ((g["rx0"] - 2, True, r[3]), (g["rx0"] - 1, True, r[3]), (g["rx1"] + 1, False, r[1])):
        g5_side_glass(s, x, 12, 30, (21,), c, lit)
    g5_side_glass(s, g["rx1"] + 2, 12, 30, (21,), r[1], False)
    hline(s, g["x0"][1], g["x1"][1], 1, G5_BLACK[1])  # black bumper over the nose
    for y in (3, 4):  # full-width black front panel framing the square lamps
        hline(s, g["x0"][y], g["x1"][y], y, G5_BLACK[0])
    for x in (4, 5, 6, 17, 18, 19):
        put(s, x, 3, HEAD[1])
        put(s, x, 4, HEAD[0])
    for x in range(9, 15, 2):  # grille slats
        put(s, x, 4, G5_BLACK[1])
    for x in (4, 5, 18, 19):
        put(s, x, 36, TAIL[1])
    for y in (37, 38):
        hline(s, g["x0"][y], g["x1"][y], y, G5_BLACK[1] if y == 37 else G5_BLACK[0])


def deco_uno_escada(s: Surf, g: dict) -> None:  # white Uno, roof bars, aluminium ladder as long as the car
    a, w = UNO_ESCADA_ALU, WHITE
    for y in (1, 37, 38):
        hline(s, g["x0"][y], g["x1"][y], y, G5_BLACK[1] if y < 38 else G5_BLACK[0])
    hline(s, 7, 11, 3, G5_BLACK[0])  # small grille offset to the left, as on the Uno
    for x in (4, 5, 18, 19):
        put(s, x, 36, TAIL[1])
    for y in (13, 30):  # roof bars poking out either side of the ladder
        hline(s, g["rx0"] - 1, g["rx1"] + 1, y, OUT)
    for y in range(1, 39):  # rails on top, rungs every 3 rows each throwing a shadow on the car
        if y % 3 == 1 and 1 < y < 38:
            hline(s, 9, 14, y, a[2])
            if s.get_at((9, y + 1))[:3] in (w[2], w[3]):
                hline(s, 9, 14, y + 1, w[1])
        put(s, 8, y, a[3])
        put(s, 15, y, a[1])
        if g["r0"] <= y <= g["r1"]:
            put(s, 16, y, a[0])


def deco_opala(s: Surf, g: dict) -> None:  # dark green coupe, two black SS stripes, chrome, quad lamps
    hline(s, g["x0"][1], g["x1"][1], 1, CHROME[3])
    for x in range(g["x0"][2], g["x1"][2] + 1):
        put(s, x, 2, CHROME[1] if x in (3, 20, 11, 12) else OUT)
    for x in (4, 6, 17, 19):
        put(s, x, 2, HEAD[1])
    for y in range(3, 37):  # the stripes run nose to tail, over the roof too
        if g["ws"][0] <= y < g["r0"] or g["r1"] < y <= 27:
            continue
        for x in (8, 9, 14, 15):
            put(s, x, y, (16, 18, 24) if x in (8, 14) else (44, 48, 60))
    for y in (36, 37):
        for x in (4, 5, 6, 17, 18, 19):
            put(s, x, y, TAIL[1] if y == 36 else TAIL[0])
    hline(s, 3, 20, 37, CHROME[3])
    hline(s, 4, 19, 38, CHROME[2])


def deco_brasilia(s: Surf, g: dict) -> None:  # canary wagon: round lamps, VW badge, wagon glass all round
    r = CAR_RAMPS["brasilia"]
    hline(s, g["x0"][1], g["x1"][1], 1, CHROME[3])
    hline(s, g["x0"][2], g["x1"][2], 2, r[3])
    lamp = art((".hH.", "hHHh", "hHHh", ".hh."), {"H": HEAD[1], "h": HEAD[0]})
    s.blit(lamp, (3, 2))
    s.blit(lamp, (17, 2))
    s.blit(art((".cc.", "cddc", "cddc", ".cc."), {"c": CHROME[3], "d": r[1]}), (10, 3))
    for x in (4, 19):
        put(s, x, 6, ORANGE[2])  # indicators under the lamps
    g5_side_glass(s, g["rx0"] - 1, g["r0"] + 1, 31, (19, 25), r[3], True)  # three side windows a side
    g5_side_glass(s, g["rx1"] + 1, g["r0"] + 1, 31, (19, 25), r[1], False)
    for y in range(31, 36):  # big rear glass
        for x in range(5, 19):
            put(s, x, y, GLASS[1] if x == 6 and y < 35 else GLASS[2] if x + y == 38 else GLASS[0])
    for x in (4, 5, 18, 19):
        put(s, x, 36, TAIL[1])
    hline(s, g["x0"][38], g["x1"][38], 38, CHROME[2])


# Film/TV cars (g6): DeLorean time machine, Ecto-1, KITT, Eleanor
RAMP_DELOREAN = [(86, 88, 94), (138, 140, 144), (178, 178, 176), (210, 210, 206), (242, 242, 238)]
DELOREAN_BRUSH = (188, 188, 184)  # the grain: every other column a hair lighter
DELOREAN_DECK = [OUT, (40, 42, 52), (60, 62, 74), (92, 96, 112), (120, 124, 140)]  # black reactor deck
DELOREAN_FUSION = [(170, 164, 150), (220, 214, 196), (255, 252, 238)]  # Mr. Fusion: lid, rim, body
RAMP_ECTO1 = [(146, 140, 130), (194, 190, 178), (232, 228, 216), (248, 246, 236), (255, 255, 248)]
ECTO1_RED = [(120, 14, 24), (186, 26, 34), (228, 44, 46), (255, 110, 96)]
RAMP_KITT = [(6, 6, 10), (16, 18, 26), (30, 32, 44), (64, 70, 92), (168, 178, 210)]
RAMP_ELEANOR = [(60, 62, 62), (94, 96, 96), (124, 126, 124), (160, 162, 158), (206, 208, 202)]
ELEANOR_STRIPE = [(14, 14, 18), (26, 26, 32), (44, 44, 52)]  # shade, body, lit

STYLES["g6_wedge"] = dict(  # DMC-12: flat wedge nose, boxy flanks, louvred rear glass
    insets={1: 2, 2: 1, 3: 0, 38: 1},
    wheels=[(6, 12), (28, 34)],
    ws=(12, 15), roof=(16, 23), rear=(24, 27), glass_in=2, roof_in=3, head=2,
)  # fmt: skip
STYLES["g6_wagon"] = dict(  # Cadillac Miller-Meteor: long hood, long flat roof, short finned tail
    insets={1: 2, 2: 1, 3: 0},
    wheels=[(5, 11), (29, 35)],
    ws=(11, 13), roof=(14, 32), rear=None, glass_in=2, roof_in=2, head=2,
)  # fmt: skip
STYLES["g6_firebird"] = dict(  # third-gen Trans Am: pointed nose, T-top, big bubble hatch
    insets={1: 5, 2: 3, 3: 2, 4: 1, 6: 0, 37: 1, 38: 2},
    wheels=[(6, 12), (28, 34)],
    ws=(13, 16), roof=(17, 21), rear=(22, 28), glass_in=2, roof_in=3, head=3,
)  # fmt: skip
STYLES["g6_fastback"] = dict(  # '67 Mustang fastback: long hood, short roof, sloping glass, ducktail
    insets={1: 2, 2: 1, 3: 0, 16: 1, 27: 0, 38: 1},
    wheels=[(5, 11), (29, 35)],
    ws=(12, 15), roof=(16, 21), rear=(22, 27), glass_in=2, roof_in=3, head=2,
)  # fmt: skip


def deco_delorean(s: Surf, g: dict, frame: int) -> None:  # brushed steel, gull-wing seam, louvres, time gear
    r = RAMP_DELOREAN
    for y in range(g["top"] + 1, g["bot"] - 1):  # vertical brush grain on the flat mid-tone panels
        for x in range(g["x0"][y] + 1, g["x1"][y]):
            if x % 2 and s.get_at((x, y))[:3] == r[2]:
                put(s, x, y, DELOREAN_BRUSH)
    hline(s, g["x0"][1], g["x1"][1], 1, (58, 60, 68))  # black urethane bumper
    hline(s, 8, 15, 2, OUT)  # slim grille between the square lamps
    for y in range(g["r0"], g["r1"] + 1):  # gull-wing doors hinge on the roof spine
        put(s, 11, y, r[1])
    for y in range(24, 29):  # black louvres over the rear glass
        hline(s, 5, 18, y, OUT if y % 2 == 0 else (72, 74, 84))
    for y in range(22, 35):  # ribbed coils along the rear quarters, a charge racing up them
        spark = (y + 3 * frame) % 12 < 2
        put(s, 4, y, GLASS_CYAN[3] if spark else (238, 150, 56) if y % 2 else (44, 44, 54))
        put(s, 19, y, GLASS_CYAN[2] if spark else (196, 108, 36) if y % 2 else (36, 36, 46))
    tank_box(s, 6, 29, 17, 36, DELOREAN_DECK)  # reactor deck
    fusion = art((".cc.", "cCCc", "cCCc", "cCdc", ".cc."), dict(zip("dcC", DELOREAN_FUSION, strict=True)))
    s.blit(fusion, (10, 29))  # Mr. Fusion on top
    glow = [*GLASS_CYAN[1:], (255, 255, 255)][(0, 1, 2, 1)[frame] :][:2]  # the time vents pulse
    for x0 in (5, 14):  # the twin time vents, glowing
        tank_box(s, x0, 34, x0 + 4, 37, METAL)
        hline(s, x0 + 1, x0 + 3, 35, glow[1])
        hline(s, x0 + 1, x0 + 3, 36, glow[0])


def draw_delorean(frame: int) -> Surf:
    deco = lambda s, g: deco_delorean(s, g, frame)  # noqa: E731
    return vehicle(24, 40, (1, 38), STYLES["g6_wedge"], RAMP_DELOREAN, frame, deco)


ECTO1_LOGO = (  # no-ghost sign: red ring and slash over a white field, a dark ghost behind the slash
    "..RRRR..",
    ".RWWWWR.",
    "RWRRoWWR",
    "RWoRRoWR",
    "RWooRRWR",
    "RWoooRRR",
    ".RoWoWR.",
    "..RRRR..",
)  # fmt: skip


def deco_ecto1(s: Surf, g: dict, frame: int) -> None:  # chrome jewel nose, logo, cluttered rack, red fins
    red = ECTO1_RED
    hline(s, g["x0"][1], g["x1"][1], 1, CHROME[4])
    for x in range(g["x0"][2], g["x1"][2] + 1):
        put(s, x, 2, CHROME[3] if x % 2 else CHROME[1])
    for x in (4, 5, 18, 19):
        put(s, x, 2, HEAD[1])
    s.blit(art(ECTO1_LOGO, {"R": red[2], "W": (255, 255, 255), "o": OUT}), (8, 3))
    # roof rack: rails, a red light bar up front, a long tank, boxes, a radar dome, rear beacons
    for y in range(14, 32):
        put(s, 6, y, METAL[3])
        put(s, 17, y, METAL[1])
    for x in range(6, 18):  # light bar: the lamps take turns
        lit = (x // 2 - frame) % 4 < 2  # chasing round the bar
        put(s, x, 14, red[3] if lit else red[1])
        put(s, x, 15, red[2] if lit else red[0])
    tank_box(s, 7, 17, 9, 29, METAL)  # long silver tank
    hline(s, 7, 9, 17, CHROME[4])
    for y in range(17, 30, 2):  # ladder of conduits
        hline(s, 10, 11, y, METAL[2])
    tank_box(s, 12, 17, 16, 20, CAR_RAMPS["black"])  # gauge box
    put(s, 13, 18, GOLD[3])
    put(s, 15, 18, (110, 230, 120))
    s.blit(blob(5, 5, [(2.5, 2.5, 2.5, 2.5, 0)], WHITE, "ecto1_dome", jitter=0), (12, 22))  # radar dome
    tank_box(s, 12, 27, 16, 29, METAL)
    for i, x0 in enumerate((7, 15)):  # rear beacons, flashing in turn
        tank_box(s, x0, 30, x0 + 1, 31, red)
        if frame % 2 == i:
            hline(s, x0, x0 + 1, 30, (255, 220, 200))
    # red fins: flare from the rear wheels to the tail, the deck notched between them
    for y in range(27, 39):
        k = 1 if y < 30 else 2 if y < 34 else 3
        for i in range(k):
            put(s, 3 + i, y, red[3] if i == 0 else red[2])
            put(s, 20 - i, y, red[1] if i == 0 else red[2])
    for y in (37, 38):
        hline(s, 7, 16, y, CLEAR)
    hline(s, 6, 17, 36, CHROME[3])
    for x in (4, 19):  # bullet lights on the fin tips
        put(s, x, 38, TAIL[2])
        put(s, x, 37, TAIL[1])


def draw_ecto1(frame: int) -> Surf:
    deco = lambda s, g: deco_ecto1(s, g, frame)  # noqa: E731
    return vehicle(24, 40, (1, 38), STYLES["g6_wagon"], RAMP_ECTO1, frame, deco)


def deco_kitt(s: Surf, g: dict, frame: int) -> None:  # hidden lamps, red scanner sweep, T-top, bubble hatch
    r = RAMP_KITT
    cyber_panel(s, g, 2, 5, r)  # pop-up lamps stay down: smooth nose
    for y in range(4, 12):  # gloss streaks down the hood and its centre bulge
        put(s, 6, y, r[3])
        put(s, 11, y, r[3])
        put(s, 12, y, r[1])
    a, step = ((7, -1), (10, 1), (14, 1), (11, -1))[frame]  # the scanner's light sweeps and bounces
    for y in (2, 3):  # the scanner slot across the nose, the light trailing a fading tail
        hline(s, 7, 16, y, (64, 4, 8))
        hline(s, a, a + 2, y, (255, 56, 40))
        for d, c in ((1, (190, 20, 22)), (2, (120, 10, 14))):
            x = a + 1 - step * (1 + d)
            if 7 <= x <= 16:
                put(s, x, y, c)
    put(s, a + 1, 2, (255, 200, 180))
    for y in range(g["r0"], g["r1"]):  # T-top glass panels either side of the bar
        for x0 in (7, 13):
            hline(s, x0, x0 + 3, y, GLASS[2] if y == g["r0"] else GLASS[1])
            put(s, x0 + 3, y, GLASS[0])
    for j in range(5):  # glare across the bubble hatch
        hline(s, 7 + j, 8 + j, 23 + j, GLASS[2])
    put(s, 7, 23, GLASS[3])
    hline(s, 4, 19, 34, r[4])  # rear spoiler lip
    hline(s, 4, 19, 35, r[0])
    for x in range(5, 19):
        put(s, x, 37, TAIL[1] if x in (5, 6, 17, 18) else TAIL[0])


def draw_kitt(frame: int) -> Surf:
    deco = lambda s, g: deco_kitt(s, g, frame)  # noqa: E731
    return vehicle(24, 40, (1, 38), STYLES["g6_firebird"], RAMP_KITT, frame, deco)


def deco_eleanor(s: Surf, g: dict, frame: int) -> None:  # pepper grey, twin black stripes, centre lamps
    r, k = RAMP_ELEANOR, ELEANOR_STRIPE
    hline(s, g["x0"][1], g["x1"][1], 1, CHROME[3])
    hline(s, 8, 15, 2, OUT)  # grille with the two centre driving lamps
    for x in (10, 13):
        put(s, x, 2, HEAD[1])
    tank_box(s, 9, 5, 14, 9, r)  # centre hood scoop
    hline(s, 10, 13, 5, OUT)
    glass = set(range(g["ws"][0], g["ws"][1] + 1)) | set(range(22, 28))
    for y in range(3, 36):
        if y in glass:
            continue
        for x in (9, 10, 13, 14):
            put(s, x, y, k[2] if x in (9, 13) else k[1])
    hline(s, 10, 13, 5, OUT)
    for y in range(23, 26):  # side scoops on the rear quarters
        put(s, g["x0"][y], y, OUT)
        put(s, g["x1"][y], y, OUT)
    hline(s, 4, 19, 34, r[4])  # ducktail
    hline(s, 4, 19, 35, r[1])
    for x in range(4, 20):  # full-width sequential tail lamps
        lit = x in (9, 10, 13, 14) or (frame and x not in (11, 12))
        put(s, x, 37, CHROME[2] if x in (11, 12) else TAIL[2] if lit else TAIL[0])


def draw_eleanor(frame: int) -> Surf:
    deco = lambda s, g: deco_eleanor(s, g, frame)  # noqa: E731
    return vehicle(24, 40, (1, 38), STYLES["g6_fastback"], RAMP_ELEANOR, frame, deco)


# Shop cars (g7): Mr. Bean's Mini, Italian Job Mini, Jurassic Park Jeep, Compact Pussycat, Mean Machine, kart
STYLES["g7_mini"] = dict(  # short bonnet, upright windshield, long glasshouse, wheels in the corners
    insets={1: 4, 2: 2, 3: 1, 4: 0, 36: 1, 37: 2, 38: 4},
    wheels=[(4, 10), (30, 36)],
    ws=(9, 11), roof=(12, 31), rear=(32, 34), glass_in=1, roof_in=2, head=2,
)  # fmt: skip
CAR_RAMPS["mini_bean"] = [(52, 96, 20), (96, 150, 26), (150, 200, 40), (196, 232, 84), (236, 252, 170)]
MINI_BEAN_BONNET = [(18, 18, 24), (30, 30, 38), (44, 44, 54), (70, 70, 84), (110, 110, 128)]
MINI_BEAN_CUSHION = [(150, 96, 52), (196, 136, 76), (226, 172, 104), (244, 204, 140), (255, 232, 186)]
MINI_BEAN_CHAIR = [(70, 34, 22), (112, 58, 34), (150, 86, 48), (190, 124, 72), (226, 170, 112)]
CAR_RAMPS["mini_job"] = [(104, 12, 24), (170, 22, 34), (222, 40, 44), (250, 98, 86), (255, 178, 158)]
CAR_RAMPS["jurassic_jeep"] = [
    (112, 104, 86),
    (160, 150, 126),
    (198, 188, 162),
    (226, 218, 194),
    (248, 244, 228),
]
JURASSIC_JEEP_RED, JURASSIC_JEEP_YELLOW = (206, 34, 30), (255, 196, 30)
JURASSIC_JEEP_SEAT = [(70, 64, 56), (104, 96, 84), (140, 130, 112), (176, 166, 146), (210, 200, 180)]
JURASSIC_JEEP_TUB = [(22, 20, 22)] * 3 + [(40, 36, 34), (52, 48, 46)]
PENELOPE = [(150, 40, 110), (210, 80, 156), (246, 132, 194), (255, 182, 224), (255, 232, 246)]
PENELOPE_LACE = [(214, 190, 220), (255, 255, 255)]  # shade, lit
MEAN_MACHINE = [(44, 14, 62), (80, 26, 108), (120, 44, 156), (164, 88, 200), (218, 168, 246)]
KART_BLUE = [(20, 34, 110), (36, 64, 178), (70, 110, 232)]


def mini_bean_face(s: Surf, g: dict, ramp: Sequence[Color]) -> None:
    """Shared Mini front: chrome moustache grille, round lamps on the wings, roof gutter seams."""
    hline(s, 8, 15, 1, CHROME[3])
    for x in range(8, 16):
        put(s, x, 2, OUT if x % 2 else CHROME[2])
    for x, y, c in ((5, 2, HEAD[0]), (4, 3, HEAD[1]), (5, 3, HEAD[1]), (4, 4, HEAD[0]), (5, 4, HEAD[0])):
        put(s, x, y, c)
        put(s, 23 - x, y, c)
    for x in (4, 19):  # the welded seams standing proud round the roof
        for y in range(g["r0"], g["r1"] + 1, 5):
            put(s, x, y, ramp[3] if x == 4 else ramp[1])


def deco_mini_bean(s: Surf, g: dict) -> None:  # citron green, matte black bonnet, armchair on the roof
    b, c = MINI_BEAN_BONNET, MINI_BEAN_CHAIR
    mini_bean_face(s, g, CAR_RAMPS["mini_bean"])
    for y in range(3, 9):  # the black bonnet between the green wings
        for x in range(7, 17):
            put(s, x, y, b[3] if x == 7 else b[1] if x == 16 else b[4] if y == 3 else b[2])
    for x, y in ((9, 4), (9, 5), (10, 4)):
        put(s, x, y, b[4])
    # armchair from above, facing forward: rolled arms, a deep seat cushion, a high back at the rear
    tank_box(s, 6, 27, 17, 31, c)  # back, its top rolled toward the seat
    hline(s, 7, 16, 27, c[4])
    put(s, 6, 31, CLEAR)
    put(s, 17, 31, CLEAR)
    for x in (6, 15):
        tank_box(s, x, 16, x + 2, 28, c)  # arms
        hline(s, x + 1, x + 1, 16, c[4])
        put(s, x, 16, CLEAR)
        put(s, x + 2, 16, CLEAR)
    tank_box(s, 9, 18, 14, 26, MINI_BEAN_CUSHION)  # cushion, a lighter fabric sunk between the arms
    for y in range(17, 27):  # deep creases down both sides of it
        put(s, 9, y, c[0])
        put(s, 14, y, c[0])
    hline(s, 9, 14, 17, c[0])
    for x in (9, 12, 14):  # buttons tufting the back
        put(s, x, 29, c[1])


def deco_mini_job(s: Surf, g: dict) -> None:  # red Cooper S, white roof, roof rack, twin spot lamps
    w = WHITE
    mini_bean_face(s, g, CAR_RAMPS["mini_job"])
    for y in range(g["r0"], g["r1"] + 1):
        for x in range(g["rx0"], g["rx1"] + 1):
            put(s, x, y, w[4] if y == g["r0"] else w[3] if x < g["rx1"] else w[1])
    for y in range(14, 31):  # rack side rails, chrome tubes
        put(s, 6, y, CHROME[3])
        put(s, 17, y, CHROME[1])
    for y in (15, 20, 25):  # three tubular crossbars, each casting a shadow on the roof
        hline(s, 6, 17, y, CHROME[2])
        put(s, 7, y, CHROME[4])
        hline(s, 6, 17, y + 1, METAL[1])
        hline(s, 7, 16, y + 2, w[1])
    hline(s, 6, 17, 30, CHROME[2])
    hline(s, 7, 16, 31, w[1])
    for cx in (9, 14):  # twin spot lamps in front of the grille
        s.blit(art((".hh.", "hHHh", ".hh."), {"h": CHROME[1], "H": HEAD[1]}), (cx - 1, 1))


JURASSIC_JEEP_LOGO = (  # red disc, black T-rex skull, yellow band with the name across the bottom
    "..oooo..", ".orrrro.", "orrkkrro", "orkkrkro", "orrkkrro", "oyyyyyyo", ".oyyyyo.", "..oooo..",
)  # fmt: skip


def deco_jurassic_jeep(s: Surf, g: dict) -> None:  # sand Wrangler, red/yellow stripes, open top, roll bar
    r = CAR_RAMPS["jurassic_jeep"]
    for x in range(8, 16, 2):  # seven-slot grille
        put(s, x, 2, OUT)
    for x, c in ((4, HEAD[1]), (5, HEAD[0])):  # square lamps
        put(s, x, 1, c)
        put(s, 23 - x, 1, c)
    for y in range(3, 37):  # the red band and its yellow pinstripe down both flanks
        for k, c in enumerate((JURASSIC_JEEP_RED, JURASSIC_JEEP_RED, JURASSIC_JEEP_YELLOW)):
            x = g["x0"][y] + k
            put(s, x, y, c)
            put(s, 23 - x, y, c)
    for wy0, wy1 in STYLES["jeep"]["wheels"]:  # black flares over the stripe
        for y in range(wy0 - 1, wy1 + 2):
            s.set_at((g["x0"][y], y), (66, 66, 80))
            s.set_at((g["x1"][y], y), (40, 40, 52))
    for y in range(4, 9):  # hood centre bulge
        put(s, 11, y, r[3])
        put(s, 12, y, r[1])
    # open tub: dark floor, two front buckets, rear bench, roll bar with a light bar
    tank_box(s, 5, 13, 18, 33, JURASSIC_JEEP_TUB)
    for sx in (6, 13):
        tank_box(s, sx, 15, sx + 4, 20, JURASSIC_JEEP_SEAT)
        hline(s, sx + 1, sx + 3, 19, JURASSIC_JEEP_SEAT[4])  # headrest
    tank_box(s, 6, 25, 17, 28, JURASSIC_JEEP_SEAT)
    hline(s, 7, 9, 13, OUT)  # steering wheel
    for y in range(21, 33):  # roll-bar side hoops
        for x in (5, 18):
            put(s, x, y, METAL[3] if x == 5 else METAL[1])
    hline(s, 5, 18, 21, METAL[3])
    hline(s, 5, 18, 22, METAL[0])
    for x in (7, 10, 13, 16):  # four spot lamps on the bar
        put(s, x, 21, HEAD[1])
        put(s, x + 1, 21, HEAD[0])
    logo = {"o": OUT, "r": JURASSIC_JEEP_RED, "k": OUT, "y": JURASSIC_JEEP_YELLOW}
    s.blit(art(JURASSIC_JEEP_LOGO, logo), (8, 31))


def draw_penelope(frame: int) -> Surf:  # pink frilly roadster under a spinning frilled parasol
    s, p, lace = new(24, 40), PENELOPE, PENELOPE_LACE
    for x0, y0, y1 in ((1, 5, 11), (20, 5, 11), (1, 28, 35), (20, 28, 35)):
        tank_tread(s, x0, y0, x0 + 2, y1, frame)
    formula_body(s, {1: 5, 2: 7, 3: 8, 4: 9, 13: 8, 27: 9, 36: 8, 37: 7, 38: 5}, 1, 38, p)
    for y in range(4, 37):  # lace frill scalloped down both flanks
        x0 = 3 if 4 <= y < 13 or 27 <= y < 36 else 4
        put(s, x0, y, lace[1] if y % 2 else p[3])
        put(s, 23 - x0, y, lace[0] if y % 2 else p[1])
    for x, y, c in ((6, 2, HEAD[1]), (7, 2, HEAD[0]), (5, 3, HEAD[1]), (6, 3, HEAD[0])):
        put(s, x, y, c)
        put(s, 23 - x, y, c)
    heart = (".hh.hh.", "hHHhHHh", "hHHHHHh", ".hHHHh.", "..hHh..", "...h...")
    s.blit(art(heart, {"h": (196, 20, 80), "H": (255, 64, 120)}), (8, 3))
    for y, (a, b) in enumerate(((9, 14), (8, 15))):  # low curved windscreen
        hline(s, a, b, 10 + y, GLASS_CYAN[2] if y == 0 else GLASS_CYAN[1])
    for x in (5, 18):  # tail lamps
        put(s, x, 37, TAIL[1])
    # parasol: eight gores, hot pink and white, round a gold finial; a scalloped lace rim; it spins a
    # half gore a frame
    cy, rad = 22.0, 8.8
    for y in range(12, 33):
        for x in range(2, 22):
            dx, dy = x + 0.5 - 12, y + 0.5 - cy
            d, a = math.hypot(dx, dy), math.atan2(dy, dx)
            rim = rad - 0.9 * abs(math.sin(a * 8 + frame * math.pi / 2))
            if d < rim:
                gore = int((a / math.tau * 8 + frame * 0.5) % 8) % 2
                lit = dx + dy < 0
                if d > rim - 1.2:
                    c = lace[1] if lit else lace[0]
                elif gore:
                    c = p[3] if lit else p[2]
                else:
                    c = (255, 255, 255) if lit else (240, 220, 236)
                put(s, x, y, c)
    s.blit(art(("Gg", "gk"), {"G": GOLD[4], "g": GOLD[2], "k": GOLD[1]}), (11, 21))
    return outline(s)


def draw_mean_machine(frame: int) -> Surf:  # purple rocket car: long pointed nose, 00, twin rocket exhausts
    s, m = new(24, 40), MEAN_MACHINE
    tank_tread(s, 2, 9, 4, 15, frame)  # small front wheels tucked behind the nose
    tank_tread(s, 19, 9, 21, 15, frame)
    tank_tread(s, 1, 24, 4, 35, frame)  # big rear drive wheels
    tank_tread(s, 19, 24, 22, 35, frame)
    formula_body(s, {1: 1, 3: 2, 5: 3, 8: 4, 11: 5, 14: 6, 20: 7, 34: 6}, 1, 36, m)
    for y in range(3, 10):  # a lit ridge down the nose
        put(s, 11, y, m[4] if y < 6 else m[3])
    beetle_disc(s, 7, 10, 10, 7, (250, 248, 255))  # white race roundel
    digits(s, 8, 11, "00", m[0])
    tank_box(s, 8, 19, 15, 26, CAR_RAMPS["black"])  # cockpit
    for y, (a, b) in enumerate(((10, 13), (9, 14))):  # curved windscreen
        hline(s, a, b, 19 + y, GLASS[2] if y == 0 else GLASS[1])
    s.blit(blob(6, 5, [(3, 2.5, 3, 2.5, 0)], m, "dastardly", jitter=0, edge=None), (9, 21))  # aviator cap
    hline(s, 9, 14, 22, (250, 220, 120))  # goggles
    put(s, 11, 22, OUT)
    put(s, 12, 22, OUT)
    for x0 in (7, 13):  # twin rocket tubes down the tail
        tank_box(s, x0, 27, x0 + 3, 37, CHROME)
        hline(s, x0, x0 + 3, 31, CHROME[0])
        afterburner(s, x0, x0 + 3, 38, (frame + (x0 > 10) * 2) % 4)
    return outline(s)


def draw_kart(frame: int) -> Surf:  # red kart, fat exposed wheels, Mario's red cap with the white M
    s, r = new(24, 40), CAR_RAMPS["red"]
    for x0, y0, x1, y1 in ((1, 4, 5, 12), (18, 4, 22, 12), (1, 26, 5, 36), (18, 26, 22, 36)):
        tank_tread(s, x0, y0, x1, y1, frame)
        tank_box(s, x0 + 1, (y0 + y1) // 2 - 1, x1 - 1, (y0 + y1) // 2 + 1, GOLD)  # gold hubs
    for y in (7, 9, 29, 33):  # axles
        hline(s, 6, 17, y, METAL[0])
    formula_body(s, {1: 4, 3: 5, 10: 4, 11: 6, 37: 5}, 1, 38, r)
    hline(s, 7, 16, 1, CHROME[3])  # front bumper
    for y in range(3, 9):  # nose crease
        put(s, 11, y, r[3])
        put(s, 12, y, r[1])
    tank_box(s, 7, 11, 16, 27, [OUT, OUT, (40, 40, 52), (58, 58, 72), (80, 80, 96)])  # cockpit tub
    hline(s, 9, 14, 11, METAL[1])  # steering wheel, gloved hands on it
    for x in (8, 15):
        put(s, x, 11, (255, 255, 255))
    for y in range(12, 22):  # red sleeves reaching forward
        put(s, 8, y, r[3])
        put(s, 15, y, r[1])
    tank_box(s, 9, 21, 14, 26, KART_BLUE)  # blue overalls behind the cap
    cap = (
        "..bbbbbb..", ".rwwwwwwr.", "rwWwwwwWwr", "rwWWwwWWwr", "rwWwWWwWwr", "rwWwwwwWwr",
        "rrwwwwwwrr", "Lrrrrrrrrd", ".LLrrrrdd.", "..Lrrrdd..",
    )  # fmt: skip
    s.blit(art(cap, {"b": r[0], "r": r[2], "L": r[3], "d": r[1], "w": (255, 255, 255), "W": r[2]}), (7, 12))
    tank_box(s, 6, 27, 17, 28, METAL)  # engine behind the seat
    for x0 in (8, 13):  # chrome exhausts
        tank_box(s, x0, 30, x0 + 2, 37, CHROME)
        put(s, x0 + 1, 37, OUT)
    return outline(s)


# Shop cars (g8): Porsche 911 (Guards red), Ferrari F40 (rosso corsa), Lamborghini Countach, Batmobile 1966
CAR_RAMPS["porsche911"] = [(112, 14, 10), (178, 26, 16), (224, 44, 24), (252, 108, 70), (255, 188, 150)]
CAR_RAMPS["f40"] = [(104, 6, 14), (172, 12, 22), (220, 20, 30), (255, 76, 72), (255, 168, 160)]
CAR_RAMPS["countach"] = [(118, 124, 146), (176, 180, 200), (222, 226, 238), (244, 246, 252), (255, 255, 255)]
RAMP_BAT66 = [(6, 6, 10), (16, 16, 24), (30, 30, 44), (70, 74, 100), (196, 204, 234)]  # gloss black
BAT66_RED = [(150, 16, 24), (232, 40, 44), (255, 120, 104)]  # pinstripe: shade, stripe, lit

STYLES["g8_911"] = dict(  # round wings with the lamps on top, narrow greenhouse, fastback, rear hips
    insets={1: 4, 2: 2, 3: 1, 13: 2, 22: 1, 25: 0, 35: 1, 36: 2, 37: 3, 38: 5},
    wheels=[(5, 11), (26, 32)],
    ws=(11, 14), roof=(15, 19), rear=None, glass_in=2, roof_in=4, head=3,
)  # fmt: skip
STYLES["g8_f40"] = dict(  # wide, low and square-shouldered
    insets={1: 5, 2: 3, 3: 2, 4: 1, 9: 0},
    wheels=[(6, 12), (26, 32)],
    ws=(12, 15), roof=(16, 19), rear=None, glass_in=3, roof_in=5, head=3,
)  # fmt: skip
STYLES["g8_countach"] = dict(  # a wedge: pointed nose, windshield running on from the hood
    insets={1: 7, 2: 6, 3: 5, 4: 4, 5: 3, 6: 2, 7: 1, 22: 0, 38: 1},
    wheels=[(7, 13), (26, 32)],
    ws=(9, 15), roof=(16, 21), rear=None, glass_in=2, roof_in=4, head=4,
)  # fmt: skip
STYLES["g8_bat66"] = dict(  # long and low; the cabin is repainted as two bubbles
    insets={1: 1, 2: 0, 13: 1, 22: 0},
    wheels=[(5, 11), (27, 33)],
    ws=(13, 14), roof=(15, 22), rear=None, glass_in=2, roof_in=3, head=2,
)  # fmt: skip


def deco_porsche911(s: Surf, g: dict) -> None:  # bug-eye lamps on round wings, fastback, grille, ducktail
    r = CAR_RAMPS["porsche911"]
    for y in range(3, 11):  # wing crests either side of the lower front lid
        put(s, 5, y, r[3])
        put(s, 18, y, r[2])
        put(s, 7, y, r[1])
        put(s, 16, y, r[1])
    lamp = art((".WW.", "WWWH", "aHHb", ".bb."), {"a": CHROME[3], "b": CHROME[1], "W": HEAD[1], "H": HEAD[0]})
    hline(s, 8, 15, 1, CLEAR)  # the lid dips between the wings, so the lamps bulge forward
    hline(s, 8, 15, 2, r[3])
    s.blit(lamp, (4, 1))
    s.blit(pygame.transform.flip(lamp, True, False), (16, 1))
    hline(s, 11, 12, 4, CHROME[3])  # lid handle
    for j, y in enumerate(range(20, 25)):  # the rear window narrows down the fastback
        a, b = 7 + j // 2, 16 - j // 2
        for x in range(a, b + 1):
            put(s, x, y, GLASS[2] if x == a else GLASS[0] if x == b or y == 24 else GLASS[1])
    put(s, 8, 21, GLASS[3])
    for y in range(26, 31):  # engine grille: vertical slats in the lid
        for x in range(9, 15):
            put(s, x, y, OUT if x % 2 else r[1])
    for x in range(g["x0"][33] - 1, g["x1"][33] + 2):  # ducktail lip, lit on top, shadow behind it
        put(s, x, 32, r[4] if x < 9 else r[3])
        put(s, x, 33, r[2] if x < 12 else r[1])
        put(s, x, 34, r[0])
    for x in (5, 6, 7):  # tail lamps
        put(s, x, 36, TAIL[2] if x == 5 else TAIL[1])
        put(s, 23 - x, 36, TAIL[1])


def deco_f40(s: Surf, g: dict) -> None:  # NACA ducts, louvred engine cover, huge wing, four tail lamps
    r = CAR_RAMPS["f40"]
    for y in (3, 5):  # vent in the front lid
        hline(s, 9, 14, y, r[0])
    for x0 in (8, 13):  # NACA ducts ahead of the windshield: narrow mouth, flaring back
        for y, (a, b) in ((7, (1, 1)), (8, (1, 2)), (9, (0, 2)), (10, (0, 2))):
            hline(s, x0 + a, x0 + b, y, r[0])
            put(s, x0 + b + 1, y, r[3])
    for y in (17, 18, 19, 20, 23, 24, 25):  # NACA ducts in the doors, scoops ahead of the rear wheels
        put(s, g["x0"][y] + 1, y, OUT)
        put(s, g["x1"][y] - 1, y, OUT)
    for y in range(20, 32):  # perspex cover with louvres over the engine
        for x in range(6, 18):
            put(s, x, y, (r[0] if (y - 20) % 2 else r[3] if x == 6 else r[1] if x == 17 else r[2]))
    for x in range(1, 23):  # the wing: the whole width of the car, over a dark shadow
        put(s, x, 32, r[4] if x < 8 else r[3])
        put(s, x, 33, r[3] if x < 6 else r[2])
        put(s, x, 34, r[1])
        put(s, x, 35, OUT)
    for x in (1, 22):  # endplates
        for y in range(31, 36):
            put(s, x, y, r[0])
    hline(s, 4, 19, 36, OUT)
    for x in (4, 6, 16, 18):  # four round tail lamps
        put(s, x, 36, TAIL[2])
        put(s, x + 1, 36, TAIL[1])
        put(s, x, 37, TAIL[1])
        put(s, x + 1, 37, TAIL[0])


def deco_countach(s: Surf, g: dict) -> None:  # NACA side ducts, air boxes, V wing, black tail
    r, k = CAR_RAMPS["countach"], (40, 42, 56)
    for y in (3, 4):  # amber lamps along the edges of the wedge
        put(s, g["x0"][y] + 1, y, HEAD[0])
        put(s, g["x1"][y] - 1, y, HEAD[0])
    for y in range(16, 23):  # long NACA ducts slicing into the doors
        d = (y - 16) // 2
        put(s, g["x0"][y] + d, y, k)
        put(s, g["x1"][y] - d, y, k)
    for x0 in (3, 18):  # air boxes behind the side windows, black mouths facing forward
        for y in range(22, 28):
            for x in range(x0, x0 + 3):
                put(s, x, y, k if y < 24 else r[4] if x == x0 else r[1] if x == x0 + 2 else r[3])
    for y in range(23, 28, 2):  # engine-cover louvres
        hline(s, 8, 15, y, r[0])
    for x in range(2, 22):  # the V wing, apex forward, on a central pylon
        y = 27 + int(abs(x - 11.5) // 1.6)
        put(s, x, y - 1, r[0])
        put(s, x, y, r[4])
        put(s, x, y + 1, r[2] if x < 12 else r[1])
        put(s, x, y + 2, k)
    for y in range(35, 39):  # black tail panel, wide red lamps
        hline(s, g["x0"][y], g["x1"][y], y, k)
    hline(s, 4, 8, 36, TAIL[1])
    hline(s, 15, 19, 36, TAIL[1])
    put(s, 4, 36, TAIL[2])
    put(s, 15, 36, TAIL[2])


BAT66_LOGO = ("#...#..#...#", "##..####..##", "############", ".###.##.###.", "..#..##..#..")
BAT66_BUBBLE = (".ccc.", "cLggc", "cLggd", "clggd", "clggd", "clggd", ".cdd.")


def deco_bat66(s: Surf, g: dict, frame: int) -> None:  # red pinstripes, twin bubbles, forked fins, rocket
    r, red = RAMP_BAT66, BAT66_RED
    cyber_panel(s, g, 1, 38, r)
    hline(s, 8, 15, 1, CLEAR)  # the nose splits into two lamp pods round a chrome chain-cutter
    hline(s, 9, 14, 2, CLEAR)
    for x, y, c in ((11, 1, CHROME[4]), (12, 1, CHROME[2]), (11, 2, CHROME[3]), (12, 2, CHROME[1])):
        put(s, x, y, c)
    for x, c in ((4, HEAD[1]), (5, HEAD[0]), (18, HEAD[0]), (19, HEAD[1])):
        put(s, x, 2, c)
    for y in range(3, 30):  # pinstripes just inside both flanks
        put(s, g["x0"][y] + 1, y, red[2] if y < 20 else red[1])
        put(s, g["x1"][y] - 1, y, red[1])
    s.blit(art(BAT66_LOGO, {"#": red[1]}), (6, 5))
    for y in range(3, 12):  # gloss on the fenders
        put(s, 5, y, r[4] if y < 5 else r[3])
        put(s, 18, y, r[2])
    legend = {"c": CHROME[2], "d": CHROME[1], "g": GLASS[1], "L": GLASS[3], "l": GLASS[2]}
    for x0 in (5, 12):  # two bubble canopies side by side
        s.blit(art(BAT66_BUBBLE, legend), (x0, 13))
    for y in range(23, 39):  # fins: red crests sweeping out to points either side of a notched tail
        d = (y - 23) // 5
        put(s, 7 - d, y, red[2])
        put(s, 16 + d, y, red[1])
        if y > 33:
            hline(s, 8 - d, 15 + d, y, CLEAR)
    for y in range(28, 36):  # rocket tube
        hline(s, 10, 13, y, CHROME[2])
        put(s, 10, y, CHROME[3])
        put(s, 13, y, CHROME[1])
    hline(s, 10, 13, 35, OUT)
    afterburner(s, 10, 13, 36, frame)


def draw_bat66(frame: int) -> Surf:  # the rocket's flame roars and gutters over 4 frames
    deco = lambda s, g: deco_bat66(s, g, frame)  # noqa: E731
    return vehicle(24, 40, (1, 38), STYLES["g8_bat66"], RAMP_BAT66, frame, deco)


# Shop cars (g9): shopping cart, golf cart, sofa, tractor, SAMU 192, fire engine
SHOPPING_CART_RED = [(120, 14, 26), (196, 30, 40), (240, 64, 64), (255, 140, 130)]
SHOPPING_CART_HOLE = (34, 36, 52)
GOLF_CART_CANOPY = [(150, 150, 140), (200, 200, 190), (232, 232, 224), (246, 246, 240), (255, 255, 252)]
GOLF_CART_BAG = [(16, 30, 80), (28, 52, 140), (52, 90, 200), (120, 160, 240)]
SOFA = [(66, 14, 34), (106, 26, 50), (146, 40, 66), (188, 70, 92), (228, 128, 140)]  # wine velvet
TRACTOR = [(16, 60, 28), (28, 96, 40), (48, 136, 52), (96, 182, 72), (176, 226, 132)]
TRACTOR_YELLOW = [(196, 140, 0), (250, 200, 20), (255, 236, 120)]
SAMU_RED = [(150, 14, 24), (222, 30, 36), (255, 110, 96)]
SAMU_ORANGE = [(214, 96, 10), (255, 150, 30)]
FIRE_TRUCK = [(112, 8, 16), (180, 16, 24), (226, 28, 32), (255, 84, 72), (255, 168, 150)]

STYLES["g9_samu"] = dict(  # tall Ducato-style van: short sloping nose, long high roof
    insets={1: 3, 2: 1, 3: 0, 37: 1, 38: 2},
    wheels=[(5, 11), (29, 35)],
    ws=(5, 8), roof=(9, 37), rear=None, glass_in=1, roof_in=1, head=2,
)  # fmt: skip
STYLES["g9_fire"] = dict(  # flat-fronted cab over the front axle, body to the tail
    insets={1: 1, 2: 0},
    wheels=[(5, 11), (29, 35)],
    ws=(4, 6), roof=(7, 37), rear=None, glass_in=1, roof_in=1, head=2,
)  # fmt: skip


def draw_shopping_cart(frame: int) -> Surf:  # wire basket, red handle and bumpers, four castors
    s, c, red = new(24, 40), CHROME, SHOPPING_CART_RED
    for x0, y0 in ((3, 3), (19, 3), (1, 28), (21, 28)):  # castors poke out under the corners
        tank_tread(s, x0, y0, x0 + 1, y0 + 4, frame)
    half = {y: 6 + (y - 3) * 3 // 31 for y in range(3, 34)}  # basket flares from the nose to the handle
    for y in range(3, 34):
        a, b = 12 - half[y] - 1, 12 + half[y]
        for x in range(a, b + 1):
            if y == 3 or x == a:
                col = c[4] if y == 3 else c[3]  # lit rim: front and left
            elif y == 33 or x == b:
                col = c[1]
            elif (x - a) % 3 == 0 or (y - 3) % 3 == 0:
                col = c[3] if x - a < 3 or y < 6 else c[2]
            else:
                col = SHOPPING_CART_HOLE
            s.set_at((x, y), col)
    tank_box(s, 8, 28, 15, 31, red)  # folding child-seat flap at the back of the basket
    hline(s, 9, 14, 30, red[0])
    for x0, x1 in ((5, 7), (16, 18)):  # red corner bumpers on the nose
        hline(s, x0, x1, 2, red[3] if x0 < 12 else red[1])
    for x in (4, 19):  # handle uprights
        for y in (34, 35):
            put(s, x, y, c[3] if x < 12 else c[1])
    for y, i in ((36, 3), (37, 1)):  # the red handle bar, wider than the basket
        hline(s, 2, 21, y, red[i])
    put(s, 2, 36, red[3])
    return outline(s)


def draw_golf_cart(frame: int) -> Surf:  # white cowl, canopy on four struts, golf bag on the back
    s, w, cp = new(24, 40), WHITE, GOLF_CART_CANOPY
    for x0, y0 in ((2, 4), (19, 4), (2, 27), (19, 27)):  # small turf tyres
        tank_tread(s, x0, y0, x0 + 2, y0 + 6, frame)
    formula_body(s, {1: 4, 2: 5, 3: 6, 5: 7}, 1, 38, w)
    for x, c in ((6, HEAD[1]), (7, HEAD[0])):  # headlamps on the cowl
        put(s, x, 3, c)
        put(s, 23 - x, 3, c)
    for y in (8, 9):  # low clear windscreen
        hline(s, 6, 17, y, GLASS[2] if y == 8 else GLASS[1])
    put(s, 7, 8, GLASS[3])
    tank_box(s, 6, 24, 17, 28, CAR_RAMPS["black"])  # bench seat, under the canopy's rear edge
    for y in range(11, 24):  # canopy roof on four struts
        for x in range(4, 20):
            i = 3 if x == 4 else 1 if x == 19 else 2
            s.set_at((x, y), cp[4 if y == 11 else 0 if y == 23 else i])
    for x in (4, 19):  # struts and the roof's shadow on the seat
        put(s, x, 24, OUT)
        put(s, x, 10, OUT)
    hline(s, 5, 18, 24, SHADOW)
    hline(s, 6, 17, 1, w[1])  # bumper
    for y in (15, 19):  # canopy ribs
        hline(s, 5, 18, y, cp[1])
    tank_box(s, 5, 29, 18, 38, (w[0], w[0], w[1], w[2], w[2]))  # rear deck
    bag = art(  # golf bag standing up: blue rim, chrome club heads, red and yellow head covers
        ("..bBBb..", ".bRRCCb.", "bRrRcCcb", "BYYCCrRB", "BYyCcRrB", "bCCcYYcb", ".bCcYyb.", "..bbbb.."),
        {"b": GOLF_CART_BAG[0], "B": GOLF_CART_BAG[2], "C": CHROME[3], "c": CHROME[1],
         "R": TAIL[2], "r": TAIL[1], "Y": GOLD[3], "y": GOLD[1]},
    )  # fmt: skip
    s.blit(bag, (8, 30))
    return outline(s)


SOFA_PILLOW = {"P": (255, 246, 220), "Q": (240, 226, 192), "p": (204, 184, 146)}


def draw_sofa(frame: int) -> Surf:  # velvet sofa sideways: tall back, rolled arms, sunken cushions, pillows
    s, r = new(24, 40), SOFA
    for x0, y0 in ((2, 7), (20, 7), (2, 29), (20, 29)):  # castor wheels
        tank_tread(s, x0, y0, x0 + 1, y0 + 3, frame)
    for y in range(2, 38):  # tall backrest along the left side, rounded at both ends
        for x in range(3, 8):
            if not (y in (2, 37) and x in (3, 7)):
                s.set_at((x, y), r[4] if x == 3 or y == 2 else r[3] if x < 6 else r[2] if x == 6 else r[1])
    for y in range(10, 31, 5):  # tufting buttons
        put(s, 5, y, r[1])
    for y0 in (1, 33):  # rolled arms front and back: lit top, shaded underside
        for y in range(y0, y0 + 5):
            for x in range(5, 21):
                if y in (y0, y0 + 4) and x == 20:
                    continue
                k = y - y0
                s.set_at((x, y), r[4 if k == 0 else 3 if k == 1 else 2 if k == 2 else 1 if x < 20 else 0])
        hline(s, 8, 19, y0 + 4, r[0])
    for y0 in (6, 15, 24):  # three cushions sunk between the arms, in the backrest's shade
        for y in range(y0, y0 + 9):
            for x in range(8, 20):
                if y in (y0, y0 + 8) and x in (8, 19):
                    continue
                i = 0 if y == y0 + 8 else 1 if x in (8, 19) else 3 if y == y0 else 2
                s.set_at((x, y), r[i])
        hline(s, 10, 12, y0 + 1, r[4])
    for x, y in ((8, 6), (8, 25)):  # throw pillows leaning in the corners
        s.blit(art(("PPPp", "PQQp", "PQQp", "pppp"), SOFA_PILLOW), (x, y))
    return outline(s)


def tractor_tyre(s: Surf, x0: int, y0: int, w: int, h: int, frame: int) -> None:
    """Lugged tractor tyre: V chevrons pointing forward, rolling 2 px per frame."""
    tank_tread(s, x0, y0, x0 + w - 1, y0 + h - 1, frame)
    mid = x0 + (w - 1) / 2
    for y in range(y0 + 1, y0 + h - 1):
        for x in range(x0, x0 + w):
            lug = (y + 2 * frame + int(abs(x - mid))) % 4 < 2
            s.set_at((x, y), TIRE[1] if lug else TIRE[0])


def draw_tractor(frame: int) -> Surf:  # narrow green hood, small front wheels, huge lugged rear wheels
    s, g, yl = new(24, 40), TRACTOR, TRACTOR_YELLOW
    tractor_tyre(s, 1, 21, 6, 17, frame)
    tractor_tyre(s, 17, 21, 6, 17, frame)
    tractor_tyre(s, 3, 3, 4, 9, frame)
    tractor_tyre(s, 17, 3, 4, 9, frame)
    for x, c in ((7, yl[2]), (16, yl[0])):  # yellow front hubs
        for y in (6, 7, 8):
            put(s, x, y, c)
    hline(s, 7, 16, 7, METAL[0])  # front axle
    tank_box(s, 8, 1, 15, 21, g)  # hood
    for y in range(2, 21):
        put(s, 9, y, yl[1])  # yellow stripe down the hood
        put(s, 14, y, yl[0])
    for y in (1, 2):  # grille
        hline(s, 10, 13, y, OUT if y == 2 else METAL[1])
    put(s, 8, 1, HEAD[1])
    put(s, 15, 1, HEAD[1])
    s.blit(art(("cC", "Co"), {"C": CHROME[3], "c": CHROME[1], "o": OUT}), (12, 14))  # exhaust stack
    for x0 in (7, 15):  # fenders over the inner half of the rear wheels
        tank_box(s, x0, 22, x0 + 1, 37, g)
    tank_box(s, 9, 22, 14, 37, METAL)  # platform
    hline(s, 10, 13, 23, OUT)  # steering wheel
    put(s, 10, 24, OUT)
    put(s, 13, 24, OUT)
    tank_box(s, 9, 28, 14, 32, (yl[0], yl[0], yl[1], yl[2], yl[2]))  # seat
    tank_box(s, 10, 28, 13, 31, CAR_RAMPS["black"])
    hline(s, 7, 16, 34, OUT)  # roll bar
    hline(s, 7, 16, 35, METAL[1])
    tank_box(s, 10, 37, 13, 38, METAL)  # hitch
    return outline(s)


def deco_samu(s: Surf, g: dict) -> None:  # white van, red/orange band, red light bar, 192 on the roof
    for y in range(3, g["bot"] - 1):  # the band down both flanks
        put(s, g["x0"][y], y, SAMU_RED[1])
        put(s, g["x1"][y], y, SAMU_RED[0])
    for y in range(9, 36):
        put(s, 4, y, SAMU_ORANGE[1])
        put(s, 19, y, SAMU_ORANGE[0])
    hline(s, g["x0"][4], g["x1"][4], 4, SAMU_RED[1])  # band round the nose
    for x in range(5, 19):  # light bar: red domes either side of a white centre
        c = WHITE[4] if 11 <= x <= 12 else SAMU_RED[2] if x in (5, 13) else SAMU_RED[1]
        put(s, x, 10, c)
        put(s, x, 11, SAMU_RED[0] if not 11 <= x <= 12 else WHITE[1])
    digits(s, 6, 15, "192", SAMU_RED[1])
    tank_box(s, 8, 24, 15, 29, WHITE)  # roof air conditioner
    hline(s, 9, 14, 26, WHITE[1])
    for y in range(31, 37):  # rear doors
        put(s, 11, y, WHITE[1])


def draw_samu(frame: int) -> Surf:
    return vehicle(24, 40, (1, 38), STYLES["g9_samu"], WHITE, frame, deco_samu)


def deco_fire_truck(s: Surf, g: dict) -> None:  # red engine: chrome grille, light bar, white stripe, ladder
    r = FIRE_TRUCK
    cyber_panel(s, g, 7, 38, r)
    hline(s, g["x0"][1], g["x1"][1], 1, CHROME[3])  # bumper
    for x in range(5, 19):  # grille
        put(s, x, 2, CHROME[2] if x % 2 else CHROME[1])
    for y in range(7, 13):  # white cab roof
        hline(s, 4, 19, y, WHITE[3] if y < 12 else WHITE[1])
    for x in range(4, 20):  # light bar on the cab's leading edge
        put(s, x, 7, POLICE_RED[2] if x in (4, 12) else POLICE_RED[1])
        put(s, x, 8, POLICE_RED[0])
    hline(s, g["x0"][13], g["x1"][13], 13, OUT)  # back wall of the cab
    for y in range(14, 38):  # white stripe down both flanks
        put(s, g["x0"][y], y, WHITE[3])
        put(s, g["x1"][y], y, WHITE[1])
    for y in range(10, 38):  # aerial ladder: two rails, rungs every other row
        put(s, 8, y, CHROME[3])
        put(s, 15, y, CHROME[1])
        if y % 2 == 0:
            hline(s, 9, 14, y, CHROME[2])


def draw_fire_truck(frame: int) -> Surf:
    return vehicle(24, 40, (1, 38), STYLES["g9_fire"], FIRE_TRUCK, frame, deco_fire_truck)


# Paint jobs (g10): stock STYLES bodies recoloured by paint_recolor(); the animated ones are route B
PAINT_ZEBRA_WHITE = [(118, 118, 130), (172, 172, 184), (220, 220, 228), (242, 242, 247), (255, 255, 254)]
PAINT_ZEBRA_BLACK = [(12, 12, 16), (22, 22, 28), (32, 32, 40), (54, 54, 66), (92, 92, 108)]
PAINT_MATTE = [(15, 16, 21), (21, 22, 29), (27, 29, 37), (33, 35, 46), (40, 43, 56)]
PAINT_MATTE_GLASS = [(6, 7, 10), (12, 14, 19), (40, 48, 66), (96, 112, 144)]
PAINT_MATTE_RIM = [(54, 66, 94), (100, 122, 166)]  # cool rim light: shaded side, lit side
PAINT_CAMO = [  # olive base, brown, dark green, khaki
    [(50, 60, 26), (74, 86, 36), (98, 110, 50), (126, 138, 68), (164, 174, 102)],
    [(56, 36, 18), (82, 54, 28), (108, 74, 40), (136, 98, 58), (174, 138, 94)],
    [(18, 38, 22), (28, 54, 30), (40, 72, 38), (58, 94, 52), (94, 128, 82)],
    [(128, 114, 74), (164, 148, 98), (194, 178, 126), (216, 202, 154), (238, 228, 188)],
]
CAR_RAMPS["paint_zebra"] = PAINT_ZEBRA_WHITE
CAR_RAMPS["paint_checker"] = PAINT_ZEBRA_WHITE
CAR_RAMPS["paint_matte"] = PAINT_MATTE
CAR_RAMPS["paint_camo"] = PAINT_CAMO[0]
PAINT_NEON = [(26, 10, 44), (40, 16, 66), (56, 24, 92), (78, 38, 124), (118, 68, 168)]
PAINT_NEON_TUBE = [(196, 60, 255), (240, 150, 255)]  # tube, hot core
PAINT_NEON_PULSE = [
    (226, 128, 255),
    (196, 60, 255),
    (140, 40, 196),
    (196, 60, 255),
]  # the edge tube, by frame
PAINT_NEON_HALO = [(150, 90), (120, 70), (50, 20), (120, 70)]  # underglow alpha next to / 2 px off, by frame
PAINT_FLAMES = [(12, 14, 36), (20, 24, 58), (30, 36, 86), (50, 60, 124), (104, 118, 196)]  # midnight blue
PAINT_FLAMES_FIRE = [  # yellow root, orange body, red tips
    [(214, 140, 16), (246, 184, 26), (255, 220, 64), (255, 240, 136), (255, 252, 210)],
    [(176, 70, 10), (226, 108, 18), (252, 146, 30), (255, 184, 80), (255, 222, 160)],
    [(120, 16, 14), (176, 30, 22), (220, 48, 30), (246, 96, 70), (255, 168, 140)],
]
PAINT_CHROME = [(30, 36, 54), (78, 88, 112), (146, 156, 180), (206, 216, 234), (240, 246, 255)]
PAINT_GOLD = [(86, 46, 6), (160, 98, 16), (226, 166, 40), (255, 214, 98), (255, 248, 204)]
PAINT_RAINBOW = [  # red, orange, yellow, green, blue, violet
    [(130, 16, 30), (196, 30, 44), (236, 56, 64), (255, 112, 108), (255, 186, 180)],
    [(160, 64, 8), (222, 110, 16), (252, 152, 36), (255, 192, 96), (255, 226, 170)],
    [(176, 140, 6), (230, 196, 20), (255, 230, 60), (255, 244, 140), (255, 252, 214)],
    [(20, 100, 40), (36, 152, 56), (70, 196, 80), (130, 228, 120), (200, 250, 190)],
    [(18, 52, 140), (32, 92, 206), (56, 138, 246), (112, 182, 255), (196, 226, 255)],
    [(70, 24, 120), (110, 40, 176), (152, 70, 220), (192, 124, 248), (232, 200, 255)],
]
PAINT_RAINBOW_BASE = [(201, 0, 1), (201, 0, 2), (201, 0, 3), (201, 0, 4), (201, 0, 5)]  # all repainted


def paint_recolor(s: Surf, ramp: Sequence[Color], pick: Callable[[int, int, int], Color]) -> None:
    """Repaint the pixels drawn in `ramp` with pick(x, y, shade index)."""
    idx = {c: i for i, c in enumerate(ramp)}
    w, h = s.get_size()
    for y in range(h):
        for x in range(w):
            c = s.get_at((x, y))
            i = idx.get((c[0], c[1], c[2]))
            if c[3] == 255 and i is not None:
                s.set_at((x, y), pick(x, y, i))


def deco_paint_zebra(s: Surf, g: dict) -> None:  # white body under wavy black stripes that wrap round it
    def pick(x: int, y: int, i: int) -> Color:
        for n in range(8):  # stripe n: a wave across the car, swelling and thinning as it goes
            yc = 1.5 + 5.5 * n + 1.5 * math.sin(x * 0.6 + n * 1.7)
            if abs(y - yc) < 1.1 + 0.35 * math.sin(x * 0.8 + n * 2.3):
                return PAINT_ZEBRA_BLACK[i]
        return PAINT_ZEBRA_WHITE[i]

    paint_recolor(s, PAINT_ZEBRA_WHITE, pick)


def deco_paint_checker(s: Surf, g: dict) -> None:  # chequered flag, 3 px squares, over everything but glass
    def pick(x: int, y: int, i: int) -> Color:
        return PAINT_ZEBRA_BLACK[i] if ((x - 3) // 3 + (y - 1) // 3) % 2 else PAINT_ZEBRA_WHITE[i]

    paint_recolor(s, PAINT_ZEBRA_WHITE, pick)


def deco_paint_matte(s: Surf, g: dict) -> None:  # flat black, no gloss; a cool rim light holds the shape
    r = PAINT_MATTE
    for y in range(g["top"] + 1, g["bot"] - 1):  # flatten the hood streak and the roof glint
        for x in range(g["x0"][y] + 1, g["x1"][y]):
            if tuple(s.get_at((x, y)))[:3] in (r[3], r[4]) and not g["r0"] <= y <= g["r1"]:
                s.set_at((x, y), r[2])
    for y in range(g["top"], g["bot"]):
        put(s, g["x0"][y], y, PAINT_MATTE_RIM[1])
        put(s, g["x1"][y], y, PAINT_MATTE_RIM[0])
    hline(s, g["x0"][1], g["x1"][1], 1, PAINT_MATTE_RIM[1])
    for y in range(g["r0"], g["r1"] + 1):  # the rim light catches the roof's edges too
        put(s, g["rx0"], y, PAINT_MATTE_RIM[0])
    hline(s, g["rx0"], g["rx1"], g["r0"], PAINT_MATTE_RIM[0])
    for x0 in (7, 14):  # twin hood vents: black slots under a rim-lit lip
        hline(s, x0, x0 + 2, 6, PAINT_MATTE_RIM[0])
        hline(s, x0, x0 + 2, 7, OUT)
        hline(s, x0, x0 + 2, 8, OUT)
    hline(s, g["x0"][34] - 1, g["x1"][34] + 1, 33, PAINT_MATTE_RIM[1])  # ducktail lip on the trunk
    hline(s, g["x0"][34], g["x1"][34], 34, OUT)
    for x, y, c in ((5, 2, (150, 140, 110)), (6, 2, (110, 104, 86)), (5, 3, (90, 86, 74))):  # smoked lamps
        put(s, x, y, c)
        put(s, 23 - x, y, c)
    for x in range(5, 8):  # smoked tail lights
        put(s, x, 37, (120, 20, 30))
        put(s, 23 - x, 37, (120, 20, 30))


def paint_camo_patch(x: int, y: int) -> int:
    rng = random.Random("paint_camo")
    k = 0
    for layer, n in ((1, 9), (2, 9), (3, 6)):
        for _ in range(n):
            cx, cy = rng.uniform(2, 22), rng.uniform(0, 40)
            rx, ry, tilt = rng.uniform(1.6, 3.4), rng.uniform(1.8, 4.0), rng.uniform(-0.6, 0.6)
            dx, dy = x + 0.5 - cx, y + 0.5 - cy
            if ((dx + tilt * dy) / rx) ** 2 + (dy / ry) ** 2 < 1:
                k = layer
    return k


def deco_paint_camo(s: Surf, g: dict) -> None:  # woodland camo all over, black arches, grille, spare wheel
    paint_recolor(s, PAINT_CAMO[0], lambda x, y, i: PAINT_CAMO[paint_camo_patch(x, y)][i])
    for x in range(8, 16, 2):
        put(s, x, 2, OUT)
    for wy0, wy1 in STYLES["jeep"]["wheels"]:
        for y in range(wy0 - 1, wy1 + 2):
            s.set_at((g["x0"][y], y), (58, 60, 52))
            s.set_at((g["x1"][y], y), (36, 38, 34))
    for y in range(34, 39):
        for x in range(8, 16):
            d = math.hypot(x + 0.5 - 12, (y + 0.5 - 36.5) * 1.25)
            if d < 4:
                put(s, x, y, PAINT_CAMO[0][1] if d < 1.6 else TIRE[1] if d < 2.6 and x < 12 else TIRE[0])


def deco_paint_neon(s: Surf, g: dict) -> None:  # neon tube round the roof and down the hood
    tube, hot = PAINT_NEON_TUBE
    for y in range(g["r0"], g["r1"] + 1):
        put(s, g["rx0"], y, hot)
        put(s, g["rx1"], y, tube)
    hline(s, g["rx0"], g["rx1"], g["r0"], hot)
    hline(s, g["rx0"], g["rx1"], g["r1"], tube)


def draw_paint_neon(frame: int) -> Surf:  # dark purple, glowing edge, underglow pulsing on the road
    s = vehicle(24, 40, (1, 38), STYLES["sedan"], PAINT_NEON, frame, deco_paint_neon, GLASS_CYAN)
    body = set(PAINT_NEON) | set(PAINT_NEON_TUBE)
    rgb = {(x, y): tuple(s.get_at((x, y)))[:3] for y in range(40) for x in range(24)}
    for (x, y), c in rgb.items():  # the outline round the body (not the tyres) becomes a neon tube
        if c == OUT and any(rgb.get((x + dx, y + dy)) in body for dx, dy in N4):
            s.set_at((x, y), PAINT_NEON_PULSE[frame])
    near, far = PAINT_NEON_HALO[frame]
    glow = new(24, 40)
    for y in range(40):
        for x in range(24):
            if solid(s, x, y):
                continue
            near_px = [(dx, dy) for dx in range(-2, 3) for dy in range(-2, 3) if solid(s, x + dx, y + dy)]
            d = min((max(abs(dx), abs(dy)) for dx, dy in near_px), default=9)
            if d <= 2:
                glow.set_at((x, y), (*PAINT_NEON_TUBE[0], near if d == 1 else far))
    glow.blit(s, (0, 0))
    return glow


PAINT_FLAMES_TONGUES = (  # flame length per column, flank (col 3) to centre (col 11); the tips dance
    (25, 20, 12, 17, 13, 8, 12, 7, 5),
    (23, 23, 11, 15, 15, 7, 10, 9, 6),
    (22, 25, 14, 13, 16, 10, 8, 11, 5),
    (24, 22, 15, 16, 12, 11, 11, 8, 4),
)


def deco_paint_flames(s: Surf, g: dict, frame: int) -> None:  # hot-rod flames licking back from the nose
    def pick(x: int, y: int, i: int) -> Color:
        f = (y - g["top"]) / PAINT_FLAMES_TONGUES[frame][min(x, 23 - x) - 3]
        return PAINT_FLAMES[i] if f >= 1 else PAINT_FLAMES_FIRE[0 if f < 0.3 else 1 if f < 0.65 else 2][i]

    paint_recolor(s, PAINT_FLAMES, pick)


def draw_paint_flames(frame: int) -> Surf:
    deco = lambda s, g: deco_paint_flames(s, g, frame)  # noqa: E731
    return vehicle(24, 40, (1, 38), STYLES["classic"], PAINT_FLAMES, frame, deco)


def paint_mirror(ramp: Sequence[Color], x: int, y: int, i: int, lift: int) -> Color:
    """Polished metal: bright panels cut by dark diagonal reflections of the road."""
    v = (y + 0.6 * x) % 12
    if 6 <= v < 8:
        return ramp[0 if i < 3 else 1]
    return ramp[min(max(i, 3), i + (lift if v < 6 else 0))]  # the roof (shade 3) stays metal, not glass-pale


def deco_paint_chrome(s: Surf, g: dict, frame: int) -> None:  # mirror chrome, a white glint sweeping across
    def pick(x: int, y: int, i: int) -> Color:
        v = (y + 0.6 * x - 3 - 6 * frame) % 24  # 6 px a frame: round the 24 px period in 4
        if v < 1.8:
            return (255, 255, 255)
        if v < 2.8:  # a dark edge trailing the glint keeps it apart from the bright panels
            return PAINT_CHROME[1]
        return paint_mirror(PAINT_CHROME, x, y, i, 1)

    paint_recolor(s, PAINT_CHROME, pick)


def draw_paint_chrome(frame: int) -> Surf:
    deco = lambda s, g: deco_paint_chrome(s, g, frame)  # noqa: E731
    return vehicle(24, 40, (1, 38), STYLES["beetle"], PAINT_CHROME, frame, deco)


PAINT_GOLD_SPARKLE = (("..w..", "..w..", "wwWww", "..w..", "..w.."), ("...", ".W.", "..."))  # big, fading


def deco_paint_gold(s: Surf, g: dict, frame: int) -> None:  # polished gold, a glint sweeping, sparkles
    def pick(x: int, y: int, i: int) -> Color:
        v = (y + 0.6 * x - 9 - 6 * frame) % 24
        if v < 1.5:
            return (255, 255, 255)
        if v < 3:
            return PAINT_GOLD[4]
        return paint_mirror(PAINT_GOLD, x, y, i, 1)

    paint_recolor(s, PAINT_GOLD, pick)
    x, y = ((4, 4), (5, 5), (14, 29), (15, 30))[frame]
    s.blit(art(PAINT_GOLD_SPARKLE[frame % 2], {"w": PAINT_GOLD[4], "W": (255, 255, 255)}), (x, y))


def draw_paint_gold(frame: int) -> Surf:
    deco = lambda s, g: deco_paint_gold(s, g, frame)  # noqa: E731
    return vehicle(24, 40, (1, 38), STYLES["classic"], PAINT_GOLD, frame, deco)


def deco_paint_rainbow(s: Surf, g: dict, frame: int) -> None:  # rainbow chevrons flowing nose -> tail
    def pick(x: int, y: int, i: int) -> Color:
        return PAINT_RAINBOW[int((y - 0.5 * abs(x - 11.5) - 4.5 * frame) // 3) % 6][i]  # 18 px in 4 frames

    paint_recolor(s, PAINT_RAINBOW_BASE, pick)


def draw_paint_rainbow(frame: int) -> Surf:
    deco = lambda s, g: deco_paint_rainbow(s, g, frame)  # noqa: E731
    return vehicle(24, 40, (1, 38), STYLES["box"], PAINT_RAINBOW_BASE, frame, deco)


# Redraws (g11): McQueen, Supra MK4, '59 Cadillac, Kombi
def g11_paint(s: Surf, x0: int, y0: int, rows: Sequence[str], legend: dict[str, Color]) -> None:
    """Like art() + blit, but set_at, so a CLEAR in the legend cuts the body away."""
    for j, row in enumerate(rows):
        for i, ch in enumerate(row):
            if ch in legend:
                put(s, x0 + i, y0 + j, legend[ch])


def g11_mirror(rows: Sequence[str]) -> list[str]:
    return [row[::-1] for row in rows]


# McQueen, drawn whole (route B): rounded stock car, grin, Rust-eze hood, windshield eyes with lids
# slanting in, "95" on the roof, one clean bolt down each flank (head forward, one jag, tip at the rear)
G11_RACER95 = [(104, 8, 20), (176, 18, 30), (224, 34, 38), (255, 92, 76), (255, 184, 164)]
G11_RACER95_BOLT = [(150, 20, 14), (240, 120, 20), (255, 200, 32), (255, 232, 72)]  # edge, orange, gold, lit
G11_RACER95_HALF = {1: 4, 2: 6, 3: 7, 4: 8, 5: 9, 37: 8, 38: 6}  # half-widths: round nose and tail
G11_RACER95_FONT = {  # 4x7 rounded race digits
    "9": (".##.", "#..#", "#..#", ".###", "...#", "#..#", ".##."),
    "5": ("####", "#...", "###.", "...#", "...#", "#..#", ".##."),
}
G11_RACER95_EYE = (  # left eye, cols 5-10 from row 10; the lid (body red) slants down toward the nose
    "WWWccc",
    "WWWWWc",
    "WWLLLW",
    "WWBPBW",
    "WWBBBW",
    "gWWWWg",
)
G11_RACER95_BOLT_ART = (  # left flank, cols 3-6 from row 16: slants out, jags back in, slants out to a tip
    ".kYY",
    "kYYY",
    "kYYk",
    "YYYk",
    "YYk.",
    "YYk.",
    "YYYY",
    "YYYY",
    "kYYY",
    ".YYk",
    "kYYk",
    "YYk.",
    "YOk.",
    "OOk.",
    "Ok..",
    "Ok..",
    "k...",
)


def g11_draw_racer95(frame: int) -> Surf:
    s, r, b = new(24, 40), G11_RACER95, G11_RACER95_BOLT
    for y0, y1 in ((6, 12), (27, 33)):
        tank_tread(s, 1, y0, 3, y1, frame)
        tank_tread(s, 20, y0, 22, y1, frame)
    formula_body(s, G11_RACER95_HALF, 1, 38, r)
    for y in range(3, 10):  # hood gloss
        put(s, 5, y, r[3])
    put(s, 6, 3, r[4])
    # grin with teeth across the nose, sticker headlamps at its corners
    g11_paint(s, 8, 2, ("n......n", ".nWWWWn.", "..nnnn.."), {"n": OUT, "W": (250, 250, 255)})
    for x, y, c in ((5, 3, HEAD[1]), (6, 3, HEAD[0]), (4, 4, HEAD[0])):
        put(s, x, y, c)
        put(s, 23 - x, y, c)
    # Rust-eze: cream oval with a red swash on the hood
    cream = {"M": (250, 232, 192), "m": (204, 168, 118), "R": r[1]}
    g11_paint(s, 8, 5, (".MMMMMm.", "MMRRRMMm", "MRRRRMMm", ".MMMMmm."), cream)
    # windshield = the eyes
    eye = {"W": (250, 250, 255), "L": (110, 176, 255), "B": (40, 104, 220), "P": OUT}
    eye |= {"g": GLASS[0], "c": r[2]}
    g11_paint(s, 5, 10, G11_RACER95_EYE, eye)
    g11_paint(s, 13, 10, g11_mirror(G11_RACER95_EYE), eye)
    for y in range(10, 16):
        hline(s, 11, 12, y, GLASS[0] if y > 10 else GLASS[1])
    hline(s, 6, 17, 16, OUT)  # the windshield's top edge, then the roof
    for y in range(17, 25):
        hline(s, 7, 16, y, r[2])
        put(s, 7, y, r[3])
        put(s, 16, y, r[1])
    for i, ch in enumerate("95"):
        g11_paint(s, 7 + 5 * i, 17, G11_RACER95_FONT[ch], {"#": b[3] if i == 0 else b[2]})
    for y in range(25, 28):  # rear glass
        hline(s, 7, 16, y, GLASS[0])
    put(s, 8, 25, GLASS[2])
    put(s, 8, 26, GLASS[1])
    g11_paint(s, 3, 16, G11_RACER95_BOLT_ART, {"k": b[0], "Y": b[3], "O": b[1]})
    g11_paint(s, 17, 16, g11_mirror(G11_RACER95_BOLT_ART), {"k": b[0], "Y": b[2], "O": b[1]})
    for x in range(2, 22):  # spoiler blade standing proud of the tail
        put(s, x, 33, r[4] if x < 8 else r[3])
        put(s, x, 34, r[0])
    hline(s, 9, 14, 36, cream["M"])  # cream Rust-eze band on the bumper
    for x, c in ((5, TAIL[2]), (6, TAIL[1]), (17, TAIL[1]), (18, TAIL[2])):
        put(s, x, 36, c)
    return outline(s)


# Supra MK4 (Fast & Furious): candy orange, coke-bottle body, teardrop lamps, black tribal on the
# front fenders, the tall hoop wing standing over the tail, four round tail lamps
CAR_RAMPS["jdm94"] = [(132, 36, 8), (206, 74, 12), (248, 116, 24), (255, 164, 70), (255, 216, 160)]
G11_JDM94_INK = [(22, 18, 24), (74, 62, 70)]  # tribal black, its gloss on the lit side
STYLES["g11_supra"] = dict(  # narrow round nose, pinched waist, wide haunches, round tail
    insets={1: 5, 2: 3, 3: 1, 4: 0, 13: 1, 23: 0, 36: 1, 37: 2, 38: 4},
    wheels=[(6, 12), (28, 34)],
    ws=(13, 16), roof=(17, 22), rear=(23, 25), glass_in=2, roof_in=4, head=2,
)  # fmt: skip
G11_JDM94_TRIBAL = (  # left side from row 4, cols 4-8: blades sweeping back off the fender, 1 px in
    "k....",
    "lk...",
    "lkk..",
    ".lkk.",
    "..kkk",
    "...kk",
    "....k",
)


def g11_deco_jdm94(s: Surf, g: dict) -> None:  # Supra MK4: tribal, teardrop lamps, hoop wing, 4 round lamps
    r, ink = CAR_RAMPS["jdm94"], G11_JDM94_INK
    g11_paint(s, 4, 4, G11_JDM94_TRIBAL, {"k": ink[0], "l": ink[1]})
    g11_paint(s, 15, 4, g11_mirror(G11_JDM94_TRIBAL), {"k": ink[0], "l": ink[0]})
    for x, y, c in ((6, 2, HEAD[1]), (5, 2, HEAD[0]), (4, 3, HEAD[1]), (5, 3, HEAD[0]), (4, 4, HEAD[0])):
        put(s, x, y, c)  # teardrop lamp clusters wrapping round the front corners
        put(s, 23 - x, y, c)
    hline(s, 9, 14, 1, r[2])
    hline(s, 9, 14, 2, ink[0])  # one wide mouth under the nose
    for y in range(4, 12):  # hood bulge
        put(s, 11, y, r[3])
        put(s, 12, y, r[1])
    # hoop wing: blade out past the body over the rear wheels, legs arching down to the haunches
    for x in range(1, 23):
        put(s, x, 29, r[4] if x < 12 else r[3])
        put(s, x, 30, r[2] if x < 12 else r[1])
    hline(s, 5, 18, 31, (64, 16, 4))  # its shadow on the deck
    for y in (31, 32, 33, 34):
        lx = 3 if y < 33 else 4
        put(s, lx, y, r[4])
        put(s, lx + 1, y, r[1])
        put(s, 23 - lx, y, r[1])
        put(s, 22 - lx, y, r[3])
    for cx in (4, 7, 15, 18):  # four round tail lamps
        for dx, dy, c in ((0, 0, TAIL[2]), (1, 0, TAIL[1]), (0, 1, TAIL[1]), (1, 1, TAIL[0])):
            put(s, cx + dx, 35 + dy, c)
    for x in (4, 5, 6, 17, 18, 19):  # no stock tail lamps under the round ones
        for y, c in ((37, r[1]), (38, r[0])):
            if solid(s, x, y):
                put(s, x, y, c)


# '59 Cadillac: long pink hardtop, white roof, wraparound glass, chrome nose, skirts, and fins that rise
# off the rear fenders and run past the bumper to points, bullet lamps in them
CAR_RAMPS["fins59"] = [(150, 62, 96), (210, 108, 146), (242, 156, 184), (255, 198, 214), (255, 236, 242)]
STYLES["g11_caddy"] = dict(  # long, flat and square: a hood to row 12, a short roof, a long deck
    insets={1: 1, 2: 0},
    wheels=[(5, 11), (28, 34)],
    ws=(13, 15), roof=(16, 22), rear=(23, 25), glass_in=1, roof_in=3, head=2,
)  # fmt: skip
G11_FINS59_FIN = (  # left rear quarter, cols 2-7 from row 21: lit outer face, ridge, shaded inner face,
    "  h   ",  # crease on the deck; bullet lamps at the tip, the tail cut away between the fins
    "  hd  ",
    " mhd  ",
    " mhd  ",
    " mhed ",
    "mmhed ",
    "mmhed ",
    "mmhed ",
    "mmhed ",
    "mmhed ",
    "mmhed ",
    "mmhed ",
    "mmhed ",
    "mmhed ",
    "mmhe..",
    ".mTe..",
    ".mTt..",
    "..t...",
)


def g11_deco_fins59(s: Surf, g: dict) -> None:  # '59 Cadillac: chrome, white roof, giant fins, bullet lamps
    r, c = CAR_RAMPS["fins59"], CHROME
    hline(s, g["x0"][1], g["x1"][1], 1, c[4])  # bumper, jewelled grille, quad lamps
    for x in range(g["x0"][2], g["x1"][2] + 1):
        put(s, x, 2, c[3] if x % 2 else c[1])
    hline(s, g["x0"][3] + 2, g["x1"][3] - 2, 3, c[2])
    for x in (4, 6, 17, 19):
        put(s, x, 2, HEAD[1])
        put(s, x, 3, HEAD[0])
    for y in range(4, 12):  # hood: twin creases
        put(s, 8, y, r[3])
        put(s, 15, y, r[1])
    for y in range(13, 16):  # panoramic windshield wraps round to the flanks
        put(s, g["x0"][y] + 1, y, GLASS[2])
        put(s, g["x1"][y] - 1, y, GLASS[0])
    w = WHITE
    for y in range(g["r0"], g["r1"] + 1):  # white hardtop
        for x in range(g["rx0"], g["rx1"] + 1):
            s.set_at((x, y), w[4] if y == g["r0"] else w[3] if x < g["rx1"] else w[1])
    for y in range(4, 33):  # chrome spear down each flank
        if not 12 <= y <= 25:
            put(s, g["x0"][y] + 1, y, c[3])
            put(s, g["x1"][y] - 1, y, c[2])
    for y in range(28, 35):  # skirts hide the rear wheels
        for x in (1, 2, 21, 22):
            s.set_at((x, y), CLEAR)
    hline(s, 7, 16, 34, c[4])  # rear bumper, then the deck stops: the fins carry on alone
    hline(s, 8, 15, 35, c[2])
    for y in range(36, 39):
        hline(s, 6, 17, y, CLEAR)
    for y in range(26, 34):  # the deck sits low between the fins, in their shade
        hline(s, 8, 15, y, r[1])
    left = {"h": (255, 255, 255), "m": r[4], "e": r[0], "d": (110, 40, 70)}
    left |= {"T": TAIL[2], "t": TAIL[1], ".": CLEAR}
    right = left | {"m": r[1], "e": r[3]}
    for j, row in enumerate(G11_FINS59_FIN):
        for i, ch in enumerate(row):
            if ch in left:
                put(s, 2 + i, 21 + j, left[ch])
                put(s, 21 - i, 21 + j, right[ch])


# Kombi: sky-blue body under a white roof; a big white V down the nose to the VW roundel, split
# windshield, folded canvas sunroof, air-intake louvres and the blue engine lid
CAR_RAMPS["kombi"] = [(28, 82, 132), (44, 120, 182), (74, 158, 216), (132, 196, 240), (206, 234, 252)]
KOMBI_WHITE = [(150, 146, 140), (196, 192, 184), (230, 226, 216), (248, 246, 238), (255, 255, 250)]
STYLES["g11_kombi"] = dict(  # a bus: round corners, wheels under the cab, windshield at the very front
    insets={1: 4, 2: 2, 3: 1, 4: 0, 36: 0, 37: 1, 38: 3},
    wheels=[(5, 11), (29, 35)],
    ws=(8, 10), roof=(11, 34), rear=None, glass_in=1, roof_in=3, head=2,
)  # fmt: skip
G11_KOMBI_CANVAS = [(150, 130, 96), (196, 176, 136), (226, 210, 172)]  # fold shade, cloth, lit fold
G11_KOMBI_V = (  # the nose from row 1, cols 4-19: the white top comes down in a V to the chrome roundel
    "......cccc......",
    ".....cbbbbc.....",
    ".....wccccw.....",
    "....wwwwwwww....",
    "...wwwwwwwwww...",
    "..wwwwwwwwwwww..",
    ".wwwwwwwwwwwwww.",
)


def g11_deco_kombi(s: Surf, g: dict) -> None:  # Kombi: V nose, split screen, sunroof, louvres
    k, w = CAR_RAMPS["kombi"], KOMBI_WHITE
    cyber_panel(s, g, 1, 7, k)  # blue nose under the windshield
    g11_paint(s, 4, 1, G11_KOMBI_V, {"w": w[3], "c": CHROME[3], "b": k[0]})
    for y in range(3, 8):  # the V's right-hand edge in shade
        put(s, 12 + (y - 3) + 2, y, w[2])
    for x, y, c in ((4, 2, HEAD[1]), (5, 2, HEAD[0]), (4, 3, HEAD[0])):  # round lamps outside the V
        put(s, x, y, c)
        put(s, 23 - x, y, c)
    for y in range(8, 11):  # split windshield: two panes, a white bar between
        hline(s, 11, 12, y, w[2])
    for y in range(11, 35):  # white roof, rounded, inside the blue body
        a, z = (7, 16) if y in (11, 34) else (6, 17)
        for x in range(a, z + 1):
            s.set_at((x, y), w[4] if y == 11 else w[3] if x < z else w[2])
    cv = G11_KOMBI_CANVAS
    for y in range(13, 24):  # canvas sunroof, folded back in ridges
        for x in range(8, 16):
            put(s, x, y, cv[1] if y < 20 else cv[2] if y % 2 else cv[0])
        put(s, 8, y, cv[2])
        put(s, 15, y, cv[0])
    for y in (27, 29, 31):  # air-intake louvres on the rear quarters
        for x in (4, 19):
            put(s, x, y, k[0])
    for y in (36, 37):  # engine-lid louvres
        hline(s, 9, 14, y, k[0] if y == 37 else k[3])
    for x, c in ((5, TAIL[2]), (6, TAIL[1]), (17, TAIL[1]), (18, TAIL[2])):  # round tail lamps
        put(s, x, 36, c)


# Motorbikes (g12), drawn whole (route B) like draw_moto, but with 4 frames: wheels in line, rider on top,
# at most 18 px wide with the arms out. Tyres roll every frame (tread phase frame % 2); fire, neon and
# lamps run a 4-frame cycle (phase frame * pi / 2), so the strip loops without a seam.
G12_FIRE = [(255, 255, 228), (255, 234, 104), (255, 164, 36), (234, 78, 22), (150, 28, 16)]  # core -> tip


def g12_bike(rows: Sequence[str], legend: dict[str, Color], tyres: Sequence[tuple], frame: int) -> Surf:
    s = new(24, 40)
    for x0, y0, x1, y1 in tyres:
        tank_tread(s, x0, y0, x1, y1, frame % 2)
    s.blit(art(rows, legend), (0, 0))
    return s


def g12_glow(s: Surf, hot: set, rgb: Color, near: int, far: int) -> Surf:
    """Halo round the pixels coloured in `hot`, on the road under the sprite (alpha < 128: no hitbox)."""
    glow = new(24, 40)
    pts = {(x, y) for y in range(40) for x in range(24) if tuple(s.get_at((x, y)))[:3] in hot}
    for y in range(40):
        for x in range(24):
            if solid(s, x, y):
                continue
            d = min(
                (max(abs(x - px), abs(y - py)) for px, py in pts if abs(x - px) < 3 and abs(y - py) < 3),
                default=9,
            )
            if d <= 2:
                glow.set_at((x, y), (*rgb, near if d == 1 else far))
    glow.blit(s, (0, 0))
    return glow


def g12_tongue(
    s: Surf,
    x: int,
    y: int,
    n: int,
    frame: int,
    seed: float,
    dy: int = 1,
    drift: float = 0.0,
    wide: bool = False,
) -> None:
    """Flame from its root (x, y) for n rows (down = blown back), swaying and stretching on a 4-frame loop."""
    n = max(1, n + round(1.6 * math.sin(frame * math.pi / 2 + seed * 2.1)))
    for k in range(n):
        xx = x + round(drift * k + 0.8 * math.sin(k * 1.1 - frame * math.pi / 2 + seed))
        i = min(4, (k * 5) // n)
        if not 1 <= y + k * dy <= 38:  # keep the outline inside the frame
            break
        put(s, xx, y + k * dy, G12_FIRE[i])
        if wide and k < n // 2:
            put(s, xx + 1, y + k * dy, G12_FIRE[min(4, i + 1)])


G12_FIRE_TYRE = [(176, 36, 16), (255, 146, 36)]  # groove, glowing tread


# Ghost Rider's hell cycle: black chopper, chrome skulls, flaming skull in black leathers, wheels of fire
GHOST_RIDER = [(8, 8, 12), (18, 18, 26), (34, 34, 46), (64, 66, 86), (140, 146, 178)]
GHOST_RIDER_LEATHER = [(16, 12, 12), (30, 24, 24), (50, 40, 38), (84, 68, 62), (150, 126, 116)]
GHOST_RIDER_BONE = {"W": (246, 240, 222), "w": (204, 194, 170), "v": (150, 138, 118), "r": (255, 90, 30)}
GHOST_RIDER_ART = (
    "........................",
    "........................",
    "........................",
    "........................",
    "........................",
    ".........M....m.........",
    ".........M....m.........",
    ".........M....m.........",
    ".........M....m.........",
    ".........MyYYym.........",
    ".........MCXMmm.........",
    "..........nMmn..........",
    "....aemMMCCXXCCMMmea....",
    "....dc...322221...cb....",
    "....dc...3CXXC1...cb....",
    ".....dc..3oCCo1..cb.....",
    ".....dc..32Cm21..cb.....",
    "......dc.322221.cb......",
    "......dc.vWWWWv.cb......",
    "......dcvWWWWWWvcb......",
    ".....XdcWooWWooWcbX.....",
    "....XddcwroWWorwcbbX....",
    "....cddcbwWooWwbcbba....",
    "....bddccbWvvWbbcbba....",
    ".....ddccccccbbbcba.....",
    ".....dccccccbbbbbba.....",
    "......dcccccbbbbba......",
    "......dccccbbbbbba......",
    ".......dcccbbbbaa.......",
    ".......M........m.......",
    ".......M........m.......",
    ".......M........m.......",
    ".......M........m.......",
    "......CM........mn......",
    "......CM........mn......",
    "........................",
    "........................",
    "........................",
    "........................",
    "........................",
)
GHOST_RIDER_SKULL = GHOST_RIDER_ART[18:24]


def draw_ghost_rider(frame: int) -> Surf:  # flames dance on the skull, both wheels and both pipes
    legend = {"o": OUT, "y": HEAD[1], "Y": HEAD[0]} | GHOST_RIDER_BONE
    legend |= dict(zip("01234", GHOST_RIDER, strict=True)) | dict(
        zip("abcde", GHOST_RIDER_LEATHER, strict=True)
    )
    legend |= dict(zip("nmMCX", CHROME, strict=True))
    s = new(24, 40)
    for x0, y0, x1, y1, tail in (
        (11, 1, 12, 8, 7),
        (10, 28, 13, 37, 4),
    ):  # tyres of fire, flames off both sides
        tank_tread(s, x0, y0, x1, y1, frame % 2, G12_FIRE_TYRE)
        for y in range(y0 + 1, y1, 2):
            put(s, x0 + (x1 - x0) // 2 + (y // 2 + frame) % 2 * (x1 > x0 + 1), y, G12_FIRE[1])
        g12_tongue(s, x0 - 1, y0 + 1, tail, frame, x0 * 0.7, drift=-0.3)
        g12_tongue(s, x1 + 1, y0 + 1, tail, frame, x0 * 0.7 + 2, drift=0.3)
    for i, x in enumerate((7, 16)):  # fishtail pipes spit fire
        g12_tongue(s, x, 35, 4, frame, i * 3.1 + 0.5)
    s.blit(art(GHOST_RIDER_ART, legend), (0, 0))
    for x, n, drift, seed in (
        (8, 7, -0.3, 0),
        (10, 8, -0.1, 1.9),
        (11, 10, 0, 3.7),
        (13, 8, 0.1, 5.3),
        (15, 7, 0.3, 2.6),
    ):
        g12_tongue(s, x, 22, n, frame, seed, drift=drift, wide=x == 11)  # the skull's mane, blown back
    for i, x in enumerate((9, 10, 11, 12, 13, 14)):  # a crown licking up off the skull, over the tank
        g12_tongue(s, x, 18, (3, 4, 6, 5, 4, 3)[i], frame, i * 2.3 + 1, dy=-1)
    s.blit(art(GHOST_RIDER_SKULL, legend), (0, 18))
    return g12_glow(outline(s), set(G12_FIRE), G12_FIRE[2], 90, 40)


def g12_arms(
    s: Surf, hand: tuple[int, int], shoulder: tuple[int, int], ramp: Sequence[Color], glove: Color
) -> None:
    """Both arms, 2 px thick, from the left grip to the left shoulder and mirrored; lit left, shaded right."""
    (hx, hy), (sx, sy) = hand, shoulder
    for y in range(hy, sy + 1):
        x = round(hx + (sx - hx) * (y - hy) / max(1, sy - hy))
        for px, c in ((x, ramp[3]), (x + 1, ramp[2]), (22 - x, ramp[2]), (23 - x, ramp[1])):
            put(s, px, y, glove if y == hy else c)


G12_NEON = (1, 2, 3)  # placeholder colour for neon pixels, recoloured by the pulse


def g12_pulse(y: int, frame: int) -> int:
    """Neon brightness 0..2 at row y: two hot pulses 16 rows apart, running nose -> tail 4 rows a frame."""
    d = (y - 4 * frame) % 16
    return 2 if d == 0 else 1 if d in (1, 15) else 0


# Tron light cycle: black capsule, cyan rails from wheel to wheel, prone rider with the identity disc
TRON = [(4, 6, 10), (10, 14, 22), (20, 26, 38), (40, 50, 70), (96, 116, 150)]
TRON_SUIT = [(8, 10, 16), (16, 20, 30), (28, 34, 48), (52, 62, 84), (110, 126, 156)]
TRON_GLOW = [(0, 150, 190), (60, 228, 255), (226, 255, 255)]  # line, bright, hot core
TRON_RIDER = (
    "..N....N..",
    "..b....b..",  # hands on the grips
    ".NdcbbcbN.",
    ".NdcHhbbN.",
    ".NdHhhhbN.",
    "NdcchhbbbN",
    "NddccbbbbN",
    ".Ndc..cbN.",
    ".dcN..Nbb.",
    ".dcN..Nbb.",
    ".dc.NN.bb.",
    ".dcc..cbb.",
    "..dcccbb..",
    "..dcccbb..",
    "..dN..Nb..",
    "..dN..Nb..",
    "..dN..Nb..",
)


def draw_tron(frame: int) -> Surf:  # neon pulses run tail-ward along the rails and into the light trail
    s = new(24, 40)
    for y0, y1 in ((1, 8), (25, 32)):
        tank_tread(s, 11, y0, 12, y1, frame % 2)
    formula_body(s, {4: 3, 6: 4, 27: 3, 29: 0}, 4, 28, TRON)
    for y in range(1, 33):  # rails: the wheel rims at the tips, the flanks between
        hw = 2 if y < 6 or y > 26 else 3
        put(s, 12 - hw, y, G12_NEON)
        put(s, 11 + hw, y, G12_NEON)
    for y, c in ((4, TRON[4]), (5, TRON[3])):  # gloss on the nose cowl
        put(s, 11, y, c)
    legend = {"N": G12_NEON, "H": TRON[4], "h": TRON[3]} | dict(zip("abcde", TRON_SUIT, strict=True))
    s.blit(art(TRON_RIDER, legend), (7, 7))
    outline(s)
    for y in range(40):
        for x in range(24):
            if tuple(s.get_at((x, y)))[:3] == G12_NEON:
                s.set_at((x, y), TRON_GLOW[g12_pulse(y, frame)])
    for y in range(33, 39):  # the light trail: a ribbon of light fading behind the rear wheel
        a = 255 if y < 36 else 220 - (y - 36) * 50
        put(s, 11, y, (*TRON_GLOW[max(1, g12_pulse(y, frame))], a))
        put(s, 12, y, (*TRON_GLOW[g12_pulse(y, frame)], a))
    return g12_glow(s, set(TRON_GLOW), TRON_GLOW[0], 80, 30)


# Kaneda's bike (Akira): long low red capsule, big round cowl, white stickers, the pill on his jacket
AKIRA = [(110, 10, 14), (178, 18, 22), (226, 34, 30), (255, 96, 70), (255, 176, 150)]
AKIRA_JACKET = [(84, 10, 20), (130, 18, 32), (168, 30, 44), (204, 64, 70), (236, 130, 130)]
AKIRA_HAIR = [(46, 26, 18), (74, 44, 28), (108, 68, 40), (146, 98, 60)]
AKIRA_KANEDA = (
    ".cddc..dcc..",  # arms reach into the cowl
    ".cd.hhhhdc..",
    ".cdhHHhhgdc.",
    ".cdhHhhggdc.",
    "ccddhggdddcb",
    "cdddddcccccb",
    ".dddddcccbb.",
    ".dddWWppcbb.",
    ".ddWWWpppbb.",
    ".dddWWppcbb.",
    ".dddddcccbb.",
    "..ddddcccb..",
    "..dddccccb..",
    "..kkkkkkkk..",
)


def draw_akira(frame: int) -> Surf:  # the tail lamps leave red light trails that stretch and shrink
    s = new(24, 40)
    tank_tread(s, 10, 33, 13, 38, frame % 2)
    formula_body(s, {1: 3, 2: 5, 3: 6, 9: 5, 11: 4, 24: 3}, 1, 34, AKIRA)
    for y in range(4, 9):  # the cowl swells: a rim of light along its left shoulder
        put(s, 6, y, AKIRA[4])
    hline(s, 10, 13, 1, HEAD[1])  # headlamp across the nose
    hline(s, 11, 12, 2, HEAD[0])
    for x0, x1, y in ((10, 13, 5), (9, 14, 6), (9, 14, 7)):  # smoked screen
        hline(s, x0, x1, y, GLASS[0])
    put(s, 10, 5, GLASS[2])
    put(s, 9, 6, GLASS[1])
    sticker = (255, 255, 255)
    for x, y0, y1 in ((7, 4, 6), (16, 4, 6), (9, 26, 31), (14, 26, 31)):  # Canon / Citizen / Shoei decals
        for y in range(y0, y1 + 1):
            put(s, x, y, sticker if (y - y0) % 3 != 2 else AKIRA[1])
    legend = {"h": AKIRA_HAIR[1], "H": AKIRA_HAIR[3], "g": AKIRA_HAIR[0], "W": sticker, "p": (130, 180, 236)}
    legend |= dict(zip("abcde", AKIRA_JACKET, strict=True)) | {"k": OUT}
    s.blit(art(AKIRA_KANEDA, legend), (6, 8))
    hline(s, 10, 13, 34, TAIL[1])
    put(s, 10, 34, TAIL[2])
    outline(s)
    for x, seed in ((9, 0), (14, 2)):  # light trails behind the tail lamps
        n = 2 + round(1.5 + 1.5 * math.sin(frame * math.pi / 2 + seed))
        for k in range(n):
            put(s, x, 35 + k, (*TAIL[2 if k == 0 else 1], 255 - k * 40))
    return g12_glow(s, {TAIL[1], TAIL[2]}, TAIL[1], 70, 25)


# Captain America chopper (Easy Rider): long chrome fork, ape hangers, stars-and-stripes tank and lid
CHOPPER_LEATHER = [(20, 18, 22), (40, 36, 42), (62, 56, 64), (100, 92, 102), (156, 146, 156)]
CHOPPER_FLAG = {
    "R": (226, 40, 44), "r": (160, 22, 32), "W": (250, 250, 246), "w": (196, 196, 204),
    "B": (52, 72, 190), "b": (28, 40, 120),
}  # fmt: skip
CHOPPER_ART = (
    "........................",
    "........................",
    "........................",
    "..........M..m..........",
    "..........M..m..........",
    "..........M..m..........",
    "..........M..m..........",
    "..........M..m..........",
    "..........M..m..........",
    "..........M..m..........",
    "..........MyYm..........",
    "..........nCMn..........",
    ".....CMMMMMMMMMMMMm.....",
    "....C.....BBBb.....m....",
    "...........WW...........",
    "..........BWWb..........",
    ".........BBWWbb.........",
    ".........RWRWrw.........",
    ".........RWRWrw.........",
    "..........WRWr..........",
    "..........bBBb..........",
    ".........KBWBWbk........",
    ".........KRWRWrk........",
    ".........KKRWrkk........",
    "......JKKKKKKkkkkj......",
    "......JKKKBBRRkkkj......",
    ".......JKKBBWWkkj.......",
    ".......JKKRRRRkkj.......",
    "........jKKKkkkj........",
    ".......M.jkkkkj.m.......",
    ".......M.CMMMMm.m.......",
    ".......M........m.......",
    ".......M........m.......",
    ".......M........m.......",
    ".......M........m.......",
    "......CM........mn......",
    "......CM........mn......",
    "........................",
    "........................",
    "........................",
)


def draw_chopper(frame: int) -> Surf:  # thin 21-inch front wheel way out on the fork, fat rear
    legend = {"y": HEAD[1], "Y": HEAD[0]} | CHOPPER_FLAG | dict(zip("nmMCX", CHROME, strict=True))
    legend |= dict(zip("jkKJL", CHOPPER_LEATHER, strict=True))
    s = g12_bike(CHOPPER_ART, legend, ((11, 1, 12, 9), (10, 29, 13, 38)), frame)
    g12_arms(s, (3, 14), (6, 23), CHOPPER_LEATHER, CHOPPER_LEATHER[0])
    return outline(s)


def g12_knobs(s: Surf, x0: int, y0: int, x1: int, y1: int, frame: int) -> None:
    """Knobbly tyre edges: notches on both sides that roll with the tread (the outline fills them)."""
    for y in range(y0 + 1, y1):
        if (y + frame) % 2:
            put(s, x0, y, CLEAR)
            put(s, x1, y, CLEAR)


# Vespa: mint scooter, round fender, headset lamp, legshield, floorboard, bulbous rear cowls, chrome rack
VESPA = [(56, 124, 108), (92, 168, 146), (140, 208, 184), (190, 236, 216), (232, 252, 244)]
VESPA_SEAT = [(64, 36, 22), (98, 58, 34), (132, 82, 48), (170, 112, 70)]
VESPA_RIDER = {  # Breton stripes, navy trousers, dark hair
    "W": (250, 250, 248), "w": (204, 208, 220), "v": (30, 40, 92), "V": (54, 68, 134),
    "h": (70, 42, 28), "H": (112, 72, 44), "g": (44, 26, 18), "s": (40, 30, 26),
}  # fmt: skip
VESPA_RIDER_ART = (
    "...HHhg...",
    "...Hhhg...",
    "WWWHhhgWww",
    "vVVhhggvvv",
    "WWWWWWWWww",
    ".VVvvvvvv.",
    ".WWWWWWww.",
    ".VVvvvvvv.",
    "..WWWWww..",
)


def draw_scooter(frame: int) -> Surf:  # Vespa: small wheels at the tips, a rider in a striped jersey
    s = new(24, 40)
    tank_tread(s, 11, 1, 12, 4, frame % 2)
    tank_tread(s, 11, 32, 12, 37, frame % 2)
    formula_body(s, {18: 4, 20: 5, 22: 6, 29: 5, 31: 4, 33: 3}, 18, 34, VESPA)  # the rear cowls
    for y in range(22, 30):  # their round shoulders catch the light
        put(s, 7, y, VESPA[4] if 23 < y < 27 else VESPA[3])
    tank_box(s, 9, 19, 14, 29, VESPA_SEAT)
    for y in range(29, 33):  # chrome rack over the tail
        put(s, 9, y, CHROME[3])
        put(s, 14, y, CHROME[1])
    hline(s, 9, 14, 32, CHROME[2])
    hline(s, 10, 13, 34, VESPA[1])
    hline(s, 11, 12, 34, TAIL[1])
    formula_body(s, {2: 2}, 2, 6, VESPA)  # front fender
    put(s, 10, 2, CLEAR)
    put(s, 13, 2, CLEAR)
    formula_body(s, {9: 5}, 9, 10, VESPA)  # legshield
    formula_body(s, {7: 3}, 7, 8, VESPA)  # headset with the round lamp
    hline(s, 11, 12, 7, HEAD[1])
    hline(s, 11, 12, 8, HEAD[0])
    for x in (7, 8, 15, 16):
        put(s, x, 8, OUT)  # grips
    for y in range(11, 18):  # floorboard: mint rails, grey rubber strips, the rider's shoes and knees
        put(s, 8, y, VESPA[3])
        put(s, 15, y, VESPA[1])
        for x in range(9, 15):
            c = METAL[1] if x % 2 else METAL[0]
            if y in (12, 13) and x not in (11, 12):
                c = VESPA_RIDER["s"]
            elif y > 13 and x not in (11, 12):
                c = VESPA_RIDER["V" if x < 11 else "v"]
            put(s, x, y, c)
    g12_arms(s, (5, 8), (7, 16), [OUT, (30, 40, 92), (54, 68, 134), (84, 100, 170)], (236, 184, 146))
    s.blit(art(VESPA_RIDER_ART, VESPA_RIDER), (7, 14))
    return outline(s)


# Dirt bike: orange/white plastics, knobbly tyres, number plates, rider in MX kit with the number on his back
MOTOCROSS = [(150, 52, 8), (216, 88, 14), (255, 128, 24), (255, 172, 72), (255, 220, 160)]
MOTOCROSS_KIT = {  # white jersey and lid with orange and black, grey pants
    "W": (252, 252, 250), "w": (206, 208, 216), "O": (255, 140, 30), "o": (204, 84, 14),
    "k": OUT, "g": (70, 72, 86), "G": (110, 112, 128), "q": (40, 42, 54),
}  # fmt: skip
MOTOCROSS_RIDER = (
    "...OOoo...",
    "..kGGGgk..",
    "..WWOoww..",
    "..WWOoww..",
    "OOOWOowooo",
    "OOWWWWwwoo",
    ".OWWWWWwo.",
    ".OWWWWWwo.",
    ".OWWWWWwo.",
    ".OWWWWWwo.",
    ".OWWWWWwo.",
    ".OWWWWWwo.",
    ".gGGGGggg.",
    ".gGGgGggq.",
)


def draw_motocross(frame: int) -> Surf:  # trail bike: knobbly tyres roll, beak fender, wide bars
    s = new(24, 40)
    for y0, y1 in ((1, 10), (28, 38)):
        tank_tread(s, 10, y0, 13, y1, frame % 2)
        g12_knobs(s, 10, y0, 13, y1, frame)
    for y in range(1, 10):  # long beak fender over the front tyre
        put(s, 11, y, MOTOCROSS[3 if y > 1 else 4])
        put(s, 12, y, MOTOCROSS[1])
    for y in range(7, 11):  # gold fork legs
        put(s, 9, y, GOLD[3])
        put(s, 14, y, GOLD[1])
    hline(s, 9, 14, 10, (252, 252, 250))  # front number plate
    hline(s, 9, 14, 11, MOTOCROSS[2])
    hline(s, 4, 19, 12, METAL[1])  # wide bars, crossbar pad
    hline(s, 10, 13, 12, MOTOCROSS[0])
    formula_body(s, {13: 3, 14: 4, 18: 3}, 13, 18, MOTOCROSS)  # radiator shrouds
    for y in range(25, 31):  # side number plates
        for x, c in (
            (8, (252, 252, 250)),
            (9, (220, 222, 230)),
            (14, (220, 222, 230)),
            (15, (200, 202, 212)),
        ):
            put(s, x, y, c)
    for y in range(26, 37):  # rear fender
        put(s, 11, y, MOTOCROSS[3])
        put(s, 12, y, MOTOCROSS[1])
    tank_box(s, 10, 24, 13, 28, [OUT, (30, 30, 40), (44, 44, 56), (62, 62, 76), (84, 84, 100)])  # seat
    g12_arms(s, (4, 12), (7, 17), MOTOCROSS[:4], OUT)
    s.blit(art(MOTOCROSS_RIDER, MOTOCROSS_KIT), (7, 12))
    digits(s, 8, 19, "21", OUT)
    return outline(s)


# Motoboy: small commuter bike, tall mirrors, rider in a black lid, big square delivery box on the back
MOTOBOY = [(14, 30, 80), (24, 52, 136), (40, 86, 196), (90, 140, 236), (170, 204, 255)]  # blue tank
MOTOBOY_BOX = [(120, 10, 18), (176, 20, 26), (222, 36, 36), (250, 90, 80), (255, 170, 156)]
MOTOBOY_KIT = {  # black lid with a red stripe, dark jacket with lime reflective bands
    "H": (110, 116, 140), "h": (40, 42, 54), "k": (20, 20, 28), "r": (222, 36, 36),
    "J": (80, 84, 100), "j": (50, 54, 66), "q": (34, 36, 46), "L": (210, 255, 60), "l": (150, 200, 30),
}  # fmt: skip
MOTOBOY_RIDER = (
    "...Hrhh...",
    "..Hhrhhk..",
    "..hhrhkk..",
    "JJjhrhkjqq",
    "JjjjkkjjjQ",
    ".LLLLLLll.",
    ".Jjjjjjqq.",
    ".jjjjjjqq.",
    ".LLLLLLll.",
    "..jjjjqq..",
)


def draw_motoboy(frame: int) -> Surf:  # the box's amber blinkers flash, two frames on, two off
    s = new(24, 40)
    tank_tread(s, 11, 1, 12, 9, frame % 2)
    tank_tread(s, 10, 34, 13, 38, frame % 2)
    hline(s, 11, 12, 3, OUT)  # short black front fender
    hline(s, 11, 12, 4, OUT)
    hline(s, 10, 13, 8, CHROME[2])  # headlamp
    hline(s, 11, 12, 7, HEAD[1])
    put(s, 10, 7, CHROME[3])
    put(s, 13, 7, CHROME[1])
    for x, y, c in ((7, 9, CHROME[2]), (6, 8, CHROME[2]), (16, 9, CHROME[1]), (17, 8, CHROME[1])):
        put(s, x, y, c)  # mirror stalks
    for x0 in (4, 17):
        hline(s, x0, x0 + 2, 7, CHROME[3] if x0 < 12 else CHROME[2])
    hline(s, 6, 17, 10, METAL[1])  # bars
    formula_body(s, {11: 3}, 11, 15, MOTOBOY)  # tank
    put(s, 10, 11, MOTOBOY[4])
    g12_arms(
        s, (5, 10), (7, 16), [MOTOBOY_KIT["q"], MOTOBOY_KIT["j"], MOTOBOY_KIT["j"], MOTOBOY_KIT["J"]], OUT
    )
    s.blit(art(MOTOBOY_RIDER, MOTOBOY_KIT), (7, 13))
    tank_box(s, 6, 23, 17, 35, MOTOBOY_BOX)  # the box: lid frame, recessed panel, reflective tape
    tank_box(s, 8, 25, 15, 32, [MOTOBOY_BOX[0], MOTOBOY_BOX[1], MOTOBOY_BOX[2], MOTOBOY_BOX[3]])
    hline(s, 10, 13, 23, METAL[2])  # latch
    for x in range(7, 17):
        put(s, x, 34, (255, 255, 255) if x % 3 else MOTOBOY_BOX[1])
    amber = (255, 190, 40) if frame < 2 else (140, 80, 20)
    for x in (6, 17):
        put(s, x, 35, amber)
    return outline(s)


# every car in the garage's order (settings.CARS): (style, deco, glass) on vehicle() in CAR_RAMPS[key], or a
# function that draws a whole frame
CAR_DESIGNS: dict[str, tuple[str, Callable[[Surf, dict], None], Sequence[Color]] | Callable[[int], Surf]] = {
    "yellow": ("sport", deco_sport, GLASS),
    "black": ("sedan", deco_stripes, GLASS),
    "blue": ("sedan", deco_police, GLASS),
    "pink": ("sport", deco_convertible, GLASS_CYAN),
    "red": ("jeep", deco_jeep, GLASS),
    "white": ("ambulance", deco_ambulance, GLASS),
    "beetle": ("beetle", deco_beetle, GLASS),
    "moto": draw_moto,
    "taxi": ("sedan", deco_taxi, GLASS),
    "kombi": ("g11_kombi", g11_deco_kombi, GLASS),
    "gol_bolinha": ("g5_hatch", deco_gol_bolinha, GLASS),
    "chevette": ("g5_notch", deco_chevette, GLASS),
    "fiat147": ("g5_box", deco_fiat147, GLASS),
    "uno_escada": ("g5_box", deco_uno_escada, GLASS),
    "shopping_cart": draw_shopping_cart,
    "golf_cart": draw_golf_cart,
    "paint_zebra": ("sedan", deco_paint_zebra, GLASS),
    "paint_checker": ("sport", deco_paint_checker, GLASS),
    "motoboy": draw_motoboy,
    "jdm94": ("g11_supra", g11_deco_jdm94, GLASS),
    "muscle70": ("sedan", deco_muscle70, GLASS),
    "fins59": ("g11_caddy", g11_deco_fins59, GLASS),
    "rc_buggy": draw_rc_buggy,
    "opala": ("classic", deco_opala, GLASS),
    "brasilia": ("g5_wagon", deco_brasilia, GLASS),
    "mini_bean": ("g7_mini", deco_mini_bean, GLASS),
    "mini_job": ("g7_mini", deco_mini_job, GLASS),
    "sofa": draw_sofa,
    "tractor": draw_tractor,
    "samu": draw_samu,
    "scooter": draw_scooter,
    "motocross": draw_motocross,
    "sedan67": ("classic", deco_sedan67, GLASS),
    "mystery_van": ("box", deco_mystery_van, GLASS),
    "stone_age": draw_stone_age,
    "formula": draw_formula,
    "monster": draw_monster,
    "eleanor": draw_eleanor,
    "jurassic_jeep": ("jeep", deco_jurassic_jeep, GLASS),
    "penelope": draw_penelope,
    "mean_machine": draw_mean_machine,
    "kart": draw_kart,
    "fire_truck": draw_fire_truck,
    "paint_matte": ("sport", deco_paint_matte, PAINT_MATTE_GLASS),
    "paint_camo": ("jeep", deco_paint_camo, GLASS),
    "chopper": draw_chopper,
    "robot_camaro": ("sport", deco_robot_camaro, GLASS),
    "cyber": ("jeep", deco_cyber, GLASS),
    "racer5": ("sport", deco_racer5, GLASS_CYAN),
    "delorean": draw_delorean,
    "ecto1": draw_ecto1,
    "kitt": draw_kitt,
    "porsche911": ("g8_911", deco_porsche911, GLASS),
    "paint_neon": draw_paint_neon,
    "paint_flames": draw_paint_flames,
    "akira": draw_akira,
    "racer95": g11_draw_racer95,
    "tank": draw_tank,
    "bat66": draw_bat66,
    "f40": ("g8_f40", deco_f40, GLASS),
    "countach": ("g8_countach", deco_countach, GLASS),
    "paint_chrome": draw_paint_chrome,
    "paint_rainbow": draw_paint_rainbow,
    "tron": draw_tron,
    "bat": draw_bat,
    "robot_truck": ("jeep", deco_robot_truck, GLASS),
    "paint_gold": draw_paint_gold,
    "ghost_rider": draw_ghost_rider,
}
# a mirror of settings.CAR_FRAMES (this script never imports the game): cars with 4 frames instead of 2
CAR_FRAMES = {
    k: 4
    for k in (
        "paint_flames", "paint_rainbow", "paint_gold", "paint_chrome", "paint_neon",
        "kitt", "bat66", "bat", "mean_machine", "delorean", "ecto1",
        "ghost_rider", "tron", "akira", "motoboy",
    )
}  # fmt: skip
SPRITES |= {f"car_{key}": (CAR_FRAMES.get(key, 2), 24, 40) for key in CAR_DESIGNS}


def car_sheet(key: str) -> Surf:
    design, frames = CAR_DESIGNS[key], range(CAR_FRAMES.get(key, 2))
    if callable(design):
        return strip([design(f) for f in frames])
    style, deco, glass = design
    return strip([vehicle(24, 40, (1, 38), STYLES[style], CAR_RAMPS[key], f, deco, glass) for f in frames])


def truck_sheet() -> Surf:
    style = dict(
        insets={1: 2, 2: 1, 3: 0}, wheels=[(5, 11), (46, 51), (54, 59)],
        ws=(4, 7), roof=(8, 15), rear=None, glass_in=2, roof_in=3, head=2,
    )  # fmt: skip
    return strip([vehicle(28, 64, (1, 62), style, TRUCK_CAB, f, deco_truck) for f in (0, 1)])


def van_sheet() -> Surf:
    style = dict(
        insets={1: 3, 2: 1, 3: 0, 46: 1}, wheels=[(6, 12), (35, 41)],
        ws=(9, 12), roof=(13, 44), rear=None, glass_in=2, roof_in=2, head=2,
    )  # fmt: skip
    return strip([vehicle(26, 48, (1, 46), style, VAN, f, deco_van) for f in (0, 1)])


# ---------------------------------------------------------------------------------------------
# Obstacles, pickups, props
# ---------------------------------------------------------------------------------------------
STONE = [(40, 40, 54), (70, 72, 88), (108, 110, 124), (152, 154, 164), (204, 204, 208)]
LEAF = [(18, 50, 46), (28, 84, 54), (48, 122, 58), (92, 166, 66), (162, 210, 92)]
LEAF_OUT = (14, 32, 34)
BARK = [(54, 32, 28), (92, 56, 38), (132, 86, 54), (172, 120, 74), (206, 162, 104)]
WOOD = [(150, 100, 58), (196, 146, 88), (226, 184, 124)]
ORANGE = [(136, 40, 16), (204, 78, 22), (246, 124, 36), (255, 174, 88), (255, 222, 170)]
GOLD = [(124, 62, 16), (192, 114, 22), (240, 172, 36), (255, 216, 94), (255, 250, 214)]
CYAN = [(14, 60, 108), (22, 118, 178), (50, 186, 230), (132, 234, 252), (236, 255, 255)]
METAL = [(54, 58, 74), (92, 98, 118), (146, 154, 172), (206, 212, 226)]
ROAD_RGB = (60, 62, 74)


def stone() -> Surf:
    balls = [
        (9.5, 10, 7.5, 7.5, 2),
        (16.5, 12.5, 5.2, 5.2, 1),
        (12, 16.6, 3.2, 2.7, 3.5),
        (4.6, 17.2, 2, 1.7, 0.5),
    ]
    s = blob(24, 22, balls, STONE, "stone", jitter=0.0, facets=26, bump=0.35)
    return with_shadow(s, 1, 2, 90)


def rock_small() -> Surf:
    s = blob(
        10,
        8,
        [(4.2, 3.8, 3.1, 2.7, 1), (6.4, 4.4, 2.2, 1.9, 1.6)],
        STONE,
        "rock",
        jitter=0.0,
        facets=8,
        bump=0.35,
    )
    return with_shadow(s, 1, 1, 80)


def tree_round(seed: str) -> Surf:
    rng = random.Random(seed)
    balls = [(15.5, 15.5, 11.5, 11.5, -9.0)]  # low base fills gaps between clumps
    for k in range(11):  # rim clumps -> scalloped silhouette
        a = k * math.tau / 11 + rng.uniform(-0.15, 0.15)
        r = rng.uniform(3.8, 4.8)
        d = 12.6 - r
        balls.append((15.5 + d * math.cos(a), 15.5 + d * math.sin(a), r, r, rng.uniform(0.0, 1.5)))
    for k in range(7):  # inner clumps sit higher
        a, d = k * math.tau / 7 + rng.uniform(-0.3, 0.3), rng.uniform(3.5, 6.5)
        r = rng.uniform(3.6, 4.6)
        balls.append((15.5 + d * math.cos(a), 15.5 + d * math.sin(a), r, r, rng.uniform(2.5, 4.0)))
    balls.append((14.5, 14.5, 4.4, 4.4, 5.0))
    return with_shadow(blob(32, 32, balls, LEAF, seed, jitter=0.08, speckle=0.05, edge=LEAF_OUT), 2, 2, 70)


def tree_palm(seed: str) -> Surf:
    """Palm seen from above: arched fronds (light midrib, leaflets angled forward) around a crown."""
    rng = random.Random(seed)
    s, c = new(32, 32), 15.5
    ramp = [(24, 74, 48), (42, 118, 58), (82, 164, 66), (156, 208, 92)]
    angles = [k * math.tau / 9 + rng.uniform(-0.12, 0.12) for k in range(9)]
    angles.sort(key=lambda a: -(math.cos(a) * LX + math.sin(a) * LY))  # lit fronds drawn last (on top)
    for a in angles:
        length, curl = rng.uniform(11.0, 13.0), rng.choice((-1, 1)) * rng.uniform(0.15, 0.35)
        pts = []
        for j in range(40):
            t = j / 39
            ang = a + curl * t
            pts.append(
                (
                    c + math.cos(a) * 1.5 + math.cos(ang) * length * t,
                    c + math.sin(a) * 1.5 + math.sin(ang) * length * t,
                    ang,
                    t,
                )
            )
        for mx, my, ang, t in pts:
            leaflet = 3.6 * math.sin(math.pi * min(1.0, 0.15 + t * 0.95)) * (1 - 0.35 * t)
            for side in (-1, 1):
                la = ang + side * 1.05
                lit = math.cos(la) * LX + math.sin(la) * LY > 0
                k = 0.0
                while k <= leaflet:
                    col = ramp[2] if lit else ramp[1]
                    if k > leaflet - 0.8:
                        col = ramp[1] if lit else ramp[0]
                    put(s, int(mx + math.cos(la) * k), int(my + math.sin(la) * k), col)
                    k += 0.5
        for mx, my, *_ in pts[:-3]:
            put(s, int(mx), int(my), ramp[3])
    for x, y, col in (
        (15, 15, (172, 112, 48)),
        (16, 15, (122, 74, 34)),
        (15, 16, (122, 74, 34)),
        (16, 16, (96, 58, 28)),
    ):
        put(s, x, y, col)
    return with_shadow(outline(s, LEAF_OUT), 2, 2, 70)


# bush's three clumps; bush_snow() lays snow on their tops
BUSH_BALLS = [(5.2, 7.0, 4.2, 3.6, 0), (10.8, 6.8, 4.2, 3.8, 0.4), (8.0, 4.6, 3.6, 3.2, 1.6)]


def bush(variant: int) -> Surf:
    s = blob(16, 12, BUSH_BALLS, LEAF, f"bush{variant}", jitter=0.1, speckle=0.06, edge=LEAF_OUT)
    if variant:
        rng = random.Random("bougainvillea")
        for _ in range(9):
            x, y = rng.randint(3, 12), rng.randint(2, 8)
            if solid(s, x, y) and s.get_at((x, y))[:3] != LEAF_OUT:
                s.set_at((x, y), rng.choice([(236, 84, 150), (255, 160, 206)]))
    return with_shadow(s, 1, 1, 70)


def pothole() -> Surf:
    rng = random.Random("pothole")
    s, cx, cy = new(30, 20), 15.0, 9.5
    harm = [(rng.uniform(0.04, 0.09), k, rng.uniform(0, math.tau)) for k in (2, 3, 5)]

    def wobble(a: float) -> float:
        return 1 + sum(amp * math.cos(k * a + p) for amp, k, p in harm)

    hole: set[tuple[int, int]] = set()
    for y in range(20):
        for x in range(30):
            fx, fy = x + 0.5 - cx, y + 0.5 - cy
            a = math.atan2(fy, fx)
            d_out = math.hypot(fx / 13.6, fy / 8.8) / wobble(a)
            d_hole = math.hypot(fx / 10.0, fy / 6.0) / wobble(a + 0.4)
            if d_hole < 1:
                hole.add((x, y))
                edge = 1 - d_hole
                if edge < 0.3:
                    c = (16, 16, 24) if fy < 0.5 else (88, 86, 96) if edge < 0.16 else (58, 56, 66)
                else:
                    c = (30, 30, 40)
                    if math.hypot((fx - 1) / 4.6, (fy - 1.4) / 1.9) < 1:
                        c = (34, 52, 84) if fy > 0.6 or fx > 1 else (92, 126, 176)
                s.set_at((x, y), c)
            elif d_out < 1:
                r = rng.random()
                if fy > 0 and d_hole < 1.18:
                    c = (112, 114, 126)  # broken lip catching light
                elif r < 0.28:
                    continue
                elif r < 0.6:
                    c = (78, 80, 94)
                else:
                    c = (46, 48, 60)
                s.set_at((x, y), c)
    for x, y in hole:  # dark rim on the inner edge facing away from the light
        if y + 0.5 < cy and any((x + dx, y + dy) not in hole for dx, dy in N4):
            s.set_at((x, y), (12, 12, 20))
    for _ in range(5):  # radiating cracks
        a = rng.uniform(0, math.tau)
        x, y = cx + 12.5 * math.cos(a), cy + 8.0 * math.sin(a)
        for _ in range(rng.randint(2, 4)):
            put(s, int(x), int(y), (40, 40, 52))
            x += math.cos(a) + rng.uniform(-0.6, 0.6)
            y += math.sin(a) * 0.7 + rng.uniform(-0.6, 0.6)
    return s


def trunk(frame: int) -> Surf:
    s = new(44, 18)
    cy, r = 9.0, 6.6
    phase = frame * (math.tau / 7) / 4  # grooves repeat every tau/7 -> loops in 4 frames
    rng = random.Random("trunk")
    breaks = {(k, b): rng.random() < 0.3 for k in range(7) for b in range(10)}
    wob = [rng.uniform(0, math.tau) for _ in range(7)]
    for y in range(2, 16):
        v = (y + 0.5 - cy) / r
        if abs(v) >= 1:
            continue
        th = math.asin(v)
        nz = math.cos(th)
        for x in range(2, 40):
            if (x < 4 and abs(v) > 0.75) or (x < 3 and abs(v) > 0.5):
                continue  # rounded far end
            lum = v * LY + nz * LZ + 0.1
            i = max(0, min(4, int((lum + 0.1) * 4.2)))
            u = (th + phase) / (math.tau / 7)
            k = math.floor(u)
            frac = u - k + 0.08 * math.sin(x * 0.45 + wob[k % 7])
            if not breaks[k % 7, x // 5] and nz > 0.25:
                if 0.42 < frac < 0.6:
                    i = max(0, i - 2)
                elif 0.6 <= frac < 0.72:
                    i = min(4, i + 1)
            s.set_at((x, y), BARK[i])
    ang = frame * math.pi / 4  # end-grain crack rotates (180° symmetric -> 4 frames)
    for y in range(2, 16):
        for x in range(37, 43):
            fx, fy = (x + 0.5 - 39.6) / 2.6, (y + 0.5 - cy) / r
            d = math.hypot(fx, fy)
            if d >= 1:
                continue
            if d > 0.82:
                c = BARK[1]
            else:
                c = WOOD[1] if int(d * 5) % 2 else WOOD[2]
                if abs(fx * math.sin(ang) - fy * math.cos(ang)) < 0.16 and d > 0.2:
                    c = WOOD[0]
                if d < 0.16:
                    c = BARK[1]
            s.set_at((x, y), c)
    return with_shadow(outline(s), 0, 2, 80)


def cone() -> Surf:
    s = new(14, 16)
    rubber = [(34, 34, 44), (58, 58, 72), (84, 84, 100)]
    for y in range(11, 15):
        for x in range(1, 13):
            if (x in (1, 12)) and (y in (11, 14)):
                continue
            put(s, x, y, rubber[2] if y == 11 or x == 1 else rubber[0] if y == 14 or x == 12 else rubber[1])
    cx = 6.5
    for y in range(1, 13):
        half = 0.9 + (y - 1) * 0.42
        for x in range(14):
            fx = x + 0.5 - cx
            if abs(fx) > half:
                continue
            rel = fx / half
            ramp = WHITE if 6 <= y <= 7 else ORANGE
            i = 3 if rel < -0.45 else 2 if rel < 0.35 else 1
            if y <= 2:
                i += 1
            if ramp is WHITE:
                i = min(4, i + 1)
            s.set_at((x, y), ramp[min(4, i)])
    return with_shadow(outline(s), 1, 1, 80)


def coin(frame: int) -> Surf:
    s = new(12, 12)
    a = frame * math.pi / 8
    rx, ry = max(0.7, 4.6 * abs(math.cos(a))), 4.7
    th = 1.4 * abs(math.sin(a))
    side = 1 if math.sin(a) >= 0 else -1
    fcx, ecx, cy = 6 - side * th / 2, 6 + side * th / 2, 6.0
    for y in range(12):
        for x in range(12):
            fx, fy = x + 0.5 - fcx, y + 0.5 - cy
            d = math.hypot(fx / rx, fy / ry)
            de = math.hypot((x + 0.5 - ecx) / rx, fy / ry)
            if d < 1:
                if rx < 1.6:
                    c = GOLD[3] if fx < 0 else GOLD[2]
                elif d > 0.7:
                    c = GOLD[3] if fx + fy < 0 else GOLD[1]
                else:
                    c = GOLD[2]
                    if abs(fx) < 0.6 and abs(fy) < 2.2:
                        c = GOLD[1]  # engraved bar
                    elif abs(fx + 0.9) < 0.6 and abs(fy) < 2.2 and rx > 2.5:
                        c = GOLD[3]
                s.set_at((x, y), c)
            elif de < 1:
                s.set_at((x, y), GOLD[0] if y % 2 else GOLD[1])  # reeded edge
    if rx > 3:
        put(s, round(fcx - rx * 0.5), 3, GOLD[4])
    return outline(s, (70, 34, 20))


def powerup_body(s: Surf, inside: Callable[[int, int], bool], ramp: Sequence[Color]) -> None:
    """Every power icon's bevel: lit rim up-left, dark rim down-right, left half a step lighter."""
    for y in range(16):
        for x in range(16):
            if inside(x, y):
                i = 3 if x < 8 else 2
                if not inside(x - 1, y) or not inside(x, y - 1):
                    i = 4
                elif not inside(x + 1, y) or not inside(x, y + 1):
                    i = 1
                s.set_at((x, y), ramp[i])


def powerup_poly(pts: Sequence[tuple[float, float]]) -> Callable[[int, int], bool]:
    def inside(x: int, y: int) -> bool:  # even-odd test at the pixel centre
        px, py, hit = x + 0.5, y + 0.5, False
        for (ax, ay), (bx, by) in zip(pts, pts[1:] + pts[:1], strict=True):
            if (ay > py) != (by > py) and px < ax + (py - ay) * (bx - ax) / (by - ay):
                hit = not hit
        return hit

    return inside


def powerup_rows(rows: Sequence[str], x0: int, y0: int) -> Callable[[int, int], bool]:
    def inside(x: int, y: int) -> bool:  # '#' cells of a hand-drawn mask placed at (x0, y0)
        return 0 <= y - y0 < len(rows) and 0 <= x - x0 < len(rows[0]) and rows[y - y0][x - x0] == "#"

    return inside


def powerup_glow(s: Surf, frame: int, glow: Color, spark: tuple[int, int]) -> Surf:
    """Outline, then a pulsing glow (two rings fading outward) and the frame-2 sparkle."""
    outline(s)
    alpha = (60, 110, 160, 110)[frame]
    body = {(x, y) for y in range(16) for x in range(16) if s.get_at((x, y))[3] == 255}

    def grow(src: set[tuple[int, int]]) -> set[tuple[int, int]]:
        return {
            (x + dx, y + dy) for x, y in src for dx, dy in N4 if 0 <= x + dx < 16 and 0 <= y + dy < 16
        } - src

    ring1 = grow(body)
    for p in ring1:
        s.set_at(p, (*glow, alpha))
    for p in grow(body | ring1):
        s.set_at(p, (*glow, alpha // 3))
    if frame == 2:
        sx, sy = spark
        for x, y in ((sx, sy), (sx, sy - 1), (sx, sy + 1), (sx - 1, sy), (sx + 1, sy)):
            put(s, x, y, (255, 255, 255, 255 if (x, y) == spark else 200))
    return s


def shield(frame: int) -> Surf:
    s = new(16, 16)

    def inside(x: int, y: int) -> bool:
        fx, fy = x + 0.5 - 8, y + 0.5
        if fy < 3 or fy > 13.6:
            return False
        if fy < 4 and abs(fx) > 4.2:
            return False
        hw = 5.0 if fy < 8 else 5.0 * math.sqrt(max(0.0, 1 - ((fy - 8) / 5.8) ** 2))
        return abs(fx) < hw

    powerup_body(s, inside, CYAN)
    for y in range(5, 11):
        for x in range(5, 11):
            if 7 <= x <= 8 or 7 <= y <= 8:
                s.set_at((x, y), CYAN[4] if x < 8 or y < 8 else (196, 246, 255))
    return powerup_glow(s, frame, (110, 236, 255), (12, 2))


STAR = [(150, 92, 8), (222, 156, 16), (255, 210, 40), (255, 240, 120), (255, 255, 222)]
GHOST = [(96, 74, 168), (150, 124, 220), (204, 190, 250), (234, 228, 255), (255, 255, 255)]
TURBO = [(150, 36, 14), (214, 74, 20), (247, 118, 34), (255, 178, 70), (255, 240, 176)]
SLOW_CAP = [(28, 44, 120), (44, 72, 176), (74, 112, 222), (124, 164, 250), (196, 220, 255)]
SLOW_GLASS = (206, 228, 255)
SLOW_SAND = [(214, 150, 60), (250, 206, 120)]  # shade, lit
LIFE = [(110, 10, 34), (178, 22, 46), (232, 46, 66), (255, 108, 118), (255, 206, 206)]


def star(frame: int) -> Surf:
    """ESTRELA: a chubby gold star with two eyes, rocking side to side."""
    s = new(16, 16)
    tilt = (0, 7, 0, -7)[frame]
    pts = []
    for k in range(10):
        a = math.radians(-90 + tilt + 36 * k)
        r = 7.0 if k % 2 == 0 else 3.6
        pts.append((8 + r * math.cos(a), 8.4 + r * math.sin(a)))
    powerup_body(s, powerup_poly(pts), STAR)
    for x in (6, 9):
        for y in (7, 8):
            s.set_at((x, y), OUT)
    return powerup_glow(s, frame, (255, 222, 80), (13, 2))


GHOST_HEMS = ("##..##..##", "..##..##..")  # the skirt's bottom row, fluttering between 3 and 2 tails


def ghost(frame: int) -> Surf:
    """FANTASMA: a lavender sheet ghost; the hem ripples and the eyes glance left, then right."""
    s = new(16, 16)
    hem = GHOST_HEMS[frame % 2]

    def inside(x: int, y: int) -> bool:
        if not 3 <= x <= 12 or y < 2:
            return False
        if y < 7:
            return math.hypot(x + 0.5 - 8, y + 0.5 - 7) < 5.1
        return y <= 12 or (y == 13 and hem[x - 3] == "#")

    powerup_body(s, inside, GHOST)
    look = -1 if frame < 2 else 1
    for ex in (6 + look, 9 + look):
        s.set_at((ex, 6), OUT)
        s.set_at((ex, 7), OUT)
    s.set_at((8 + look, 9), GHOST[0])  # little "o" of a mouth
    return powerup_glow(s, frame, (196, 168, 255), (13, 2))


TURBO_BOLT = (
    ".....#####", "....#####.", "...#####..", "..#####...", ".#########", "#########.", "...#####..",
    "...####...", "..####....", "..###.....", ".###......", ".##.......", "#.........",
)  # fmt: skip


def turbo(frame: int) -> Surf:
    """TURBO: a flame-orange lightning bolt; a white-hot spark runs down it."""
    s = new(16, 16)
    inside = powerup_rows(TURBO_BOLT, 3, 2)
    powerup_body(s, inside, TURBO)
    band = (2, 5, 8, 11)[frame]  # rows lit by the travelling spark
    for y in range(band, band + 2):
        for x in range(16):
            if inside(x, y) and s.get_at((x, y))[:3] != TURBO[1]:
                s.set_at((x, y), TURBO[4])
    return powerup_glow(s, frame, (255, 146, 56), (2, 3))


def slow(frame: int) -> Surf:
    """DEVAGAR: a blue-capped hourglass, sand trickling through the neck."""
    s = new(16, 16)

    def glass(x: int, y: int) -> bool:
        fx = abs(x + 0.5 - 8)
        return 4 <= y <= 11 and fx < 0.9 + 0.95 * abs(y + 0.5 - 8)

    def cap(x: int, y: int) -> bool:
        return 3 <= x <= 12 and y in (2, 3, 12, 13)

    for y in range(16):
        for x in range(16):
            if glass(x, y):
                s.set_at((x, y), SLOW_GLASS)
    for y in range(6, 8):  # top sand, draining
        for x in range(16):
            if glass(x, y) and glass(x - 1, y) and glass(x + 1, y):
                s.set_at((x, y), SLOW_SAND[x < 8])
    for y in range(10, 12):  # bottom heap
        for x in range(16):
            w = 2.6 if y == 10 else 4.0
            if glass(x, y) and abs(x + 0.5 - 8) < w:
                s.set_at((x, y), SLOW_SAND[x < 8])
    for y in range(8, 10):
        if (y + frame) % 2 == 0:
            s.set_at((7, y), SLOW_SAND[1])  # falling grains
    powerup_body(s, cap, SLOW_CAP)
    return powerup_glow(s, frame, (132, 186, 255), (13, 7))


LIFE_HEARTS = (  # full size, and the squeezed beat of frame 1
    ("..###..###..", ".####..####.", "############", "############", "############",
     ".##########.", "..########..", "...######...", "....####....", ".....##....."),
    (".##....##.", "####..####", "##########", "##########", ".########.", "..######..",
     "...####...", "....##...."),
)  # fmt: skip


def life(frame: int) -> Surf:
    """VIDA EXTRA: a red heart that squeezes on frame 1 and springs back."""
    s = new(16, 16)
    rows = LIFE_HEARTS[frame == 1]
    x0, y0 = 8 - len(rows[0]) // 2, 3 if frame != 1 else 4
    powerup_body(s, powerup_rows(rows, x0, y0), LIFE)
    for x, y in ((x0 + 2, y0 + 2), (x0 + 2, y0 + 3), (x0 + 3, y0 + 2)):
        s.set_at((x, y), LIFE[4])  # glint on the left lobe
    return powerup_glow(s, frame, (255, 84, 104), (13, 2))


def lamp() -> Surf:
    """Street light: concrete foot, pole, arm reaching right to a head with a warm lens."""
    s = new(10, 28)
    concrete = [(108, 108, 118), (146, 146, 156), (186, 186, 194)]
    for y in range(23, 27):
        for x in range(0, 7):
            d = math.hypot((x + 0.5 - 3) / 2.8, (y + 0.5 - 25) / 1.8)
            if d < 1:
                s.set_at((x, y), concrete[2 if (x < 3 and y < 25) else 0 if (x > 4 or y > 25) else 1])
    for y in range(3, 25):
        s.set_at((2, y), METAL[3] if y < 6 else METAL[2])
        s.set_at((3, y), METAL[1])
    hline(s, 2, 8, 2, METAL[3])
    hline(s, 3, 8, 3, METAL[1])
    hline(s, 5, 8, 1, METAL[2])
    hline(s, 5, 8, 4, METAL[0])
    hline(s, 6, 7, 4, (255, 252, 226))
    put(s, 5, 4, (255, 222, 140))
    put(s, 8, 4, (255, 222, 140))
    return with_shadow(outline(s), 1, 1, 70)


FLOWER_ART = [
    ("..y.....", ".yOy..y.", "..yg.yOy", ".g.G..yG", "gG.Gg.Gg", ".GgGGgG."),
    ("......p.", ".p...pOp", "pOp...pG", ".pG.g.G.", "gG.GgGg.", ".GgG.Gg."),
    (".w....l.", "wOw..lOl", ".wG...lg", ".gG.g.G.", "gGgGgGgG", ".G.GgG.."),
]
FLOWER_COLORS = [
    {"y": (255, 212, 60), "O": (206, 110, 30)},
    {"p": (240, 88, 140), "O": (255, 228, 130)},
    {"w": (246, 246, 255), "l": (170, 140, 236), "O": (255, 200, 70)},
]


def flowers(i: int) -> Surf:
    return art(FLOWER_ART[i], {"g": (92, 166, 66), "G": (40, 104, 52), **FLOWER_COLORS[i]})


def blinker(frame: int) -> Surf:
    if frame:
        return art(
            ["......", "......", "..dd..", "..dD..", "......", "......"],
            {"d": (150, 72, 22), "D": (110, 50, 16)},
        )
    rows = [".oooo.", "oyYYyo", "oYWWYo", "oYWWYo", "oyYYyo", ".oooo."]
    legend = {"o": (255, 132, 24, 120), "y": (255, 160, 40), "Y": (255, 204, 84), "W": (255, 252, 226)}
    return art(rows, legend)


# Biome props: desert cactus, snow pine and snowman, dry and snowy bushes (bush frames 2 and 3)
CACTUS_GREEN = [(22, 58, 54), (36, 94, 70), (60, 132, 82), (102, 172, 98), (170, 214, 134)]
CACTUS_SPINE = (240, 232, 188)
CACTUS_BLOOM = [(200, 40, 96), (246, 92, 150), (255, 176, 212), (255, 220, 92)]  # shade, petal, lit, heart
CACTUS_SAGUARO = (  # trunk + two arms, lit from the left, ribs as grooves; caps lit seen a little from above
    "..............",
    ".....eed......",
    "....eedcb.....",
    "....dbcab.....",
    "....dbcab..e..",
    "....dbcab.eed.",
    "....dbcab.dba.",
    "....dbcab.dba.",
    ".ed.dbcab.dba.",
    ".db.dbcab.dba.",
    ".db.dbcab.dba.",
    ".db.dbcab.dba.",
    ".db.dbcabcdba.",
    ".db.dbcabbdba.",
    ".db.dbcabaaa..",
    ".dbcdbcab.....",
    ".dbbdbcab.....",
    "..aadbcab.....",
    "....dbcab.....",
    "....dbcab.....",
    "....dbcab.....",
    "....dbcab.....",
    "....dbcab.....",
    "....bbaaa.....",
)
CACTUS_SAGUARO_SPINES = ((4, 5), (6, 8), (4, 11), (6, 14), (4, 17), (6, 20), (10, 8), (10, 11), (1, 11))


def cactus_saguaro() -> Surf:
    s = new(14, 26)
    s.blit(art(CACTUS_SAGUARO, dict(zip("abcde", CACTUS_GREEN, strict=True))), (0, 0))
    for x, y in CACTUS_SAGUARO_SPINES:
        put(s, x, y, CACTUS_SPINE)
    return with_shadow(outline(s, LEAF_OUT), 1, 1, 80)


CACTUS_GOLD = [(176, 136, 60), (240, 204, 100)]  # barrel spines: shade, lit


def cactus_barrel() -> Surf:
    """Golden barrel cactus: ribs bowing round the ball, spines on the ridges, a pink bloom on the crown."""
    s = new(14, 26)
    cx, cy, rx, ry = 6.5, 18.5, 5.5, 5.3
    angles = (-0.95, 0.0, 0.95)  # rib grooves facing us; spiny ridges sit halfway between
    for y in range(13, 24):
        dy = (y + 0.5 - cy) / ry
        hw = rx * math.sqrt(max(0.0, 1 - dy * dy))
        grooves = {round(cx + math.sin(a) * hw - 0.5) for a in angles}
        ridges = {round(cx + math.sin(a + 0.47) * hw - 0.5) for a in angles[:-1]}
        for x in range(14):
            dx = (x + 0.5 - cx) / rx
            if dx * dx + dy * dy >= 1:
                continue
            nz = math.sqrt(1 - dx * dx - dy * dy)
            i = max(1, min(4, int((dx * LX + dy * LY + nz * LZ + 0.12) / 1.02 * 5)))
            c = CACTUS_GREEN[i]
            if dy < -0.6 and abs(dx) < 0.42:
                c = CACTUS_BLOOM[3] if abs(dx) < 0.1 and dy > -0.85 else CACTUS_BLOOM[2 if dx < 0 else 1]
            elif x in grooves and dy > -0.75:
                c = CACTUS_GREEN[i - 1 if i < 3 else i - 2]
            elif x in ridges and y % 2 and dy > -0.75:
                c = CACTUS_GOLD[i >= 3]
            s.set_at((x, y), c)
    return with_shadow(outline(s, LEAF_OUT), 1, 1, 80)


PINE_NEEDLE = [(12, 40, 44), (20, 64, 56), (30, 92, 62), (52, 124, 70), (98, 162, 88)]
SNOWMAN_SNOW = [(104, 122, 170), (150, 170, 212), (200, 214, 238), (234, 241, 252), (255, 255, 255)]
PINE_TIERS = ((1, 8, 0.8, 3.6), (5, 14, 1.6, 5.6), (10, 20, 2.6, 7.4), (15, 26, 3.6, 9.0))  # y0, y1, hw0, hw1
PINE_SNOW_DEPTH = (0.75, 0.6, 0.5, 0.4)  # share of each visible skirt under snow, top tier first


def pine(snowy: bool) -> Surf:
    """Conifer in three-quarter view: four skirts, each front edge bowing down toward the camera."""
    s, rng, cx = new(20, 32), random.Random("pine"), 10.0
    for y in range(26, 30):
        for x in range(8, 12):
            s.set_at((x, y), BARK[3] if x == 8 else BARK[1] if x < 11 else BARK[0])
    owner: dict[tuple[int, int], tuple[int, float, float]] = {}
    for k, (yt, yb, w0, w1) in enumerate(PINE_TIERS):
        for y in range(yt, yb + 3):
            for x in range(20):
                f = x + 0.5 - cx
                hw = w0 + (w1 - w0) * min(1.0, (y - yt) / (yb - yt))
                bottom = yb + 1.8 * (1 - (f / w1) ** 2) - (0.9 if (x + k) % 3 else 0)
                if abs(f) <= hw and y + 0.5 <= bottom and (x, y) not in owner:
                    owner[x, y] = (k, f / hw, (y + 0.5 - yt) / (bottom - yt))
    for (x, y), (k, u, v) in sorted(owner.items()):
        d = next(j for j in range(32) if owner.get((x, y - j - 1), (-1,))[0] != k)  # rows of this skirt above
        n = d + next(j for j in range(32) if owner.get((x, y + j + 1), (-1,))[0] != k) + 1
        covered = (x, y - d - 1) in owner  # a higher skirt overlaps this one here
        i = 3 if u < -0.45 else 2 if u < 0.15 else 1 if u < 0.65 else 0
        if v > 0.8 and u < 0.3:
            i += 1  # lit branch tips along the front edge
        if covered and d < 2:
            i -= 2 - d  # in the shade of the skirt above
        if rng.random() < 0.12:
            i += rng.choice((-1, 1))
        c = PINE_NEEDLE[max(0, min(4, i))]
        if snowy and covered <= d < PINE_SNOW_DEPTH[k] * n + (x * 7 + k * 3) % 3 - 1:
            c = SNOWMAN_SNOW[max(1, min(4, i + 1))]
        s.set_at((x, y), c)
    return with_shadow(outline(s, LEAF_OUT), 1, 1, 80)


SNOWMAN_SCARF = [(150, 20, 36), (220, 44, 56), (255, 112, 104)]
SNOWMAN_CARROT = [(204, 78, 22), (255, 140, 40)]
SNOWMAN_COAL = (34, 34, 46)
SNOWMAN_TWIG = (92, 56, 38)


def snowman() -> Surf:
    """Three snowballs seen a little from above: coal face, carrot nose, red scarf, twig arms."""
    balls = [(6.5, 11.9, 4.6, 3.4, 0), (6.5, 7.6, 3.4, 2.7, 2.0), (6.5, 3.2, 2.6, 2.3, 4.0)]
    s = blob(12, 16, balls, SNOWMAN_SNOW, "snowman", jitter=0.0)
    for x in range(4, 9):  # scarf round the neck, its tail hanging on the lit side
        put(s, x, 5, SNOWMAN_SCARF[2 if x < 6 else 1])
    put(s, 4, 6, SNOWMAN_SCARF[1])
    put(s, 4, 7, SNOWMAN_SCARF[0])
    for x, y in ((5, 2), (7, 2), (6, 8), (6, 10)):  # eyes, buttons
        put(s, x, y, SNOWMAN_COAL)
    put(s, 6, 3, SNOWMAN_CARROT[1])
    put(s, 7, 4, SNOWMAN_CARROT[0])
    for x, y in ((2, 7), (1, 6), (0, 5), (10, 7), (11, 6), (11, 5)):  # twig arms
        put(s, x, y, SNOWMAN_TWIG)
    return with_shadow(s, 1, 1, 80)


BUSH_DRY = [(52, 32, 22), (96, 60, 36), (140, 94, 52), (180, 130, 70)]  # shade, twig, lit twig, tip
BUSH_DRY_LEAF = [(110, 104, 48), (150, 140, 64)]
BUSH_DRY_STEMS = (  # root to tip; a stem may start on another one (a fork)
    ((7, 10), (7, 9), (7, 8), (8, 7), (8, 6), (7, 5), (8, 4), (8, 3), (8, 2), (8, 1)),
    ((7, 10), (6, 9), (5, 8), (4, 7), (3, 6), (2, 6), (1, 5)),
    ((7, 8), (6, 7), (5, 6), (5, 5), (4, 4), (4, 3), (3, 2)),
    ((8, 7), (9, 6), (10, 5), (10, 4), (11, 3), (12, 2)),
    ((8, 10), (9, 9), (10, 8), (11, 7), (12, 7), (13, 6), (14, 5)),
    ((5, 5), (6, 4), (6, 3), (6, 2)),
    ((10, 5), (11, 5), (12, 4)),
    ((3, 6), (2, 4)),
)
BUSH_DRY_LEAVES = ((1, 4, 1), (3, 1, 0), (8, 0, 1), (12, 1, 0), (14, 4, 1), (6, 1, 0), (13, 3, 1), (2, 3, 0))


def bush_dry() -> Surf:
    """Dry desert scrub: bare stems fanning up from one root, a few khaki leaves left on the tips."""
    s = new(16, 12)
    for stem in BUSH_DRY_STEMS:
        for j, (x, y) in enumerate(stem):
            put(s, x, y, BUSH_DRY[3 if j == len(stem) - 1 else 2 if y < 7 else 1])
    for x, y, i in BUSH_DRY_LEAVES:
        put(s, x, y, BUSH_DRY_LEAF[i])
    for x, y in [(x, y) for y in range(12) for x in range(16) if solid(s, x, y)]:
        if not solid(s, x, y + 1):  # 1 px shade under each twig gives it some body
            put(s, x, y + 1, BUSH_DRY[0])
    return with_shadow(s, 1, 1, 70)


def bush_snow() -> Surf:
    """Today's bush with snow lying on top of each clump."""
    s, rng = bush(0), random.Random("bush_snow")
    for y in range(12):
        for x in range(16):
            c = s.get_at((x, y))
            if c[3] < 255 or c[:3] == LEAF_OUT:
                continue
            best = None
            for bx, by, rx, ry, z in BUSH_BALLS:
                dx, dy = (x + 0.5 - bx) / rx, (y + 0.5 - by) / ry
                if dx * dx + dy * dy < 1:
                    nz = math.sqrt(1 - dx * dx - dy * dy)
                    if best is None or z + nz * min(rx, ry) > best[0]:
                        best = (z + nz * min(rx, ry), dx, dy, nz)
            if best and best[2] < -0.05 + rng.uniform(-0.25, 0.2):
                _, dx, dy, nz = best
                i = int((dx * LX + dy * LY + nz * LZ + 0.12) / 1.02 * 5)
                s.set_at((x, y), SNOWMAN_SNOW[max(1, min(4, i + 1))])
    return s


# Biome props: city rooftops, volcano basalt and lava
# Night city rooftops: a height map (parapet 1, units 3, tank 4) shaded from the upper-left, with
# diagonal cast shadows; warm skylights and a red beacon are the lit details that read at night.
BUILDING_CONCRETE = [
    (28, 30, 46),
    (44, 48, 68),
    (60, 65, 88),
    (78, 84, 110),
    (102, 109, 138),
    (140, 148, 178),
]
BUILDING_TAR = [(34, 26, 42), (52, 40, 60), (70, 56, 78), (90, 74, 98), (118, 100, 126), (156, 138, 164)]
BUILDING_METAL = [(30, 34, 46), (58, 64, 82), (90, 98, 118), (128, 136, 156), (176, 184, 202)]
BUILDING_TANK = [(16, 36, 84), (26, 58, 128), (42, 90, 170), (82, 136, 210), (150, 196, 240)]
BUILDING_GLASS = [(64, 46, 34), (230, 150, 60), (255, 206, 106), (255, 246, 206)]  # frame, deep, glass, glint

BuildingCells = dict[tuple[int, int], tuple[int, str]]


def building_rect(cells: BuildingCells, x0: int, y0: int, x1: int, y1: int, h: int, mat: str) -> None:
    for y in range(y0, y1 + 1):
        for x in range(x0, x1 + 1):
            cells[x, y] = (h, mat)


def building_shell(cells: BuildingCells, rects: Sequence[tuple[int, int, int, int]], roof: str) -> None:
    """Union of footprint rects: a 2 px parapet (height 1) round a flat roof (height 0)."""
    for x0, y0, x1, y1 in rects:
        building_rect(cells, x0, y0, x1, y1, 0, roof)
    inside = set(cells)
    for x, y in inside:
        if any((x + dx, y + dy) not in inside for dx in range(-2, 3) for dy in range(-2, 3)):
            cells[x, y] = (1, roof + "_wall")


BuildingMats = dict[str, tuple[Sequence[Color], int, float]]  # material -> (ramp, base index, gravel)


def building_render(cells: BuildingCells, mats: BuildingMats, seed: str) -> Surf:
    rng, s = random.Random(seed), new(40, 40)

    def hgt(x: int, y: int) -> int:
        c = cells.get((x, y))
        return c[0] if c else -1

    for (x, y), (h, m) in sorted(cells.items()):
        ramp, i, speck = mats[m]
        if hgt(x - 1, y) < h or hgt(x, y - 1) < h:
            i += 1  # edge facing the light
        elif hgt(x + 1, y) < h or hgt(x, y + 1) < h:
            i -= 1
        if any(hgt(x - k, y - k) >= h + k for k in range(1, 8)):
            i -= 2  # cast shadow, falling down-right
        if speck and rng.random() < speck:
            i -= 1  # dark gravel
        s.set_at((x, y), ramp[max(0, min(len(ramp) - 1, i))])
    return s


def building_skylight(s: Surf, x0: int, y0: int, panes: int) -> None:
    """A row of lit 2x3 glass panes in a dark frame (shared mullions)."""
    for y in range(y0, y0 + 5):
        for x in range(x0, x0 + 3 * panes + 1):
            if (x - x0) % 3 == 0 or y in (y0, y0 + 4):
                c = BUILDING_GLASS[0]
            elif (x - x0) % 3 == 1 and y == y0 + 1:
                c = BUILDING_GLASS[3]
            else:
                c = BUILDING_GLASS[1] if y == y0 + 3 else BUILDING_GLASS[2]
            put(s, x, y, c)


def building_fan(s: Surf, cx: float, cy: float) -> None:
    """Condenser fan from above: dark round grille, lit lower-right lip, bright hub."""
    for y in range(int(cy) - 3, int(cy) + 4):
        for x in range(int(cx) - 3, int(cx) + 4):
            fx, fy = x + 0.5 - cx, y + 0.5 - cy
            d = math.hypot(fx, fy)
            if d < 2.7:
                c = BUILDING_METAL[0]
                if d > 1.7 and fx + fy > 1.2:
                    c = BUILDING_METAL[2]
                elif d < 0.8:
                    c = BUILDING_METAL[3]
                put(s, x, y, c)


def building(frame: int) -> Surf:
    cells: BuildingCells = {}
    mats = {
        "concrete": (BUILDING_CONCRETE, 3, 0.1),
        "concrete_wall": (BUILDING_CONCRETE, 4, 0.0),
        "tar": (BUILDING_TAR, 3, 0.0),
        "tar_wall": (BUILDING_TAR, 4, 0.0),
        "box": (BUILDING_CONCRETE, 4, 0.0),
        "metal": (BUILDING_METAL, 2, 0.0),
        "pipe": (BUILDING_METAL, 3, 0.0),
        "tank": (BUILDING_TANK, 2, 0.0),
    }
    if frame == 0:  # concrete roof: blue water tank, stair box with a lit door, roof hatch, skylights
        building_shell(cells, [(1, 1, 36, 36)], "concrete")
        building_rect(cells, 22, 4, 31, 11, 3, "box")
        building_rect(cells, 5, 25, 9, 29, 1, "metal")
        tank = blob(11, 11, [(5.5, 5.5, 4.4, 4.4, 0)], BUILDING_TANK, "tank", jitter=0.0)
        for y in range(11):
            for x in range(11):
                if tank.get_at((x, y))[3]:
                    cells[x + 4, y + 4] = (4, "tank")
        s = building_render(cells, mats, "building0")
        for y in range(11):  # lid groove
            for x in range(11):
                if 2.1 < math.hypot(x + 0.5 - 5.5, y + 0.5 - 5.5) < 2.9:
                    tank.set_at((x, y), BUILDING_TANK[1] if x + y > 10 else BUILDING_TANK[3])
        s.blit(tank, (4, 4))
        for x, y, c in ((9, 9, (255, 160, 150)), (10, 9, (226, 44, 52)), (9, 10, (226, 44, 52))):
            put(s, x, y, c)  # red beacon on the lid
        put(s, 10, 10, (150, 24, 40))
        hline(s, 25, 27, 11, BUILDING_GLASS[2])  # open door, its light spilling onto the roof
        hline(s, 25, 27, 12, (164, 140, 112))
        hline(s, 24, 28, 13, (126, 112, 104))
        hline(s, 25, 27, 14, (104, 98, 104))
        building_skylight(s, 21, 22, 4)
        building_skylight(s, 21, 28, 4)
    else:  # L-shaped tar roof: two condensers on a duct, a long skylight
        building_shell(cells, [(1, 9, 36, 36), (1, 1, 22, 9)], "tar")
        building_rect(cells, 10, 12, 11, 25, 1, "pipe")
        building_rect(cells, 10, 24, 28, 25, 1, "pipe")
        building_rect(cells, 4, 4, 11, 11, 3, "metal")
        building_rect(cells, 24, 15, 31, 22, 3, "metal")
        s = building_render(cells, mats, "building1")
        for (x, y), (_, m) in cells.items():  # membrane seams
            if m == "tar" and y % 5 == 2 and s.get_at((x, y))[:3] == BUILDING_TAR[3]:
                s.set_at((x, y), BUILDING_TAR[2])
        building_fan(s, 8.0, 8.0)
        building_fan(s, 28.0, 19.0)
        building_skylight(s, 5, 29, 9)
    return with_shadow(outline(s), 2, 2, 90)


# Volcano: chiselled basalt (lit top-left facet, dark flank, a faint ember line where it sits on the hot
# ground) and a crusted lava pool.
BASALT = {
    "o": (14, 10, 16), "e": (168, 52, 28), "r": (78, 38, 38),
    "1": (12, 12, 18), "2": (40, 40, 54), "3": (62, 62, 80), "4": (92, 94, 114), "5": (142, 146, 168),
}  # fmt: skip
BASALT_ART = (
    (  # one big chunk
        "....oooo......",
        "..oo5543ooo...",
        ".o554444133o..",
        "o54444441333o.",
        ".o44444413322o",
        ".o34441122222e",
        "..o11222r2r1e.",
        "...oeeeeeee...",
        "..............",
        "..............",
    ),
    (  # a chunk with a splinter leaning on it
        "..oooo........",
        ".o5543o..ooo..",
        "o554443o.o543o",
        "o5444413oo432o",
        "o4444122o3322o",
        ".o3411222o221e",
        "..o112r21o1re.",
        "...oeeeee.ee..",
        "..............",
        "..............",
    ),
)
LAVA = [(110, 20, 14), (182, 40, 16), (234, 88, 24), (255, 150, 40), (255, 212, 84), (255, 248, 196)]
LAVA_CRUST = [(20, 12, 14), (40, 24, 24), (62, 38, 32)]  # outline, crust, crust lit top-left


def basalt(frame: int) -> Surf:
    return with_shadow(art(BASALT_ART[frame], BASALT), 1, 1, 80)


def lava() -> Surf:
    """Pool: crust ring (lit outer top-left, glowing inner lip), molten bands to a white-hot core, cracks."""
    rng = random.Random("lava")
    s, cx, cy = new(24, 14), 12.0, 7.0
    harm = [(rng.uniform(0.04, 0.08), k, rng.uniform(0, math.tau)) for k in (2, 3, 5)]
    for y in range(14):
        for x in range(24):
            fx, fy = x + 0.5 - cx, y + 0.5 - cy
            a = math.atan2(fy, fx)
            d = math.hypot(fx / 10.2, fy / 5.6) / (1 + sum(amp * math.cos(k * a + p) for amp, k, p in harm))
            if d >= 1:
                continue
            if d > 0.72:
                c = LAVA_CRUST[2 if fx + 1.6 * fy < -6 else 1]
                if d < 0.8:
                    c = LAVA[0]  # crust lip lit by the melt
            else:
                heat = (1 - d / 0.72) * 4.6 + 0.35 * math.sin(fx * 0.7 - fy * 1.3)
                c = LAVA[max(1, min(5, round(heat)))]
            s.set_at((x, y), c)
    for x, y in ((7, 5), (8, 5), (16, 9), (17, 9), (17, 8), (14, 3)):  # floating crust plates
        s.set_at((x, y), LAVA_CRUST[1])
    for x, y in ((2, 7), (3, 7), (21, 6), (22, 5), (12, 1), (11, 12)):  # cracks glowing through the crust
        if s.get_at((x, y))[3]:
            s.set_at((x, y), LAVA[1])
    return outline(s, LAVA_CRUST[0])


def tile_noise(w: int, h: int, cell: int, rng: random.Random) -> list[list[float]]:
    gw, gh = w // cell, h // cell
    g = [[rng.random() for _ in range(gw)] for _ in range(gh)]

    def at(x: int, y: int) -> float:
        fx, fy = x / cell, y / cell
        ix, iy = int(fx), int(fy)
        tx, ty = fx - ix, fy - iy
        tx, ty = tx * tx * (3 - 2 * tx), ty * ty * (3 - 2 * ty)
        a, b = g[iy % gh][ix % gw], g[iy % gh][(ix + 1) % gw]
        c, d = g[(iy + 1) % gh][ix % gw], g[(iy + 1) % gh][(ix + 1) % gw]
        return (a + (b - a) * tx) * (1 - ty) + (c + (d - c) * tx) * ty

    return [[at(x, y) for x in range(w)] for y in range(h)]


def road_tile() -> Surf:
    w, h = 160, 64
    rng = random.Random("road")
    big, small = tile_noise(w, h, 32, rng), tile_noise(w, h, 8, rng)
    s = pygame.Surface((w, h), pygame.SRCALPHA)
    for y in range(h):
        for x in range(w):
            lx = x % 32
            track = lx in (7, 8, 9, 22, 23, 24)  # tyre-polished bands, two per lane
            # Low-frequency mottling posterised into a few flat shades (pixel-art discipline; it also keeps
            # the scrolling road cheap to encode in the README GIF), plus sparse light and dark grit.
            mottle = (big[y][x] - 0.5) * 10 + (small[y][x] - 0.5) * 1.5 - (2.5 if track else 0)
            v = 3.0 * round(mottle / 3.0)
            r = rng.random()
            if r < 0.014:
                v = 13.0 if rng.random() < 0.6 else 9.0
            elif r < 0.03:
                v = -7.0
            base = ROAD_RGB
            s.set_at((x, y), (round(base[0] + v), round(base[1] + v), round(base[2] + v * 1.1), 255))
    for _ in range(3):  # short sealed cracks (wrap so the tile stays seamless)
        x, y = rng.randrange(w), rng.randrange(h)
        for _ in range(rng.randint(5, 9)):
            c = s.get_at((x % w, y % h))
            s.set_at((x % w, y % h), (c[0] - 9, c[1] - 9, c[2] - 9, 255))
            x += rng.choice((-1, 0, 1))
            y += 1
    return s


RUBBER = [(26, 26, 34), (44, 44, 56), (64, 64, 78), (90, 90, 106), (124, 124, 142)]
CHROME = [(60, 66, 84), (116, 124, 142), (170, 178, 194), (222, 228, 238), (255, 255, 255)]
FIRE = [(150, 22, 32), (228, 58, 34), (255, 138, 30), (255, 208, 60), (255, 248, 200)]


def icon() -> Surf:
    """Flaming tyre: tread on the left, chrome 5-spoke rim, flames trailing up-right."""
    s = new(64, 64)
    rng = random.Random("icon")
    fcx, bcx, cy, rx, ry = 31.0, 23.0, 36.0, 14.5, 22.5
    tongues = []
    for k in range(8):
        a = math.radians(-115 + k * 24 + rng.uniform(-6, 6))
        root = (fcx + rx * 0.7 * math.cos(a), cy + ry * 0.75 * math.sin(a))
        d = _unit(1.0 + rng.uniform(-0.25, 0.2), -0.75 + rng.uniform(-0.25, 0.25), 0)
        tongues.append((root, d, rng.uniform(22, 33), rng.uniform(5.5, 8.5), rng.uniform(0, math.tau)))
    for y in range(64):
        for x in range(64):
            heat = 0.0
            for (ox, oy), (dx, dy, _), length, width, ph in tongues:
                vx, vy = x + 0.5 - ox, y + 0.5 - oy
                t = (vx * dx + vy * dy) / length
                if not -0.2 < t < 1:
                    continue
                perp = -vx * dy + vy * dx + math.sin(t * 7 + ph) * 2.2 * max(0.0, t)
                half = width * (1 - max(t, 0)) ** 0.75
                f = 1 - abs(perp) / half
                if f > 0:
                    heat = max(heat, f * (1 - 0.72 * max(t, 0)))
            if heat > 0.07:
                i = 4 if heat > 0.66 else 3 if heat > 0.48 else 2 if heat > 0.3 else 1 if heat > 0.15 else 0
                s.set_at((x, y), FIRE[i])
    outline(s, (96, 14, 26))

    def in_tyre(x: int, y: int) -> bool:
        fy = (y + 0.5 - cy) / ry
        if abs(fy) >= 1:
            return False
        half = rx * math.sqrt(1 - fy * fy)
        return bcx - half <= x + 0.5 <= fcx + half

    spokes = [k * math.tau / 5 - math.pi / 2 + 0.25 for k in range(5)]
    for y in range(64):
        for x in range(64):
            if not in_tyre(x, y):
                continue
            nx, ny = (x + 0.5 - fcx) / rx, (y + 0.5 - cy) / ry
            r = math.hypot(nx, ny)
            ang = math.atan2(ny, nx)
            if r >= 1:  # tread band
                fy = (y + 0.5 - cy) / ry
                lum = 0.55 - 0.5 * fy
                c = RUBBER[max(1, min(3, int(lum * 4)))]
                if (y + int(abs(x + 0.5 - (bcx + fcx) / 2 + 4) / 2)) % 4 == 0:
                    c = RUBBER[0]
            elif r > 0.6:  # sidewall
                lit = -(math.cos(ang) * 0.6 + math.sin(ang) * 0.8)
                i = 2 + (1 if lit > 0.35 else -1 if lit < -0.35 else 0)
                if 0.9 < r < 0.96 and lit > 0:
                    i = 4
                elif r < 0.66:
                    i = 0
                c = RUBBER[i]
            elif r > 0.5:  # rim lip
                c = (
                    CHROME[3]
                    if math.cos(ang) + math.sin(ang) < -0.2
                    else CHROME[1]
                    if r > 0.55
                    else CHROME[2]
                )
            elif r < 0.16:  # hub
                c = CHROME[4] if r < 0.07 else CHROME[2] if nx + ny < 0 else CHROME[1]
            else:
                dist = min(abs((ang - sp + math.pi) % math.tau - math.pi) for sp in spokes)
                width = 0.34 - 0.18 * r
                if dist < width:
                    near = min(spokes, key=lambda sp: abs((ang - sp + math.pi) % math.tau - math.pi))
                    c = CHROME[3] if ((ang - near + math.pi) % math.tau - math.pi) < 0 else CHROME[2]
                else:
                    c = (34, 36, 50) if r < 0.42 else CHROME[0]
            s.set_at((x, y), c)

    def on_edge(x: int, y: int) -> bool:
        return in_tyre(x, y) and not all(in_tyre(x + dx, y + dy) for dx, dy in N4)

    for y in range(64):  # crisp outline around the tyre, inside its mask
        for x in range(64):
            if on_edge(x, y):
                s.set_at((x, y), OUT)
            elif in_tyre(x, y) and any(on_edge(x + dx, y + dy) for dx, dy in N4):
                s.set_at((x, y), (138, 143, 168))  # light rim: keeps the tyre readable on dark docks/taskbars
            nx, ny = (x + 0.5 - fcx) / rx, (y + 0.5 - cy) / ry
            if in_tyre(x, y) and 0.97 < math.hypot(nx, ny) < 1.06 and nx < 0.2:
                s.set_at((x, y), OUT)  # sidewall / tread edge
    return s


def build_sprites() -> dict[str, Surf]:
    out = {f"car_{key}": car_sheet(key) for key in CAR_DESIGNS}
    out |= {
        "truck": truck_sheet(),
        "van": van_sheet(),
        "stone": stone(),
        "pothole": pothole(),
        "trunk": strip([trunk(f) for f in range(4)]),
        "cone": cone(),
        "coin": strip([coin(f) for f in range(8)]),
        "shield": strip([shield(f) for f in range(4)]),
        "star": strip([star(f) for f in range(4)]),
        "ghost": strip([ghost(f) for f in range(4)]),
        "turbo": strip([turbo(f) for f in range(4)]),
        "slow": strip([slow(f) for f in range(4)]),
        "life": strip([life(f) for f in range(4)]),
        "tree": strip([tree_round("tree0"), tree_palm("palm")]),
        "bush": strip([bush(0), bush(1), bush_dry(), bush_snow()]),
        "lamp": lamp(),
        "rock_small": rock_small(),
        "flowers": strip([flowers(i) for i in range(3)]),
        "cactus": strip([cactus_saguaro(), cactus_barrel()]),
        "pine": strip([pine(False), pine(True)]),
        "snowman": snowman(),
        "building": strip([building(0), building(1)]),
        "basalt": strip([basalt(0), basalt(1)]),
        "lava": lava(),
        "blinker": strip([blinker(0), blinker(1)]),
        "road_tile": road_tile(),
        "icon": icon(),
    }
    return out


# ---------------------------------------------------------------------------------------------
# Audio DSP (mono float lists at 22050 Hz)
# ---------------------------------------------------------------------------------------------
SR = 22050
TAU = math.tau
PEAK = 10 ** (-1.2 / 20)  # normalisation target, a hair under the -1 dBFS limit
LIMIT = 10 ** (-1 / 20)
Sig = list[float]


def note_hz(m: float) -> float:
    return 440.0 * 2 ** ((m - 69) / 12)


def _dts(f: float | Sig, n: int) -> Sig:
    return [v / SR for v in f] if isinstance(f, list) else [f / SR] * n


def _blep(t: float, dt: float) -> float:
    if t < dt:
        t /= dt
        return t + t - t * t - 1.0
    if t > 1.0 - dt:
        t = (t - 1.0) / dt
        return t * t + t + t + 1.0
    return 0.0


def saw(f: float | Sig, n: int, phase: float = 0.0) -> Sig:
    out, t = [0.0] * n, phase
    for i, dt in enumerate(_dts(f, n)):
        out[i] = 2.0 * t - 1.0 - _blep(t, dt)
        t += dt
        if t >= 1.0:
            t -= 1.0
    return out


def pulse(f: float | Sig, n: int, pw: float = 0.5, phase: float = 0.0) -> Sig:
    out, t = [0.0] * n, phase
    for i, dt in enumerate(_dts(f, n)):
        t2 = t - pw + (1.0 if t < pw else 0.0)
        out[i] = (1.0 if t < pw else -1.0) + _blep(t, dt) - _blep(t2, dt)
        t += dt
        if t >= 1.0:
            t -= 1.0
    return out


def tri(f: float | Sig, n: int) -> Sig:
    out, t = [0.0] * n, 0.25
    for i, dt in enumerate(_dts(f, n)):
        out[i] = 4.0 * abs(t - 0.5) - 1.0
        t += dt
        if t >= 1.0:
            t -= 1.0
    return out


def sine(f: float | Sig, n: int, phase: float = 0.0) -> Sig:
    out, t = [0.0] * n, phase
    sin = math.sin
    for i, dt in enumerate(_dts(f, n)):
        out[i] = sin(TAU * t)
        t += dt
        if t >= 1.0:
            t -= 1.0
    return out


def noise(n: int, rng: random.Random) -> Sig:
    u = rng.uniform
    return [u(-1.0, 1.0) for _ in range(n)]


def lp(x: Sig, fc: float | Sig, poles: int = 1) -> Sig:
    """One-pole low-pass (cascaded), in place; fc may vary per sample."""
    n = len(x)
    if isinstance(fc, list):
        co = [1.0 - math.exp(-TAU * min(c, SR * 0.45) / SR) for c in fc]
    else:
        co = [1.0 - math.exp(-TAU * fc / SR)] * n
    for _ in range(poles):
        y = 0.0
        for i in range(n):
            y += co[i] * (x[i] - y)
            x[i] = y
    return x


def hp(x: Sig, fc: float, poles: int = 1) -> Sig:
    """One-pole RC high-pass (cascaded); unlike x - lowpass(x) it keeps the top octave intact."""
    a = 1.0 / (1.0 + TAU * fc / SR)
    for _ in range(poles):
        out, y, prev = [0.0] * len(x), 0.0, 0.0
        for i, v in enumerate(x):
            y = a * (y + v - prev)
            prev = v
            out[i] = y
        x = out
    return x


def unit(x: Sig) -> tuple[float, ...]:
    pk = max(map(abs, x)) or 1.0
    return tuple(v / pk for v in x)


def bandpass(x: Sig, fc: float | Sig, q: float = 0.7) -> Sig:
    """Chamberlin state-variable band-pass."""
    fcs = fc if isinstance(fc, list) else [fc] * len(x)
    low = band = 0.0
    out = [0.0] * len(x)
    for i, (v, c) in enumerate(zip(x, fcs, strict=True)):
        f = 2 * math.sin(math.pi * min(c, SR / 6) / SR)
        low += f * band
        band += f * (v - low - q * band)
        out[i] = band
    return out


def env_adsr(n: int, a: float, d: float, s: float, r: float, gate: float) -> Sig:
    def level(t: float) -> float:
        if t < a:
            return t / a
        u = (t - a) / d
        return s + (1 - s) * (1 - u) ** 2 if u < 1 else s

    lg = level(gate)
    out = [0.0] * n
    for i in range(n):
        t = i / SR
        if t < gate:
            out[i] = level(t)
        else:
            u = (t - gate) / r
            out[i] = lg * (1 - u) ** 2 if u < 1 else 0.0
    return out


def env_exp(n: int, tau: float, attack: float = 0.002) -> Sig:
    ka, kr = attack * SR, min(n, round(0.005 * SR))
    env = [min(1.0, i / ka) * math.exp(-i / (tau * SR)) for i in range(n)]
    for i in range(kr):  # 5 ms raised-cosine release so a cut-off note never clicks
        env[n - 1 - i] *= 0.5 - 0.5 * math.cos(math.pi * i / kr)
    return env


def mul(x: Sig, e: Sig, g: float = 1.0) -> Sig:
    return [a * b * g for a, b in zip(x, e, strict=True)]


def mix(*parts: tuple[float, Sig]) -> Sig:
    n = max(len(p) for _, p in parts)
    out = [0.0] * n
    for g, p in parts:
        for i, v in enumerate(p):
            out[i] += v * g
    return out


def add(buf: Sig, sig: Sequence[float], t: float, g: float = 1.0) -> None:
    o = round(t * SR)
    if o + len(sig) > len(buf):  # grow (music buffers carry a tail; SFX get trimmed in finish)
        buf.extend([0.0] * (o + len(sig) - len(buf)))
    for i, v in enumerate(sig, o):
        buf[i] += v * g


def echo(x: Sig, delay: float, fb: float, wet: float) -> Sig:
    d = round(delay * SR)
    w = [0.0] * len(x)
    for i in range(d, len(x)):
        w[i] = (x[i - d] + w[i - d]) * fb
    return [a + b * wet for a, b in zip(x, w, strict=True)]


def reverb(x: Sig, room: float = 0.8, damp: float = 0.35) -> Sig:
    """Freeverb-style: 4 damped combs + 2 allpasses (wet only)."""
    n = len(x)
    out = [0.0] * n
    for d in (558, 638, 711, 779):
        buf, j, f = [0.0] * d, 0, 0.0
        for i in range(n):
            y = buf[j]
            f = y * (1 - damp) + f * damp
            buf[j] = x[i] + f * room
            out[i] += y
            j += 1
            if j == d:
                j = 0
    for d in (278, 170):
        buf, j = [0.0] * d, 0
        for i in range(n):
            b = buf[j]
            v = out[i]
            out[i] = b - v
            buf[j] = v + b * 0.5
            j += 1
            if j == d:
                j = 0
    return [v * 0.25 for v in out]


def finish(
    x: Sig, drive: float = 1.3, fade: float = 0.005, tail_fade: float | None = None, trim: bool = True
) -> Sig:
    """Trim -60 dB tail, DC removal, gentle tanh saturation, peak-normalise to -1.2 dBFS, edge fades."""
    if trim:
        floor = max(map(abs, x)) * 0.001
        end = max(i for i, v in enumerate(x) if abs(v) > floor) + 1
        x = x[: end + round(0.01 * SR)]
    m = sum(x) / len(x)
    x = [v - m for v in x]
    pk = max(map(abs, x)) or 1.0
    k = drive / pk
    x = [math.tanh(v * k) for v in x]
    m = sum(x) / len(x)
    x = [v - m for v in x]
    pk = max(map(abs, x)) or 1.0
    x = [v * PEAK / pk for v in x]
    if not fade and not tail_fade:
        return x  # loops: edges must stay untouched for a seamless wrap
    win = [1.0] * len(x)
    for length, rev in ((fade, False), (tail_fade if tail_fade is not None else fade, True)):
        n = max(1, round(length * SR))
        for i in range(min(n, len(x))):
            win[-1 - i if rev else i] *= 0.5 - 0.5 * math.cos(math.pi * i / n)
    x = [v * g for v, g in zip(x, win, strict=True)]
    m, wm = sum(x) / len(x), sum(win) / len(win)
    return [v - m * g / wm for v, g in zip(x, win, strict=True)]  # remove residual DC, edges stay at zero


# ---------------------------------------------------------------------------------------------
# Instruments (cached: every repeated note/hit is rendered once)
# ---------------------------------------------------------------------------------------------
@lru_cache(None)
def kick() -> tuple[float, ...]:
    n = round(0.42 * SR)
    f = [44 + 120 * math.exp(-i / (0.03 * SR)) for i in range(n)]
    body = mul(sine(f, n), env_exp(n, 0.17, 0.001))
    click = lp(noise(round(0.006 * SR), random.Random("kick")), 3000)
    sig = mix((1.0, body), (0.5, mul(click, env_exp(len(click), 0.002, 0.0005))))
    return unit([math.tanh(1.6 * v) for v in sig])


@lru_cache(None)
def snare(soft: bool = False) -> tuple[float, ...]:
    n = round(0.32 * SR)
    rng = random.Random("snare")
    nz = lp(hp(noise(n, rng), 1200, 2), 7500)
    nz = mul(nz, env_exp(n, 0.09 if soft else 0.07, 0.001))
    f = [185 + 70 * math.exp(-i / (0.01 * SR)) for i in range(n)]
    tone = mul(sine(f, n), env_exp(n, 0.05, 0.001))
    return unit(mix((1.4, nz), (0.55, tone)))


@lru_cache(None)
def clap() -> tuple[float, ...]:
    n = round(0.35 * SR)
    rng = random.Random("clap")
    nz = bandpass(noise(n, rng), 1400, 0.9)
    env = [0.0] * n
    for k, start in enumerate((0.0, 0.011, 0.022)):
        o = round(start * SR)
        for i in range(o, n):
            tau = 0.006 if k < 2 else 0.11
            env[i] = max(env[i], math.exp(-(i - o) / (tau * SR)))
    return unit(mul(nz, env))


@lru_cache(None)
def hat(open_: bool = False) -> tuple[float, ...]:
    n = round((0.38 if open_ else 0.07) * SR)
    rng = random.Random("hat")
    metal = mix(*[(0.18, pulse(f, n)) for f in (317.0, 457.0, 563.0, 743.0, 878.0, 1031.0)])
    sig = hp(mix((0.7, noise(n, rng)), (0.6, metal)), 5000, 2)
    return unit(mul(sig, env_exp(n, 0.13 if open_ else 0.018, 0.0008)))


@lru_cache(None)
def crash_cymbal() -> tuple[float, ...]:
    n = round(1.8 * SR)
    rng = random.Random("crash_cymbal")
    metal = mix(*[(0.15, pulse(f, n)) for f in (331.0, 497.0, 618.0, 811.0, 1093.0, 1430.0)])
    sig = hp(mix((0.9, noise(n, rng)), (0.5, metal)), 3500, 2)
    return unit(mul(sig, env_exp(n, 0.55, 0.001)))


@lru_cache(None)
def bass(m: int, dur: float) -> tuple[float, ...]:
    f = note_hz(m)
    n = round((dur + 0.06) * SR)
    x = mix((0.75, saw(f, n)), (0.6, sine(f, n)))
    lp(x, [150 + 1600 * math.exp(-i / (0.06 * SR)) for i in range(n)], 2)
    return tuple(mul(x, env_adsr(n, 0.003, 0.12, 0.7, 0.05, dur)))


@lru_cache(None)
def pluck(m: int, dur: float) -> tuple[float, ...]:
    f = note_hz(m)
    n = round((dur + 0.08) * SR)
    x = mix((0.5, pulse(f, n, 0.3)), (0.5, saw(f * 1.004, n, 0.5)))
    lp(x, [800 + 5200 * math.exp(-i / (0.05 * SR)) for i in range(n)], 2)
    env = env_adsr(n, 0.002, 0.22, 0.25, 0.07, dur)
    return tuple(mul(x, env))


@lru_cache(None)
def pad(chord: tuple[int, ...], dur: float) -> tuple[float, ...]:
    n = round((dur + 0.7) * SR)
    x = [0.0] * n
    for k, m in enumerate(chord):
        f = note_hz(m)
        for det, ph in ((0.9965, 0.13 * k), (1.0035, 0.57 + 0.21 * k)):
            for i, v in enumerate(saw(f * det, n, ph % 1)):
                x[i] += v
    lp(x, 1500, 2)
    return tuple(mul(x, env_adsr(n, 0.35, 0.4, 0.8, 0.65, dur), 1 / len(chord)))


def _vibrato(f: float, n: int, depth: float, rate: float = 5.5, delay: float = 0.18) -> Sig:
    return [f * (1 + depth * math.sin(TAU * rate * i / SR) * min(1.0, i / (delay * SR))) for i in range(n)]


@lru_cache(None)
def lead(m: int, dur: float) -> tuple[float, ...]:
    f = note_hz(m)
    n = round((dur + 0.14) * SR)
    fv = _vibrato(f, n, 0.006)
    x = mix((0.55, pulse(fv, n, 0.25)), (0.45, saw([v * 1.003 for v in fv], n)))
    lp(x, [2800 + 3000 * math.exp(-i / (0.08 * SR)) for i in range(n)], 2)
    return tuple(mul(x, env_adsr(n, 0.008, 0.15, 0.72, 0.12, dur)))


@lru_cache(None)
def soft_lead(m: int, dur: float) -> tuple[float, ...]:
    f = note_hz(m)
    n = round((dur + 0.35) * SR)
    fv = _vibrato(f, n, 0.005, 5.0, 0.3)
    x = mix((0.8, tri(fv, n)), (0.3, sine([v * 2 for v in fv], n)), (0.25, pulse(fv, n, 0.5)))
    lp(x, 2400, 2)
    return tuple(mul(x, env_adsr(n, 0.05, 0.3, 0.75, 0.32, dur)))


@lru_cache(None)
def brass(m: int, dur: float) -> tuple[float, ...]:
    f = note_hz(m)
    n = round((dur + 0.3) * SR)
    fv = _vibrato(f, n, 0.007, 5.5, 0.25)
    x = mix((0.5, saw(fv, n)), (0.5, saw([v * 1.005 for v in fv], n, 0.4)))
    lp(
        x,
        [
            600 + 2600 * min(1.0, i / (0.06 * SR)) * (0.75 + 0.25 * math.exp(-i / (0.3 * SR)))
            for i in range(n)
        ],
        2,
    )
    return tuple(mul(x, env_adsr(n, 0.02, 0.12, 0.8, 0.28, dur)))


@lru_cache(None)
def bell(m: int, tau: float = 0.35) -> tuple[float, ...]:
    f = note_hz(m)
    n = round(tau * 5 * SR)
    x = mix(
        (0.7, mul(sine(f, n), env_exp(n, tau, 0.001))),
        (0.3, mul(sine(f * 2.0, n), env_exp(n, tau * 0.5, 0.001))),
        (0.15, mul(sine(f * 3.01, n), env_exp(n, tau * 0.25, 0.001))),
    )
    return tuple(x)


# ---------------------------------------------------------------------------------------------
# Sound effects
# ---------------------------------------------------------------------------------------------
def blank(seconds: float) -> Sig:
    return [0.0] * round(seconds * SR)


def sfx_coin() -> Sig:
    out = blank(0.34)
    for t, m, d in ((0.0, 83, 0.065), (0.065, 88, 0.26)):
        f, n = note_hz(m), round(d * SR)
        x = mix((0.6, lp(pulse(f, n), 6000)), (0.35, sine(f * 2, n)))
        add(out, mul(x, env_exp(n, 0.035 if t == 0 else 0.09, 0.001)), t)
    return out


def sfx_crash() -> Sig:
    rng = random.Random("crash")
    n = round(1.4 * SR)
    thump = mul(sine([36 + 95 * math.exp(-i / (0.05 * SR)) for i in range(n)], n), env_exp(n, 0.2, 0.001))
    crunch = lp(noise(n, rng), [260 + 5200 * math.exp(-i / (0.12 * SR)) for i in range(n)], 2)
    crunch = mul(crunch, env_exp(n, 0.3, 0.001), 2.2)
    grains = blank(1.4)
    for _ in range(26):
        t = rng.uniform(0, 0.55) ** 1.4
        g = round(rng.uniform(0.004, 0.02) * SR)
        add(grains, mul(hp(noise(g, rng), 1500), env_exp(g, g / SR / 3, 0.0005)), t, rng.uniform(0.3, 1.0))
    partials = ((347, 0.5, 0.45), (563, 0.4, 0.35), (881, 0.35, 0.3), (1290, 0.25, 0.25), (1977, 0.18, 0.18))
    clang = mix(*[(a, mul(sine(f, n), env_exp(n, tau, 0.001))) for f, a, tau in partials])
    tinkle = blank(1.4)
    for _ in range(16):
        t, f = rng.uniform(0.05, 0.75), rng.uniform(2400, 5200)
        g = round(0.12 * SR)
        add(tinkle, mul(sine(f, g), env_exp(g, rng.uniform(0.02, 0.05), 0.0005)), t, rng.uniform(0.2, 0.5))
    return mix((0.75, thump), (1.15, crunch), (0.9, grains), (0.3, clang), (0.35, tinkle))


def sfx_near_miss() -> Sig:
    rng = random.Random("near_miss")
    n = round(0.42 * SR)
    shape = [math.sin(math.pi * min(1.0, i / n)) ** 1.5 for i in range(n)]
    fc = [400 + 2800 * s for s in shape]
    whoosh = mul(
        bandpass(noise(n, rng), fc, 0.5),
        [min(1.0, i / (0.12 * SR)) * math.exp(-i / (0.16 * SR)) for i in range(n)],
    )
    out = blank(0.7)
    add(out, whoosh, 0.0, 1.6)
    add(out, bell(88, 0.08), 0.1, 0.25)
    add(out, bell(95, 0.1), 0.16, 0.22)
    return out


def beep(m: float, gate: float, release: float) -> Sig:
    f = note_hz(m)
    n = round((gate + release + 0.01) * SR)
    x = mix((0.5, lp(pulse(f, n), 2600, 2)), (0.6, sine(f, n)))
    return mul(x, env_adsr(n, 0.004, 0.05, 0.6, release, gate))


def sfx_countdown() -> Sig:
    return beep(79, 0.12, 0.06)


def sfx_go() -> Sig:
    return mix((1.0, beep(91, 0.3, 0.18)), (0.6, beep(79, 0.3, 0.18)))


def sfx_shield_up() -> Sig:
    out = blank(0.75)
    for k, m in enumerate((72, 76, 79, 84, 88)):
        add(out, bell(m, 0.18), k * 0.045, 0.6)
        f = note_hz(m)
        n = round(0.2 * SR)
        add(out, mul(tri(f * 1.005, n), env_exp(n, 0.08, 0.004)), k * 0.045, 0.25)
    rng = random.Random("shield_up")
    n = round(0.35 * SR)
    sweep = bandpass(noise(n, rng), [800 + 5000 * i / n for i in range(n)], 0.4)
    add(out, mul(sweep, [math.sin(math.pi * i / n) for i in range(n)]), 0.0, 0.35)
    return out


def sfx_shield_break() -> Sig:
    rng = random.Random("shield_break")
    out = blank(0.65)
    n = round(0.3 * SR)
    add(out, mul(hp(noise(n, rng), 2500, 2), env_exp(n, 0.06, 0.001)), 0, 0.9)
    for _ in range(18):
        g = round(0.1 * SR)
        add(
            out,
            mul(sine(rng.uniform(2000, 6000), g), env_exp(g, rng.uniform(0.015, 0.05), 0.0005)),
            rng.uniform(0, 0.16) ** 1.3,
            0.3,
        )
    n = round(0.45 * SR)
    fall = lp(saw([1100 * math.exp(-i / (0.16 * SR)) + 140 for i in range(n)], n), 2500)
    add(out, mul(fall, env_exp(n, 0.12, 0.002)), 0.02, 0.4)
    return out


def blip(notes: Sequence[tuple[float, int, float]], shape: str = "pulse") -> Sig:
    out = blank(max(t + d for t, _, d in notes) + 0.03)
    for t, m, d in notes:
        f, n = note_hz(m), round(d * SR)
        x = lp(pulse(f, n, 0.25), 3500) if shape == "pulse" else mix((0.8, tri(f, n)), (0.3, sine(2 * f, n)))
        add(out, mul(x, env_exp(n, d / 3, 0.001)), t)
    return out


def sfx_ui_move() -> Sig:
    return blip([(0.0, 84, 0.06)], "tri")


def sfx_ui_select() -> Sig:
    return blip([(0.0, 84, 0.06), (0.06, 91, 0.12)])


def sfx_ui_back() -> Sig:
    return blip([(0.0, 79, 0.06), (0.06, 72, 0.12)], "tri")


def sfx_record() -> Sig:
    out = blank(1.5)
    for t, m, d in ((0.0, 72, 0.09), (0.1, 76, 0.09), (0.2, 79, 0.09)):
        add(out, brass(m, d), t, 0.8)
    for m, g in ((84, 0.8), (79, 0.45), (76, 0.45), (72, 0.45)):
        add(out, brass(m, 0.62), 0.3, g)
    for k, m in enumerate((96, 91, 100)):
        add(out, bell(m, 0.15), 0.32 + k * 0.08, 0.25)
    return out


def sfx_lane_change() -> Sig:
    rng = random.Random("lane_change")
    n = round(0.09 * SR)
    tick = mul(bandpass(noise(n, rng), 1800, 0.6), env_exp(n, 0.012, 0.001))
    thump = mul(sine([220 - 600 * i / SR for i in range(n)], n), env_exp(n, 0.02, 0.001))
    return mix((1.0, tick), (0.5, thump))


SFX: dict[str, Callable[[], Sig]] = {
    "coin": sfx_coin, "crash": sfx_crash, "near_miss": sfx_near_miss, "countdown": sfx_countdown,
    "go": sfx_go, "shield_up": sfx_shield_up, "shield_break": sfx_shield_break, "ui_move": sfx_ui_move,
    "ui_select": sfx_ui_select, "ui_back": sfx_ui_back, "record": sfx_record, "lane_change": sfx_lane_change,
}  # fmt: skip

# ---------------------------------------------------------------------------------------------
# Music
# ---------------------------------------------------------------------------------------------
TAIL_S = 3.0


def loop_frame(name: str) -> tuple[float, int, int]:
    bpm, bars = LOOPS[name]
    beat = 60 / bpm
    n = round(bars * 4 * beat * SR)
    return beat, n, n + round(TAIL_S * SR)


def fold(x: Sig, n: int) -> Sig:
    """Wrap everything that rings past the loop end back onto the start -> seamless loop."""
    for i in range(len(x) - n):
        x[i] += x[n + i]
    return x[:n]


def pump(n: int, beat: float, depth: float = 0.55, tau: float = 0.09) -> Sig:
    return [1 - depth * math.exp(-((i / SR) % beat) / tau) for i in range(n)]


def race_track() -> Sig:
    beat, n, total = loop_frame("race")
    bar = 4 * beat
    drums, low, pads, leads, arps, send = ([0.0] * total for _ in range(6))
    prog = [  # (bass root, pad chord)
        (45, (57, 60, 64)), (41, (53, 57, 60)), (36, (55, 60, 64)), (43, (55, 59, 62)),
        (45, (57, 60, 64)), (41, (53, 57, 60)), (38, (57, 62, 65)), (40, (56, 59, 64)),
    ]  # fmt: skip
    hook = [
        [(0, 0.75, 76), (0.75, 0.75, 74), (1.5, 0.5, 72), (2, 1.5, 69), (3.5, 0.5, 72)],
        [(0, 0.75, 77), (0.75, 0.75, 76), (1.5, 0.5, 72), (2, 2, 69)],
        [(0, 0.75, 79), (0.75, 0.75, 76), (1.5, 0.5, 72), (2, 1, 76), (3, 1, 74)],
        [(0, 0.75, 74), (0.75, 0.75, 71), (1.5, 0.5, 67), (2, 1.5, 71), (3.5, 0.5, 74)],
        [(0, 0.75, 76), (0.75, 0.75, 74), (1.5, 0.5, 72), (2, 1.5, 69), (3.5, 0.5, 72)],
        [(0, 0.75, 77), (0.75, 0.75, 79), (1.5, 0.5, 81), (2, 1.5, 84), (3.5, 0.5, 81)],
        [(0, 0.75, 77), (0.75, 0.75, 76), (1.5, 0.5, 74), (2, 1, 77), (3, 1, 76)],
        [(0, 1, 76), (1, 1, 80), (2, 1.5, 83), (3.5, 0.5, 80)],
    ]
    for b in range(16):
        t0 = b * bar
        root, chord = prog[b % 8]
        part_b = b >= 8
        for q in range(4):
            add(drums, kick(), t0 + q * beat, 1.0)
        for q in (1, 3):
            add(drums, snare(), t0 + q * beat, 0.8)
            add(send, snare(), t0 + q * beat, 0.25)
        for s in range(16):
            t = t0 + s * beat / 4
            if part_b and s % 4 == 2:
                add(drums, hat(True), t, 0.2)
            else:
                add(drums, hat(), t, (0.26, 0.12, 0.2, 0.12)[s % 4])
        for s in range(16):  # galloping 16th bass, octave on the 3rd sixteenth
            m = root + (12 if s % 4 == 2 else 0)
            add(low, bass(m, beat / 4 * 0.7), t0 + s * beat / 4, 0.5 if s % 4 == 0 else 0.4)
        add(pads, pad(chord, bar * 0.98), t0, 0.5)
        for st, d, m in hook[b % 8]:
            add(leads, lead(m, d * beat * 0.92), t0 + st * beat, 0.42)
            if part_b:
                add(leads, lead(m - 12, d * beat * 0.92), t0 + st * beat, 0.2)
        if part_b:
            seq = [chord[0] + 12, chord[1] + 12, chord[2] + 12, chord[0] + 24, chord[2] + 12, chord[1] + 12]
            for s in range(16):
                add(arps, pluck(seq[(b * 16 + s) % 6], beat / 4 * 0.6), t0 + s * beat / 4, 0.22)
    t0 = 15 * bar
    for k in range(8):  # snare fill back into bar 1
        add(drums, snare(), t0 + 2 * beat + k * beat / 4, 0.25 + 0.06 * k)
    for t in (0.0, 8 * bar):
        add(drums, crash_cymbal(), t, 0.35)
    leads = echo(leads, 0.75 * beat, 0.3, 0.3)
    arps = echo(arps, 0.75 * beat, 0.35, 0.35)
    wet = reverb([a + b * 0.25 + c * 0.2 for a, b, c in zip(send, leads, pads, strict=True)], 0.78, 0.4)
    pm = pump(total, beat)
    master = [
        d + (lo * 1.0 + p * 0.55) * g + le + a + w * 0.9
        for d, lo, p, le, a, w, g in zip(drums, low, pads, leads, arps, wet, pm, strict=True)
    ]
    return finish(fold(master, n), drive=1.5, fade=0.0, tail_fade=0.0, trim=False)


def menu_track() -> Sig:
    beat, n, total = loop_frame("menu")
    bar = 4 * beat
    drums, low, pads, leads, arps, send = ([0.0] * total for _ in range(6))
    prog = [(41, (53, 57, 60, 64)), (43, (55, 59, 62, 69)), (40, (52, 55, 59, 62)), (45, (57, 60, 64, 67))]
    melody = {
        4: [(0, 1.5, 72), (1.5, 0.5, 69), (2, 2, 67)],
        5: [(0, 1, 67), (1, 1, 69), (2, 1.5, 71), (3.5, 0.5, 74)],
        6: [(0, 3, 76), (3, 1, 74)],
        7: [(0, 2, 72), (2, 2, 69)],
        8: [(0, 1.5, 72), (1.5, 0.5, 74), (2, 2, 76)],
        9: [(0, 2, 79), (2, 1, 76), (3, 1, 74)],
        10: [(0, 1.5, 71), (1.5, 0.5, 72), (2, 2, 74)],
        11: [(0, 1, 76), (1, 1, 72), (2, 2, 69)],
    }
    for b in range(12):
        t0 = b * bar
        root, chord = prog[b % 4]
        for q in (0, 2.5):
            add(drums, kick(), t0 + q * beat, 0.75)
        for q in (1, 3):
            add(drums, clap(), t0 + q * beat, 0.4)
            add(send, clap(), t0 + q * beat, 0.6)
        for e in range(8):
            add(drums, hat(), t0 + e * beat / 2, 0.16 if e % 2 else 0.08)
        for st, d, dm in ((0, 1.4, 0), (1.5, 0.4, 0), (2, 1.4, 0), (3.5, 0.4, 12)):
            add(low, bass(root + dm, d * beat), t0 + st * beat, 0.42)
        add(pads, pad(chord, bar * 0.99), t0, 0.6)
        tones = [m + 12 for m in chord]
        seq = [tones[0], tones[1], tones[2], tones[3], tones[0] + 12, tones[3], tones[2], tones[1]]
        for s in range(16):
            add(arps, pluck(seq[s % 8], beat / 4 * 0.8), t0 + s * beat / 4, 0.2 if s % 4 else 0.26)
        for st, d, m in melody.get(b, []):
            add(leads, soft_lead(m, d * beat * 0.95), t0 + st * beat, 0.34)
    arps = echo(arps, 0.75 * beat, 0.4, 0.45)
    leads = echo(leads, 0.75 * beat, 0.3, 0.3)
    wet = reverb(
        [s + p * 0.3 + le * 0.4 + a * 0.3 for s, p, le, a in zip(send, pads, leads, arps, strict=True)],
        0.84,
        0.3,
    )
    pm = pump(total, 2 * beat, 0.3, 0.2)
    master = [
        d + (lo + p * 0.8) * g + le + a + w * 1.2
        for d, lo, p, le, a, w, g in zip(drums, low, pads, leads, arps, wet, pm, strict=True)
    ]
    return finish(fold(master, n), drive=1.2, fade=0.0, tail_fade=0.0, trim=False)


def win_track() -> Sig:
    beat = 0.4  # 150 BPM
    total = round(4.0 * SR)
    music, drums = blank(4.6), blank(4.6)
    for k, m in enumerate((72, 76, 79, 84, 88, 91)):
        add(music, brass(m, beat / 3 * 0.9), k * beat / 3, 0.5)
    stabs = [(2.0, (68, 72, 75, 80), 44), (2.67, (70, 74, 77, 82), 46)]
    for t, chord, root in stabs:
        for m in chord:
            add(music, brass(m, beat * 0.55), t * beat, 0.32)
        add(music, bass(root, beat * 0.55), t * beat, 0.6)
        add(drums, kick(), t * beat, 0.8)
    t_c = 3.33 * beat
    for m in (72, 76, 79, 84):
        add(music, brass(m, 1.75), t_c, 0.32)
    add(music, bass(36, 1.75), t_c, 0.6)
    add(music, bass(48, 1.75), t_c, 0.3)
    for k, m in enumerate((96, 100, 103, 108, 103, 108)):
        add(music, bell(m, 0.25), t_c + 0.15 + k * 0.11, 0.18)
    add(drums, kick(), t_c, 1.0)
    add(drums, crash_cymbal(), t_c, 0.5)
    for k in range(8):
        add(drums, snare(), k * beat / 4, 0.12 + 0.05 * k)
    wet = reverb([m * 0.4 + d * 0.3 for m, d in zip(music, drums, strict=True)], 0.8, 0.35)
    mixd = [m + d + w for m, d, w in zip(music, drums, wet, strict=True)][:total]
    return finish(mixd, drive=1.3, fade=0.005, tail_fade=0.25, trim=False)


MUSIC: dict[str, Callable[[], Sig]] = {"menu": menu_track, "race": race_track, "win": win_track}

# ---------------------------------------------------------------------------------------------
# Writing, validation, review sheets
# ---------------------------------------------------------------------------------------------


def write_wav(path: Path, x: Sig) -> None:
    a = array.array("h", (max(-32767, min(32767, round(v * 32767))) for v in x))
    if sys.byteorder == "big":
        a.byteswap()
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(a.tobytes())


def read_wav(path: Path) -> array.array:
    with wave.open(str(path), "rb") as w:
        params = (w.getnchannels(), w.getsampwidth(), w.getframerate())
        assert params == (1, 2, SR), f"{path.name}: {params} != mono/16-bit/{SR}"
        a = array.array("h", w.readframes(w.getnframes()))
    if sys.byteorder == "big":
        a.byteswap()
    return a


def validate() -> list[str]:
    report = []
    for name, (frames, fw, fh) in {**SPRITES, "icon": (1, 64, 64)}.items():
        path = ASSETS / ("icon.png" if name == "icon" else f"sprites/{name}.png")
        raw = path.read_bytes()
        assert raw[:8] == b"\x89PNG\r\n\x1a\n" and raw[24:26] == b"\x08\x06", (
            f"{path.name}: not 8-bit RGBA PNG"
        )
        img = pygame.image.load(str(path))
        assert img.get_size() == (frames * fw, fh), f"{path.name}: {img.get_size()} != {(frames * fw, fh)}"
        for f in range(frames):
            alphas = {img.get_at((f * fw + x, y))[3] for y in range(fh) for x in range(fw)}
            if name in OPAQUE:
                assert alphas == {255}, f"{path.name}: must be fully opaque"
            else:
                assert 0 in alphas and 255 in alphas, (
                    f"{path.name} frame {f}: needs transparency + opaque pixels"
                )
        report.append(f"{path.relative_to(ASSETS)} {img.get_width()}x{img.get_height()} ok")
    for name in (*SOUNDS, *MUSIC):
        path = ASSETS / ("sounds" if name in SOUNDS else "music") / f"{name}.wav"
        a = read_wav(path)
        peak = max(map(abs, a)) / 32768
        mean = sum(a) / len(a) / 32768
        assert peak <= LIMIT, f"{path.name}: peak {20 * math.log10(peak):.2f} dBFS > -1"
        assert abs(mean) < 0.002, f"{path.name}: DC offset {mean:.4f}"
        info = f"{path.relative_to(ASSETS)} {len(a) / SR:.2f}s peak {20 * math.log10(peak):.2f} dBFS"
        info += f" dc {mean:+.5f}"
        if name in LOOPS:
            _, n, _ = loop_frame(name)
            assert len(a) == n, f"{path.name}: {len(a)} samples is not whole bars ({n})"
            assert 24 <= len(a) / SR <= 32, f"{path.name}: loop length {len(a) / SR:.1f}s"
            # the wrap step must look like its neighbours (steps within 32 samples either side)
            local = max(abs(a[i + 1] - a[i]) for i in (*range(32), *range(len(a) - 33, len(a) - 1)))
            seam = abs(a[0] - a[-1])
            assert seam <= 1.5 * local + 64, f"{path.name}: loop seam jump {seam} vs local steps {local}"
            info += f" seam step {seam} (local max {local})"
        else:
            assert abs(a[0]) < 200 and abs(a[-1]) < 200, f"{path.name}: edges not faded"
        report.append(info)
    return report


def contact_sheet(sprites: dict[str, Surf], path: Path) -> None:
    font = pygame.font.Font(None, 20)
    order = [*SPRITES, "icon"]
    dims = {**SPRITES, "icon": (1, 64, 64)}

    def framed(name: str) -> Surf:
        frames, fw, fh = dims[name]
        img = sprites[name]
        out = new(frames * (fw * 3 + 6) - 6, fh * 3)
        for f in range(frames):
            sub = pygame.transform.scale_by(img.subsurface((f * fw, 0, fw, fh)), 3)
            out.blit(sub, (f * (fw * 3 + 6), 0))
        return out

    def panel(bg: Color, fg: Color, width: int) -> Surf:
        x = y = 12
        rowh, items = 0, []
        for name in order:
            img = framed(name)
            frames, fw, fh = dims[name]
            label = font.render(f"{name}  {frames}x{fw}x{fh}", True, fg)
            iw, ih = max(img.get_width(), label.get_width()), img.get_height() + 18
            if x + iw > width - 12:
                x, y, rowh = 12, y + rowh + 14, 0
            items.append((img, label, x, y))
            x += iw + 22
            rowh = max(rowh, ih)
        surf = pygame.Surface((width, y + rowh + 12))
        surf.fill(bg)
        for img, label, ix, iy in items:
            surf.blit(label, (ix, iy))
            surf.blit(img, (ix, iy + 16))
        return surf

    dark = panel((22, 24, 34), (200, 204, 220), 1060)
    grass = panel((74, 124, 58), (240, 250, 230), 1060)
    mock = scene_mock(sprites, dark.get_height() + grass.get_height())
    sheet = pygame.Surface((1060 + mock.get_width(), dark.get_height() + grass.get_height()))
    sheet.blit(dark, (0, 0))
    sheet.blit(grass, (0, dark.get_height()))
    sheet.blit(mock, (1060, 0))
    pygame.image.save(sheet, str(path))


def scene_mock(sprites: dict[str, Surf], height: int) -> Surf:
    """In-context preview: road (x3) with verges, lane dashes, traffic, obstacles and props."""
    rng = random.Random("mock")
    w = 640
    s = pygame.Surface((w, height))
    s.fill((76, 128, 60))
    for _ in range(260):
        c = rng.choice([(70, 120, 56), (84, 138, 64), (66, 112, 52)])
        s.fill(c, (rng.randrange(w), rng.randrange(height), 6, 3))

    def fr(name: str, i: int = 0) -> Surf:
        _, fw, fh = {**SPRITES, "icon": (1, 64, 64)}[name]
        return pygame.transform.scale_by(sprites[name].subsurface((i * fw, 0, fw, fh)), 3)

    road_x = 80
    s.fill((96, 98, 108), (road_x - 16, 0, 16, height))
    s.fill((96, 98, 108), (road_x + 480, 0, 16, height))
    tile = fr("road_tile")
    for y in range(0, height, tile.get_height()):
        s.blit(tile, (road_x, y))
    s.fill((236, 236, 230), (road_x + 2, 0, 6, height))
    s.fill((236, 236, 230), (road_x + 472, 0, 6, height))
    for k in range(1, 5):
        for y in range(-20, height, 96):
            s.fill((236, 236, 230), (road_x + 96 * k - 3, y, 6, 48))

    def at(img: Surf, cx: float, cy: float) -> None:
        s.blit(img, (round(cx - img.get_width() / 2), round(cy - img.get_height() / 2)))

    lane = [road_x + 48 + 96 * i for i in range(5)]
    for k, y in enumerate(range(40, height, 150)):
        at(fr("tree", k % 2), 28, y)
        at(fr("tree", (k + 1) % 2), w - 30, y + 70)
        at(fr("bush", k % 2), 30, y + 80)
        at(fr("flowers", k % 3), 18, y + 115)
        at(fr("flowers", (k + 1) % 3), w - 20, y + 10)
        at(fr("rock_small"), w - 40, y + 125)
    for y in range(120, height, 400):
        at(fr("lamp"), road_x - 34, y)
        at(fr("lamp"), road_x + 480 + 34, y + 200)
    at(fr("truck"), lane[0], 160)
    at(fr("van"), lane[3], 300)
    at(fr("blinker"), lane[3] - 33, 300 + 66)
    at(fr("car_black"), lane[4], 120)
    at(fr("car_white"), lane[1], 560)
    at(fr("trunk", 1), lane[2], 90)
    at(fr("stone"), lane[1], 330)
    at(fr("pothole"), lane[4], 480)
    at(fr("cone"), lane[2], 420)
    at(fr("cone"), lane[3], 640)
    for k in range(5):
        at(fr("coin", k * 2 % 8), lane[2], 700 + k * 48)
    at(fr("shield", 2), lane[4], 760)
    at(fr("car_red"), lane[0], 820)
    at(fr("car_blue"), lane[4], 980)
    at(fr("car_pink"), lane[3], 1010)
    at(fr("car_yellow"), lane[2], min(height - 80, 1080))
    return s


def waveform_sheet(path: Path) -> None:
    font = pygame.font.Font(None, 20)
    names = [*SOUNDS, *MUSIC]
    bw, bh, cols = 760, 84, 2
    rows = (len(names) + 1) // cols
    sheet = pygame.Surface((cols * bw + 30, rows * (bh + 26) + 12))
    sheet.fill((18, 20, 28))
    for k, name in enumerate(names):
        path_wav = ASSETS / ("sounds" if name in SOUNDS else "music") / f"{name}.wav"
        a = read_wav(path_wav)
        x0, y0 = 10 + (k % cols) * (bw + 10), 8 + (k // cols) * (bh + 26)
        pk = max(map(abs, a)) / 32768
        rms = math.sqrt(sum(v * v for v in a) / len(a)) / 32768
        label = f"{name}  {len(a) / SR:.2f}s  peak {20 * math.log10(pk):.1f} dBFS"
        label += f"  rms {20 * math.log10(rms):.1f} dBFS"
        sheet.blit(font.render(label, True, (210, 214, 230)), (x0, y0))
        box = pygame.Rect(x0, y0 + 18, bw, bh)
        pygame.draw.rect(sheet, (30, 34, 46), box)
        mid = box.centery
        lim = LIMIT * bh / 2
        for yy in (mid - lim, mid + lim):
            pygame.draw.line(sheet, (120, 50, 50), (box.left, yy), (box.right, yy))
        step = len(a) / bw
        for x in range(bw):
            seg = a[int(x * step) : max(int(x * step) + 1, int((x + 1) * step))]
            lo, hi = min(seg) / 32768, max(seg) / 32768
            pygame.draw.line(
                sheet, (90, 200, 230), (box.left + x, mid - hi * bh / 2), (box.left + x, mid - lo * bh / 2)
            )
    pygame.image.save(sheet, str(path))


def main() -> None:
    t_start = time.perf_counter()
    pygame.init()
    (ASSETS / "sprites").mkdir(parents=True, exist_ok=True)
    sprites = build_sprites()
    for name, img in sprites.items():
        pygame.image.save(img, str(ASSETS / ("icon.png" if name == "icon" else f"sprites/{name}.png")))
    t_art = time.perf_counter()
    for name, fn in SFX.items():
        write_wav(ASSETS / "sounds" / f"{name}.wav", finish(fn()))
    t_sfx = time.perf_counter()
    for name, fn in MUSIC.items():
        write_wav(ASSETS / "music" / f"{name}.wav", fn())
    t_music = time.perf_counter()
    report = validate()
    contact_sheet(sprites, TOOLS / "contact_sheet.png")
    waveform_sheet(TOOLS / "audio_waveforms.png")
    print("\n".join(report))
    print(
        f"art {t_art - t_start:.1f}s, sfx {t_sfx - t_art:.1f}s, music {t_music - t_sfx:.1f}s, "
        f"total {time.perf_counter() - t_start:.1f}s"
    )


if __name__ == "__main__":
    main()
