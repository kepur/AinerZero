"""Tests for E1 metric module (pure NumPy / CPU).

Covers:
- Frozen constant verification against PREREG_DRAFT §4 & §5.
- Analytical known answers (exact zero error, free fall energy conservation).
- Broken controls (adversarial mutations moving metrics in declared bad directions).
- Micro-bounce debouncing (<= 3 frames merged vs > 3 frames separated).
- Ballistic segment filtering (< 5 frames discarded vs >= 5 frames evaluated).
- Event matching tolerance (+/- 1 frame match vs +/- 2 frames mismatch).
- Paired bootstrap CI coverage, macro seed aggregation, and reproducibility.
- Failure subset stratification.
- Rigorous input validation (rejection of non-finite, bad shapes, empty inputs).
"""

from __future__ import annotations

import math
import numpy as np
import pytest

from ainerzero.v9.experiments.e1 import metrics
from ainerzero.v9.experiments.e1.metrics import (
    BALLISTIC_MIN_FRAMES,
    BOOTSTRAP_CONFIDENCE,
    BOOTSTRAP_RESAMPLES,
    BOOTSTRAP_SEED,
    COLLISION_DEBOUNCE_FRAMES,
    COLLISION_MATCH_TOLERANCE_FRAMES,
    COLLISION_VELOCITY_THRESHOLD_MPS,
    CONTACT_TOLERANCE_M,
    DEFAULT_K_STEPS,
    GRAVITY_ACCEL,
    PRIMARY_K,
    CollisionEvent,
    aggregate_seeds_macro,
    compute_ballistic_energy_drift,
    compute_collision_f1,
    compute_k_step_position_errors,
    compute_position_error,
    detect_collision_events,
    paired_bootstrap_ci,
    stratify_failure_subset,
    summarize_inference_latency,
)


# =========================================================================
# 1. Frozen Constants Verification
# =========================================================================

def test_frozen_constants_match_prereg():
    """Verify all constants strictly match PREREG_DRAFT r2/r3."""
    assert DEFAULT_K_STEPS == (1, 5, 10, 30)
    assert PRIMARY_K == 10
    assert CONTACT_TOLERANCE_M == 0.004
    assert COLLISION_VELOCITY_THRESHOLD_MPS == 0.05
    assert COLLISION_DEBOUNCE_FRAMES == 3
    assert COLLISION_MATCH_TOLERANCE_FRAMES == 1
    assert BALLISTIC_MIN_FRAMES == 5
    assert GRAVITY_ACCEL == 9.81
    assert BOOTSTRAP_RESAMPLES == 10000
    assert BOOTSTRAP_SEED == 42
    assert BOOTSTRAP_CONFIDENCE == 0.95


# =========================================================================
# 2. k-step Position Error & Broken Controls
# =========================================================================

def test_position_error_known_answer_and_broken_control():
    """Test position error on known offsets and verify broken control degradation."""
    truth = np.array(
        [
            [0.0, 0.0, 1.0],
            [1.0, 2.0, 3.0],
            [2.0, 0.0, 0.0],
        ]
    )

    # 1. Perfect prediction -> 0 error
    perfect = truth.copy()
    res_perf = compute_position_error(perfect, truth)
    assert res_perf["mean_error_m"] == 0.0
    assert res_perf["median_error_m"] == 0.0
    assert res_perf["rmse_m"] == 0.0
    assert res_perf["max_error_m"] == 0.0
    assert res_perf["count"] == 3

    # 2. Known constant shift of dx=0.1, dy=0.2, dz=0.2 -> dist = sqrt(0.01+0.04+0.04) = 0.3
    shifted = truth + np.array([0.1, 0.2, 0.2])
    res_shifted = compute_position_error(shifted, truth)
    assert res_shifted["mean_error_m"] == pytest.approx(0.3)
    assert res_shifted["rmse_m"] == pytest.approx(0.3)
    assert res_shifted["max_error_m"] == pytest.approx(0.3)

    # 3. Broken control: larger mutation strictly increases error
    worse = truth + np.array([0.2, 0.4, 0.4])  # dist = 0.6
    res_worse = compute_position_error(worse, truth)
    assert res_worse["mean_error_m"] == pytest.approx(0.6)
    assert res_worse["mean_error_m"] > res_shifted["mean_error_m"]
    assert res_worse["rmse_m"] > res_shifted["rmse_m"]


