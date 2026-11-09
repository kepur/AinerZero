"""GridLab-S3 Experiment Package.

Pure CPU, NumPy / standard library only.
Strictly zero MLX imports per reports/V9-S3-DESIGN/DESIGN-r2.md §2.
"""

from __future__ import annotations

import sys

# Assertion to ensure MLX is never loaded into sys.modules
assert not any(
    m == "mlx" or m.startswith("mlx.") for m in sys.modules
), "MLX imported into sys.modules prior to S3 package initialization"

from ainerzero.v9.experiments.s3 import content, data, spec, tour, world
from ainerzero.v9.experiments.s3.content import ContentState, generate_content_state
from ainerzero.v9.experiments.s3.data import (
    derive_seed,
    generate_episode,
    generate_partition,
)
from ainerzero.v9.experiments.s3.tour import extract_readout_events, run_tour
from ainerzero.v9.experiments.s3.world import (
    compute_reverse_bfs_distances,
    compute_student_obs,
    get_connected_free_cells,
    step_to_goal,
    step_with_slip,
    update_odometry,
)

__all__ = [
    "spec",
    "world",
    "content",
    "tour",
    "data",
    "ContentState",
    "generate_content_state",
    "compute_reverse_bfs_distances",
    "step_to_goal",
    "step_with_slip",
    "update_odometry",
    "compute_student_obs",
    "get_connected_free_cells",
    "run_tour",
    "extract_readout_events",
    "generate_episode",
    "generate_partition",
    "derive_seed",
]
