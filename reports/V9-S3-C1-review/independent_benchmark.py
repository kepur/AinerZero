#!/usr/bin/env python3
"""Independent benchmark script for S3-C1 (P204 Review).

Runs 100-world independent tests of:
1. Reverse BFS pathfinding reachability (100 worlds x 5 goals = 500 goals, noise=0.0).
2. P-a coverage and swap ratio across 100 worlds (T=360, p_slip=0.05, noise=0.10).
3. Compares results with author P203 claims.
"""

import collections
import json
from pathlib import Path
import random
import time

import numpy as np

from ainerzero.v9.experiments.s2.world import (
    ACTION_WAIT,
    FREE,
    SIZE,
    State,
    make_layout,
    step,
)
from ainerzero.v9.experiments.s3.content import generate_content_state
from ainerzero.v9.experiments.s3.data import derive_seed, generate_episode
from ainerzero.v9.experiments.s3.spec import BUCKET_LONG, M, NOISE, P_SLIP, T
from ainerzero.v9.experiments.s3.world import (
    compute_reverse_bfs_distances,
    get_connected_free_cells,
    step_to_goal,
)


def run_pathfinding_benchmark(n_worlds: int = 100, goals_per_world: int = 5) -> dict:
    """Evaluate pure reverse-BFS pathfinding without exploration noise."""
    total_goals = 0
    reached_goals = 0
    steps_taken_list = []

    for w_idx in range(n_worlds):
        w_seed = derive_seed("independent-review", "pathfinding", w_idx)
        layout = make_layout(w_seed)
        connected = get_connected_free_cells(layout)
        rng = random.Random(w_seed + 10007)

        for g_idx in range(goals_per_world):
            start_cell = rng.choice(connected)
            goal_cell = rng.choice(connected)
            while goal_cell == start_cell and len(connected) > 1:
                goal_cell = rng.choice(connected)

            start_h = rng.choice([0, 1, 2, 3])
            s = State(x=start_cell[0], y=start_cell[1], heading=start_h, wall_bumps=0)

            dist_field = compute_reverse_bfs_distances(layout, goal_cell)
            guard = 0
            reached = False

            while guard < 250:
                if (s.x, s.y) == goal_cell:
                    reached = True
                    break
                act = step_to_goal(layout, s, dist_field)
                if act == ACTION_WAIT:
                    break
                s = step(layout, s, act, k=1)
                guard += 1

            total_goals += 1
            if reached:
                reached_goals += 1
                steps_taken_list.append(guard)

    reachability = reached_goals / total_goals if total_goals else 0.0
    return {
        "n_worlds": n_worlds,
        "goals_per_world": goals_per_world,
        "total_goals": total_goals,
        "reached_goals": reached_goals,
        "reachability": reachability,
        "avg_steps": float(np.mean(steps_taken_list)) if steps_taken_list else 0.0,
        "max_steps": int(np.max(steps_taken_list)) if steps_taken_list else 0,
    }


def run_pa_benchmark(n_worlds: int = 100) -> dict:
    """Evaluate Probe P-a criteria across 100 independent worlds."""
    unique_cells_list = []
    top_cell_fractions = []
    episodes_with_long_swapped = 0
    total_returns = 0
    total_swapped = 0
    long_returns = 0
    long_swapped = 0

    for w_idx in range(n_worlds):
        w_seed = derive_seed("independent-review", "pa-eval", w_idx)
        ep_seed = derive_seed("independent-review", "pa-ep", w_idx)

        ep = generate_episode(w_seed, ep_seed, family="F1", t_max=T, p_slip=P_SLIP, noise=NOISE)
        summary = ep["summary"]

        unique_cells_list.append(summary["unique_cells_visited"])
        top_cell_fractions.append(summary["most_frequent_cell_ratio"])

        events = ep["events"]
        has_long_swapped = any(e["bucket"] == BUCKET_LONG and e["swapped"] for e in events)
        if has_long_swapped:
            episodes_with_long_swapped += 1

        for e in events:
            total_returns += 1
            if e["swapped"]:
                total_swapped += 1
            if e["bucket"] == BUCKET_LONG:
                long_returns += 1
                if e["swapped"]:
                    long_swapped += 1

    return {
        "n_worlds": n_worlds,
        "unique_cells_median": float(np.median(unique_cells_list)),
        "unique_cells_min": int(np.min(unique_cells_list)),
        "unique_cells_max": int(np.max(unique_cells_list)),
        "top_cell_fraction_median": float(np.median(top_cell_fractions)),
        "top_cell_fraction_max": float(np.max(top_cell_fractions)),
        "episodes_with_long_swapped_pct": float(episodes_with_long_swapped / n_worlds * 100.0),
        "total_returns": total_returns,
        "avg_returns_per_ep": float(total_returns / n_worlds),
        "total_swapped": total_swapped,
        "swapped_ratio": float(total_swapped / total_returns) if total_returns else 0.0,
        "long_returns": long_returns,
        "long_swapped": long_swapped,
    }


def main():
    print("Running independent pathfinding benchmark (100 worlds x 5 goals = 500 goals)...")
    t0 = time.time()
    path_res = run_pathfinding_benchmark(100, 5)
    t1 = time.time()
    print(f"Pathfinding complete in {t1 - t0:.2f}s: {path_res['reached_goals']}/{path_res['total_goals']} reached ({path_res['reachability']*100:.1f}%)")

    print("\nRunning independent Probe P-a benchmark (100 worlds, T=360)...")
    t2 = time.time()
    pa_res = run_pa_benchmark(100)
    t3 = time.time()
    print(f"P-a benchmark complete in {t3 - t2:.2f}s:")
    print(f"  Distinct cells median: {pa_res['unique_cells_median']} (min={pa_res['unique_cells_min']}, max={pa_res['unique_cells_max']})")
    print(f"  Top cell fraction max: {pa_res['top_cell_fraction_max']*100:.2f}% (median={pa_res['top_cell_fraction_median']*100:.2f}%)")
    print(f"  Episodes with long swapped: {pa_res['episodes_with_long_swapped_pct']:.1f}%")
    print(f"  Swapped ratio: {pa_res['swapped_ratio']*100:.2f}% ({pa_res['total_swapped']}/{pa_res['total_returns']})")

    out_file = Path("reports/V9-S3-C1-review/benchmark_results.json")
    out_file.parent.mkdir(parents=True, exist_ok=True)
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump({"pathfinding": path_res, "probe_pa": pa_res}, f, indent=2)
    print(f"\nSaved results to {out_file}")


if __name__ == "__main__":
    main()
