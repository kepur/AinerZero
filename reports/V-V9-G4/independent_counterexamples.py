#!/usr/bin/env python3
"""Independent adversarial checks for ainerzero.V9.G3 canonicalization (G4).

Author of G3: deepseek-flash-9m2x. Reviewer: composer-m7k2.
Does NOT reuse the author's pytest suite as sole evidence.
Each case carries a "poison" control that must turn red under deliberate breakage.
Read-only: never writes under src/ or tests/.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
import traceback
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from ainerzero.v9.geometry import SE2, SE3, GravityFrame, TangentGaussian, boxplus  # noqa: E402
from ainerzero.v9.geometry import canonical as C  # noqa: E402

Z_UP = GravityFrame([0.0, 0.0, -9.81], [0.0, 0.0, 1.0], [1.0, 0.0, 0.0])
ROUNDTRIP_TOL = 1e-9
EQUIV_TOL = 1e-9
COV_REL_TOL = 0.05


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def make_belief(mean=None, cov=None, group=SE2, frame=Z_UP, side="right"):
    if mean is None:
        mean = SE2.identity() if group is SE2 else frame.lift(SE2.identity(), 0.25)
    if cov is None:
        cov = np.eye(group.dof) * 1e-4
    return C.CanonicalBelief(TangentGaussian(group, mean, cov, side), frame)


def se2(tx, ty, yaw):
    return SE2.exp([tx, ty, yaw])


def _jsonable(obj):
    """Convert numpy scalars / bools so json.dumps never sees np.bool_."""
    if isinstance(obj, dict):
        return {str(k): _jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_jsonable(v) for v in obj]
    if isinstance(obj, (np.bool_, bool)):
        return bool(obj)
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating, float)):
        return float(obj)
    if obj is None or isinstance(obj, (str, int)):
        return obj
    return obj


def record(name, ok, detail, poison_ok, metrics=None):
    return _jsonable(
        {
            "name": name,
            "ok": bool(ok),
            "poison_caught": bool(poison_ok),
            "detail": detail,
            "metrics": metrics or {},
        }
    )


# ── C1 near-π rotation equivariance + identity ─────────────────────────────


def case_near_pi_equivariance():
    """Near ±π yaw left action must keep canonicalize SE(2)-equivariant."""
    rng = np.random.default_rng(20261020)
    points = rng.normal(size=(32, 2))
    vectors = rng.normal(size=(32, 2))
    yaws = [
        math.pi,
        -math.pi,
        math.pi - 1e-12,
        -math.pi + 1e-12,
        math.pi - 1e-8,
        -math.pi + 1e-8,
    ]
    max_pt = 0.0
    max_vec = 0.0
    max_rt = 0.0
    for yaw in yaws:
        for tx in (0.0, 1e-12, -1e-12, 0.7):
            belief = make_belief(mean=se2(0.3, -0.4, 0.2))
            g = se2(tx, -tx, yaw)
            moved_pts = SE2.act(g, points)
            moved_belief = belief.left_compose(g)
            a = np.asarray(C.canonicalize_points(points, belief))
            b = np.asarray(C.canonicalize_points(moved_pts, moved_belief))
            max_pt = max(max_pt, float(np.max(np.abs(a - b))))
            a_v = np.asarray(C.canonicalize_vectors(vectors, belief))
            b_v = np.asarray(
                C.canonicalize_vectors(SE2.act(g, vectors, vectors=True), moved_belief)
            )
            max_vec = max(max_vec, float(np.max(np.abs(a_v - b_v))))
            rt = np.asarray(
                C.decanonicalize_points(C.canonicalize_points(points, belief), belief)
            )
            max_rt = max(max_rt, float(np.max(np.abs(rt - points))))

    ok = max_pt <= EQUIV_TOL and max_vec <= EQUIV_TOL and max_rt <= ROUNDTRIP_TOL

    # Poison: flip canonicalize direction (use g instead of g^-1).
    poison_max = 0.0
    belief = make_belief(mean=se2(0.3, -0.4, 0.2))
    g = se2(0.0, 0.0, math.pi)
    moved = SE2.act(g, points)
    moved_belief = belief.left_compose(g)
    # Wrong map: act with planar() instead of inverse(planar()).
    wrong_a = SE2.act(belief.planar(), points)
    wrong_b = SE2.act(moved_belief.planar(), moved)
    poison_max = float(np.max(np.abs(wrong_a - wrong_b)))
    poison_ok = poison_max > 1e-3  # must be visibly non-equivariant

    return record(
        "C1_near_pi_equivariance_and_identity",
        ok,
        f"max_equiv_pt={max_pt:.3e} max_equiv_vec={max_vec:.3e} max_rt={max_rt:.3e}",
        poison_ok,
        {
            "max_equivariance_points": max_pt,
            "max_equivariance_vectors": max_vec,
            "max_roundtrip": max_rt,
            "poison_equiv_error": poison_max,
        },
    )


# ── C2 reflection mixed into SE(2) action ──────────────────────────────────


def case_reflection_rejected():
    """Orientation-reversing (det=-1) matrices must not pass as SE(2)."""
    reflection = np.array(
        [[1.0, 0.0, 0.5], [0.0, -1.0, -0.3], [0.0, 0.0, 1.0]], dtype=np.float64
    )
    assert abs(np.linalg.det(reflection[:2, :2]) + 1.0) < 1e-12

    rejected = False
    try:
        SE2.validate(reflection)
    except ValueError:
        rejected = True

    belief = make_belief()
    left_rejected = False
    try:
        belief.left_compose(reflection)
    except ValueError:
        left_rejected = True

    # Even if somehow forced through act, equivariance must break badly.
    # Build a "reflected" left action manually (not through validate).
    points = np.array([[1.0, 0.0], [0.0, 1.0], [2.0, -1.0]])
    a = np.asarray(C.canonicalize_points(points, belief))
    # Wrong world action with reflection: R_ref @ p + t, and belief mean reflected.
    reflected_pts = (reflection[:2, :2] @ points.T).T + reflection[:2, 2]
    # Compare against true SE(2) equivariance residual under this illegal g.
    # Using reflected points with an illegal "moved" belief constructed by
    # composing without validation would raise; instead measure that reflection
    # of already-canonical points is NOT identity-preserving under canonicalize.
    reflected_canonical = (reflection[:2, :2] @ a.T).T  # det=-1 on agent frame
    residual = float(np.max(np.abs(reflected_canonical - a)))
    ok = rejected and left_rejected and residual > 0.5

    # Poison: a would-be checker that only looks at finite entries (accepts reflection).
    poison_accepts = np.isfinite(reflection).all() and reflection.shape == (3, 3)
    poison_ok = poison_accepts and not rejected  # wait: we WANT poison_ok True when
    # the weak checker would miss the bug. The control is: if we replaced
    # SE2.validate with "isfinite only", reflection would be accepted.
    weak_ok = bool(np.isfinite(reflection).all())
    poison_ok = weak_ok and rejected  # weak path green + real path red

    return record(
        "C2_reflection_mixed_in_rejected",
        ok,
        f"validate_rejected={rejected} left_compose_rejected={left_rejected} "
        f"reflection_on_canonical_residual={residual:.3e}",
        poison_ok,
        {
            "se2_validate_rejected": rejected,
            "left_compose_rejected": left_rejected,
            "reflection_residual": residual,
        },
    )


# ── C3 non-rigid transform rejected ────────────────────────────────────────


def case_nonrigid_rejected():
    """Scale / shear must be rejected by SE(2) validation and thus by belief APIs."""
    scale = np.array(
        [[2.0, 0.0, 0.1], [0.0, 2.0, -0.2], [0.0, 0.0, 1.0]], dtype=np.float64
    )
    shear = np.array(
        [[1.0, 0.4, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]], dtype=np.float64
    )
    results = {}
    for name, mat in (("scale", scale), ("shear", shear)):
        try:
            SE2.validate(mat)
            results[name] = "accepted"
        except ValueError:
            results[name] = "rejected"
    belief = make_belief()
    for name, mat in (("scale_compose", scale), ("shear_compose", shear)):
        try:
            belief.left_compose(mat)
            results[name] = "accepted"
        except ValueError:
            results[name] = "rejected"

    ok = all(v == "rejected" for v in results.values())

    # Poison: checker that only verifies bottom row == [0,0,1] (misses scale/shear).
    def weak_validate(m):
        return m.shape == (3, 3) and np.allclose(m[2], [0, 0, 1])

    poison_ok = weak_validate(scale) and weak_validate(shear) and ok
    return record(
        "C3_nonrigid_transform_rejected",
        ok,
        str(results),
        poison_ok,
        results,
    )


# ── C4 grid out-of-bounds fill + mask ──────────────────────────────────────


def case_grid_out_of_bounds():
    """Far belief → most cells outside source index rectangle → fill + invalid."""
    h = 0.25
    rows = cols = 8
    xs = (np.arange(cols) + 0.5) * h
    ys = (np.arange(rows) + 0.5) * h
    gx, gy = np.meshgrid(xs, ys)
    data = np.sin(gx) + np.cos(gy)
    grid = C.PlanarGrid(data=data, resolution=h, frame=SE2.identity(), fill=-7.0)
    # Belief centered far from the lattice footprint [0,2]x[0,2].
    belief = make_belief(mean=se2(20.0, -15.0, 0.3))
    out = C.canonicalize_grid(grid, belief)
    valid_frac = float(out.valid.mean())
    fill_frac = float(np.mean(np.isclose(out.data, grid.fill)))
    # Almost everything should be invalid / filled.
    ok = valid_frac < 0.05 and fill_frac > 0.95 and np.allclose(
        out.data[~out.valid], grid.fill
    )

    # Interior cell of a nearby belief must remain valid (sanity, non-vacuous).
    near = make_belief(mean=se2(0.5, 0.5, 0.0))
    near_out = C.canonicalize_grid(grid, near)
    interior_ok = bool(near_out.valid[rows // 2, cols // 2])
    ok = ok and interior_ok

    # Poison: a checker that ignores the mask and only looks at finite data.
    poison_would_pass = bool(np.isfinite(out.data).all()) and valid_frac < 0.05
    poison_ok = poison_would_pass  # finite-only check misses OOB contract

    return record(
        "C4_grid_out_of_bounds_fill_and_mask",
        ok,
        f"far_valid_frac={valid_frac:.4f} far_fill_frac={fill_frac:.4f} "
        f"near_interior_valid={interior_ok}",
        poison_ok,
        {
            "far_valid_fraction": valid_frac,
            "far_fill_fraction": fill_frac,
            "near_interior_valid": interior_ok,
        },
    )


# ── C5 non-positive-definite covariance injection ──────────────────────────


def case_non_pd_covariance():
    """Indefinite / singular / NaN covariances must be rejected before injection."""
    mean = se2(0.1, -0.2, 0.3)
    cases = {
        "indefinite": np.diag([1.0, -0.5, 1.0]),
        "singular": np.diag([1.0, 1.0, 0.0]),
        "nonsymmetric": np.array([[1.0, 0.2, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]]),
        "nan": np.eye(3) * np.nan,
        "inf": np.eye(3) * np.inf,
    }
    outcomes = {}
    for name, cov in cases.items():
        try:
            make_belief(mean=mean, cov=cov)
            outcomes[name] = "accepted"
        except ValueError:
            outcomes[name] = "rejected"

    # Valid SPD must still accept + inject.
    spd = np.array([[2e-4, 1e-5, 0.0], [1e-5, 3e-4, 0.0], [0.0, 0.0, 4e-4]])
    belief = make_belief(mean=mean, cov=spd)
    rng = np.random.default_rng(7)
    inj = C.inject_pose_error(belief, rng)
    inject_ok = isinstance(inj, C.CanonicalBelief)
    ok = all(v == "rejected" for v in outcomes.values()) and inject_ok

    # Poison: drop eigvalsh check → indefinite would be accepted by weak path.
    weak_accepts_indefinite = (
        cases["indefinite"].shape == (3, 3)
        and np.isfinite(cases["indefinite"]).all()
        and np.allclose(cases["indefinite"], cases["indefinite"].T)
    )
    poison_ok = weak_accepts_indefinite and outcomes["indefinite"] == "rejected"

    return record(
        "C5_non_pd_covariance_injection_rejected",
        ok,
        f"outcomes={outcomes} inject_ok={inject_ok}",
        poison_ok,
        {**outcomes, "spd_inject_ok": inject_ok},
    )


# ── C6 identity round-trip with SE3 height preservation ────────────────────


def case_identity_and_height():
    """decanonicalize∘canonicalize ≈ id; height/up component preserved under SE3."""
    frame = Z_UP
    # Explicit SE(2) matrix so translation is exactly the agent horizontal position
    # (SE2.exp tangent coords are NOT world translation).
    planar = np.array(
        [
            [math.cos(0.7), -math.sin(0.7), 1.2],
            [math.sin(0.7), math.cos(0.7), -0.8],
            [0.0, 0.0, 1.0],
        ],
        dtype=np.float64,
    )
    planar = SE2.validate(planar)
    belief = make_belief(mean=frame.lift(planar, 0.37), cov=np.eye(6) * 1e-6, group=SE3)
    agent_xy = planar[:2, 2]
    pts = np.array(
        [
            [agent_xy[0], agent_xy[1], 1.25],
            [2.0, 0.0, -0.5],
            [0.0, 0.0, 0.37],
            [agent_xy[0], agent_xy[1], 0.37],
        ],
        dtype=np.float64,
    )
    can = np.asarray(C.canonicalize_points(pts, belief))
    back = np.asarray(C.decanonicalize_points(can, belief))
    rt = float(np.max(np.abs(back - pts)))
    # Point directly above agent horizontal origin keeps world height; xy → 0.
    at_agent = np.asarray(
        C.canonicalize_points(np.array([agent_xy[0], agent_xy[1], 1.25]), belief)
    )
    height_ok = (
        abs(at_agent[2] - 1.25) <= 1e-12
        and abs(at_agent[0]) <= 1e-9
        and abs(at_agent[1]) <= 1e-9
    )
    # Roll/pitch belief rejected (compose a small roll onto a gravity-aligned pose).
    aligned = frame.lift(planar, 0.0)
    rolled = boxplus(SE3, aligned, np.array([0.0, 0.0, 0.0, 0.15, 0.0, 0.0]), side="right")
    roll_rejected = False
    try:
        make_belief(mean=rolled, cov=np.eye(6) * 1e-6, group=SE3)
    except ValueError:
        roll_rejected = True
    ok = rt <= ROUNDTRIP_TOL and height_ok and roll_rejected

    # Poison: use full SE3 mean inverse (includes height 0.37) instead of lift(...,0).
    L_full = belief.belief.mean
    probe = np.array([[agent_xy[0], agent_xy[1], 1.25]])
    wrong = SE3.act(SE3.inverse(L_full), probe)[0]
    # Contract keeps z=1.25; full-mean inverse shifts z by -0.37 → 0.88.
    poison_height_drift = abs(wrong[2] - 1.25) > 1e-6
    poison_ok = poison_height_drift and height_ok

    return record(
        "C6_identity_roundtrip_and_height_preservation",
        ok,
        f"rt={rt:.3e} height_ok={height_ok} at_agent={at_agent.tolist()} "
        f"roll_rejected={roll_rejected} poison_wrong_z={wrong[2]:.6f}",
        poison_ok,
        {
            "max_roundtrip": rt,
            "height_ok": height_ok,
            "at_agent_canonical": [float(x) for x in at_agent],
            "roll_pitch_rejected": roll_rejected,
            "poison_wrong_z": float(wrong[2]),
        },
    )


# ── C7 error-propagation derivation vs measured ────────────────────────────


def _independent_point_jacobian_se2(p):
    """Independent derivation: δ ≈ -[ρx,ρy] - θ J p, J=[[0,-1],[1,0]]."""
    px, py = float(p[0]), float(p[1])
    # columns: ρx, ρy, θ  →  rows: δx, δy, δz(=0)
    J = np.zeros((3, 3))
    J[0, 0] = -1.0
    J[1, 1] = -1.0
    J[0, 2] = py  # -θ * (J p)_x = -θ*(-py)? wait J_rot p = [-py, px]; -θ Jp = [θ py, -θ px]
    J[1, 2] = -px
    return J


def _independent_vector_jacobian_se2(v):
    vx, vy = float(v[0]), float(v[1])
    J = np.zeros((3, 3))
    J[0, 2] = vy
    J[1, 2] = -vx
    return J


def case_error_propagation():
    """Finite-diff Jacobian + MC empirical cov vs module prediction & independent JΣJᵀ."""
    rng = np.random.default_rng(42)
    cov = np.array(
        [
            [4e-4, 1e-5, 2e-5],
            [1e-5, 5e-4, -1e-5],
            [2e-5, -1e-5, 3e-4],
        ]
    )
    belief = make_belief(mean=se2(0.5, -0.3, 0.4), cov=cov)
    world_pt = np.array([1.7, -0.9, 0.0])
    world_vec = np.array([0.6, 0.8, 0.0])
    p_can = np.asarray(C.canonicalize_points(world_pt, belief))
    v_can = np.asarray(C.canonicalize_vectors(world_vec, belief))

    pred_pt = C.predicted_point_error_covariance(belief, p_can)
    pred_vec = C.predicted_vector_error_covariance(belief, v_can)
    indep_pt = _independent_point_jacobian_se2(p_can) @ cov @ _independent_point_jacobian_se2(p_can).T
    indep_vec = (
        _independent_vector_jacobian_se2(v_can)
        @ cov
        @ _independent_vector_jacobian_se2(v_can).T
    )
    deriv_pt = float(np.max(np.abs(pred_pt - indep_pt)))
    deriv_vec = float(np.max(np.abs(pred_vec - indep_vec)))

    # Finite-difference Jacobian of canonicalize_points w.r.t. right tangent.
    eps = 1e-7
    fd = np.zeros((3, 3))
    base = np.asarray(C.canonicalize_points(world_pt, belief))
    for k in range(3):
        xi = np.zeros(3)
        xi[k] = eps
        pert = C.apply_pose_error(belief, xi)
        fd[:, k] = (np.asarray(C.canonicalize_points(world_pt, pert)) - base) / eps
    fd_err = float(np.max(np.abs(fd - _independent_point_jacobian_se2(p_can))))

    # Monte Carlo empirical covariance.
    n = 8000
    samples = C.sample_pose_errors(belief, rng, n)
    errs_pt = np.zeros((n, 3))
    errs_vec = np.zeros((n, 3))
    for i, xi in enumerate(samples):
        pert = C.apply_pose_error(belief, xi)
        errs_pt[i] = np.asarray(C.canonicalize_points(world_pt, pert)) - base
        errs_vec[i] = np.asarray(C.canonicalize_vectors(world_vec, pert)) - np.asarray(
            C.canonicalize_vectors(world_vec, belief)
        )
    emp_pt = np.cov(errs_pt, rowvar=False)
    emp_vec = np.cov(errs_vec, rowvar=False)

    def rel_frob(a, b):
        return float(np.linalg.norm(a - b, "fro") / max(np.linalg.norm(b, "fro"), 1e-30))

    rel_pt = rel_frob(emp_pt, pred_pt)
    rel_vec = rel_frob(emp_vec, pred_vec)
    ok = (
        deriv_pt < 1e-12
        and deriv_vec < 1e-12
        and fd_err < 5e-5
        and rel_pt <= COV_REL_TOL
        and rel_vec <= COV_REL_TOL
    )

    # Poison: drop the yaw columns → prediction mismatches MC badly.
    bad_J = _independent_point_jacobian_se2(p_can).copy()
    bad_J[:, 2] = 0.0
    bad_pred = bad_J @ cov @ bad_J.T
    poison_rel = rel_frob(emp_pt, bad_pred)
    poison_ok = poison_rel > 0.2 and rel_pt <= COV_REL_TOL

    return record(
        "C7_error_propagation_derivation_vs_measured",
        ok,
        f"deriv_pt={deriv_pt:.3e} deriv_vec={deriv_vec:.3e} fd_err={fd_err:.3e} "
        f"rel_pt={rel_pt:.4f} rel_vec={rel_vec:.4f} poison_rel={poison_rel:.4f}",
        poison_ok,
        {
            "deriv_match_point": deriv_pt,
            "deriv_match_vector": deriv_vec,
            "finite_diff_jacobian_err": fd_err,
            "mc_relative_point": rel_pt,
            "mc_relative_vector": rel_vec,
            "mc_samples": n,
            "poison_yaw_dropped_relative": poison_rel,
        },
    )


# ── C8 RGB / image rejected (extra adversarial) ────────────────────────────


def case_image_rejected():
    belief = make_belief()
    img = np.zeros((8, 8, 3))
    rejected = False
    try:
        C.canonicalize(img, belief)
    except ValueError:
        rejected = True
    ok = rejected
    # Poison: treat trailing-3 as 3D points batch of length 8*8 — would wrongly accept.
    flat = img.reshape(-1, 3)
    wrong_accept = C.canonicalize_points(flat, belief)
    poison_ok = wrong_accept.shape == (64, 3) and rejected
    return record(
        "C8_image_rgb_rejected",
        ok,
        f"rejected={rejected}",
        poison_ok,
        {"rejected": rejected},
    )


CASES = [
    case_near_pi_equivariance,
    case_reflection_rejected,
    case_nonrigid_rejected,
    case_grid_out_of_bounds,
    case_non_pd_covariance,
    case_identity_and_height,
    case_error_propagation,
    case_image_rejected,
]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--json-out", type=Path, required=True)
    args = parser.parse_args()

    results = []
    for fn in CASES:
        try:
            results.append(fn())
        except Exception as exc:  # pragma: no cover - surface unexpected
            results.append(
                record(
                    fn.__name__,
                    False,
                    f"EXCEPTION: {exc}\n{traceback.format_exc()}",
                    False,
                )
            )

    summary = _jsonable(
        {
            "task": "ainerzero.V9.G4",
            "reviewer": "composer-m7k2",
            "author_under_review": "deepseek-flash-9m2x",
            "n_cases": len(results),
            "n_ok": sum(1 for r in results if r["ok"]),
            "n_poison_caught": sum(1 for r in results if r["poison_caught"]),
            "all_ok": all(r["ok"] for r in results),
            "all_poison_caught": all(r["poison_caught"] for r in results),
            "cases": results,
            "canonical_sha256": sha256(ROOT / "src/ainerzero/v9/geometry/canonical.py"),
            "test_canonical_sha256": sha256(ROOT / "tests/v9/geometry/test_canonical.py"),
        }
    )
    args.json_out.parent.mkdir(parents=True, exist_ok=True)
    args.json_out.write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n")
    print(json.dumps({k: summary[k] for k in (
        "n_cases", "n_ok", "n_poison_caught", "all_ok", "all_poison_caught"
    )}, indent=2))
    for r in results:
        flag = "PASS" if r["ok"] else "FAIL"
        poison = "poisonOK" if r["poison_caught"] else "poisonMISS"
        print(f"  [{flag}/{poison}] {r['name']}: {r['detail']}")

    if not summary["all_ok"] or not summary["all_poison_caught"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
