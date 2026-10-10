"""Obstacle rows that are always survivable.

Every object gets a *track position* ``g``: the distance the player will have driven when the object's
centre reaches the player's reference line (``PLAYER_Y``). Static objects keep their ``g``; traffic drives
forward, so its ``g`` grows while it is on screen. Blocking is tracked per lane as intervals of
player-centre track positions where the player's hitbox could touch the object (conservatively padded).

Each row keeps a *safe corridor*: one free lane plus a lane-change window between consecutive rows, sized
for ``LANE_CHANGE_TIME`` (+ reaction slack) at the speed the player will have when getting there. Obstacles
are never placed on the corridor, so a surviving path always exists. Staying in the previous safe lane is
always a valid choice (nothing that started earlier can block it later), so planning never gets stuck.
The corridor prefers to stay near the player's lane, so a lane that looks free is rarely a dead end.

Rows are planned one row ahead and every placement is held back until it reaches ``SPAWN_Y``, so the coins
in a lane-change window (which lies before its row) appear off screen too.
"""

import math
import random
from dataclasses import dataclass, field

from ..settings import (
    LANE_CENTERS,
    LANE_CHANGE_TIME,
    LANES,
    MAX_LANE_SHIFT,
    PLAYER_HITBOX,
    PLAYER_Y,
    REACTION_TIME,
    SPAWN_Y,
    START_LANE,
    Difficulty,
    Item,
    Kind,
    kind_size,
)
from ..tween import clamp
from .difficulty import max_blocked_at, row_gap, speed_at, unlocked_kinds

LOOKAHEAD = PLAYER_Y - SPAWN_Y  # placements are released when they would appear at SPAWN_Y
EXIT_Y = 720 + 140  # screen y after which nothing can touch the player any more
PAD = PLAYER_HITBOX[1] / 2 + 6  # player half-length + safety margin
BAND = max(kind_size(k)[1] for k in Kind) / 2 + PAD  # safe-lane reservation around a row centre
FIRST_ROW = LOOKAHEAD + 500.0
SPEED_LOOKAHEAD_S = 3.0  # rows are reached a few seconds after they are planned

KIND_WEIGHT = {
    Kind.CAR: 4.0,
    Kind.VAN: 2.0,
    Kind.TRUCK: 1.4,
    Kind.STONE: 3.0,
    Kind.POTHOLE: 2.2,
    Kind.CONE: 2.2,
    Kind.TRUNK: 3.5,  # it needs two free lanes, so most draws fail
}
# traffic drives forward at this fraction of the world speed at spawn time; faster cars linger on screen
TRAFFIC_SPEED = {Kind.CAR: (0.1, 0.25), Kind.VAN: (0.08, 0.2), Kind.TRUCK: (0.05, 0.15)}
SWERVE_Y = (60.0, 300.0)  # screen y where a signalling car moves over: well ahead of the player
BLINK_RANGE = (0.45, 0.8)  # seconds of blinker before the move
SHIFT_WEIGHT = (1.0, 1.7, 0.6)  # preference for keeping / moving the safe lane by 1 / 2 lanes
COIN_CHANCE = 0.3
SHIELD_CHANCE = 0.04
SHIELD_COOLDOWN = 25.0

Interval = tuple[float, float]


@dataclass(frozen=True)
class Placement:
    kind: Kind
    lane: int
    g: float
    to_lane: int | None = None  # trunk: lane it rolls into; traffic: lane it will change into
    own_speed: float = 0.0  # traffic forward speed in px/s
    turn_y: float = 0.0  # traffic: screen y where the blinker starts
    blink: float = 0.0  # traffic: seconds of blinker before it moves over
    variant: int = 0  # car skin index


@dataclass(frozen=True)
class ItemPlacement:
    item: Item
    x: float
    g: float


@dataclass(frozen=True)
class Segment:
    """A piece of the safe corridor: drive in ``lane`` (moving to ``to_lane``) for start <= p < end."""

    start: float
    end: float
    lane: int
    to_lane: int


def traffic_drift(own_speed: float, speed: float, spawn_y: float) -> float:
    """Upper bound of how far (in track px) traffic moves forward while it is still on screen."""
    if own_speed <= 0:
        return 0.0
    if speed <= own_speed:
        return math.inf
    return own_speed / (speed - own_speed) * max(0.0, EXIT_Y - spawn_y)


def _overlaps(intervals: list[Interval], a: float, b: float) -> bool:
    return any(lo < b and a < hi for lo, hi in intervals)


