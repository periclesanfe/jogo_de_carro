"""Contra o bot: the bot runs in lockstep on the same road, run.verdict ends the race, menus lead to it."""

import platform
import random
from types import SimpleNamespace

import pygame
import pytest

from jogo_de_carro.app import Game
from jogo_de_carro.input import Action
from jogo_de_carro.run import Run, verdict
from jogo_de_carro.scenes import results, title
from jogo_de_carro.scenes.base import Transition
from jogo_de_carro.scenes.pause import PauseScene
from jogo_de_carro.scenes.race import Outcome, Phase
from jogo_de_carro.scenes.results import RaceStats, ResultsScene
from jogo_de_carro.scenes.title import TitleScene
from jogo_de_carro.scenes.versus import BotScene, VersusScene
from jogo_de_carro.settings import DANGER, FIXED_DT, HEIGHT, NORMAL, WIDTH, Item
from jogo_de_carro.world.autopilot import BOT_LEVELS, Bot
from jogo_de_carro.world.scoring import Score
from jogo_de_carro.world.world import Controls

FRAME = 1 / 60


@pytest.fixture
def game(tmp_path):
    return Game(save_path=tmp_path / "save.json", seed=3)


def key(game: Game, k: int, wait: int = 20) -> None:
    pygame.event.post(pygame.event.Event(pygame.KEYDOWN, key=k, mod=0, unicode="", scancode=0))
    pygame.event.post(pygame.event.Event(pygame.KEYUP, key=k, mod=0, unicode="", scancode=0))
    for _ in range(wait):
        game.step(FRAME)


def until(game: Game, condition, seconds: float) -> None:
    for _ in range(int(seconds / FRAME)):
        if condition():
            return
        game.step(FRAME)
    raise AssertionError(f"condition not met within {seconds}s (top scene: {game.scenes.top})")


def versus(game: Game, level: str, seed: int, mode: str, autopilot: bool) -> tuple[VersusScene, list, list]:
    """Play a whole versus at 20x (drawing every frame); returns the scene and both worlds' placements."""
    game.ctx.save.mode, game.ctx.autopilot, game.time_scale = mode, autopilot, 20.0
    scene = VersusScene(game.ctx, level, seed)
    placed: tuple[list, list] = ([], [])
    for world, out in zip((scene.world, scene.rival.world), placed, strict=True):
        world._spawn = lambda p, out=out, spawn=world._spawn: (out.append(p), spawn(p))
    game.scenes.switch(scene, Transition.NONE)
    until(game, lambda: isinstance(game.scenes.top, ResultsScene), 400)
    assert game.scenes.top.stats.verdict == scene.verdict is not None
    return scene, *placed


@pytest.mark.parametrize("level", list(BOT_LEVELS))
def test_each_bot_level_reaches_the_same_verdict_on_the_same_road(game, level):
    def play() -> tuple:
        scene, mine, theirs = versus(game, level, seed=11, mode="facil", autopilot=True)
        n = min(len(mine), len(theirs))
        assert n > 30 and mine[:n] == theirs[:n], "both drivers see the same road"
        me, bot = scene.run, scene.rival
        alone = Run(
            game.ctx.assets, "facil", bot.skin, 11, True, Bot(BOT_LEVELS[level], random.Random(11 ^ 0xB07))
        )
        alone.advance(bot.tick)
        assert (alone.outcome, alone.tick, alone.score) == (bot.outcome, bot.tick, bot.score), (
            "lockstep == headless"
        )
        assert bot.skin != me.skin
        return scene.verdict, me.tick, me.score.total, bot.tick, bot.outcome, bot.score.total, scene.reason()

    assert play() == play()


def test_the_bot_crashing_first_wins_without_driving_on(game):
    scene, _, _ = versus(game, "facil", seed=4, mode="normal", autopilot=True)
    stats = game.scenes.top.stats
    assert scene.verdict == 1 and stats.won and scene.phase is Phase.WON and scene.banner[0] == "VITÓRIA!"
    assert scene.rival.outcome == "crash" and scene.run.tick == scene.rival.tick + 1  # stopped the next tick
    assert stats.reason.startswith("O bot bateu aos ") and "bateu aos" in stats.rival