def test_k_step_position_errors_sliding_window_and_endpoints():
    """Test k-step error computation and endpoint frame exclusion."""
    t_total = 50
    # Create synthetic trajectory: object moving linearly
    t_arr = np.linspace(0, 1, t_total)[:, None]
    truth = np.hstack([t_arr, t_arr * 2.0, np.ones((t_total, 1))])  # (50, 3)

    # Perfect prediction at all k
    pred_dict = {k: truth.copy() for k in [1, 5, 10, 30]}

    # exclude_endpoints=True: target frames in [1 + k, 48]
    res = compute_k_step_position_errors(pred_dict, truth, k_steps=[1, 5, 10, 30], exclude_endpoints=True)
    assert res["primary_k"] == 10
    assert res["primary_error_m"] == 0.0

    # For k=10: target frames are [11, 48], count = 38 frames
    assert res["10"]["valid_target_frames"] == 38
    assert res["10"]["mean_error_m"] == 0.0

    # Broken control: perturb prediction at k=10 only
    broken_pred_dict = {k: truth.copy() for k in [1, 5, 10, 30]}
    broken_pred_dict[10] = truth + 0.5
    res_broken = compute_k_step_position_errors(
        broken_pred_dict, truth, k_steps=[1, 5, 10, 30], exclude_endpoints=True
    )
    assert res_broken["10"]["mean_error_m"] == pytest.approx(np.sqrt(3 * 0.25))
    assert res_broken["primary_error_m"] > res["primary_error_m"]
    # k=1 and k=5 remain zero
    assert res_broken["1"]["mean_error_m"] == 0.0
    assert res_broken["5"]["mean_error_m"] == 0.0


def test_position_error_rejects_invalid_inputs():
    """Verify robust input validation."""
    with pytest.raises(ValueError, match="must not be empty"):
        compute_position_error(np.zeros((0, 3)), np.zeros((0, 3)))

    with pytest.raises(ValueError, match="Shape mismatch"):
        compute_position_error(np.zeros((10, 3)), np.zeros((12, 3)))

    with pytest.raises(ValueError, match="Last axis of positions must be 3"):
        compute_position_error(np.zeros((10, 2)), np.zeros((10, 2)))

    with pytest.raises(ValueError, match="finite"):
        bad = np.zeros((5, 3))
        bad[1, 1] = np.nan
        compute_position_error(bad, np.zeros((5, 3)))


# =========================================================================
# 3. Collision Event Extraction & Debouncing
# =========================================================================

def test_collision_detection_known_answer_and_velocity_threshold():
    """Verify collision starts on no-contact -> contact with velocity >= 0.05."""
    t_total = 20
    # Distances: high -> low (contact at frame 8) -> high
    dists = np.full(t_total, 0.1)
    dists[8:12] = 0.002  # in contact (<= 0.004)

    # Case A: velocity >= 0.05 m/s at frame 8 -> triggers event
    vels_high = np.zeros(t_total)
    vels_high[8] = 0.12

    events_high = detect_collision_events(dists, vels_high, pair_id=(1, 2))
    assert len(events_high) == 1
    assert events_high[0].start_frame == 8
    assert events_high[0].end_frame == 11
    assert events_high[0].max_velocity == pytest.approx(0.12)
    assert events_high[0].debounce_count == 0

    # Broken control (sub-threshold): velocity < 0.05 m/s -> NO collision event
    vels_low = np.zeros(t_total)
    vels_low[8] = 0.03  # < 0.05
    events_low = detect_collision_events(dists, vels_low, pair_id=(1, 2))
    assert len(events_low) == 0


