"""Drivers that follow the spawner's safe corridor: they power the attract mode, demos, tests and the bot."""

import random

from ..settings import LANE_CHANGE_TIME, PLAYER_Y, START_LANE
from ..tween import clamp
from .traffic import Traffic
from .world import Controls, World

LATE_DODGE = 0.05  # seconds before contact when the show-off driver finally changes lane


def autopilot(world: World) -> Controls:
    player = world.player
    track = world.distance + (PLAYER_Y - player.y)
    target = world.spawner.corridor_lane(track + 4.0)
    steer = (target > player.lane) - (target < player.lane)
    return Controls(steer=steer, vertical=clamp((player.y - PLAYER_Y) / -40.0, -1.0, 1.0))


def showoff(world: World) -> Controls:
    """The autopilot, but it holds its lane until the last moment, so dodges become near misses.

    Only one-lane moves are delayed, and only while the corridor keeps wanting the new lane, which the
    spawner keeps reserved from the lane-change window on; so it is as safe as the autopilot.
    """
    base = autopilot(world)
    player = world.player
    if player.changing_lane or not base.steer:
        return base
    track = world.distance + (PLAYER_Y - player.y)
    target = player.lane + base.steer
    v = max(world.speed, 1.0)
    if world.spawner.corridor_lane(track + 4.0) != target:  # a two-lane move: no stunts
        return base
    if world.spawner.corridor_lane(track + (LANE_CHANGE_TIME + 0.15) * v) != target:
        return base  # the corridor moves on soon
    body = player.body.inflate(12, 0)
    for ob in world.obstacles:
        ob_body = ob.body
        if ob_body.right <= body.left or ob_body.left >= body.right or ob_body.top > body.bottom:
            continue
        closing = v - (ob.own_speed if isinstance(ob, Traffic) else 0.0)
        if body.top - ob_body.bottom <= LATE_DODGE * closing:
            return base  # now!
    return Controls(steer=0, vertical=base.vertical)


class Bot:
    """The autopilot with human reflexes, for "desafiar um bot".

    Each time the corridor asks for a new lane the bot reacts after a random delay (exponential, mean
    ``react`` s). A rare slow reaction misses the lane-change window, and the window shrinks as the rows
    get faster, so it crashes later in a run on easier modes and sooner on harder ones.
    """

    def __init__(self, react: float, rng: random.Random) -> None:
        self.react, self.rng = react, rng
        self.target, self.at = START_LANE, 0.0

    def __call__(self, world: World) -> Controls:
        base = autopilot(world)
        player = world.player
        target = world.spawner.corridor_lane(world.distance + (PLAYER_Y - player.y) + 4.0)
        if target != self.target:
            self.target, self.at = target, world.elapsed + self.rng.expovariate(1 / self.react)
        if world.elapsed < self.at:
            return Controls(steer=0, vertical=base.vertical)
        return base


# mean reaction time (s) per bot level, tuned on the shared road
BOT_LEVELS = {"facil": 0.20, "medio": 0.13, "dificil": 0.07}
