#!/usr/bin/env python3
"""Independent verifier for ainerzero.V9.T8 (RLT frame dropping reference implementation).

Role: verifier (not the author). Read-only on the verified module and its tests;
this script only writes under reports/V-V9-T8/. CPU only, no MLX/torch/GPU.

The oracle below is written from the task specification / implementation docstring
(ARCHITECTURE_V9 §4 item 10, Eq. 10: a patch is merged when
``||p_t - p_{t-1}||_inf < tau``; frame 0 is always kept; runs are length encoded),
**not** from the author's test fixtures. It uses plain Python loops over
``ndarray.tolist()`` so it does not reuse the module's vectorised logic.

Usage:
  python3 -I reports/V-V9-T8/verify_t9.py --verify   # independent verification, exit 0/1
  python3 -I reports/V-V9-T8/verify_t9.py --mutate   # deliberate-break controls, exit 0/1
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import importlib.util
import json
import math
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[2]
SRC = REPO / "src"
IMPL = SRC / "ainerzero" / "v9" / "tokenization" / "rlt.py"
TESTS = REPO / "tests" / "v9" / "tokenization" / "test_rlt.py"
OUT = REPO / "reports" / "V-V9-T8"
IMPL_SHA_EXPECTED = "6514aa80a66ab1ff3f92bcc8dce3a59c3ea0da9c2d49bbadea675afa63526167"
TESTS_SHA_EXPECTED = "58957951c50e008b453059da5da2c4e505fc555140f879f87a2c416593c69314"


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_module_from(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


# ---------------------------------------------------------------------------
# Independent oracle (pure Python loops; no reuse of module internals)
# ---------------------------------------------------------------------------
def oracle(video: np.ndarray, tau: float) -> dict:
    T, ph, pw, D = video.shape
    data = video.tolist()
    kept: dict[tuple[int, int], list[int]] = {}
    for h in range(ph):
        for w in range(pw):
            frames = [0]
            for t in range(1, T):
                diff = max(abs(data[t][h][w][k] - data[t - 1][h][w][k]) for k in range(D))
                if diff >= tau:
                    frames.append(t)
            kept[(h, w)] = frames

    retained, run_lengths, positions = [], [], []
    for h in range(ph):
        for w in range(pw):
            frames = kept[(h, w)]
            for i, t in enumerate(frames):
                end = frames[i + 1] if i + 1 < len(frames) else T
                run_lengths.append(end - t)
                retained.append(list(data[t][h][w]))
                positions.append([h, w])

    restoration = [
        [[[float(data[t][h][w][k]) for k in range(D)] for w in range(pw)] for h in range(ph)] for t in range(T)
    ]
    for h in range(ph):
        for w in range(pw):
            frames = kept[(h, w)]
            for i, t in enumerate(frames):
                end = frames[i + 1] if i + 1 < len(frames) else T
                for tt in range(t, end):
                    restoration[tt][h][w] = list(data[t][h][w])

    K = len(retained)
    return {
        "retained": retained,
        "run_lengths": run_lengths,
        "positions": positions,
        "restoration": restoration,
        "K": K,
        "retention_rate": K / (T * ph * pw),
        "kept": kept,
    }


# ---------------------------------------------------------------------------
# Adversarial cases (>= 6 real adversarial; all non-trivial)
# ---------------------------------------------------------------------------
def case(name: str, desc: str, video: np.ndarray, tau: float, expect_error: type | None = None) -> dict:
    return {"name": name, "desc": desc, "video": video, "tau": tau, "expect_error": expect_error}


def build_cases() -> list[dict]:
    cases = []

    # 1. periodic flicker above tau: every frame must be kept (must NOT be dropped as "still")
    flicker_hi = np.zeros((6, 2, 2, 3), dtype=np.float64)
    flicker_hi[1::2] = 0.6
    cases.append(case("periodic_flicker_above_tau", "alternating +0.6 every frame with tau=0.5: everything is motion", flicker_hi, 0.5))

    # 2. periodic flicker below tau: everything after frame 0 merges into one token per position
    flicker_lo = np.zeros((6, 2, 2, 3), dtype=np.float64)
    flicker_lo[1::2] = 0.49
    cases.append(case("periodic_flicker_below_tau", "alternating +0.49 < tau=0.5: must merge after frame 0", flicker_lo, 0.5))

    # 3. single pixel change at one spatial position, returning to base one frame later
    single = np.zeros((5, 3, 3, 2), dtype=np.float64)
    single[3, 1, 2, :] = 0.7
    cases.append(case("single_pixel_change", "one 1x1 patch changes by 0.7 for one frame only", single, 0.5))

    # 4. tau exactly at the boundary: diff == tau must be KEPT (merge rule is strict < tau)
    boundary_equal = np.zeros((3, 1, 2, 1), dtype=np.float64)
    boundary_equal[1, :, :, 0] = 0.5
    boundary_equal[2, :, :, 0] = 0.5
    cases.append(case("tau_boundary_equal", "diff exactly == tau: kept, not merged", boundary_equal, 0.5))

    # 5. tau just below the boundary: diff < tau must be merged
    boundary_below = np.zeros((3, 1, 2, 1), dtype=np.float64)
    boundary_below[1, :, :, 0] = 0.5 - 1e-9
    boundary_below[2, :, :, 0] = 0.5 - 1e-9
    cases.append(case("tau_boundary_below", "diff = tau - 1e-9 < tau: must merge", boundary_below, 0.5))

    # 6. super long static segment: one token per position for 1000 frames
    cases.append(case("long_static_1000", "T=1000 identical frames, tau=0.1: rate must be 1/T per position", np.zeros((1000, 2, 3, 4), dtype=np.float64), 0.1))

    # 7. first-frame / last-frame changes
    first_last = np.zeros((4, 2, 2, 1), dtype=np.float64)
    first_last[0, 0, 0, 0] = 0.3
    first_last[1:, 0, 0, 0] = 0.8  # diff 0.5 == tau from frame 0 -> frame 1 kept
    first_last[3, 1, 1, 0] = 0.8  # last-frame-only change at another position
    cases.append(case("first_last_frame_change", "first frame unique and last frame changes; both edges must be kept correctly", first_last, 0.5))

    # 8. T=1 edge: no diff exists, everything kept exactly once
    cases.append(case("single_frame_T1", "T=1: no frames to merge", np.arange(4, dtype=np.float64).reshape(1, 2, 2, 1), 0.5))

    # 9. tau=0: no frame dropping at all (diff >= 0 always true, including equal frames)
    tau_zero = np.zeros((4, 2, 2, 1), dtype=np.float64)
    tau_zero[2, 0, 0, 0] = 1.0
    cases.append(case("tau_zero_no_dropping", "tau=0 must retain every (frame, position) token", tau_zero, 0.0))

    # 10. ragged batch: API takes a single [T,H,W,D] tensor; mixed-length batches must fail closed
    batch = [np.zeros((3, 2, 2, 1), dtype=np.float64), np.zeros((5, 2, 2, 1), dtype=np.float64)]
    cases.append(case("mixed_length_batch_fail_closed", "list of T=3 and T=5 chunks: must not silently produce wrong output", batch, 0.5, expect_error=AttributeError))

    # 11. invalid tau: negative threshold must be rejected, not silently accepted
    cases.append(case("negative_tau_rejected", "tau=-0.1 must raise AssertionError", np.zeros((3, 1, 1, 1), dtype=np.float64), -0.1, expect_error=AssertionError))
    return cases


# ---------------------------------------------------------------------------
# Verification of one module against the oracle
# ---------------------------------------------------------------------------
CASE_METRICS: list[dict] = []


def verify_module(module, cases, *, label: str = "impl") -> list[dict]:
    results = []

    def fail(case_name: str, check: str, detail) -> None:
        results.append({"label": label, "case": case_name, "check": check, "ok": False, "detail": str(detail)})

    def ok(case_name: str, check: str, detail=None) -> None:
        results.append({"label": label, "case": case_name, "check": check, "ok": True, "detail": str(detail) if detail is not None else None})

    for item in cases:
        name, video, tau = item["name"], item["video"], item["tau"]
        if isinstance(video, list):  # ragged batch: only error behaviour is defined
            try:
                module.rlt_frame_dropping(video, tau)
                fail(name, "expected_fail_closed", "ragged batch produced no error")
            except item["expect_error"]:
                ok(name, "expected_fail_closed", f"raised {item['expect_error'].__name__} (API is single-tensor only)")
            except Exception as exc:  # noqa: BLE001
                fail(name, "expected_fail_closed", f"raised unexpected {type(exc).__name__}: {exc}")
            continue
        if item["expect_error"] is not None:
            try:
                module.rlt_frame_dropping(video, tau)
                fail(name, "expected_error", f"expected {item['expect_error'].__name__}, no error raised")
            except item["expect_error"]:
                ok(name, "expected_error", f"raised {item['expect_error'].__name__}")
            except Exception as exc:  # noqa: BLE001
                fail(name, "expected_error", f"raised unexpected {type(exc).__name__}: {exc}")
            continue

        before = video.copy()
        try:
            retained, run_lengths, positions, restoration, rate = module.rlt_frame_dropping(video, tau)
        except Exception as exc:  # noqa: BLE001
            fail(name, "run", f"raised {type(exc).__name__}: {exc}")
            continue
        if not np.array_equal(video, before):
            fail(name, "input_not_mutated", "implementation modified its input tensor")
        ref = oracle(video, tau)
        T, ph, pw, D = video.shape
        total = T * ph * pw

        CASE_METRICS.append({
            "case": name, "desc": item["desc"], "T": T, "ph": ph, "pw": pw, "D": D, "tau": tau,
            "total_tokens": total, "K_impl": int(len(retained)), "K_oracle": ref["K"],
            "retention_rate_impl": float(rate), "retention_rate_oracle": ref["retention_rate"],
            "expected_shape": [T, ph, pw, D],
        })
        if int(len(retained)) != ref["K"]:
            fail(name, "retained_count", f"impl K={len(retained)} oracle K={ref['K']}")
        if int(len(run_lengths)) != ref["K"] or int(len(positions)) != ref["K"]:
            fail(name, "artifact_lengths", f"K mismatch: retained={len(retained)} runs={len(run_lengths)} positions={len(positions)}")
        if list(map(tuple, positions.tolist())) != [tuple(p) for p in ref["positions"]]:
            fail(name, "positions_order", "retained token spatial order differs from oracle row-major order")
        if [list(map(float, row)) for row in retained.tolist()] != ref["retained"]:
            fail(name, "retained_values", "retained feature vectors differ from oracle")
        if [int(x) for x in run_lengths.tolist()] != ref["run_lengths"]:
            fail(name, "run_lengths", "run lengths differ from oracle")
        if not math.isclose(float(rate), ref["retention_rate"], rel_tol=0.0, abs_tol=1e-15):
            fail(name, "retention_rate", f"impl rate={rate!r} oracle={ref['retention_rate']!r}")

        # independent recomputation from the returned artifacts only
        recomputed_k = len(retained)
        recomputed_rate = recomputed_k / total
        if int(recomputed_k) != ref["K"] or abs(recomputed_rate - float(rate)) > 1e-15:
            fail(name, "recompute_from_artifacts", f"K={recomputed_k} rate={recomputed_rate} reported={rate}")
        per_position: dict[tuple[int, int], int] = {}
        for pos, run in zip(positions.tolist(), run_lengths.tolist()):
            key = (int(pos[0]), int(pos[1]))
            per_position[key] = per_position.get(key, 0) + int(run)
        if set(per_position) != {(h, w) for h in range(ph) for w in range(pw)} or any(v != T for v in per_position.values()):
            fail(name, "run_coverage", f"per-position run lengths do not sum to T: {per_position}")

        # reversibility: decode (positions, run_lengths, retained) -> frames + restoration
        decoded_kept: dict[tuple[int, int], list[int]] = {(h, w): [] for h in range(ph) for w in range(pw)}
        cursor: dict[tuple[int, int], int] = {(h, w): 0 for h in range(ph) for w in range(pw)}
        decoded_tokens: dict[tuple[int, int], list[list[float]]] = {(h, w): [] for h in range(ph) for w in range(pw)}
        for pos, run, token in zip(positions.tolist(), run_lengths.tolist(), retained.tolist()):
            key = (int(pos[0]), int(pos[1]))
            decoded_kept[key].append(cursor[key])
            decoded_tokens[key].append(list(map(float, token)))
            cursor[key] += int(run)
        for key in decoded_kept:
            if decoded_kept[key] != ref["kept"][key]:
                fail(name, "reversible_kept_frames", f"{key}: decoded {decoded_kept[key][:6]} != oracle {ref['kept'][key][:6]}")
            if decoded_tokens[key] != [ref["retained"][i] for i in range(ref["K"]) if ref["positions"][i] == list(key)]:
                fail(name, "reversible_token_values", f"{key}: decoded tokens differ")

        # restoration: kept frames exact; merged frames equal the run's kept token; merged diff < tau
        restoration_arr = np.asarray(restoration)
        if restoration_arr.shape != video.shape:
            fail(name, "restoration_shape", f"{restoration_arr.shape} != {video.shape}")
        else:
            for h in range(ph):
                for w in range(pw):
                    frames = ref["kept"][(h, w)]
                    for i, t in enumerate(frames):
                        end = frames[i + 1] if i + 1 < len(frames) else T
                        token = video[t, h, w, :]
                        if not np.array_equal(restoration_arr[t, h, w, :], token):
                            fail(name, "restoration_kept", f"kept ({t},{h},{w}) not exact")
                        for tt in range(t + 1, end):
                            if not np.array_equal(restoration_arr[tt, h, w, :], token):
                                fail(name, "restoration_merged_token", f"merged ({tt},{h},{w}) not filled from token")
                            diff = float(np.max(np.abs(video[tt, h, w, :] - video[tt - 1, h, w, :])))
                            if not diff < tau:
                                fail(name, "merged_diff_lt_tau", f"({tt},{h},{w}) diff={diff} >= tau")
        # determinism: second call is byte-identical
        again = module.rlt_frame_dropping(video.copy(), tau)
        if not (
            np.array_equal(retained, again[0])
            and np.array_equal(run_lengths, again[1])
            and np.array_equal(positions, again[2])
            and np.array_equal(restoration_arr, np.asarray(again[3]))
            and float(rate) == float(again[4])
        ):
            fail(name, "determinism", "two calls with identical input differ")
        if not any(r["case"] == name and r["label"] == label and r["check"] in {
            "retained_count", "artifact_lengths", "retained_values", "run_lengths",
            "retention_rate", "recompute_from_artifacts", "restoration_shape",
        } for r in results):
            ok(name, "all_structural_checks")
    return results


def import_purity() -> dict:
    source = IMPL.read_text(encoding="utf-8")
    tree = ast.parse(source)
    roots = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            roots.add(node.module.split(".")[0])
    code = (
        "import sys; sys.path.insert(0, %r); import ainerzero.v9.tokenization.rlt as m; "
        "print(','.join(sorted({n.split('.')[0] for n in sys.modules if n.split('.')[0] in "
        "('torch','mlx','tensorflow','jax','coremltools')})))" % str(SRC)
    )
    import tempfile

    env = {k: v for k, v in os.environ.items() if k not in {"PYTHONPATH", "PYTHONSTARTUP"}}
    with tempfile.TemporaryDirectory(prefix="v9t9-purity-") as cwd:
        completed = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=False, cwd=cwd, env=env)
    return {
        "ast_import_roots": sorted(roots),
        "ast_ok": roots == {"numpy"},
        "loaded_forbidden_modules": completed.stdout.strip(),
        "import_ok": completed.returncode == 0 and completed.stdout.strip() == "",
        "command": f"{sys.executable} -c '<import ainerzero.v9.tokenization.rlt and scan sys.modules>' (cwd=temp, PYTHONPATH cleared)",
    }


def summarize(results: list[dict]) -> dict:
    failed = [r for r in results if not r["ok"]]
    cases = sorted({r["case"] for r in results})
    return {
        "checks": len(results),
        "failed_checks": len(failed),
        "cases": len(cases),
        "case_names": cases,
        "failures": failed[:20],
        "ok": not failed,
    }


def run_verify() -> int:
    CASE_METRICS.clear()
    impl_sha = sha256_file(IMPL)
    tests_sha = sha256_file(TESTS)
    identity_ok = impl_sha == IMPL_SHA_EXPECTED and tests_sha == TESTS_SHA_EXPECTED
    module = load_module_from(IMPL, "rlt_impl_t9")
    cases = build_cases()
    results = verify_module(module, cases)
    summary = summarize(results)
    purity = import_purity()
    out = {
        "task": "ainerzero.V9.T9",
        "verified_task": "ainerzero.V9.T8",
        "verifier": "deepseek-flash-3tgx",
        "author": "opencode-de3b",
        "verifier_is_author": False,
        "impl_sha256": impl_sha,
        "tests_sha256": tests_sha,
        "identity_matches_author_report": identity_ok,
        "import_purity": purity,
        "results": results,
        "case_metrics": CASE_METRICS,
        "summary": summary,
        "python": sys.version.split()[0],
        "numpy": np.__version__,
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "case-results.json").write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"check": "identity", "ok": identity_ok, "impl_sha256": impl_sha, "tests_sha256": tests_sha}, ensure_ascii=False))
    print(json.dumps({"check": "import_purity", **purity}, ensure_ascii=False))
    for item in results:
        print(json.dumps(item, ensure_ascii=False))
    print(json.dumps({"summary": summary}, ensure_ascii=False))
    exit_ok = identity_ok and summary["ok"] and purity["ast_ok"] and purity["import_ok"]
    return 0 if exit_ok else 1


# ---------------------------------------------------------------------------
# Deliberate-break controls: each mutation MUST turn the verifier red
# ---------------------------------------------------------------------------
MUTATIONS = [
    ("M1-merge-boundary-le", "(diff_max >= tau)", "(diff_max > tau)",
     "tau_boundary_equal", "retained_values"),
    ("M2-retention-denominator", "retention_rate = K / (T * ph * pw)", "retention_rate = K / (T * ph * pw + 1)",
     "long_static_1000", "retention_rate"),
    ("M3-no-restoration-propagation",
     "restoration[t, merged, :] = restoration[t - 1, merged, :]",
     "restoration[t, merged, :] = video_chunks[t, merged, :]",
     "periodic_flicker_below_tau", "restoration_merged_token"),
    ("M4-drop-first-frame", "keep_mask[0] = True", "keep_mask[0] = False",
     "single_frame_T1", "retained_count"),
]


def run_mutations() -> int:
    source = IMPL.read_text(encoding="utf-8")
    cases = build_cases()
    controls = []
    all_red = True
    tmp_root = Path(tempfile.mkdtemp(prefix="v9t9-mutations-"))
    for name, old, new, expected_case, expected_check in MUTATIONS:
        if old not in source:
            controls.append({"mutation": name, "ok": False, "detail": "anchor text not found in implementation"})
            all_red = False
            continue
        mutated = source.replace(old, new)
        path = tmp_root / f"{name}.py"
        path.write_text(mutated, encoding="utf-8")
        try:
            module = load_module_from(path, f"rlt_mut_{name.replace('-', '_')}")
            results = verify_module(module, cases, label=name)
            summary = summarize(results)
            hit = any(
                (not r["ok"]) and r["case"] == expected_case and r["check"] == expected_check for r in results
            )
            any_red = summary["failed_checks"] > 0
            ok = bool(any_red and hit)
            controls.append({
                "mutation": name,
                "sha256": sha256_file(path),
                "ok": ok,
                "turned_red": any_red,
                "failed_checks": summary["failed_checks"],
                "expected_case": expected_case,
                "expected_check": expected_check,
                "expected_hit": hit,
                "sample_failures": summary["failures"][:5],
            })
        except Exception as exc:  # noqa: BLE001
            controls.append({"mutation": name, "ok": False, "detail": f"mutation crashed unexpectedly: {type(exc).__name__}: {exc}"})
        if not controls[-1]["ok"]:
            all_red = False
    result = {
        "task": "ainerzero.V9.T9",
        "mode": "deliberate-break-controls",
        "mutations": MUTATIONS and [m[0] for m in MUTATIONS],
        "controls": controls,
        "all_controls_turned_red": all_red,
        "tmp_root": str(tmp_root),
    }
    (OUT / "mutation-results.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    for control in controls:
        print(json.dumps(control, ensure_ascii=False))
    print(json.dumps({"all_controls_turned_red": all_red}, ensure_ascii=False))
    shutil.rmtree(tmp_root, ignore_errors=True)
    return 0 if all_red else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--verify", action="store_true")
    group.add_argument("--mutate", action="store_true")
    args = parser.parse_args()
    os.environ.setdefault("PYTHONDONTWRITEBYTECODE", "1")
    if args.verify:
        return run_verify()
    return run_mutations()


if __name__ == "__main__":
    sys.exit(main())
