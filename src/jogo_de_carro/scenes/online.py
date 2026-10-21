"""Races over the site's socket (the Game routes its messages): JOGAR's ranked run, AMIGOS and the invites
to a live race, and the wait for the server's go."""

import pygame

from ..input import Action
from ..settings import ACCENT, HEIGHT, MODE_BY_KEY, MUTED, WHITE, WIDTH, Difficulty
from ..tween import out_cubic
from ..ui import Menu, blit_text, fit, outlined, panel
from .base import Context, MenuScene, Scene, Transition, menu_hint

# the results screen's line about the server's word on the run (plan §3)
VERIFYING = "verificando…"
LOST = "Corrida invalidada: conexão perdida"  # the socket closed mid-race
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
ROWS = 6  # friends listed in AMIGOS


def official(result: dict, mode: Difficulty) -> str:
    """The line for a result message: ok (with the rank), review or rejected (with the reason)."""
    if result.get("state") == "ok":
        return f"✓ #{result.get('rank')} no ranking {mode.name}"
    if result.get("state") == "review":
        return "Em análise — entra no ranking após revisão"
    why = result.get("why")
    return f"Corrida invalidada: {WHY.get(why, why or 'motivo desconhecido')}"


def play(ctx: Context) -> Scene:
    """JOGAR: a ranked run when the page is logged in to the site, otherwise the offline race."""
    from .race import RaceScene

    return WaitScene(ctx) if ctx.net else RaceScene(ctx)


class WaitScene(MenuScene):
    """Asks the server for a race and waits for its go (the Game sends ready at the match and starts the
    race at go); Esc cancels. A ranked run (solo): Conectando…, Preparando…, or why it was refused. A live
    race against ``friend``: the invite (Aguardando ana_42…, or why it was turned down), or with ``reply``
    the yes to one."""

    dim, blur = 30, True

    def __init__(
        self, ctx: Context, friend: dict | None = None, mode: str | None = None, reply: str | None = None
    ) -> None:
        super().__init__(ctx)
        self.mode = MODE_BY_KEY[mode] if mode else ctx.mode
        self.friend = friend  # {"id", "nick"}: a live race
        self.kind = "live" if friend else "solo"
        if friend is None:
            self.ask: dict = {"t": "solo", "mode": self.mode.key}
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
        # the hello names the car: another car needs a new socket (not for a reply: the invite is this one's)
        if self.ask["t"] != "invite_reply" and (not net.up or net.skin != save.skin):
            net.connect(save.skin)
        elif net.me and not self.friend:
            self.label = "Aguardando…"
        net.send(self.ask)

    def say(self, label: str) -> None:
        """The server refused (or the socket closed): the reason stays up until Esc."""
        self.label, self.refused, self.m = label, True, None

    def on_net(self, msg: dict) -> None:
        t = msg.get("t")
        if t == "closed" and not self.refused:
            self.say("Sem conexão com o servidor")
        elif t == "result" and self.m is not None and msg.get("m") == self.m:
            self.say("Corrida anulada")  # void before go: someone was not ready
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
        if self.friend:
            line = f"Ao vivo contra {self.friend['nick']} · modo {self.mode.name}"
        else:
            line = f"Corrida valendo ranking · modo {self.mode.name}"
        blit_text(surface, line, 30, (WIDTH // 2, 400), MUTED)
        back = "B" if self.ctx.input.using_pad else "ESC"
        blit_text(
            surface,
            f"{back} {'voltar' if self.refused else 'cancelar'}",
            24,
            (WIDTH // 2, HEIGHT - 40),
            MUTED,
        )


class AmigosScene(MenuScene):
    """Friends online (the welcome's list, kept by presence): CORRER AGORA invites one to a live race in the
    current mode. Friends are added on the site."""

    dim, blur = 30, True

    def __init__(self, ctx: Context) -> None:
        super().__init__(ctx)
        self.rows: list[dict] = []
        self.menu = Menu([], (840, 380), ctx.audio)
        self.shown: list[tuple] = [()]  # what the menu was built from: rebuilt as presence changes

    def online(self) -> list[dict]:
        """In-menu friends first (they can be invited), then those racing; by nick."""
        net = self.ctx.net
        friends = [f for f in (net.friends.values() if net else ()) if f.get("s") in ("menu", "racing")]
        # ponytail: the first ROWS only; a scrolling list when players have that many friends online at once
        return sorted(friends, key=lambda f: (f["s"] != "menu", str(f["nick"]).lower()))[:ROWS]

    def handle(self, action: Action | None, event: pygame.Event) -> None:
        if action is Action.BACK:
            self._back()
            return
        choice = self.menu.handle(action, event) if self.rows else None
        if choice is None:
            return
        friend = self.rows[choice]
        if friend["s"] != "menu":
            self.ctx.toast(f"{friend['nick']} está correndo agora")
            return
        self.ctx.audio.play("ui_select")
        self.ctx.scenes.switch(WaitScene(self.ctx, friend), Transition.FADE)

    def _back(self) -> None:
        from .title import TitleScene

        self.ctx.audio.play("ui_back")
        self.ctx.scenes.switch(TitleScene(self.ctx, focus=4), Transition.SLIDE_RIGHT)

    def update(self, dt: float) -> None:
        super().update(dt)
        if not self.ctx.net:  # logged out meanwhile: offline play has no friends
            self._back()
            return
        rows = self.online()
        shown = [(f["id"], f["s"]) for f in rows]
        if shown != self.shown:
            focused = self.shown[self.menu.index] if self.rows else None
            index = next((i for i, row in enumerate(shown) if focused and row[0] == focused[0]), 0)
            labels = ["CORRER AGORA" if f["s"] == "menu" else "CORRENDO" for f in rows]
            self.menu = Menu(labels, (840, 380), self.ctx.audio, size=(260, 52), gap=20, index=index)
            self.rows, self.shown = rows, shown
        self.menu.update(dt)

    def draw_ui(self, surface: pygame.Surface) -> None:
        net = self.ctx.net
        heading = outlined("AMIGOS", 80, WHITE, width=4)
        surface.blit(heading, heading.get_rect(center=(WIDTH // 2, 74)))
        line = f"Corrida ao vivo no modo {self.ctx.mode.name}: quem durar mais vence"
        blit_text(surface, line, 28, (WIDTH // 2, 126), MUTED)
        for friend, button in zip(self.rows, self.menu.buttons, strict=True):
            y = button.rect.centery
            panel(surface, pygame.Rect(300, y - 34, 680, 68), alpha=200, radius=18)
            blit_text(surface, fit(str(friend["nick"]), 34, 230), 34, (328, y), WHITE, anchor="midleft")
            free = friend["s"] == "menu"
            pygame.draw.circle(surface, (99, 199, 77) if free else ACCENT, (574, y), 7)
            blit_text(surface, "no menu" if free else "correndo", 26, (590, y), MUTED, "midleft", False)
        self.menu.draw(surface)
        if not self.rows:
            empty = "Conectando…" if not (net and net.me) else "Nenhum amigo online agora"
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
