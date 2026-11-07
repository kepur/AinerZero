"""Data generator and partition management for S2 GridLab multi-room experiments.

Pure CPU, NumPy / standard library only. Zero MLX imports.
Specifications per reports/V9-S2-DESIGN/DESIGN-r2.md §2.
"""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
import random
from typing import Any, Sequence

from .world import (
    SIZE,
    FREE,
    ACTION_WAIT,
    ACTIONS,
    PATH_ACTIONS,
    Layout,
    State,
    step,
    student_obs,
    truth,
    sample_goal,
    sample_start_goal_pair,
    compute_pose_bfs_distances,
    prepare_world_with_long_pairs,
    get_layout_view_counts,
    is_success,
    is_success_strict,
    LONG_PAIRS_PER_WORLD,
)

# Registered irregular-dt distribution and frozen χ² gate (df=2).
K_VALUES = (1, 2, 3)
K_WEIGHTS = (0.5, 0.3, 0.2)
# Frozen a priori threshold for multinomial goodness-of-fit (df=2, ~α≪0.001).
K_CHI2_THRESHOLD = 20.0
MIN_NON_BFS_RATIO = 0.5
SEGMENT_LEN_RANGE = (20, 60)
EPISODE_STEPS = 240
PERTURB_LONG_FRACTION = 1.0 / 3.0


def _get_derived_seed(namespace: str, *keys: Any) -> int:
    """Deterministic 64-bit integer seed derived from namespace and keys."""
    raw = f"{namespace}:" + ":".join(str(k) for k in keys)
    h = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    return int(h[:16], 16) & 0x7FFFFFFF


def sample_k(rng: random.Random, *, force_k1: bool = False, force_k: int | None = None) -> int:
    """Draw k from the registered distribution {1:0.5, 2:0.3, 3:0.2}.

    ``force_k`` is a mutation hook (P115-M7); production callers leave it None.
    """
    if force_k1:
        return 1
    if force_k is not None:
        return int(force_k)
    return rng.choices(list(K_VALUES), weights=list(K_WEIGHTS))[0]


def chi_square_k_distribution(counts: dict[int, int] | Sequence[int]) -> float:
    """Pearson χ² for empirical k counts vs registered weights."""
    if isinstance(counts, dict):
        obs = [int(counts.get(k, 0)) for k in K_VALUES]
    else:
        obs = [int(c) for c in counts]
    n = sum(obs)
    if n <= 0:
        raise ValueError("chi_square_k_distribution requires a positive sample size")
    expected = [n * w for w in K_WEIGHTS]
    return sum((o - e) ** 2 / e for o, e in zip(obs, expected))


def assert_k_distribution(
    counts: dict[int, int] | Sequence[int],
    *,
    threshold: float = K_CHI2_THRESHOLD,
    min_n: int = 5000,
) -> float:
    """Fail if sample size < min_n or χ² exceeds the frozen threshold."""
    if isinstance(counts, dict):
        n = sum(int(counts.get(k, 0)) for k in K_VALUES)
    else:
        n = sum(int(c) for c in counts)
    if n < min_n:
        raise AssertionError(f"k-distribution sample size {n} < required {min_n}")
    chi2 = chi_square_k_distribution(counts)
    if chi2 > threshold:
        raise AssertionError(
            f"k-distribution χ²={chi2:.4f} exceeds frozen threshold {threshold} "
            f"(expected weights {dict(zip(K_VALUES, K_WEIGHTS))}, counts={counts})"
        )
    return chi2


def _find_path_step(
    layout: Layout,
    state: State,
    target: State,
    *,
    dist_from_goal: dict[tuple[int, int, int], int] | None = None,
) -> int:
    """Greedy one-step action reducing pose-BFS distance to the target pose."""
    if _pose_reached_cell(state, target) and state.heading == target.heading:
        return ACTION_WAIT
    from_goal = dist_from_goal if dist_from_goal is not None else compute_pose_bfs_distances(
        layout, target
    )
    cur_d = from_goal.get((state.x, state.y, state.heading), 10**9)

    best_action = ACTION_WAIT
    best_d = cur_d
    for action in PATH_ACTIONS:
        nxt = step(layout, state, action, k=1)
        d = from_goal.get((nxt.x, nxt.y, nxt.heading), 10**9)
        if d < best_d:
            best_d = d
            best_action = action
    return best_action


