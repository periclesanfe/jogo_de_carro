"""Boot the real Game headless and drive every scene with scripted input."""

import pygame
import pytest

from jogo_de_carro.app import Game
from jogo_de_carro.save import load
from jogo_de_carro.scenes import race, results
from jogo_de_carro.scenes.base import Transition
from jogo_de_carro.scenes.difficulty import DifficultyScene, card_rect
from jogo_de_carro.scenes.garage import ARROWS, TABS, GarageScene
from jogo_de_carro.scenes.pause import PauseScene
from jogo_de_carro.scenes.race import SHIELD_BOX, Outcome, Phase, RaceScene
from jogo_de_carro.scenes.results import ResultsScene
from jogo_de_carro.scenes.title import TitleScene
from jogo_de_carro.scenes.versus import VersusScene
from jogo_de_carro.settings import (
    FACIL,
    FIXED_DT,
    FLAME,
    GOLD,
    HEIGHT,
    LANE_CENTERS,
    NORMAL,
    PLAYER_Y,
    POWERS,
    PROTECT,
    PX_PER_METER,
    START_LANE,
    WHITE,
    WIDTH,
    Item,
)
from jogo_de_carro.world.player import GRACE, Player
from jogo_de_carro.world.road import BIOMES, TILE_H
from jogo_de_carro.world.world import EventKind, WorldEvent

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
    scene = RaceScene(game.ctx)
    game.scenes.switch(scene, Transition.NONE)
    until(game, lambda: scene.phase is Phase.CRASHED, 120)
    road = scene.world.road
    road.px = 1000 * PX_PER_METER - 2  # the car is 2 px short of the Deserto
    until(game, lambda: isinstance(top(game), ResultsScene), 120)
    assert road.biome(PLAYER_Y) == 1 and scene.biome == 0  # the slow-motion rolled in: the race did not
    stats = top(game).stats
    assert stats.outcome is Outcome.CRASH and stats.seconds > 0
    assert stats.new_record and game.ctx.save.best[NORMAL.key] == stats.score.total > 0
    frames(game, 120)


def test_race_until_win(game, monkeypatch):
    game.ctx.save.mode = FACIL.key
    game.ctx.autopilot = True
    game.time_scale = 20.0
    scene = RaceScene(game.ctx)
    game.scenes.switch(scene, Transition.NONE)
    until(game, lambda: isinstance(top(game), RaceScene) and top(game).phase is Phase.WON, 20)
    until(game, lambda: isinstance(top(game), ResultsScene), 10)
    stats = top(game).stats
    assert stats.outcome is Outcome.WIN and stats.seconds == FACIL.win_s
    assert game.ctx.save.best_time[FACIL.key] == FACIL.win_s
    assert stats.score.coins > 0
    assert stats.unlocked == (1, 2) and game.ctx.save.best_m == int(stats.score.meters)  # 2.6 km
    assert scene.biome == 2  # the banner named each biome on the way
    drawn: list[str] = []
    monkeypatch.setattr(results, "blit_text", lambda surface, label, *a, **k: drawn.append(label))
    frames(game, 1)
    assert "Cenários liberados: DESERTO, NEVE" in drawn


def test_the_garage_previews_every_scenery_and_picks_a_reached_one(game):
    """DOWN (or its tab) switches to CENÁRIOS: each biome restarts the road behind as its preview, and ENTER
    picks one a race has reached; races then start there, both halves of a versus too."""
    save = game.ctx.save
    save.best_m = 1500  # Deserto, not Neve
    scene = GarageScene(game.ctx)
    game.scenes.switch(scene, Transition.NONE)
    road = game.ctx.backdrop.world.road
    key(game, pygame.K_DOWN)
    key(game, pygame.K_RIGHT)
    key(game, pygame.K_RIGHT, 1)
    assert scene.scenery and road.start == 2 and scene.target == 0  # the cars stay put
    neve = {sprite for sprite, *_ in BIOMES[2].props} | {"lamp"}
    assert {p.sprite for p in road.props} <= neve  # planted anew: no cactus of the Deserto left
    assert scene.info() == "Chegue a 2 km numa corrida para liberar · seu recorde: 1,5 km"
    key(game, pygame.K_RETURN)
    assert top(game) is scene and save.biome == 0  # previewed, not chosen
    key(game, pygame.K_UP)
    assert not scene.scenery
    click(game, TABS[1].center)
    assert scene.scenery and road.start == 2
    key(game, pygame.K_LEFT)
    assert road.start == 1 and scene.info() == "Liberado"
    game.time_scale = 20.0
    frames(game, 120)  # 40 s: the preview drives on past its km...
    game.time_scale = 1.0
    deserto = {sprite for sprite, *_ in BIOMES[1].props} | {"lamp"}
    assert {road.biome(y) for y in (-TILE_H, PLAYER_Y, HEIGHT)} == {1}  # ...and stays in the Deserto
    assert {p.sprite for p in road.props} <= deserto
    key(game, pygame.K_RETURN, 60)
    assert isinstance(top(game), TitleScene) and save.biome == 1 == load(game.ctx.save_path).biome
    race, versus = RaceScene(game.ctx), VersusScene(game.ctx, "medio")
    assert [r.start for r in (race.world.road, versus.world.road, versus.rival.world.road)] == [1, 1, 1]


