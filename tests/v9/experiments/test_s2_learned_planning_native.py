"""Native (MLX) smoke of learned planning: one decision per arm on a real GridLab-S2 obs.

Collected only with ``--native-mlx`` (see tests/conftest.py NATIVE_MODULES).
"""

from __future__ import annotations

import random
import time

import mlx.core  # noqa: F401  (native module: module-level MLX import)
import numpy as np
import pytest

from ainerzero.v9.experiments.s2 import learned_planning as lp
from ainerzero.v9.experiments.s2 import planner, spec, world
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


def test_native_batching_wall_clock_and_parity_per_arm() -> None:
    """Benchmark and verify parity between batched and unbatched reference across 3 MLX arms."""
    from ainerzero.v9.experiments.s2 import adapters_mlx

    obs, goal_obs = _obs_pair()
    timing_records = {}

    for arm_id in ("arm_a", "arm_b", "arm_c"):
        arm = adapters_mlx.make_mlx_arm(arm_id)
        arm.init(42)
        kind = lp.arm_kind_of(arm_id)
        choice = dict(spec.SMOKE_PLAN_CHOICE[kind])
        n_fwd = int(spec.N_FWD)

        # 1. Batched plan_fn
        plan_fn_b = lp.make_plan_fn(arm, arm_id, choice, n_fwd)
        counter_b = ForwardCounter(budget=n_fwd)
        counter_b.begin_episode()
        t0 = time.perf_counter()
        res_b = plan_fn_b(obs, goal_obs, 1, counter_b, np.random.default_rng(100))
        t_batched = time.perf_counter() - t0

        # 2. Sequential reference
        cfg = lp.cem_config_for_budget(arm_id, choice, n_fwd)
        counter_r = ForwardCounter(budget=n_fwd)
        counter_r.begin_episode()
        t0 = time.perf_counter()
        enc_r = counter_r.wrap("encode", arm.encode)
        p1_r = counter_r.wrap("predict_l1", arm.predict_l1)
        x_obs = lp.featurize_obs(obs, 1)
        x_goal = lp.featurize_goal(goal_obs)

        if kind == "flat":
            dts = np.full(cfg.horizon, float(spec.PLAN_FUTURE_DT_L1), dtype=np.float64)
            dts[0] = 1.0
            res_r = planner.flat_cem_plan_reference(
                encode=enc_r,
                predict_l1=p1_r,
                obs=x_obs,
                goal_obs=x_goal,
                config=cfg,
                rng=np.random.default_rng(100),
                counter=counter_r,
                dts=dts,
                cost_mode=spec.PLAN_COST_TRAJECTORY_SUM,
            )
        else:
            enc2_r = counter_r.wrap("encode_l2", arm.encode_l2)
            raw_p2 = arm.predict_l2
            p2_r = counter_r.wrap("predict_l2", lambda z, u, dt: raw_p2(z, lp.denormalize_macro(u), dt))
            macro_dts = np.full(cfg.macro_horizon, float(spec.PLAN_FUTURE_DT_L2), dtype=np.float64)
            macro_dts[0] = 1.0 + float(round((cfg.s2 - 1) * lp.expected_k()))
            raw_dts = np.full(cfg.s2, float(spec.PLAN_FUTURE_DT_L1), dtype=np.float64)
            raw_dts[0] = 1.0
            res_r = planner.hierarchical_cem_plan_reference(
                encode=enc_r,
                predict_l1=p1_r,
                predict_l2=p2_r,
                encode_l2=enc2_r,
                obs=x_obs,
                goal_obs=x_goal,
                config=cfg,
                rng=np.random.default_rng(100),
                counter=counter_r,
                macro_dts=macro_dts,
                raw_dts=raw_dts,
            )
        t_ref = time.perf_counter() - t0

        timing_records[arm_id] = {
            "wall_batched_sec": t_batched,
            "wall_ref_sec": t_ref,
            "speedup": t_ref / max(t_batched, 1e-9),
        }
        print(
            f"\n[NATIVE BENCHMARK] {arm_id}: batched={t_batched:.4f}s, "
            f"ref={t_ref:.4f}s, speedup={t_ref / max(t_batched, 1e-9):.2f}x"
        )

        np.testing.assert_array_equal(res_b.actions, res_r.actions)
        assert counter_b.total == counter_r.total
        assert counter_b.by_name == counter_r.by_name
