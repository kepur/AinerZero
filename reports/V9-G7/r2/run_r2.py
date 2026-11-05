"""V9.G7 r2 evidence: reruns the G8 findings against the r2 package and writes strict JSON.

Writes only under --out (default: this file's directory): metrics.json, evidence/pytest.txt,
evidence/mutation_matrix.json, SHA256SUMS.txt.  Mutants are built in a TemporaryDirectory.
G8's independent generator is loaded read-only from reports/V9-G8/independent_gen.py and patched
in memory (its ObservationContext call drops the in_slow_domain label, which r2 removed).
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
import math
from pathlib import Path
import subprocess
import sys
import tempfile
import types

import numpy as np

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests/v9/mechanism"))

import ainerzero.v9.mechanism as pkg  # noqa: E402
import test_cmfl_r2_adversarial as adv  # noqa: E402

G8_GEN = ROOT / "reports/V9-G8/independent_gen.py"
G8_PATCH = ("        in_slow_domain=in_slow_domain,\n    )", "    )")
PRIOR_COV = np.diag([1.5, 0.25, 0.60])


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _finite(x):
    """Strict JSON: non-finite floats become None (recorded as such, never Infinity/NaN)."""
    if isinstance(x, dict):
        return {str(k): _finite(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [_finite(v) for v in x]
    if isinstance(x, (np.floating, float)):
        return float(x) if math.isfinite(float(x)) else None
    if isinstance(x, np.integer):
        return int(x)
    if isinstance(x, np.bool_):
        return bool(x)
    return x


def load_g8_generator() -> types.ModuleType:
    text = G8_GEN.read_text(encoding="utf-8")
    assert text.count(G8_PATCH[0]) == 1
    mod = types.ModuleType("g8_independent_gen_nolabel")
    sys.modules[mod.__name__] = mod  # dataclasses resolve annotations through sys.modules
    exec(compile(text.replace(*G8_PATCH), str(G8_GEN), "exec"), mod.__dict__)
    return mod


def toy_routes() -> dict:
    reg = pkg.default_cmfl_registration()
    contexts, metas = pkg.build_benchmark_suite(reg, n_per_route=8, seed=20261028)
    prior = adv._prior(pkg)
    out = {}
    for tag, gate in (
        ("frozen_toy_envelope", pkg.MechanismSufficiencyGate(reg, domain_envelope=pkg.toy_slow_d_valid_envelope())),
        ("no_envelope_fail_closed", pkg.MechanismSufficiencyGate(reg)),
    ):
        recs = [gate.route(c, prior, scope_id=c.context_id) for c in contexts]
        cm = pkg.evaluate_msg_confusion_matrix(recs, metas)
        out[tag] = {"accuracy": cm["accuracy"], "per_class_recall": cm["per_class_recall"], "predicted_counts": cm["predicted_counts"]}
    out["toy_envelope_limits"] = dict(pkg.TOY_SLOW_D_VALID_LIMITS)
    return out


def g8_cross_check(G) -> dict:
    reg = pkg.default_cmfl_registration()
    prior = pkg.ParamBelief(mean=G.G_PRIOR.copy(), cov=PRIOR_COV.copy(), dimensionless_scale=G.SCALE.copy())
    gate = pkg.MechanismSufficiencyGate(reg, domain_envelope=pkg.toy_slow_d_valid_envelope())
    hits: dict[str, list[int]] = {}
    for c, m in G.gen_suite(seed=1, n=6, ood_flag=False):
        r = gate.route(c, prior, scope_id=c.context_id)
        h = hits.setdefault(m.true_route, [0, 0])
        h[0] += int(r.route_code.value == m.true_route)
        h[1] += 1
    stl = pkg.WeakFormSTLSQ(threshold=0.20)
    ctxs = [c for c, _ in G.gen_parametric(seed=401, n=6)] + [c for c, _ in G.gen_structural(seed=601, n=6)]
    raws = [pkg.compute_innovations_and_nis(c, G.G_PRIOR)[0] for c in ctxs]
    energy = {"r1_pooled_per_context": adv._pooled_r1_ratios(stl, ctxs, G.G_PRIOR)}
    for tag, nc in (("r2_hard", None), ("r2_gls", PRIOR_COV)):
        b = stl._compute_context_orthogonal_bases(ctxs, G.G_PRIOR, "single_step", nc)
        pr = stl._project_views_orthogonal(raws, b)
        energy[tag] = [float(np.sum(p ** 2) / np.sum(r ** 2)) for p, r in zip(pr, raws)]
    energy = {k: {"max": max(v), "values": v} for k, v in energy.items()}
    disc = {}
    for tag, kw in (("none", {"project_orthogonal": False}), ("r2_hard", {}), ("r2_gls", {"nuisance_cov": PRIOR_COV})):
        fp = 0
        for k in range(10):
            cand = stl.discover([c for c, _ in G.gen_parametric(seed=400 + k, n=6)], G.G_PRIOR, rng=np.random.default_rng(500 + k), **kw)
            fp += int(len(cand.active_terms) > 0)
        cnt: Counter = Counter()
        for k in range(20):
            cand = stl.discover([c for c, _ in G.gen_structural(seed=600 + k, n=6)], G.G_PRIOR, rng=np.random.default_rng(700 + k), **kw)
            cnt["+".join(cand.active_terms) or "(empty)"] += 1
        disc[tag] = {"param_world_false_discovery": f"{fp}/10", "structural_support_counts_of_20": dict(cnt)}
    return {
        "g8_generator_sha256": _sha(G8_GEN),
        "g8_patch": "ObservationContext(... in_slow_domain=...) argument dropped in memory",
        "route_recall_frozen_toy_envelope_no_labels": {k: f"{a}/{b}" for k, (a, b) in hits.items()},
        "projection_energy_ratio": energy,
        "discovery": disc,
    }


def promotion_numbers() -> dict:
    out = {}
    rng = np.random.default_rng(2028)
    d, c, t = adv._worlds(pkg, rng, "D", 6), adv._worlds(pkg, rng, "C", 20), adv._worlds(pkg, rng, "T", 12)
    dec = adv._promote(pkg, adv._discover_true(pkg, d, rng, "f2"), d, c, t, tag="f2")
    out["F2_true_mechanism_4_worlds_per_family"] = {
        "admitted": dec.admitted, "superiority_passed": dec.superiority_passed, "e_pers": dec.e_pers,
        "e_threshold": 1.0 / dec.alpha_per_candidate, "rejection_reasons": list(dec.rejection_reasons),
    }
    rng = np.random.default_rng(3128)
    d, c = adv._worlds(pkg, rng, "D", 6), adv._worlds(pkg, rng, "C", 20)
    cand = adv._discover_true(pkg, d, rng, "lab")
    t = adv._worlds(pkg, rng, "Tok", 45)
    dec = adv._promote(pkg, cand, d, c, t, tag="lab_ok")
    out["F3_F4_true_mechanism_15_worlds_per_family"] = {
        "admitted": dec.admitted, "e_by_family": dict(dec.e_by_family), "e_threshold": 1.0 / dec.alpha_per_candidate,
        "facttest_score": dec.facttest_score, "facttest_threshold": dec.facttest_threshold,
        "facttest_order_k": dec.facttest_order_k, "facttest_n_null": dec.facttest_n_null,
    }
    for seed in (15, 16):
        rng = np.random.default_rng(seed)
        d = adv._worlds(pkg, rng, "FD", 6, coeff=0.55)
        c = adv._worlds(pkg, rng, "FC", 20, coeff=0.55)
        t = adv._worlds(pkg, rng, "FT", 120, coeff=0.55)
        wrong = pkg.DiscoveredCandidate(
            candidate_id="coulomb_wrong", proposer="adversary", active_terms=("coulomb_friction",),
            coefficients=np.array([0.45]), confidence_intervals=((0.45, 0.45),), abstained_terms=(),
            pareto_error=0.0, pareto_complexity=1, discovery_data_id="FD", total_candidates_attempted=1,
            orthogonality_mode="single_step",
        )
        dec = adv._promote(pkg, wrong, d, c, t, tag=f"f4_{seed}")
        out[f"F4_coulomb_0.45_on_drag_0.55_seed{seed}_120_worlds"] = {
            "admitted": dec.admitted, "superiority_passed": dec.superiority_passed,
            "zero_regression_passed": dec.zero_regression_passed, "e_lond_passed": dec.e_lond_passed,
            "e_pers": dec.e_pers, "facttest_score": dec.facttest_score, "facttest_threshold": dec.facttest_threshold,
            "rejection_reasons": list(dec.rejection_reasons),
        }
    return out


def mutation_matrix() -> dict:
    rows = {}
    with tempfile.TemporaryDirectory() as td:
        for key in sorted(adv.MUTANTS):
            mut = adv._build_mutant(Path(td), key)
            try:
                holds = adv.SCENARIOS[key](mut)
                how = "scenario returned False" if not holds else "NOT CAUGHT"
            except AssertionError as exc:
                holds, how = False, f"AssertionError: {str(exc)[:120]}"
            finally:
                for m in [m for m in sys.modules if m == mut.__name__ or m.startswith(mut.__name__ + ".")]:
                    sys.modules.pop(m, None)
            rows[key] = {"baseline_holds": adv.SCENARIOS[key](pkg), "mutant_holds": holds, "caught_by": how,
                         "mutation": [f"{f}: {o[:70]!r} -> {n[:70]!r}" for f, o, n in adv.MUTANTS[key]]}
    return rows


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=Path(__file__).resolve().parent)
    args = ap.parse_args()
    out: Path = args.out
    (out / "evidence").mkdir(parents=True, exist_ok=True)

    py = subprocess.run(
        [sys.executable, "-m", "pytest", "tests/v9/mechanism", "-q", "-p", "no:cacheprovider"],
        cwd=ROOT, capture_output=True, text=True, env={"PATH": "/usr/bin:/bin", "HOME": str(Path.home())},
    )
    (out / "evidence/pytest.txt").write_text(py.stdout + py.stderr, encoding="utf-8")

    mm = mutation_matrix()
    (out / "evidence/mutation_matrix.json").write_text(json.dumps(_finite(mm), indent=1, allow_nan=False, ensure_ascii=False) + "\n", encoding="utf-8")

    src_files = sorted((ROOT / "src/ainerzero/v9/mechanism").glob("*.py")) + sorted((ROOT / "tests/v9/mechanism").glob("*.py"))
    metrics = {
        "task": "ainerzero.V9.G7",
        "revision": "r2",
        "pytest_returncode": py.returncode,
        "pytest_tail": (py.stdout.strip().splitlines() or [""])[-1],
        "toy_routes": toy_routes(),
        "g8_cross_check": g8_cross_check(load_g8_generator()),
        "promotion": promotion_numbers(),
        "mutation_matrix_all_caught": all(not r["mutant_holds"] and r["baseline_holds"] for r in mm.values()),
        "source_sha256": {str(p.relative_to(ROOT)): _sha(p) for p in src_files},
    }
    (out / "metrics.json").write_text(json.dumps(_finite(metrics), indent=1, allow_nan=False, ensure_ascii=False) + "\n", encoding="utf-8")

    listed = sorted(p for p in out.rglob("*") if p.is_file() and p.name != "SHA256SUMS.txt" and "__pycache__" not in p.parts)
    (out / "SHA256SUMS.txt").write_text("".join(f"{_sha(p)}  {p.relative_to(out)}\n" for p in listed), encoding="utf-8")
    print(json.dumps({"pytest": metrics["pytest_tail"], "mutants_all_caught": metrics["mutation_matrix_all_caught"]}))


if __name__ == "__main__":
    main()
