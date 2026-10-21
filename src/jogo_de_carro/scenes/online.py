"""Races over the site's socket (the Game routes its messages): JOGAR's ranked run, AMIGOS with the invites
to a live race and the challenges, and the wait for the server's go."""

import pygame

from ..input import Action
from ..settings import ACCENT, HEIGHT, MODE_BY_KEY, MUTED, WHITE, WIDTH, Difficulty
from ..tween import out_cubic
from ..ui import Menu, blit_text, fit, mss, outlined, panel
from .base import Context, MenuScene, Scene, Transition, menu_hint

# the results screen's line about the server's word on the run (plan §3)
VERIFYING = "verificando…"
LOST = "Corrida invalidada: conexão perdida"  # the socket closed mid-race
CHALLENGE_LOST = "Desafio perdido: conexão perdida"  # ...in a challenge: the server counts it as a loss
NO_RESULT = "Conexão perdida antes do resultado"  # ...after the run ended, before the server's result
WHY = {
    "ritmo": "ritmo irregular",
    "adiantado": "mais rápida que o relógio",
    "invalido": "dados inválidos",
    "conexao": "conexão perdida",
    "prazo": "prazo esgotado",
    "substituida": "há uma melhor sua em análise",
}
GONE = {  # invite_gone, on either side ({} is the friend)
    "declined": "{} recusou o convite",
    "expired": "O convite expirou",
    "cancelled": "{} cancelou o convite",
    "offline": "{} saiu do jogo",
    "busy": "{} está ocupado agora",
}
ROWS = 7  # rows AMIGOS shows at a time: the list scrolls to the focused button's row
BUTTONS = {"JOGAR": (1000, 170), "CORRER AGORA": (790, 220), "DESAFIAR": (1000, 170)}  # centre x, width
STATUS = {"menu": ("no menu", (99, 199, 77)), "racing": ("correndo", ACCENT), "off": ("offline", MUTED)}


def official(result: dict, mode: Difficulty, to: str = "") -> str:
    """The line for a result message: ok (with the rank), review or rejected (with the reason). A run that
    challenges ``to`` (never in review): sent to them once ok; rejected, a loss (they win, no second try)."""
    why = WHY.get(result.get("why"), result.get("why") or "motivo desconhecido")
    if to:
        return f"✓ Desafio enviado a {to}" if result.get("state") == "ok" else f"Desafio perdido: {why}"
    if result.get("state") == "ok":
        return f"✓ #{result.get('rank')} no ranking {mode.name}"
    if result.get("state") == "review":
        return "Em análise — entra no ranking após revisão"
    return f"Corrida invalidada: {why}"


def play(ctx: Context) -> Scene:
    """JOGAR: a ranked run when the page is logged in to the site, otherwise the offline race."""
    from .race import RaceScene

    return WaitScene(ctx) if ctx.net else RaceScene(ctx)


