"""Gameplay: countdown, racing with HUD and juice, crash slow-motion, victory lap; online, the inputs stream
to the server (plan §5), which scores the run itself."""

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
    DANGER,
    FLAME,
    HEIGHT,
    MODE_BY_KEY,
    MUTED,
    NEAR_MISS_POINTS,
    PLAYER_Y,
    POWERS,
    TIME_SCALE,
    WHITE,
    WIDTH,
)
from ..tween import clamp, out_back, out_cubic
from ..ui import blit_pop, blit_text, clock_text, faded, glow, panel
from ..world.autopilot import autopilot
from ..world.road import BIOMES
from ..world.world import Controls, EventKind
from .base import WEB, Context, Scene, Transition
from .online import CHALLENGE_LOST, LOST, NO_COINS, NO_RESULT, VERIFYING, official, paid

COUNT_STEP = 0.75  # seconds per countdown number
SLOWMO_TIME, SLOWMO_SCALE = 0.35, 0.25
CRASH_TO_RESULTS = 1.7
WIN_CRUISE = 0.6  # the victory lap cruises a moment before zooming off the top
WIN_TO_RESULTS = 2.0
HINT_TIME = 4.5  # the controls card shows from the countdown until this long after "JÁ!"
BIOME_S = 1.6  # a new biome's name shows this long
SHIELD_BOX = pygame.Rect(24, HEIGHT - 84, 230, 60)  # the power on; the extra life's heart beside it
BREAKS = (EventKind.SHIELD_BREAK, EventKind.SMASH, EventKind.LIFE_LOST)  # a hit a power took: shake, flash
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
REPORT = 12  # online: the inputs go to the server every this many ticks (10 times a second)
NO_PAUSE = "Sem pausa no online · R desiste"


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
    pause_button = pygame.Rect(336, 20, 48, 48)
    button = "JOGAR DE NOVO"  # the results' first button, which plays again()
    cannons = (0, WIDTH)  # world x of the victory confetti cannons: the screen's bottom corners
    biome_banner = ((200, 170), 255)  # a new biome's name: centre (on the left verge, under TEMPO), alpha

    def __init__(
        self,
        ctx: Context,
        seed: int | None = None,
        shared_road: bool = False,
        rival: str | None = None,
        online: int | None = None,  # the server's match: a ranked run, created at its go
        mode: str | None = None,  # a live race: the match's mode, not the menu's
        skin: str | None = None,  # ...and the car its hello named, which the rival sees
        to: str = "",  # a challenge to this friend: the run they will race against
    ) -> None:
        super().__init__(ctx)
        self.online, self.to = online, to
        if to:
            self.button = "AMIGOS"
        self.realtime = online is not None
        self.official = VERIFYING if online is not None else None  # the server's word on the run
        self.wallet = NO_COINS if WEB and online is None else ""  # ...and what it paid (online.paid)
        self.sent = 0  # run.ev entries sent
        self.reported = online is None  # nothing more goes to the server (fin sent, or it decided)
        self.mode = MODE_BY_KEY[mode] if mode else ctx.mode
        self.seed = ctx.rng.getrandbits(53) if seed is None else seed  # 53 bits survive JSON in a browser
        skin = skin or ctx.save.skin
        self.run = Run(ctx.assets, self.mode.key, skin, self.seed, shared_road, rival=rival)
        self.world, self.score = self.run.world, self.run.score
        self.world.road.restart(ctx.save.biome)  # only a look: never in the Run, its log or the server
        self.biome, self.biome_t = ctx.save.biome, 0.0
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
        self.banner: tuple[str, tuple[int, int, int]] | None = None  # replaces VITÓRIA!/BATEU! (versus)

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
            and self.pause_button.collidepoint(event.pos)
        ):
            pause = True
        if pause and self.realtime:
            self.ctx.toast(NO_PAUSE)
        elif pause:
            self.open_pause()
        elif action is Action.GIVE_UP and self.phase is Phase.RACING:
            self.finish(Outcome.GAVE_UP)
        elif action in (Action.LEFT, Action.RIGHT) and self.phase is Phase.RACING:
            self.steer.append(-1 if action is Action.LEFT else 1)

    def open_pause(self) -> None:
        from .pause import PauseScene

        self.ctx.audio.play("ui_back")
        self.ctx.scenes.push(PauseScene(self.ctx, self.snapshot(), self.again))

    def again(self) -> Scene:
        """A fresh race like this one (new seed), for REINICIAR and JOGAR DE NOVO."""
        from .online import AmigosScene, play

        if self.to:
            return AmigosScene(self.ctx)
        return play(self.ctx) if self.online is not None else RaceScene(self.ctx)

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
            self._report()
            # the car enters a new biome; only while the race counts meters (a crash still rolls on a bit)
            if (biome := self.world.road.biome(PLAYER_Y)) != self.biome:
                self.biome, self.biome_t = biome, BIOME_S
            if self.run.outcome == "win":
                self._win()
            elif self.run.known and self.run.outcome is None and self.run.tick == self.run.known:
                self.finish(Outcome.GAVE_UP)  # a replayed log ends here: its player gave up
                return
        else:  # the countdown, the crash slow-motion and the victory lap: nothing scores
            self.world.update(world_dt, Controls())
        self.biome_t = max(0.0, self.biome_t - dt)
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

    def _report(self) -> None:
        """Online: the inputs not sent yet, every REPORT ticks, and with fin once the run is over."""
        run = self.run
        if self.reported or not (run.outcome or run.tick % REPORT == 0):
            return
        msg: dict = {"t": "in", "m": self.online, "k": run.tick, "ev": run.ev[self.sent :]}
        if run.outcome:
            msg["fin"] = {"outcome": run.outcome, "score": run.score.total}
            self.reported = True
        self.sent = len(run.ev)
        if self.ctx.net:
            self.ctx.net.send(msg)

    def on_net(self, msg: dict) -> None:
        """Online: the server's result, or a closed socket, ends a run that is still on."""
        if self.official != VERIFYING:  # offline, or settled
            return
        racing = self.phase in (Phase.COUNTDOWN, Phase.RACING)
        if msg.get("t") == "result" and msg.get("m") == self.online:
            self.official, why = official(msg, self.mode, self.to), "Corrida encerrada pelo servidor"
            self.wallet = paid(msg)
        elif msg.get("t") == "closed":
            lost = CHALLENGE_LOST if self.to else LOST  # (a challenge: the friend wins it)
            self.official, why = lost if racing else NO_RESULT, "Conexão perdida"
        else:
            return
        self.reported = True
        if racing:
            self.finish(Outcome.GAVE_UP, why)

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
            elif e.kind is EventKind.POWER_UP:
                power = POWERS[e.item]
                self._popup(f"{power.label}!", e.x, e.y - 30, power.colour, 40)
                audio.play("shield_up")
            elif e.kind in BREAKS:
                if e.kind is EventKind.LIFE_LOST:
                    self._popup("-1 VIDA", e.x, e.y - 30, DANGER, 40)
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

    def _win(self, celebrate: bool = True) -> None:
        self.phase, self.phase_t = Phase.WON, 0.0
        self.world.spawner.enabled = False
        self.world.invulnerable = True
        self.world.player.bounded = False
        self.popups.clear()
        if celebrate:  # a versus finished but lost on points gets the lap without the party
            self.world.particles.confetti(140)
            self.world.particles.cannon(self.cannons[0], HEIGHT, 1)
            self.world.particles.cannon(self.cannons[1], HEIGHT, -1)
            self.ctx.audio.music("win", loop=False, fade_ms=0)

    def finish(self, outcome: Outcome, why: str = "") -> None:
        from .results import RaceStats, ResultsScene

        self._stop()
        if (folder := os.environ.get("JOGO_RECORD")) and not (self.piloted or self.run.known):  # nor a replay
            path = Path(folder) / f"{self.mode.key}-{self.seed}.json"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(self.run.log(), separators=(",", ":")), encoding="utf-8")
        seconds = self.run.seconds
        save = self.ctx.save
        # a challenge's run is on the versus road: no record (its road is not the solo road)
        record = not self.run.shared and save.record(self.mode.key, save.skin, self.score.total, seconds)
        unlocked = save.drove(self.score.meters)
        self.ctx.persist()
        stats = RaceStats(
            outcome,
            self.mode,
            seconds,
            self.score,
            record,
            self.best,
            reason=why,
            official=self.official,
            button=self.button,
            to=self.to,
            wallet=self.wallet,
            unlocked=unlocked,
        )
        self.ctx.scenes.switch(ResultsScene(self.ctx, stats, self.snapshot(), self.again), Transition.NONE)

    def _stop(self) -> None:
        """End my run on this tick (a crash or a win already ended it); online, its fin goes out."""
        if not self.reported and self.run.tick % REPORT == 0:  # a give-up on a tick already sent: every
            self.run.play(0, self.run.held)  # message must move k on, so one more tick, with no new input
        self.run.stop("giveup")
        self._report()

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
        self._draw_world(surface, offset)
        hud = 1.0 if self.phase is not Phase.WON else clamp(1 - (self.phase_t - 0.2) / 0.3, 0.0, 1.0)
        faded(surface, 255 * hud, self._draw_hud)
        if self.biome_t:
            self._draw_biome(surface)
        if overlay:
            self._draw_overlay_text(surface)

    def _draw_world(self, surface: pygame.Surface, offset: tuple[float, float]) -> None:
        self.world.draw(surface, offset)
        self._draw_juice(surface, offset)

    def _draw_juice(self, surface: pygame.Surface, offset: tuple[float, float], dx: float = 0) -> None:
        """Popups and the impact flash; ``dx`` moves the popups with a world drawn shifted (versus)."""
        for p in self.popups:
            k = p.life / p.ttl
            scale = out_back(min(1.0, p.life / 0.18))
            blit_pop(surface, p.label, p.size, p.color, (p.x + dx, p.y), scale, round(255 * (1 - k**3)))
        if self.flash > 0:  # a short white impact frame around the hit, over a brief global flash
            surface.fill((round(160 * self.flash),) * 3, special_flags=pygame.BLEND_RGB_ADD)
            if self.impact:
                light = glow(150, (255, 244, 214), 255 * min(1.0, self.flash * 2.5))
                at = (round(self.impact[0] + offset[0]), round(self.impact[1] + offset[1]))
                surface.blit(light, light.get_rect(center=at))

    def _draw_biome(self, surface: pygame.Surface) -> None:
        center, alpha = self.biome_banner
        scale = out_back(min(1.0, (BIOME_S - self.biome_t) / 0.3))
        alpha = round(alpha * min(1.0, self.biome_t / 0.3))
        blit_pop(surface, BIOMES[self.biome].name.upper(), 56, ACCENT, center, scale, alpha, width=4)

    def _draw_pause(self, surface: pygame.Surface) -> None:
        button = self.pause_button
        panel(surface, button, alpha=200, radius=12)
        for dx in (-7, 4):
            surface.fill(WHITE, (button.centerx + dx, button.centery - 9, 5, 18))

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
        if not self.realtime:  # online has no pause
            self._draw_pause(surface)

        # score panel (top-right)
        box = pygame.Rect(WIDTH - 324, 20, 300, 104)
        panel(surface, box, alpha=225)
        blit_text(surface, "PONTOS", 24, (box.x + 18, box.y + 13), MUTED, anchor="topleft", shadow=False)
        blit_text(surface, f"{score.total}", 60, (box.right - 16, box.y + 36), WHITE, anchor="topright")
        if not self.run.shared:  # a challenge's run is on the versus road: no record to chase
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
        power = self.world.player.power or self.world.player.lives
        if power:
            self._draw_power(surface)
        self._draw_speedometer(surface)
        hints = self._hint_alpha()
        if hints > 0:
            self._draw_hints(surface, hints, bottom=SHIELD_BOX.y - 12 if power else HEIGHT - 24)

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

    def _draw_power(self, surface: pygame.Surface) -> None:
        player, frame = self.world.player, int(self.clock * 6)
        if player.lives:  # beside the power's panel, or in its place
            x = SHIELD_BOX.right + 8 if player.power else SHIELD_BOX.x
            box = pygame.Rect(x, SHIELD_BOX.y, SHIELD_BOX.height, SHIELD_BOX.height)
            panel(surface, box, alpha=225)
            heart = self.ctx.assets.frame("life", frame)
            surface.blit(heart, heart.get_rect(center=box.center))
        if not player.power:
            return
        box, power = SHIELD_BOX, POWERS[player.power]
        panel(surface, box, alpha=225)
        icon = self.ctx.assets.frame(player.power.value, frame)
        surface.blit(icon, icon.get_rect(midleft=(box.x + 10, box.centery)))
        bar = pygame.Rect(box.x + 72, box.centery + 6, 140, 8)
        blit_text(surface, power.label, 24, (bar.x, box.y + 9), power.colour, anchor="topleft", shadow=False)
        pygame.draw.rect(surface, (40, 60, 80), bar, border_radius=4)
        bar.width = round(bar.width * self._power_left())
        pygame.draw.rect(surface, power.colour, bar, border_radius=4)

    def _power_left(self) -> float:
        """The share of the power's time left, for its bar: 0 every other blink in the last 2 s."""
        player = self.world.player
        if player.power_t < 2.0 and int(self.clock * 8) % 2:
            return 0.0
        return player.power_t / POWERS[player.power].seconds

    def _draw_speedometer(
        self, surface: pygame.Surface, center: tuple[int, int] = (WIDTH - 110, HEIGHT - 96), radius: int = 70
    ) -> None:
        speed = self.world.speed * TIME_SCALE.get(self.world.player.power, 1.0)  # as the road scrolls
        k = min(1.0, speed / 1000)
        arc = pygame.Rect(0, 0, radius * 2, radius * 2)
        arc.center = center
        start, sweep = math.radians(-30), math.radians(240)
        pygame.draw.circle(surface, (16, 18, 30), center, radius + 8)
        pygame.draw.arc(surface, (50, 54, 78), arc, start, start + sweep, 8)
        if k > 0:
            color = ACCENT if k < 0.7 else FLAME
            pygame.draw.arc(surface, color, arc, start + sweep * (1 - k), start + sweep, 8)
        blit_text(surface, f"{round(speed * 0.25)}", 48, (center[0], center[1] + 2), WHITE)
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
        pad = self.ctx.input.using_pad
        lines = PAD_HINTS if pad else KEY_HINTS
        if self.realtime:  # online: no pause, R gives up
            lines = lines[:-1] + (() if pad else (("R", "desistir"),))
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
            label, color = self.banner or ("VITÓRIA!", ACCENT)
            blit_pop(surface, label, 150, color, center, scale, alpha, width=6)
        elif self.phase is Phase.CRASHED and self.phase_t > 0.5:
            k = min(1.0, (self.phase_t - 0.5) / 0.3)
            alpha = round(255 * clamp((CRASH_TO_RESULTS - self.phase_t) / 0.2, 0.0, 1.0))
            label, color = self.banner or ("BATEU!", DANGER)
            blit_pop(surface, label, 140, color, center, out_back(k), alpha, width=6)
