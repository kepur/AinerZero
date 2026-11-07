"""S2 linear probe evaluation & prediction non-inferiority gate.

Pure CPU, NumPy / standard library only. Strictly ZERO MLX imports.
Authority:
- reports/V9-S2-DESIGN/DESIGN-r2.md §5, Appendix D5.1, Appendix E
- Ridge regression: ainerzero.v9.experiments.s2.probe.fit_ridge / eval_error
- Bootstrap: ainerzero.v9.experiments.s2.stats.cluster_paired_bootstrap
- Observation featurization: ainerzero.v9.experiments.s2.learned_planning.featurize_obs
- Spec constants: ainerzero.v9.experiments.s2.spec
"""

from __future__ import annotations

import collections
import hashlib
import json
from pathlib import Path
import random
from typing import Any, Mapping, Sequence

import numpy as np

from ainerzero.v9.experiments.s2 import learned_planning, probe, spec, stats

__all__ = [
    "derive_probe_seed",
    "fit_probe",
    "probe_errors",
    "prediction_noninferiority",
]


def derive_probe_seed(namespace: str, *keys: Any) -> int:
    """Deterministic 31-bit integer seed derived from namespace and keys."""
    raw = ":".join([namespace, *(str(k) for k in keys)]) if keys else namespace
    h = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    return int(h[:16], 16) & 0x7FFFFFFF


def _canonical_arm_id(arm: str) -> str:
    norm = str(arm).strip().lower()
    if norm in ("arm_a", "a"):
        return "arm_a"
    if norm in ("arm_b", "b"):
        return "arm_b"
    if norm in ("arm_c", "c"):
        return "arm_c"
    return norm