def _pose_reached_cell(state: State, target: State) -> bool:
    return state.x == target.x and state.y == target.y


def _sample_exploration_target(
    layout: Layout,
    state: State,
    rng: random.Random,
) -> State:
    """Pick a far navigation target for exploration.

    Prefers an unambiguous long (pose-BFS ≥ 40) goal. If the current pose cannot
    reach any long goal, fall back to the furthest unambiguous pose — this path
    is only for trajectory generation, never for eval long-goal contracts.
    """
    try:
        goal, _, _ = sample_goal(layout, state, rng, kind="long", max_attempts=120)
        return goal
    except RuntimeError:
        pass

    distances = compute_pose_bfs_distances(layout, state)
    views, counts = get_layout_view_counts(layout)
    ranked = sorted(distances.items(), key=lambda kv: kv[1], reverse=True)
    unambiguous = [
        pose for pose, _d in ranked if counts[views[pose]] == 1 and pose != (state.x, state.y, state.heading)
    ]
    if unambiguous:
        gx, gy, gh = unambiguous[0]
        return State(x=gx, y=gy, heading=gh)
    if ranked:
        gx, gy, gh = ranked[0][0]
        return State(x=gx, y=gy, heading=gh)
    return state


def _choose_segment_kind(
    rng: random.Random,
    non_bfs_steps: int,
    bfs_steps: int,
    remaining: int,
    *,
    force_bfs_only: bool = False,
) -> str:
    """Assign next segment kind so non-BFS env-step share stays ≥ MIN_NON_BFS_RATIO."""
    if force_bfs_only:
        return "bfs"
    total = non_bfs_steps + bfs_steps
    if total == 0:
        return "non_bfs"
    # If taking an all-BFS remainder would drop below the floor, force non_bfs.
    if (non_bfs_steps / (total + remaining)) < MIN_NON_BFS_RATIO:
        return "non_bfs"
    non_bfs_frac = non_bfs_steps / total
    bfs_frac = bfs_steps / total
    if non_bfs_frac < MIN_NON_BFS_RATIO:
        return "non_bfs"
    if bfs_frac < MIN_NON_BFS_RATIO:
        return "bfs"
    return "non_bfs" if rng.random() < 0.5 else "bfs"


