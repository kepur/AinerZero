#!/usr/bin/env python3
"""Independent verification script for S2 data generator path-finding defect (ainerzero.V9.P200).

Strict isolation requirements:
- Zero MLX / zero GPU;
- Read-only on artifacts/v9/s2/phase1/datasets/train;
- Never open or query sqlite ledgers;
- Pure CPU NumPy / standard library.
"""
from __future__ import annotations

import collections
import glob
import json
import random
import time
from pathlib import Path

from ainerzero.v9.experiments.s2 import world, data

REVIEW_DIR = Path("reports/V9-S2-CLOSE/addendum-data-defect/review")
REVIEW_DIR.mkdir(parents=True, exist_ok=True)


# --- 1. Independent Backward Multi-Source BFS Implementation ---
def compute_backward_bfs(layout: world.Layout, goal_x: int, goal_y: int, goal_h: int | None = None) -> dict[tuple[int, int, int], int]:
    """Compute exact shortest distance from all reachable poses (x, y, h) TO the goal.

    Traverses the reversed pose graph:
    For an edge u -> v:
      - TURN_LEFT: u=(x, y, (h+1)%4) -> v=(x, y, h)
      - TURN_RIGHT: u=(x, y, (h-1)%4) -> v=(x, y, h)
      - FORWARD: u=(x-dx, y-dy, h) -> v=(x, y, h) (if u is FREE in layout)
    """
    if goal_h is not None:
        init_nodes = [(goal_x, goal_y, goal_h)]
    else:
        init_nodes = [(goal_x, goal_y, h) for h in range(4)]

    distances = {node: 0 for node in init_nodes}
    queue = collections.deque(init_nodes)

    while queue:
        x, y, h = queue.popleft()
        d = distances[(x, y, h)]

        # Predecessor 1: TURN_LEFT (turning left leads to (x, y, h), so pred was at h+1)
        p_left = (x, y, (h + 1) % 4)
        if p_left not in distances:
            distances[p_left] = d + 1
            queue.append(p_left)

        # Predecessor 2: TURN_RIGHT (turning right leads to (x, y, h), so pred was at h-1)
        p_right = (x, y, (h - 1) % 4)
        if p_right not in distances:
            distances[p_right] = d + 1
            queue.append(p_right)

        # Predecessor 3: FORWARD (moving forward with heading h leads to (x, y, h))
        dx, dy = world.DELTA[h]
        px, py = x - dx, y - dy
        if 0 <= px < world.SIZE and 0 <= py < world.SIZE and layout.terrain[py][px] == world.FREE:
            p_fwd = (px, py, h)
            if p_fwd not in distances:
                distances[p_fwd] = d + 1
                queue.append(p_fwd)

    return distances


def find_step_backward_bfs(
    layout: world.Layout,
    state: world.State,
    target: world.State,
    dist_to_goal: dict[tuple[int, int, int], int],
) -> int:
    """Greedy one-step action minimizing true distance to goal."""
    if state.x == target.x and state.y == target.y:
        return world.ACTION_WAIT

    cur_d = dist_to_goal.get((state.x, state.y, state.heading), 10**9)
    best_action = world.ACTION_WAIT
    best_d = cur_d

    for action in world.PATH_ACTIONS:
        nxt = world.step(layout, state, action, k=1)
        d = dist_to_goal.get((nxt.x, nxt.y, nxt.heading), 10**9)
        if d < best_d:
            best_d = d
            best_action = action

    return best_action


