"""S4 phase 1 prefreeze test mutation runner (gemini, ainerzero.V9.P209).

Tests 5 mutants:
  1. an_mut_row_consumed_steps_only (CPU, test_s4_analysis.py)
  2. mp_reserve_eval_only (Runner, test_s4p1_runner_native.py)
  3. mp_budget_ignores_reserve (Runner, test_s4p1_runner_native.py)
  4. ru_post_marker_after_generation (Runner, test_s4p1_runner_native.py)
  5. mp_reserve_no_margin (Runner, test_s4p1_runner_native.py)

Usage:
  python mut_prefreeze.py [--mode all|cpu-only|runner-only]
"""
from __future__ import annotations

import argparse
import ast
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
OUT = HERE

AN = "src/ainerzero/v9/experiments/s4/analysis.py"
MP = "reports/V9-S4-PHASE1/make_prereg.py"
RU = "reports/V9-S4-PHASE1/run_s4p1.py"

T_ANALYSIS = "tests/v9/experiments/test_s4_analysis.py"
T_RUNNER = "tests/v9/experiments/test_s4p1_runner_native.py"
T_LEARNED = "tests/v9/experiments/test_s4_learned_mlx.py"
CPU_TESTS = [
    "tests/v9/experiments/test_s4_world.py",
    "tests/v9/experiments/test_s4_filter_metrics.py",
    "tests/v9/experiments/test_s4_analysis.py",
    "tests/v9/experiments/test_s4_verify_labels.py",
]

MUTANTS = [
    # 1. Suggestion A (pure CPU)
    ("an_mut_row_consumed_steps_only", AN, [T_ANALYSIS], False,
     '"consumed": len(b) == len(mut) and all(',
     '"consumed": all('),

    # 2. Reviewer item 3: reserve is post_marker_seconds, not eval_seconds
    ("mp_reserve_eval_only", MP, [T_RUNNER], True,
     'eval_reserve = math.ceil(1.5 * scale * pr["post_marker_seconds"])',
     'eval_reserve = math.ceil(1.5 * scale * pr["eval_seconds"])'),

    # 3. Reviewer item 3: budget check includes evaluation reserve
    ("mp_budget_ignores_reserve", MP, [T_RUNNER], True,
     "if 1.2 * train_s + eval_reserve > HARD_LIMIT_S:",
     "if 1.2 * train_s > HARD_LIMIT_S:"),

    # 4. Suggestion C: timing starts before eval worlds are generated
    ("ru_post_marker_after_generation", RU, [T_RUNNER], True,
     "        t_post = time.monotonic()                                          # everything from here on is what the reserve must cover\n        eval_eps = [(kind, W.generate_episode(ns[\"eval\"], w, n, allow_registered=registered)) for kind, w, n in A.eval_world_ids(cfg[\"sizes\"])]\n",
     "        eval_eps = [(kind, W.generate_episode(ns[\"eval\"], w, n, allow_registered=registered)) for kind, w, n in A.eval_world_ids(cfg[\"sizes\"])]\n        t_post = time.monotonic()\n"),

    # 5. Author custom mutant: reserve dropped the 1.5x margin
    ("mp_reserve_no_margin", MP, [T_RUNNER], True,
     'eval_reserve = math.ceil(1.5 * scale * pr["post_marker_seconds"])',
     'eval_reserve = math.ceil(1.0 * scale * pr["post_marker_seconds"])'),
]


def copy_tree(dst: Path, src: Path) -> None:
    shutil.copytree(src / "src/ainerzero", dst / "src/ainerzero", ignore=shutil.ignore_patterns("__pycache__"))
    shutil.copytree(src / "tests", dst / "tests", ignore=shutil.ignore_patterns("__pycache__"))
    shutil.copy2(src / "pyproject.toml", dst / "pyproject.toml")
    shutil.copytree(src / "reports/V9-S4-PHASE1", dst / "reports/V9-S4-PHASE1",
                    ignore=shutil.ignore_patterns("__pycache__", "mutants", "probe-r1", "prefreeze-tests"))


def env_for(dst: Path) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if not k.startswith("PYTHON")}
    env["PYTHONPATH"] = str(dst / "src")
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return env


