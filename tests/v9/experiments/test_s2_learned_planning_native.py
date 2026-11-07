"""Native (MLX) smoke of learned planning: one decision per arm on a real GridLab-S2 obs.

Collected only with ``--native-mlx`` (see tests/conftest.py NATIVE_MODULES).
"""

from __future__ import annotations

import random

import mlx.core  # noqa: F401  (native module: module-level MLX import)
import numpy as np
import pytest

from ainerzero.v9.experiments.s2 import learned_planning as lp
from ainerzero.v9.experiments.s2 import spec, world
from ainerzero.v9.experiments.s2.fwd_counter import ForwardCounter

pytestmark = pytest.mark.native_mlx


def _obs_pair() -> tuple[dict, dict]:
    layout, pairs, _ = world.prepare_world_with_long_pairs(20001, random.Random(20001), n_long_pairs=1)
    start = pairs[0]["start"]
    goal = pairs[0]["goal"]
    st = world.State(x=start["x"], y=start["y"], heading=start["heading"]) if isinstance(start, dict) else world.State(*start[:3])
    gs = world.State(x=goal["x"], y=goal["y"], heading=goal["heading"]) if isinstance(goal, dict) else world.State(*goal[:3])
    obs = world.student_obs(layout, st, last_action=world.ACTION_WAIT, dt=1)
    goal_obs = {
        "view": world.compute_ego_view(layout, gs.x, gs.y, gs.heading),
        "heading": [1 if i == gs.heading else 0 for i in range(4)],
    }
    return obs, goal_obs


def test_native_one_decision_per_arm_respects_budget() -> None:
    from ainerzero.v9.experiments.s2 import adapters_mlx

    obs, goal_obs = _obs_pair()
    for arm_id in ("arm_a", "arm_b", "arm_c"):
        arm = adapters_mlx.make_mlx_arm(arm_id)
        arm.init(42)
        kind = lp.arm_kind_of(arm_id)
        choice = dict(spec.SMOKE_PLAN_CHOICE[kind])
        plan_fn = lp.make_plan_fn(arm, arm_id, choice, int(spec.N_FWD))
        counter = ForwardCounter(budget=int(spec.N_FWD))
        counter.begin_episode()
        res = plan_fn(obs, goal_obs, 1, counter, np.random.default_rng(42))
        assert 0 < counter.total <= int(spec.N_FWD)
        assert counter.by_name.get("encode", 0) == 2
        if kind == "hierarchical":
            assert counter.by_name.get("encode_l2", 0) > 0 and counter.by_name.get("predict_l2", 0) > 0
        assert np.asarray(res.actions).size >= 1
