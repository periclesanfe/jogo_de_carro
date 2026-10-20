"""``python -m jogo_de_carro.golden`` prints ``GOLDEN <sha256>``.

The digest covers what the simulation computes that another runtime could compute differently: the speed
curve's fifth roots at every tick of a ranked run, every collision mask and body box (pygame's scale and draw
code), and the replay corpus: its state on every tick (a 1-ULP drift seldom changes a result) and its
results. The server refuses to start unless its digest equals the one the browser printed. No display is
needed.
"""

import dataclasses
import hashlib
import json
import struct
from pathlib import Path

import pygame

from .assets import Assets
from .run import Run
from .settings import FIXED_DT, HITBOX_SHRINK, RANKED_CAP_S, SKINS, Kind
from .world.difficulty import pow_08
from .world.obstacles import OBSTACLE_HITBOX, Obstacle
from .world.spawner import SPEED_LOOKAHEAD_S

REPLAYS = Path(__file__).parent / "replays"  # package data: the browser and the server run this too


def _bits(mask: pygame.Mask) -> bytes:
    w, h = mask.get_size()  # one byte per pixel: the Mask's own buffer depends on the word size
    return bytes(mask.get_at((x, y)) for y in range(h) for x in range(w))


def digest() -> str:
    logs = sorted(REPLAYS.glob("*.json"))
    if not logs:
        raise FileNotFoundError(f"no replays in {REPLAYS}")
    h = hashlib.sha256()

    def put(*values: object) -> None:
        h.update(repr([v.hex() if isinstance(v, float) else v for v in values]).encode())

    roots, elapsed = [], 0.0
    for _ in range(round(RANKED_CAP_S / FIXED_DT)):  # the speed curve as World.update and the spawner ask
        elapsed += FIXED_DT
        roots += (pow_08(elapsed), pow_08(elapsed + SPEED_LOOKAHEAD_S))
    h.update(struct.pack(f"<{len(roots)}d", *roots))

    assets = Assets()
    cars = [f"car_{skin}" for skin in SKINS]
    for name, shrink in [(c, HITBOX_SHRINK) for c in cars] + [
        (n, OBSTACLE_HITBOX) for n in [*cars, "van", "truck", "stone", "cone", "trunk"]
    ]:
        mask = assets.mask(name, 0, shrink)
        put(name, shrink, mask.get_size(), _bits(mask), tuple(assets.bounds(name)))
    pothole = Obstacle(assets, Kind.POTHOLE, "pothole", 0, 0.0, 0.0, flat=True).mask
    put("pothole", pothole.get_size(), _bits(pothole), tuple(assets.bounds("pothole")))

    for path in logs:  # simulate(), one tick at a time
        log = json.loads(path.read_text(encoding="utf-8"))
        run = Run(assets, log["mode"], log["skin"], log["seed"], log["shared"])
        run.load(log["end"], log["ev"])
        world, player = run.world, run.world.player
        while run.outcome is None and run.tick < log["end"]:
            run.advance(run.tick + 1)
            state = [player.x, player.y, player.vy, world.speed, world.distance, len(world.pickups)]
            state += [v for ob in world.obstacles for v in (ob.x, ob.y)]
            h.update(struct.pack(f"<{len(state)}d", *state))
        run.stop("giveup")
        put(path.name, run.outcome, run.tick, world.elapsed, world.distance, *dataclasses.astuple(run.score))
    return h.hexdigest()


if __name__ == "__main__":
    print("GOLDEN", digest())
