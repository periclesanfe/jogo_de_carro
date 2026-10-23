"""Game-wide constants, the asset manifest and the difficulty presets."""

from collections import namedtuple
from dataclasses import dataclass
from enum import Enum

TITLE = "Jogo de Carro"
WIDTH, HEIGHT = 1280, 720
FPS = 60
FIXED_DT = 1 / 120  # simulation step; rendering runs at FPS
SCALE = 3  # pixel art is authored at native size and scaled x3 (nearest) at load

# --- road -------------------------------------------------------------------------------------------
LANES = 5
LANE_WIDTH = 96
ROAD_LEFT = 400
ROAD_RIGHT = ROAD_LEFT + LANES * LANE_WIDTH  # 880
LANE_CENTERS: tuple[int, ...] = tuple(ROAD_LEFT + LANE_WIDTH // 2 + i * LANE_WIDTH for i in range(LANES))
SHOULDER = 16

# --- player -----------------------------------------------------------------------------------------
START_LANE = 2
PLAYER_Y = 560  # resting screen y of the car centre; also the spawner's reference line
PLAYER_Y_MIN, PLAYER_Y_MAX = 440, 640  # higher up there is no time left to react
LANE_CHANGE_TIME = 0.14
TILT_DEG = 6.0  # more shears the pixel-art outlines
PLAYER_MAX_VY = 460.0  # px/s
PLAYER_VY_RESPONSE = 9.0  # 1/s, how fast vertical velocity follows input (accel + damping)
HITBOX_SHRINK = (0.8, 0.88)  # forgiving player hitbox relative to the sprite
BOOST_SCORE_RATE = 1.15  # holding "up" scores distance 15% faster
START_RAMP_S = 0.7  # seconds to reach cruising speed after "JÁ!"

# --- scoring ----------------------------------------------------------------------------------------
PX_PER_METER = 14.4  # makes km/h = px/s * 0.25, an arcade-feeling speedometer
COIN_POINTS = 10
NEAR_MISS_PX = 30  # only counts when the player was dodging (see World._collide)
NEAR_MISS_POINTS = 25
COMBO_MAX = 5
COMBO_TIME = 2.5

# --- spawning ---------------------------------------------------------------------------------------
SPAWN_Y = -140  # screen y where new rows appear (above the top edge)
DESPAWN_Y = HEIGHT + 140
REACTION_TIME = 0.12  # slack added to every planned lane change
MAX_LANE_SHIFT = 2  # the safe lane moves at most this many lanes between rows
# A shared road (versus, challenges) ignores the player's lane, which makes it harder; rows are spaced out
# by this factor to compensate (the one knob to refit from versus logs).
VERSUS_ROWS = 1.15

# --- runs ---------------------------------------------------------------------------------------------
VERSUS_CAP_S = 600  # a run on a shared road ends here at the latest (Infinito "wins" at the cap)
RANKED_CAP_S = 1800  # same for a solo run


class Kind(Enum):
    CAR = "car"
    VAN = "van"
    TRUCK = "truck"
    STONE = "stone"
    POTHOLE = "pothole"
    CONE = "cone"
    TRUNK = "trunk"

    @property
    def is_traffic(self) -> bool:
        return self in (Kind.CAR, Kind.VAN, Kind.TRUCK)


class Item(Enum):  # the value is the sprite
    COIN = "coin"
    SHIELD = "shield"
    STAR = "star"
    GHOST = "ghost"
    TURBO = "turbo"
    SLOW = "slow"
    LIFE = "life"


SKINS: tuple[str, ...] = ("yellow", "black", "blue", "pink", "red", "white")  # the free cars; traffic's paint
# every car, in the garage's order: key (what runs.skin, the garage table and the save store) -> (name,
# price in coins, 0: free). A name or price changes with no migration; the key never does.
CARS: dict[str, tuple[str, int]] = {
    "yellow": ("Amarelo", 0),
    "black": ("Preto", 0),
    "blue": ("Azul", 0),
    "pink": ("Rosa", 0),
    "red": ("Vermelho", 0),
    "white": ("Branco", 0),
    "beetle": ("Herbie 53", 300),
    "moto": ("Moto", 300),
    "taxi": ("Táxi", 300),
    "kombi": ("Kombi", 300),
    "jdm94": ("Toyota Supra MK4", 800),
    "muscle70": ("Dodge Charger R/T 70", 800),
    "fins59": ("Cadillac Series 62", 800),
    "rc_buggy": ("Carrinho RC (Toy Story)", 800),
    "sedan67": ("Impala 67 (Sobrenatural)", 1500),
    "mystery_van": ("Máquina Mistério", 1500),
    "stone_age": ("Carro dos Flintstones", 1500),
    "formula": ("Fórmula 1", 1500),
    "monster": ("Monster Truck", 1500),
    "robot_camaro": ("Bumblebee", 3000),
    "cyber": ("Cybertruck", 3000),
    "racer5": ("Mach 5", 3000),
    "racer95": ("Relâmpago McQueen", 5000),
    "tank": ("Tanque de Guerra", 5000),
    "bat": ("Batmóvel", 8000),
    "robot_truck": ("Optimus Prime", 8000),
}
PRICE = {k: p for k, (_, p) in CARS.items() if p}
assert tuple(CARS)[: len(SKINS)] == SKINS

# name -> (frame width, frame height, frame count) at native resolution; frames are laid out horizontally.
SPRITES: dict[str, tuple[int, int, int]] = {
    **{f"car_{key}": (24, 40, 2) for key in CARS},
    "truck": (28, 64, 2),
    "van": (26, 48, 2),
    "stone": (24, 22, 1),
    "pothole": (30, 20, 1),
    "trunk": (44, 18, 4),
    "cone": (14, 16, 1),
    "coin": (12, 12, 8),
    "shield": (16, 16, 4),  # every power's icon: one size, so one pickup reach
    "star": (16, 16, 4),
    "ghost": (16, 16, 4),
    "turbo": (16, 16, 4),
    "slow": (16, 16, 4),
    "life": (16, 16, 4),
    "tree": (32, 32, 2),
    "bush": (16, 12, 4),  # green, in flower, dry, snowy
    "lamp": (10, 28, 1),
    "rock_small": (10, 8, 1),
    "flowers": (8, 6, 3),
    "cactus": (14, 26, 2),  # saguaro, barrel
    "pine": (20, 32, 2),  # green, snowy
    "snowman": (12, 16, 1),
    "building": (40, 40, 2),  # rooftops: water tank, air conditioning
    "basalt": (14, 10, 2),
    "lava": (24, 14, 1),
    "blinker": (6, 6, 2),
    "road_tile": (160, 64, 1),
}
ICON_SIZE = (64, 64)
SOUNDS = (
    "coin",
    "crash",
    "near_miss",
    "countdown",
    "go",
    "shield_up",
    "shield_break",
    "ui_move",
    "ui_select",
    "ui_back",
    "record",
    "lane_change",
)
MUSIC = ("menu", "race", "win")

KIND_SPRITE = {Kind.CAR: "car_yellow", **{k: k.value for k in Kind if k is not Kind.CAR}}


def kind_size(kind: Kind) -> tuple[int, int]:
    """On-screen (scaled) size of an obstacle kind."""
    w, h, _ = SPRITES[KIND_SPRITE[kind]]
    return w * SCALE, h * SCALE


PLAYER_SIZE = (SPRITES["car_yellow"][0] * SCALE, SPRITES["car_yellow"][1] * SCALE)
PLAYER_HITBOX = (round(PLAYER_SIZE[0] * HITBOX_SHRINK[0]), round(PLAYER_SIZE[1] * HITBOX_SHRINK[1]))


@dataclass(frozen=True)
class Difficulty:
    key: str
    name: str
    win_s: float | None
    base_speed: float
    ramp: float
    max_speed: float
    max_blocked: int
    traffic_lane_change: float
    unlocks: tuple[tuple[Kind, float], ...]  # (kind, seconds into the run when it starts appearing)
    row_time: tuple[float, float]  # seconds between obstacle rows at the start / after RAMP_ROWS_S
    color: tuple[int, int, int]
    late_blocked: tuple[float, int] | None = None  # (after seconds, max_blocked) for Infinito
    path_bias: float = 12.0  # how strongly the guaranteed free lane follows the player's lane
    description: str = ""


_BASIC = ((Kind.CAR, 0.0), (Kind.STONE, 0.0), (Kind.POTHOLE, 0.0), (Kind.CONE, 0.0))

FACIL = Difficulty(
    key="facil",
    name="Fácil",
    win_s=90,
    base_speed=320,
    ramp=5.0,
    max_speed=520,
    max_blocked=2,
    traffic_lane_change=0.30,
    unlocks=(*_BASIC, (Kind.VAN, 40.0), (Kind.TRUNK, 45.0)),
    row_time=(1.05, 0.9),
    color=(99, 199, 77),
    path_bias=3.0,  # stronger makes Fácil passive: fewer lane changes
    description="Para aquecer os motores",
)
NORMAL = Difficulty(
    key="normal",
    name="Normal",
    win_s=180,
    base_speed=380,
    ramp=5.5,
    max_speed=700,
    max_blocked=3,
    traffic_lane_change=0.60,
    unlocks=(*_BASIC, (Kind.VAN, 15.0), (Kind.TRUNK, 25.0), (Kind.TRUCK, 60.0)),
    row_time=(0.92, 0.72),
    color=(44, 160, 230),
    description="A estrada de sempre",
)
DIFICIL = Difficulty(
    key="dificil",
    name="Difícil",
    win_s=270,
    base_speed=460,
    ramp=7.0,
    max_speed=860,
    max_blocked=4,
    traffic_lane_change=1.0,
    unlocks=(*_BASIC, (Kind.VAN, 0.0), (Kind.TRUNK, 0.0), (Kind.TRUCK, 10.0)),
    row_time=(0.84, 0.62),
    color=(247, 118, 34),
    description="Só para pilotos de verdade",
)
INFINITO = Difficulty(
    key="infinito",
    name="Infinito",
    win_s=None,
    base_speed=380,
    ramp=6.0,
    max_speed=980,
    max_blocked=3,
    traffic_lane_change=0.75,
    unlocks=(*_BASIC, (Kind.VAN, 15.0), (Kind.TRUNK, 30.0), (Kind.TRUCK, 60.0)),
    row_time=(0.92, 0.6),
    color=(181, 80, 218),
    late_blocked=(120.0, 4),
    description="Até onde você aguenta?",
)
MODES: tuple[Difficulty, ...] = (FACIL, NORMAL, DIFICIL, INFINITO)
MODE_BY_KEY = {m.key: m for m in MODES}
DEFAULT_MODE = NORMAL.key

# --- palette (UI) -----------------------------------------------------------------------------------
INK = (26, 28, 44)
WHITE = (244, 244, 244)
MUTED = (148, 156, 180)
ACCENT = (255, 205, 60)
FLAME = (247, 118, 34)
DANGER = (235, 70, 70)
CYAN = (65, 220, 240)
PANEL = (22, 24, 38)
GOLD = (255, 214, 90)
LAVENDER = (190, 160, 255)
SKY = (140, 180, 255)
PINK = (255, 120, 150)  # a life gained; DANGER is the one lost

# --- power-ups --------------------------------------------------------------------------------------
# One slot: picking a power up replaces the one on (the extra life is kept apart, in Player.lives). seconds
# are real seconds; weight is the spawner's draw. Capped powers never show in Infinito: its run "wins" at the
# input cap, which a slow clock would reach first, and an extra life would inflate it.
Power = namedtuple("Power", "label colour seconds weight capped")
POWERS = {  # the dict order is the draw order: reordering it changes the GOLDEN
    Item.SHIELD: Power("ESCUDO", CYAN, 8.0, 3, False),
    Item.STAR: Power("ESTRELA", GOLD, 5.0, 2, False),
    Item.GHOST: Power("FANTASMA", LAVENDER, 6.0, 2, False),
    Item.TURBO: Power("TURBO", FLAME, 4.0, 2, False),
    Item.SLOW: Power("DEVAGAR", SKY, 4.0, 2, True),
    Item.LIFE: Power("VIDA EXTRA", PINK, 0.0, 1, True),
}
# the world's clock (exact binary fractions: plain IEEE products); the player's car keeps real time
TIME_SCALE = {Item.SLOW: 0.5, Item.TURBO: 1.5}
# nothing hurts; TURBO has to protect: a two-lane change on its clock can outlast the corridor's window
PROTECT = {Item.STAR, Item.GHOST, Item.TURBO}
NO_NEAR_MISS = PROTECT | {Item.SLOW}