def test_collision_debouncing_micro_bounce_vs_true_separation():
    """Verify micro-bounce within <= 3 frames is debounced into 1 event, while > 3 frames forms 2 events."""
    t_total = 30
    # Base distances: no contact
    dists_debounced = np.full(t_total, 0.05)

    # Initial impact at frame 5-6
    dists_debounced[5:7] = 0.001

    # Micro-separation for exactly 2 frames: frames 7, 8 are no-contact (<= 3 frames debounce window)
    # Re-contact at frames 9, 10
    dists_debounced[9:11] = 0.001

    vels = np.zeros(t_total)
    vels[5] = 0.20
    vels[9] = 0.15  # re-contact speed

    # Test with debounce_frames=3 -> MUST BE 1 MERGED EVENT
    events_debounced = detect_collision_events(
        dists_debounced, vels, debounce_frames=3, pair_id=(0, 1)
    )
    assert len(events_debounced) == 1
    assert events_debounced[0].start_frame == 5
    assert events_debounced[0].end_frame == 10
    assert events_debounced[0].debounce_count == 1
    assert events_debounced[0].max_velocity == pytest.approx(0.20)

    # Broken control: Separation lasts 4 frames (> 3 frames debounce window)
    dists_separated = np.full(t_total, 0.05)
    dists_separated[5:7] = 0.001
    # Frames 7, 8, 9, 10 no contact (4 frames separation > 3)
    dists_separated[11:13] = 0.001
    vels_separated = np.zeros(t_total)
    vels_separated[5] = 0.20
    vels_separated[11] = 0.15

    events_separated = detect_collision_events(
        dists_separated, vels_separated, debounce_frames=3, pair_id=(0, 1)
    )
    # MUST BE 2 DISTINCT EVENTS
    assert len(events_separated) == 2
    assert events_separated[0].start_frame == 5
    assert events_separated[0].end_frame == 6
    assert events_separated[1].start_frame == 11
    assert events_separated[1].end_frame == 12


def test_collision_debouncing_exact_boundary():
    """Parametric test on separation frame counts: 1, 2, 3 frames merged; 4 frames new event."""
    for sep_frames in [1, 2, 3, 4]:
        t_total = 20
        dists = np.full(t_total, 0.1)
        vels = np.zeros(t_total)

        # Contact 1: frames 2-3
        dists[2:4] = 0.001
        vels[2] = 0.1

        # Separation from frame 4 to 3 + sep_frames
        # Contact 2 starts at frame 4 + sep_frames
        recontact_start = 4 + sep_frames
        recontact_end = recontact_start + 2
        dists[recontact_start:recontact_end] = 0.001
        vels[recontact_start] = 0.1

        events = detect_collision_events(dists, vels, debounce_frames=3)
        if sep_frames <= 3:
            assert len(events) == 1, f"Failed at sep_frames={sep_frames}, expected 1 merged event"
            assert events[0].debounce_count == 1
            assert events[0].end_frame == recontact_end - 1
        else:
            assert len(events) == 2, f"Failed at sep_frames={sep_frames}, expected 2 distinct events"
            assert events[0].start_frame == 2
            assert events[1].start_frame == recontact_start


# =========================================================================
# 4. Collision F1 & Match Tolerance
# =========================================================================

