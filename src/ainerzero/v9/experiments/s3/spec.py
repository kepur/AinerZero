"""GridLab-S3 Experiment Specifications and Frozen Constants.

Per reports/V9-S3-DESIGN/DESIGN-r2.md §2, §4, §6.
Zero MLX imports. Pure CPU.
"""

from __future__ import annotations

from typing import Final, Sequence

# Episode length and content budget
T: Final[int] = 360
M: Final[int] = 8

# Token families (disjoint, 8 classes per family)
F1_TOKENS: Final[tuple[int, ...]] = tuple(range(1, 9))
F2_TOKENS: Final[tuple[int, ...]] = tuple(range(9, 17))
ALL_TOKENS: Final[tuple[int, ...]] = tuple(range(1, 17))
NONE_TOKEN: Final[int] = 0

# Odometry slip probability and tour exploration noise
P_SLIP: Final[float] = 0.05
NOISE: Final[float] = 0.10

# Observation specification (198 dimensions total)
VIEW_RADIUS: Final[int] = 1
VIEW_GRID_SIZE: Final[int] = 3  # 3x3 crop from center of 7x7 ego view
NUM_TERRAIN_CLASSES: Final[int] = 4  # FREE=0, WALL=1, PILLAR=2, UNSEEN=3
NUM_TOKEN_CLASSES: Final[int] = 17  # 0 (NONE) + 16 tokens
CELL_FEAT_DIM: Final[int] = NUM_TERRAIN_CLASSES + NUM_TOKEN_CLASSES  # 21
VIEW_FEAT_DIM: Final[int] = (VIEW_GRID_SIZE * VIEW_GRID_SIZE) * CELL_FEAT_DIM  # 9 * 21 = 189
NUM_HEADINGS: Final[int] = 4  # North, East, South, West
NUM_ACTIONS: Final[int] = 4  # Forward, Left, Right, Wait
BUMP_FEAT_DIM: Final[int] = 1  # Proprioceptive bump signal
OBS_DIM: Final[int] = VIEW_FEAT_DIM + NUM_HEADINGS + NUM_ACTIONS + BUMP_FEAT_DIM  # 198

# Return interval lag buckets
# NOTE on lag < 8:
# Return events with lag < 8 steps (e.g. immediate double-step turns/slips)
# have bucket = None. They are excluded from short/mid/long bucket statistics
# and main benchmark evaluations per DESIGN-r2 §2.
BUCKET_SHORT: Final[str] = "short"
BUCKET_MID: Final[str] = "mid"
BUCKET_LONG: Final[str] = "long"
BUCKETS: Final[tuple[tuple[str, int, int], ...]] = (
    (BUCKET_SHORT, 8, 29),
    (BUCKET_MID, 30, 79),
    (BUCKET_LONG, 80, 10**6),
)

# Registered seed namespaces (mutually exclusive)
NAMESPACE_TRAIN: Final[str] = "s3p1-train"
NAMESPACE_DEV: Final[str] = "s3p1-dev"
NAMESPACE_FINAL: Final[str] = "s3p1-final"
NAMESPACE_PROBE: Final[str] = "s3p1-probe"
REGISTERED_NAMESPACES: Final[tuple[str, ...]] = (
    NAMESPACE_TRAIN,
    NAMESPACE_DEV,
    NAMESPACE_FINAL,
    NAMESPACE_PROBE,
)

# Probe P-a criteria thresholds
PA_DISTINCT_CELLS_MEDIAN_MIN: Final[int] = 60
PA_TOP_CELL_FRAC_MAX: Final[float] = 0.15
PA_LONG_SWAPPED_EPISODES_FRAC_MIN: Final[float] = 0.90
PA_SWAPPED_RATIO_MIN: Final[float] = 0.40
PA_SWAPPED_RATIO_MAX: Final[float] = 0.60


def get_bucket(lag: int) -> str | None:
    """Return bucket name for given lag, or None if lag < 8.

    Events with lag < 8 are considered immediate transitions and do not belong
    to any registered time bucket.
    """
    for name, lo, hi in BUCKETS:
        if lo <= lag <= hi:
            return name
    return None
