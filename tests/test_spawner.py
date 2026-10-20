"""Spawner fairness: an independent checker proves a surviving path exists through 10k rows per mode."""

import bisect
import heapq
import math
import random

import pytest

from jogo_de_carro.settings import (
    LANE_CHANGE_TIME,
    LANES,
    MODES,
    PLAYER_HITBOX,
    PLAYER_Y,
    START_LANE,
    Item,
    Kind,
    kind_size,
)
from jogo_de_carro.world.difficulty import speed_at, versus_rows
from jogo_de_carro.world.spawner import EXIT_Y, LOOKAHEAD, ItemPlacement, Placement, Spawner

ROWS = 10_000
HALF_LEN = PLAYER_HITBOX[1] / 2


def _run(mode, seed, shared=False):
    if shared:  # as World(shared_road=True) builds it: rows spaced out, and no pull towards the player
        mode = versus_rows(mode)
    spawner = Spawner(mode, random.Random(seed))
    distance = t = 0.0
    obstacles: list[tuple[Placement, float, float]] = []
    items: list[ItemPlacement] = []
    samples: list[tuple[float, float]] = []
    rows: list[float] = []
    while spawner.rows < ROWS:
        v = speed_at(mode, t)
        distance += 40.0
        t += 40.0 / v
        samples.append((distance, v))
        before = spawner.rows
        player_lane = None if shared else spawner.corridor_lane(distance)  # exercises the player bias
        for p in spawner.update(distance, t, v, player_lane):
            assert p.g > distance + LOOKAHEAD - 40.0, "everything appears above the top of the screen"
            if isinstance(p, Placement):
                obstacles.append((p, distance, v))
            else:
                items.append(p)
        if spawner.rows != before:
            rows.append(spawner.prev_g)
    return obstacles, items, samples, rows


def _blocked_by_lane(obstacles) -> list[list[tuple[float, float]]]:
    """Player-centre track positions where the player's hitbox could overlap each obstacle."""
    lanes: list[list[tuple[float, float]]] = [[] for _ in range(LANES)]
    for p, distance, v in obstacles:
        h = kind_size(p.kind)[1]
        lo, hi = p.g - h / 2 - HALF_LEN, p.g + h / 2 + HALF_LEN
        if p.own_speed:
            spawn_y = PLAYER_Y - (p.g - distance)
            hi += p.own_speed / (v - p.own_speed) * max(0.0, EXIT_Y - spawn_y)
        for lane in {p.lane, p.to_lane} - {None}:
            lanes[lane].append((lo, hi))
    merged = []
    for intervals in lanes:
        out: list[list[float]] = []
        for lo, hi in sorted(intervals):
            if out and lo <= out[-1][1]:
                out[-1][1] = max(out[-1][1], hi)
            else:
                out.append([lo, hi])
        merged.append([(a, b) for a, b in out])
    return merged


def _free_intervals(blocked, end):
    free = []
    for intervals in blocked:
        lane, cursor = [], -math.inf
        for lo, hi in intervals:
            if lo > cursor:
                lane.append((cursor, lo))
            cursor = max(cursor, hi)
        lane.append((cursor, end))
        free.append(lane)
    return free


def _survivable_until(free, hop_len, end) -> float:
    """Earliest-arrival search over (lane, free interval); returns how far a perfect driver gets."""
    starts = [[iv[0] for iv in lane] for lane in free]
    first = bisect.bisect_right(starts[START_LANE], 0.0) - 1
    best: dict[tuple[int, int], float] = {(START_LANE, first): 0.0}
    heap = [(0.0, START_LANE, first)]
    reach = 0.0
    while heap:
        e, lane, i = heapq.heappop(heap)
        if e > best[(lane, i)]:
            continue
        a_end = free[lane][i][1]
        reach = max(reach, a_end)
        if reach >= end:
            return reach
        for other in (lane - 1, lane + 1):
            if not 0 <= other < LANES:
                continue
            j = max(0, bisect.bisect_right(starts[other], e) - 1)
            while j < len(free[other]) and free[other][j][0] < a_end:
                b_start, b_end = free[other][j]
                p = max(e, b_start)
                arrive = p + hop_len(p)
                if arrive <= min(a_end, b_end) and arrive < best.get((other, j), math.inf):
                    best[(other, j)] = arrive
                    heapq.heappush(heap, (arrive, other, j))
                j += 1
    return reach


@pytest.mark.parametrize("shared", [False, True], ids=["solo", "shared"])
@pytest.mark.parametrize("mode", MODES, ids=lambda m: m.key)
def test_every_row_is_survivable(mode, shared):
    obstacles, items, samples, rows = _run(mode, seed=1234, shared=shared)
    blocked = _blocked_by_lane(obstacles)

    # never all lanes blocked at a row centre
    starts = [[lo for lo, _ in lane] for lane in blocked]

    def is_blocked(lane: int, g: float) -> bool:
        k = bisect.bisect_left(starts[lane], g) - 1
        return k >= 0 and blocked[lane][k][1] > g

    for g in rows:
        assert not all(is_blocked(lane, g) for lane in range(LANES)), f"row at {g:.0f} blocks every lane"

    # a perfect driver (lane change takes LANE_CHANGE_TIME at the speed it is made) survives every row
    sample_d = [d for d, _ in samples]

    def hop_len(p: float) -> float:
        k = min(bisect.bisect_left(sample_d, p), len(samples) - 1)
        return LANE_CHANGE_TIME * samples[k][1]

    end = rows[-1] - 1000
    reach = _survivable_until(_free_intervals(blocked, end + 1), hop_len, end)
    assert reach >= end, f"{mode.name}: no surviving path past track position {reach:.0f} of {end:.0f}"

    # the rows are not trivially empty, and coins never sit on an obstacle
    assert len(obstacles) > ROWS
    kinds = {p.kind for p, _, _ in obstacles}
    assert {Kind.CAR, Kind.STONE, Kind.POTHOLE, Kind.CONE} <= kinds
    assert any(i.item is Item.SHIELD for i in items)


@pytest.mark.parametrize("mode", MODES, ids=lambda m: m.key)
def test_rows_use_the_difficulty_cap(mode):
    obstacles, *_ = _run(mode, seed=99)
    per_row: dict[float, int] = {}
    for p, _, _ in obstacles:
        per_row[p.g] = per_row.get(p.g, 0) + (1 if p.to_lane is None else 2)
    assert max(per_row.values()) <= LANES - 1
    cap = mode.late_blocked[1] if mode.late_blocked else mode.max_blocked
    assert max(per_row.values()) == cap
