"""G10 independent non-author CPU review of G7 r3.

Does not import author tests. Uses independently coded RK4 fixtures.
Writes only under reports/V9-G10/. Never mutates product source.
"""
from __future__ import annotations

import dataclasses
import hashlib
import importlib.util
import json
import math
import shutil
import subprocess
import sys
import traceback
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
SOURCE = ROOT / "src/ainerzero/v9/mechanism"
EVID = OUT / "evidence"
EVID.mkdir(parents=True, exist_ok=True)


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def strict(x):
    if dataclasses.is_dataclass(x):
        return strict(dataclasses.asdict(x))
    if isinstance(x, dict):
        return {str(k): strict(v) for k, v in x.items()}
    if isinstance(x, (tuple, list)):
        return [strict(v) for v in x]
    if isinstance(x, np.ndarray):
        return strict(x.tolist())
    if isinstance(x, (float, np.floating)):
        return float(x) if math.isfinite(float(x)) else str(float(x))
    if isinstance(x, np.integer):
        return int(x)
    if isinstance(x, np.bool_):
        return bool(x)
    return x


def save(name: str, x) -> None:
    (OUT / name).write_text(json.dumps(strict(x), ensure_ascii=False, indent=2, allow_nan=False) + "\n")


def load(name: str, changes=()):
    dest = OUT / "isolated" / name
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True, exist_ok=True)
    for p in SOURCE.glob("*.py"):
        shutil.copyfile(p, dest / p.name)
    for fn, old, new in changes:
        path = dest / fn
        text = path.read_text()
        assert text.count(old) == 1, (fn, old, text.count(old))
        path.write_text(text.replace(old, new))
    # Avoid colliding with previously imported product package names.
    for key in list(sys.modules):
        if key == name or key.startswith(name + "."):
            del sys.modules[key]
    spec = importlib.util.spec_from_file_location(
        name, dest / "__init__.py", submodule_search_locations=[str(dest)]
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


P = load("g10baseline")
REG = P.default_cmfl_registration()
PHI = np.array([9.81, 0.25, 1.2])
COV = np.diag([1.5, 0.25, 0.6])
SCALE = np.array([2.0, 0.2, 0.5])
TRUSTED = {"verified_producer": "g10-independent-evaluator", "isolated_evaluator": True}


def prior(p=P):
    return p.ParamBelief(PHI, COV, SCALE)


# Independently coded vector field + RK4; no product simulator for fixture generation.
def rhs(s, u, phi, drag):
    a = u - phi[1] * s[2:] - phi[2] * s[:2] - np.array([0.0, phi[0]]) - drag * np.linalg.norm(s[2:]) * s[2:]
    return np.r_[s[2:], a]


def step(s, u, dt, phi, drag):
    a = rhs(s, u, phi, drag)
    b = rhs(s + dt * a / 2, u, phi, drag)
    c = rhs(s + dt * b / 2, u, phi, drag)
    d = rhs(s + dt * c, u, phi, drag)
    return s + dt * (a + 2 * b + 2 * c + d) / 6


def gen(prefix, n, seed, W=20, dt=0.01, sigma=0.004, drag=0.55, param=False, p=P):
    rng = np.random.default_rng(seed)
    out = []
    for i in range(n):
        phi = (
            PHI + np.array([rng.uniform(-1.4, 1.4), rng.uniform(0.1, 0.35), rng.uniform(-0.5, 0.5)])
            if param
            else PHI
        )
        s = np.array(
            [
                rng.uniform(0.8, 2.8),
                rng.uniform(-2.7, -0.8),
                rng.uniform(2.2, 4.2),
                rng.uniform(-3.8, -1.8),
            ]
        )
        actions = rng.uniform(-3, 3, (W, 2))
        states, nxt = [], []
        for u in actions:
            states.append(s.copy())
            s = step(s, u, dt, phi, 0.0 if param else drag)
            nxt.append(s + rng.normal(0, sigma, 4))
        out.append(
            p.ObservationContext(
                context_id=f"{prefix}:{i}",
                world_instance_id=f"{prefix}/{i}",
                t_start=0,
                object_keys=("particle",),
                dt=dt,
                integrator="rk4",
                states=np.array(states),
                next_states=np.array(nxt),
                actions=actions,
                innovation_cov=np.eye(4) * sigma**2,
                env_family=REG.env_families[i % 3],
            )
        )
    return out


def candidate(p=P, term="quadratic_drag", coef=0.55, cid="g10-fixed"):
    return p.DiscoveredCandidate(
        cid,
        "sindy",
        (term,),
        np.array([coef]),
        ((coef, coef),),
        (),
        0.0,
        1,
        "G10-D",
        1,
        "single_step",
    )


D = gen("D", 9, 291001)
C = gen("C", 24, 291002)
T = gen("T", 60, 291003)
fixture_identity = {}
for name, ctxs in [("D", D), ("C", C), ("T", T)]:
    payload = [{f.name: getattr(c, f.name) for f in dataclasses.fields(c)} for c in ctxs]
    save(f"evidence/fixture_{name}.json", payload)
    fixture_identity[name] = sha(OUT / f"evidence/fixture_{name}.json")


def evaluate(
    p=P,
    cand=None,
    tests=None,
    nulls=None,
    cal=None,
    disc=None,
    gate=None,
    ids=("G10-D", "G10-C", "G10-T"),
    tid="G10-test",
):
    cand = candidate(p) if cand is None else cand
    disc = D if disc is None else disc
    cal = C if cal is None else cal
    tests = T if tests is None else tests
    if nulls is None:
        nulls = p.build_facttest_null_controls(cand, disc, prior(p), p.default_basis_library())
    return (gate or p.OneSidedPromotionGate(REG)).evaluate_and_promote(
        cand,
        prior(p),
        discovery_contexts=disc,
        calibration_contexts=cal,
        test_contexts=tests,
        discovery_data_id=ids[0],
        calibration_data_id=ids[1],
        test_data_id=ids[2],
        test_id=tid,
        producer="g10-independent-evaluator",
        trusted_context=TRUSTED,
        facttest_null_candidates=nulls,
    )


results = {
    "scope": "CPU NumPy only; independent RK4 fixtures; no author tests imported; no accept",
    "reviewer": "composer-6201",
    "reviewed_task": "ainerzero.V9.G7",
    "revision": "r3",
    "registration": REG.to_dict(),
    "registration_sha": REG.registration_sha(),
    "fixture_sha256": fixture_identity,
    "n_req": int(P.facttest_required_null_count(REG.tau_cal, REG.delta_cal)),
}


def record(name, fn):
    try:
        value = fn()
        results[name] = strict(value)
        print(name, json.dumps(strict(value), ensure_ascii=False, allow_nan=False)[:500], flush=True)
        return value
    except Exception as e:
        results[name] = {"exception": repr(e), "traceback": traceback.format_exc()}
        print(name, traceback.format_exc(), flush=True)
        return results[name]


# --- Core G10 checks ---
base = record("positive", evaluate)
assert base.admitted, base.rejection_reasons


def null_same_id_empty():
    forged = [dataclasses.replace(candidate(coef=0.0), candidate_id="same") for _ in range(29)]
    dec = evaluate(nulls=forged)
    return {
        "admitted": dec.admitted,
        "facttest_passed": dec.facttest_passed,
        "reasons": dec.rejection_reasons,
        "n_null": dec.facttest_n_null,
        "recipe_sha": dec.facttest_recipe_sha,
    }


def null_different_id_empty():
    forged = [dataclasses.replace(candidate(coef=0.0), candidate_id=f"forged-{i}") for i in range(29)]
    dec = evaluate(nulls=forged)
    return {
        "admitted": dec.admitted,
        "facttest_passed": dec.facttest_passed,
        "reasons": dec.rejection_reasons,
        "n_null": dec.facttest_n_null,
        "binding_sha": dec.facttest_binding_sha,
    }


record("null_29_same_id_empty", null_same_id_empty)
record("null_29_different_id_empty", null_different_id_empty)


def id_swap_candidate():
    """Rename candidate_id of a wrong nonempty law; must still reject (content, not ID)."""
    wrong = candidate(term="coulomb_friction", coef=0.45, cid="looks-like-good-id")
    nulls = P.build_facttest_null_controls(wrong, D, prior(), P.default_basis_library())
    dec = evaluate(cand=wrong, nulls=nulls, tests=gen("idswap", 120, 292001), ids=("G10-D", "G10-C", "G10-Tidswap"), tid="idswap")
    return {"admitted": dec.admitted, "facttest_passed": dec.facttest_passed, "reasons": dec.rejection_reasons}


record("id_swap_wrong_candidate", id_swap_candidate)


def retest_rename_and_copy():
    g = P.OneSidedPromotionGate(REG)
    first = evaluate(gate=g)
    out = {"first_admitted": first.admitted, "first_step": first.step_t}
    # Same numeric T, only test_data_id renamed.
    try:
        evaluate(gate=g, ids=("G10-D", "G10-C", "G10-T-renamed"), tid="retest-label")
        out["same_content_new_label"] = {"raised": False}
    except ValueError as e:
        out["same_content_new_label"] = {"raised": True, "message": str(e)}
    # Full label rewrite of the same arrays (context/world/object/time).
    g2 = P.OneSidedPromotionGate(REG)
    evaluate(gate=g2)
    renamed = [
        dataclasses.replace(
            x,
            context_id=f"renamed{i}",
            world_instance_id=f"renamed-world/{i}",
            t_start=987,
            object_keys=("renamed",),
        )
        for i, x in enumerate(T)
    ]
    try:
        evaluate(gate=g2, tests=renamed, ids=("G10-D", "G10-C", "G10-T-relabel"), tid="retest-relabel")
        out["relabeled_same_arrays"] = {"raised": False}
    except ValueError as e:
        out["relabeled_same_arrays"] = {"raised": True, "message": str(e)}
    # Rejected first attempt still reserves T content.
    g3 = P.OneSidedPromotionGate(REG)
    bad = evaluate(gate=g3, nulls=[])
    out["rejected_reserves"] = {"admitted": bad.admitted, "step": bad.step_t}
    try:
        evaluate(gate=g3, ids=("G10-D", "G10-C", "G10-T-after-reject"), tid="after-reject")
        out["reuse_after_reject"] = {"raised": False}
    except ValueError as e:
        out["reuse_after_reject"] = {"raised": True, "message": str(e)}
    # Fresh independent world advances to step 2.
    g4 = P.OneSidedPromotionGate(REG)
    first2 = evaluate(gate=g4)
    fresh = gen("freshT", 60, 291919)
    second = evaluate(gate=g4, tests=fresh, ids=("G10-D", "G10-C", "G10-T-fresh"), tid="fresh")
    out["fresh_world"] = {
        "first_step": first2.step_t,
        "second_step": second.step_t,
        "second_admitted": second.admitted,
        "content_overlap": bool(set(first2.test_content_shas) & set(second.test_content_shas)),
    }
    return out


record("t_world_replay_guards", retest_rename_and_copy)


def hard_vs_gls():
    stl = P.WeakFormSTLSQ(threshold=0.20)
    hard = stl.discover(D, PHI, rng=np.random.default_rng(700), nuisance_cov=None)
    implicit = stl.discover(D, PHI, rng=np.random.default_rng(700))
    gls = stl.discover(D, PHI, rng=np.random.default_rng(700), nuisance_cov=COV)
    ctx = D[0]
    g = P.step_sensitivity_jacobian(ctx.states, ctx.actions, ctx.dt, PHI, integrator=ctx.integrator).reshape(-1, 3)
    q, _ = np.linalg.qr(g)
    views = [q[:, 0].reshape(ctx.states.shape)]
    hard_p = stl._project_views_orthogonal(
        views, stl._compute_context_orthogonal_bases([ctx], PHI, "single_step", None)
    )[0]
    gls_p = stl._project_views_orthogonal(
        views, stl._compute_context_orthogonal_bases([ctx], PHI, "single_step", COV)
    )[0]
    # Diagnostic promotion rejection on tagged candidate.
    cand = candidate()
    nulls = P.build_facttest_null_controls(cand, D, prior(), P.default_basis_library())
    good = evaluate(cand=cand, nulls=nulls)
    tagged = dataclasses.replace(cand, diagnostic_only=True)
    blocked = evaluate(
        cand=tagged,
        nulls=nulls,
        tests=gen("diagT", 60, 293001),
        ids=("G10-D", "G10-C", "G10-T-diag"),
        tid="diag",
    )
    return {
        "default_matches_hard": bool(
            implicit.active_terms == hard.active_terms
            and np.array_equal(implicit.coefficients, hard.coefficients)
            and (not getattr(implicit, "diagnostic_only", False))
        ),
        "gls_diagnostic_only": bool(gls.diagnostic_only),
        "hard_parameter_inner": float(np.linalg.norm(q.T @ hard_p.reshape(-1))),
        "gls_parameter_inner": float(np.linalg.norm(q.T @ gls_p.reshape(-1))),
        "positive_admitted": good.admitted,
        "diagnostic_admitted": blocked.admitted,
        "diagnostic_reasons": blocked.rejection_reasons,
    }


record("hard_projection_vs_gls", hard_vs_gls)


def nonempty_wrong():
    rows = []
    for i in range(3):
        wrong = candidate(term="coulomb_friction", coef=0.45, cid=f"wrong-{i}")
        nulls = P.build_facttest_null_controls(wrong, D, prior(), P.default_basis_library())
        dec = evaluate(
            cand=wrong,
            nulls=nulls,
            tests=gen(f"wrong{i}", 120, 294000 + i),
            ids=("G10-D", "G10-C", f"G10-Tw{i}"),
            tid=f"wrong{i}",
        )
        rows.append({"admitted": dec.admitted, "reasons": dec.rejection_reasons})
    return {"admissions": sum(r["admitted"] for r in rows), "rows": rows}


record("nonempty_wrong_mechanism", nonempty_wrong)


def discovery_cells():
    rows = []
    for W, dt, sig, tag in [(20, 0.01, 0.003, "authorlike"), (16, 0.015, 0.0025, "g8like")]:
        for mode, cov in [("hard_default", None), ("gls_diagnostic_only", COV)]:
            counts = {
                "parameter_false_discoveries": 0,
                "structural_exact_support": 0,
                "trials": 10,
            }
            for k in range(10):
                rng = np.random.default_rng(3000 + k)
                cand = P.WeakFormSTLSQ(threshold=0.20).discover(
                    gen("P", 6, 31000 + k, W=W, dt=dt, sigma=sig, param=True),
                    PHI,
                    rng=rng,
                    nuisance_cov=cov,
                )
                counts["parameter_false_discoveries"] += int(bool(cand.active_terms))
                rng = np.random.default_rng(4000 + k)
                cand = P.WeakFormSTLSQ(threshold=0.20).discover(
                    gen("S", 6, 41000 + k, W=W, dt=dt, sigma=sig, drag=0.45),
                    PHI,
                    rng=rng,
                    nuisance_cov=cov,
                )
                counts["structural_exact_support"] += int(cand.active_terms == ("quadratic_drag",))
            rows.append({"setting": tag, "W": W, "dt": dt, "sigma": sig, "mode": mode, **counts})
    return rows


record("independent_discovery_recovery", discovery_cells)


# Real single-gate break controls in temp copies only.
mutations = [
    (
        "recipe_bypass",
        "promotion_gate.py",
        "        elif not recipe_valid:",
        "        elif False:",
        "null_29_different_id_empty",
    ),
    (
        "history_bypass",
        "promotion_gate.py",
        "        if t_worlds & self._used_test_worlds or t_content & self._used_test_contents:",
        "        if False:",
        "history",
    ),
    (
        "diagnostic_bypass",
        "promotion_gate.py",
        "        if candidate.diagnostic_only:",
        "        if False:",
        "diagnostic",
    ),
]
matrix = []
for name, fn, old, new, kind in mutations:
    mutant = load("g10mut_" + name, [(fn, old, new)])
    row = {"mutation": name, "kind": kind}
    if kind == "null_29_different_id_empty":
        forged = [dataclasses.replace(candidate(coef=0.0, p=mutant), candidate_id=f"forged-{i}") for i in range(29)]
        # Use mutant package API for evaluation.
        def _eval_mut(nulls=forged, p=mutant, tests=None, ids=("G10-D", "G10-C", "G10-Tm"), tid="mut"):
            cand = candidate(p=p)
            disc, cal = gen("Dm", 9, 291001, p=p), gen("Cm", 24, 291002, p=p)
            tests = gen("Tm", 60, 291003, p=p) if tests is None else tests
            return p.OneSidedPromotionGate(p.default_cmfl_registration()).evaluate_and_promote(
                cand,
                prior(p),
                discovery_contexts=disc,
                calibration_contexts=cal,
                test_contexts=tests,
                discovery_data_id=ids[0],
                calibration_data_id=ids[1],
                test_data_id=ids[2],
                test_id=tid,
                producer="g10-independent-evaluator",
                trusted_context=TRUSTED,
                facttest_null_candidates=nulls,
            )

        base_dec = null_different_id_empty()
        mut_dec = _eval_mut()
        # True control: bad recipe rejected on product; mutant must admit (gate destroyed).
        caught = (not base_dec["admitted"]) and bool(mut_dec.admitted)
        row.update(
            {
                "caught": caught,
                "baseline_admitted": base_dec["admitted"],
                "mutant_admitted": mut_dec.admitted,
                "mutant_reasons": mut_dec.rejection_reasons,
            }
        )
    elif kind == "history":
        # Build mutant-local contexts once.
        Dm, Cm, Tm = gen("Dm", 9, 291001, p=mutant), gen("Cm", 24, 291002, p=mutant), gen("Tm", 60, 291003, p=mutant)
        cand_m = candidate(p=mutant)
        nulls_m = mutant.build_facttest_null_controls(cand_m, Dm, prior(mutant), mutant.default_basis_library())

        def _ev(gate, p, tests, ids, tid):
            return gate.evaluate_and_promote(
                cand_m,
                prior(p),
                discovery_contexts=Dm,
                calibration_contexts=Cm,
                test_contexts=tests,
                discovery_data_id=ids[0],
                calibration_data_id=ids[1],
                test_data_id=ids[2],
                test_id=tid,
                producer="g10-independent-evaluator",
                trusted_context=TRUSTED,
                facttest_null_candidates=nulls_m,
            )

        g_base = P.OneSidedPromotionGate(REG)
        evaluate(gate=g_base)  # reserve on product
        raised_base = False
        try:
            evaluate(gate=g_base, ids=("G10-D", "G10-C", "G10-Tren"), tid="ren")
        except ValueError:
            raised_base = True
        g_mut = mutant.OneSidedPromotionGate(mutant.default_cmfl_registration())
        _ev(g_mut, mutant, Tm, ("G10-D", "G10-C", "G10-T"), "t1")
        raised_mut = False
        admitted_mut = None
        try:
            second = _ev(g_mut, mutant, Tm, ("G10-D", "G10-C", "G10-Tren"), "t2")
            admitted_mut = second.admitted
        except ValueError as e:
            raised_mut = True
            admitted_mut = str(e)
        caught = raised_base and (not raised_mut) and bool(admitted_mut is True)
        row.update(
            {
                "caught": caught,
                "baseline_raises": raised_base,
                "mutant_raises": raised_mut,
                "mutant_second_admitted": admitted_mut,
            }
        )
    else:  # diagnostic
        cand = candidate()
        nulls = P.build_facttest_null_controls(cand, D, prior(), P.default_basis_library())
        tagged = dataclasses.replace(cand, diagnostic_only=True)
        base_blocked = evaluate(
            cand=tagged,
            nulls=nulls,
            tests=gen("diagB", 60, 295001),
            ids=("G10-D", "G10-C", "G10-Tdb"),
            tid="diagb",
        )
        # Mutant evaluation with diagnostic flag.
        Dm, Cm, Tm = gen("Dd", 9, 291001, p=mutant), gen("Cd", 24, 291002, p=mutant), gen("Td", 60, 295002, p=mutant)
        cand_m = candidate(p=mutant)
        nulls_m = mutant.build_facttest_null_controls(cand_m, Dm, prior(mutant), mutant.default_basis_library())
        tagged_m = dataclasses.replace(cand_m, diagnostic_only=True)
        mut_dec = mutant.OneSidedPromotionGate(mutant.default_cmfl_registration()).evaluate_and_promote(
            tagged_m,
            prior(mutant),
            discovery_contexts=Dm,
            calibration_contexts=Cm,
            test_contexts=Tm,
            discovery_data_id="G10-D",
            calibration_data_id="G10-C",
            test_data_id="G10-Tdm",
            test_id="diagm",
            producer="g10-independent-evaluator",
            trusted_context=TRUSTED,
            facttest_null_candidates=nulls_m,
        )
        caught = (not base_blocked.admitted) and bool(mut_dec.admitted)
        row.update(
            {
                "caught": caught,
                "baseline_admitted": base_blocked.admitted,
                "mutant_admitted": mut_dec.admitted,
                "baseline_reasons": base_blocked.rejection_reasons,
            }
        )
    matrix.append(row)
    print("MUTATION", name, row.get("caught"), flush=True)

results["three_mutations"] = strict(matrix)
results["mutations_caught"] = f"{sum(1 for r in matrix if r.get('caught'))}/3"

# Manifest / archive integrity.
manifest = {
    "head": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
    "product_sha256": {str(p.relative_to(ROOT)): sha(p) for p in sorted(SOURCE.glob("*.py"))},
    "author_manifest_match": {},
}
author_manifest = json.loads((ROOT / "reports/V9-G7/r3/evidence/manifest.json").read_text())
for rel, expect in author_manifest["sha256"].items():
    if rel.startswith("../") or "interfaces/" in rel or rel.endswith(".md"):
        continue
    p = ROOT / rel
    if p.exists():
        got = sha(p)
        manifest["author_manifest_match"][rel] = {"ok": got == expect, "expect": expect, "got": got}

archive_ok = []
for sums_path in [
    ROOT / "reports/V9-G7/r1-archive/SHA256SUMS.txt",
    ROOT / "reports/V9-G7/r2/SHA256SUMS.txt",
]:
    base = sums_path.parent
    for line in sums_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if len(parts) < 2:
            continue
        expect, rel = parts[0], parts[-1]
        p = base / rel
        got = sha(p) if p.exists() else None
        # Known historical self-ref defect on r1 SHA256SUMS.txt itself.
        ok = (got == expect) or (rel.endswith("SHA256SUMS.txt") and expect.startswith("e3b0"))
        archive_ok.append({"sums": str(sums_path.relative_to(ROOT)), "file": rel, "ok": ok})
manifest["r1_r2_archive"] = {
    "all_ok_excluding_known_selfref": all(x["ok"] for x in archive_ok),
    "rows": archive_ok,
}
results["identity"] = strict(manifest)
# Recipe SHA already observed on positive decision / author match.
results["recipe_sha"] = results["positive"]["facttest_recipe_sha"]
results["verdict_hint"] = {
    "f1_29_empty_rejected": (not results["null_29_same_id_empty"]["admitted"])
    and (not results["null_29_different_id_empty"]["admitted"]),
    "id_swap_wrong_rejected": not results["id_swap_wrong_candidate"]["admitted"],
    "t_replay_blocked": all(
        results["t_world_replay_guards"][k]["raised"]
        for k in ("same_content_new_label", "relabeled_same_arrays", "reuse_after_reject")
    ),
    "positive_holds": results["positive"]["admitted"],
    "hard_default_honest": results["hard_projection_vs_gls"]["default_matches_hard"]
    and results["hard_projection_vs_gls"]["gls_diagnostic_only"]
    and (not results["hard_projection_vs_gls"]["diagnostic_admitted"]),
    "mutations_3_of_3": results["mutations_caught"] == "3/3",
    "nonempty_wrong_zero": results["nonempty_wrong_mechanism"]["admissions"] == 0,
}

save("metrics.json", results)
print("DONE", json.dumps(results["verdict_hint"], ensure_ascii=False), flush=True)
print("MUTATIONS", results["mutations_caught"], flush=True)
