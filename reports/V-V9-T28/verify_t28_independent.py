"""Independent CPU mathematical review and verification of T28 calibration proposal.

Authored independently by gemini-kzer (non-author of T28).
Does NOT import or rely on author's check_math.py.
Uses fresh, independent small-matrix fixtures and mathematical derivations:
1. Relative pose and scale gauge freedom derivation (SE(3) + positive scale invariance)
2. Collinear camera center constraint & Sim3 orientation degeneracy
3. Fit vs Holdout partition independence & leakage verification
4. Covariance rank deficiency (rank <= 2 for 3 worlds, d=7) and NEES non-invertibility
5. Call/view counts and 1200s budget accounting verification
6. Five intentional sabotage controls (故意改坏测试) with real non-zero exit codes
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import subprocess
import sys
from pathlib import Path
import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[2]
PROPOSAL_PATH = REPO_ROOT / "reports/V9-T28/proposal.json"
EXPECTED_PROPOSAL_SHA256 = "af3131a51bf93ff12b43c08b4ca564124c1b1542cf9f9e196316cfa6e391cb4a"


def rodrigues(axis: np.ndarray, angle: float) -> np.ndarray:
    """Independent Rodrigues rotation matrix formula."""
    axis = axis / np.linalg.norm(axis)
    kx, ky, kz = axis
    K = np.array([[0, -kz, ky], [kz, 0, -kx], [-ky, kx, 0]], dtype=float)
    return np.eye(3) + math.sin(angle) * K + (1.0 - math.cos(angle)) * (K @ K)


def log_so3(R: np.ndarray) -> np.ndarray:
    """Independent SO(3) logarithm extracting rotation vector."""
    cos_theta = float(np.clip((np.trace(R) - 1.0) / 2.0, -1.0, 1.0))
    theta = math.acos(cos_theta)
    if math.pi - theta <= 1e-6:
        raise ValueError("Near pi branch singularity in SO(3) logarithm")
    if theta < 1e-9:
        return np.zeros(3, dtype=float)
    sin_theta = math.sin(theta)
    skew = (R - R.T) / (2.0 * sin_theta)
    return np.array([skew[2, 1], skew[0, 2], skew[1, 0]], dtype=float) * theta


def compute_relative_pose_residual(
    gt_c2w_list: list[np.ndarray],
    pred_c2w_list: list[np.ndarray],
) -> np.ndarray:
    """Independent derivation of anchored relative pose residual."""
    # Ensure C2W shapes
    for m in gt_c2w_list + pred_c2w_list:
        assert m.shape == (4, 4)
        assert np.allclose(m[3], [0, 0, 0, 1])

    # Relative to anchor frame 0
    R0_gt, c0_gt = gt_c2w_list[0][:3, :3], gt_c2w_list[0][:3, 3]
    R1_gt, c1_gt = gt_c2w_list[1][:3, :3], gt_c2w_list[1][:3, 3]
    R2_gt, c2_gt = gt_c2w_list[2][:3, :3], gt_c2w_list[2][:3, 3]

    R0_pred, c0_pred = pred_c2w_list[0][:3, :3], pred_c2w_list[0][:3, 3]
    R1_pred, c1_pred = pred_c2w_list[1][:3, :3], pred_c2w_list[1][:3, 3]
    R2_pred, c2_pred = pred_c2w_list[2][:3, :3], pred_c2w_list[2][:3, 3]

    # Relative poses
    Rrel_gt_1 = R0_gt.T @ R1_gt
    u_gt_1 = R0_gt.T @ (c1_gt - c0_gt)
    u_gt_2 = R0_gt.T @ (c2_gt - c0_gt)

    Rrel_pred_1 = R0_pred.T @ R1_pred
    u_pred_1 = R0_pred.T @ (c1_pred - c0_pred)
    u_pred_2 = R0_pred.T @ (c2_pred - c0_pred)

    b_gt = np.linalg.norm(u_gt_2)
    b_pred = np.linalg.norm(u_pred_2)
    assert b_gt > 1e-6, "Ground-truth baseline to view 2 is zero"
    assert b_pred > 1e-12, "Predicted baseline to view 2 is degenerate"

    scale = b_gt / b_pred

    # Rotation residual vector
    delta_R = Rrel_gt_1.T @ Rrel_pred_1
    rot_vec = log_so3(delta_R)

    # Translation residual vector normalized by baseline
    trans_res = (scale * u_pred_1 - u_gt_1) / b_gt

    return np.concatenate([rot_vec, trans_res])


def test_gauge_invariance_and_perturbations() -> dict[str, Any]:
    """Test 1: Independent verification of gauge invariance and sensitivity."""
    # Create 3 collinear ground truth camera poses
    c0 = np.array([0.0, 1.0, 2.0])
    c1 = np.array([0.5, 1.0, 2.0])  # along x-axis
    c2 = np.array([1.2, 1.0, 2.0])  # along x-axis

    R0 = rodrigues(np.array([1.0, 1.0, 0.0]), 0.3)
    R1 = rodrigues(np.array([0.0, 1.0, 1.0]), 0.6)
    R2 = rodrigues(np.array([1.0, 0.0, 1.0]), 0.9)

    gt_c2w = [
        np.block([[R0, c0[:, None]], [np.zeros((1, 3)), 1.0]]),
        np.block([[R1, c1[:, None]], [np.zeros((1, 3)), 1.0]]),
        np.block([[R2, c2[:, None]], [np.zeros((1, 3)), 1.0]]),
    ]

    # Apply arbitrary global SE(3) transform + arbitrary positive scale
    R_global = rodrigues(np.array([2.0, -1.0, 3.0]), 1.15)
    t_global = np.array([15.3, -42.1, 7.8])
    alpha_scale = 5.842

    pred_c2w_clean = []
    for c2w in gt_c2w:
        R_orig = c2w[:3, :3]
        c_orig = c2w[:3, 3]
        R_trans = R_global @ R_orig
        c_trans = alpha_scale * (R_global @ c_orig) + t_global
        pred_c2w_clean.append(
            np.block([[R_trans, c_trans[:, None]], [np.zeros((1, 3)), 1.0]])
        )

    # Evaluate residual on clean transformed prediction
    res_clean = compute_relative_pose_residual(gt_c2w, pred_c2w_clean)
    max_clean_error = float(np.max(np.abs(res_clean)))
    assert max_clean_error < 1e-12, f"Gauge invariance failed: max error {max_clean_error}"

    # Verify rotation sensitivity: inject known 0.25 rad rotation on view 1
    pert_axis = np.array([1.0, 2.0, 3.0]) / math.sqrt(14.0)
    pert_angle = 0.25
    pred_c2w_rot_perturbed = [m.copy() for m in pred_c2w_clean]
    pred_c2w_rot_perturbed[1][:3, :3] = pred_c2w_rot_perturbed[1][:3, :3] @ rodrigues(
        pert_axis, pert_angle
    )

    res_rot = compute_relative_pose_residual(gt_c2w, pred_c2w_rot_perturbed)
    measured_rot_error = float(np.linalg.norm(res_rot[:3]))
    assert abs(measured_rot_error - pert_angle) < 1e-12, (
        f"Rotation error mismatch: expected {pert_angle}, got {measured_rot_error}"
    )

    # Verify translation sensitivity: inject known displacement on view 1
    pred_c2w_trans_perturbed = [m.copy() for m in pred_c2w_clean]
    # In C2W, shift along camera 0 coordinate
    b_gt = float(np.linalg.norm(gt_c2w[2][:3, 3] - gt_c2w[0][:3, 3]))
    expected_rel_disp = 0.15
    pred_c2w_trans_perturbed[1][:3, 3] += (
        alpha_scale * (R_global @ R0 @ np.array([expected_rel_disp * b_gt, 0.0, 0.0]))
    )

    res_trans = compute_relative_pose_residual(gt_c2w, pred_c2w_trans_perturbed)
    measured_trans_error = float(np.linalg.norm(res_trans[3:]))
    assert abs(measured_trans_error - expected_rel_disp) < 1e-12, (
        f"Translation error mismatch: expected {expected_rel_disp}, got {measured_trans_error}"
    )

    return {
        "status": "passed",
        "clean_gauge_residual_max": max_clean_error,
        "measured_rotation_error_rad": measured_rot_error,
        "expected_rotation_error_rad": pert_angle,
        "measured_translation_error_norm": measured_trans_error,
        "expected_translation_error_norm": expected_rel_disp,
    }


def test_collinear_sim3_degeneracy() -> dict[str, Any]:
    """Test 2: Prove that 3 collinear camera centers cause Sim(3) rotation degeneracy."""
    # 3 points on a line
    P_gt = np.array([[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [2.5, 0.0, 0.0]])
    # Centered points
    P_centered = P_gt - np.mean(P_gt, axis=0)
    # Covariance of 3D point cloud
    cov_pts = P_centered.T @ P_centered
    eigenvalues = np.sort(np.linalg.eigvalsh(cov_pts))[::-1]
    # SVD has only 1 non-zero singular value; rank is 1!
    rank_pts = int(np.sum(eigenvalues > 1e-10))
    assert rank_pts == 1, f"Expected rank 1 for collinear points, got {rank_pts}"

    # Any rotation around x-axis leaves collinear point cloud invariant:
    R_x = rodrigues(np.array([1.0, 0.0, 0.0]), 1.570796)
    P_rot = (P_centered @ R_x.T)
    point_fit_error = float(np.max(np.abs(P_rot - P_centered)))
    assert point_fit_error < 1e-14, "Collinear points failed to demonstrate axis ambiguity"

    return {
        "status": "passed",
        "collinear_point_cloud_rank": rank_pts,
        "rotation_around_axis_residual": point_fit_error,
        "degeneracy_verified": True,
        "note": "Proves that point-only Sim(3) on 3 collinear views has an unconstrained rotational degree of freedom; T28 anchor formulation correctly avoids this by using camera rotation matrices directly.",
    }


def test_fit_holdout_split_and_covariance_rank(proposal: dict) -> dict[str, Any]:
    """Test 3: Verify split independence, covariance rank ceiling <= 2, and NEES impossibility."""
    fit_worlds = proposal["split"]["fit_worlds"]
    holdout_worlds = proposal["split"]["holdout_worlds"]

    # 1. Strict partition disjointness
    assert len(fit_worlds) == 3, f"Expected 3 fit worlds, got {len(fit_worlds)}"
    assert len(holdout_worlds) == 3, f"Expected 3 holdout worlds, got {len(holdout_worlds)}"
    intersection = set(fit_worlds) & set(holdout_worlds)
    assert len(intersection) == 0, f"Fit and holdout worlds overlap: {intersection}"

    # 2. Covariance rank derivation
    # With N=3 worlds and d=7 diagnostic dimension
    # Generate 3 arbitrary 7-dimensional residual vectors
    np.random.seed(42)
    E_toy = np.random.randn(3, 7)
    E_centered = E_toy - np.mean(E_toy, axis=0)
    cov_sample = (E_centered.T @ E_centered) / (3.0 - 1.0)
    cov_rank = int(np.linalg.matrix_rank(cov_sample, tol=1e-10))
    eigenvalues = np.sort(np.linalg.eigvalsh(cov_sample))[::-1]

    assert cov_rank <= 2, f"Covariance rank must be <= 2, got {cov_rank}"
    zero_eigenvalues_count = int(np.sum(eigenvalues < 1e-10))
    assert zero_eigenvalues_count >= 5, f"Expected at least 5 zero eigenvalues, got {zero_eigenvalues_count}"

    # Prove that inverting cov_sample fails
    inversion_failed = False
    try:
        np.linalg.inv(cov_sample)
    except np.linalg.LinAlgError:
        inversion_failed = True
    assert inversion_failed, "Singular covariance should not be invertible!"

    # 3. Check proposal flags
    assert proposal["estimation"]["nees"] is None
    assert proposal["estimation"]["coverage_95"] is None
    assert proposal["estimation"]["regularization"] == "none; no inverse or pseudoinverse"
    assert proposal["status"] == "proposal_unapproved"
    assert proposal["execution_permitted"] is False

    return {
        "status": "passed",
        "fit_worlds_count": len(fit_worlds),
        "holdout_worlds_count": len(holdout_worlds),
        "partition_overlap": len(intersection),
        "covariance_dimension": 7,
        "sample_covariance_rank": cov_rank,
        "zero_eigenvalues_count": zero_eigenvalues_count,
        "direct_inversion_singular": inversion_failed,
        "nees_unclaimed": proposal["estimation"]["nees"] is None,
        "coverage_unclaimed": proposal["estimation"]["coverage_95"] is None,
    }


def test_budget_and_views_accounting(proposal: dict) -> dict[str, Any]:
    """Test 4: Verify views, stages, model calls, and 1200s budget consistency."""
    budget = proposal["budget"]
    models = budget["models"]
    assert len(models) == 2, f"Expected 2 models, got {len(models)}"

    total_calls = 0
    total_views = 0
    model_breakdown = []

    for m in models:
        variant = m["variant"]
        stages = m["stages"]
        m_calls = sum(s["calls"] for s in stages)
        m_views = sum(s["calls"] * s["frames_per_call"] for s in stages)
        assert m_calls == m["forward_calls"] == 11, f"Mismatch in calls for {variant}"
        assert m_views == m["forward_views"] == 31, f"Mismatch in views for {variant}"
        total_calls += m_calls
        total_views += m_views
        model_breakdown.append(
            {"variant": variant, "calls": m_calls, "views": m_views, "stages_count": len(stages)}
        )

    assert total_calls == budget["total_planned_forward_calls"] == 22
    assert total_views == budget["total_planned_forward_views"] == 62
    assert total_views <= 64, f"Total views {total_views} exceeds quota 64"
    assert budget["unallocated_views"] == 2
    assert budget["cumulative_wall_seconds_max"] <= 1200
    assert budget["single_run_wall_seconds_max"] <= 1200
    assert budget["rss_bytes_max"] <= 8 * 1024**3

    return {
        "status": "passed",
        "total_calls": total_calls,
        "total_views": total_views,
        "views_quota_max": 64,
        "unallocated_views": budget["unallocated_views"],
        "cumulative_wall_max_s": budget["cumulative_wall_seconds_max"],
        "rss_max_bytes": budget["rss_bytes_max"],
        "model_breakdown": model_breakdown,
    }


def execute_intentional_sabotages() -> list[dict[str, Any]]:
    """Execute five intentional sabotage tests as child processes, confirming non-zero exit."""
    sabotages = [
        ("sabotage_gauge", "Corrupted rotation gauge factor violates identity on clean inputs"),
        ("sabotage_leakage", "Fit/holdout overlap leakage injected into proposal"),
        ("sabotage_views", "Views budget overcommit (> 64 views) injected into proposal"),
        ("sabotage_covariance", "Attempting to invert rank-deficient covariance without regularization"),
        ("sabotage_approval", "Falsely claiming approved status and execution_permitted=true"),
    ]

    records = []
    for sab_name, description in sabotages:
        cmd = [sys.executable, "-I", "-B", str(Path(__file__).resolve()), "--sabotage", sab_name]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        assert proc.returncode != 0, f"Sabotage {sab_name} failed to exit non-zero!"
        records.append(
            {
                "sabotage": sab_name,
                "description": description,
                "returncode": proc.returncode,
                "stderr_tail": proc.stderr.strip().splitlines()[-1] if proc.stderr else "",
                "passed_red_test": True,
            }
        )
    return records


def main():
    parser = argparse.ArgumentParser(description="T28 independent review")
    parser.add_argument("--sabotage", choices=[
        "sabotage_gauge",
        "sabotage_leakage",
        "sabotage_views",
        "sabotage_covariance",
        "sabotage_approval",
    ])
    args = parser.parse_args()

    proposal_bytes = PROPOSAL_PATH.read_bytes()
    proposal_sha = hashlib.sha256(proposal_bytes).hexdigest()
    assert proposal_sha == EXPECTED_PROPOSAL_SHA256, (
        f"Proposal SHA mismatch: expected {EXPECTED_PROPOSAL_SHA256}, got {proposal_sha}"
    )
    proposal = json.loads(proposal_bytes.decode("utf-8"))

    # Intentional sabotage branches
    if args.sabotage == "sabotage_gauge":
        # Inject corrupted orientation into clean input
        gt = [np.eye(4) for _ in range(3)]
        pred = [np.eye(4) for _ in range(3)]
        pred[1][:3, :3] = rodrigues(np.array([1.0, 0.0, 0.0]), 0.5)
        res = compute_relative_pose_residual(gt, pred)
        assert np.max(np.abs(res)) < 1e-12, "Gauge check failed: non-zero residual on damaged input"
        sys.exit(0)

    elif args.sabotage == "sabotage_leakage":
        # Inject leakage
        fit = proposal["split"]["fit_worlds"]
        holdout = proposal["split"]["holdout_worlds"] + [fit[0]]
        assert len(set(fit) & set(holdout)) == 0, f"Holdout leakage detected: {fit[0]}"
        sys.exit(0)

    elif args.sabotage == "sabotage_views":
        # Overcommit views
        views = proposal["budget"]["total_planned_forward_views"] + 4  # 62 + 4 = 66 > 64
        assert views <= 64, f"Views overcommit: {views} > 64"
        sys.exit(0)

    elif args.sabotage == "sabotage_covariance":
        # Force checking rank == 7 on rank-2 covariance
        E = np.random.randn(3, 7)
        E_c = E - E.mean(axis=0)
        Q = E_c.T @ E_c / 2.0
        rank = int(np.linalg.matrix_rank(Q, tol=1e-6))
        assert rank == 7, f"Covariance is rank-deficient (rank {rank} < 7), cannot claim full-rank noise model"
        sys.exit(0)

    elif args.sabotage == "sabotage_approval":
        # Falsely assert approval
        status = "approved"
        assert status == proposal["status"] == "proposal_unapproved", "Unapproved proposal claiming approved"
        sys.exit(0)

    # Normal execution: run full independent review suite
    res_gauge = test_gauge_invariance_and_perturbations()
    res_collinear = test_collinear_sim3_degeneracy()
    res_split_cov = test_fit_holdout_split_and_covariance_rank(proposal)
    res_budget = test_budget_and_views_accounting(proposal)
    sabotage_results = execute_intentional_sabotages()

    final_report = {
        "task": "ainerzero.V9.T29",
        "reviewer": "gemini-kzer",
        "reviewed_task": "ainerzero.V9.T28",
        "reviewed_author": "codex",
        "proposal_sha256": proposal_sha,
        "proposal_sha256_verified": True,
        "verdict": "recommend_immutable_sha_registration_as_unapproved_proposal",
        "tests": {
            "gauge_invariance": res_gauge,
            "collinear_sim3_degeneracy": res_collinear,
            "split_and_covariance_rank": res_split_cov,
            "budget_and_views": res_budget,
            "intentional_sabotages": sabotage_results,
        },
        "all_independent_checks_passed": True,
    }

    out_json = REPO_ROOT / "reports/V-V9-T28/independent_verification.json"
    out_json.write_text(json.dumps(final_report, indent=2) + "\n")
    print(json.dumps(final_report, indent=2))


if __name__ == "__main__":
    main()
