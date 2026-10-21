"""Ranked runs over the site's socket: JOGAR, and the wait for the server's go (the Game routes messages)."""

import pygame

from ..input import Action
from ..settings import HEIGHT, MUTED, WHITE, WIDTH, Difficulty
from ..ui import blit_text, outlined
from .base import Context, MenuScene, Scene, Transition

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
    """Asks for a ranked run (solo) and waits: Conectando…, then Preparando… once the server opened the match,
    or why it refused. The Game sends ready and starts the race at go; Esc cancels."""

    dim, blur = 30, True

    def __init__(self, ctx: Context) -> None:
        super().__init__(ctx)
        self.label = "Conectando…"
        self.m: int | None = None  # the match, once the server opened it
        self.refused = False

    def enter(self) -> None:
        net, save = self.ctx.net, self.ctx.save
        assert net
        if not net.up or net.skin != save.skin:  # the hello names the car: another car needs a new socket
            net.connect(save.skin)
        elif net.me:
            self.label = "Aguardando…"
        net.send({"t": "solo", "mode": save.mode})

    def say(self, label: str) -> None:
        """The server refused (or the socket closed): the reason stays up until Esc."""
        self.label, self.refused, self.m = label, True, None

    def on_net(self, msg: dict) -> None:
        if msg.get("t") == "closed" and not self.refused:
            self.say("Sem conexão com o servidor")

    def handle(self, action: Action | None, event: pygame.Event) -> None:
        if action is not Action.BACK:
            return
        from .title import TitleScene

        if self.m is not None and self.ctx.net:
            self.ctx.net.send({"t": "leave", "m": self.m})
        self.ctx.audio.play("ui_back")
        self.ctx.scenes.switch(TitleScene(self.ctx), Transition.FADE)

    def draw_ui(self, surface: pygame.Surface) -> None:
        heading = outlined(self.label, 72, WHITE, width=4)
        surface.blit(heading, heading.get_rect(center=(WIDTH // 2, 320)))
        blit_text(
            surface, f"Corrida valendo ranking · modo {self.ctx.mode.name}", 30, (WIDTH // 2, 400), MUTED
        )
        back = "B" if self.ctx.input.using_pad else "ESC"
        blit_text(
            surface,
            f"{back} {'voltar' if self.refused else 'cancelar'}",
            24,
            (WIDTH // 2, HEIGHT - 40),
            MUTED,
        )
