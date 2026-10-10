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

SKINS = ("yellow", "black", "blue", "pink", "red", "white")
# name -> (frames, frame_w, frame_h). Everything is transparent except the road tile.
SPRITES: dict[str, tuple[int, int, int]] = {
    **{f"car_{c}": (2, 24, 40) for c in SKINS},
    "truck": (2, 28, 64),
    "van": (2, 26, 48),
    "stone": (1, 24, 22),
    "pothole": (1, 30, 20),
    "trunk": (4, 44, 18),
    "cone": (1, 14, 16),
    "coin": (8, 12, 12),
    "shield": (4, 16, 16),
    "tree": (2, 32, 32),
    "bush": (2, 16, 12),
    "lamp": (1, 10, 28),
    "rock_small": (1, 10, 8),
    "flowers": (3, 8, 6),
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


CAR_DESIGNS: dict[str, tuple[str, Callable[[Surf, dict], None] | None, Sequence[Color]]] = {
    "yellow": ("sport", deco_sport, GLASS),
    "black": ("sedan", deco_stripes, GLASS),
    "blue": ("sedan", deco_police, GLASS),
    "pink": ("sport", deco_convertible, GLASS_CYAN),
    "red": ("jeep", deco_jeep, GLASS),
    "white": ("ambulance", deco_ambulance, GLASS),
}


def car_sheet(skin: str) -> Surf:
    style, deco, glass = CAR_DESIGNS[skin]
    return strip([vehicle(24, 40, (1, 38), STYLES[style], CAR_RAMPS[skin], f, deco, glass) for f in (0, 1)])


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


def bush(variant: int) -> Surf:
    balls = [(5.2, 7.0, 4.2, 3.6, 0), (10.8, 6.8, 4.2, 3.8, 0.4), (8.0, 4.6, 3.6, 3.2, 1.6)]
    s = blob(16, 12, balls, LEAF, f"bush{variant}", jitter=0.1, speckle=0.06, edge=LEAF_OUT)
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

    for y in range(16):
        for x in range(16):
            if not inside(x, y):
                continue
            i = 3 if x < 8 else 2
            if not inside(x - 1, y) or not inside(x, y - 1):
                i = 4
            elif not inside(x + 1, y) or not inside(x, y + 1):
                i = 1
            s.set_at((x, y), CYAN[i])
    for y in range(5, 11):
        for x in range(5, 11):
            if 7 <= x <= 8 or 7 <= y <= 8:
                s.set_at((x, y), CYAN[4] if x < 8 or y < 8 else (196, 246, 255))
    outline(s)
    alpha = (60, 110, 160, 110)[frame]  # pulsing glow, two rings fading outward
    body = {(x, y) for y in range(16) for x in range(16) if s.get_at((x, y))[3] == 255}

    def grow(src: set[tuple[int, int]]) -> set[tuple[int, int]]:
        return {
            (x + dx, y + dy) for x, y in src for dx, dy in N4 if 0 <= x + dx < 16 and 0 <= y + dy < 16
        } - src

    ring1 = grow(body)
    for p in ring1:
        s.set_at(p, (110, 236, 255, alpha))
    for p in grow(body | ring1):
        s.set_at(p, (110, 236, 255, alpha // 3))
    if frame == 2:
        for x, y in ((12, 2), (12, 1), (12, 3), (11, 2), (13, 2)):
            s.set_at((x, y), (255, 255, 255, 255 if (x, y) == (12, 2) else 200))
    return s


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
    out = {f"car_{c}": car_sheet(c) for c in SKINS}
    out |= {
        "truck": truck_sheet(),
        "van": van_sheet(),
        "stone": stone(),
        "pothole": pothole(),
        "trunk": strip([trunk(f) for f in range(4)]),
        "cone": cone(),
        "coin": strip([coin(f) for f in range(8)]),
        "shield": strip([shield(f) for f in range(4)]),
        "tree": strip([tree_round("tree0"), tree_palm("palm")]),
        "bush": strip([bush(0), bush(1)]),
        "lamp": lamp(),
        "rock_small": rock_small(),
        "flowers": strip([flowers(i) for i in range(3)]),
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
