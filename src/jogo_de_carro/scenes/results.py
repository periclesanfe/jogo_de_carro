"""Game over / victory screen: stats with a count-up, and confetti for a new record or a win."""

import math
import random
from dataclasses import dataclass

import pygame

from ..input import Action
from ..particles import Particles
from ..settings import ACCENT, DANGER, HEIGHT, MUTED, WHITE, WIDTH, Difficulty
from ..tween import out_back, out_cubic
from ..ui import Menu, blit_pop, blit_text, clock_text, faded, panel
from ..world.scoring import Score
from .base import Context, Scene, Transition
from .pause import blurred
from .race import Outcome

COUNT_UP = 1.1  # seconds for the score to count up
CARD = pygame.Rect(0, 0, 860, 630)
CARD.center = (WIDTH // 2, HEIGHT // 2)


@dataclass(frozen=True)
class RaceStats:
    outcome: Outcome
    mode: Difficulty
    seconds: float
    score: Score
    new_record: bool
    previous_best: int

    @property
    def celebrate(self) -> bool:
        """Cannons and fanfare for a win or a beaten record; a first-ever score is only noted."""
        return self.outcome is Outcome.WIN or (self.new_record and self.previous_best > 0)


class ResultsScene(Scene):
    def __init__(self, ctx: Context, stats: RaceStats, frame: pygame.Surface) -> None:
        super().__init__(ctx)
        self.stats = stats
        self.frame = frame
        self.background = blurred(frame)
        self.menu = Menu(
            ["JOGAR DE NOVO", "MENU", "SAIR"],
            (WIDTH // 2, CARD.bottom - 66),
            ctx.audio,
            size=(232, 56),
            gap=24,
            horizontal=True,
        )
        self.particles = Particles(random.Random(ctx.rng.random()))
        self.t = 0.0
        self.celebrated = False

    def enter(self) -> None:
        if self.stats.outcome is not Outcome.WIN:
            self.ctx.audio.music("menu", fade_ms=2500)

    def handle(self, action: Action | None, event: pygame.Event) -> None:
        if self.t < 0.4:
            return
        if action is Action.BACK:
            choice: int | None = 1
        else:
            choice = self.menu.handle(action, event)
        if choice is None:
            return
        self.ctx.audio.play("ui_select")
        if choice == 0:
            from .race import RaceScene

            self.ctx.scenes.switch(RaceScene(self.ctx), Transition.FADE)
        elif choice == 1:
            from .title import TitleScene

            self.ctx.scenes.switch(TitleScene(self.ctx), Transition.FADE)
        else:
            self.ctx.quit()

    def update(self, dt: float) -> None:
        self.t += dt
        self.menu.update(dt)
        self.particles.update(dt, 0.0)
        if self.stats.new_record and not self.celebrated and self.t >= 0.3 + COUNT_UP:
            self.celebrated = True
            if self.stats.celebrate:
                self.ctx.audio.play("record")
                self.particles.confetti(70)
                self.particles.cannon(0, HEIGHT, 1)
                self.particles.cannon(WIDTH, HEIGHT, -1)

    def draw(self, surface: pygame.Surface) -> None:
        k = out_cubic(min(1.0, self.t / 0.35))
        surface.blit(self.frame, (0, 0))
        self.background.set_alpha(round(255 * k))
        surface.blit(self.background, (0, 0))
        self.particles.draw(surface)  # confetti frames the card instead of covering the numbers
        rise = round(60 * (1 - out_back(min(1.0, self.t / 0.45))))
        faded(surface, 255 * k, self._draw_card, (0, rise))  # the buttons rise and fade with the card

    def _draw_card(self, surface: pygame.Surface) -> None:
        stats = self.stats
        won = stats.outcome is Outcome.WIN
        box = CARD
        panel(surface, box, alpha=232, radius=26, border=(60, 64, 92))

        title, color = ("VOCÊ VENCEU!", ACCENT) if won else ("GAME OVER", DANGER)
        blit_pop(
            surface, title, 96, color, (WIDTH // 2, box.y + 76), out_back(min(1.0, self.t / 0.4)), width=5
        )
        subtitle = {
            Outcome.WIN: f"Sobreviveu {clock_text(stats.seconds)} no modo {stats.mode.name}",
            Outcome.CRASH: f"Você bateu no modo {stats.mode.name}",
            Outcome.GAVE_UP: f"Você desistiu no modo {stats.mode.name}",
        }[stats.outcome]
        blit_text(surface, subtitle, 30, (WIDTH // 2, box.y + 140), MUTED)

        score = stats.score
        count = out_cubic(min(1.0, max(0.0, self.t - 0.3) / COUNT_UP))
        rows = (
            ("TEMPO", clock_text(stats.seconds)),
            ("DISTÂNCIA", f"{round(score.meters * count)} m"),
            ("MOEDAS", f"{round(score.coins * count)}"),
            (
                "QUASE-BATIDAS",
                f"{round(score.near_misses * count)}"
                + (f"  (combo máx. x{score.best_combo})" if score.best_combo > 1 else ""),
            ),
        )
        for i, (label, value) in enumerate(rows):
            y = box.y + 196 + i * 40
            blit_text(surface, label, 28, (box.x + 90, y), MUTED, anchor="midleft", shadow=False)
            blit_text(surface, value, 32, (box.right - 90, y), WHITE, anchor="midright")
        pygame.draw.line(surface, (60, 64, 92), (box.x + 80, box.y + 362), (box.right - 80, box.y + 362), 2)
        blit_text(surface, "PONTUAÇÃO", 30, (box.x + 90, box.y + 402), ACCENT, anchor="midleft")
        blit_text(
            surface,
            f"{round(score.total * count)}",
            72,
            (box.right - 90, box.y + 402),
            WHITE,
            anchor="midright",
        )
        self._draw_record(surface, box)
        self.menu.draw(surface)

    def _draw_record(self, surface: pygame.Surface, box: pygame.Rect) -> None:
        stats = self.stats
        y = box.y + 468
        if stats.new_record and self.celebrated:
            if not stats.celebrate:  # the first score in this mode: a record, but nothing to beat yet
                blit_text(surface, f"Primeiro recorde: {stats.score.total}", 28, (WIDTH // 2, y), MUTED)
                return
            pulse = 1 + 0.06 * math.sin(self.t * 8)
            pop = out_back(min(1.0, (self.t - 0.3 - COUNT_UP) / 0.35)) * pulse
            blit_pop(surface, "NOVO RECORDE!", 54, ACCENT, (WIDTH // 2, y), pop, width=4, peak=1.17)
        elif not stats.new_record:
            best = max(stats.previous_best, stats.score.total)
            blit_text(surface, f"Recorde no {stats.mode.name}: {best}", 28, (WIDTH // 2, y), MUTED)
