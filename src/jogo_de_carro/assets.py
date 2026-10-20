"""Sprites, sounds and music shipped in the package's ``assets`` folder.

Missing files never crash the game in normal mode: sprites become a loud magenta checkerboard of the
manifest size and sounds become silence, each with a one-line warning. Set ``JOGO_STRICT_ASSETS=1`` to
turn any missing or mis-sized asset into an error instead.
"""

import importlib.resources
import logging
import os
from pathlib import Path

import pygame

from .settings import ICON_SIZE, MUSIC, SCALE, SOUNDS, SPRITES

log = logging.getLogger(__name__)
STRICT_ENV = "JOGO_STRICT_ASSETS"


class AssetError(RuntimeError):
    pass


def default_root() -> Path:
    return Path(str(importlib.resources.files(__package__) / "assets"))


def checker(size: tuple[int, int], cell: int = 4) -> pygame.Surface:
    surf = pygame.Surface(size, pygame.SRCALPHA)
    surf.fill((255, 0, 255))
    for y in range(0, size[1], cell):
        for x in range((y // cell) % 2 * cell, size[0], cell * 2):
            surf.fill((20, 0, 20), (x, y, cell, cell))
    return surf


def shrunk_mask(surface: pygame.Surface, sx: float, sy: float) -> pygame.Mask:
    """Mask of ``surface`` scaled by (sx, sy) about its centre, in the original surface's coordinates."""
    w, h = surface.get_size()
    small = pygame.transform.scale(surface, (max(1, round(w * sx)), max(1, round(h * sy))))
    mask = pygame.Mask((w, h))
    mask.draw(pygame.mask.from_surface(small), ((w - small.get_width()) // 2, (h - small.get_height()) // 2))
    return mask


class Assets:
    def __init__(self, root: Path | None = None, strict: bool | None = None) -> None:
        self.root = root or default_root()
        self.strict = os.environ.get(STRICT_ENV) == "1" if strict is None else strict
        self.missing: list[str] = []
        self._native: dict[str, list[pygame.Surface]] = {}
        self._scaled: dict[str, list[pygame.Surface]] = {}
        self._rotated: dict[tuple[str, int, int, bool], pygame.Surface] = {}
        self._masks: dict[tuple[str, int, float, float], pygame.Mask] = {}
        self._bounds: dict[str, pygame.Rect] = {}
        self._shadows: dict[tuple[str, int], pygame.Surface] = {}
        self._sounds: dict[str, pygame.mixer.Sound | None] = {}

    def _problem(self, message: str) -> None:
        if self.strict:
            raise AssetError(message)
        if message not in self.missing:
            self.missing.append(message)
            log.warning("%s - using a placeholder", message)

    def _image(self, rel: str, size: tuple[int, int]) -> pygame.Surface:
        path = self.root / rel
        if not path.is_file():
            self._problem(f"missing asset {rel}")
            return checker(size)
        image = pygame.image.load(path)
        if image.get_size() != size:
            self._problem(f"asset {rel} is {image.get_size()}, expected {size}")
            return checker(size)
        return image.convert_alpha() if pygame.display.get_surface() else image

    # --- sprites -------------------------------------------------------------------------------------

    def native(self, name: str) -> list[pygame.Surface]:
        """Frames at authored resolution."""
        if name not in self._native:
            w, h, count = SPRITES[name]
            sheet = self._image(f"sprites/{name}.png", (w * count, h))
            self._native[name] = [sheet.subsurface((i * w, 0, w, h)).copy() for i in range(count)]
        return self._native[name]

    def frames(self, name: str) -> list[pygame.Surface]:
        """Frames scaled x SCALE with nearest neighbour (crisp pixels)."""
        if name not in self._scaled:
            self._scaled[name] = [pygame.transform.scale_by(f, SCALE) for f in self.native(name)]
        return self._scaled[name]

    def frame(self, name: str, index: int = 0) -> pygame.Surface:
        frames = self.frames(name)
        return frames[index % len(frames)]

    def rotated(self, name: str, index: int, angle: float, flip_x: bool = False) -> pygame.Surface:
        """Rotate at native resolution then scale, so rotated pixel art keeps chunky, even pixels."""
        key = (name, index, round(angle) % 360, flip_x)
        if key not in self._rotated:
            native = self.native(name)[index % len(self.native(name))]
            if flip_x:
                native = pygame.transform.flip(native, True, False)
            self._rotated[key] = pygame.transform.scale_by(pygame.transform.rotate(native, key[2]), SCALE)
        return self._rotated[key]

    def mask(self, name: str, index: int = 0, shrink: tuple[float, float] = (1.0, 1.0)) -> pygame.Mask:
        if name.startswith("car_"):  # one hitbox for every car colour: a skin never changes the race
            name = "car_yellow"
        key = (name, index, *shrink)
        if key not in self._masks:
            self._masks[key] = shrunk_mask(self.frame(name, index), *shrink)
        return self._masks[key]

    def bounds(self, name: str) -> pygame.Rect:
        """Bounding box of the opaque pixels of frame 0, relative to the frame's top-left corner."""
        if name not in self._bounds:  # cached: it is read for every obstacle on every step
            rects = self.mask(name).get_bounding_rects()
            self._bounds[name] = rects[0].unionall(rects[1:]) if rects else self.frame(name).get_rect()
        return self._bounds[name]

    def shadow(self, name: str, index: int = 0) -> pygame.Surface:
        """Soft drop-shadow silhouette of a frame."""
        key = (name, index)
        if key not in self._shadows:
            mask = pygame.mask.from_surface(self.frame(name, index))
            self._shadows[key] = mask.to_surface(setcolor=(10, 12, 24, 95), unsetcolor=(0, 0, 0, 0))
        return self._shadows[key]

    def icon(self) -> pygame.Surface:
        if "icon" not in self._native:
            self._native["icon"] = [self._image("icon.png", ICON_SIZE)]
        return self._native["icon"][0]

    # --- audio ---------------------------------------------------------------------------------------

    def sound(self, name: str) -> pygame.mixer.Sound | None:
        """A Sound, a silent Sound for missing files, or None when there is no audio device."""
        if name not in self._sounds:
            path = self.root / "sounds" / f"{name}.wav"
            found = path.is_file()
            if not found:
                self._problem(f"missing asset sounds/{name}.wav")
            if not pygame.mixer.get_init():
                self._sounds[name] = None
            else:
                self._sounds[name] = (
                    pygame.mixer.Sound(path) if found else pygame.mixer.Sound(buffer=bytes(256))
                )
        return self._sounds[name]

    def music_path(self, name: str) -> Path | None:
        path = self.root / "music" / f"{name}.wav"
        if path.is_file():
            return path
        self._problem(f"missing asset music/{name}.wav")
        return None

    def preload(self) -> None:
        """Touch every manifest entry so problems surface at start-up rather than mid-race."""
        for name in SPRITES:
            self.frames(name)
        self.icon()
        for name in SOUNDS:
            self.sound(name)
        for name in MUSIC:
            self.music_path(name)
