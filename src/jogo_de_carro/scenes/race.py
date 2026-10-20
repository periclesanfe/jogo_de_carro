"""Gameplay: countdown, racing with HUD and juice, crash slow-motion, victory lap."""

import json
import math
import os
from dataclasses import dataclass
from enum import Enum, auto
from pathlib import Path

import pygame

from ..input import Action
from ..run import Run, Scored
from ..settings import (
    ACCENT,
    COMBO_TIME,
    CYAN,
    DANGER,
    FLAME,
    HEIGHT,
    MUTED,
    NEAR_MISS_POINTS,
    SHIELD_TIME,
    WHITE,
    WIDTH,
)
from ..tween import clamp, out_back, out_cubic
from ..ui import blit_pop, blit_text, clock_text, faded, glow, panel
from ..world.autopilot import autopilot
from ..world.world import Controls, EventKind
from .base import Context, Scene, Transition

COUNT_STEP = 0.75  # seconds per countdown number
SLOWMO_TIME, SLOWMO_SCALE = 0.35, 0.25
CRASH_TO_RESULTS = 1.7
WIN_CRUISE = 0.6  # the victory lap cruises a moment before zooming off the top
WIN_TO_RESULTS = 2.0
HINT_TIME = 4.5  # the controls card shows from the countdown until this long after "JÁ!"
PAUSE_BUTTON = pygame.Rect(336, 20, 48, 48)
SHIELD_BOX = pygame.Rect(24, HEIGHT - 84, 230, 60)
KEY_HINTS = (
    ("SETAS / A D", "trocar de faixa"),
    ("W / S", "subir e descer"),
    ("segure W", "+15% de pontos"),
    ("ESC / R", "pausar / desistir"),
)
PAD_HINTS = (
    ("ESQ. / DIR.", "trocar de faixa"),
    ("CIMA / BAIXO", "subir e descer"),
    ("segure CIMA", "+15% de pontos"),
    ("START", "pausar"),
)
COUNT_COLORS = (DANGER, FLAME, ACCENT)
GO_COLOR = (99, 199, 77)


class Phase(Enum):
    COUNTDOWN = auto()
    RACING = auto()
    CRASHED = auto()
    WON = auto()


class Outcome(Enum):
    CRASH = auto()
    WIN = auto()
    GAVE_UP = auto()


@dataclass
class Popup:
    label: str
    x: float
    y: float
    color: tuple[int, int, int]
    size: int = 34
    ttl: float = 0.9
    life: float = 0.0
    follow: bool = False  # keeps beside the car (coin totals), so a lane change never drags it over it


COIN_POPUP_DX = 66