def fit_probe(
    model: Any,
    train_root: str | Path,
    holdout_worlds: Sequence[Any] | set[Any] | None = None,
    *,
    n_samples: int = spec.PROBE_FIT_SAMPLES,
    seed_namespace: str = spec.PROBE_SEED_NAMESPACE,
    lam: float = spec.PROBE_RIDGE_LAMBDA,
) -> probe.RidgeProbe:
    """Fit closed-form ridge regression probe from training non-holdout episodes.

    Per DESIGN-r2.md §5 & Appendix D5.1:
    - Strictly forbids reading model.dev_Z, model.dev_XY or test hooks.
    - Excludes all holdout worlds in train partition.
    - Samples n_samples (default 2000) steps across non-holdout episodes using
      deterministic seed derived from seed_namespace (default 's2p1-train-v1|probe').
    - Observation featurization follows learned_planning.featurize_obs(student_obs, k=dt).
    - Ground truth target (x, y) read from truth_before.
    - Ridge regression lambda = spec.PROBE_RIDGE_LAMBDA (default 1.0).
    """
    if getattr(model, "dev_Z", None) is not None or getattr(model, "dev_XY", None) is not None:
        raise ValueError("model must not expose dev_Z or dev_XY test hooks; fail-closed per §5")

    if not callable(getattr(model, "encode", None)):
        raise AttributeError("model must provide callable encode method")

    root = Path(train_root)
    if not root.exists():
        raise FileNotFoundError(f"train_root {root} does not exist")

    # Determine holdout world identifiers
    holdout_set: set[Any] = set()
    if holdout_worlds is not None:
        for w in holdout_worlds:
            holdout_set.add(w)
            if isinstance(w, int):
                holdout_set.add(f"world_{w:04d}")
                holdout_set.add(str(w))
            elif isinstance(w, str):
                if w.startswith("world_"):
                    try:
                        holdout_set.add(int(w.split("_")[1]))
                    except (IndexError, ValueError):
                        pass
                else:
                    try:
                        holdout_set.add(int(w))
                    except ValueError:
                        pass
    else:
        holdout_file = root / "HOLDOUT_WORLDS.json"
        if holdout_file.exists():
            payload = json.loads(holdout_file.read_text(encoding="utf-8"))
            for w in payload.get("holdout_worlds", []):
                holdout_set.add(w)
                if isinstance(w, int):
                    holdout_set.add(f"world_{w:04d}")
                    holdout_set.add(str(w))

    # Discover candidate world directories or episode files
    world_dirs = sorted([d for d in root.iterdir() if d.is_dir() and d.name.startswith("world_")])
    candidate_files: list[Path] = []

    if world_dirs:
        for w_dir in world_dirs:
            w_name = w_dir.name
            w_idx: int | None = None
            try:
                w_idx = int(w_name.split("_")[1])
            except (IndexError, ValueError):
                pass

            if w_name in holdout_set or (w_idx is not None and w_idx in holdout_set):
                continue

            ep_files = sorted(w_dir.glob("episode_*.json"))
            if not ep_files:
                ep_files = sorted(w_dir.glob("*.json"))
                # Filter out metadata files
                ep_files = [f for f in ep_files if f.name not in ("layout.json", "goal_episode_specs.json")]
            candidate_files.extend(ep_files)
    else:
        # Direct episode files in root
        ep_files = sorted(root.glob("episode_*.json"))
        if not ep_files:
            ep_files = [f for f in sorted(root.glob("*.json")) if f.name not in ("manifest.json", "HOLDOUT_WORLDS.json")]
        candidate_files.extend(ep_files)

    if not candidate_files:
        raise FileNotFoundError(f"No non-holdout episode files found in {root}")

    # Gather all candidate steps
    all_steps: list[tuple[dict[str, Any], int, float, float]] = []
    for ep_file in candidate_files:
        payload = json.loads(ep_file.read_text(encoding="utf-8"))
        steps = payload.get("steps")
        if steps is None:
            raise ValueError(f"Episode file {ep_file} missing 'steps' field")
        for st in steps:
            if "student_obs" not in st:
                raise ValueError(f"Step missing 'student_obs' in {ep_file}")
            if "truth_before" not in st:
                raise ValueError(f"Step missing 'truth_before' in {ep_file}")
            truth_before = st["truth_before"]
            if "x" not in truth_before or "y" not in truth_before:
                raise ValueError(f"Step missing 'x' or 'y' in truth_before in {ep_file}")

            obs = st["student_obs"]
            dt = int(st.get("dt", 1))
            x_coord = float(truth_before["x"])
            y_coord = float(truth_before["y"])
            all_steps.append((obs, dt, x_coord, y_coord))

    if len(all_steps) < n_samples:
        raise ValueError(
            f"Insufficient steps for probe fitting: required {n_samples}, found {len(all_steps)}"
        )

    # Deterministic sampling without replacement
    if isinstance(seed_namespace, int):
        seed = seed_namespace
    else:
        seed = derive_probe_seed(seed_namespace)
    rng = random.Random(seed)
    sampled = rng.sample(all_steps, n_samples)

    # Encode observations and assemble arrays
    z_list: list[np.ndarray] = []
    xy_list: list[list[float]] = []
    for obs, dt, x_coord, y_coord in sampled:
        feat = learned_planning.featurize_obs(obs, dt)
        z = model.encode(feat)
        z_arr = np.asarray(z, dtype=np.float64).reshape(-1)
        z_list.append(z_arr)
        xy_list.append([x_coord, y_coord])

    Z = np.asarray(z_list, dtype=np.float64)
    XY = np.asarray(xy_list, dtype=np.float64)

    return probe.fit_ridge(Z, XY, lam=float(lam))


