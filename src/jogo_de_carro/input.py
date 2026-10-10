"""Keyboard and gamepad events mapped to game actions, plus held-direction state."""

import contextlib
from enum import Enum, auto

import pygame


class Action(Enum):
    UP = auto()
    DOWN = auto()
    LEFT = auto()
    RIGHT = auto()
    CONFIRM = auto()
    BACK = auto()
    PAUSE = auto()
    GIVE_UP = auto()
    FULLSCREEN = auto()
    MUTE = auto()


KEYS = {
    pygame.K_UP: Action.UP,
    pygame.K_w: Action.UP,
    pygame.K_DOWN: Action.DOWN,
    pygame.K_s: Action.DOWN,
    pygame.K_LEFT: Action.LEFT,
    pygame.K_a: Action.LEFT,
    pygame.K_RIGHT: Action.RIGHT,
    pygame.K_d: Action.RIGHT,
    pygame.K_RETURN: Action.CONFIRM,
    pygame.K_KP_ENTER: Action.CONFIRM,
    pygame.K_SPACE: Action.CONFIRM,
    pygame.K_ESCAPE: Action.BACK,
    pygame.K_BACKSPACE: Action.BACK,
    pygame.K_p: Action.PAUSE,
    pygame.K_r: Action.GIVE_UP,
    pygame.K_F11: Action.FULLSCREEN,
    pygame.K_m: Action.MUTE,
}
# SDL joystick numbering for XInput-style pads: A, B, Back/Select, Start (+ 9 = Start on many others)
PAD_BUTTONS = {0: Action.CONFIRM, 1: Action.BACK, 6: Action.PAUSE, 7: Action.PAUSE, 9: Action.PAUSE}
DIRECTIONS = (Action.UP, Action.DOWN, Action.LEFT, Action.RIGHT)
DEADZONE = 0.5


def _direction(x: float, y: float) -> set[Action]:
    """Directions for a stick/hat position (y grows downwards)."""
    out = set()
    if x <= -DEADZONE:
        out.add(Action.LEFT)
    if x >= DEADZONE:
        out.add(Action.RIGHT)
    if y <= -DEADZONE:
        out.add(Action.UP)
    if y >= DEADZONE:
        out.add(Action.DOWN)
    return out


class Input:
    def __init__(self) -> None:
        self._keys: set[Action] = set()
        self._pads: dict[int, set[Action]] = {}  # instance id -> held directions
        self._sticks: dict[int, list[float]] = {}  # instance id -> [x, y] of the left stick
        self._hats: dict[int, tuple[int, int]] = {}
        self._joysticks: dict[int, pygame.joystick.JoystickType] = {}
        self.using_pad = False  # the last input came from a gamepad: on-screen hints show pad buttons

    def translate(self, event: pygame.Event) -> list[Action]:
        """Actions newly triggered by this event (edge-triggered)."""
        if event.type == pygame.KEYDOWN:
            self.using_pad = False
            action = KEYS.get(event.key)
            if action is None:
                return []
            if action in DIRECTIONS:
                self._keys.add(action)
            return [action]
        if event.type == pygame.KEYUP:
            if (action := KEYS.get(event.key)) in DIRECTIONS:
                self._keys.discard(action)
            return []
        if event.type == pygame.WINDOWFOCUSLOST:
            self._keys.clear()
            return []
        if event.type == pygame.JOYDEVICEADDED:
            with contextlib.suppress(pygame.error):  # the pad may already be gone (e.g. a Bluetooth blip)
                joy = pygame.joystick.Joystick(event.device_index)
                self._joysticks[joy.get_instance_id()] = joy
            return []
        if event.type == pygame.JOYDEVICEREMOVED:
            for table in (self._joysticks, self._pads, self._sticks, self._hats):
                table.pop(event.instance_id, None)
            return []
        if event.type == pygame.JOYBUTTONDOWN:
            self.using_pad = True
            action = PAD_BUTTONS.get(event.button)
            return [action] if action else []
        if event.type == pygame.JOYAXISMOTION and event.axis in (0, 1):
            stick = self._sticks.setdefault(event.instance_id, [0.0, 0.0])
            stick[event.axis] = event.value
            return self._update_pad(event.instance_id)
        if event.type == pygame.JOYHATMOTION:
            self._hats[event.instance_id] = event.value
            return self._update_pad(event.instance_id)
        return []

    def _update_pad(self, pad: int) -> list[Action]:
        x, y = self._sticks.get(pad, [0.0, 0.0])
        hx, hy = self._hats.get(pad, (0, 0))
        held = _direction(x, y) | _direction(hx, -hy)  # hat y is +1 for up
        new = held - self._pads.get(pad, set())
        self._pads[pad] = held
        self.using_pad = self.using_pad or bool(new)
        return [a for a in DIRECTIONS if a in new]

    def held(self, action: Action) -> bool:
        return action in self._keys or any(action in dirs for dirs in self._pads.values())

    def vertical(self) -> float:
        """-1 when holding up, +1 when holding down."""
        return float(self.held(Action.DOWN)) - float(self.held(Action.UP))

    def release_all(self) -> None:
        self._keys.clear()
        self._pads.clear()