def test_collision_f1_known_answer_and_match_tolerance():
    """Verify precision, recall, F1 and match tolerance (+/- 1 frame)."""
    # Ground truth event at frame 10
    true_events = [
        CollisionEvent(pair_id=(0, 1), start_frame=10, end_frame=12, max_velocity=0.1)
    ]

    # 1. Exact match at frame 10
    pred_exact = [
        CollisionEvent(pair_id=(0, 1), start_frame=10, end_frame=12, max_velocity=0.1)
    ]
    res_exact = compute_collision_f1(pred_exact, true_events, match_tolerance_frames=1)
    assert res_exact["precision"] == 1.0
    assert res_exact["recall"] == 1.0
    assert res_exact["f1"] == 1.0
    assert res_exact["true_positives"] == 1

    # 2. Shifted by +1 frame (frame 11) -> within tolerance (+/- 1 frame) -> Still F1 = 1.0
    pred_shift1 = [
        CollisionEvent(pair_id=(0, 1), start_frame=11, end_frame=13, max_velocity=0.1)
    ]
    res_shift1 = compute_collision_f1(pred_shift1, true_events, match_tolerance_frames=1)
    assert res_shift1["precision"] == 1.0
    assert res_shift1["recall"] == 1.0
    assert res_shift1["f1"] == 1.0

    # 3. Order-independent pair IDs: (1, 0) matches (0, 1)
    pred_reversed = [
        CollisionEvent(pair_id=(1, 0), start_frame=10, end_frame=12, max_velocity=0.1)
    ]
    res_rev = compute_collision_f1(pred_reversed, true_events, match_tolerance_frames=1)
    assert res_rev["f1"] == 1.0

    # 4. Broken control: shifted by +2 frames (frame 12) -> outside tolerance -> F1 = 0.0
    pred_shift2 = [
        CollisionEvent(pair_id=(0, 1), start_frame=12, end_frame=14, max_velocity=0.1)
    ]
    res_shift2 = compute_collision_f1(pred_shift2, true_events, match_tolerance_frames=1)
    assert res_shift2["precision"] == 0.0
    assert res_shift2["recall"] == 0.0
    assert res_shift2["f1"] == 0.0
    assert res_shift2["true_positives"] == 0
    assert res_shift2["false_positives"] == 1
    assert res_shift2["false_negatives"] == 1

    # 5. Broken control: false alarms drop precision
    pred_with_fa = [
        CollisionEvent(pair_id=(0, 1), start_frame=10, end_frame=12, max_velocity=0.1),
        CollisionEvent(pair_id=(0, 1), start_frame=30, end_frame=32, max_velocity=0.1),  # False alarm
    ]
    res_fa = compute_collision_f1(pred_with_fa, true_events, match_tolerance_frames=1)
    assert res_fa["recall"] == 1.0
    assert res_fa["precision"] == 0.5
    assert res_fa["f1"] == pytest.approx(2.0 * 0.5 * 1.0 / 1.5)  # 2/3 ≈ 0.6667
    assert res_fa["f1"] < res_exact["f1"]


def test_collision_f1_empty_cases():
    """Verify edge cases when no events occur."""
    # Both empty -> 1.0
    res_empty = compute_collision_f1([], [])
    assert res_empty["precision"] == 1.0
    assert res_empty["recall"] == 1.0
    assert res_empty["f1"] == 1.0

    # True empty, pred has events -> precision 0.0
    ev = CollisionEvent(pair_id=(0, 1), start_frame=5, end_frame=6, max_velocity=0.1)
    res_pred_only = compute_collision_f1([ev], [])
    assert res_pred_only["precision"] == 0.0
    assert res_pred_only["recall"] == 0.0
    assert res_pred_only["f1"] == 0.0

    # Pred empty, true has events -> recall 0.0
    res_true_only = compute_collision_f1([], [ev])
    assert res_true_only["precision"] == 0.0
    assert res_true_only["recall"] == 0.0
    assert res_true_only["f1"] == 0.0


# =========================================================================
# 5. Ballistic Energy Drift
# =========================================================================

def test_ballistic_energy_drift_analytical_free_fall():
    """Analytical free fall has zero theoretical energy drift."""
    # Analytical free fall under g=9.81
    dt = 1.0 / 60.0  # 60 fps
    t_steps = 30
    t = np.arange(t_steps) * dt

    z0 = 5.0
    v0 = 2.0  # initial upward velocity
    # z(t) = z0 + v0*t - 0.5*g*t^2
    z = z0 + v0 * t - 0.5 * GRAVITY_ACCEL * t**2
    # vz(t) = v0 - g*t
    vz = v0 - GRAVITY_ACCEL * t

    pos = np.zeros((t_steps, 3))
    pos[:, 2] = z
    vel = np.zeros((t_steps, 3))
    vel[:, 2] = vz

    # Entire sequence is contact-free (ballistic length = 30 >= 5)
    res = compute_ballistic_energy_drift(pos, vel, min_segment_frames=5)
    assert res["segments_count"] == 1
    # Conservation of mechanical energy means drift must be ~0
    assert res["max_drift"] == pytest.approx(0.0, abs=1e-12)
    assert res["mean_drift"] == pytest.approx(0.0, abs=1e-12)


