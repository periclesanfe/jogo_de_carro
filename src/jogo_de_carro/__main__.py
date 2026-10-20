"""Entry point: ``python -m jogo_de_carro`` (or the ``jogo-de-carro`` script).

Set ``JOGO_AUTOPILOT=1`` to play the scripted demo instead; add ``JOGO_SCREENSHOT_DIR=<dir>`` to save its
frames as PNGs (see tools/screenshots.py). ``JOGO_RECORD=<dir>`` saves the input log of every race played, and
``--replay run.json`` plays one back (for reviewing a run; nothing is saved).
"""

import asyncio
import json
import logging
import os
import sys
import tempfile
from pathlib import Path

import pygame


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    try:
        if sys.argv[1:2] == ["--replay"]:
            replay(json.loads(Path(sys.argv[2]).read_text(encoding="utf-8")))
        elif os.environ.get("JOGO_AUTOPILOT") == "1":
            from .demo import run_demo

            out = os.environ.get("JOGO_SCREENSHOT_DIR")
            run_demo(Path(out) if out else None)
        else:
            from .app import Game

            asyncio.run(Game().run())
    finally:
        pygame.quit()


def replay(log: dict) -> None:
    from .app import Game
    from .scenes.base import Transition
    from .scenes.race import RaceScene

    with tempfile.TemporaryDirectory() as tmp:
        game = Game(save_path=Path(tmp) / "save.json")  # a throw-away save: the replay sets no records
        game.ctx.save.mode, game.ctx.save.skin = log["mode"], log["skin"]
        race = RaceScene(game.ctx, log["seed"], log["shared"])
        race.run.load(log["end"], log["ev"])  # the log drives the race; Esc still pauses
        game.scenes.switch(race, Transition.FADE)
        asyncio.run(game.run())


if __name__ == "__main__":
    main()