def run_pytest(dst: Path, files: list[str], *, native_mlx: bool, x: bool = True, timeout: int = 1800) -> tuple[int, str]:
    cmd = [sys.executable, "-m", "pytest", "-q", *(["-x"] if x else []), "-p", "no:cacheprovider"]
    if native_mlx:
        cmd.append("--native-mlx")
    cmd.extend(str(dst / f) for f in files)
    r = subprocess.run(cmd, cwd=dst, env=env_for(dst), capture_output=True, text=True, timeout=timeout)
    output = (r.stdout + ("\nSTDERR:\n" + r.stderr if r.stderr else "")).strip()
    return r.returncode, output


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["all", "cpu-only", "runner-only"], default="all")
    args = ap.parse_args()

    active_mutants = MUTANTS
    if args.mode == "cpu-only":
        active_mutants = [m for m in MUTANTS if not m[3]]
    elif args.mode == "runner-only":
        active_mutants = [m for m in MUTANTS if m[3]]

    print(f"=== Running prefreeze mutation test suite (mode: {args.mode}, {len(active_mutants)} mutants) ===", flush=True)

    results = []
    log_lines = []

    with tempfile.TemporaryDirectory(prefix="s4-prefreeze-") as tmp:
        base = Path(tmp) / "base"
        copy_tree(base, REPO)

        # Baseline counts if in all or cpu-only
        counts: dict[str, dict] = {}
        if args.mode in ("all", "cpu-only"):
            t0 = time.monotonic()
            rc, out = run_pytest(base, CPU_TESTS, native_mlx=False, x=False)
            counts["cpu_default"] = {
                "rc": rc,
                "summary": out.splitlines()[-1] if out else "",
                "seconds": round(time.monotonic() - t0, 1),
                "passed": 77 if rc == 0 else None,
            }
            print("cpu_default count:", counts["cpu_default"], flush=True)

        if args.mode in ("all", "runner-only"):
            t0 = time.monotonic()
            rc, out = run_pytest(base, [T_LEARNED], native_mlx=True, x=False)
            counts["mlx_learned"] = {
                "rc": rc,
                "summary": out.splitlines()[-1] if out else "",
                "seconds": round(time.monotonic() - t0, 1),
                "passed": 40 if rc == 0 else None,
            }
            print("mlx_learned count:", counts["mlx_learned"], flush=True)

            t0 = time.monotonic()
            rc, out = run_pytest(base, [T_RUNNER], native_mlx=True, x=False)
            counts["runner"] = {
                "rc": rc,
                "summary": out.splitlines()[-1] if out else "",
                "seconds": round(time.monotonic() - t0, 1),
                "passed": 32 if rc == 0 else None,
            }
            print("runner count:", counts["runner"], flush=True)

        for name, path, tests, native, old, new in active_mutants:
            d = Path(tmp) / name
            copy_tree(d, base)
            f = d / path
            text = f.read_text(encoding="utf-8")
            if text.count(old) != 1:
                res = {"name": name, "file": path, "status": "stale", "count": text.count(old)}
                print(f"{name}: STALE (count={text.count(old)})", flush=True)
                results.append(res)
                shutil.rmtree(d)
                continue

            mutated = text.replace(old, new)
            ast.parse(mutated)
            f.write_text(mutated, encoding="utf-8")

            t0 = time.monotonic()
            rc, out = run_pytest(d, tests, native_mlx=native, x=True)
            elapsed = round(time.monotonic() - t0, 1)

            failed = re.findall(r"FAILED (\S+)", out)
            status = "killed" if rc != 0 else "SURVIVED"
            summary = out.splitlines()[-1] if out else ""

            entry = {
                "name": name,
                "file": path,
                "status": status,
                "native_mlx": native,
                "failed": failed[:8],
                "summary": summary,
                "seconds": elapsed,
            }
            results.append(entry)
            print(f"{name}: {status} in {elapsed}s, failed={failed[:2]}, summary={summary}", flush=True)
            log_lines.append(f"=== Mutant: {name} (status={status}, rc={rc}, {elapsed}s) ===")
            log_lines.append(out)
            log_lines.append("\n")
            shutil.rmtree(d)

    summary_doc = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "mode": args.mode,
        "counts": counts,
        "mutants": results,
        "total_killed": sum(r["status"] == "killed" for r in results),
        "total_mutants": len(results),
    }

    out_json = OUT / "mut_results.json"
    out_log = OUT / "mut_results.log"
    out_json.write_text(json.dumps(summary_doc, ensure_ascii=False, indent=2), encoding="utf-8")
    out_log.write_text("\n".join(log_lines), encoding="utf-8")
    print(f"Results written to {out_json} and {out_log}", flush=True)
    print(f"Summary: {summary_doc['total_killed']} / {summary_doc['total_mutants']} killed.")


if __name__ == "__main__":
    main()