def test_ballistic_segment_filtering_and_broken_control():
    """Verify segments < 5 frames are excluded, and artificially decaying energy increases drift."""
    t_steps = 20
    pos = np.ones((t_steps, 3))
    vel = np.ones((t_steps, 3))

    # Boundary test: exactly 4 frames (< 5) vs exactly 5 frames (>= 5)
    contact_4 = np.ones(t_steps, dtype=bool)
    contact_4[2:6] = False  # frames 2, 3, 4, 5 -> 4 frames
    res_4 = compute_ballistic_energy_drift(pos, vel, in_contact=contact_4, min_segment_frames=5)
    assert res_4["segments_count"] == 0

    contact_5 = np.ones(t_steps, dtype=bool)
    contact_5[2:7] = False  # frames 2, 3, 4, 5, 6 -> 5 frames
    res_5 = compute_ballistic_energy_drift(pos, vel, in_contact=contact_5, min_segment_frames=5)
    assert res_5["segments_count"] == 1
    assert res_5["max_drift"] == pytest.approx(0.0)

    # Contact mask with 6 consecutive frames of free flight (frames 2 to 7) >= 5
    contact_valid = np.ones(t_steps, dtype=bool)
    contact_valid[2:8] = False  # 6 frames free flight >= 5

    # Constant energy -> drift = 0
    res_valid = compute_ballistic_energy_drift(pos, vel, in_contact=contact_valid, min_segment_frames=5)
    assert res_valid["segments_count"] == 1
    assert res_valid["max_drift"] == pytest.approx(0.0)

    # Broken control: Introduce energy dissipation (decaying velocity within segment)
    vel_decay = vel.copy()
    for i, t_idx in enumerate(range(2, 8)):
        vel_decay[t_idx] *= (1.0 - 0.1 * i)  # progressively drops velocity across segment
    res_decay = compute_ballistic_energy_drift(pos, vel_decay, in_contact=contact_valid, min_segment_frames=5)
    assert res_decay["segments_count"] == 1
    assert res_decay["max_drift"] > 0.0
    assert res_decay["max_drift"] > res_valid["max_drift"]


def test_paired_bootstrap_full_resamples_performance_and_absolute_mode():
    """Verify performance and accuracy of full 10,000 resamples paired bootstrap in both modes."""
    n_seeds = 3
    n_episodes = 200  # full dev/final size

    rng = np.random.default_rng(777)
    base_scores = rng.uniform(0.5, 1.5, size=(n_seeds, n_episodes))
    # Candidate arm has constant -0.05 shift
    candidate_scores = base_scores - 0.05

    # Absolute mode with full 10,000 resamples
    res_abs = paired_bootstrap_ci(
        base_scores, candidate_scores, n_resamples=10000, seed=42, mode="absolute"
    )
    assert res_abs["n_resamples"] == 10000
    assert res_abs["point_estimate"] == pytest.approx(-0.05)
    assert res_abs["ci_lower"] == pytest.approx(-0.05)
    assert res_abs["ci_upper"] == pytest.approx(-0.05)
    assert res_abs["contains_zero"] is False

    # Relative mode
    res_rel = paired_bootstrap_ci(
        base_scores, candidate_scores, n_resamples=10000, seed=42, mode="relative"
    )
    assert res_rel["n_resamples"] == 10000
    assert res_rel["point_estimate"] < 0.0
    assert res_rel["contains_zero"] is False


# =========================================================================
# 6. Latency Summary
# =========================================================================

