"""Browser entry point: tools/web_build.py packs it next to the package and builds it with pygbag.

``?golden=1`` logs ``GOLDEN <sha256>`` to the browser console instead of starting the game (CI's golden gate);
``?selftest=1`` sends a hello over the site's socket and logs ``NET OK`` once any reply comes (``error/login``
proves the round trip).
"""

import asyncio
import platform  # pygbag's: exposes the page's ``window``
import time
import traceback
from urllib.parse import parse_qs

import pygame  # noqa: F401  pygbag only installs the packages main.py imports

from jogo_de_carro.app import Game
from jogo_de_carro.net import CLOSED, Net


def say(line: str) -> None:
    print(line)
    platform.window.console.log(line)  # print() only reaches pygbag's in-page terminal


async def selftest() -> str:
    net = Net()
    net.connect("yellow")
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        if any(m.get("t") != CLOSED for m in net.poll()):
            return "NET OK"
        await asyncio.sleep(0)
    return "NET FAIL"


async def main() -> None:
    query = parse_qs(str(platform.window.location.search)[1:])
    if query.get("golden") == ["1"]:
        from jogo_de_carro.golden import digest

        try:
            say(f"GOLDEN {digest()}")
        except Exception:
            say(f"GOLDEN ERROR {traceback.format_exc()}")
        return
    if query.get("selftest") == ["1"]:
        say(await selftest())
        return
    await Game(net=Net()).run()


asyncio.run(main())
