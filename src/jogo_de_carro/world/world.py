"""The driving simulation shared by the race and the title screen's attract mode."""

import math
import random
from dataclasses import dataclass
from enum import Enum, auto

import pygame

from ..assets import Assets
from ..particles import Particles
from ..settings import (
    FIXED_DT,
    HEIGHT,
    LANE_CENTERS,
    NEAR_MISS_PX,
    NO_NEAR_MISS,
    PLAYER_Y,
    POWERS,
    PROTECT,
    SKINS,
    START_RAMP_S,
    TIME_SCALE,
    Difficulty,
    Item,
    Kind,
)
from ..tween import approach
from .difficulty import speed_at, versus_rows
from .obstacles import Obstacle, Trunk
from .pickups import Pickup
from .player import GRACE, Player
from .road import Road
from .spawner import ItemPlacement, Placement, Spawner
from .traffic import Traffic

ATTRACT_T = 45.0  # difficulty clock used by the title screen's endless demo drive
SPEED_LINE_BANDS = ((300.0, 396.0), (884.0, 980.0))
DODGE_WINDOW = 0.2  # seconds after a lane change starts during which passing an obstacle is a dodge
DEBRIS = {
    Kind.STONE: ((120, 116, 128), (86, 82, 96), (160, 156, 166)),
    Kind.CONE: ((247, 118, 34), (244, 244, 244)),
    Kind.TRUNK: ((122, 78, 48), (160, 108, 64), (86, 54, 36)),
    Kind.POTHOLE: ((60, 60, 70), (90, 90, 100)),
}


class EventKind(Enum):
    LANE_CHANGE = auto()
    COIN = auto()
    POWER_UP = auto()  # any power, the extra life included (WorldEvent.item)
    SHIELD_BREAK = auto()
    NEAR_MISS = auto()
    BUMP = auto()
    CRASH = auto()
    SMASH = auto()  # the star destroyed an obstacle
    LIFE_LOST = auto()  # the extra life took a hit, as a shield would


@dataclass(frozen=True)
class WorldEvent:
    kind: EventKind
    x: float
    y: float
    item: Item | None = None  # POWER_UP's


@dataclass
class Controls:
    steer: int = 0  # -1 / +1 to change lane this step
    vertical: float = 0.0  # -1 (up) .. +1 (down), held