def test_summarize_inference_latency():
    """Verify latency summary statistics."""
    latencies = np.array([10.0, 12.0, 15.0, 18.0, 20.0, 25.0, 30.0, 50.0, 100.0, 120.0])
    res = summarize_inference_latency(latencies)
    assert res["count"] == 10
    assert res["min_ms"] == 10.0
    assert res["max_ms"] == 120.0
    assert res["median_ms"] == pytest.approx(np.median(latencies))
    assert res["p95_ms"] == pytest.approx(np.percentile(latencies, 95.0))
    assert res["mean_ms"] == pytest.approx(np.mean(latencies))

    with pytest.raises(ValueError, match="finite"):
        summarize_inference_latency([10.0, np.nan, 20.0])


# =========================================================================
# 7. Seed Aggregation & Paired Bootstrap
# =========================================================================

def test_aggregate_seeds_macro():
    """Verify macro-average across seeds."""
    # 3 seeds, 4 episodes each
    seed_data = np.array(
        [
            [1.0, 2.0, 3.0, 4.0],  # mean = 2.5
            [2.0, 3.0, 4.0, 5.0],  # mean = 3.5
            [3.0, 4.0, 5.0, 6.0],  # mean = 4.5
        ]
    )
    res = aggregate_seeds_macro(seed_data)
    assert res["num_seeds"] == 3
    assert res["num_episodes"] == 4
    assert res["seed_means"] == [2.5, 3.5, 4.5]
    assert res["macro_mean"] == pytest.approx(3.5)


def test_paired_bootstrap_ci_coverage_and_broken_control():
    """Verify paired bootstrap CI on known treatment effects and reproducibility."""
    n_seeds = 3
    n_episodes = 50

    # Arm A baseline scores
    rng = np.random.default_rng(123)
    base_scores = rng.uniform(1.0, 2.0, size=(n_seeds, n_episodes))

    # 1. Identical arms -> relative difference exactly 0, CI contains 0
    res_identical = paired_bootstrap_ci(base_scores, base_scores, n_resamples=1000, seed=42)
    assert res_identical["point_estimate"] == pytest.approx(0.0)
    assert res_identical["contains_zero"] is True
    assert res_identical["ci_lower"] <= 0.0 <= res_identical["ci_upper"]

    # 2. Arm B is exactly 15% better (lower error) on every episode: scores * 0.85
    arm_b_better = base_scores * 0.85
    res_better = paired_bootstrap_ci(base_scores, arm_b_better, n_resamples=1000, seed=42)
    assert res_better["point_estimate"] == pytest.approx(-0.15)
    assert res_better["ci_lower"] == pytest.approx(-0.15)
    assert res_better["ci_upper"] == pytest.approx(-0.15)
    assert res_better["contains_zero"] is False

    # 3. Broken control: Arm B is strictly worse (higher error): scores * 1.20
    arm_b_worse = base_scores * 1.20
    res_worse = paired_bootstrap_ci(base_scores, arm_b_worse, n_resamples=1000, seed=42)
    assert res_worse["point_estimate"] == pytest.approx(0.20)
    assert res_worse["point_estimate"] > res_better["point_estimate"]

    # 4. Deterministic reproducibility: running with seed=42 yields identical values
    res_repeat = paired_bootstrap_ci(base_scores, arm_b_better, n_resamples=1000, seed=42)
    assert res_repeat["ci_lower"] == res_better["ci_lower"]
    assert res_repeat["ci_upper"] == res_better["ci_upper"]


# =========================================================================
# 8. Failure Subset Stratification
# =========================================================================

def test_stratify_failure_subset():
    """Verify stratification of metrics on failure subset."""
    metrics_arr = np.array([0.1, 0.2, 0.5, 0.9])
    is_fail = np.array([False, False, True, True])

    res = stratify_failure_subset(metrics_arr, is_fail)
    assert res["total_episodes"] == 4
    assert res["failure_episodes_count"] == 2
    assert res["non_failure_episodes_count"] == 2
    assert res["overall_mean"] == pytest.approx((0.1 + 0.2 + 0.5 + 0.9) / 4.0)
    assert res["failure_subset_mean"] == pytest.approx((0.5 + 0.9) / 2.0)
    assert res["non_failure_subset_mean"] == pytest.approx((0.1 + 0.2) / 2.0)