class WaitScene(MenuScene):
    """Asks the server for a race and waits for its go (the Game sends ready at the match and starts the
    race at go); Esc cancels. A ranked run (solo): Conectando…, Preparando…, or why it was refused. A live
    race against ``friend``: the invite (Aguardando ana_42…, or why it was turned down), or with ``reply``
    the yes to one. A challenge: to ``friend`` (``challenge``), or ``play``ing the one they sent."""

    dim, blur = 30, True

    def __init__(
        self,
        ctx: Context,
        friend: dict | None = None,
        mode: str | None = None,
        reply: str | None = None,
        *,
        challenge: bool = False,
        play: dict | None = None,
    ) -> None:
        super().__init__(ctx)
        self.mode = MODE_BY_KEY[mode] if mode else ctx.mode
        self.friend = friend  # {"id", "nick"}: a live race or a challenge (only "nick" to play one)
        self.kind = "challenge" if challenge or play else "live" if friend else "solo"
        self.play = play  # the received challenge played (welcome's challenges)
        if friend is None:
            self.ask: dict = {"t": "solo", "mode": self.mode.key}
            self.label = "Conectando…"
        elif play:
            self.ask = {"t": "challenge_play", "id": play["id"]}
            self.label = "Preparando…"
        elif challenge:
            self.ask = {"t": "challenge", "to": friend["id"], "mode": self.mode.key}
            self.label = "Conectando…"
        elif reply is None:
            self.ask = {"t": "invite", "to": friend["id"], "mode": self.mode.key}
            self.label = f"Aguardando {friend['nick']}…"
        else:
            self.ask = {"t": "invite_reply", "id": reply, "ok": True}
            self.label = "Preparando…"
        self.invite = reply  # the invite's id (the inviter learns it from waiting)
        self.m: int | None = None  # the match, once the server opened it
        self.match: dict | None = None  # ...and its message (the rival of a live race)
        self.refused = False

    def enter(self) -> None:
        net, save = self.ctx.net, self.ctx.save
        assert net
        # the hello names the car: another car needs a new socket (not for a reply: the invite is this one's;
        # nor to play a challenge, as for a reply: its new welcome would list the challenge being played)
        keep = self.ask["t"] == "invite_reply" or (self.ask["t"] == "challenge_play" and net.up)
        if not keep and (not net.up or net.skin != save.skin):
            net.connect(save.skin)
        elif net.me and self.label == "Conectando…":
            self.label = "Aguardando…"
        net.send(self.ask)

    def say(self, label: str) -> None:
        """The server refused (or the socket closed): the reason stays up until Esc."""
        self.label, self.refused, self.m = label, True, None

    def on_net(self, msg: dict) -> None:
        t = msg.get("t")
        if t == "closed" and not self.refused:  # the attempt was used once the match came
            self.say(CHALLENGE_LOST if self.play and self.m is not None else "Sem conexão com o servidor")
        elif t == "welcome" and self.play and self.ctx.net:  # a new socket's list: still has the one played
            self.ctx.net.challenges = [c for c in self.ctx.net.challenges if c["id"] != self.play["id"]]
        elif t == "result" and self.m is not None and msg.get("m") == self.m:  # before go: one was not ready
            if msg.get("verdict") == "loss":  # a challenge's one attempt: missing the deadline loses it
                self.say(f"Desafio perdido: {WHY.get(msg.get('why'), 'prazo esgotado')}")
            else:
                self.say("Corrida anulada")
        elif t == "invite_gone" and msg.get("id") == self.invite and self.m is None and self.friend:
            self.say(GONE.get(msg.get("why"), "O convite acabou").format(self.friend["nick"]))

    def handle(self, action: Action | None, event: pygame.Event) -> None:
        if action is not Action.BACK:
            return
        from .title import TitleScene

        net = self.ctx.net
        if net and self.m is not None:
            net.send({"t": "leave", "m": self.m})
        elif net and self.ask["t"] == "invite" and self.invite and not self.refused:
            net.send({"t": "invite_cancel", "id": self.invite})
        self.ctx.audio.play("ui_back")
        back = AmigosScene(self.ctx) if self.friend else TitleScene(self.ctx)
        self.ctx.scenes.switch(back, Transition.FADE)

    def draw_ui(self, surface: pygame.Surface) -> None:
        heading = outlined(self.label, 72, WHITE, width=4)
        surface.blit(heading, heading.get_rect(center=(WIDTH // 2, 320)))
        line = {
            "solo": "Corrida valendo ranking · modo {mode}",
            "challenge": "Desafio para {nick} · modo {mode}",
            "challenge_play": "Desafio de {nick} · contra a corrida gravada · modo {mode}",
        }.get(self.ask["t"], "Ao vivo contra {nick} · modo {mode}")
        nick = self.friend["nick"] if self.friend else ""
        blit_text(surface, line.format(nick=nick, mode=self.mode.name), 30, (WIDTH // 2, 400), MUTED)
        back = "B" if self.ctx.input.using_pad else "ESC"
        cancel = "desistir (conta como derrota)" if self.play else "cancelar"  # the one attempt is used
        blit_text(
            surface,
            f"{back} {'voltar' if self.refused else cancel}",
            24,
            (WIDTH // 2, HEIGHT - 40),
            MUTED,
        )


class AmigosScene(MenuScene):
    """Challenges received (JOGAR races the friend's recorded run, once) and every friend, online first:
    CORRER AGORA invites one in the menu to a live race, DESAFIAR challenges any friend to beat the run you
    play now; both in the current mode. Friends are added on the site."""

    dim, blur = 30, True

    def __init__(self, ctx: Context) -> None:
        super().__init__(ctx)
        self.rows: list[dict] = []  # the challenges, then the friends
        self.actions: list[tuple[str, int]] = []  # each button's label and row (its index in rows)
        self.menu = Menu([], (0, 0), ctx.audio)
        self.shown: list[tuple] | None = None  # what the rows were built from: rebuilt as it changes
        self.challenges = 0  # how many of the rows are challenges
        self.top = 0  # the first row shown

    def listed(self) -> tuple[list[dict], list[dict]]:
        """The challenges, then the friends: in the menu, racing, offline; by nick."""
        net, order = self.ctx.net, {"menu": 0, "racing": 1}
        friends = sorted(
            net.friends.values() if net else (), key=lambda f: (order.get(f["s"], 2), f["nick"].lower())
        )
        return list(net.challenges) if net else [], friends

    def handle(self, action: Action | None, event: pygame.Event) -> None:
        if action is Action.BACK:
            self._back()
            return
        if action in (Action.LEFT, Action.RIGHT):  # the buttons go in reading order: any arrow moves along
            action = Action.UP if action is Action.LEFT else Action.DOWN
        choice = self.menu.handle(action, event) if self.actions else None
        net = self.ctx.net
        if choice is None or not net:
            return
        label, i = self.actions[choice]
        row = self.rows[i]
        self.ctx.audio.play("ui_select")
        if label == "JOGAR":  # the one attempt starts now
            net.challenges = [c for c in net.challenges if c["id"] != row["id"]]
            wait = WaitScene(self.ctx, {"nick": row["from"]}, row["mode"], play=row)
        else:
            wait = WaitScene(self.ctx, row, challenge=label == "DESAFIAR")
        self.ctx.scenes.switch(wait, Transition.FADE)

    def _back(self) -> None:
        from .title import TitleScene

        self.ctx.audio.play("ui_back")
        self.ctx.scenes.switch(TitleScene(self.ctx, focus=4), Transition.SLIDE_RIGHT)

    def update(self, dt: float) -> None:
        super().update(dt)
        if not self.ctx.net:  # logged out meanwhile: offline play has no friends
            self._back()
            return
        challenges, friends = self.listed()
        shown = [("c", c["id"]) for c in challenges] + [("f", f["id"], f["s"]) for f in friends]
        if shown != self.shown:
            self._build(challenges, friends)
            self.shown = shown
        self._scroll()
        self.menu.update(dt)

    def _build(self, challenges: list[dict], friends: list[dict]) -> None:
        """The rows and their buttons, keeping the focus on its button."""
        focused = self.ids()[self.menu.index] if self.actions else None
        self.rows, self.actions, self.challenges = challenges + friends, [], len(challenges)
        for i, row in enumerate(self.rows):
            if i < self.challenges:
                labels = ["JOGAR"]
            else:  # CORRER AGORA to a friend in the menu only
                labels = ["CORRER AGORA"] * (row["s"] == "menu") + ["DESAFIAR"]
            self.actions += [(label, i) for label in labels]
        self.menu = Menu([label for label, _ in self.actions], (0, 0), self.ctx.audio)
        self.menu.index = self.ids().index(focused) if focused in self.ids() else 0
        for button in self.menu.buttons:
            button.size = 28

    def ids(self) -> list[tuple[str, int]]:
        return [(label, self.rows[i]["id"]) for label, i in self.actions]

    def y(self, i: int) -> int:
        """Where row i is drawn while shown (a gap between the challenges and the friends)."""
        return 212 + (i - self.top) * 58 + 12 * (self.top < self.challenges <= i)

    def _scroll(self) -> None:
        """ROWS rows from top, which follows the focused button; the hidden rows' buttons go off screen."""
        focus = self.actions[self.menu.index][1] if self.actions else 0
        self.top = max(0, min(self.top, focus, len(self.rows) - ROWS), focus - ROWS + 1)
        for (label, i), button in zip(self.actions, self.menu.buttons, strict=True):
            x, w = BUTTONS[label]
            y = self.y(i) if self.top <= i < self.top + ROWS else -100
            button.rect = pygame.Rect(x - w // 2, y - 21, w, 42)

    def draw_ui(self, surface: pygame.Surface) -> None:
        net = self.ctx.net
        heading = outlined("AMIGOS", 80, WHITE, width=4)
        surface.blit(heading, heading.get_rect(center=(WIDTH // 2, 74)))
        line = f"Modo {self.ctx.mode.name}: corra ao vivo, ou desafie a bater a corrida que você fizer agora"
        blit_text(surface, line, 28, (WIDTH // 2, 126), MUTED)
        if self.top < self.challenges:
            blit_text(surface, "DESAFIOS RECEBIDOS", 24, (200, 172), ACCENT, anchor="midleft", shadow=False)
        shown = range(self.top, min(len(self.rows), self.top + ROWS))
        for i in shown:
            row, y = self.rows[i], self.y(i)
            panel(surface, pygame.Rect(180, y - 27, 920, 54), alpha=200, radius=18)
            if i < self.challenges:
                mode, secs = MODE_BY_KEY[row["mode"]].name, mss(row["secs"])
                score = f"{row['score']:,}".replace(",", ".")  # 2.845
                said = fit(f"{row['from']} fez {score} em {secs} ({mode})", 28, 660)
                blit_text(surface, said, 28, (208, y), WHITE, anchor="midleft")
                continue
            status, color = STATUS.get(row["s"], STATUS["off"])
            nick = fit(str(row["nick"]), 32, 240)
            blit_text(surface, nick, 32, (208, y), MUTED if row["s"] == "off" else WHITE, anchor="midleft")
            pygame.draw.circle(surface, color, (470, y), 7)
            blit_text(surface, status, 26, (486, y), MUTED, "midleft", False)
        self.menu.draw(surface)
        above, below = self.top, len(self.rows) - shown.stop
        if more := " · ".join([f"↑ mais {above}"] * bool(above) + [f"↓ mais {below}"] * bool(below)):
            blit_text(surface, more, 24, (1100, 172), MUTED, anchor="midright", shadow=False)  # it scrolls
        if not self.rows:
            empty = "Conectando…" if not (net and net.me) else "Nenhum amigo ainda"
            blit_text(surface, empty, 40, (WIDTH // 2, 330), WHITE)
            blit_text(surface, "Adicione amigos pelo apelido no site", 28, (WIDTH // 2, 386), MUTED)
        if net and net.requests:
            n = net.requests
            asks = f"{n} pedido{'s' if n > 1 else ''} de amizade — veja no site"
            blit_text(surface, asks, 28, (WIDTH // 2, HEIGHT - 92), ACCENT)
        blit_text(surface, menu_hint(self.ctx), 24, (WIDTH // 2, HEIGHT - 40), MUTED)


class ConviteScene(Scene):
    """A friend's invite to a live race, over whatever is on screen: ACEITAR / RECUSAR before its time runs
    out. The Game pushes it (never over a race or a wait)."""

    def __init__(self, ctx: Context, msg: dict) -> None:
        super().__init__(ctx)
        self.below = ctx.scenes.top  # keeps moving underneath
        self.id, self.friend = msg["id"], msg["from"]
        self.mode = MODE_BY_KEY[msg["mode"]]
        self.ttl = self.left = float(msg.get("ttl") or 30)
        self.menu = Menu(
            ["ACEITAR", "RECUSAR"], (WIDTH // 2, 446), ctx.audio, size=(232, 56), gap=24, horizontal=True
        )
        self.t = 0.0

    def enter(self) -> None:
        self.ctx.audio.play("shield_up")

    def handle(self, action: Action | None, event: pygame.Event) -> None:
        choice = 1 if action is Action.BACK else self.menu.handle(action, event)
        if choice == 0:
            self.ctx.audio.play("ui_select")
            reply = WaitScene(self.ctx, self.friend, self.mode.key, self.id)
            self.ctx.scenes.switch(reply, Transition.FADE)
        elif choice == 1:
            self.ctx.audio.play("ui_back")
            if self.ctx.net:
                self.ctx.net.send({"t": "invite_reply", "id": self.id, "ok": False})
            self.ctx.scenes.pop()

    def on_net(self, msg: dict) -> None:
        if msg.get("t") == "invite_gone" and msg.get("id") == self.id:
            self._gone(GONE.get(msg.get("why"), "O convite acabou"))
            return
        if msg.get("t") == "closed":
            self._gone("Conexão perdida")
        self.below.on_net(msg)  # e.g. a ranked run's late result on the results screen

    def _gone(self, why: str) -> None:
        if self.ctx.scenes.top is self:
            self.ctx.scenes.pop()
            self.ctx.toast(why.format(self.friend["nick"]), 2.5)

    def update(self, dt: float) -> None:
        self.t += dt
        self.below.update(dt)
        self.menu.update(dt)
        self.left -= dt
        if self.left <= 0:
            self._gone(GONE["expired"])

    def draw(self, surface: pygame.Surface) -> None:
        self.below.draw(surface)
        k = out_cubic(min(1.0, self.t / 0.25))
        surface.fill((round(255 - 150 * k),) * 3, special_flags=pygame.BLEND_RGB_MULT)
        box = pygame.Rect(0, 0, 760, 330)
        box.center = (WIDTH // 2, HEIGHT // 2 + round(30 * (1 - k)))
        panel(surface, box, alpha=255 * k, radius=24, border=(60, 64, 92))
        title = outlined("CONVITE", 60, ACCENT, width=3)
        surface.blit(title, title.get_rect(center=(WIDTH // 2, box.y + 52)))
        who = f"{self.friend['nick']} te chamou para correr ({self.mode.name})"
        blit_text(surface, who, 34, (WIDTH // 2, box.y + 118), WHITE)
        blit_text(
            surface, "Ao vivo, na mesma estrada: quem durar mais vence", 26, (WIDTH // 2, box.y + 158), MUTED
        )
        bar = pygame.Rect(box.x + 60, box.y + 190, box.width - 120, 8)
        pygame.draw.rect(surface, (50, 54, 78), bar, border_radius=4)
        bar.width = round(bar.width * max(0.0, self.left) / self.ttl)
        pygame.draw.rect(surface, ACCENT, bar, border_radius=4)
        self.menu.draw(surface)
        pad = self.ctx.input.using_pad
        hint = "A aceitar · B recusar" if pad else "ENTER aceitar · ESC recusar"
        blit_text(surface, hint, 24, (WIDTH // 2, box.bottom + 28), MUTED)
