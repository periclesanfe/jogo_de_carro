"""Keyboard and gamepad events map to the same actions."""

import pygame

from jogo_de_carro.input import Action, Input


def ev(kind: int, **attrs) -> pygame.Event:
    return pygame.event.Event(kind, **attrs)


def test_keyboard_actions_and_held_directions():
    inp = Input()
    assert inp.translate(ev(pygame.KEYDOWN, key=pygame.K_a)) == [Action.LEFT]
    assert inp.translate(ev(pygame.KEYDOWN, key=pygame.K_UP)) == [Action.UP]
    assert inp.held(Action.UP) and inp.held(Action.LEFT)
    inp.translate(ev(pygame.KEYUP, key=pygame.K_UP))
    assert not inp.held(Action.UP)
    assert inp.translate(ev(pygame.KEYDOWN, key=pygame.K_ESCAPE)) == [Action.BACK]
    assert inp.translate(ev(pygame.KEYDOWN, key=pygame.K_r)) == [Action.GIVE_UP]
    assert inp.translate(ev(pygame.KEYDOWN, key=pygame.K_q)) == []
    inp.translate(ev(pygame.WINDOWFOCUSLOST))
    assert not inp.held(Action.LEFT)


def test_gamepad_stick_hat_and_buttons():
    inp = Input()
    pad = {"instance_id": 0}
    assert inp.translate(ev(pygame.JOYBUTTONDOWN, button=0, **pad)) == [Action.CONFIRM]
    assert inp.translate(ev(pygame.JOYBUTTONDOWN, button=1, **pad)) == [Action.BACK]
    assert inp.translate(ev(pygame.JOYBUTTONDOWN, button=7, **pad)) == [Action.PAUSE]
    # stick: edge-triggered once when crossing the dead zone, held while deflected
    assert inp.translate(ev(pygame.JOYAXISMOTION, axis=0, value=0.9, **pad)) == [Action.RIGHT]
    assert inp.translate(ev(pygame.JOYAXISMOTION, axis=0, value=0.95, **pad)) == []
    assert inp.held(Action.RIGHT)
    assert inp.translate(ev(pygame.JOYAXISMOTION, axis=0, value=0.1, **pad)) == []
    assert inp.translate(ev(pygame.JOYAXISMOTION, axis=1, value=-0.8, **pad)) == [Action.UP]
    assert inp.held(Action.UP)
    inp.translate(ev(pygame.JOYAXISMOTION, axis=1, value=0.0, **pad))
    # d-pad (hat y is +1 for up)
    assert inp.translate(ev(pygame.JOYHATMOTION, hat=0, value=(0, -1), **pad)) == [Action.DOWN]
    assert inp.held(Action.DOWN) and not inp.held(Action.UP)
    assert inp.translate(ev(pygame.JOYHATMOTION, hat=0, value=(-1, 0), **pad)) == [Action.LEFT]
    inp.translate(ev(pygame.JOYDEVICEREMOVED, **pad))
    assert not inp.held(Action.DOWN)
    assert inp.using_pad
    inp.translate(ev(pygame.KEYDOWN, key=pygame.K_a))
    assert not inp.using_pad


def test_gamepad_that_vanished_before_it_was_opened_is_ignored():
    pygame.joystick.init()
    assert Input().translate(ev(pygame.JOYDEVICEADDED, device_index=99)) == []
