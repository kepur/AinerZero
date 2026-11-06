#!/usr/bin/env python3
"""Independent reconciliation probe for V9.P118 goal embedding cache semantics.

Runs 2 episodes, 3 decisions per episode, testing:
1. Flat CEM planner
2. Hierarchical CEM planner
Verifying:
- Goal embedding is computed and charged exactly 1 time per episode.
- Current observation encoding is charged 1 time per decision (3 times per episode).
- Total encode charges per episode = 1 (goal) + 3 (obs) = 4.
- In-episode goal change raises ValueError.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "src"))

import numpy as np

from ainerzero.v9.experiments.s2.fwd_counter import ForwardCounter
from ainerzero.v9.experiments.s2.planner import (
    FlatCEMConfig,
    HierCEMConfig,
    flat_cem_plan,
    hierarchical_cem_plan,
)


def identity_encode(obs):
    return np.asarray(obs, dtype=np.float64).flatten()


def predict_l1_dummy(z, a, dt=1.0):
    return z + a


def predict_l2_dummy(z2, macro_a, dt=1.0):
    return z2 + macro_a


def encode_l2_dummy(z1):
    return z1[:2] if len(z1) >= 2 else np.pad(z1, (0, 2 - len(z1)))


def run_probe():
    results = {
        "flat": [],
        "hierarchical": [],
        "goal_change_raises_flat": False,
        "goal_change_raises_hierarchical": False,
    }

    # 1. Flat CEM Probe
    flat_cfg = FlatCEMConfig(
        horizon=2,
        n_iters=1,
        pop_size=2,
        elite_frac=0.5,
        action_dim=1,
        n_exec=1,
        n_categories=4,
    )

    goal_obs_ep1 = np.array([10.0, 10.0])
    goal_obs_ep2 = np.array([20.0, 20.0])

    counter = ForwardCounter(budget=100_000)
    enc = counter.wrap("encode", identity_encode)
    p1 = counter.wrap("predict_l1", predict_l1_dummy)

    for ep, goal in enumerate([goal_obs_ep1, goal_obs_ep2], 1):
        counter.begin_episode()
        ep_record = {"episode": ep, "decisions": []}
        for dec in range(1, 4):
            counter.reset()
            obs = np.array([float(ep * 10 + dec), 1.0])
            res = flat_cem_plan(
                encode=enc,
                predict_l1=p1,
                obs=obs,
                goal_obs=goal,
                config=flat_cfg,
                rng=np.random.default_rng(ep * 100 + dec),
                counter=counter,
            )
            c = counter.by_name
            enc_count = c.get("encode", 0)
            p1_count = c.get("predict_l1", 0)
            expected_enc = 2 if dec == 1 else 1
            assert enc_count == expected_enc, f"Flat ep {ep} dec {dec}: expected enc={expected_enc}, got {enc_count}"
            ep_record["decisions"].append({
                "decision": dec,
                "encode": enc_count,
                "predict_l1": p1_count,
                "goal_cache_hit": (dec > 1),
            })
        results["flat"].append(ep_record)

    # Test goal change in same episode raises ValueError for Flat
    counter.begin_episode()
    counter.reset()
    flat_cem_plan(
        encode=enc,
        predict_l1=p1,
        obs=np.array([1.0, 1.0]),
        goal_obs=np.array([10.0, 10.0]),
        config=flat_cfg,
        rng=np.random.default_rng(1),
        counter=counter,
    )
    counter.reset()
    try:
        flat_cem_plan(
            encode=enc,
            predict_l1=p1,
            obs=np.array([1.0, 1.0]),
            goal_obs=np.array([99.0, 99.0]),
            config=flat_cfg,
            rng=np.random.default_rng(1),
            counter=counter,
        )
    except ValueError:
        results["goal_change_raises_flat"] = True

    # 2. Hierarchical CEM Probe
    hier_cfg = HierCEMConfig(
        macro_horizon=1,
        upper_iters=1,
        upper_pop=2,
        upper_elite_frac=0.5,
        macro_dim=1,
        s2=2,
        lower_iters=1,
        lower_pop=2,
        lower_elite_frac=0.5,
        action_dim=1,
        upper_budget=10_000,
        lower_budget=10_000,
        n_exec=1,
        n_categories=4,
        n_macro_categories=4,
    )

    counter_h = ForwardCounter(budget=100_000)
    enc_h = counter_h.wrap("encode", identity_encode)
    p1_h = counter_h.wrap("predict_l1", predict_l1_dummy)
    p2_h = counter_h.wrap("predict_l2", predict_l2_dummy)
    e2_h = counter_h.wrap("encode_l2", encode_l2_dummy)

    for ep, goal in enumerate([goal_obs_ep1, goal_obs_ep2], 1):
        counter_h.begin_episode()
        ep_record = {"episode": ep, "decisions": []}
        for dec in range(1, 4):
            counter_h.reset()
            obs = np.array([float(ep * 10 + dec), 1.0])
            res = hierarchical_cem_plan(
                encode=enc_h,
                predict_l1=p1_h,
                predict_l2=p2_h,
                encode_l2=e2_h,
                obs=obs,
                goal_obs=goal,
                config=hier_cfg,
                rng=np.random.default_rng(ep * 100 + dec),
                counter=counter_h,
            )
            c = counter_h.by_name
            enc_count = c.get("encode", 0)
            e2_count = c.get("encode_l2", 0)
            p1_count = c.get("predict_l1", 0)
            p2_count = c.get("predict_l2", 0)
            expected_enc = 2 if dec == 1 else 1
            assert enc_count == expected_enc, f"Hier ep {ep} dec {dec}: expected enc={expected_enc}, got {enc_count}"
            ep_record["decisions"].append({
                "decision": dec,
                "encode": enc_count,
                "encode_l2": e2_count,
                "predict_l1": p1_count,
                "predict_l2": p2_count,
                "goal_cache_hit": (dec > 1),
            })
        results["hierarchical"].append(ep_record)

    # Test goal change in same episode raises ValueError for Hierarchical
    counter_h.begin_episode()
    counter_h.reset()
    hierarchical_cem_plan(
        encode=enc_h,
        predict_l1=p1_h,
        predict_l2=p2_h,
        encode_l2=e2_h,
        obs=np.array([1.0, 1.0]),
        goal_obs=np.array([10.0, 10.0]),
        config=hier_cfg,
        rng=np.random.default_rng(1),
        counter=counter_h,
    )
    counter_h.reset()
    try:
        hierarchical_cem_plan(
            encode=enc_h,
            predict_l1=p1_h,
            predict_l2=p2_h,
            encode_l2=e2_h,
            obs=np.array([1.0, 1.0]),
            goal_obs=np.array([99.0, 99.0]),
            config=hier_cfg,
            rng=np.random.default_rng(1),
            counter=counter_h,
        )
    except ValueError:
        results["goal_change_raises_hierarchical"] = True

    print(json.dumps(results, indent=2))
    return results


if __name__ == "__main__":
    run_probe()
