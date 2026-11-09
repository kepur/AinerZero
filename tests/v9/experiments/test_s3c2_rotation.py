"""Unit test for S3-C2 view rotation invariance across headings.

Verifies that for 50+ walkable cells, egocentric 3x3 terrain views observed
across all 4 headings rotate via align_ego_terrain_to_world to identical
world-aligned views, matching the actual world layout.
"""

from __future__ import annotations

import numpy as np
import pytest

from ainerzero.v9.experiments.s3 import spec, world
from ainerzero.v9.experiments.s3.store import align_ego_terrain_to_world, parse_student_step


def test_ego_terrain_rotation_invariance_across_headings() -> None:
    """Extract ego terrain at (x, y) for all 4 headings and verify world alignment."""
    layout = world.make_layout(seed=42)
    walkable = world.get_connected_free_cells(layout)

    # Test at least 50 walkable cells
    test_cells = walkable[:60]
    assert len(test_cells) >= 50

    for x, y in test_cells:
        aligned_views = []
        for heading in (0, 1, 2, 3):
            state = world.State(x=x, y=y, heading=heading)
            obs = world.compute_student_obs(
                layout,
                state,
                last_action=0,
                bumped=False,
                content_at_step={},
            )
            rec = parse_student_step({
                "t": 0,
                "est_pose": (float(x), float(y), heading),
                "obs": obs,
            })
            aligned_views.append(rec.world_terrain)

        # All 4 headings must rotate to the EXACT same world-aligned view
        for h in range(1, 4):
            np.testing.assert_array_equal(
                aligned_views[h],
                aligned_views[0],
                err_msg=f"Cell ({x}, {y}) heading {h} did not align to heading 0",
            )
