"""One race as a pure function of (mode, skin, seed, shared road, inputs).

RaceScene, the bot rival and the server's verifier all step a Run, so the scoring rules live only here. Each
step is one FIXED_DT tick; tick 0 is the first racing tick ("JÁ!").

Input log v1 (JSON): {"v": 1, "mode": "normal", "skin": "yellow", "seed": <int>, "shared": false,
"end": <ticks played>, "ev": [[tick, "L" | "R" | held], ...]}. "L"/"R" is the lane change made on that tick;
held, from that tick on, is the held keys: bit 1 = UP (up, plus the +15% boost when held alone), bit 2 = DOWN.
A run that neither crashed nor won before "end" was given up there.
"""

import random
from collections import deque
from collections.abc import Callable

from .assets import Assets
from .settings import CARS, FIXED_DT, MODE_BY_KEY, RANKED_CAP_S, VERSUS_CAP_S
from .world.scoring import Score
from .world.world import Controls, EventKind, World, WorldEvent

MAX_STEP = 240  # ticks one input message may cover
MAX_MESSAGE = 64  # events per message
MAX_EVENTS = 30 * RANKED_CAP_S  # events per run: 30 a second over the longest run (2 a tick at most)

Driver = Callable[[World], Controls]
Scored = list[tuple[WorldEvent, int]]  # a tick's events with the points each one earned


class BadInput(ValueError):
    """A malformed input message: the run is rejected."""


