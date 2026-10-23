"""Difficulty curves, scoring/combo and the save file."""

import itertools
import json
import math
from decimal import Decimal, localcontext

import pytest

from jogo_de_carro import save
from jogo_de_carro.settings import COMBO_MAX, COMBO_TIME, FIXED_DT, MODES, NEAR_MISS_POINTS, PX_PER_METER
from jogo_de_carro.tween import STEP_DECAY
from jogo_de_carro.world.difficulty import max_blocked_at, pow_08, row_gap, speed_at, unlocked_kinds
from jogo_de_carro.world.scoring import Score

TIMES = [i * 0.5 for i in range(2000)]  # 0 .. 1000 s


@pytest.mark.parametrize("mode", MODES, ids=lambda m: m.key)
def test_difficulty_is_monotonic_and_capped(mode):
    speeds = [speed_at(mode, t) for t in TIMES]
    assert speeds[0] == mode.base_speed
    assert all(a <= b for a, b in itertools.pairwise(speeds))
    assert max(speeds) == mode.max_speed

    blocked = [max_blocked_at(mode, t) for t in TIMES]
    assert all(a <= b for a, b in itertools.pairwise(blocked))
    assert blocked[0] >= 1 and blocked[-1] == (mode.late_blocked or (0, mode.max_blocked))[1] <= 4

    gaps = [row_gap(mode, t, speed_at(mode, t)) / speed_at(mode, t) for t in TIMES]
    assert all(a >= b - 1e-9 for a, b in itertools.pairwise(gaps)), "rows only get denser"

    kinds = [len(unlocked_kinds(mode, t)) for t in TIMES]
    assert all(a <= b for a, b in itertools.pairwise(kinds))


def test_libm_free_math_is_exact():
    with localcontext() as ctx:
        ctx.prec = 50
        for rate, k in STEP_DECAY.items():  # the literals are exp(-rate * FIXED_DT), correctly rounded
            assert k == float(Decimal(-rate * FIXED_DT).exp())
        for t in [*TIMES[1:], 1e-9, FIXED_DT, 3 + FIXED_DT, 1803.0]:
            exact = float(Decimal(t) ** (Decimal(4) / 5))
            assert abs(pow_08(t) - exact) <= math.ulp(exact)
    assert pow_08(0.0) == pow_08(-1.0) == pow_08(math.nan) == pow_08(1e-300) == 0.0 < pow_08(math.inf) < 1e50


def test_modes_keep_relative_order_and_original_win_times():
    facil, normal, dificil, infinito = MODES
    assert [m.win_s for m in MODES] == [90, 180, 270, None]
    assert facil.max_speed < normal.max_speed < dificil.max_speed < infinito.max_speed
    assert facil.base_speed < normal.base_speed < dificil.base_speed
    assert facil.max_blocked < normal.max_blocked < dificil.max_blocked


def test_score_combo_builds_caps_and_decays():
    s = Score()
    gained = [s.near_miss() for _ in range(COMBO_MAX + 2)]
    assert gained[:3] == [NEAR_MISS_POINTS, 2 * NEAR_MISS_POINTS, 3 * NEAR_MISS_POINTS]
    assert s.combo == COMBO_MAX and gained[-1] == COMBO_MAX * NEAR_MISS_POINTS
    s.update(COMBO_TIME - 0.1)
    assert s.combo == COMBO_MAX
    s.update(0.2)
    assert s.combo == 0 and s.best_combo == COMBO_MAX
    assert s.near_miss() == NEAR_MISS_POINTS  # combo restarts


def test_score_total_and_boost():
    s = Score()
    s.drive(PX_PER_METER * 100, boosting=False)
    s.drive(PX_PER_METER * 100, boosting=True)
    s.coin()
    s.near_miss()
    assert round(s.meters) == 200
    assert s.total == 100 + 115 + 10 + NEAR_MISS_POINTS


def test_save_roundtrip(tmp_path):
    path = tmp_path / "nested" / "save.json"
    data = save.load(path)  # missing file -> defaults
    assert data == save.SaveData()
    data.skin, data.mode, data.muted = "pink", "dificil", True
    assert data.record("dificil", "pink", 1234, 61.5) is True
    assert data.record("dificil", "pink", 1000, 70.0) is False
    save.store(data, path)
    loaded = save.load(path)
    assert loaded == data
    assert loaded.best == {"dificil": 1234} and loaded.best_time == {"dificil": 70.0}
    assert loaded.races == 2


@pytest.mark.parametrize(
    "content",
    [
        "{not json",
        "",
        "[]",
        "null",
        json.dumps({"skin": "purple", "mode": 3, "muted": "yes", "best": {"normal": "9", "x": 5}}),
        json.dumps({"best": {"normal": -5, "facil": True}, "races": -1}),
        '{"best": {"normal": Infinity, "facil": NaN}, "races": true}',
        json.dumps({"mode": []}),
        json.dumps({"mode": {"x": 1}}),
        '{"best": {"normal": ' + "9" * 400 + "}}",
        "[" * 200_000,
    ],
    ids=lambda c: c[:40],
)
def test_corrupt_save_falls_back_to_defaults(tmp_path, content):
    path = tmp_path / "save.json"
    path.write_text(content, encoding="utf-8")
    data = save.load(path)
    assert data.skin == "yellow" and data.mode == "normal" and data.muted is False
    assert data.best == {} and data.races == 0
    save.store(data, path)  # and it can be overwritten afterwards
    assert save.load(path) == data


def test_partial_save_keeps_valid_fields(tmp_path):
    path = tmp_path / "save.json"
    raw = {"skin": "tank", "best": {"normal": 50, "bogus": 1}, "best_by_skin": {"tank": 7, "purple": 1}}
    path.write_text(json.dumps(raw), encoding="utf-8")
    data = save.load(path)
    assert data.skin == "tank" and data.best == {"normal": 50} and data.best_by_skin == {"tank": 7}


def test_a_scenery_is_kept_once_a_race_unlocked_it(tmp_path):
    data = save.SaveData()
    assert data.drove(999.9) == () and data.best_m == 999
    assert data.drove(2500.4) == (1, 2) and data.drove(1800.0) == () and data.best_m == 2500  # Deserto, Neve
    data.biome = 2
    path = tmp_path / "save.json"
    save.store(data, path)
    assert save.load(path) == data
    for raw, best_m, biome in [
        ({"best_m": 2500, "biome": 3}, 2500, 0),  # not reached yet
        ({"best_m": 9000, "biome": 5}, 9000, 0),
        ({"best_m": 9000, "biome": -1}, 9000, 0),
        ({"best_m": 9000, "biome": True}, 9000, 0),
        ({"best_m": 9000, "biome": "4"}, 9000, 0),
        ({"best_m": 4000.0, "biome": 4}, 0, 0),
        ({"best_m": -5, "biome": 0}, 0, 0),
    ]:
        path.write_text(json.dumps(raw), encoding="utf-8")
        assert (save.load(path).best_m, save.load(path).biome) == (best_m, biome), raw


def test_unwritable_save_does_not_crash(tmp_path):
    blocker = tmp_path / "file"
    blocker.write_text("x")
    save.store(save.SaveData(), blocker / "save.json")  # parent is a file -> OSError swallowed
