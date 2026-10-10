"""Boot the real Game headless and drive every scene with scripted input."""

import pygame
import pytest

from jogo_de_carro.app import Game
from jogo_de_carro.scenes.base import Transition
from jogo_de_carro.scenes.difficulty import DifficultyScene, card_rect
from jogo_de_carro.scenes.garage import ARROWS, GarageScene
from jogo_de_carro.scenes.pause import PauseScene
from jogo_de_carro.scenes.race import Outcome, Phase, RaceScene
from jogo_de_carro.scenes.results import ResultsScene
from jogo_de_carro.scenes.title import TitleScene
from jogo_de_carro.settings import FACIL, NORMAL

FRAME = 1 / 60


@pytest.fixture
def game(tmp_path):
    return Game(save_path=tmp_path / "save.json", seed=7)


def frames(game: Game, n: int) -> None:
    for _ in range(n):
        game.step(FRAME)


def key(game: Game, k: int, wait: int = 20) -> None:
    pygame.event.post(pygame.event.Event(pygame.KEYDOWN, key=k, mod=0, unicode="", scancode=0))
    pygame.event.post(pygame.event.Event(pygame.KEYUP, key=k, mod=0, unicode="", scancode=0))
    frames(game, wait)


def click(game: Game, pos: tuple[int, int], wait: int = 20) -> None:
    pygame.event.post(pygame.event.Event(pygame.MOUSEMOTION, pos=pos, rel=(0, 0), buttons=(0, 0, 0)))
    pygame.event.post(pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=pos, button=1))
    frames(game, wait)


def until(game: Game, condition, seconds: float) -> None:
    for _ in range(int(seconds / FRAME)):
        if condition():
            return
        game.step(FRAME)
    raise AssertionError(f"condition not met within {seconds}s (top scene: {game.scenes.top})")


def top(game: Game):
    return game.scenes.top


def test_every_scene_with_scripted_input(game):
    frames(game, 120)
    assert isinstance(top(game), TitleScene)

    key(game, pygame.K_DOWN)
    key(game, pygame.K_RETURN, 60)  # SKIN
    assert isinstance(top(game), GarageScene)
    key(game, pygame.K_RIGHT)
    click(game, ARROWS[1].center)
    frames(game, 120)
    key(game, pygame.K_RETURN, 60)
    assert game.ctx.save.skin == "blue"  # yellow -> black (key) -> blue (mouse arrow)
    assert isinstance(top(game), TitleScene)

    key(game, pygame.K_DOWN)
    key(game, pygame.K_RETURN, 60)  # DIFICULDADE
    assert isinstance(top(game), DifficultyScene)
    key(game, pygame.K_RIGHT)
    frames(game, 120)
    click(game, card_rect(0).center, 60)  # mouse picks Fácil
    assert game.ctx.save.mode == FACIL.key and isinstance(top(game), TitleScene)

    key(game, pygame.K_UP)
    key(game, pygame.K_UP)
    key(game, pygame.K_RETURN, 60)  # JOGAR
    race = top(game)
    assert isinstance(race, RaceScene) and race.phase is Phase.COUNTDOWN
    until(game, lambda: race.phase is Phase.RACING, 5)
    pygame.event.post(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_UP, mod=0, unicode="", scancode=0))
    key(game, pygame.K_LEFT, 30)
    key(game, pygame.K_RIGHT, 30)
    frames(game, 60)
    assert race.world.player.y < 560, "holding up moves the car up"
    key(game, pygame.K_m)  # mute toggles and persists
    assert game.ctx.save.muted is True
    key(game, pygame.K_F11)  # fullscreen toggle must not crash headless

    key(game, pygame.K_ESCAPE)
    assert isinstance(top(game), PauseScene)
    frames(game, 120)
    key(game, pygame.K_ESCAPE)
    assert top(game) is race
    key(game, pygame.K_p)
    key(game, pygame.K_DOWN)
    key(game, pygame.K_RETURN, 60)  # Reiniciar
    race2 = top(game)
    assert isinstance(race2, RaceScene) and race2 is not race
    until(game, lambda: race2.phase is Phase.RACING, 5)
    frames(game, 120)
    key(game, pygame.K_r)  # give up
    results = top(game)
    assert isinstance(results, ResultsScene) and results.stats.outcome is Outcome.GAVE_UP
    frames(game, 120)
    key(game, pygame.K_RETURN, 60)  # Jogar de novo
    assert isinstance(top(game), RaceScene)
    key(game, pygame.K_ESCAPE)
    key(game, pygame.K_DOWN)
    key(game, pygame.K_DOWN)
    key(game, pygame.K_RETURN, 60)  # Menu
    assert isinstance(top(game), TitleScene)
    key(game, pygame.K_ESCAPE)  # focuses SAIR
    key(game, pygame.K_RETURN)
    assert not game.running


def test_race_until_crash(game):
    game.ctx.save.mode = NORMAL.key
    game.time_scale = 4.0
    game.scenes.switch(RaceScene(game.ctx), Transition.NONE)
    until(game, lambda: isinstance(top(game), ResultsScene), 120)
    stats = top(game).stats
    assert stats.outcome is Outcome.CRASH and stats.seconds > 0
    assert stats.new_record and game.ctx.save.best[NORMAL.key] == stats.score.total > 0
    frames(game, 120)


def test_race_until_win(game):
    game.ctx.save.mode = FACIL.key
    game.ctx.autopilot = True
    game.time_scale = 20.0
    game.scenes.switch(RaceScene(game.ctx), Transition.NONE)
    until(game, lambda: isinstance(top(game), RaceScene) and top(game).phase is Phase.WON, 20)
    until(game, lambda: isinstance(top(game), ResultsScene), 10)
    stats = top(game).stats
    assert stats.outcome is Outcome.WIN and stats.seconds == FACIL.win_s
    assert game.ctx.save.best_time[FACIL.key] == FACIL.win_s
    assert stats.score.coins > 0
