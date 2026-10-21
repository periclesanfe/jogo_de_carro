"""How many ranked runs this machine verifies at once, to set MAX_ATIVAS (plan §8 M3):

    python -m jogo_server.load --n 100 [--secs 60]        (on the VPS: jogo-admin load --n 100)

Starts the server in this process on a scratch database and plays N real-time ranked runs over WebSockets:
the corpus's Difícil win, cut at --secs and given up there, all on its seed. The clients share the server's
event loop, so they pay its lag too, as a slow server would make real players pay it. Reports the loop's lag
(the hub's sweeper skips its checks past 500 ms), the CPU used and every result: pick the largest N whose p99
lag stays well under 500 ms with no run rejected for ritmo or adiantado, and leave room for the other sites.
"""

import argparse
import asyncio
import dataclasses
import json
import logging
import os
import statistics
import tempfile
import time
from collections import Counter
from collections.abc import Iterator
from pathlib import Path

os.environ.setdefault("JOGO_DEV", "1")  # importing app builds its module-level app from the environment

import uvicorn
from websockets.asyncio.client import connect

from jogo_de_carro.golden import REPLAYS
from jogo_de_carro.run import simulate

from . import app as site
from . import auth, hub

BASE = "http://load.test"


def messages(log: dict, m: int, fin: dict | None = None) -> Iterator[tuple[int, dict]]:
    """A log's inputs as the game sends them: (k, the `in` message) every 12 ticks, the last one with fin."""
    ev, i = log["ev"], 0
    for k in range(hub.REPORT, log["end"] + hub.REPORT, hub.REPORT):
        k, j = min(k, log["end"]), i
        while j < len(ev) and ev[j][0] < k:
            j += 1
        msg, i = {"t": "in", "m": m, "k": k, "ev": ev[i:j]}, j
        if k == log["end"] and fin:
            msg["fin"] = fin
        yield k, msg


async def player(port: int, token: str, log: dict, delay: float) -> dict:
    await asyncio.sleep(delay)
    loop = asyncio.get_running_loop()
    uri = f"ws://127.0.0.1:{port}/ws"
    async with connect(uri, origin=BASE, additional_headers={"Cookie": f"sid={token}"}) as ws:
        hello = {"t": "hello", "build": "dev", "py": hub.RUNTIME[0], "pg": hub.RUNTIME[1], "skin": "yellow"}
        for msg in (hello, {"t": "solo", "mode": log["mode"]}):
            await ws.send(json.dumps(msg))
            reply = json.loads(await ws.recv())
        await ws.send(json.dumps({"t": "ready", "m": reply["m"]}))
        await ws.recv()  # go
        t0 = loop.time() + hub.COUNTDOWN_S
        for k, msg in messages(log, reply["m"], log["fin"]):
            await asyncio.sleep(max(0.0, t0 + k / 120 - loop.time()))
            await ws.send(json.dumps(msg))
        return json.loads(await ws.recv())


async def main(n: int, secs: float) -> None:
    full = json.loads((REPLAYS / "dificil_win.json").read_text(encoding="utf-8"))
    end = min(full["end"], round(secs * 120))
    log = {**full, "end": end, "ev": [e for e in full["ev"] if e[0] < end]}
    run = simulate(hub.assets(), log)
    log["fin"] = {"outcome": run.outcome, "score": run.score.total}
    hub.new_seed = lambda: log["seed"]
    with tempfile.TemporaryDirectory() as tmp:
        cfg = dataclasses.replace(
            site.Config.from_env(), dev=True, base=BASE, db=f"{tmp}/jogo.db", www=Path(tmp), smtp_host="",
            max_ativas=n, drain=Path(tmp) / "drain",
        )  # fmt: skip
        app = site.create_app(cfg)
        server = uvicorn.Server(
            uvicorn.Config(app, host="127.0.0.1", port=0, log_level="warning", ws_max_size=16384)
        )
        serving = asyncio.create_task(server.serve())
        while not server.started:
            await asyncio.sleep(0.05)
        port = server.servers[0].sockets[0].getsockname()[1]
        logging.getLogger("jogo").setLevel(logging.WARNING)  # not a line per run
        tokens = []
        for i in range(n):
            sql = "INSERT INTO users(email, nick, created) VALUES (?, ?, 0) RETURNING id"
            uid = app.state.db.execute(sql, (f"load{i}@load.test", f"load{i}")).fetchone()[0]
            tokens.append(auth.new_session(app.state.db, uid))

        lags, loop = [], asyncio.get_running_loop()

        async def sample() -> None:  # the hub's own measure: how late a 100 ms sleep wakes up
            while True:
                t = loop.time()
                await asyncio.sleep(0.1)
                lags.append(loop.time() - t - 0.1)

        sampler = asyncio.create_task(sample())
        wall, cpu = time.monotonic(), time.process_time()
        results = await asyncio.gather(*(player(port, t, log, i / n) for i, t in enumerate(tokens)))
        wall, cpu = time.monotonic() - wall, time.process_time() - cpu
        sampler.cancel()
        server.should_exit = True
        await serving
    ms = sorted(round(lag * 1000) for lag in lags)
    print(f"{n} corridas de {end / 120:.0f} s ao mesmo tempo, em {wall:.0f} s")
    p50, p99 = statistics.median(ms), ms[len(ms) * 99 // 100]
    print(f"atraso do loop: p50 {p50:.0f} ms, p99 {p99} ms, máx {ms[-1]} ms")
    print(f"CPU: {cpu / wall:.0%} de um núcleo (servidor e clientes)")
    print("resultados:", dict(Counter(f"{r['state']}/{r['why']}" for r in results)))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Mede quantas corridas ranqueadas o servidor aguenta.")
    parser.add_argument("--n", type=int, default=100, help="corridas ao mesmo tempo")
    parser.add_argument("--secs", type=float, default=60, help="duração de cada corrida (até 270 s)")
    args = parser.parse_args()
    asyncio.run(main(args.n, args.secs))