class World:
    def __init__(
        self,
        assets: Assets,
        mode: Difficulty,
        skin: str,
        rng: random.Random,
        attract: bool = False,
        shared_road: bool = False,  # the road ignores the player: same seed, same road for every driver
        rival: str | None = None,  # the other driver's skin (versus): no traffic car wears it either
    ) -> None:
        self.assets = assets
        self.mode = mode
        self.rng = rng
        self.attract = attract
        self.shared_road = shared_road
        self.rival = rival
        # int sub-seeds: Random(float) seeds from hash(), which differs on 32-bit builds (the wasm)
        self.road = Road(assets, random.Random(rng.getrandbits(64)))
        if shared_road:
            mode = versus_rows(mode)
        self.spawner = Spawner(mode, random.Random(rng.getrandbits(64)))
        self.particles = Particles(random.Random(rng.getrandbits(64)))
        self.player = Player(assets, skin)
        self.obstacles: list[Obstacle] = []
        self.pickups: list[Pickup] = []
        self.distance = 0.0
        self.elapsed = ATTRACT_T if attract else 0.0
        self.speed = speed_at(mode, ATTRACT_T) if attract else 0.0
        self.running = attract
        self.invulnerable = attract
        if attract:  # the demo car never wears a power under the title menu
            self.spawner.next_item_t, self.spawner.frozen = math.inf, True
        self.px = 0.0  # how far the world moved on the last update
        self._exhaust = 0.0

    # --- simulation ------------------------------------------------------------------------------------

    def update(self, dt: float, controls: Controls) -> list[WorldEvent]:
        events: list[WorldEvent] = []
        player = self.player
        scale = TIME_SCALE.get(player.power, 1.0)
        wdt = dt * scale  # the world's clock: DEVAGAR and TURBO change it, the player's car keeps real time
        if self.running:
            if not self.attract and not player.crashed:
                self.elapsed += wdt
            target = speed_at(self.mode, self.elapsed)
            if player.crashed:  # a crash ends the power: the scale is 1 (and approach() needs no libm)
                self.speed = approach(self.speed, 0.0, 1.8, wdt)
            else:
                self.speed = min(target, self.speed + self.mode.base_speed / START_RAMP_S * wdt)
        self.px = self.speed * wdt
        self.distance += self.px
        lane = None if self.shared_road else player.lane
        for placement in self.spawner.update(self.distance, self.elapsed, self.speed, lane):
            self._spawn(placement)

        if controls.steer and player.steer(controls.steer):
            events.append(WorldEvent(EventKind.LANE_CHANGE, player.x, player.y))
            self.particles.dust(player.x - controls.steer * 24, player.y + 50, 5)
        player.update(dt, controls.vertical, self.speed)
        for ob in self.obstacles:
            ob.update(wdt, self.speed)
        for pickup in self.pickups:
            pickup.update(wdt, self.speed)
        self.road.update(self.px)
        self.particles.update(wdt, self.px)
        self._effects(dt, self.speed * scale)
        if not player.crashed:
            self._collide(events)
            self._collect(events)
        self.obstacles = [o for o in self.obstacles if o.rect.top < HEIGHT + 40]
        self.pickups = [p for p in self.pickups if p.y < HEIGHT + 40]
        return events

    def _spawn(self, p: Placement | ItemPlacement) -> None:
        y = PLAYER_Y - (p.g - self.distance)
        if isinstance(p, ItemPlacement):
            self.pickups.append(Pickup(self.assets, p.item, p.x, y))
            return
        x = float(LANE_CENTERS[p.lane])
        if p.kind.is_traffic:
            i = p.variant
            while SKINS[i % len(SKINS)] in (self.player.skin, self.rival):  # never a twin of a driver's car
                i += 1
            sprite = f"car_{SKINS[i % len(SKINS)]}" if p.kind is Kind.CAR else p.kind.value
            car = Traffic(
                self.assets,
                p.kind,
                sprite,
                p.lane,
                x,
                y,
                y,
                own_speed=p.own_speed,
                to_lane=p.to_lane,
                turn_y=p.turn_y,
                blink_time=p.blink,
            )
            self.obstacles.append(car)
        elif p.kind is Kind.TRUNK:
            assert p.to_lane is not None
            self.obstacles.append(Trunk(self.assets, p.kind, "trunk", p.lane, x, y, y, to_lane=p.to_lane))
        else:
            ob = Obstacle(self.assets, p.kind, p.kind.value, p.lane, x, y, y, flat=p.kind is Kind.POTHOLE)
            self.obstacles.append(ob)

    def _effects(self, dt: float, shown: float) -> None:
        """Exhaust, crash smoke and speed lines over the verges; ``shown``: the speed the road scrolls at."""
        player = self.player
        if player.crashed:
            if self.rng.random() < dt * 14:
                self.particles.smoke(player.x, player.y, 1)
            return
        self._exhaust -= dt
        if self._exhaust <= 0:  # idling at the start line puffs more slowly
            self._exhaust = 0.05 if self.speed > 0 else 0.14
            self.particles.exhaust(player.x - 14, player.y + 62)
        if shown > 520 and self.rng.random() < dt * (shown - 520) / 18:
            band = SPEED_LINE_BANDS[self.rng.random() < 0.5]
            self.particles.speed_line(self.rng.uniform(*band), self.speed)

    def _collide(self, events: list[WorldEvent]) -> None:
        player = self.player
        prect, pmask, pbody = player.rect, player.mask, player.body
        for ob in list(self.obstacles):
            orect = ob.rect
            if orect.colliderect(prect) and pmask.overlap(ob.mask, (orect.x - prect.x, orect.y - prect.y)):
                cx, cy = (player.x + ob.x) / 2, (player.y + ob.y) / 2
                if self.invulnerable or player.grace > 0 or player.power in PROTECT:
                    ob.passed = True  # driving through it is no near miss
                    if not self.invulnerable:  # a power's protection never ends inside it
                        player.grace = max(player.grace, 2 * FIXED_DT)
                    if player.power is Item.STAR:
                        self._smash(ob, cx, cy, Item.STAR, EventKind.SMASH, events)
                    continue
                if player.power is Item.SHIELD:
                    player.power, player.power_t, player.grace = None, 0.0, GRACE
                    self._smash(ob, cx, cy, Item.SHIELD, EventKind.SHIELD_BREAK, events)
                    continue
                if player.lives:
                    player.lives, player.grace = player.lives - 1, GRACE
                    self._smash(ob, cx, cy, Item.LIFE, EventKind.LIFE_LOST, events)
                    continue
                direction = player.x - ob.x or self.rng.choice((-1, 1))
                player.crash(direction)
                if isinstance(ob, Traffic):  # the other car takes the hit too
                    ob.x -= math.copysign(14, direction)
                    ob.tilt = math.copysign(12, direction)
                self.particles.sparks(cx, cy, 40)
                self.particles.smoke(cx, cy, 24)
                self.particles.debris(cx, cy, DEBRIS.get(ob.kind, ((210, 210, 220), (60, 64, 80))), 10)
                events.append(WorldEvent(EventKind.CRASH, cx, cy))
                return
            if ob.kind is Kind.POTHOLE:
                if orect.colliderect(prect.inflate(-20, -30)) and not ob.passed:
                    ob.passed = True
                    self.particles.dust(ob.x, ob.y, 6, (90, 90, 96))
                    events.append(WorldEvent(EventKind.BUMP, ob.x, ob.y))
                continue
            if ob.passed:
                continue
            body = ob.body
            if body.top > pbody.bottom:
                ob.passed = True
                if ob.dodged and ob.min_gap <= NEAR_MISS_PX and player.power not in NO_NEAR_MISS:
                    events.append(WorldEvent(EventKind.NEAR_MISS, (player.x + ob.x) / 2, player.y - 40))
            elif body.bottom >= pbody.top:  # side by side: only a dodge counts, not cruising past a truck
                gap = max(body.left - pbody.right, pbody.left - body.right)
                ob.min_gap = min(ob.min_gap, gap)
                ob.dodged = ob.dodged or player.steer_age < DODGE_WINDOW

    def _smash(
        self, ob: Obstacle, x: float, y: float, item: Item, kind: EventKind, events: list[WorldEvent]
    ) -> None:
        """An obstacle broken by a power: gone, in debris, for no points."""
        self.obstacles.remove(ob)
        self.particles.debris(ob.x, ob.y, DEBRIS.get(ob.kind, ((200, 200, 210), (90, 90, 110))))
        self.particles.burst(x, y, POWERS[item].colour, 24, 360)
        events.append(WorldEvent(kind, x, y))

    def _collect(self, events: list[WorldEvent]) -> None:
        player = self.player
        reach = player.rect.inflate(-14, -24)
        for pickup in list(self.pickups):
            if not reach.colliderect(pickup.rect):
                continue
            self.pickups.remove(pickup)
            item = pickup.item
            if item is Item.COIN:
                self.particles.burst(pickup.x, pickup.y, (255, 214, 90), 10)
                events.append(WorldEvent(EventKind.COIN, pickup.x, pickup.y))
                continue
            if player.crashed:  # taken on the crash tick: a wreck holds no power
                pass
            elif item is Item.LIFE:
                player.lives = 1
            else:  # it takes the one slot
                player.power, player.power_t = item, POWERS[item].seconds
            self.particles.burst(pickup.x, pickup.y, POWERS[item].colour, 22, 300)
            events.append(WorldEvent(EventKind.POWER_UP, pickup.x, pickup.y, item))

    # --- drawing ---------------------------------------------------------------------------------------

    def draw(
        self, surface: pygame.Surface, offset: tuple[float, float] = (0, 0), vignette: bool = True
    ) -> None:
        self.road.draw(surface, offset)
        for ob in self.obstacles:
            if ob.flat:
                ob.draw(surface, offset)
        for pickup in self.pickups:
            pickup.draw(surface, offset)
        for ob in sorted((o for o in self.obstacles if not o.flat), key=lambda o: o.y):
            ob.draw(surface, offset)
        self.player.draw(surface, offset)
        self.particles.draw(surface, offset)
        if vignette:  # the versus split screen shades both halves at once
            surface.blit(self.road.vignette, (0, 0))
