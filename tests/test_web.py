"""Browser-only branches (sys.platform == "emscripten"), run against a stand-in for pygbag's ``window``."""

import platform
import sys
from types import SimpleNamespace

from jogo_de_carro import save


class Storage(dict):
    def getItem(self, key):
        return self.get(key)

    def setItem(self, key, value):
        self[key] = value


def test_save_lives_in_local_storage(monkeypatch, tmp_path):
    storage, path = Storage(), tmp_path / "save.json"
    monkeypatch.setattr(sys, "platform", "emscripten")
    monkeypatch.setattr(platform, "window", SimpleNamespace(localStorage=storage), raising=False)
    assert save.load(path) == save.SaveData()  # nothing stored yet
    data = save.SaveData(skin="pink", muted=True)
    save.store(data, path)
    assert save.load(path) == data
    assert list(storage) == [str(path)] and not path.exists()


def test_full_local_storage_does_not_crash(monkeypatch, tmp_path):
    def full(key, value):
        raise RuntimeError("QuotaExceededError")

    window = SimpleNamespace(localStorage=SimpleNamespace(setItem=full))
    monkeypatch.setattr(sys, "platform", "emscripten")
    monkeypatch.setattr(platform, "window", window, raising=False)
    save.store(save.SaveData(), tmp_path / "save.json")