def test_the_hud_reads_each_power(game, monkeypatch):
    """Each power's panel has its label, colour and icon, and a bar that blinks out in the last 2 s; the extra
    life is a heart beside it (or alone); the speedometer reads the road's speed. A pickup pops the power's
    name; a hit a power or the life took shakes and flashes, with the shield's sounds."""
    texts, icons, sounds = [], [], []
    monkeypatch.setattr(
        race, "blit_text", lambda surface, s, size, at, colour=WHITE, **k: texts.append((s, colour))
    )
    frame = game.ctx.assets.frame
    monkeypatch.setattr(game.ctx.assets, "frame", lambda name, i=0: (icons.append(name), frame(name, i))[1])
    monkeypatch.setattr(game.ctx.audio, "play", lambda name, *a: sounds.append(name))
    scene = RaceScene(game.ctx)
    player, surface = scene.world.player, pygame.Surface((WIDTH, HEIGHT))
    x, y = SHIELD_BOX.x + 72, SHIELD_BOX.centery + 10  # the bar's left end, mid-height
    for item, power in POWERS.items():
        if item is Item.LIFE:
            continue
        player.power, player.power_t = item, power.seconds / 2  # 2 s or more: steady
        scene._draw_power(surface)
        assert (power.label, power.colour) in texts and icons[-1] == item.value
        assert surface.get_at((x + 35, y))[:3] == power.colour != surface.get_at((x + 105, y))[:3]  # half
        player.power_t, scene.clock = 1.0, 1 / 8
        assert scene._power_left() == 0, "the last 2 s: it blinks out..."
        scene.clock = 0.0
        assert scene._power_left() == 1.0 / power.seconds, "...and back"
    player.lives = 1
    heart = (SHIELD_BOX.right + 8 + SHIELD_BOX.height // 2, SHIELD_BOX.centery)  # beside the power's panel
    surface.fill((0, 0, 0))
    scene._draw_power(surface)
    assert icons[-2:] == ["life", player.power.value] and surface.get_at(heart)[:3] != (0, 0, 0)
    player.power = None
    icons.clear()
    surface.fill((0, 0, 0))
    scene._draw_power(surface)
    assert icons == ["life"] and surface.get_at(heart)[:3] == (0, 0, 0)  # in its place

    scene.world.speed = 400.0  # 100 km/h
    for item, kmh in ((Item.TURBO, "150"), (Item.SLOW, "50"), (Item.STAR, "100")):
        player.power = item
        texts.clear()
        scene._draw_speedometer(surface)
        assert texts[0] == (kmh, WHITE)

    for item, power in POWERS.items():
        scene._react([(WorldEvent(EventKind.POWER_UP, 640, 500, item), 0)])
        popup = scene.popups[-1]
        assert (popup.label, popup.color, sounds[-1]) == (f"{power.label}!", power.colour, "shield_up")
    for kind in (EventKind.SHIELD_BREAK, EventKind.SMASH, EventKind.LIFE_LOST):
        scene.trauma = scene.flash = 0.0
        scene.popups.clear()
        scene._react([(WorldEvent(kind, 640, 500), 0)])
        assert scene.trauma > 0 and scene.flash > 0 and sounds[-1] == "shield_break"
        assert [p.label for p in scene.popups] == (["-1 VIDA"] if kind is EventKind.LIFE_LOST else [])


def test_each_power_shows_on_the_car(game):
    """FANTASMA washes the car out, ESTRELA rings it, TURBO lights its exhaust pipes; and the grace that a
    protected car gets inside an obstacle never makes it blink, as the grace after a hit does."""

    def drawn(power: Item | None, grace: float = 0.0) -> pygame.Surface:
        surface = pygame.Surface((WIDTH, HEIGHT))
        Player(game.ctx.assets, "yellow", power=power, power_t=4.0, grace=grace, clock=0.06).draw(surface)
        return surface  # (0.06 s: a blink's off frame)

    def lit(surface: pygame.Surface, colour: tuple[int, int, int]) -> int:
        return pygame.mask.from_threshold(surface, colour, (1, 1, 1, 255)).count()

    plain, centre = drawn(None), (LANE_CENTERS[START_LANE], PLAYER_Y)
    assert drawn(None, GRACE).get_at(centre) != plain.get_at(centre)  # blinked out
    for power in PROTECT:
        steady, floored = (pygame.image.tobytes(drawn(power, grace), "RGB") for grace in (0.0, 2 * FIXED_DT))
        assert steady == floored, power
    assert drawn(Item.GHOST).get_at(centre) != plain.get_at(centre)
    assert lit(drawn(Item.STAR), GOLD) > 500 and lit(drawn(Item.TURBO), FLAME) > 50 and not lit(plain, GOLD)
