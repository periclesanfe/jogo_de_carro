"""Score = distance (m) + coins + near-miss bonuses (with a decaying combo)."""

from dataclasses import dataclass

from ..settings import (
    BOOST_SCORE_RATE,
    COIN_POINTS,
    COMBO_MAX,
    COMBO_TIME,
    NEAR_MISS_POINTS,
    PX_PER_METER,
)


@dataclass
class Score:
    meters: float = 0.0  # real distance driven
    distance_points: float = 0.0  # meters, but boosted while accelerating
    coins: int = 0
    near_misses: int = 0
    bonus: int = 0
    combo: int = 0
    best_combo: int = 0
    combo_timer: float = 0.0

    def drive(self, px: float, boosting: bool) -> None:
        m = px / PX_PER_METER
        self.meters += m
        self.distance_points += m * (BOOST_SCORE_RATE if boosting else 1.0)

    def coin(self) -> int:
        self.coins += 1
        return COIN_POINTS

    def near_miss(self) -> int:
        """Register a near miss; returns the points it was worth."""
        self.combo = min(self.combo + 1, COMBO_MAX)
        self.best_combo = max(self.best_combo, self.combo)
        self.combo_timer = COMBO_TIME
        self.near_misses += 1
        points = NEAR_MISS_POINTS * self.combo
        self.bonus += points
        return points

    def update(self, dt: float) -> None:
        if self.combo:
            self.combo_timer -= dt
            if self.combo_timer <= 0:
                self.combo, self.combo_timer = 0, 0.0

    @property
    def total(self) -> int:
        return int(self.distance_points) + self.coins * COIN_POINTS + self.bonus
