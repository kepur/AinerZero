"""GridLab-S3 Episodic Memory Store.

Per reports/V9-S3-DESIGN/DESIGN-r2.md §3 and task P206 specification.
Pure CPU, NumPy / standard library only. Zero MLX imports.
"""

from __future__ import annotations

from dataclasses import dataclass
import random
from typing import Any, Sequence

import numpy as np

from ainerzero.v9.experiments.s3 import spec


@dataclass(frozen=True)
class EpisodicRecord:
    """A single memory record recorded at step t.

    Attributes:
        t: Step index in the episode.
        est_pose: Estimated pose (ex, ey, eh) from odometry.
        world_terrain: 3x3 int8 array of terrain classes aligned to world orientation.
        observed_token: Token observed at the agent's center cell (0 if none).
    """

    t: int
    est_pose: tuple[float, float, int]
    world_terrain: np.ndarray
    observed_token: int

    def __post_init__(self) -> None:
        assert isinstance(self.t, int)
        assert len(self.est_pose) == 3
        assert isinstance(self.world_terrain, np.ndarray)
        assert self.world_terrain.shape == (spec.VIEW_GRID_SIZE, spec.VIEW_GRID_SIZE)
        assert isinstance(self.observed_token, int)


def align_ego_terrain_to_world(
    ego_terrain: np.ndarray,
    heading: int,
) -> np.ndarray:
    """Rotate 3x3 egocentric terrain grid to world orientation.

    Heading: 0=NORTH, 1=EAST, 2=SOUTH, 3=WEST.
    In GridLab egocentric coordinates (where row 0 is ahead, col 0 is left),
    rotating back to world coordinates requires np.rot90 with k=(-heading) % 4.
    """
    assert ego_terrain.shape == (spec.VIEW_GRID_SIZE, spec.VIEW_GRID_SIZE)
    return np.rot90(ego_terrain, k=(-heading) % 4)


def parse_student_step(
    step_data: dict[str, Any],
) -> EpisodicRecord:
    """Parse student-visible step dictionary into an EpisodicRecord.

    Strictly reads ONLY student-visible fields: 't', 'obs', 'est_pose'.
    Never touches, reads, or caches any 'truth' key.
    """
    t = int(step_data["t"])
    est_pose = (
        float(step_data["est_pose"][0]),
        float(step_data["est_pose"][1]),
        int(step_data["est_pose"][2]),
    )
    obs = step_data["obs"]
    assert obs.shape == (spec.OBS_DIM,)

    # 189 terrain and token features for 3x3 ego view
    # 9 cells, each 21 dims (4 terrain one-hot, 17 token one-hot)
    view_feats = obs[:spec.VIEW_FEAT_DIM].reshape(spec.VIEW_GRID_SIZE, spec.VIEW_GRID_SIZE, spec.CELL_FEAT_DIM)

    # 4-dim terrain one-hot at each cell: FREE=0, WALL=1, PILLAR=2, UNSEEN=3
    ego_terrain = np.argmax(view_feats[:, :, :spec.NUM_TERRAIN_CLASSES], axis=-1).astype(np.int8)

    # Heading from est_pose (or student heading one-hot at obs[189:193])
    heading = est_pose[2]
    world_terrain = align_ego_terrain_to_world(ego_terrain, heading)

    # Observed token at agent's center cell (local row 1, col 1 in 3x3 grid)
    center_token_one_hot = view_feats[1, 1, spec.NUM_TERRAIN_CLASSES : spec.CELL_FEAT_DIM]
    observed_token = int(np.argmax(center_token_one_hot))

    return EpisodicRecord(
        t=t,
        est_pose=est_pose,
        world_terrain=world_terrain,
        observed_token=observed_token,
    )


class EpisodicStore:
    """Episodic memory store holding within-episode records.

    Invariants:
    - Records contain strictly student-visible fields (no truth coordinates).
    - Clear at end of episode; zero cross-episode parameter modification.
    """

    def __init__(self) -> None:
        self._records: list[EpisodicRecord] = []

    def add_step(self, step_data: dict[str, Any]) -> EpisodicRecord:
        """Parse student step data and record into store."""
        rec = parse_student_step(step_data)
        self._records.append(rec)
        return rec

    def add_record(self, record: EpisodicRecord) -> None:
        """Directly add a pre-constructed EpisodicRecord."""
        self._records.append(record)

    def clear(self) -> None:
        """Clear all records at end of episode."""
        self._records.clear()

    def get_pool(self, query_t: int, gap: int = 5) -> list[EpisodicRecord]:
        """Return memory pool excluding records from the most recent `gap` steps.

        Only records with r.t <= query_t - gap are eligible for retrieval.
        """
        max_t = query_t - gap
        if max_t < 0:
            return []
        return [r for r in self._records if r.t <= max_t]

    def shuffle_tokens(self, rng: random.Random) -> EpisodicStore:
        """Return a negative-control store with permuted tokens across records.

        Terrain, estimated poses, and timestamps remain completely unchanged,
        while token-location association is destroyed.
        """
        new_store = EpisodicStore()
        if not self._records:
            return new_store

        tokens = [r.observed_token for r in self._records]
        rng.shuffle(tokens)

        for r, tok in zip(self._records, tokens):
            new_store.add_record(
                EpisodicRecord(
                    t=r.t,
                    est_pose=r.est_pose,
                    world_terrain=r.world_terrain.copy(),
                    observed_token=tok,
                )
            )
        return new_store

    def __len__(self) -> int:
        return len(self._records)

    def __getitem__(self, idx: int) -> EpisodicRecord:
        return self._records[idx]

    def __iter__(self):
        return iter(self._records)