def run_episode(
    layout: Layout,
    rng: random.Random,
    *,
    max_steps: int = EPISODE_STEPS,
    force_k1: bool = False,
    force_k: int | None = None,
    exploration_noise: float = 0.2,
    force_bfs_only: bool = False,
) -> dict[str, Any]:
    """Run a mixed-segment exploration episode (r2).

    Segments alternate between noisy BFS and inertial random walk. Segment
    lengths are drawn uniformly from [20, 60] (clipped by remaining steps).
    Non-BFS env-step share is kept ≥ 0.5 unless ``force_bfs_only`` (mutation).
    """
    # Joint-draw an initial (start, long goal) when possible so exploration begins
    # from a pose that admits ≥40; fall back to a random FREE pose otherwise.
    try:
        state, current_goal, _, _ = sample_start_goal_pair(layout, rng, kind="long")
    except RuntimeError:
        free_cells = [
            (x, y)
            for y in range(SIZE)
            for x in range(SIZE)
            if layout.terrain[y][x] == FREE
        ]
        start_pos = rng.choice(free_cells)
        state = State(x=start_pos[0], y=start_pos[1], heading=rng.choice([0, 1, 2, 3]))
        current_goal = _sample_exploration_target(layout, state, rng)

    steps_data: list[dict[str, Any]] = []
    segments_meta: list[dict[str, Any]] = []
    total_env_steps = 0
    last_action = ACTION_WAIT
    non_bfs_steps = 0
    bfs_steps = 0
    k_hist = {1: 0, 2: 0, 3: 0}
    dist_from_goal = compute_pose_bfs_distances(layout, current_goal)

    while total_env_steps < max_steps:
        remaining = max_steps - total_env_steps
        seg_lo, seg_hi = SEGMENT_LEN_RANGE
        if remaining < seg_lo:
            seg_len = remaining
        else:
            seg_len = rng.randint(seg_lo, min(seg_hi, remaining))

        kind = _choose_segment_kind(
            rng,
            non_bfs_steps,
            bfs_steps,
            remaining,
            force_bfs_only=force_bfs_only,
        )
        seg_env = 0
        seg_start_index = len(steps_data)

        while seg_env < seg_len and total_env_steps < max_steps:
            if _pose_reached_cell(state, current_goal):
                current_goal = _sample_exploration_target(layout, state, rng)
                dist_from_goal = compute_pose_bfs_distances(layout, current_goal)

            if kind == "bfs":
                if rng.random() < exploration_noise:
                    action = rng.choice(ACTIONS)
                else:
                    action = _find_path_step(
                        layout, state, current_goal, dist_from_goal=dist_from_goal
                    )
            else:
                # Inertial random walk: 0.7 repeat last action, else uniform.
                if rng.random() < 0.7:
                    action = last_action
                else:
                    action = rng.choice(ACTIONS)

            k = sample_k(rng, force_k1=force_k1, force_k=force_k)
            if total_env_steps + k > max_steps:
                k = max_steps - total_env_steps
            if k <= 0:
                break

            obs = student_obs(layout, state, last_action=last_action, dt=k)
            state_truth_before = truth(state)
            next_state = step(layout, state, action, k=k)
            state_truth_after = truth(next_state)

            steps_data.append(
                {
                    "step_index": len(steps_data),
                    "action": action,
                    "dt": k,
                    "segment_kind": kind,
                    "student_obs": obs,
                    "truth_before": state_truth_before,
                    "truth_after": state_truth_after,
                }
            )

            if k in k_hist:
                k_hist[k] += 1
            total_env_steps += k
            seg_env += k
            if kind == "bfs":
                bfs_steps += k
            else:
                non_bfs_steps += k
            state = next_state
            last_action = action

        segments_meta.append(
            {
                "kind": kind,
                "env_steps": seg_env,
                "step_index_start": seg_start_index,
                "step_index_end": len(steps_data),
            }
        )

    total = non_bfs_steps + bfs_steps
    non_bfs_ratio = (non_bfs_steps / total) if total else 0.0
    bfs_ratio = (bfs_steps / total) if total else 0.0

    return {
        "max_steps": max_steps,
        "total_env_steps": total_env_steps,
        "steps_count": len(steps_data),
        "steps": steps_data,
        "segments": segments_meta,
        "segment_stats": {
            "non_bfs_steps": non_bfs_steps,
            "bfs_steps": bfs_steps,
            "non_bfs_ratio": non_bfs_ratio,
            "bfs_ratio": bfs_ratio,
        },
        "k_histogram": k_hist,
        "layout_sha256": layout.layout_sha256,
    }


def make_goal_episode_specs(
    layout: Layout,
    pairs: Sequence[dict[str, Any]],
    rng: random.Random,
    *,
    partition: str,
) -> list[dict[str, Any]]:
    """Build eval episode specs; long goals get perturb=True on 1/3 of them (dev/final)."""
    specs: list[dict[str, Any]] = []
    long_indices = list(range(len(pairs)))
    n_perturb = int(math.floor(len(long_indices) * PERTURB_LONG_FRACTION))
    if partition in ("dev", "final") and long_indices:
        # At least one perturb when there are ≥3 long pairs (6 → 2).
        n_perturb = max(n_perturb, 1) if len(long_indices) >= 3 else n_perturb
        perturb_set = set(rng.sample(long_indices, min(n_perturb, len(long_indices))))
    else:
        perturb_set = set()

    for idx, pair in enumerate(pairs):
        perturb = idx in perturb_set
        specs.append(
            {
                "episode_index": idx,
                "kind": "long",
                "start": pair["start"],
                "goal": pair["goal"],
                "bfs_distance": pair["bfs_distance"],
                "perturb": perturb,
                "perturb_spec": (
                    {"at_step": 20, "n_random_actions": 5} if perturb else None
                ),
            }
        )
    return specs


