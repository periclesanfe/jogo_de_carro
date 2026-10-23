"""Scripted tour through every scene, driven by synthetic input and the corridor autopilot.

Used for README screenshots/GIF (``tools/screenshots.py``) and to watch the game play itself.
Frames advance with a fixed 1/60 s step, so a run with the same seed always looks the same.
"""

import contextlib
import logging
import tempfile
from collections.abc import Callable
from pathlib import Path

import pygame

from .app import Game
from .save import SaveData, store
from .scenes.race import Phase, RaceScene
from .scenes.results import ResultsScene
from .settings import FACIL, HEIGHT, NORMAL
from .world.autopilot import showoff
from .world.traffic import Traffic

log = logging.getLogger(__name__)
FRAME = 1 / 60


class Director:
    def __init__(self, game: Game, out_dir: Path | None) -> None:
        self.game = game
        self.out_dir = out_dir
        self.clock = pygame.time.Clock()
        self.saved: list[Path] = []
        if out_dir:
            out_dir.mkdir(parents=True, exist_ok=True)

    def frame(self, dt: float = FRAME) -> None:
        if not self.game.running:
            raise SystemExit
        self.game.step(dt)
        if self.out_dir is None:  # watching live: keep real time
            self.clock.tick(round(1 / dt))

    def wait(self, seconds: float) -> None:
        for _ in range(round(seconds / FRAME)):
            self.frame()

    def until(self, condition: Callable[[], bool], timeout: float = 600.0) -> None:
        for _ in range(round(timeout / FRAME)):
            if condition():
                return
            self.frame()
        raise TimeoutError("demo step timed out")

    def tap(self, key: int, pause: float = 0.25) -> None:
        pygame.event.post(pygame.event.Event(pygame.KEYDOWN, key=key, mod=0, unicode="", scancode=0))
        pygame.event.post(pygame.event.Event(pygame.KEYUP, key=key, mod=0, unicode="", scancode=0))
        self.wait(pause)

    def shot(self, name: str) -> None:
        if self.out_dir:
            path = self.out_dir / f"{name}.png"
            pygame.image.save(self.game.screen, path)
            self.saved.append(path)
            log.info("saved %s", path)

    def record(self, name: str, seconds: float, fps: int = 25) -> None:
        """Save ``fps`` evenly timed frames per second into ``<out>/<name>/``, for GIFs/videos."""
        folder = self.out_dir / name if self.out_dir else None
        if folder:
            folder.mkdir(exist_ok=True)
        for i in range(round(seconds * fps)):
            self.frame(1 / fps)
            if folder:
                pygame.image.save(self.game.screen, folder / f"frame_{i:04d}.png")

    def best(self, name: str, seconds: float, score: Callable[[], float]) -> None:
        """Play for ``seconds`` and save the frame that scored highest (e.g. the busiest moment)."""
        best, top = None, 0.0
        for _ in range(round(seconds / FRAME)):
            self.frame()
            value = score()
            if value > top:
                best, top = self.game.screen.copy(), value
        if self.out_dir and best:
            pygame.image.save(best, self.out_dir / f"{name}.png")
            self.saved.append(self.out_dir / f"{name}.png")

    @property
    def race(self) -> RaceScene | None:
        top = self.game.scenes.top
        return top if isinstance(top, RaceScene) else None

    def racing(self) -> RaceScene:
        self.until(lambda: self.race is not None and self.race.phase is Phase.RACING)
        assert self.race
        return self.race

    def ram_traffic(self) -> bool:
        """Steer at the nearest car ahead (used as an ``until`` condition: True once crashed)."""
        race = self.race
        if race is None or race.phase is not Phase.RACING:
            return race is not None
        player = race.world.player
        ahead = [o for o in race.world.obstacles if isinstance(o, Traffic) and o.y < player.y - 140]
        if ahead and not player.changing_lane:
            lane = max(ahead, key=lambda o: o.y).lane
            if lane != player.lane:
                key = pygame.K_LEFT if lane < player.lane else pygame.K_RIGHT
                pygame.event.post(pygame.event.Event(pygame.KEYDOWN, key=key, mod=0, unicode="", scancode=0))
                pygame.event.post(pygame.event.Event(pygame.KEYUP, key=key, mod=0, unicode="", scancode=0))
        return False


