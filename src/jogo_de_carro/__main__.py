"""Entry point: ``python -m jogo_de_carro`` (or the ``jogo-de-carro`` script).

Set ``JOGO_AUTOPILOT=1`` to play the scripted demo instead; add ``JOGO_SCREENSHOT_DIR=<dir>`` to save its
frames as PNGs (see tools/screenshots.py).
"""

import asyncio
import logging
import os
from pathlib import Path

import pygame


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    try:
        if os.environ.get("JOGO_AUTOPILOT") == "1":
            from .demo import run_demo

            out = os.environ.get("JOGO_SCREENSHOT_DIR")
            run_demo(Path(out) if out else None)
        else:
            from .app import Game

            asyncio.run(Game().run())
    finally:
        pygame.quit()


if __name__ == "__main__":
    main()