def generate_partition(
    partition: str,
    n_worlds: int,
    episodes_per_world: int,
    output_root: str | Path,
    seed_namespace: str,
    *,
    allowed_root: str | Path | None = None,
    max_steps_per_episode: int = EPISODE_STEPS,
    enforce_rejection_redraw: bool = True,
    force_bfs_only: bool = False,
) -> dict[str, Any]:
    """Generate a single dataset partition. Caller-provided output_root asserted."""
    out_path = Path(output_root).resolve()
    if allowed_root is not None:
        all_path = Path(allowed_root).resolve()
        assert out_path == all_path or all_path in out_path.parents, (
            f"output_root {out_path} is not under allowed_root {all_path}"
        )

    part_dir = out_path / partition
    part_dir.mkdir(parents=True, exist_ok=True)

    layouts: list[Layout] = []
    generated_files: list[Path] = []
    world_summaries: list[dict[str, Any]] = []
    aggregate_non_bfs = 0
    aggregate_bfs = 0
    goal_specs_all: list[dict[str, Any]] = []

    for w_idx in range(n_worlds):
        w_seed = _get_derived_seed(seed_namespace, partition, "world", w_idx)
        prep_rng = random.Random(_get_derived_seed(seed_namespace, partition, "prep", w_idx))
        n_pairs = LONG_PAIRS_PER_WORLD if partition in ("dev", "final") else max(
            1, min(episodes_per_world, LONG_PAIRS_PER_WORLD)
        )
        layout, pairs, prep_summary = prepare_world_with_long_pairs(
            w_seed,
            prep_rng,
            n_long_pairs=n_pairs,
            enforce_rejection_redraw=enforce_rejection_redraw,
        )
        layouts.append(layout)
        world_summaries.append({"world_index": w_idx, **prep_summary})

        world_dir = part_dir / f"world_{w_idx:04d}"
        world_dir.mkdir(parents=True, exist_ok=True)

        layout_file = world_dir / "layout.json"
        layout_file.write_text(json.dumps(layout.to_dict(), indent=2, sort_keys=True) + "\n")
        generated_files.append(layout_file)

        for ep_idx in range(episodes_per_world):
            ep_seed = _get_derived_seed(seed_namespace, partition, "ep", w_idx, ep_idx)
            ep_rng = random.Random(ep_seed)
            ep_data = run_episode(
                layout,
                ep_rng,
                max_steps=max_steps_per_episode,
                force_k1=False,
                force_bfs_only=force_bfs_only,
            )
            aggregate_non_bfs += int(ep_data["segment_stats"]["non_bfs_steps"])
            aggregate_bfs += int(ep_data["segment_stats"]["bfs_steps"])
            ep_file = world_dir / f"episode_{ep_idx:04d}.json"
            ep_file.write_text(json.dumps(ep_data, indent=2, sort_keys=True) + "\n")
            generated_files.append(ep_file)

        if partition in ("dev", "final"):
            spec_rng = random.Random(
                _get_derived_seed(seed_namespace, partition, "specs", w_idx)
            )
            specs = make_goal_episode_specs(layout, pairs, spec_rng, partition=partition)
            for spec in specs:
                spec["world_index"] = w_idx
            goal_specs_all.extend(specs)
            specs_file = world_dir / "goal_episode_specs.json"
            specs_file.write_text(json.dumps(specs, indent=2, sort_keys=True) + "\n")
            generated_files.append(specs_file)

    # For dev and final partitions, also save regular dt (k=1) test set
    if partition in ("dev", "final"):
        reg_dir = part_dir / "regular_dt_k1"
        reg_dir.mkdir(parents=True, exist_ok=True)
        for w_idx, layout in enumerate(layouts):
            reg_world_dir = reg_dir / f"world_{w_idx:04d}"
            reg_world_dir.mkdir(parents=True, exist_ok=True)
            for ep_idx in range(episodes_per_world):
                ep_seed = _get_derived_seed(seed_namespace, partition, "reg_k1", w_idx, ep_idx)
                ep_rng = random.Random(ep_seed)
                ep_data = run_episode(
                    layout,
                    ep_rng,
                    max_steps=max_steps_per_episode,
                    force_k1=True,
                    force_bfs_only=force_bfs_only,
                )
                ep_file = reg_world_dir / f"episode_{ep_idx:04d}.json"
                ep_file.write_text(json.dumps(ep_data, indent=2, sort_keys=True) + "\n")
                generated_files.append(ep_file)

    sums_lines = []
    for f in sorted(generated_files):
        rel = f.relative_to(part_dir)
        h = hashlib.sha256(f.read_bytes()).hexdigest()
        sums_lines.append(f"{h}  {rel}")

    sums_file = part_dir / "SHA256SUMS.txt"
    sums_file.write_text("\n".join(sums_lines) + "\n")
    generated_files.append(sums_file)

    total_seg = aggregate_non_bfs + aggregate_bfs
    manifest_data = {
        "partition": partition,
        "seed_namespace": seed_namespace,
        "n_worlds": n_worlds,
        "episodes_per_world": episodes_per_world,
        "layout_digests": [ly.layout_sha256 for ly in layouts],
        "total_files": len(generated_files),
        "segment_stats": {
            "non_bfs_steps": aggregate_non_bfs,
            "bfs_steps": aggregate_bfs,
            "non_bfs_ratio": (aggregate_non_bfs / total_seg) if total_seg else 0.0,
            "bfs_ratio": (aggregate_bfs / total_seg) if total_seg else 0.0,
        },
        "world_summaries": world_summaries,
        "goal_episode_specs": goal_specs_all,
    }
    manifest_file = part_dir / "manifest.json"
    manifest_file.write_text(json.dumps(manifest_data, indent=2, sort_keys=True) + "\n")

    return manifest_data