def busy(race: RaceScene) -> float:
    """How much is going on: objects on the road, floating popups and particles."""
    world = race.world
    road = sum(2 if isinstance(o, Traffic) else 1 for o in world.obstacles if 0 < o.y < HEIGHT)
    coins = sum(1 for p in world.pickups if 0 < p.y < HEIGHT)
    return road + coins / 2 + 3 * len(race.popups) + min(len(world.particles.items), 60) / 15


def near_miss(race: RaceScene) -> float:
    fresh = [p for p in race.popups if "QUASE" in p.label and 0.15 < p.life < 0.4]
    return 10 * len(fresh) + race.score.combo + busy(race) / 10 if fresh else 0.0


def tour(d: Director) -> None:
    k = pygame
    d.wait(4.6)
    d.shot("01_title")
    d.tap(k.K_DOWN)
    d.tap(k.K_RETURN, 0.9)  # SKIN
    d.tap(k.K_RIGHT, 0.35)
    d.tap(k.K_RIGHT, 0.8)
    d.shot("02_garage")
    d.tap(k.K_LEFT, 0.2)
    d.tap(k.K_LEFT, 0.5)
    d.tap(k.K_RETURN, 0.9)  # back on the title, SKIN focused
    d.tap(k.K_DOWN)
    d.tap(k.K_RETURN, 1.0)  # DIFICULDADE
    d.shot("03_difficulty")
    d.tap(k.K_ESCAPE, 0.9)
    d.tap(k.K_UP)
    d.tap(k.K_UP)
    d.tap(k.K_RETURN, 0.65)  # JOGAR (Normal)
    d.shot("04_countdown")

    race = d.racing()
    race.pilot = showoff  # late dodges: near misses and combos
    d.wait(6.5)
    d.shot("05_race")
    d.game.time_scale = 4.0
    d.until(lambda: race.world.player.power is not None)  # fast-forward to the first power picked up
    d.game.time_scale = 1.0
    d.wait(0.3)
    d.shot("07_power")
    d.game.time_scale = 6.0  # fast-forward to the faster, busier part of the run
    d.until(lambda: race.world.elapsed >= 80)
    d.game.time_scale = 1.0
    d.record("gif_race", 10.0)
    d.best("06_near_miss", 8.0, lambda: near_miss(race))  # late in the run, so combos are up
    d.best("08_race_late", 8.0, lambda: busy(race))
    d.tap(k.K_ESCAPE, 0.5)
    d.shot("09_pause")
    d.tap(k.K_ESCAPE, 0.8)

    d.game.ctx.autopilot = False  # let go of the wheel... and aim for the traffic
    d.until(d.ram_traffic)
    d.wait(0.3)
    d.shot("10_crash")
    d.until(lambda: isinstance(d.game.scenes.top, ResultsScene))
    d.wait(2.2)
    d.shot("11_game_over")

    d.tap(k.K_RIGHT)
    d.tap(k.K_RETURN, 1.0)  # MENU
    d.tap(k.K_DOWN)
    d.tap(k.K_DOWN)
    d.tap(k.K_RETURN, 0.9)  # DIFICULDADE
    d.tap(k.K_LEFT, 0.4)  # Fácil
    d.tap(k.K_RETURN, 0.9)
    d.tap(k.K_UP)
    d.tap(k.K_UP)
    d.game.ctx.autopilot = True
    d.tap(k.K_RETURN, 0.9)  # JOGAR (Fácil)
    race = d.racing()
    race.pilot = showoff
    d.game.time_scale = 12.0
    d.until(lambda: race.phase is Phase.WON)
    d.game.time_scale = 1.0
    d.wait(0.3)
    d.shot("12_victory")
    d.until(lambda: isinstance(d.game.scenes.top, ResultsScene))
    d.wait(2.2)
    d.shot("13_victory_results")


def run_demo(out_dir: Path | None = None, seed: int = 2022) -> list[Path]:
    """Play the tour with a throw-away save; returns the screenshots written (if ``out_dir`` is set)."""
    with tempfile.TemporaryDirectory() as tmp:
        save_path = Path(tmp) / "save.json"
        store(SaveData(best={NORMAL.key: 5000, FACIL.key: 3000}), save_path)  # records to show and beat
        game = Game(save_path=save_path, seed=seed, autopilot=True)
        director = Director(game, out_dir)
        with contextlib.suppress(SystemExit):  # the window was closed
            tour(director)
        return director.saved