# --- 2. Comparative Benchmark on 40 Worlds x 5 Long Pairs = 200 Pairs ---
def run_bfs_comparison(n_worlds: int = 40, pairs_per_world: int = 5, max_steps: int = 200) -> dict:
    print(f"\n[Part 2] Running comparative benchmark: {n_worlds} worlds x {pairs_per_world} pairs ({n_worlds * pairs_per_world} pairs)...")
    
    results = {
        "existing_forward_bfs": {
            "total_pairs": 0,
            "reached_goal": 0,
            "stuck_on_wait": 0,
            "timeout": 0,
            "action_counts": collections.Counter(),
            "avg_steps": 0.0,
        },
        "corrected_backward_bfs": {
            "total_pairs": 0,
            "reached_goal": 0,
            "stuck_on_wait": 0,
            "timeout": 0,
            "action_counts": collections.Counter(),
            "avg_steps": 0.0,
        }
    }

    total_steps_existing = 0
    total_steps_corrected = 0

    for w_idx in range(n_worlds):
        rng = random.Random(20261109 + w_idx)
        layout, pairs, _ = world.prepare_world_with_long_pairs(w_idx, rng)
        sampled_pairs = pairs[:pairs_per_world]

        for p in sampled_pairs:
            start = world.State(x=p["start"]["x"], y=p["start"]["y"], heading=p["start"]["heading"])
            goal = world.State(x=p["goal"]["x"], y=p["goal"]["y"], heading=p["goal"]["heading"])

            # --- Existing Forward BFS Method ---
            dist_from_goal = world.compute_pose_bfs_distances(layout, goal)
            state = start
            reached = False
            stuck_wait = False

            for step_idx in range(max_steps):
                if state.x == goal.x and state.y == goal.y:
                    reached = True
                    break
                act = data._find_path_step(layout, state, goal, dist_from_goal=dist_from_goal)
                results["existing_forward_bfs"]["action_counts"][act] += 1
                total_steps_existing += 1
                if act == world.ACTION_WAIT:
                    stuck_wait = True
                    break
                state = world.step(layout, state, act, k=1)

            results["existing_forward_bfs"]["total_pairs"] += 1
            if reached:
                results["existing_forward_bfs"]["reached_goal"] += 1
            elif stuck_wait:
                results["existing_forward_bfs"]["stuck_on_wait"] += 1
            else:
                results["existing_forward_bfs"]["timeout"] += 1

            # --- Corrected Backward BFS Method ---
            dist_to_goal = compute_backward_bfs(layout, goal.x, goal.y, goal_h=None)
            state = start
            reached_corr = False
            stuck_wait_corr = False

            for step_idx in range(max_steps):
                if state.x == goal.x and state.y == goal.y:
                    reached_corr = True
                    break
                act = find_step_backward_bfs(layout, state, goal, dist_to_goal)
                results["corrected_backward_bfs"]["action_counts"][act] += 1
                total_steps_corrected += 1
                if act == world.ACTION_WAIT:
                    stuck_wait_corr = True
                    break
                state = world.step(layout, state, act, k=1)

            results["corrected_backward_bfs"]["total_pairs"] += 1
            if reached_corr:
                results["corrected_backward_bfs"]["reached_goal"] += 1
            elif stuck_wait_corr:
                results["corrected_backward_bfs"]["stuck_on_wait"] += 1
            else:
                results["corrected_backward_bfs"]["timeout"] += 1

    results["existing_forward_bfs"]["avg_steps"] = total_steps_existing / (n_worlds * pairs_per_world)
    results["corrected_backward_bfs"]["avg_steps"] = total_steps_corrected / (n_worlds * pairs_per_world)

    print("Existing Forward BFS:", {
        "reached": results["existing_forward_bfs"]["reached_goal"],
        "stuck_wait": results["existing_forward_bfs"]["stuck_on_wait"],
        "timeout": results["existing_forward_bfs"]["timeout"],
        "avg_steps": results["existing_forward_bfs"]["avg_steps"],
    })
    print("Corrected Backward BFS:", {
        "reached": results["corrected_backward_bfs"]["reached_goal"],
        "stuck_wait": results["corrected_backward_bfs"]["stuck_on_wait"],
        "timeout": results["corrected_backward_bfs"]["timeout"],
        "avg_steps": results["corrected_backward_bfs"]["avg_steps"],
    })

    return results