@dataclass
class Spawner:
    mode: Difficulty
    rng: random.Random
    enabled: bool = True
    safe_lane: int = START_LANE
    next_g: float = FIRST_ROW
    prev_g: float = FIRST_ROW - 600.0
    reserved_until: float = 0.0
    next_shield_t: float = 15.0
    blocked: list[list[Interval]] = field(default_factory=lambda: [[] for _ in range(LANES)])
    reserved: list[list[Interval]] = field(default_factory=lambda: [[] for _ in range(LANES)])
    corridor: list[Segment] = field(default_factory=list)
    pending: list[Placement | ItemPlacement] = field(default_factory=list)
    player_lane: int | None = None
    rows: int = 0

    def update(
        self, distance: float, t: float, speed: float, player_lane: int | None = None
    ) -> list[Placement | ItemPlacement]:
        """Plan rows ahead and return the placements that reached the top of the screen."""
        self.player_lane = player_lane
        speed = max(speed, speed_at(self.mode, t))  # the world may still be pulling away from the start
        spawn = distance + LOOKAHEAD
        while self.enabled and self.prev_g <= spawn:  # plan a row while the previous one is still unseen
            self.pending += self._plan_row(self.next_g, t, speed)
            self.rows += 1
            self.prev_g = self.next_g
            self.next_g += row_gap(self.mode, t, speed)
        if not self.enabled:
            self.pending.clear()
        out = [p for p in self.pending if p.g <= spawn]
        self.pending = [p for p in self.pending if p.g > spawn]
        self._prune(distance - 400.0)
        return out

    def corridor_lane(self, p: float) -> int:
        """Lane the safe corridor wants the player in at track position p (used by the autopilot)."""
        for seg in reversed(self.corridor):  # later segments win: a lane-change window may start early
            if seg.start <= p < seg.end:
                return seg.to_lane
        return self.safe_lane if self.corridor and p >= self.corridor[-1].end else START_LANE

    # --- planning ----------------------------------------------------------------------------------------

    def _plan_row(self, g: float, t: float, speed: float) -> list[Placement | ItemPlacement]:
        v = max(speed, speed_at(self.mode, t + SPEED_LOOKAHEAD_S)) * 1.05
        mid = (self.prev_g + g) / 2
        options: list[tuple[int, list[tuple[int, float, float]], float]] = []
        for lane in range(LANES):
            shift = abs(lane - self.safe_lane)
            if shift > MAX_LANE_SHIFT:
                continue
            if shift == 0:
                spans = [(lane, self.reserved_until, g + BAND)]
            else:
                half = (shift * LANE_CHANGE_TIME + REACTION_TIME) * v / 2
                w0, w1 = mid - half, mid + half
                lo, hi = sorted((lane, self.safe_lane))
                spans = [(self.safe_lane, self.reserved_until, w0)]
                spans += [(path, w0, w1) for path in range(lo, hi + 1)]
                spans.append((lane, w1, g + BAND))
            if all(b <= a or not _overlaps(self.blocked[ln], a, b) for ln, a, b in spans):
                options.append((lane, spans, SHIFT_WEIGHT[shift] * self._near_player(lane)))
        if not options:  # cannot happen (see module docstring); an empty row is always fair anyway
            return []
        new_lane, spans, _ = self.rng.choices(options, weights=[o[2] for o in options])[0]
        for ln, a, b in spans:
            if b > a:
                self.reserved[ln].append((a, b))
        self._extend_corridor(spans, new_lane)
        self.safe_lane, self.reserved_until = new_lane, g + BAND

        out: list[Placement | ItemPlacement] = self._place_obstacles(g, t, speed, new_lane)
        out += self._place_items(g, t, spans, new_lane)
        return out

    def _near_player(self, lane: int) -> float:
        """Weight that keeps the corridor near the player: their lane, then its neighbours."""
        if self.player_lane is None:
            return 1.0
        d = abs(lane - self.player_lane)
        return self.mode.path_bias if d == 0 else math.sqrt(self.mode.path_bias) if d == 1 else 1.0

    def _extend_corridor(self, spans: list[tuple[int, float, float]], new_lane: int) -> None:
        first_lane, a, b = spans[0]
        if b > a:
            self.corridor.append(Segment(a, b, first_lane, first_lane))
        if len(spans) > 1:  # lane change window
            w0, w1 = spans[1][1], spans[1][2]
            self.corridor.append(Segment(w0, w1, first_lane, new_lane))
            self.corridor.append(Segment(w1, spans[-1][2], new_lane, new_lane))

    def _place_obstacles(
        self, g: float, t: float, speed: float, safe: int
    ) -> list[Placement | ItemPlacement]:
        kinds = unlocked_kinds(self.mode, t)
        cap = max_blocked_at(self.mode, t)
        target = self.rng.randint((cap + 1) // 2, cap)
        lanes = [ln for ln in range(LANES) if ln != safe]
        self.rng.shuffle(lanes)
        out: list[Placement | ItemPlacement] = []
        used = 0
        for lane in lanes:
            if used >= target:
                break
            placement = self._fit(lane, g, speed, kinds, allow_wide=used + 2 <= target)
            if placement:
                out.append(placement)
                used += 1 if placement.to_lane is None else 2
        return out

    def _fit(
        self, lane: int, g: float, speed: float, kinds: list[Kind], allow_wide: bool
    ) -> Placement | None:
        rng = self.rng
        pool = list(kinds)
        while pool:
            kind = rng.choices(pool, weights=[KIND_WEIGHT[k] for k in pool])[0]
            pool.remove(kind)
            h = kind_size(kind)[1]
            lo, hi = g - h / 2 - PAD, g + h / 2 + PAD
            neighbours = [n for n in (lane - 1, lane + 1) if 0 <= n < LANES]
            own_speed, turn_y, blink, to_lane = 0.0, 0.0, 0.0, None
            if kind.is_traffic:
                own_speed = rng.uniform(*TRAFFIC_SPEED[kind]) * speed
                hi += traffic_drift(own_speed, speed, SPAWN_Y)
                if allow_wide and rng.random() < self.mode.traffic_lane_change:
                    # both lanes stay blocked for the whole interval; the timing is only for the show
                    to_lane, move_y = rng.choice(neighbours), rng.uniform(*SWERVE_Y)
                    closing = speed - own_speed
                    blink = clamp((move_y + 60.0) / closing, *BLINK_RANGE)
                    turn_y = move_y - blink * closing
            elif kind is Kind.TRUNK:
                if not allow_wide:
                    continue
                to_lane = rng.choice(neighbours)
            if to_lane is not None and not self._can_block(to_lane, lo, hi):
                if kind is Kind.TRUNK:
                    continue
                to_lane = None  # traffic just stays in its lane
            if not self._can_block(lane, lo, hi):
                continue
            for ln in (lane,) if to_lane is None else (lane, to_lane):
                self.blocked[ln].append((lo, hi))
            variant = rng.randrange(6) if kind is Kind.CAR else 0
            return Placement(kind, lane, g, to_lane, own_speed, turn_y, blink, variant)
        return None

    def _can_block(self, lane: int, lo: float, hi: float) -> bool:
        return not _overlaps(self.reserved[lane], lo, hi) and not _overlaps(self.blocked[lane], lo, hi)

    def _place_items(
        self, g: float, t: float, spans: list[tuple[int, float, float]], lane: int
    ) -> list[Placement | ItemPlacement]:
        rng = self.rng
        if t >= self.next_shield_t and rng.random() < SHIELD_CHANCE:
            self.next_shield_t = t + SHIELD_COOLDOWN
            return [ItemPlacement(Item.SHIELD, LANE_CENTERS[lane], g)]
        if rng.random() >= COIN_CHANCE:
            return []
        if len(spans) == 1:  # straight line in the safe lane
            return [ItemPlacement(Item.COIN, LANE_CENTERS[lane], g + dy) for dy in (-120, -40, 40, 120)]
        # an arc that follows the lane change
        start_lane, w0, w1 = spans[0][0], spans[1][1], spans[1][2]
        x0, x1 = LANE_CENTERS[start_lane], LANE_CENTERS[lane]
        coins = []
        for i in range(6):
            k = i / 5
            ease = k * k * (3 - 2 * k)
            coins.append(ItemPlacement(Item.COIN, x0 + (x1 - x0) * ease, w0 + (w1 - w0) * k))
        return coins

    def _prune(self, behind: float) -> None:
        for lists in (self.blocked, self.reserved):
            for i, intervals in enumerate(lists):
                lists[i] = [iv for iv in intervals if iv[1] >= behind]
        if self.corridor and self.corridor[0].end < behind:
            self.corridor = [s for s in self.corridor if s.end >= behind]