class RaceScene(Scene):
    def __init__(self, ctx: Context, seed: int | None = None, shared_road: bool = False) -> None:
        super().__init__(ctx)
        self.mode = ctx.mode
        self.seed = ctx.rng.getrandbits(53) if seed is None else seed  # 53 bits survive JSON in a browser
        self.run = Run(ctx.assets, self.mode.key, ctx.save.skin, self.seed, shared_road)
        self.world, self.score = self.run.world, self.run.score
        self.best = ctx.save.best.get(self.mode.key, 0)
        self.phase = Phase.COUNTDOWN
        self.phase_t = 0.0
        self.beeps = 0
        self.steer: list[int] = []
        self.popups: list[Popup] = []
        self.coin_streak: tuple[Popup, int] | None = None
        self.trauma = 0.0
        self.flash = 0.0
        self.impact: tuple[float, float] | None = None
        self.clock = 0.0
        self.combo_pop = 0.0
        self.pilot = autopilot  # who drives when ctx.autopilot is on (the demo swaps in a show-off)
        self.piloted = False  # the pilot drove some ticks, so the input log does not replay this race

    def enter(self) -> None:
        self.ctx.audio.stop_music(400)
        self.ctx.input.release_all()

    # --- input ---------------------------------------------------------------------------------------

    def handle(self, action: Action | None, event: pygame.Event) -> None:
        if self.phase in (Phase.CRASHED, Phase.WON):
            return
        pause = action in (Action.BACK, Action.PAUSE) or event.type == pygame.WINDOWFOCUSLOST
        if (
            event.type == pygame.MOUSEBUTTONDOWN
            and event.button == 1
            and PAUSE_BUTTON.collidepoint(event.pos)
        ):
            pause = True
        if pause:
            self.open_pause()
        elif action is Action.GIVE_UP and self.phase is Phase.RACING:
            self.finish(Outcome.GAVE_UP)
        elif action in (Action.LEFT, Action.RIGHT) and self.phase is Phase.RACING:
            self.steer.append(-1 if action is Action.LEFT else 1)

    def open_pause(self) -> None:
        from .pause import PauseScene

        self.ctx.audio.play("ui_back")
        self.ctx.scenes.push(PauseScene(self.ctx, self.snapshot()))

    def resume(self) -> None:
        self.ctx.audio.pause_music(False)
        self.ctx.input.release_all()
        self.steer.clear()

    # --- update --------------------------------------------------------------------------------------

    def update(self, dt: float) -> None:
        self.clock += dt
        self.phase_t += dt
        self.trauma = max(0.0, self.trauma - 1.5 * dt)
        self.flash = max(0.0, self.flash - 6.0 * dt)
        self.combo_pop = max(0.0, self.combo_pop - 3.0 * dt)
        world_dt = dt
        if self.phase is Phase.COUNTDOWN:
            self._countdown()
        elif self.phase is Phase.CRASHED:
            k = min(1.0, max(0.0, (self.phase_t - SLOWMO_TIME) / 0.3))
            world_dt = dt * (SLOWMO_SCALE + (1 - SLOWMO_SCALE) * k)
            if self.phase_t >= CRASH_TO_RESULTS:
                self.finish(Outcome.CRASH)
                return
        elif self.phase is Phase.WON:
            lap = self.phase_t - WIN_CRUISE
            if lap > 0:  # victory lap: zoom off the top of the screen
                self.world.player.y -= (200 + 1400 * lap) * dt
            if self.phase_t >= WIN_TO_RESULTS:
                self.finish(Outcome.WIN)
                return

        if self.phase is Phase.RACING:
            self._react(self._step())
            if self.run.outcome == "win":
                self._win()
            elif self.run.known and self.run.outcome is None and self.run.tick == self.run.known:
                self.finish(Outcome.GAVE_UP)  # a replayed log ends here: its player gave up
                return
        else:  # the countdown, the crash slow-motion and the victory lap: nothing scores
            self.world.update(world_dt, Controls())
        for popup in self.popups:
            popup.life += dt
            popup.y -= 70 * dt
            if popup.follow:
                popup.x = self.world.player.x + COIN_POPUP_DX
        self.popups = [p for p in self.popups if p.life < p.ttl]

    def _step(self) -> Scored:
        if self.ctx.autopilot:
            self.piloted = True
            return self.run.step(self.pilot(self.world), False)
        if self.run.known:  # a loaded log drives (--replay)
            return self.run.advance(self.run.tick + 1)
        return self.run.play(*self._controls())

    def _controls(self) -> tuple[int, int]:
        """This tick's lane change and held keys (1 = up, 2 = down), as the input log records them."""
        held = self.ctx.input.held
        return self.steer.pop(0) if self.steer else 0, held(Action.UP) | held(Action.DOWN) << 1

    def _countdown(self) -> None:
        step = int(self.phase_t / COUNT_STEP)
        if step >= self.beeps and self.beeps < 4:
            self.beeps += 1
            if step < 3:
                self.ctx.audio.play("countdown")
            else:
                self.ctx.audio.play("go")
                self.ctx.audio.music("race")
                self.phase, self.phase_t = Phase.RACING, 0.0

    def _react(self, events: Scored) -> None:
        """The effects of a tick's events (the Run did the scoring)."""
        audio, player = self.ctx.audio, self.world.player
        for e, points in events:
            if e.kind is EventKind.LANE_CHANGE:
                audio.play("lane_change", 0.5)
            elif e.kind is EventKind.COIN:
                self._coin_popup(points, player.x + COIN_POPUP_DX, player.y)
                audio.play("coin", 0.6)
            elif e.kind is EventKind.NEAR_MISS:
                combo = points // NEAR_MISS_POINTS
                label = f"+{points} QUASE!" + (f" x{combo}" if combo > 1 else "")
                self._popup(label, e.x, e.y - 50, WHITE, 34)
                self.combo_pop = 1.0
                audio.play("near_miss", 0.8)
            elif e.kind is EventKind.SHIELD_UP:
                self._popup("ESCUDO!", e.x, e.y - 30, CYAN, 40)
                audio.play("shield_up")
            elif e.kind is EventKind.SHIELD_BREAK:
                self.trauma = min(1.0, self.trauma + 0.45)
                self.flash, self.impact = 0.35, (e.x, e.y)
                audio.play("shield_break")
            elif e.kind is EventKind.BUMP:
                self.trauma = min(1.0, self.trauma + 0.2)
            elif e.kind is EventKind.CRASH:
                self.phase, self.phase_t = Phase.CRASHED, 0.0
                self.trauma, self.flash, self.impact = 1.0, 0.5, (e.x, e.y)
                audio.play("crash")
                audio.stop_music(900)

    def _coin_popup(self, points: int, x: float, y: float) -> None:
        """Coins collected in quick succession add up in one popup instead of stacking."""
        streak = self.coin_streak
        if streak and streak[0] in self.popups and streak[0].life < 0.45:
            popup, total = streak[0], streak[1] + points
            popup.label, popup.life, popup.x, popup.y = f"+{total}", 0.12, x, y  # stay full size, live on
        else:
            popup, total = Popup(f"+{points}", x, y, ACCENT, 30, 0.7, follow=True), points
            self.popups.append(popup)
        self.coin_streak = (popup, total)

    def _popup(
        self, label: str, x: float, y: float, color: tuple[int, int, int], size: int = 30, ttl: float = 0.9
    ) -> None:
        for other in self.popups:  # two near misses in one dodge: stack the popups instead of overlapping
            if not other.follow and other.life < 0.4 and abs(other.x - x) < 240 and abs(other.y - y) < 40:
                y = other.y - 42
        self.popups.append(Popup(label, x, y, color, size, ttl))

    def _win(self) -> None:
        self.phase, self.phase_t = Phase.WON, 0.0
        self.world.spawner.enabled = False
        self.world.invulnerable = True
        self.world.player.bounded = False
        self.world.particles.confetti(140)
        self.world.particles.cannon(0, HEIGHT, 1)
        self.world.particles.cannon(WIDTH, HEIGHT, -1)
        self.popups.clear()
        self.ctx.audio.music("win", loop=False, fade_ms=0)

    def finish(self, outcome: Outcome) -> None:
        from .results import RaceStats, ResultsScene

        self.run.stop("giveup")  # a crash or a win already ended it
        if (folder := os.environ.get("JOGO_RECORD")) and not (self.piloted or self.run.known):  # nor a replay
            path = Path(folder) / f"{self.mode.key}-{self.seed}.json"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(self.run.log(), separators=(",", ":")), encoding="utf-8")
        seconds = self.run.seconds
        save = self.ctx.save
        record = save.record(self.mode.key, save.skin, self.score.total, seconds)
        self.ctx.persist()
        stats = RaceStats(outcome, self.mode, seconds, self.score, record, self.best)
        self.ctx.scenes.switch(ResultsScene(self.ctx, stats, self.snapshot()), Transition.NONE)

    def snapshot(self) -> pygame.Surface:
        """The current frame without the big centre text, as a backdrop for pause/results."""
        frame = pygame.Surface((WIDTH, HEIGHT))
        self.draw(frame, overlay=False)
        return frame

    # --- drawing -------------------------------------------------------------------------------------

    def draw(self, surface: pygame.Surface, overlay: bool = True) -> None:
        shake = self.trauma**2 * 16
        offset = (
            shake * math.sin(self.clock * 71.0),
            shake * math.cos(self.clock * 53.0 + 1.3),
        )
        self.world.draw(surface, offset)
        for p in self.popups:
            k = p.life / p.ttl
            scale = out_back(min(1.0, p.life / 0.18))
            blit_pop(surface, p.label, p.size, p.color, (p.x, p.y), scale, round(255 * (1 - k**3)))
        if self.flash > 0:  # a short white impact frame around the hit, over a brief global flash
            surface.fill((round(160 * self.flash),) * 3, special_flags=pygame.BLEND_RGB_ADD)
            if self.impact:
                light = glow(150, (255, 244, 214), 255 * min(1.0, self.flash * 2.5))
                at = (round(self.impact[0] + offset[0]), round(self.impact[1] + offset[1]))
                surface.blit(light, light.get_rect(center=at))
        hud = 1.0 if self.phase is not Phase.WON else clamp(1 - (self.phase_t - 0.2) / 0.3, 0.0, 1.0)
        faded(surface, 255 * hud, self._draw_hud)
        if overlay:
            self._draw_overlay_text(surface)

    def _draw_hud(self, surface: pygame.Surface) -> None:
        mode, score = self.mode, self.score
        # time panel (top-left)
        box = pygame.Rect(24, 20, 300, 104)
        panel(surface, box, alpha=225)
        blit_text(surface, "TEMPO", 24, (box.x + 18, box.y + 13), MUTED, anchor="topleft", shadow=False)
        blit_text(
            surface, clock_text(self.world.elapsed), 60, (box.x + 16, box.y + 36), WHITE, anchor="topleft"
        )
        goal = f"/ {clock_text(self.run.win_s)}"  # Infinito ends at the run cap
        blit_text(surface, goal, 28, (box.right - 18, box.y + 54), MUTED, anchor="topright", shadow=False)
        bar = pygame.Rect(box.x + 18, box.bottom - 18, box.width - 36, 6)
        pygame.draw.rect(surface, (50, 54, 78), bar, border_radius=3)
        if mode.win_s:
            fill = bar.copy()
            fill.width = round(bar.width * min(1.0, self.world.elapsed / mode.win_s))
            pygame.draw.rect(surface, mode.color, fill, border_radius=3)
        else:
            blit_text(
                surface, mode.name.upper(), 24, (box.right - 18, box.y + 13), mode.color, anchor="topright"
            )
        # pause button
        panel(surface, PAUSE_BUTTON, alpha=200, radius=12)
        for dx in (-7, 4):
            surface.fill(WHITE, (PAUSE_BUTTON.centerx + dx, PAUSE_BUTTON.centery - 9, 5, 18))

        # score panel (top-right)
        box = pygame.Rect(WIDTH - 324, 20, 300, 104)
        panel(surface, box, alpha=225)
        blit_text(surface, "PONTOS", 24, (box.x + 18, box.y + 13), MUTED, anchor="topleft", shadow=False)
        blit_text(surface, f"{score.total}", 60, (box.right - 16, box.y + 36), WHITE, anchor="topright")
        beat = score.total > self.best > 0
        best_label = "NOVO RECORDE!" if beat else f"RECORDE {self.best}"
        blit_text(
            surface,
            best_label,
            24,
            (box.right - 18, box.y + 13),
            ACCENT if beat else MUTED,
            anchor="topright",
            shadow=False,
        )
        coin = self.ctx.assets.frame("coin")
        surface.blit(coin, coin.get_rect(midleft=(box.x + 16, box.bottom - 22)))
        blit_text(surface, f"x {score.coins}", 26, (box.x + 58, box.bottom - 22), ACCENT, anchor="midleft")

        if score.combo >= 2:
            self._draw_combo(surface)
        shield = self.world.player.shield > 0
        if shield:
            self._draw_shield(surface)
        self._draw_speedometer(surface)
        hints = self._hint_alpha()
        if hints > 0:
            self._draw_hints(surface, hints, bottom=SHIELD_BOX.y - 12 if shield else HEIGHT - 24)

    def _draw_combo(self, surface: pygame.Surface) -> None:
        """A pill hanging under the score panel: the combo and the time left to extend it."""
        score = self.score
        box = pygame.Rect(WIDTH - 324, 132, 300, 44)
        panel(surface, box, alpha=225, radius=22)
        scale = 1 + 0.35 * out_cubic(self.combo_pop)
        label = f"COMBO x{score.combo}"
        blit_pop(surface, label, 32, ACCENT, (box.x + 88, box.centery), scale, peak=1.35)
        bar = pygame.Rect(box.x + 170, box.centery - 4, 112, 8)
        pygame.draw.rect(surface, (50, 54, 78), bar, border_radius=4)
        bar.width = round(bar.width * score.combo_timer / COMBO_TIME)
        pygame.draw.rect(surface, ACCENT, bar, border_radius=4)

    def _draw_shield(self, surface: pygame.Surface) -> None:
        box = SHIELD_BOX
        panel(surface, box, alpha=225)
        icon = self.ctx.assets.frame("shield", int(self.clock * 6))
        surface.blit(icon, icon.get_rect(midleft=(box.x + 10, box.centery)))
        bar = pygame.Rect(box.x + 72, box.centery + 6, 140, 8)
        blit_text(surface, "ESCUDO", 24, (bar.x, box.y + 9), CYAN, anchor="topleft", shadow=False)
        pygame.draw.rect(surface, (40, 60, 80), bar, border_radius=4)
        bar.width = round(bar.width * self.world.player.shield / SHIELD_TIME)
        pygame.draw.rect(surface, CYAN, bar, border_radius=4)

    def _draw_speedometer(self, surface: pygame.Surface) -> None:
        center = (WIDTH - 110, HEIGHT - 96)
        radius = 70
        k = min(1.0, self.world.speed / 1000)
        arc = pygame.Rect(0, 0, radius * 2, radius * 2)
        arc.center = center
        start, sweep = math.radians(-30), math.radians(240)
        pygame.draw.circle(surface, (16, 18, 30), center, radius + 8)
        pygame.draw.arc(surface, (50, 54, 78), arc, start, start + sweep, 8)
        if k > 0:
            color = ACCENT if k < 0.7 else FLAME
            pygame.draw.arc(surface, color, arc, start + sweep * (1 - k), start + sweep, 8)
        blit_text(surface, f"{round(self.world.speed * 0.25)}", 48, (center[0], center[1] + 2), WHITE)
        blit_text(surface, "km/h", 24, (center[0], center[1] + 32), MUTED, shadow=False)
        if self.run.held == 1 and self.phase is Phase.RACING:
            blit_text(surface, "+15%", 26, (center[0], center[1] - 36), ACCENT)

    def _hint_alpha(self) -> float:
        """The controls card fades in with the countdown and out a few seconds into the race."""
        if self.phase is Phase.COUNTDOWN:
            return min(1.0, self.phase_t / 0.3)
        if self.phase is Phase.RACING:
            return clamp(HINT_TIME - self.phase_t, 0.0, 1.0)
        return 0.0

    def _draw_hints(self, surface: pygame.Surface, k: float, bottom: int) -> None:
        lines = PAD_HINTS if self.ctx.input.using_pad else KEY_HINTS
        box = pygame.Rect(24, 0, 330, 16 + len(lines) * 30)
        box.bottom = bottom
        panel(surface, box, alpha=215 * k)
        a = round(255 * k)
        for i, (keys, what) in enumerate(lines):
            y = box.y + 12 + i * 30
            blit_text(surface, keys, 24, (box.x + 18, y), ACCENT, anchor="topleft", shadow=False, alpha=a)
            blit_text(surface, what, 24, (box.x + 162, y), WHITE, anchor="topleft", shadow=False, alpha=a)

    def _draw_overlay_text(self, surface: pygame.Surface) -> None:
        center = (WIDTH // 2, HEIGHT // 2 - 60)
        if self.phase is Phase.COUNTDOWN:
            step = min(2, int(self.phase_t / COUNT_STEP))
            local = self.phase_t - step * COUNT_STEP
            scale = 1.3 - 0.3 * out_back(min(1.0, local / 0.3))
            alpha = round(255 * min(1.0, (COUNT_STEP - local) / 0.15))
            color = COUNT_COLORS[step]
            blit_pop(surface, str(3 - step), 220, color, center, scale, alpha, width=7, peak=1.3)
        elif self.phase is Phase.RACING and self.phase_t < 0.7:
            k = self.phase_t / 0.7  # lands with a small squash, then fades (never grows past its render)
            scale = 1.25 - 0.25 * out_back(min(1.0, self.phase_t / 0.3))
            blit_pop(
                surface, "JÁ!", 220, GO_COLOR, center, scale, round(255 * (1 - k**2)), width=7, peak=1.25
            )
        elif self.phase is Phase.WON:
            scale = out_back(min(1.0, self.phase_t / 0.4))
            alpha = round(255 * clamp((WIN_TO_RESULTS - self.phase_t) / 0.2, 0.0, 1.0))
            blit_pop(surface, "VITÓRIA!", 150, ACCENT, center, scale, alpha, width=6)
        elif self.phase is Phase.CRASHED and self.phase_t > 0.5:
            k = min(1.0, (self.phase_t - 0.5) / 0.3)
            alpha = round(255 * clamp((CRASH_TO_RESULTS - self.phase_t) / 0.2, 0.0, 1.0))
            blit_pop(surface, "BATEU!", 140, DANGER, center, out_back(k), alpha, width=6)
