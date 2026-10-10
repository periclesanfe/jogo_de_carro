"""Music and sound effects with a global mute. Silently does nothing without an audio device."""

import pygame

from .assets import Assets

MUSIC_VOLUME = 0.5
PAUSED_VOLUME = 0.12  # the music keeps playing quietly under the pause menu
SFX_VOLUME = 0.8


class Audio:
    def __init__(self, assets: Assets, muted: bool = False) -> None:
        self.assets = assets
        self.muted = muted
        self.paused = False
        self.enabled = pygame.mixer.get_init() is not None
        self.track: str | None = None
        if self.enabled:
            pygame.mixer.set_num_channels(24)

    def play(self, name: str, volume: float = 1.0) -> None:
        if not self.enabled or self.muted:
            return
        sound = self.assets.sound(name)
        if sound is not None:
            sound.set_volume(volume * SFX_VOLUME)
            sound.play()

    def music(self, name: str, loop: bool = True, fade_ms: int = 700) -> None:
        if not self.enabled or (name == self.track and pygame.mixer.music.get_busy()):
            return
        path = self.assets.music_path(name)
        self.track, self.paused = name, False
        if path is None:
            pygame.mixer.music.stop()
            return
        pygame.mixer.music.load(path)
        pygame.mixer.music.set_volume(self._music_volume())
        pygame.mixer.music.play(-1 if loop else 0, fade_ms=fade_ms)

    def stop_music(self, fade_ms: int = 500) -> None:
        self.track = None
        if self.enabled:
            pygame.mixer.music.fadeout(fade_ms)

    def pause_music(self, paused: bool) -> None:
        """Duck the music. Never mixer.music.pause()/unpause(): in SDL_mixer 2.8 they can deadlock against
        the callback that runs when a sound effect ends."""
        self.paused = paused
        if self.enabled:
            pygame.mixer.music.set_volume(self._music_volume())

    def _music_volume(self) -> float:
        if self.muted:
            return 0.0
        return PAUSED_VOLUME if self.paused else MUSIC_VOLUME

    def toggle_mute(self) -> bool:
        self.muted = not self.muted
        if self.enabled:
            pygame.mixer.music.set_volume(self._music_volume())
            if self.muted:
                pygame.mixer.stop()
        return self.muted