# --- 3. Independent Audit of Real Training Dataset ---
def audit_training_dataset(max_episodes: int = 1000) -> dict:
    print(f"\n[Part 3] Auditing real training dataset (sampling {max_episodes} episodes)...")
    train_dir = Path("artifacts/v9/s2/phase1/datasets/train")
    world_dirs = sorted([d for d in train_dir.glob("world_*") if d.is_dir()])
    assert len(world_dirs) > 0, f"No world directories found in {train_dir}"

    print(f"Total worlds in train partition: {len(world_dirs)}")

    # Stratified sampling: 1 episode per world across min(len(world_dirs), max_episodes) worlds
    sampled_files = []
    for d in world_dirs[:max_episodes]:
        ep_files = sorted(d.glob("episode_*.json"))
        if ep_files:
            sampled_files.append(ep_files[0])

    print(f"Sampled episodes to inspect: {len(sampled_files)} (stratified: 1 episode per world)")

    action_counts_env_steps = collections.Counter()
    bfs_action_counts = collections.Counter()
    non_bfs_action_counts = collections.Counter()

    unique_cells_per_episode = []
    max_cell_visit_fractions = []
    revisits_after_60_steps = []

    total_episodes_audited = 0

    for ep_path in sampled_files:
        with open(ep_path, "r", encoding="utf-8") as f:
            ep = json.load(f)

        total_episodes_audited += 1
        steps = ep.get("steps", [])

        # Track trajectory of cells
        cells_visited = []
        episode_env_step = 0

        # For revisit tracking after >= 60 steps
        cell_last_seen = {}
        cell_revisit_count_after_60 = 0

        for s in steps:
            act = s["action"]
            dt = s.get("dt", 1)
            kind = s.get("segment_kind", "unknown")

            action_counts_env_steps[act] += dt
            if kind == "bfs":
                bfs_action_counts[act] += dt
            else:
                non_bfs_action_counts[act] += dt

            # Position after step
            pos = (s["truth_after"]["x"], s["truth_after"]["y"])
            cells_visited.append(pos)

            if pos in cell_last_seen:
                if episode_env_step - cell_last_seen[pos] >= 60:
                    cell_revisit_count_after_60 += 1
            cell_last_seen[pos] = episode_env_step
            episode_env_step += dt

        unique_cells = len(set(cells_visited))
        unique_cells_per_episode.append(unique_cells)

        counts = collections.Counter(cells_visited)
        if counts:
            most_common_count = counts.most_common(1)[0][1]
            frac = most_common_count / len(cells_visited)
            max_cell_visit_fractions.append(frac)
        else:
            max_cell_visit_fractions.append(0.0)

        revisits_after_60_steps.append(cell_revisit_count_after_60)

    import statistics

    total_env_steps = sum(action_counts_env_steps.values())
    total_bfs_steps = sum(bfs_action_counts.values())
    total_non_bfs_steps = sum(non_bfs_action_counts.values())

    stats = {
        "audited_episodes_count": total_episodes_audited,
        "sampling_method": "Stratified sampling across worlds: exactly episode_0000.json from 1000 distinct training worlds",
        "action_distribution_env_steps": {
            "ACTION_FORWARD": action_counts_env_steps[world.ACTION_FORWARD] / total_env_steps,
            "ACTION_TURN_LEFT": action_counts_env_steps[world.ACTION_TURN_LEFT] / total_env_steps,
            "ACTION_TURN_RIGHT": action_counts_env_steps[world.ACTION_TURN_RIGHT] / total_env_steps,
            "ACTION_WAIT": action_counts_env_steps[world.ACTION_WAIT] / total_env_steps,
        },
        "bfs_wait_ratio": bfs_action_counts[world.ACTION_WAIT] / total_bfs_steps if total_bfs_steps else 0,
        "non_bfs_wait_ratio": non_bfs_action_counts[world.ACTION_WAIT] / total_non_bfs_steps if total_non_bfs_steps else 0,
        "unique_cells_per_episode": {
            "median": statistics.median(unique_cells_per_episode),
            "mean": statistics.mean(unique_cells_per_episode),
            "min": min(unique_cells_per_episode),
            "max": max(unique_cells_per_episode),
        },
        "max_cell_visit_fraction": {
            "median": statistics.median(max_cell_visit_fractions),
            "mean": statistics.mean(max_cell_visit_fractions),
            "min": min(max_cell_visit_fractions),
            "max": max(max_cell_visit_fractions),
        },
        "revisit_after_60_steps_count": {
            "median": statistics.median(revisits_after_60_steps),
            "mean": statistics.mean(revisits_after_60_steps),
            "min": min(revisits_after_60_steps),
            "max": max(revisits_after_60_steps),
        }
    }

    print("Audited Action Distribution:")
    for a, frac in stats["action_distribution_env_steps"].items():
        print(f"  {a}: {frac*100:.1f}%")
    print(f"BFS WAIT Ratio: {stats['bfs_wait_ratio']*100:.1f}%")
    print(f"Non-BFS WAIT Ratio: {stats['non_bfs_wait_ratio']*100:.1f}%")
    print(f"Unique cells median: {stats['unique_cells_per_episode']['median']} (min={stats['unique_cells_per_episode']['min']}, max={stats['unique_cells_per_episode']['max']})")
    print(f"Max cell visit fraction median: {stats['max_cell_visit_fraction']['median']*100:.1f}% (max={stats['max_cell_visit_fraction']['max']*100:.1f}%)")

    return stats


def main():
    t0 = time.time()
    bfs_results = run_bfs_comparison(n_worlds=40, pairs_per_world=5, max_steps=200)
    dataset_stats = audit_training_dataset(max_episodes=1000)

    # Convert Counter to dict for json
    for k in ("existing_forward_bfs", "corrected_backward_bfs"):
        bfs_results[k]["action_counts"] = dict(bfs_results[k]["action_counts"])

    full_report = {
        "benchmark_comparison": bfs_results,
        "dataset_audit": dataset_stats,
        "elapsed_seconds": time.time() - t0,
    }

    out_file = REVIEW_DIR / "defect_reproduction.json"
    out_file.write_text(json.dumps(full_report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nAll verification completed in {time.time() - t0:.2f}s. Saved to {out_file}")


if __name__ == "__main__":
    main()
