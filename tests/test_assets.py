"""Asset loading: placeholders in normal mode, errors in strict mode, and the shipped files."""

import pygame
import pytest

from jogo_de_carro.assets import AssetError, Assets, default_root
from jogo_de_carro.settings import ICON_SIZE, MUSIC, SCALE, SOUNDS, SPRITES


@pytest.fixture(autouse=True, scope="module")
def display():
    pygame.init()
    pygame.display.set_mode((64, 64))


def test_missing_assets_become_visible_placeholders(tmp_path, caplog):
    assets = Assets(root=tmp_path, strict=False)
    for name, (w, h, count) in SPRITES.items():
        frames = assets.frames(name)
        assert len(frames) == count
        assert all(f.get_size() == (w * SCALE, h * SCALE) for f in frames)
    assert assets.frame("coin").get_at((4 * SCALE, 0))[:3] == (255, 0, 255)  # loud magenta checker
    assert assets.icon().get_size() == ICON_SIZE
    assert assets.music_path("menu") is None
    assets.sound("coin")  # silent sound (or None without an audio device), never an exception
    assert len(assets.missing) >= len(SPRITES)
    assert "missing asset sprites/coin.png" in caplog.text


def test_strict_mode_raises_on_missing_asset(tmp_path):
    assets = Assets(root=tmp_path, strict=True)
    with pytest.raises(AssetError, match=r"sprites/coin\.png"):
        assets.frames("coin")
    with pytest.raises(AssetError):
        assets.sound("coin")
    with pytest.raises(AssetError):
        assets.music_path("race")


def test_wrong_size_is_rejected(tmp_path):
    (tmp_path / "sprites").mkdir()
    pygame.image.save(pygame.Surface((5, 5)), tmp_path / "sprites" / "cone.png")
    assert Assets(root=tmp_path, strict=False).frame("cone").get_size() == (14 * SCALE, 16 * SCALE)
    with pytest.raises(AssetError, match="expected"):
        Assets(root=tmp_path, strict=True).frames("cone")


def test_strict_env_variable(monkeypatch, tmp_path):
    monkeypatch.setenv("JOGO_STRICT_ASSETS", "1")
    assert Assets(root=tmp_path).strict
    monkeypatch.setenv("JOGO_STRICT_ASSETS", "0")
    assert not Assets(root=tmp_path).strict


@pytest.mark.skipif(not (default_root() / "sprites").is_dir(), reason="assets not generated yet")
def test_shipped_assets_match_the_manifest():
    assets = Assets(strict=True)
    assets.preload()
    assert not assets.missing
    assert {p.stem for p in (default_root() / "sounds").glob("*.wav")} >= set(SOUNDS)
    assert {p.stem for p in (default_root() / "music").glob("*.wav")} >= set(MUSIC)
