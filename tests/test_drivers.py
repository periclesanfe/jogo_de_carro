"""The corridor drivers survive with the real sprites and pixel-mask collisions; near misses need a dodge."""

import random

import pygame
import pytest

from jogo_de_carro.assets import Assets
from jogo_de_carro.settings import DIFICIL, NORMAL, Kind
from jogo_de_carro.world.autopilot import autopilot, showoff
from jogo_de_carro.world.spawner import Placement
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


def _drive_past(assets, placements, dodge_at=None, shield=False) -> list[EventKind]:
    """Player in the middle lane; steer right once the first obstacle is ``dodge_at`` px away."""
    world = World(assets, NORMAL, "yellow", random.Random(0))
    world.running, world.spawner.enabled = True, False
    world.player.shield = 8.0 if shield else 0.0
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
    shield = _drive_past(assets, [(Kind.STONE, 2, 600), (Kind.CONE, 2, 760)], shield=True)
    assert shield == [EventKind.SHIELD_BREAK]
