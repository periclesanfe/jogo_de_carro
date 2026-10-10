"""Drivers that follow the spawner's safe corridor: they power the attract mode, demos and tests."""

from ..settings import LANE_CHANGE_TIME, PLAYER_Y
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
