"""Car picker and shop: an endless carousel of every car on a turntable. A paid car is locked until the site's
account owns it (net.owned): ENTER twice buys it, and the server's wallet message says it went through."""

import math
import random

import pygame

from ..input import Action
from ..particles import Particles
from ..settings import ACCENT, CARS, HEIGHT, MUTED, PRICE, WHITE, WIDTH
from ..tween import approach, out_back
from ..ui import blit_pop, blit_text, glow, outlined, panel, text
from .base import WEB, Context, MenuScene, Transition, menu_hint

KEYS = tuple(CARS)
CENTER = (WIDTH // 2, 330)
ARROWS = (pygame.Rect(0, 0, 48, 48), pygame.Rect(0, 0, 48, 48))
ARROWS[0].center = (CENTER[0] - 172, CENTER[1])
ARROWS[1].center = (CENTER[0] + 172, CENTER[1])
DISC_R = 135
UNLOCKED_S = 2.5  # LIBERADO! stays up this long


def slot_x(d: float) -> float:
    """Horizontal position of a car ``d`` slots away from the centre (wider gap next to the centre)."""
    a = abs(d)
    offset = 250 * a if a <= 1 else 250 + 175 * (a - 1)
    return CENTER[0] + math.copysign(offset, d)


def coins(n: int) -> str:
    return f"{n:,}".replace(",", ".")  # 1.500


class GarageScene(MenuScene):
    dim, blur = 70, True

    def __init__(self, ctx: Context) -> None:
        super().__init__(ctx)
        self.target = KEYS.index(ctx.save.skin)  # unbounded; the car is target % len(KEYS)
        self.pos = float(self.target)
        self.t = 0.0
        self.armed: str | None = None  # the locked car a first ENTER asked to buy
        self.buying: str | None = None  # the car a second ENTER sent buy for, until the wallet answers
        self.unlocked = 0.0  # LIBERADO! is up while this runs down
        self.particles = Particles(random.Random(ctx.rng.random()))

    @property
    def skin(self) -> str:
        return KEYS[self.target % len(KEYS)]

    def locked(self, key: str) -> bool:
        """A paid car the account does not own: offline and on the desktop, all but the one already chosen."""
        net = self.ctx.net
        return key in PRICE and key not in (net.owned if net else ()) and key != self.ctx.save.skin

    def _move(self, step: int) -> None:
        self.target += step
        self.armed = None
        self.ctx.audio.play("ui_move", 0.6)

    def _confirm(self) -> None:
        """A car it may race is chosen; on a locked one the first ENTER asks, the second buys it."""
        if not self.locked(self.skin):
            self._leave(confirm=True)
            return
        net = self.ctx.net
        if not (net and net.up and net.coins is not None and net.coins >= PRICE[self.skin]):
            self.ctx.audio.play("ui_back")  # the line says why
        elif self.armed != self.skin:
            self.armed = self.skin
            self.ctx.audio.play("ui_select")
        else:
            net.send({"t": "buy", "skin": self.skin})
            self.armed, self.buying = None, self.skin
            self.ctx.audio.play("ui_select")

    def _leave(self, confirm: bool) -> None:
        from .title import TitleScene

        if confirm:
            self.ctx.save.skin = self.skin
            self.ctx.persist()
            self.ctx.audio.play("ui_select")
        else:
            self.ctx.audio.play("ui_back")
        self.ctx.scenes.switch(TitleScene(self.ctx, focus=1), Transition.SLIDE_RIGHT)

    def handle(self, action: Action | None, event: pygame.Event) -> None:
        if action is Action.LEFT:
            self._move(-1)
        elif action is Action.RIGHT:
            self._move(1)
        elif action is Action.CONFIRM:
            self._confirm()
        elif action is Action.BACK:
            self._leave(confirm=False)
        elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if ARROWS[0].collidepoint(event.pos):
                self._move(-1)
            elif ARROWS[1].collidepoint(event.pos):
                self._move(1)
            elif abs(event.pos[0] - CENTER[0]) < 80 and abs(event.pos[1] - CENTER[1]) < 130:
                self._confirm()
            elif abs(event.pos[1] - CENTER[1]) < 120:
                self._move(-1 if event.pos[0] < CENTER[0] else 1)

    def on_net(self, msg: dict) -> None:
        """The wallet answers every buy (net.py keeps its coins and owned): bought, the car is chosen."""
        net = self.ctx.net
        if msg.get("t") != "wallet" or not net:
            return
        bought, self.buying, self.armed = self.buying, None, None
        if bought in net.owned:
            self.ctx.save.skin = bought
            self.ctx.persist()
            self.unlocked = UNLOCKED_S
            self.ctx.audio.play("record")
            self.particles.confetti(90)

    def update(self, dt: float) -> None:
        super().update(dt)
        self.t += dt
        self.pos = approach(self.pos, self.target, 12.0, dt)
        self.unlocked = max(0.0, self.unlocked - dt)
        self.particles.update(dt, 0.0)

    def info(self) -> str:
        """The line under the name: the record with this car, or what it takes to buy it."""
        save, net, key = self.ctx.save, self.ctx.net, self.skin
        if not self.locked(key):
            current = " · SELECIONADO" if key == save.skin else ""
            return f"Recorde com este carro: {save.best_by_skin.get(key, 0)}{current}"
        price = PRICE[key]
        if not WEB:
            return "Disponível na versão online"
        if not net:  # logged out of the site
            return "Entre no site para comprar"
        if not net.up:  # it keeps the last wallet, but a buy could not go out
            return "Sem conexão com o servidor"
        if net.coins is None:  # its socket has not been welcomed yet
            return "Conectando…"
        if (n := price - net.coins) > 0:  # a debt too
            return f"Falta{'' if n == 1 else 'm'} {coins(n)} moeda{'' if n == 1 else 's'}"
        if self.armed == key:
            enter = "A" if self.ctx.input.using_pad else "ENTER"
            return f"{enter} de novo para comprar por {coins(price)}"
        return f"{coins(price)} moedas · você tem {coins(net.coins)}"

    def draw_ui(self, surface: pygame.Surface) -> None:
        heading = outlined("GARAGEM", 80, WHITE, width=4)
        surface.blit(heading, heading.get_rect(center=(WIDTH // 2, 74)))
        if self.unlocked:
            pop = out_back(min(1.0, (UNLOCKED_S - self.unlocked) / 0.35))
            alpha = round(255 * min(1.0, self.unlocked * 3))
            blit_pop(surface, "LIBERADO!", 54, ACCENT, (WIDTH // 2, 140), pop, alpha, width=4, peak=1.17)
        else:
            blit_text(surface, "Escolha o seu carro", 28, (WIDTH // 2, 126), MUTED)

        self._draw_turntable(surface)
        for rect, direction in zip(ARROWS, (-1, 1), strict=True):  # under the cars that slide past them
            panel(surface, rect, alpha=210, radius=24)
            cx, cy = rect.center
            pts = [(cx + 8 * direction, cy), (cx - 6 * direction, cy - 11), (cx - 6 * direction, cy + 11)]
            pygame.draw.polygon(surface, WHITE, pts)

        base = math.floor(self.pos)
        slots = sorted(range(base - 3, base + 5), key=lambda k: -abs(k - self.pos))  # far cars first
        for k in slots:
            self._draw_car(surface, k)
        if self.locked(self.skin):
            self._draw_price(surface, PRICE[self.skin])
        self.particles.draw(surface)

        name = outlined(CARS[self.skin][0].upper(), 72, ACCENT, width=4)
        surface.blit(name, name.get_rect(center=(WIDTH // 2, 548)))
        blit_text(surface, self.info(), 28, (WIDTH // 2, 600), ACCENT if self.armed else WHITE)
        blit_text(surface, menu_hint(self.ctx), 24, (WIDTH // 2, HEIGHT - 40), MUTED)

    def _draw_price(self, surface: pygame.Surface, price: int) -> None:
        """A padlock and the price on the turntable's rim, under a locked car."""
        label = coins(price)
        rect = pygame.Rect(0, 0, 100 + text(label, 30).get_width(), 44)
        rect.center = (CENTER[0], CENTER[1] + DISC_R + 8)  # clear of the car
        panel(surface, rect, alpha=230, radius=22, border=ACCENT)
        lock = pygame.Rect(rect.x + 18, rect.centery - 5, 18, 14)
        pygame.draw.arc(surface, MUTED, (lock.x + 3, lock.y - 10, 12, 20), 0, math.pi, 3)
        pygame.draw.rect(surface, MUTED, lock, border_radius=3)
        coin = self.ctx.assets.frame("coin")
        surface.blit(coin, coin.get_rect(midleft=(lock.right + 4, rect.centery)))
        blit_text(surface, label, 30, (rect.right - 18, rect.centery), ACCENT, "midright", False)

    def _draw_turntable(self, surface: pygame.Surface) -> None:
        """Seen from above, like the cars: a dark disc with a slowly turning ring of ticks."""
        halo = glow(DISC_R + 60, ACCENT, 45)
        surface.blit(halo, halo.get_rect(center=CENTER))
        pygame.draw.circle(surface, (14, 16, 28), CENTER, DISC_R)
        pygame.draw.circle(surface, (44, 48, 70), CENTER, DISC_R - 16, 2)
        for i in range(36):
            a = self.t * 0.5 + i * math.tau / 36
            c, s = math.cos(a), math.sin(a)
            r0, r1 = DISC_R - 12, DISC_R - 4
            color = ACCENT if i % 3 == 0 else (120, 104, 60)
            pygame.draw.line(
                surface,
                color,
                (CENTER[0] + c * r0, CENTER[1] + s * r0),
                (CENTER[0] + c * r1, CENTER[1] + s * r1),
                2,
            )
        pygame.draw.circle(surface, ACCENT, CENTER, DISC_R, 3)

    def _draw_car(self, surface: pygame.Surface, k: int) -> None:
        d = k - self.pos
        if abs(d) > 2.6:
            return
        key = KEYS[k % len(KEYS)]
        native = self.ctx.assets.native(f"car_{key}")
        frame = native[int(self.t * 6) % len(native)] if abs(d) < 0.5 else native[0]
        scale = max(3.0, 6.0 - 2.0 * abs(d))  # whole numbers at rest: 6x in the middle, 4x and 3x beside
        img = pygame.transform.scale_by(frame, math.ceil(scale))
        if scale % 1:  # sliding: shrink a whole-pixel render smoothly, nearest would give uneven columns
            img = pygame.transform.smoothscale_by(img, scale / math.ceil(scale))
        if abs(d) >= 0.5 and self.locked(key):  # in colour once in the middle, where its price shows
            img.fill((80, 84, 104), special_flags=pygame.BLEND_RGB_MULT)
        bob = math.sin(self.t * 2.5) * 4 * max(0.0, 1 - abs(d))
        center = (round(slot_x(d)), round(CENTER[1] + bob + 18 * min(1, abs(d))))
        if abs(d) < 0.5:
            shadow = pygame.mask.from_surface(img).to_surface(
                setcolor=(0, 0, 0, 110), unsetcolor=(0, 0, 0, 0)
            )
            surface.blit(shadow, shadow.get_rect(center=(center[0] + 10, center[1] + 14)))
        img.set_alpha(round(255 * max(0.0, 1 - 0.45 * abs(d))))
        surface.blit(img, img.get_rect(center=center))
