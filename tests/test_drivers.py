"""The corridor drivers survive with the real sprites and pixel-mask collisions; near misses need a dodge."""

import json
import random

import pygame
import pytest

from jogo_de_carro.assets import Assets
from jogo_de_carro.golden import REPLAYS
from jogo_de_carro.run import Run
from jogo_de_carro.settings import DIFICIL, LANE_CENTERS, NORMAL, PROTECT, Item, Kind
from jogo_de_carro.world.autopilot import autopilot, showoff
from jogo_de_carro.world.spawner import ItemPlacement, Placement
from jogo_de_carro.world.world import Controls, EventKind, World


@pytest.fixture(scope="module")
def assets():
    pygame.init()
    pygame.display.set_mode((64, 64))
    return Assets()


@pytest.mark.parametrize("driver", [autopilot, showoff], ids=["autopilot", "showoff"])
def test_drivers_survive_a_minute_of_dificil(assets, driver):
    world = World(assets, DIFICIL, "yellow", random.Random(3))
    world.running = True
    events: list[EventKind] = []
    while world.elapsed < 60:
        events += [e.kind for e in world.update(1 / 120, driver(world))]
    assert EventKind.CRASH not in events
    assert EventKind.SHIELD_BREAK not in events
    if driver is showoff:  # late dodges are what the demo is for
        assert events.count(EventKind.NEAR_MISS) >= 10


def test_autopilot_survives_slow_motion(assets):
    """DEVAGAR protects nothing: in bullet time the corridor still fits every lane change."""
    hit = (EventKind.CRASH, EventKind.SHIELD_BREAK, EventKind.LIFE_LOST)
    for seed in range(40):
        world = World(assets, DIFICIL, "yellow", random.Random(seed))
        world.running = True
        while world.elapsed < 20:
            world.player.power, world.player.power_t = Item.SLOW, 1.0  # whatever it picks up
            assert not any(e.kind in hit for e in world.update(1 / 120, autopilot(world))), seed


def _drive_past(assets, placements, dodge_at=None, power=None, lives=0) -> list[EventKind]:
    """Player in the middle lane; steer right once the first obstacle is ``dodge_at`` px away."""
    world = World(assets, NORMAL, "yellow", random.Random(0))
    world.running, world.spawner.enabled = True, False
    world.player.power, world.player.power_t, world.player.lives = power, 8.0, lives
    for kind, lane, ahead in placements:
        world._spawn(Placement(kind, lane, world.distance + ahead))
    first = world.obstacles[0]
    events: list[EventKind] = []
    for _ in range(4 * 120):
        steer = dodge_at is not None and world.player.lane == 2 and first.y >= world.player.y - dodge_at
        events += [e.kind for e in world.update(1 / 120, Controls(steer=int(steer)))]
    return [e for e in events if e is not EventKind.LANE_CHANGE]


def test_near_miss_needs_a_dodge(assets):
    assert _drive_past(assets, [(Kind.TRUCK, 3, 600)]) == []  # cruising past a truck is free of charge
    assert _drive_past(assets, [(Kind.STONE, 2, 600)], dodge_at=140) == [EventKind.NEAR_MISS]
    assert _drive_past(assets, [(Kind.STONE, 2, 600)], dodge_at=400) == []  # dodged early: no thrill
    # driving through a cone while the broken shield still protects you is no near miss
    shield = _drive_past(assets, [(Kind.STONE, 2, 600), (Kind.CONE, 2, 760)], power=Item.SHIELD)
    assert shield == [EventKind.SHIELD_BREAK]
    stone = [(Kind.STONE, 2, 600)]
    for power in PROTECT:  # nor is a dodge while a power is on, but for the shield
        assert _drive_past(assets, stone, dodge_at=140, power=power) == [], power
    assert _drive_past(assets, stone, dodge_at=140, power=Item.SHIELD) == [EventKind.NEAR_MISS]


def test_no_near_miss_in_slow_motion(assets):
    """Nor in DEVAGAR's, which a lone stone cannot show (in bullet time it comes alongside after the dodge
    window, real time, has closed): on a real road, Difícil's corpus win dodges while it holds DEVAGAR."""
    log = json.loads((REPLAYS / "dificil_win.json").read_text(encoding="utf-8"))
    run = Run(assets, log["mode"], log["skin"], log["seed"], log["shared"])
    run.load(log["end"], log["ev"])
    near, slow = 0, 0
    while run.tick < log["end"]:
        kinds = {e.kind for e, _ in run.advance(run.tick + 1)}
        power = run.world.player.power
        slow += power is Item.SLOW
        if EventKind.NEAR_MISS in kinds and EventKind.POWER_UP not in kinds:  # (the power it was dodged with)
            near += 1
            assert power in (None, Item.SHIELD), (run.tick, power)
    assert near > 10 and slow


def test_powers_take_the_hits(assets):
    ahead = [(Kind.STONE, 2, 600), (Kind.CONE, 2, 760)]
    assert _drive_past(assets, ahead, power=Item.STAR) == [EventKind.SMASH] * 2
    assert _drive_past(assets, ahead, power=Item.GHOST) == [] == _drive_past(assets, ahead, power=Item.TURBO)
    # an extra life breaks like a shield: neither a crash nor, for the cone in its grace, a near miss
    assert _drive_past(assets, ahead, lives=1) == [EventKind.LIFE_LOST]


def test_protection_never_ends_inside_an_obstacle(assets):
    """FANTASMA runs out inside a truck that is nearly as fast: the grace lasts until the car is out of it."""
    world = World(assets, NORMAL, "yellow", random.Random(0))
    world.running, world.spawner.enabled, world.speed = True, False, NORMAL.base_speed
    world.player.power, world.player.power_t = Item.GHOST, 0.1
    world._spawn(Placement(Kind.TRUCK, 2, world.distance, own_speed=NORMAL.base_speed - 40))
    truck, ticks = world.obstacles[0], 0
    while truck.rect.colliderect(world.player.rect):
        assert EventKind.CRASH not in [e.kind for e in world.update(1 / 120, Controls())]
        ticks += 1
    assert ticks > 120 * 2  # out long after the power and its grace ran out

    world = World(assets, NORMAL, "yellow", random.Random(0))
    world.running, world.spawner.enabled, world.invulnerable = True, False, True  # a victory lap: no blinking
    world._spawn(Placement(Kind.STONE, 2, world.distance))
    world.update(1 / 120, Controls())
    assert world.obstacles[0].passed and world.player.grace == 0


def test_a_wreck_holds_no_power(assets):
    """A power (or the life) taken on the crash tick goes with the car: no TURBO clock, look or panel."""
    for item in (Item.TURBO, Item.LIFE):
        world = World(assets, NORMAL, "yellow", random.Random(0))
        world.running, world.spawner.enabled = True, False
        world._spawn(Placement(Kind.STONE, 2, world.distance))
        world._spawn(ItemPlacement(item, LANE_CENTERS[2], world.distance))
        assert [e.kind for e in world.update(1 / 120, Controls())] == [EventKind.CRASH, EventKind.POWER_UP]
        assert (world.player.power, world.player.lives) == (None, 0), item
