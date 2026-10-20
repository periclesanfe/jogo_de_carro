"""Persistent save (best scores, chosen skin and mode, audio settings) as JSON in the user data dir, or in
localStorage in the browser."""

import json
import logging
import math
import os
import sys
from collections.abc import Container
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .settings import DEFAULT_MODE, MODE_BY_KEY, SKINS

log = logging.getLogger(__name__)
APP_DIR = "jogo-de-carro"


def default_save_path() -> Path:
    if override := os.environ.get("JOGO_SAVE_DIR"):
        return Path(override) / "save.json"
    home = Path.home()
    if sys.platform == "darwin":
        base = home / "Library" / "Application Support"
    elif sys.platform == "win32":
        base = Path(os.environ.get("APPDATA") or home / "AppData" / "Roaming")
    else:
        base = Path(os.environ.get("XDG_DATA_HOME") or home / ".local" / "share")
    return base / APP_DIR / "save.json"


@dataclass
class SaveData:
    skin: str = SKINS[0]
    mode: str = DEFAULT_MODE
    muted: bool = False
    best: dict[str, int] = field(default_factory=dict)  # best score per mode key
    best_time: dict[str, float] = field(default_factory=dict)  # longest survival per mode key
    best_by_skin: dict[str, int] = field(default_factory=dict)
    races: int = 0

    def record(self, mode: str, skin: str, score: int, seconds: float) -> bool:
        """Store a finished race; returns True when it beat the previous best of that mode."""
        self.races += 1
        self.best_time[mode] = max(self.best_time.get(mode, 0.0), round(seconds, 2))
        self.best_by_skin[skin] = max(self.best_by_skin.get(skin, 0), score)
        if score > self.best.get(mode, 0):
            self.best[mode] = score
            return True
        return False

    @classmethod
    def from_json(cls, raw: object) -> "SaveData":
        """Build from untrusted JSON, keeping only well-typed known values."""
        data = cls()
        if not isinstance(raw, dict):
            return data
        if raw.get("skin") in SKINS:
            data.skin = raw["skin"]
        if isinstance(raw.get("mode"), str) and raw["mode"] in MODE_BY_KEY:
            data.mode = raw["mode"]
        if isinstance(raw.get("muted"), bool):
            data.muted = raw["muted"]
        if type(raw.get("races")) is int and raw["races"] >= 0:
            data.races = raw["races"]
        data.best = _numbers(raw.get("best"), MODE_BY_KEY, int)
        data.best_time = _numbers(raw.get("best_time"), MODE_BY_KEY, float)
        data.best_by_skin = _numbers(raw.get("best_by_skin"), SKINS, int)
        return data


def _numbers[T: (int, float)](raw: object, keys: Container[str], kind: type[T]) -> dict[str, T]:
    if not isinstance(raw, dict):
        return {}
    return {
        k: kind(v)
        for k, v in raw.items()
        if k in keys and type(v) in (int, float) and math.isfinite(v) and v >= 0
    }


def _read(path: Path) -> str:
    if sys.platform == "emscripten":  # browser (pygbag): the FS is in-memory, localStorage persists
        import platform

        raw = platform.window.localStorage.getItem(str(path))
        if raw is None:
            raise FileNotFoundError(path)
        return str(raw)
    return path.read_text(encoding="utf-8")


def load(path: Path) -> SaveData:
    try:
        return SaveData.from_json(json.loads(_read(path)))
    except FileNotFoundError:
        return SaveData()
    except Exception as exc:  # untrusted input: any surprise means a fresh save, never a crash
        log.warning("save %s unreadable (%s); starting fresh", path, exc)
        return SaveData()


def store(data: SaveData, path: Path) -> None:
    """Atomic write; a failing disk (or a full or blocked localStorage) must never crash the game."""
    text = json.dumps(asdict(data), indent=2, ensure_ascii=False)
    if sys.platform == "emscripten":
        import platform

        try:
            platform.window.localStorage.setItem(str(path), text)
        except Exception as exc:
            log.warning("could not write save %s: %s", path, exc)
        return
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(text, encoding="utf-8")
        os.replace(tmp, path)
    except OSError as exc:
        log.warning("could not write save %s: %s", path, exc)
