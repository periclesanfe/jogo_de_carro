"""Persistent save (best scores, chosen skin, mode and scenery, audio settings) as JSON in the user data dir,
or in localStorage in the browser."""

import json
import logging
import math
import os
import sys
from collections.abc import Container
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .settings import CARS, DEFAULT_MODE, MODE_BY_KEY, SKINS
from .world.road import BIOMES

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
    best_m: int = 0  # the longest race in meters, offline too (a scenery is only a look): it unlocks biomes
    biome: int = 0  # the scenery races start in (world/road.py BIOMES), once unlocked

    def unlocked(self, biome: int) -> bool:
        return self.best_m >= biome * 1000

    def drove(self, meters: float) -> tuple[int, ...]:
        """Store a race's distance; returns the biomes it unlocked."""
        locked = [i for i in range(len(BIOMES)) if not self.unlocked(i)]
        self.best_m = max(self.best_m, int(meters))
        return tuple(i for i in locked if self.unlocked(i))

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
        if isinstance(raw.get("skin"), str) and raw["skin"] in CARS:
            data.skin = raw["skin"]
        if isinstance(raw.get("mode"), str) and raw["mode"] in MODE_BY_KEY:
            data.mode = raw["mode"]
        if isinstance(raw.get("muted"), bool):
            data.muted = raw["muted"]
        if type(raw.get("races")) is int and raw["races"] >= 0:
            data.races = raw["races"]
        if type(raw.get("best_m")) is int and raw["best_m"] >= 0:
            data.best_m = raw["best_m"]
        if type(raw.get("biome")) is int and 0 <= raw["biome"] < len(BIOMES) and data.unlocked(raw["biome"]):
            data.biome = raw["biome"]
        data.best = _numbers(raw.get("best"), MODE_BY_KEY, int)
        data.best_time = _numbers(raw.get("best_time"), MODE_BY_KEY, float)
        data.best_by_skin = _numbers(raw.get("best_by_skin"), CARS, int)
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
