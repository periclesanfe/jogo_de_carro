"""Scene protocol, shared services and a stack-based scene manager with fade/slide transitions."""

import random
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING

import pygame

from ..assets import Assets
from ..audio import Audio
from ..input import Action, Input
from ..save import SaveData, store
from ..settings import HEIGHT, MODE_BY_KEY, WIDTH, Difficulty
from ..tween import in_out_cubic

if TYPE_CHECKING:
    from .backdrop import Backdrop


@dataclass
class Context:
    """Services every scene can use. Owned by the Game; there are no module-level globals."""

    assets: Assets
    audio: Audio
    input: Input
    save: SaveData
    save_path: Path
    rng: random.Random
    quit: Callable[[], None]
    autopilot: bool = False  # races drive themselves (demo / tests)
    scenes: "SceneManager" = field(init=False)
    backdrop: "Backdrop | None" = None  # the menus share one endless demo drive behind them

    @property
    def mode(self) -> Difficulty:
        return MODE_BY_KEY[self.save.mode]

    def persist(self) -> None:
        store(self.save, self.save_path)


class Scene:
    """Overlays (pause) are pushed on top of the stack and draw a frozen frame of the scene below."""

    def __init__(self, ctx: Context) -> None:
        self.ctx = ctx

    def enter(self) -> None:
        """Called when the scene becomes active (after a push or switch)."""

    def resume(self) -> None:
        """Called when an overlay above this scene is popped."""

    def handle(self, action: Action | None, event: pygame.Event) -> None:
        """One input event; ``action`` is its mapped game action, if any."""

    def update(self, dt: float) -> None: ...

    def draw(self, surface: pygame.Surface) -> None: ...


def menu_hint(ctx: Context) -> str:
    """Footer of the pickers, in the words of the device in use."""
    if ctx.input.using_pad:
        return "D-PAD trocar  ·  A confirmar  ·  B voltar"
    return "SETAS / A D trocar  ·  ENTER confirmar  ·  ESC voltar"


class MenuScene(Scene):
    """A menu over the shared attract-mode drive. Between two menus only the UI slides; the road stays."""

    dim = 0  # extra darkening of the backdrop
    blur = False

    def __init__(self, ctx: Context) -> None:
        super().__init__(ctx)
        from .backdrop import Backdrop

        self.backdrop = Backdrop.shared(ctx)

    def update(self, dt: float) -> None:
        self.backdrop.update(dt)

    def draw(self, surface: pygame.Surface) -> None:
        self.backdrop.draw(surface, self.dim, self.blur)
        self.draw_ui(surface)

    def draw_ui(self, surface: pygame.Surface) -> None: ...


class Transition(Enum):
    NONE = "none"
    FADE = "fade"
    SLIDE_LEFT = "slide_left"  # new scene comes in from the right
    SLIDE_RIGHT = "slide_right"


DURATION = {Transition.FADE: 0.5, Transition.SLIDE_LEFT: 0.42, Transition.SLIDE_RIGHT: 0.42}


@dataclass
class _Running:
    kind: Transition
    snapshot: pygame.Surface
    previous: Scene | None
    t: float = 0.0

    @property
    def k(self) -> float:
        return min(1.0, self.t / DURATION[self.kind])


class SceneManager:
    def __init__(self, canvas: pygame.Surface) -> None:
        self.canvas = canvas
        self.stack: list[Scene] = []
        self.transition: _Running | None = None
        self._buffer = pygame.Surface((WIDTH, HEIGHT))
        self._black = pygame.Surface((WIDTH, HEIGHT))
        self._ui = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)

    @property
    def top(self) -> Scene:
        return self.stack[-1]

    def push(self, scene: Scene) -> None:
        self.stack.append(scene)
        scene.enter()

    def pop(self) -> None:
        self.stack.pop()
        if self.stack:
            self.top.resume()

    def switch(self, scene: Scene, transition: Transition = Transition.FADE) -> None:
        """Replace the whole stack. The outgoing frame is frozen and animated away."""
        snapshot = self.canvas.copy()
        previous = self.stack[-1] if self.stack else None
        self.stack = [scene]
        scene.enter()
        self.transition = None if transition is Transition.NONE else _Running(transition, snapshot, previous)

    @property
    def busy(self) -> bool:
        """Input is ignored while the outgoing scene is still on screen."""
        return self.transition is not None and self.transition.k < 0.6

    def handle(self, action: Action | None, event: pygame.Event) -> None:
        # losing focus always gets through, so a race that is still fading in can pause itself
        if self.stack and (not self.busy or event.type == pygame.WINDOWFOCUSLOST):
            self.top.handle(action, event)

    def update(self, dt: float) -> None:
        tr = self.transition
        if tr:
            tr.t += dt
            if tr.k >= 1.0:
                self.transition = None
            elif tr.kind is Transition.FADE and tr.k < 0.5:
                return  # the new scene starts once it becomes visible
        if self.stack:
            self.top.update(dt)

    def draw(self, surface: pygame.Surface) -> None:
        tr = self.transition
        if tr is None:
            self.top.draw(surface)
            return
        if tr.kind is Transition.FADE:
            if tr.k < 0.5:
                surface.blit(tr.snapshot, (0, 0))
                self._black.set_alpha(round(255 * in_out_cubic(tr.k * 2)))
            else:
                self.top.draw(surface)
                self._black.set_alpha(round(255 * (1 - in_out_cubic(tr.k * 2 - 1))))
            surface.blit(self._black, (0, 0))
            return
        e = in_out_cubic(tr.k)
        direction = -1 if tr.kind is Transition.SLIDE_LEFT else 1
        old, new = tr.previous, self.top
        if isinstance(old, MenuScene) and isinstance(new, MenuScene):
            self._slide_ui(surface, old, new, e, direction)
            return
        self.top.draw(self._buffer)
        surface.blit(tr.snapshot, (round(direction * WIDTH * e), 0))
        surface.blit(self._buffer, (round(-direction * WIDTH * (1 - e)), 0))

    def _slide_ui(
        self, surface: pygame.Surface, old: MenuScene, new: MenuScene, e: float, direction: int
    ) -> None:
        """The shared road stays put while its blur/dim crossfade; only the two UI layers slide."""
        new.backdrop.draw(surface, new.dim, new.blur)
        old.backdrop.draw(self._buffer, old.dim, old.blur)
        self._buffer.set_alpha(round(255 * (1 - e)))
        surface.blit(self._buffer, (0, 0))
        self._buffer.set_alpha(None)
        for scene, x in ((old, direction * WIDTH * e), (new, -direction * WIDTH * (1 - e))):
            self._ui.fill((0, 0, 0, 0))
            scene.draw_ui(self._ui)
            surface.blit(self._ui, (round(x), 0))