def test_giving_up_right_after_the_bot_crashed_still_wins(game):
    game.ctx.save.mode, game.ctx.autopilot = "normal", True
    scene = VersusScene(game.ctx, "facil", 4)  # the bot crashes first, as above
    game.scenes.switch(scene, Transition.NONE)
    while not scene.rival.outcome:
        scene.update(FIXED_DT)
    assert scene.verdict is None and scene.run.tick == scene.rival.tick  # open until my next tick
    key(game, pygame.K_r, 40)  # R before that tick
    stats = game.scenes.top.stats
    assert stats.verdict == 1 and stats.reason.startswith("O bot bateu aos ")
    assert scene.run.tick == scene.rival.tick + 1


@pytest.mark.parametrize("skin", ["yellow", "red"])
def test_traffic_wears_the_same_colours_in_both_halves(game, skin):
    game.ctx.save.skin = skin
    scene = VersusScene(game.ctx, "medio", 3)
    seen = []
    for world in (scene.world, scene.rival.world):
        world.invulnerable = True
        sprites, spawn = [o.sprite for o in world.obstacles], world._spawn

        def record(p, world=world, sprites=sprites, spawn=spawn) -> None:
            n = len(world.obstacles)
            spawn(p)
            sprites += [o.sprite for o in world.obstacles[n:]]

        world._spawn = record
        seen.append(sprites)
    for tick in range(1, 60 * 120):
        scene.run.step(Controls(), False)
        scene.rival.advance(tick)
    mine, theirs = seen
    n = min(len(mine), len(theirs))
    assert n > 30 and mine[:n] == theirs[:n]
    assert not {f"car_{skin}", f"car_{scene.rival.skin}"} & set(mine + theirs), "no twin of either car"


def test_crashing_first_loses(game):
    scene, _, _ = versus(game, "dificil", seed=4, mode="normal", autopilot=False)  # nobody steers: a crash
    stats = game.scenes.top.stats
    assert scene.verdict == -1 and not stats.won and scene.banner[0] == "VOCÊ PERDEU"
    assert scene.run.outcome == "crash" and scene.rival.tick == scene.run.tick + 1
    assert stats.outcome is Outcome.CRASH and stats.reason.startswith("Você bateu aos ")
    assert not game.ctx.save.best, "a versus sets no solo records"


def test_the_card_tells_the_verdict_in_real_time(game):
    """I held TURBO and the bot DEVAGAR: my world's clock ran 2 s ahead and its 2 s behind. The verdict reads
    ticks, and so does every time that explains it: the reason, the rival's line and pill, and my TEMPO."""
    scene = VersusScene(game.ctx, "medio", 3)
    me, bot = scene.run, scene.rival
    me.world.invulnerable = bot.world.invulnerable = True  # the crashes are set below
    me.world.player.power, me.world.player.power_t = Item.TURBO, 4.0
    bot.world.player.power, bot.world.player.power_t = Item.SLOW, 4.0
    for tick in range(960):
        if tick < 900:
            me.step(Controls(), False)
        bot.step(Controls(), False)
    me.outcome = bot.outcome = "crash"  # I at 7.5 s (9.5 s on my clock), the bot at 8 s (6 s on its)
    scene.verdict = verdict(me, bot)
    assert scene.verdict == -1 and bot.seconds < me.seconds
    assert (scene.reason(), scene.state()) == ("Você bateu aos 0:07", ("BATEU 0:08", DANGER))
    assert scene.line().endswith("bateu aos 0:08")
    scene._results(Outcome.CRASH)
    assert game.scenes.top.stats.seconds == 900 * FIXED_DT
    me.outcome = bot.outcome = "win"  # both at the end, on different ticks: the points decide
    scene.verdict = verdict(me, bot)
    assert scene.reason().startswith("Os dois chegaram ao fim")