def probe_errors(
    model: Any,
    probe_model: probe.RidgeProbe,
    partition_root: str | Path,
    *,
    steps: Sequence[int] = spec.PROBE_EVAL_STEPS,
    start_points: Sequence[int] = spec.PROBE_START_POINTS,
    max_horizon: int = spec.PROBE_HORIZON_MAX,
) -> dict[str, Any]:
    """Evaluate multi-step rollout position prediction errors on partition episodes.

    Per DESIGN-r2.md §5 & Appendix D5.1:
    - Rolls out from start points t in start_points (t + max_horizon <= len).
    - For offsets k in steps, rolls out with predict_l1 and decodes pose with probe.
    - Error e_k = ||W*z_{t+k} - XY_{t+k}||_2 (grid units).
    - Averages error across valid start points within each episode.
    - Groups errors by world id and horizon step k.
    """
    if getattr(model, "dev_Z", None) is not None or getattr(model, "dev_XY", None) is not None:
        raise ValueError("model must not expose dev_Z or dev_XY test hooks; fail-closed per §5")

    for method in ("encode", "predict_l1"):
        if not callable(getattr(model, method, None)):
            raise AttributeError(f"model must provide callable {method!r} method")

    root = Path(partition_root)
    if not root.exists():
        raise FileNotFoundError(f"partition_root {root} does not exist")

    steps_tuple = tuple(int(k) for k in steps)
    if not steps_tuple:
        raise ValueError("steps must not be empty")
    max_step = max(steps_tuple)
    if max_step > max_horizon:
        raise ValueError(f"max step horizon {max_step} exceeds max_horizon {max_horizon}")

    # Discover world dirs or flat episode files
    world_dirs = sorted([d for d in root.iterdir() if d.is_dir() and d.name.startswith("world_")])
    world_episodes: list[tuple[int, Path]] = []

    if world_dirs:
        for w_dir in world_dirs:
            w_idx = 0
            try:
                w_idx = int(w_dir.name.split("_")[1])
            except (IndexError, ValueError):
                pass
            ep_files = sorted(w_dir.glob("episode_*.json"))
            if not ep_files:
                ep_files = [f for f in sorted(w_dir.glob("*.json")) if f.name not in ("layout.json", "goal_episode_specs.json")]
            for ep_file in ep_files:
                world_episodes.append((w_idx, ep_file))
    else:
        ep_files = sorted(root.glob("episode_*.json"))
        if not ep_files:
            ep_files = [f for f in sorted(root.glob("*.json")) if f.name not in ("manifest.json", "HOLDOUT_WORLDS.json")]
        for ep_file in ep_files:
            world_episodes.append((0, ep_file))

    if not world_episodes:
        raise FileNotFoundError(f"No episode files found in {root}")

    records: list[dict[str, Any]] = []
    by_world: dict[int, dict[int, list[float]]] = collections.defaultdict(lambda: collections.defaultdict(list))
    errors_by_k: dict[int, list[float]] = collections.defaultdict(list)

    for w_idx, ep_file in world_episodes:
        payload = json.loads(ep_file.read_text(encoding="utf-8"))
        steps_data = payload.get("steps")
        if not steps_data:
            raise ValueError(f"Episode {ep_file} missing 'steps' field")

        L = len(steps_data)
        valid_starts = [int(t) for t in start_points if t + max_horizon <= L]
        if not valid_starts:
            raise ValueError(
                f"Episode {ep_file} length {L} has no valid start points for max_horizon {max_horizon}"
            )

        # Compute errors for each start point
        start_errors: dict[int, dict[int, float]] = collections.defaultdict(dict)
        for t in valid_starts:
            st_0 = steps_data[t]
            if "student_obs" not in st_0:
                raise ValueError(f"Step {t} missing 'student_obs' in {ep_file}")
            dt_0 = int(st_0.get("dt", 1))
            x_obs_0 = learned_planning.featurize_obs(st_0["student_obs"], dt_0)
            z_curr = model.encode(x_obs_0)

            for j in range(max_step):
                curr_idx = t + j
                st_j = steps_data[curr_idx]
                act = np.asarray(st_j["action"])
                dt = float(st_j.get("dt", 1))
                z_curr = model.predict_l1(z_curr, act, dt)

                k = j + 1
                if k in steps_tuple:
                    pred_xy = probe_model.predict(z_curr).reshape(-1)
                    if t + k < L:
                        tgt = steps_data[t + k].get("truth_before")
                    else:
                        tgt = steps_data[t + k - 1].get("truth_after")

                    if tgt is None or "x" not in tgt or "y" not in tgt:
                        raise ValueError(f"Target coordinates missing at offset {k} in {ep_file}")

                    true_xy = np.array([float(tgt["x"]), float(tgt["y"])], dtype=np.float64)
                    dist = float(np.linalg.norm(pred_xy - true_xy))
                    start_errors[t][k] = dist

        # Average errors across valid start points within episode
        ep_errors: dict[int, float] = {}
        for k in steps_tuple:
            k_mean = float(np.mean([start_errors[t][k] for t in valid_starts]))
            ep_errors[k] = k_mean
            by_world[w_idx][k].append(k_mean)
            errors_by_k[k].append(k_mean)

        records.append({
            "world_id": w_idx,
            "episode_file": str(ep_file),
            "errors": ep_errors,
        })

    # Convert defaultdicts to regular dicts
    clean_by_world: dict[int, dict[int, list[float]]] = {
        w: {k: list(v) for k, v in k_map.items()}
        for w, k_map in by_world.items()
    }
    clean_errors_by_k: dict[int, list[float]] = {
        k: list(v) for k, v in errors_by_k.items()
    }
    mean_by_k: dict[int, float] = {
        k: float(np.mean(clean_errors_by_k[k])) for k in steps_tuple
    }

    return {
        "steps": steps_tuple,
        "world_ids": [r["world_id"] for r in records],
        "records": records,
        "by_world": clean_by_world,
        "errors_by_k": clean_errors_by_k,
        "mean_by_k": mean_by_k,
    }