def assert_partitions_disjoint(manifests: Sequence[dict[str, Any] | str | Path]) -> None:
    """Assert that a collection of partition manifests have zero overlapping layout digests."""
    loaded: list[dict[str, Any]] = []
    for m in manifests:
        if isinstance(m, (str, Path)):
            loaded.append(json.loads(Path(m).read_text()))
        else:
            loaded.append(m)

    seen_digests: dict[str, str] = {}
    seen_namespaces: dict[str, str] = {}

    for manifest in loaded:
        part = manifest["partition"]
        ns = manifest["seed_namespace"]
        if ns in seen_namespaces:
            raise ValueError(
                f"Shared seed namespace detected: namespace '{ns}' used by both "
                f"'{seen_namespaces[ns]}' and '{part}'"
            )
        seen_namespaces[ns] = part

        for digest in manifest["layout_digests"]:
            if digest in seen_digests:
                prior = seen_digests[digest]
                raise ValueError(
                    f"Partitions overlap: layout digest {digest} appears in both '{prior}' and '{part}'"
                )
            seen_digests[digest] = part


# Re-export success helpers for callers / tests
__all__ = [
    "generate_partition",
    "assert_partitions_disjoint",
    "run_episode",
    "sample_k",
    "chi_square_k_distribution",
    "assert_k_distribution",
    "make_goal_episode_specs",
    "is_success",
    "is_success_strict",
    "K_CHI2_THRESHOLD",
    "K_WEIGHTS",
    "MIN_NON_BFS_RATIO",
]