def test_my_card_shows_my_power_and_the_rival_only_its_car(game, monkeypatch):
    drawn, icons = [], []
    monkeypatch.setattr("jogo_de_carro.scenes.versus.blit_text", lambda surface, s, *a, **k: drawn.append(s))
    frame = game.ctx.assets.frame
    monkeypatch.setattr(game.ctx.assets, "frame", lambda name, i=0: (icons.append(name), frame(name, i))[1])
    scene = VersusScene(game.ctx, "medio", 3)
    me, it = scene.world.player, scene.rival.world.player
    me.power, me.power_t, me.lives = Item.STAR, 3.0, 1
    it.power, it.power_t = Item.GHOST, 3.0
    scene.draw(game.screen)
    assert "ESTRELA" in drawn and "FANTASMA" not in drawn and "life" in icons


def test_menus_lead_to_the_bot_and_restarts_keep_its_level(game):
    until(game, lambda: not game.scenes.busy, 2)  # the title fades in
    for _ in range(3):
        key(game, pygame.K_DOWN)
    key(game, pygame.K_RETURN, 60)  # CONTRA O BOT
    assert isinstance(game.scenes.top, BotScene)
    key(game, pygame.K_DOWN)  # from MÉDIO to DIFÍCIL
    key(game, pygame.K_RETURN, 60)
    race = game.scenes.top
    assert isinstance(race, VersusScene) and (race.level, race.mode) == ("dificil", game.ctx.mode)

    until(game, lambda: race.phase is Phase.RACING, 5)
    key(game, pygame.K_ESCAPE)
    assert isinstance(game.scenes.top, PauseScene)
    key(game, pygame.K_DOWN)
    key(game, pygame.K_RETURN, 60)  # REINICIAR
    again = game.scenes.top
    assert isinstance(again, VersusScene) and again is not race and again.level == "dificil"

    until(game, lambda: again.phase is Phase.RACING, 5)
    key(game, pygame.K_r, 40)  # give up: the bot drives one more tick and wins (results take keys at 0.4 s)
    stats = game.scenes.top.stats
    assert stats.verdict == -1 and stats.reason.startswith("Você desistiu aos ")
    key(game, pygame.K_RETURN, 60)  # JOGAR DE NOVO
    assert isinstance(game.scenes.top, VersusScene) and game.scenes.top.level == "dificil"

    key(game, pygame.K_ESCAPE)
    key(game, pygame.K_DOWN)
    key(game, pygame.K_DOWN)
    key(game, pygame.K_RETURN, 60)  # MENU
    assert isinstance(game.scenes.top, TitleScene)


def test_the_web_build_has_site_instead_of_sair(game, monkeypatch):
    location = SimpleNamespace(href="/jogo/x/")
    monkeypatch.setattr(platform, "window", SimpleNamespace(location=location), raising=False)
    monkeypatch.setattr(title, "WEB", True)
    monkeypatch.setattr(results, "WEB", True)
    menu = TitleScene(game.ctx)
    assert list(menu.menu.labels) == ["JOGAR", "SKIN", "DIFICULDADE", "CONTRA O BOT", "SITE"]
    enter = pygame.event.Event(pygame.KEYDOWN, key=pygame.K_RETURN)
    menu.handle(Action.BACK, enter)  # Esc moves to SITE, as it moves to SAIR on the desktop
    menu.handle(Action.CONFIRM, enter)
    assert location.href == "/"  # the site's home page

    location.href = "/jogo/x/"
    stats = RaceStats(Outcome.CRASH, NORMAL, 1.0, Score(), False, 0)
    scene = ResultsScene(game.ctx, stats, pygame.Surface((WIDTH, HEIGHT)), lambda: TitleScene(game.ctx))
    assert list(scene.menu.labels) == ["JOGAR DE NOVO", "MENU", "SITE"]
    scene.t, scene.menu.index = 1.0, 2
    scene.handle(Action.CONFIRM, enter)
    assert location.href == "/"