def _extract_world_errors(seed_data: Any, k: int) -> dict[Any, list[float]]:
    """Helper to extract {world_id: [episode_errors_at_k]} from varied valid inputs."""
    if isinstance(seed_data, dict) and "by_world" in seed_data:
        out: dict[Any, list[float]] = {}
        for w, k_dict in seed_data["by_world"].items():
            if k not in k_dict:
                raise KeyError(f"Step horizon k={k} not found in probe result for world {w}")
            out[w] = [float(v) for v in k_dict[k]]
        return out

    if isinstance(seed_data, dict) and "records" in seed_data:
        temp: dict[Any, list[float]] = collections.defaultdict(list)
        for r in seed_data["records"]:
            w = r["world_id"]
            if k not in r["errors"]:
                raise KeyError(f"Step horizon k={k} not found in episode record errors")
            temp[w].append(float(r["errors"][k]))
        return dict(temp)

    if isinstance(seed_data, dict):
        out = {}
        for w, val in seed_data.items():
            if isinstance(val, dict):
                if k not in val:
                    raise KeyError(f"Step horizon k={k} not found in world {w} error dict")
                out[w] = [float(x) for x in val[k]]
            elif isinstance(val, (list, tuple, np.ndarray)):
                out[w] = [float(x) for x in val]
            else:
                raise TypeError(f"Unsupported world error data type: {type(val)}")
        return out

    raise TypeError(f"Unsupported seed data format: {type(seed_data)}")