class Run:
    def __init__(
        self,
        assets: Assets,
        mode_key: str,
        skin: str,
        seed: int,
        shared: bool,
        driver: Driver | None = None,
        rival: str | None = None,  # the other driver's skin, for the traffic colours only
    ) -> None:
        ok = type(mode_key) is str and mode_key in MODE_BY_KEY and type(skin) is str and skin in CARS
        if not (ok and type(shared) is bool):
            raise BadInput("bad run")
        if type(seed) is not int or seed < 0:  # Random(1.5) seeds from hash(): another road on wasm32
            raise BadInput("bad seed")
        self.mode = MODE_BY_KEY[mode_key]
        self.skin, self.seed, self.shared, self.driver = skin, seed, shared, driver
        cap_s = VERSUS_CAP_S if shared else RANKED_CAP_S
        self.win_s = self.mode.win_s or cap_s  # Infinito "wins" at the cap
        self.cap = round(cap_s / FIXED_DT) + 1  # input ticks accepted (the clock reaches 600 s on tick 72001)
        self.world = World(assets, self.mode, skin, random.Random(seed), shared_road=shared, rival=rival)
        # the countdown: the car stands while the first rows are planned; more standing ticks change nothing
        self.world.update(FIXED_DT, Controls())
        self.score = Score()
        self.tick = 0  # racing ticks simulated
        self.known = 0  # inputs are known for the ticks before this one
        self.outcome: str | None = None  # "crash", "win", "giveup"... once the run is over
        self.held = 0
        self.ev: list[list] = []  # the log of the ticks simulated
        self._fed: deque[tuple[int, int | str]] = deque()  # inputs fed but not simulated yet
        self._fed_held = 0
        self._fed_count = 0

    @property
    def seconds(self) -> float:
        return min(self.world.elapsed, self.win_s)

    def step(self, controls: Controls, boost: bool) -> Scored:
        """One racing tick: the only code that scores."""
        world, score = self.world, self.score
        world.running = True
        events = world.update(FIXED_DT, controls)
        score.drive(world.px, boost)
        score.update(FIXED_DT)
        out = []
        for e in events:  # the events after a crash in the same tick still score
            points = 0
            if e.kind is EventKind.COIN:
                points = score.coin()
            elif e.kind is EventKind.NEAR_MISS:
                points = score.near_miss()
            out.append((e, points))
        self.tick += 1
        if any(e.kind is EventKind.CRASH for e in events):
            self.outcome = "crash"
        elif world.elapsed >= self.win_s:  # never a tick count: Difícil is won on tick 32401, not 32400
            self.outcome = "win"
        return out

    def play(self, steer: int, held: int) -> Scored:
        """One tick of player input, a lane change (-1, 0, 1) and the held keys: logged, then stepped.

        Past MAX_EVENTS logged, input is ignored, as load() would not take it: what is played always replays.
        """
        if held != self.held and len(self.ev) < MAX_EVENTS:
            self.ev.append([self.tick, held])
            self.held = held
        if steer and len(self.ev) < MAX_EVENTS:
            self.ev.append([self.tick, "L" if steer < 0 else "R"])
        else:
            steer = 0
        held = self.held
        return self.step(Controls(steer, float((held >> 1) - (held & 1))), held == 1)

    def feed(self, k: int, ev: list) -> None:
        """One input message from a client: the inputs for the ticks [known, k).

        The trust boundary: it accepts exactly the well-formed messages, and anything else raises BadInput
        (and nothing else) before any state changes. JSON true is not an int; 1.0 is not a tick.
        """
        if type(k) is not int or type(ev) is not list or k > self.known + MAX_STEP or len(ev) > MAX_MESSAGE:
            raise BadInput("bad message")
        self.load(k, ev)

    def load(self, k: int, ev: list) -> None:
        """Queue the inputs for the ticks [known, k), event by event; feed() adds the per-message limits.

        Anything malformed raises BadInput (and nothing else) before any state changes.
        """
        if not (type(k) is int and type(ev) is list and self.known < k <= self.cap):
            raise BadInput("bad k")
        if self._fed_count + len(ev) > MAX_EVENTS:
            raise BadInput("too many events")
        queue: list[tuple[int, int | str]] = []
        tick, held, steered, changed = self.known, self._fed_held, -1, -1
        try:
            for t, v in ev:
                if type(t) is not int or not tick <= t < k:
                    raise BadInput("bad tick")
                if v in ("L", "R") and t != steered:  # one lane change per tick at most
                    steered = t
                elif type(v) is int and 0 <= v <= 3 and v != held and t != changed:  # only changes are logged
                    held, changed = v, t
                else:
                    raise BadInput("bad event")
                tick = t
                queue.append((t, v))
        except BadInput:
            raise
        except Exception as e:  # e.g. an event that is not a pair
            raise BadInput("bad event") from e
        self._fed += queue
        self.known, self._fed_held, self._fed_count = k, held, self._fed_count + len(queue)

    def advance(self, to: int) -> Scored:
        """Simulate up to tick ``to`` with the driver, or with the fed inputs as far as they are known."""
        out = []
        while self.outcome is None and self.tick < to and (self.driver or self.tick < self.known):
            if self.driver:
                out += self.step(self.driver(self.world), False)
                continue
            steer, held = 0, self.held
            while self._fed and self._fed[0][0] == self.tick:
                v = self._fed.popleft()[1]
                if isinstance(v, int):
                    held = v
                else:
                    steer = -1 if v == "L" else 1
            out += self.play(steer, held)
        return out

    def stop(self, why: str) -> None:
        """End a run that is still going on the current tick: a give-up or a lost connection."""
        self.outcome = self.outcome or why

    def log(self) -> dict:
        return {
            "v": 1,
            "mode": self.mode.key,
            "skin": self.skin,
            "seed": self.seed,
            "shared": self.shared,
            "end": self.tick,
            "ev": self.ev,
        }


def verdict(a: Run, b: Run) -> int | None:
    """1 if run a beat run b, -1 if b beat a, 0 for a draw, None while it is open.

    A run that ended early (crash, give-up, lost connection) after T ticks loses to a run still alive past T:
    a tick is real time (DEVAGAR and TURBO only change the world's clock), so that is who lasted longer, as
    the split screen shows it. Two runs that both won (or reached the cap), or ended early on the same tick,
    are decided by score.
    """
    early_a, early_b = a.outcome not in (None, "win"), b.outcome not in (None, "win")
    if early_a and early_b and a.tick != b.tick:
        return 1 if a.tick > b.tick else -1
    if early_a and not early_b:
        return -1 if b.outcome == "win" or b.tick > a.tick else None
    if early_b and not early_a:
        return 1 if a.outcome == "win" or a.tick > b.tick else None
    if early_a or a.outcome == b.outcome == "win":
        return (a.score.total > b.score.total) - (a.score.total < b.score.total)
    return None


def simulate(assets: Assets, log: dict) -> Run:
    """Replay a v1 log and return the finished Run."""
    run = Run(assets, log["mode"], log["skin"], log["seed"], log["shared"])
    run.load(log["end"], log["ev"])
    run.advance(log["end"])
    run.stop("giveup")
    return run
