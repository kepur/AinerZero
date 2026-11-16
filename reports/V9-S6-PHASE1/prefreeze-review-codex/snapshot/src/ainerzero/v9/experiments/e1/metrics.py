"""E1 metric computations (pure NumPy; frozen preregistration definitions).

All functions here are deterministic, side-effect free, and unit-tested with
synthetic cases having known answers plus broken controls (mutating predictions
moves metrics in the declared bad direction).

The metrics implement the registered S1 Phase 2 / E1 frozen specification
(reports/V9-P48/PREREG_DRAFT.md):
- k-step position error (k in {1, 5, 10, 30}, primary k=10; excluding endpoint frames).
- Collision event extraction (no contact -> contact with normal relative velocity >= 0.05 m/s,
  debounced over 3 frames) and F1 evaluation under +/-1 frame match tolerance.
- Ballistic segment energy drift (|Delta H| / H_0) on continuous contact-free intervals (>= 5 frames).
- Device inference latency summarization (median, p95).
- Hierarchical seed aggregation (macro-average of seed-level episode means across 3 training seeds).
- Paired episode bootstrap (10,000 resamples, frozen RNG seed) for 95% confidence intervals.
- Failure subset stratification (DESIGN_CORE sec 2 item 9).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping, NamedTuple, Sequence

import numpy as np

# --- Frozen Constants (PREREG_DRAFT §4 & §5) ---
DEFAULT_K_STEPS: tuple[int, ...] = (1, 5, 10, 30)
PRIMARY_K: int = 10
CONTACT_TOLERANCE_M: float = 0.004  # 4 mm exact shape surface distance
COLLISION_VELOCITY_THRESHOLD_MPS: float = 0.05  # 0.05 m/s normal relative velocity
COLLISION_DEBOUNCE_FRAMES: int = 3  # re-contact within <= 3 frames merged
COLLISION_MATCH_TOLERANCE_FRAMES: int = 1  # match within +/- 1 frame
BALLISTIC_MIN_FRAMES: int = 5  # ballistic segments must be >= 5 continuous frames
GRAVITY_ACCEL: float = 9.81  # m/s^2 along -Z axis
BOOTSTRAP_RESAMPLES: int = 10000  # 10,000 resamples
BOOTSTRAP_SEED: int = 42  # frozen resampling seed
BOOTSTRAP_CONFIDENCE: float = 0.95  # 95% confidence interval


@dataclass(frozen=True)
class CollisionEvent:
    """Represents a discrete collision event between an object pair."""

    pair_id: tuple[int, int] | str | int
    start_frame: int
    end_frame: int
    max_velocity: float
    debounce_count: int = 0

    def canonical_pair_id(self) -> Any:
        """Return canonical order-independent pair ID if pair_id is a 2-tuple."""
        if isinstance(self.pair_id, tuple) and len(self.pair_id) == 2:
            return tuple(sorted(self.pair_id))
        return self.pair_id


def _ensure_finite_array(
    value: Any,
    *,
    name: str = "array",
    min_dims: int | None = None,
    max_dims: int | None = None,
) -> np.ndarray:
    """Convert input to float64 numpy array and verify it is non-empty and finite."""
    arr = np.asarray(value, dtype=np.float64)
    if arr.size == 0:
        raise ValueError(f"{name} must not be empty")
    if min_dims is not None and arr.ndim < min_dims:
        raise ValueError(f"{name} must have at least {min_dims} dimensions, got {arr.ndim}")
    if max_dims is not None and arr.ndim > max_dims:
        raise ValueError(f"{name} must have at most {max_dims} dimensions, got {arr.ndim}")
    if not np.all(np.isfinite(arr)):
        raise ValueError(f"{name} must contain only finite numbers (no NaN or Inf)")
    return arr


# =========================================================================
# 1. k-step Position Error (PREREG_DRAFT §4 item 1)
# =========================================================================

def compute_position_error(
    pred_positions: Any,
    true_positions: Any,
) -> dict[str, float | int]:
    """Compute Euclidean position error between predicted and true positions.

    Supports arrays of shape (N, 3), (N, num_objects, 3), or any matching shapes
    whose last axis has length 3.

    Returns:
        dict with mean_error_m, median_error_m, rmse_m, max_error_m, and count.
    """
    pred = _ensure_finite_array(pred_positions, name="pred_positions", min_dims=2)
    truth = _ensure_finite_array(true_positions, name="true_positions", min_dims=2)
    if pred.shape != truth.shape:
        raise ValueError(f"Shape mismatch: pred {pred.shape} vs truth {truth.shape}")
    if pred.shape[-1] != 3:
        raise ValueError(f"Last axis of positions must be 3 (x, y, z), got {pred.shape[-1]}")

    errors = np.linalg.norm(pred - truth, axis=-1)  # shape (...,)
    flat_errors = errors.reshape(-1)

    return {
        "mean_error_m": float(np.mean(flat_errors)),
        "median_error_m": float(np.median(flat_errors)),
        "rmse_m": float(np.sqrt(np.mean(flat_errors**2))),
        "max_error_m": float(np.max(flat_errors)),
        "count": int(flat_errors.size),
    }


def compute_horizon_position_errors(
    pred_future: Any,
    truth_positions: Any,
    prefix_frames: int = 10,
    k_steps: Sequence[int] = DEFAULT_K_STEPS,
    exclude_endpoints: bool = True,
    primary_k: int = PRIMARY_K,
) -> dict[str, Any]:
    """Compute single-origin horizon position errors (PREREG_DRAFT r2 / P89).

    Each horizon step k evaluates the prediction at target frame = prefix_frames - 1 + k.
    pred_future item j (0-indexed) corresponds to frame prefix_frames + j.
    Thus pred_future[k - 1] predicts frame target_frame.

    Parameters:
        pred_future: predicted positions on future window, shape (n_future, num_objects, 3) or (n_future, 3).
        truth_positions: full episode ground truth positions, shape (T, num_objects, 3) or (T, 3).
        prefix_frames: number of observation prefix frames (default 10).
        k_steps: sequence of horizon steps to evaluate (default 1, 5, 10, 30).
        exclude_endpoints: whether to exclude boundary frame T-1. If True and target_frame == T-1
            (or >= T-1), horizon k is marked unavailable.
        primary_k: primary horizon step for decision checks (default 10).

    Returns:
        dict mapping available k (as string) to its position error dict, plus:
        - "primary_k": int
        - "primary_error_m": float (omitted if primary_k is unavailable)
        - "unavailable_k": list[int] listing any k that could not be evaluated.
    """
    pred = _ensure_finite_array(pred_future, name="pred_future", min_dims=2)
    truth = _ensure_finite_array(truth_positions, name="truth_positions", min_dims=2)

    if pred.shape[-1] != 3:
        raise ValueError(f"Last axis of pred_future must be 3, got {pred.shape[-1]}")
    if truth.shape[-1] != 3:
        raise ValueError(f"Last axis of truth_positions must be 3, got {truth.shape[-1]}")
    if pred.ndim != truth.ndim or pred.shape[1:] != truth.shape[1:]:
        raise ValueError(f"Shape mismatch: pred_future {pred.shape} vs truth_positions {truth.shape}")

    n_future = pred.shape[0]
    t_total = truth.shape[0]

    results: dict[str, Any] = {}
    unavailable_k: list[int] = []
    primary_error: float | None = None

    for k in k_steps:
        k_int = int(k)
        target_frame = prefix_frames - 1 + k_int

        is_unavailable = False
        if k_int > n_future:
            is_unavailable = True
        elif target_frame >= t_total:
            is_unavailable = True
        elif exclude_endpoints and target_frame >= t_total - 1:
            is_unavailable = True

        if is_unavailable:
            unavailable_k.append(k_int)
            continue

        pred_idx = k_int - 1
        pred_k = pred[pred_idx]
        truth_k = truth[target_frame]

        err_dict = compute_position_error(pred_k, truth_k)
        err_dict["k"] = k_int
        err_dict["target_frame"] = int(target_frame)
        results[str(k_int)] = err_dict

        if k_int == primary_k:
            primary_error = float(err_dict["mean_error_m"])

    results["primary_k"] = int(primary_k)
    if primary_error is not None:
        results["primary_error_m"] = primary_error
    results["unavailable_k"] = unavailable_k
    return results


def compute_k_step_position_errors(
    pred_trajectories_by_k: Mapping[int, Any],
    true_positions: Any,
    *,
    k_steps: Sequence[int] = DEFAULT_K_STEPS,
    primary_k: int = PRIMARY_K,
    exclude_endpoints: bool = True,
) -> dict[str, Any]:
    """Compute position errors for specified prediction horizons k using a sliding window.

    Note:
        滑动起点定义，E1 不用。
        This function uses a sliding window definition across the entire rollout.
        E1 evaluation does not use this function (it uses compute_horizon_position_errors instead).

    Parameters:
        pred_trajectories_by_k: mapping from horizon k to predicted positions at t+k.
            For each k, pred_trajectories_by_k[k] can be:
            - an array of shape (T_eval, num_objects, 3) or (T_eval, 3) aligned with
              true_positions[valid_target_indices].
            - OR a full rollout array of shape (T, num_objects, 3) aligned with true_positions.
        true_positions: full episode ground truth positions, shape (T, num_objects, 3) or (T, 3).
        k_steps: sequence of horizon steps to evaluate (default 1, 5, 10, 30).
        primary_k: primary horizon for threshold checks (default 10).
        exclude_endpoints: whether to exclude boundary frames (0 and T-1) from the
            evaluation window, as mandated by PREREG_DRAFT §4 item 1 ("评测窗口不含端点帧").

    Returns:
        dict mapping each k to its position error dict, plus "primary_k" and "primary_error_m".
    """
    truth = _ensure_finite_array(true_positions, name="true_positions", min_dims=2)
    t_total = truth.shape[0]

    results: dict[str, Any] = {}
    primary_error: float | None = None

    for k in k_steps:
        if k not in pred_trajectories_by_k:
            continue
        pred_k = _ensure_finite_array(pred_trajectories_by_k[k], name=f"pred_k_{k}", min_dims=2)

        # Determine valid target window
        # Internal frames only if exclude_endpoints is True:
        # frame 0 and frame T-1 are excluded from target evaluation.
        # Target t+k must satisfy: 1 <= t+k <= T-2
        # Base frame t must satisfy: 1 <= t <= T-2-k (if base is also internal) or 0 <= t <= T-1-k
        if exclude_endpoints:
            # Base frames t in [1, t_total - 2 - k], target frames in [1 + k, t_total - 2]
            target_indices = np.arange(1 + k, t_total - 1)
        else:
            target_indices = np.arange(k, t_total)

        if len(target_indices) == 0:
            raise ValueError(f"Episode length T={t_total} too short for k={k} evaluation")

        truth_target = truth[target_indices]

        # Check alignment: pred_k may already be sliced to target_indices or full length T
        if pred_k.shape[0] == truth.shape[0]:
            pred_eval = pred_k[target_indices]
        elif pred_k.shape[0] == len(target_indices):
            pred_eval = pred_k
        else:
            raise ValueError(
                f"pred_trajectories_by_k[{k}] length {pred_k.shape[0]} matches neither "
                f"total length {truth.shape[0]} nor target window length {len(target_indices)}"
            )

        err_dict = compute_position_error(pred_eval, truth_target)
        err_dict["k"] = int(k)
        err_dict["valid_target_frames"] = int(len(target_indices))
        results[str(k)] = err_dict

        if k == primary_k:
            primary_error = float(err_dict["mean_error_m"])

    results["primary_k"] = int(primary_k)
    results["primary_error_m"] = primary_error
    return results


# =========================================================================
# 2. Collision Event Extraction & F1 (PREREG_DRAFT §4 item 2)
# =========================================================================

def detect_collision_events(
    distances: Any,
    relative_velocities: Any,
    *,
    contact_tolerance: float = CONTACT_TOLERANCE_M,
    vel_threshold: float = COLLISION_VELOCITY_THRESHOLD_MPS,
    debounce_frames: int = COLLISION_DEBOUNCE_FRAMES,
    pair_id: tuple[int, int] | str | int = (0, 1),
    initial_in_contact: bool = False,
) -> list[CollisionEvent]:
    """Detect debounced collision events for a single pair of objects.

    A collision event starts when an object pair transitions from 'no contact'
    (surface distance > contact_tolerance) to 'contact' (surface distance <= contact_tolerance)
    with normal relative closing velocity >= vel_threshold.

    Debouncing:
    If the pair separates (distance > contact_tolerance) and re-contacts within
    <= debounce_frames (e.g. 3 frames), the re-contact is merged into the existing
    event rather than creating a new one (PREREG_DRAFT §4 item 2).

    Parameters:
        distances: 1D array of surface distances over time, shape (T,).
        relative_velocities: 1D array of normal relative velocities over time, shape (T,).
        contact_tolerance: threshold distance for contact (default 0.004 m).
        vel_threshold: minimum normal relative velocity at transition (default 0.05 m/s).
        debounce_frames: maximum separation frames to merge re-contact (default 3 frames).
        pair_id: identifier for the object pair.
        initial_in_contact: whether the objects were in contact before frame 0.

    Returns:
        list of CollisionEvent instances.
    """
    dists = _ensure_finite_array(distances, name="distances", min_dims=1, max_dims=1)
    vels = _ensure_finite_array(relative_velocities, name="relative_velocities", min_dims=1, max_dims=1)
    if len(dists) != len(vels):
        raise ValueError(f"Length mismatch: distances {len(dists)} vs velocities {len(vels)}")

    t_total = len(dists)
    in_contact = dists <= contact_tolerance

    events: list[CollisionEvent] = []

    # State tracking
    active_event_start: int | None = None
    active_event_end: int | None = None
    active_max_vel: float = 0.0
    active_debounces: int = 0
    separation_counter: int = 0
    was_in_contact: bool = initial_in_contact

    for t in range(t_total):
        curr_contact = bool(in_contact[t])
        curr_vel = float(vels[t])

        if curr_contact:
            if active_event_start is not None:
                # We have an ongoing event that was either continuous or debounced
                if separation_counter > 0:
                    # Re-contact within debounce window!
                    active_debounces += 1
                active_event_end = t
                active_max_vel = max(active_max_vel, curr_vel)
                separation_counter = 0
            else:
                # No active event. Check if this is a transition from no-contact
                if not was_in_contact:
                    if curr_vel >= vel_threshold:
                        # Start new collision event
                        active_event_start = t
                        active_event_end = t
                        active_max_vel = curr_vel
                        active_debounces = 0
                        separation_counter = 0
            was_in_contact = True
        else:
            # Current frame is no-contact
            if active_event_start is not None:
                separation_counter += 1
                if separation_counter > debounce_frames:
                    # Separation lasted > debounce_frames: close the event
                    assert active_event_end is not None
                    events.append(
                        CollisionEvent(
                            pair_id=pair_id,
                            start_frame=active_event_start,
                            end_frame=active_event_end,
                            max_velocity=active_max_vel,
                            debounce_count=active_debounces,
                        )
                    )
                    active_event_start = None
                    active_event_end = None
                    separation_counter = 0
            was_in_contact = False

    # Flush any trailing active event at the end of the episode
    if active_event_start is not None:
        assert active_event_end is not None
        events.append(
            CollisionEvent(
                pair_id=pair_id,
                start_frame=active_event_start,
                end_frame=active_event_end,
                max_velocity=active_max_vel,
                debounce_count=active_debounces,
            )
        )

    return events


def compute_collision_f1(
    pred_events: Sequence[CollisionEvent],
    true_events: Sequence[CollisionEvent],
    *,
    match_tolerance_frames: int = COLLISION_MATCH_TOLERANCE_FRAMES,
) -> dict[str, float | int]:
    """Compute Precision, Recall, and F1 between predicted and true collision events.

    Matching rules (PREREG_DRAFT §4 item 2):
    1. A predicted event matches a true event if and only if they involve the same
       pair of objects (order-independent).
    2. The start frames differ by at most +/- match_tolerance_frames (default +/- 1 frame).
    3. Each true event can be matched at most once (1-to-1 matching, minimizing |t_pred - t_true|).

    Returns:
        dict with precision, recall, f1, true_positives, false_positives, false_negatives.
    """
    n_pred = len(pred_events)
    n_true = len(true_events)

    if n_pred == 0 and n_true == 0:
        return {
            "precision": 1.0,
            "recall": 1.0,
            "f1": 1.0,
            "true_positives": 0,
            "false_positives": 0,
            "false_negatives": 0,
            "num_pred_events": 0,
            "num_true_events": 0,
        }

    if n_pred == 0 or n_true == 0:
        return {
            "precision": 0.0,
            "recall": 0.0,
            "f1": 0.0,
            "true_positives": 0,
            "false_positives": n_pred,
            "false_negatives": n_true,
            "num_pred_events": n_pred,
            "num_true_events": n_true,
        }

    # Build candidate matches: (distance, true_idx, pred_idx)
    candidates: list[tuple[int, int, int]] = []
    for p_idx, p_ev in enumerate(pred_events):
        p_canon = p_ev.canonical_pair_id()
        for t_idx, t_ev in enumerate(true_events):
            t_canon = t_ev.canonical_pair_id()
            if p_canon == t_canon:
                frame_diff = abs(p_ev.start_frame - t_ev.start_frame)
                if frame_diff <= match_tolerance_frames:
                    candidates.append((frame_diff, t_idx, p_idx))

    # Greedy 1-to-1 matching sorted by frame distance ascending
    candidates.sort(key=lambda item: (item[0], item[1], item[2]))

    matched_true: set[int] = set()
    matched_pred: set[int] = set()

    for diff, t_idx, p_idx in candidates:
        if t_idx not in matched_true and p_idx not in matched_pred:
            matched_true.add(t_idx)
            matched_pred.add(p_idx)

    tp = len(matched_true)
    fp = n_pred - tp
    fn = n_true - tp

    precision = float(tp / (tp + fp)) if (tp + fp) > 0 else 0.0
    recall = float(tp / (tp + fn)) if (tp + fn) > 0 else 0.0
    f1 = float(2.0 * precision * recall / (precision + recall)) if (precision + recall) > 0 else 0.0

    return {
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "true_positives": tp,
        "false_positives": fp,
        "false_negatives": fn,
        "num_pred_events": n_pred,
        "num_true_events": n_true,
    }


# =========================================================================
# 3. Ballistic Energy Drift (PREREG_DRAFT §4 item 3)
# =========================================================================

def compute_ballistic_energy_drift(
    positions: Any,
    velocities: Any,
    *,
    in_contact: Any | None = None,
    distances: Any | None = None,
    contact_tolerance: float = CONTACT_TOLERANCE_M,
    mass: float = 1.0,
    min_segment_frames: int = BALLISTIC_MIN_FRAMES,
    g: float = GRAVITY_ACCEL,
    eps: float = 1e-9,
) -> dict[str, Any]:
    """Compute relative energy drift |Delta H| / H_0 on ballistic flight segments.

    Physics definition (PREREG_DRAFT §4 item 3):
    - H(t) = 0.5 * m * ||v(t)||^2 + m * g * z(t)  (translational kinetic + potential energy)
    - Evaluated exclusively on ballistic segments: contiguous contact-free intervals
      (surface distance > contact_tolerance) with length >= min_segment_frames (default 5 frames).
    - Intervals shorter than min_segment_frames are discarded to avoid boundary noise.
    - Diagnostic only; no threshold gate is placed on energy drift.

    Parameters:
        positions: array of shape (T, 3) representing (x, y, z) in meters (Z is up).
        velocities: array of shape (T, 3) representing (vx, vy, vz) in m/s.
        in_contact: optional boolean array of shape (T,).
        distances: optional array of shape (T,) surface distances. Used if in_contact is None.
        contact_tolerance: surface distance threshold (0.004 m).
        mass: mass in kg (default 1.0; factors out if constant).
        min_segment_frames: minimum contiguous no-contact frames (default 5).
        g: gravitational acceleration (9.81 m/s^2).
        eps: safeguard against division by near-zero initial energy.

    Returns:
        dict with segments_count, max_drift, mean_drift, and detailed segment records.
    """
    pos = _ensure_finite_array(positions, name="positions", min_dims=2, max_dims=2)
    vel = _ensure_finite_array(velocities, name="velocities", min_dims=2, max_dims=2)
    if pos.shape != vel.shape or pos.shape[1] != 3:
        raise ValueError(f"positions and velocities must both have shape (T, 3), got {pos.shape}")

    t_total = pos.shape[0]

    # Contact mask
    if in_contact is not None:
        contact_mask = np.asarray(in_contact, dtype=bool)
        if contact_mask.shape != (t_total,):
            raise ValueError(f"in_contact shape {contact_mask.shape} != ({t_total},)")
    elif distances is not None:
        dists = _ensure_finite_array(distances, name="distances", min_dims=1, max_dims=1)
        if len(dists) != t_total:
            raise ValueError(f"distances length {len(dists)} != {t_total}")
        contact_mask = dists <= contact_tolerance
    else:
        # If neither is provided, assume entire trajectory is contact-free
        contact_mask = np.zeros(t_total, dtype=bool)

    # Compute energy H(t) = 0.5 * m * ||v||^2 + m * g * z
    v_sq = np.sum(vel**2, axis=-1)
    z = pos[:, 2]
    energy = 0.5 * mass * v_sq + mass * g * z

    # Identify contiguous no-contact segments
    segments: list[dict[str, Any]] = []
    seg_start: int | None = None

    for t in range(t_total):
        if not contact_mask[t]:
            if seg_start is None:
                seg_start = t
        else:
            if seg_start is not None:
                seg_len = t - seg_start
                if seg_len >= min_segment_frames:
                    segments.append({"start": seg_start, "end": t - 1, "length": seg_len})
                seg_start = None

    if seg_start is not None:
        seg_len = t_total - seg_start
        if seg_len >= min_segment_frames:
            segments.append({"start": seg_start, "end": t_total - 1, "length": seg_len})

    if not segments:
        return {
            "segments_count": 0,
            "max_drift": None,
            "mean_drift": None,
            "segments": [],
        }

    segment_records: list[dict[str, Any]] = []
    all_max_drifts: list[float] = []
    all_mean_drifts: list[float] = []

    for seg in segments:
        s, e = seg["start"], seg["end"]
        h_seg = energy[s : e + 1]
        h0 = float(h_seg[0])
        h0_denom = abs(h0) if abs(h0) > eps else eps

        rel_drifts = np.abs(h_seg - h0) / h0_denom
        seg_max = float(np.max(rel_drifts))
        seg_mean = float(np.mean(rel_drifts))
        seg_final = float(rel_drifts[-1])

        all_max_drifts.append(seg_max)
        all_mean_drifts.append(seg_mean)

        segment_records.append(
            {
                "start_frame": int(s),
                "end_frame": int(e),
                "length": int(seg["length"]),
                "h0": h0,
                "max_drift": seg_max,
                "mean_drift": seg_mean,
                "final_drift": seg_final,
            }
        )

    return {
        "segments_count": int(len(segments)),
        "max_drift": float(np.max(all_max_drifts)),
        "mean_drift": float(np.mean(all_mean_drifts)),
        "segments": segment_records,
    }


# =========================================================================
# 4. Inference Latency Summary (PREREG_DRAFT §4 item 4)
# =========================================================================

def summarize_inference_latency(latencies: Any) -> dict[str, float | int]:
    """Summarize step latencies (median, p95, mean, min, max).

    Returns:
        dict with median_ms, p95_ms, mean_ms, min_ms, max_ms, and count.
    """
    arr = _ensure_finite_array(latencies, name="latencies", min_dims=1, max_dims=1)
    return {
        "count": int(arr.size),
        "median_ms": float(np.median(arr)),
        "p95_ms": float(np.percentile(arr, 95.0)),
        "mean_ms": float(np.mean(arr)),
        "min_ms": float(np.min(arr)),
        "max_ms": float(np.max(arr)),
    }


# =========================================================================
# 5. Seed Aggregation & Paired Bootstrap (PREREG_DRAFT §5)
# =========================================================================

def aggregate_seeds_macro(seed_episode_metrics: Any) -> dict[str, Any]:
    """Compute hierarchical seed aggregation across training seeds.

    Specification (PREREG_DRAFT §5):
    - Each training seed first computes its own episode mean.
    - The macro-average across the 3 seeds is taken for comparison.

    Parameters:
        seed_episode_metrics: 2D array of shape (num_seeds, num_episodes) or sequence of 1D arrays.

    Returns:
        dict with macro_mean, seed_means, num_seeds, num_episodes.
    """
    arr = _ensure_finite_array(seed_episode_metrics, name="seed_episode_metrics", min_dims=2, max_dims=2)
    n_seeds, n_episodes = arr.shape
    if n_seeds < 1 or n_episodes < 1:
        raise ValueError(f"Need at least 1 seed and 1 episode, got shape {arr.shape}")

    seed_means = np.mean(arr, axis=1)
    macro_mean = float(np.mean(seed_means))

    return {
        "macro_mean": macro_mean,
        "seed_means": [float(m) for m in seed_means],
        "num_seeds": int(n_seeds),
        "num_episodes": int(n_episodes),
    }


def paired_bootstrap_ci(
    episodes_a: Any,
    episodes_b: Any,
    *,
    n_resamples: int = BOOTSTRAP_RESAMPLES,
    seed: int = BOOTSTRAP_SEED,
    confidence_level: float = BOOTSTRAP_CONFIDENCE,
    mode: str = "relative",
) -> dict[str, Any]:
    """Compute paired episode bootstrap confidence interval across seeds.

    Specification (PREREG_DRAFT §5):
    - Resample episode indices with replacement (10,000 resamples, frozen RNG seed).
    - For each resample, the exact same episode indices are evaluated across all seeds
      and across both Arm A and Arm B (paired comparison).
    - For each arm, seed means are computed on the resampled episodes, followed by
      the macro-average across seeds.
    - Difference is computed per resample:
      - if mode == 'relative': (macro_b - macro_a) / macro_a
      - if mode == 'absolute': (macro_b - macro_a)
    - 95% confidence interval is extracted from the 2.5% and 97.5% percentiles.

    Parameters:
        episodes_a: shape (num_seeds, num_episodes) for baseline arm.
        episodes_b: shape (num_seeds, num_episodes) for candidate arm.
        n_resamples: number of bootstrap resamples (default 10000).
        seed: random seed for reproducibility (default 42).
        confidence_level: confidence level (default 0.95).
        mode: 'relative' or 'absolute'.

    Returns:
        dict with point_estimate, macro_a, macro_b, ci_lower, ci_upper, ci_width,
        contains_zero, confidence_level, n_resamples, seed.
    """
    arr_a = _ensure_finite_array(episodes_a, name="episodes_a", min_dims=2, max_dims=2)
    arr_b = _ensure_finite_array(episodes_b, name="episodes_b", min_dims=2, max_dims=2)
    if arr_a.shape != arr_b.shape:
        raise ValueError(f"Shape mismatch: episodes_a {arr_a.shape} vs episodes_b {arr_b.shape}")

    n_seeds, n_episodes = arr_a.shape
    if n_episodes < 2:
        raise ValueError(f"Need at least 2 episodes for bootstrap, got {n_episodes}")

    # Point estimate on unresampled data
    macro_a = float(np.mean(np.mean(arr_a, axis=1)))
    macro_b = float(np.mean(np.mean(arr_b, axis=1)))

    if mode == "relative":
        if abs(macro_a) < 1e-12:
            raise ValueError("macro_a is effectively zero; cannot compute relative difference")
        point_estimate = float((macro_b - macro_a) / macro_a)
    elif mode == "absolute":
        point_estimate = float(macro_b - macro_a)
    else:
        raise ValueError(f"Unknown mode {mode!r}, must be 'relative' or 'absolute'")

    # Vectorized bootstrap resampling
    rng = np.random.default_rng(seed)
    resample_indices = rng.integers(0, n_episodes, size=(n_resamples, n_episodes))

    # Vectorized gather: arr has shape (n_seeds, n_episodes)
    # arr[:, resample_indices] has shape (n_seeds, n_resamples, n_episodes)
    gather_a = arr_a[:, resample_indices]
    gather_b = arr_b[:, resample_indices]

    # Means per seed: shape (n_seeds, n_resamples)
    seed_means_a = np.mean(gather_a, axis=2)
    seed_means_b = np.mean(gather_b, axis=2)

    # Macro average across seeds: shape (n_resamples,)
    macro_resamples_a = np.mean(seed_means_a, axis=0)
    macro_resamples_b = np.mean(seed_means_b, axis=0)

    if mode == "relative":
        deltas = (macro_resamples_b - macro_resamples_a) / macro_resamples_a
    else:
        deltas = macro_resamples_b - macro_resamples_a

    alpha = 1.0 - confidence_level
    q_lower = 100.0 * (alpha / 2.0)
    q_upper = 100.0 * (1.0 - alpha / 2.0)

    ci_lower = float(np.percentile(deltas, q_lower))
    ci_upper = float(np.percentile(deltas, q_upper))

    return {
        "point_estimate": point_estimate,
        "macro_a": macro_a,
        "macro_b": macro_b,
        "ci_lower": ci_lower,
        "ci_upper": ci_upper,
        "ci_width": float(ci_upper - ci_lower),
        "contains_zero": bool(ci_lower <= 0.0 <= ci_upper),
        "confidence_level": float(confidence_level),
        "n_resamples": int(n_resamples),
        "seed": int(seed),
        "mode": mode,
    }


# =========================================================================
# 6. Failure Subset Stratification (DESIGN_CORE §2 item 9)
# =========================================================================

def stratify_failure_subset(
    episode_metrics: Any,
    is_failure_subset: Any,
) -> dict[str, Any]:
    """Stratify episode metrics by failure subset membership.

    Parameters:
        episode_metrics: 1D array of shape (N,) or 2D array of shape (S, N).
        is_failure_subset: 1D boolean array of shape (N,) indicating whether
            each episode belongs to the registered failure subset.

    Returns:
        dict with overall, failure_subset, and non_failure_subset statistics.
    """
    arr = _ensure_finite_array(episode_metrics, name="episode_metrics", min_dims=1, max_dims=2)
    is_fail = np.asarray(is_failure_subset, dtype=bool)

    n_episodes = arr.shape[-1]
    if is_fail.shape != (n_episodes,):
        raise ValueError(f"is_failure_subset shape {is_fail.shape} != ({n_episodes},)")

    fail_count = int(np.sum(is_fail))
    non_fail_count = n_episodes - fail_count

    if arr.ndim == 1:
        overall_mean = float(np.mean(arr))
        fail_mean = float(np.mean(arr[is_fail])) if fail_count > 0 else None
        non_fail_mean = float(np.mean(arr[~is_fail])) if non_fail_count > 0 else None
    else:
        overall_mean = float(np.mean(np.mean(arr, axis=1)))
        fail_mean = float(np.mean(np.mean(arr[:, is_fail], axis=1))) if fail_count > 0 else None
        non_fail_mean = float(np.mean(np.mean(arr[:, ~is_fail], axis=1))) if non_fail_count > 0 else None

    return {
        "overall_mean": overall_mean,
        "failure_subset_mean": fail_mean,
        "non_failure_subset_mean": non_fail_mean,
        "total_episodes": int(n_episodes),
        "failure_episodes_count": fail_count,
        "non_failure_episodes_count": non_fail_count,
    }