def prediction_noninferiority(
    errors_by_arm_seed: Mapping[str, Any],
    *,
    k: int = 30,
    delta_pred: float = spec.DELTA_PRED,
    n_boot: int = spec.BOOTSTRAP_RESAMPLES,
    alpha: float = 0.05,
    rng: np.random.Generator | int | None = None,
) -> dict[str, Any]:
    """Test non-inferiority gate of Arm C against Arm A and Arm B at step horizon k.

    Per DESIGN-r2.md §5 & Appendix D5.1:
    - Arm errors are averaged across seeds for each paired episode:
        e_arm(i) = mean_{seed}(e_{arm, seed}(i))
    - Pairwise delta:
        Delta(i) = e_C(i) - min(e_A(i), e_B(i))
    - Clustered paired bootstrap (stats.cluster_paired_bootstrap) with n_boot resamples.
    - Gate passes if 95% upper confidence bound <= delta_pred (default 1.0 grid unit).
    """
    arm_map: dict[str, Any] = {}
    for arm_raw, val in errors_by_arm_seed.items():
        canonical = _canonical_arm_id(arm_raw)
        arm_map[canonical] = val

    for required_arm in ("arm_a", "arm_b", "arm_c"):
        if required_arm not in arm_map:
            raise KeyError(f"Missing required arm {required_arm!r} in errors_by_arm_seed")

    arm_world_seed_data: dict[str, list[dict[Any, list[float]]]] = {}
    for arm_name in ("arm_a", "arm_b", "arm_c"):
        seeds_data = arm_map[arm_name]
        if not isinstance(seeds_data, Mapping):
            raise TypeError(f"Errors for {arm_name} must be a mapping of seed -> data")
        if not seeds_data:
            raise ValueError(f"No seed data provided for {arm_name}")

        seed_list: list[dict[Any, list[float]]] = []
        for seed_key, seed_val in seeds_data.items():
            parsed = _extract_world_errors(seed_val, k=k)
            seed_list.append(parsed)
        arm_world_seed_data[arm_name] = seed_list

    # Ensure all arms and seeds share identical worlds
    base_worlds = sorted(arm_world_seed_data["arm_a"][0].keys())
    if len(base_worlds) < 2:
        raise ValueError(f"At least 2 worlds required for clustered bootstrap, found {len(base_worlds)}")

    for arm_name, seed_list in arm_world_seed_data.items():
        for s_idx, world_dict in enumerate(seed_list):
            if sorted(world_dict.keys()) != base_worlds:
                raise ValueError(
                    f"Mismatched worlds between arms/seeds: {sorted(world_dict.keys())} vs {base_worlds}"
                )

    # Compute episode-level errors and pairwise differences grouped by world
    diff_by_world: dict[Any, list[float]] = {}
    for w in base_worlds:
        diff_by_world[w] = []
        # Number of episodes in world w
        n_eps = len(arm_world_seed_data["arm_a"][0][w])
        for arm_name, seed_list in arm_world_seed_data.items():
            for s_idx, world_dict in enumerate(seed_list):
                if len(world_dict[w]) != n_eps:
                    raise ValueError(
                        f"Episode count mismatch in world {w} for {arm_name} seed index {s_idx}: "
                        f"{len(world_dict[w])} vs {n_eps}"
                    )

        for ep_idx in range(n_eps):
            e_a = float(np.mean([seed_list[w][ep_idx] for seed_list in arm_world_seed_data["arm_a"]]))
            e_b = float(np.mean([seed_list[w][ep_idx] for seed_list in arm_world_seed_data["arm_b"]]))
            e_c = float(np.mean([seed_list[w][ep_idx] for seed_list in arm_world_seed_data["arm_c"]]))

            delta = e_c - min(e_a, e_b)
            diff_by_world[w].append(delta)

    boot_res = stats.cluster_paired_bootstrap(
        diff_by_world,
        n_boot=n_boot,
        rng=rng,
        alpha=alpha,
    )

    passed = bool(boot_res.ci_upper <= float(delta_pred))

    return {
        "k": int(k),
        "delta_pred": float(delta_pred),
        "ci_upper": float(boot_res.ci_upper),
        "ci_lower": float(boot_res.ci_lower),
        "mean_diff": float(boot_res.mean),
        "passed": passed,
        "n_worlds": int(boot_res.n_worlds),
        "n_episodes": int(boot_res.n_episodes),
        "bootstrap": boot_res.to_dict(),
    }
