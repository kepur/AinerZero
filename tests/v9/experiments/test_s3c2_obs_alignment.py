"""Test S3 Student Observation Token Alignment and Zero Future Leakage.

Requirement per Task P206 parameter v1:
Step-by-step verification that for every visible cell in the student's 3x3 observation,
the token channel strictly equals content_state.get_token(cell, t) (mapping the 3x3 ego
coordinates back to world coordinates via heading).
Must cover steps before and after token swap (t == t_swap - 1 and t == t_swap) across
>= 100 episodes, and hard assert that at least >= 20 token swap boundaries are witnessed.
"""

from __future__ import annotations

import numpy as np
import pytest

from ainerzero.v9.experiments.s3 import spec
from ainerzero.v9.experiments.s3.content import ContentState
from ainerzero.v9.experiments.s3.data import derive_seed, generate_episode
from ainerzero.v9.experiments.s3.world import _ego_to_world_coords


def test_obs_token_alignment_and_no_future_leak() -> None:
    """Step-by-step assert observation token channel equals content_state.get_token(cell, t)."""
    n_episodes = 100
    swap_boundary_observations = 0
    total_visible_token_checks = 0

    for ep_idx in range(n_episodes):
        w_seed = derive_seed("obs-align", "world", ep_idx)
        ep_seed = derive_seed("obs-align", "ep", ep_idx)
        family = "F1" if ep_idx % 2 == 0 else "F2"

        ep = generate_episode(world_seed=w_seed, episode_seed=ep_seed, family=family)
        cstate_dict = ep["content_state"]
        content_state = ContentState(
            content_cells=tuple(tuple(c) for c in cstate_dict["content_cells"]),
            initial_tokens={
                tuple(map(int, k.split(","))): v
                for k, v in cstate_dict["initial_tokens"].items()
            },
            swap_times={
                tuple(map(int, k.split(","))): v
                for k, v in cstate_dict["swap_times"].items()
            },
            new_tokens={
                tuple(map(int, k.split(","))): v
                for k, v in cstate_dict["new_tokens"].items()
            },
            family=cstate_dict["family"],
        )

        steps = ep["steps"]
        swap_times_set = set(content_state.swap_times.values())

        for step_data in steps:
            t = step_data["t"]
            obs = step_data["obs"]
            true_x = step_data["truth"]["x"]
            true_y = step_data["truth"]["y"]
            true_h = step_data["truth"]["heading"]

            # Parse 3x3 ego view features
            view_feats = obs[:spec.VIEW_FEAT_DIM].reshape(spec.VIEW_GRID_SIZE, spec.VIEW_GRID_SIZE, spec.CELL_FEAT_DIM)

            for i in range(spec.VIEW_GRID_SIZE):
                for j in range(spec.VIEW_GRID_SIZE):
                    # In 7x7 ego view, the center is (3, 3). The 3x3 crop uses rows 2..4, cols 2..4.
                    r = 2 + i
                    c = 2 + j

                    # Terrain one-hot: FREE=0, WALL=1, PILLAR=2, UNSEEN=3
                    terrain_one_hot = view_feats[i, j, :spec.NUM_TERRAIN_CLASSES]
                    terrain_type = int(np.argmax(terrain_one_hot))

                    # If cell is UNSEEN (occluded or outside bounds), it cannot observe token
                    if terrain_type == 3:
                        continue

                    # Map ego cell (r, c) to world coordinates (wx, wy)
                    wx, wy = _ego_to_world_coords(true_x, true_y, true_h, r, c)

                    # Extract observed token from student observation
                    token_one_hot = view_feats[i, j, spec.NUM_TERRAIN_CLASSES:spec.CELL_FEAT_DIM]
                    obs_token = int(np.argmax(token_one_hot))

                    # Expected ground-truth token at step t
                    expected_token = content_state.get_token((wx, wy), t)

                    assert obs_token == expected_token, (
                        f"Episode {ep_idx} step {t}: Token alignment mismatch at world cell ({wx}, {wy}) "
                        f"(ego [{i}, {j}], heading {true_h}): observed {obs_token} != expected {expected_token}. "
                        f"Potential future or stale token leak!"
                    )
                    total_visible_token_checks += 1

                    # Check if this visible cell is a content cell at swap boundary (t == t_swap - 1 or t == t_swap)
                    if (wx, wy) in content_state.content_cells:
                        t_swap = content_state.swap_times[(wx, wy)]
                        if t in (t_swap - 1, t_swap):
                            swap_boundary_observations += 1

    print(f"\n[test_s3c2_obs_alignment] Completed {total_visible_token_checks} visible token checks across {n_episodes} episodes.")
    print(f"[test_s3c2_obs_alignment] Total swap boundary checks witnessed: {swap_boundary_observations}")

    # Mandatory assertion per parameter v1: witnessed >= 20 swap boundary transitions
    assert swap_boundary_observations >= 20, (
        f"Insufficient swap boundary coverage: witnessed {swap_boundary_observations} < 20 required"
    )
