"""Versus: two roads from one seed side by side. Contra o bot: the bot stepped in lockstep, decided by
run.verdict. Ao vivo: a friend's inputs relayed by the server, decided by the server's result. Desafio: the
same, with the friend's recorded run as the server streams it."""

import contextlib
import random
from collections import deque
from dataclasses import replace

import pygame

from ..input import Action
from ..run import BadInput, Run, Scored, verdict
from ..settings import (
    ACCENT,
    COMBO_TIME,
    CYAN,
    DANGER,
    FIXED_DT,
    FLAME,
    HEIGHT,
    MUTED,
    SHIELD_TIME,
    WHITE,
    WIDTH,
)
from ..tween import clamp, out_cubic
from ..ui import Color, Menu, blit_pop, blit_text, clock_text, fit, mss, outlined, panel
from ..world.autopilot import BOT_LEVELS, Bot
from ..world.scoring import Score
from ..world.world import Controls
from .base import Context, MenuScene, Scene, Transition, menu_hint
from .online import CHALLENGE_LOST, LOST, NO_RESULT, WHY, paid
from .race import REPORT, Outcome, Phase, RaceScene

BOT_NAMES = {"facil": "FÁCIL", "medio": "MÉDIO", "dificil": "DIFÍCIL"}
BANNERS = {1: ("VITÓRIA!", ACCENT), 0: ("EMPATE!", WHITE), -1: ("VOCÊ PERDEU", DANGER)}
MINE = pygame.Rect(0, 0, WIDTH // 2, HEIGHT)
THEIRS = pygame.Rect(WIDTH // 2, 0, WIDTH // 2, HEIGHT)
SHIFT = -320  # each World draws unchanged but shifted: the road (x 400..880) lands on 80..560 of its half
COLUMN = pygame.Rect(566, 0, 148, HEIGHT)  # the HUD, over the two inner verges (never over a lane)
ENDED = {"crash": "BATEU!", "giveup": "DESISTIU"}  # a stopped rival; any other forfeit: SAIU
ENDS = {  # how a run ended early, for the results (op_end's why)
    "crash": "bateu",
    "giveup": "desistiu",
    "conexao": "perdeu a conexão",
    "ritmo": "ficou para trás",
    "adiantado": "foi desclassificado",
    "invalido": "foi desclassificado",
}
LAG = 24  # live: the rival is replayed at least this many ticks behind me, the server's relay gate (§3, §5)
CATCH_UP = 6  # live: rival ticks at most in one of mine, catching up after late or bursty inputs
UNSTABLE = 60  # live: ticks the rival may fall behind its place before "conexão instável"; the most it is
# drawn behind me for late inputs (a jitter buffer: one-way latency up to about 200 ms stays smooth)
HOLD_S = 12.0  # live: my run is over; the race waits this long at most for the server's result
VERDICTS = {"win": 1, "draw": 0, "loss": -1}


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
        self.level = level
        self.name = self.nick = f"BOT {BOT_NAMES[level]}"
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
        if self.verdict is None and self.rival.outcome:  # the bot crashed on my last tick: I outlasted it
            self._step()
        self.run.stop("giveup")
        self._decide()
        self._results(outcome)

    def _results(self, outcome: Outcome, why: str = "", seconds: float | None = None) -> None:
        """The results card: the verdict, why (or `why`), and the rival's line."""
        from .results import RaceStats, ResultsScene

        stats = RaceStats(
            outcome,
            self.mode,
            self.run.seconds if seconds is None else seconds,
            self.score,
            False,
            self.best,
            self.verdict,
            why or self.reason(),
            self.line(),
            self.official,
            button=self.button,
            wallet=self.wallet,
        )
        self.ctx.scenes.switch(ResultsScene(self.ctx, stats, self.snapshot(), self.again), Transition.NONE)

    def _theirs(self) -> tuple[str | None, dict]:
        """How the rival's run ended, and the server's numbers for it (a live race's)."""
        return self.rival.outcome, {}

    def line(self) -> str:
        theirs, op = self._theirs()
        line = f"{self.nick}: {op.get('score', self.rival.score.total)} pontos"
        if theirs in ENDS:
            line += f" · {ENDS[theirs]} aos {mss(op.get('secs') or self.rival.seconds)}"
        return line

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
        if (ended := self.rival.outcome) not in (None, "win"):  # frozen where it stopped, dimmed
            theirs.fill((110, 110, 120), special_flags=pygame.BLEND_RGB_MULT)
            blit_pop(theirs, ENDED.get(ended, "SAIU"), 72, DANGER, (THEIRS.width // 2, 440), 1.0, width=4)
        surface.blit(self.world.road.vignette, (0, 0))
        self._draw_juice(mine, shifted, SHIFT)

    def _draw_hud(self, surface: pygame.Surface) -> None:
        score, rival, x, w = self.score, self.rival, COLUMN.x, COLUMN.width
        if not self.realtime:  # online has no pause
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
        if state := self.state():
            pill = pygame.Rect(x + 6, box.bottom - 38, w - 12, 28)
            panel(surface, pill, state[1], 255, radius=14)
            blit_text(surface, state[0], 22, pill.center, WHITE, shadow=False)

        self._draw_speedometer(surface, (COLUMN.centerx, HEIGHT - 84), 58)

    def state(self) -> tuple[str, Color] | None:
        """The rival card's pill."""
        if self.rival.outcome == "crash":
            return f"BATEU {mss(self.rival.seconds)}", DANGER
        return None


class LiveScene(VersusScene):
    """Ao vivo contra um amigo, created at the server's go. My run streams to the server as a ranked run does;
    the rival is the friend's inputs as the server relays them (op), replayed at least LAG ticks behind me.
    The server's result decides and ends both runs; when mine ends first, the race stays up until it comes."""

    button = "REVANCHE"
    lost = LOST  # the socket closed mid-race: the server counts it as my forfeit
    stops_short = True  # her op_end past my gate: she stops where her inputs got to

    def __init__(self, ctx: Context, match: dict, friend: dict, seed: int) -> None:
        net, op = ctx.net, match["op"]
        assert net
        RaceScene.__init__(self, ctx, seed, True, op["skin"], match["m"], match["mode"], net.skin)
        self.official = None  # no ranking line: the verdict is the server's word
        self.friend, self.nick = friend, op["nick"]
        self.name = fit(self.nick, 22, COLUMN.width - 24)
        self.rival = Run(ctx.assets, self.mode.key, op["skin"], self.seed, True, rival=net.skin)
        self.verdict: int | None = None
        self.result: dict | None = None
        self.end: tuple[int, str] | None = None  # the rival's last tick, and why (op_end)
        self.over: Outcome | None = None  # my run ended first: the race waits for the result
        self.ticks = 0  # racing ticks since JÁ! on the wall clock (my run stops when it ends)
        # ticks the rival is drawn behind me: more when its inputs come later. ponytail: it only grows (to
        # UNSTABLE), so one hiccup keeps her up to 0.5 s back for the rest of the race; decay it if that shows
        self.lag = LAG
        self.kept: deque[tuple[int, Score]] = deque(maxlen=64)  # my score at each k sent: the server's
        self.waited = 0.0

    def again(self) -> Scene:
        from .online import WaitScene

        return WaitScene(self.ctx, self.friend, self.mode.key)  # REVANCHE: a new invite, same friend and mode

    def _step(self) -> Scored:
        if self.run.outcome:  # given up: my road stands still
            return []
        events = RaceScene._step(self)
        if self.run.tick % REPORT == 0:
            self.kept.append((self.run.tick, replace(self.score)))
        return events

    def update(self, dt: float) -> None:
        if self.phase is Phase.COUNTDOWN:
            self.rival.world.update(dt, Controls())  # standing ticks change nothing
        RaceScene.update(self, dt)
        if self.phase is Phase.COUNTDOWN:
            return
        self.ticks += 1
        rival = self.rival
        rival.advance(min(rival.known, self.ticks - self.lag, rival.tick + CATCH_UP))
        caught_up = self.result is not None and rival.tick == rival.known  # decided: no more of hers comes
        if self.end and (rival.tick >= self.end[0] or (caught_up and self.stops_short)):
            rival.stop(self.end[1])
        elif caught_up and rival.outcome is None:  # she won: she cruises on, for show, as the bot does
            rival.world.invulnerable = True
            rival.world.update(dt, Controls())
        if self.over:
            self.waited += dt
            if self.waited > HOLD_S:
                self.finish(self.over, "O servidor não respondeu")

    @property
    def unstable(self) -> bool:
        """The rival's inputs are late: it is drawn more than UNSTABLE ticks behind its place."""
        racing = self.result is None and self.run.outcome is None and self.rival.outcome is None
        return racing and self.end is None and self.ticks - self.lag - self.rival.tick > UNSTABLE

    def on_net(self, msg: dict) -> None:
        t = msg.get("t")
        if t == "closed":
            if self.result is None:  # nobody will say who won
                self.official = NO_RESULT if self.run.outcome else self.lost
                self.reported = True
                self.finish(self._outcome(), "Conexão perdida")
            return
        if msg.get("m") != self.online:
            return
        if t == "op":
            with contextlib.suppress(BadInput):  # the server checked them; a stale or empty batch is moot
                self.rival.load(msg.get("k"), msg.get("ev"))
                # drawn far enough back that the next batch comes before she is: no stop-and-jump
                self.lag = min(UNSTABLE, max(self.lag, self.ticks - msg["k"] + REPORT))
        elif t == "op_end" and type(msg.get("k")) is int:
            self.end = (msg["k"], str(msg.get("why")))
        elif t == "result" and self.result is None:
            self.result, self.reported = msg, True  # it ended my run too: nothing more to send
            self.wallet = paid(msg)
            self.verdict = VERDICTS.get(msg.get("verdict"))
            if self.verdict is None:  # void
                self.finish(self._outcome(), "Corrida encerrada pelo servidor")
                return
            self.banner = BANNERS[self.verdict]
            if self.over:
                self.finish(self.over)
            elif self.phase in (Phase.COUNTDOWN, Phase.RACING) and self.run.outcome is None:
                self._win()  # decided while I drive: it ends here

    def _outcome(self) -> Outcome:
        return self.over or {Phase.CRASHED: Outcome.CRASH, Phase.WON: Outcome.WIN}.get(
            self.phase, Outcome.GAVE_UP
        )

    def _win(self, celebrate: bool = True) -> None:
        if self.verdict is None:  # I reached the end: the server still compares the points
            self.banner = ("CHEGOU!", WHITE)
        super()._win(celebrate)

    def finish(self, outcome: Outcome, why: str = "") -> None:
        self._stop()  # fin
        if self.result is None and not why:  # my run is over, the race is not: the rival drives on
            self.over = outcome
            return
        result, seconds = self.result or {}, None
        secs = result.get("secs")
        # the server stopped my run (decided, or a forfeit stored as a give-up), maybe after I ran on
        if result.get("outcome") in ("decided", "giveup") and isinstance(secs, int | float):
            mine = dict(self.kept).get(round(secs / FIXED_DT))  # at its last k (a tenth of a second): its
            if mine:  # numbers, which the rival's card shows too
                self.score, seconds = mine, secs
        self._results(outcome, why, seconds)

    def _theirs(self) -> tuple[str | None, dict]:
        """How the rival's run ended (op_end, else as replayed here), and the result's numbers for it."""
        return (self.end[1] if self.end else self.rival.outcome), (self.result or {}).get("op") or {}

    def reason(self) -> str:
        result, v = self.result or {}, self.verdict
        assert v is not None
        theirs, op = self._theirs()
        mine, why = result.get("outcome") or self.run.outcome, result.get("why")
        if v < 0 and why in WHY:  # the server stopped my run
            return f"Você perdeu: {WHY[why]}"
        if v > 0 and theirs in ENDS:
            return f"{self.nick} {ENDS[theirs]} aos {mss(op.get('secs') or self.rival.seconds)}"
        if v < 0 and mine in ENDS:
            return f"Você {ENDS[mine]} aos {mss(result.get('secs') or self.run.seconds)}"
        return {
            1: "Você fez mais pontos",
            0: "Os dois fizeram os mesmos pontos",
            -1: f"{self.nick} fez mais pontos",
        }[v]

    def state(self) -> tuple[str, Color] | None:
        if self.rival.outcome not in (None, "win", "crash"):
            return ENDED.get(self.rival.outcome, "SAIU"), MUTED
        if self.unstable:
            return "conexão instável", FLAME
        return super().state()

    def _draw_hud(self, surface: pygame.Surface) -> None:
        super()._draw_hud(surface)
        panel(surface, pygame.Rect(COLUMN.x + 24, 516, COLUMN.width - 48, 30), alpha=240, radius=15)
        pygame.draw.circle(surface, DANGER, (COLUMN.centerx - 38, 531), 6)
        blit_text(surface, "AO VIVO", 22, (COLUMN.centerx - 26, 531), WHITE, anchor="midleft", shadow=False)


class RecordingScene(LiveScene):
    """Desafio: the rival is a friend's recorded run. The server streams it as op, through the same gate as a
    live rival's inputs (never ahead of my own k + 24, so the recording is never here whole), and its result
    decides against the stored run. One attempt: the results go back to AMIGOS."""

    button = "AMIGOS"
    lost = CHALLENGE_LOST  # the one attempt
    stops_short = False  # her recording went on past where it got to here: she cruises on, its end in line()

    def again(self) -> Scene:
        from .online import AmigosScene

        return AmigosScene(self.ctx)

    def _draw_hud(self, surface: pygame.Surface) -> None:
        VersusScene._draw_hud(self, surface)  # no AO VIVO: it was played before
        panel(surface, pygame.Rect(COLUMN.x + 20, 516, COLUMN.width - 40, 30), alpha=240, radius=15)
        blit_text(surface, "GRAVAÇÃO", 22, (COLUMN.centerx, 531), MUTED, shadow=False)


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
