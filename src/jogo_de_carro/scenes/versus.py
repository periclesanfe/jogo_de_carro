"""Contra o bot: two roads from one seed side by side, the bot stepped in lockstep, decided by run.verdict."""

import random

import pygame

from ..input import Action
from ..run import Run, Scored, verdict
from ..settings import ACCENT, COMBO_TIME, CYAN, DANGER, FLAME, HEIGHT, MUTED, SHIELD_TIME, WHITE, WIDTH
from ..tween import clamp, out_cubic
from ..ui import Menu, blit_pop, blit_text, clock_text, outlined, panel
from ..world.autopilot import BOT_LEVELS, Bot
from ..world.world import Controls
from .base import Context, MenuScene, Scene, Transition, menu_hint
from .race import Outcome, Phase, RaceScene

BOT_NAMES = {"facil": "FÁCIL", "medio": "MÉDIO", "dificil": "DIFÍCIL"}
BANNERS = {1: ("VITÓRIA!", ACCENT), 0: ("EMPATE!", WHITE), -1: ("VOCÊ PERDEU", DANGER)}
MINE = pygame.Rect(0, 0, WIDTH // 2, HEIGHT)
THEIRS = pygame.Rect(WIDTH // 2, 0, WIDTH // 2, HEIGHT)
SHIFT = -320  # each World draws unchanged but shifted: the road (x 400..880) lands on 80..560 of its half
COLUMN = pygame.Rect(566, 0, 148, HEIGHT)  # the HUD, over the two inner verges (never over a lane)


def mss(seconds: float) -> str:
    return clock_text(seconds).removeprefix("0")


def bar(surface: pygame.Surface, rect: pygame.Rect, k: float, color: tuple[int, int, int]) -> None:
    pygame.draw.rect(surface, (50, 54, 78), rect, border_radius=rect.height // 2)
    fill = rect.copy()
    fill.width = round(rect.width * clamp(k, 0.0, 1.0))
    pygame.draw.rect(surface, color, fill, border_radius=rect.height // 2)


class VersusScene(RaceScene):
    pause_button = pygame.Rect(16, 20, 48, 48)  # on the left verge
    cannons = (-SHIFT, WIDTH // 2 - SHIFT)  # the corners of my half

    def __init__(self, ctx: Context, level: str, seed: int | None = None) -> None:
        skin = "red" if ctx.save.skin != "red" else "blue"  # never the player's car
        super().__init__(ctx, seed, shared_road=True, rival=skin)
        self.level, self.name = level, f"BOT {BOT_NAMES[level]}"
        bot = Bot(BOT_LEVELS[level], random.Random(self.seed ^ 0xB07))
        self.rival = Run(ctx.assets, self.mode.key, skin, self.seed, True, bot, rival=ctx.save.skin)
        self.verdict: int | None = None

    def again(self) -> Scene:
        return VersusScene(self.ctx, self.level)

    # --- the bot, in lockstep ------------------------------------------------------------------------

    def _step(self) -> Scored:
        events = super()._step()
        self.rival.advance(self.run.tick)
        self._decide()
        return events

    def _decide(self) -> None:
        while (v := verdict(self.run, self.rival)) is None and self.run.outcome:  # I stopped: the bot goes on
            self.rival.advance(self.rival.tick + 1)
        self.verdict = v
        if v is not None:
            self.banner = BANNERS[v]
            self.rival.world.invulnerable = True  # a surviving bot only cruises on, for show

    def update(self, dt: float) -> None:
        rival = self.rival
        if self.phase is Phase.COUNTDOWN:
            rival.world.update(dt, Controls())  # standing ticks change nothing
        elif self.verdict is not None and rival.outcome != "crash":
            rival.world.update(dt, rival.driver(rival.world))
        super().update(dt)
        if self.verdict is not None and self.phase is Phase.RACING:  # decided while I drive: it ends here
            self._win()

    def _win(self, celebrate: bool = True) -> None:
        super()._win(self.verdict == 1)
        self.world.running = False  # the clock stops where the race was decided

    def finish(self, outcome: Outcome) -> None:
        from .results import RaceStats, ResultsScene

        if self.verdict is None and self.rival.outcome:  # the bot crashed on my last tick: I outlasted it
            self._step()
        self.run.stop("giveup")
        self._decide()
        rival = self.rival
        line = f"{self.name}: {rival.score.total} pontos"
        if rival.outcome == "crash":
            line += f" · bateu aos {mss(rival.seconds)}"
        stats = RaceStats(
            outcome,
            self.mode,
            self.run.seconds,
            self.score,
            False,
            self.best,
            self.verdict,
            self.reason(),
            line,
        )
        self.ctx.scenes.switch(ResultsScene(self.ctx, stats, self.snapshot(), self.again), Transition.NONE)

    def reason(self) -> str:
        me, bot, v = self.run, self.rival, self.verdict
        assert v is not None
        if me.tick != bot.tick or (me.outcome == "win") != (bot.outcome == "win"):  # who lasted longer
            loser, who = (me, "Você") if v < 0 else (bot, "O bot")
            return f"{who} {'desistiu' if loser.outcome == 'giveup' else 'bateu'} aos {mss(loser.seconds)}"
        if me.outcome == "win":
            both = "Os dois chegaram ao fim"
        else:
            both = f"Os dois {'bateram' if me.outcome == 'crash' else 'pararam'} aos {mss(me.seconds)}"
        return (
            both + {1: ": você fez mais pontos", 0: " com os mesmos pontos", -1: ": o bot fez mais pontos"}[v]
        )

    # --- drawing -------------------------------------------------------------------------------------

    def _draw_world(self, surface: pygame.Surface, offset: tuple[float, float]) -> None:
        mine, theirs = surface.subsurface(MINE), surface.subsurface(THEIRS)
        shifted = (offset[0] + SHIFT, offset[1])
        self.world.draw(mine, shifted, vignette=False)
        self.rival.world.draw(theirs, (SHIFT, 0), vignette=False)
        if self.rival.outcome == "crash":  # frozen where it crashed, dimmed
            theirs.fill((110, 110, 120), special_flags=pygame.BLEND_RGB_MULT)
            blit_pop(theirs, "BATEU!", 72, DANGER, (THEIRS.width // 2, 440), 1.0, width=4)
        surface.blit(self.world.road.vignette, (0, 0))
        self._draw_juice(mine, shifted, SHIFT)

    def _draw_hud(self, surface: pygame.Surface) -> None:
        score, rival, x, w = self.score, self.rival, COLUMN.x, COLUMN.width
        self._draw_pause(surface)

        box = pygame.Rect(x, 20, w, 92)
        panel(surface, box, alpha=240)
        blit_text(surface, "TEMPO", 22, (x + 12, box.y + 10), MUTED, anchor="topleft", shadow=False)
        goal = f"/ {clock_text(self.run.win_s)}"  # Infinito ends at the versus cap
        blit_text(surface, goal, 22, (box.right - 12, box.y + 10), MUTED, anchor="topright", shadow=False)
        blit_text(surface, clock_text(self.world.elapsed), 48, (box.centerx, box.y + 52), WHITE)
        bar(
            surface,
            pygame.Rect(x + 12, box.bottom - 16, w - 24, 6),
            self.world.elapsed / self.run.win_s,
            self.mode.color,
        )

        box = pygame.Rect(x, 124, w, 186)
        panel(surface, box, alpha=240)
        blit_text(surface, "VOCÊ", 22, (x + 12, box.y + 10), ACCENT, anchor="topleft", shadow=False)
        blit_text(surface, f"{score.total}", 48, (box.right - 12, box.y + 30), WHITE, anchor="topright")
        coin = self.ctx.assets.frame("coin")
        surface.blit(coin, coin.get_rect(midleft=(x + 8, box.y + 96)))
        blit_text(surface, f"x {score.coins}", 26, (x + 50, box.y + 96), ACCENT, anchor="midleft")
        if score.combo >= 2:
            scale = 1 + 0.35 * out_cubic(self.combo_pop)
            blit_pop(
                surface, f"COMBO x{score.combo}", 26, ACCENT, (box.centerx, box.y + 126), scale, peak=1.35
            )
            bar(surface, pygame.Rect(x + 12, box.y + 142, w - 24, 5), score.combo_timer / COMBO_TIME, ACCENT)
        if self.world.player.shield > 0:
            blit_text(surface, "ESCUDO", 22, (x + 12, box.y + 152), CYAN, anchor="topleft", shadow=False)
            bar(
                surface,
                pygame.Rect(x + 12, box.y + 172, w - 24, 6),
                self.world.player.shield / SHIELD_TIME,
                CYAN,
            )

        vs = outlined("VS", 56, FLAME)
        surface.blit(vs, vs.get_rect(center=(COLUMN.centerx, 342)))

        box = pygame.Rect(x, 374, w, 132)
        panel(surface, box, alpha=240)
        blit_text(surface, self.name, 22, (x + 12, box.y + 10), MUTED, anchor="topleft", shadow=False)
        blit_text(surface, f"{rival.score.total}", 48, (box.right - 12, box.y + 30), WHITE, anchor="topright")
        if rival.outcome == "crash":
            pill = pygame.Rect(x + 10, box.bottom - 38, w - 20, 28)
            panel(surface, pill, DANGER, 255, radius=14)
            blit_text(surface, f"BATEU {mss(rival.seconds)}", 22, pill.center, WHITE, shadow=False)

        self._draw_speedometer(surface, (COLUMN.centerx, HEIGHT - 84), 58)


class BotScene(MenuScene):
    """Picks the bot's level; the race is in the current mode."""

    dim, blur = 30, True

    def __init__(self, ctx: Context) -> None:
        super().__init__(ctx)
        self.menu = Menu(list(BOT_NAMES.values()), (WIDTH // 2, 380), ctx.audio, index=1)

    def handle(self, action: Action | None, event: pygame.Event) -> None:
        if action is Action.BACK:
            from .title import TitleScene

            self.ctx.audio.play("ui_back")
            self.ctx.scenes.switch(TitleScene(self.ctx, focus=3), Transition.SLIDE_RIGHT)
            return
        choice = self.menu.handle(action, event)
        if choice is not None:
            self.ctx.audio.play("ui_select")
            self.ctx.scenes.switch(VersusScene(self.ctx, list(BOT_NAMES)[choice]), Transition.FADE)

    def update(self, dt: float) -> None:
        super().update(dt)
        self.menu.update(dt)

    def draw_ui(self, surface: pygame.Surface) -> None:
        heading = outlined("CONTRA O BOT", 80, WHITE, width=4)
        surface.blit(heading, heading.get_rect(center=(WIDTH // 2, 74)))
        line = f"Mesma estrada no modo {self.ctx.mode.name}: quem durar mais vence"
        blit_text(surface, line, 28, (WIDTH // 2, 126), MUTED)
        self.menu.draw(surface)
        blit_text(surface, menu_hint(self.ctx), 24, (WIDTH // 2, HEIGHT - 40), MUTED)
