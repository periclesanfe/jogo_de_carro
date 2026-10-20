"""Browser entry point: tools/web_build.py packs it next to the package and builds it with pygbag.

``?golden=1`` logs ``GOLDEN <sha256>`` to the browser console instead of starting the game (CI's golden gate).
"""

import asyncio
import platform  # pygbag's: exposes the page's ``window``
import traceback
from urllib.parse import parse_qs

import pygame  # noqa: F401  pygbag only installs the packages main.py imports

from jogo_de_carro.app import Game


async def main() -> None:
    if parse_qs(str(platform.window.location.search)[1:]).get("golden") == ["1"]:
        from jogo_de_carro.golden import digest

        try:
            line = f"GOLDEN {digest()}"
        except Exception:
            line = f"GOLDEN ERROR {traceback.format_exc()}"
        print(line)
        platform.window.console.log(line)  # print() only reaches pygbag's in-page terminal
        return
    await Game().run()


asyncio.run(main())
