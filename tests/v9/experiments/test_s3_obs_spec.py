"""Test GridLab-S3 Student Observation Specification.

Requirements per DESIGN-r2.md §2:
- Observation vector is exactly 198 dimensions, np.float32.
- Student observation strictly contains no absolute coordinates (x, y),
  ground-truth pose, or swap status flags.
- Ground truth is strictly segregated inside the 'truth' key.
"""

from __future__ import annotations

import numpy as np
import pytest

from ainerzero.v9.experiments.s3 import spec
from ainerzero.v9.experiments.s3.data import generate_episode


def test_student_observation_dimension_and_no_leakage() -> None:
    """Verify observation vector length 198 and absence of coordinates in student obs."""
    episode = generate_episode(world_seed=7001, episode_seed=7002, family="F1")

    assert "steps" in episode
    assert len(episode["steps"]) == spec.T

    for step_data in episode["steps"]:
        # 1. Dimension and type checks
        obs = step_data["obs"]
        assert isinstance(obs, np.ndarray), f"Obs must be numpy array, got {type(obs)}"
        assert obs.shape == (spec.OBS_DIM,), f"Obs dimension must be {spec.OBS_DIM}, got {obs.shape}"
        assert obs.dtype == np.float32, f"Obs dtype must be float32, got {obs.dtype}"

        # 2. Key leakage checks on student-visible fields
        # Allowed top-level step keys: 't', 'obs', 'action', 'est_pose', 'truth'
        allowed_keys = {"t", "obs", "action", "est_pose", "truth"}
        assert set(step_data.keys()).issubset(allowed_keys)

        # Ensure absolute coordinates are NOT in top-level step keys
        assert "x" not in step_data
        assert "y" not in step_data
        assert "heading" not in step_data
        assert "swapped" not in step_data

        # 3. Ground truth segregation check
        truth = step_data["truth"]
        assert isinstance(truth, dict)
        assert "x" in truth
        assert "y" in truth
        assert "heading" in truth
        assert "cell_token" in truth

        # 4. Check that observation vector elements are in valid normalized ranges
        # One-hot values are 0.0 or 1.0; bump is 0.0 or 1.0
        assert np.all((obs >= 0.0) & (obs <= 1.0)), "Observation elements must be bounded in [0, 1]"
