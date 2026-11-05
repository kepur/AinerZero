#!/usr/bin/env python3
"""P24 guard-broken controls: mutate ONE guard in an isolated source copy and
show the same independent probe turns red.

The real source tree is never modified: each case gets a throw-away copy under
a temp directory.  Only the guard/condition named for that F-item is changed.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path("/Users/mac/AinerWorkFlow/AinerZero")
HARNESS = REPO / "reports" / "V9-P24" / "harness" / "probe_core.py"
OUT = REPO / "reports" / "V9-P24" / "evidence" / "guard-broken-controls.json"
TESTS = REPO / "tests" / "v9" / "experiments"

# (case, relative file, exact old text, replacement, one-line description)
MUTATIONS = [
    (
        "f1",
        "src/ainerzero/v9/experiments/s1/completion.py",
        '        if event["expired"]:\n'
        "            raise CompletionDeadlineExceeded(\n"
        '                f"phase {phase}: elapsed {elapsed:.6f}s exceeds the frozen deadline "\n'
        '                f"{self.deadline_seconds:.6f}s"\n'
        "            )\n",
        "        if False:  # P24 mutation: deadline guard disabled\n"
        "            raise CompletionDeadlineExceeded('disabled')\n",
        "disable the completion-protocol deadline refusal",
    ),
    (
        "f2",
        "src/ainerzero/v9/experiments/s1/worker.py",
        'ACTIVE_STATES = frozenset(\n'
        "    {\n"
        '        "created",\n'
        '        "initializing",\n'
        '        "collecting",\n'
        '        "training",\n'
        '        "validating",\n'
        '        "pausing",\n'
        '        "paused",\n'
        '        "stopping",\n'
        "    }\n"
        ")\n",
        'ACTIVE_STATES = frozenset(\n'
        "    {\n"
        '        "created",\n'
        '        "initializing",\n'
        '        "training",\n'
        '        "pausing",\n'
        '        "paused",\n'
        "    }\n"
        ")\n",
        "restore the r7 ACTIVE_STATES that omits collecting/validating/stopping",
    ),
    (
        "f3",
        "src/ainerzero/v9/experiments/s1/worker.py",
        "                ledger.reserve(\n"
        "                    active_run,\n"
        "                    active_seconds=min(0.5 * d_budget, max(0.0, reserved_now)),\n"
        "                )\n",
        "                ledger.reserve(\n"
        "                    active_run,\n"
        "                    active_seconds=max(5.0, min(0.5 * d_budget, max(0.0, reserved_now))),\n"
        "                )\n",
        "reintroduce the 5 s reservation floor that exceeds the 2 s D budget",
    ),
    (
        "f4",
        "src/ainerzero/v9/experiments/s1/worker.py",
        '        if arm_id == "arm1":\n'
        "            attempted.append(run)\n"
        "            continue\n",
        '        if False and arm_id == "arm1":  # P24 mutation: product row invisible\n'
        "            attempted.append(run)\n"
        "            continue\n",
        "make the one-D guard ignore the arm_id row the product writes",
    ),
    (
        "f5",
        "src/ainerzero/v9/experiments/s1/worker.py",
        "    value = float(value)\n"
        "    if not math.isfinite(value):\n"
        '        raise LedgerStateInvalid(f"run {run_id} has a non-finite reserved_active_seconds {value!r}")\n'
        "    if value < 0:\n"
        '        raise LedgerStateInvalid(f"run {run_id} has a negative reserved_active_seconds {value!r}")\n'
        "    return value\n",
        "    return max(0.0, float(value) or 0.0)  # P24 mutation: silent-zero normalisation\n",
        "normalise the raw reservation with max(0.0, value or 0.0) before validation",
    ),
    (
        "f6",
        "src/ainerzero/v9/experiments/s1/identity.py",
        "    if recomputed_digest != registered_digest:\n"
        "        raise DIdentityError(\n"
        '            "the A2 manifest self digest does not match the registered digest: "\n'
        '            f"{recomputed_digest} != {registered_digest}"\n'
        "        )\n",
        "    if False:  # P24 mutation: digest compared nowhere\n"
        "        raise DIdentityError('disabled')\n",
        "stop comparing the recomputed A2 manifest digest with the registered one",
    ),
    (
        "f7",
        "src/ainerzero/v9/experiments/s1/identity.py",
        "from . import spec\n",
        "from . import spec\nfrom . import arms  # P24 mutation: eager MLX/loader import\n",
        "add a module-level arms import (which imports MLX) to the identity module",
    ),
    (
        "f8",
        "src/ainerzero/v9/experiments/s1/worker.py",
        "                # This is an internal seam; the CLI never exposes it.\n"
        "                backend=backend,\n",
        "                # This is an internal seam; the CLI never exposes it.\n"
        "                backend=None,  # P24 mutation: forward the CPU double dropped\n",
        "drop the public train branch's forwarding of the CPU test double",
    ),
]


def _run_probe(case: str, p24_src: Path, extra_env: dict | None = None) -> dict:
    env = dict(os.environ)
    paths = [str(p24_src), str(TESTS)]
    if extra_env and extra_env.get("shim"):
        paths.insert(0, extra_env["shim"])
    env["PYTHONPATH"] = os.pathsep.join(paths)
    env["P24_SRC"] = str(p24_src)
    proc = subprocess.run(
        [sys.executable, str(HARNESS), "--case", case],
        capture_output=True, text=True, env=env, cwd=str(REPO),
    )
    last = (proc.stdout.strip().splitlines() or [""])[-1]
    try:
        payload = json.loads(last)
    except Exception:  # noqa: BLE001
        payload = {
            "passed": False,
            "parse_error": True,
            "stdout_tail": proc.stdout[-1000:],
            "stderr_tail": proc.stderr[-1000:],
        }
    payload["returncode"] = proc.returncode
    return payload


def _mutated_copy(rel: str, old: str, new: str) -> Path:
    tmp = Path(tempfile.mkdtemp(prefix="p24-mutant-"))
    dst = tmp / "src"
    shutil.copytree(REPO / "src" / "ainerzero", dst / "ainerzero")
    target = tmp / rel
    text = target.read_text(encoding="utf-8")
    if text.count(old) != 1:
        raise SystemExit(f"mutation anchor not unique/found in {rel}: count={text.count(old)}")
    target.write_text(text.replace(old, new), encoding="utf-8")
    return tmp / "src"


def main() -> int:
    rows = []
    for case, rel, old, new, description in MUTATIONS:
        baseline = _run_probe(case, REPO / "src")
        mutant_src = _mutated_copy(rel, old, new)
        extra = None
        if case == "f8":
            shim = Path(tempfile.mkdtemp(prefix="p24-shim-")) / "shim"
            (shim / "mlx").mkdir(parents=True)
            (shim / "mlx" / "__init__.py").write_text(
                "raise ImportError('P24 mutation probe: MLX unavailable')\n", encoding="utf-8"
            )
            extra = {"shim": str(shim)}
        mutated = _run_probe(case, mutant_src, extra)
        rows.append(
            {
                "case": case,
                "description": description,
                "file": rel,
                "baseline_passed": baseline.get("passed") is True,
                "mutated_passed": mutated.get("passed") is True,
                "control_is_red": baseline.get("passed") is True and mutated.get("passed") is not True,
                "baseline": baseline,
                "mutated": mutated,
            }
        )
        print(f"{case}: baseline={baseline.get('passed')} mutated={mutated.get('passed')} "
              f"red={rows[-1]['control_is_red']}  ({description})")
    payload = {
        "tool": "reports/V9-P24/harness/run_mutations.py",
        "rule": "one isolated copy per case; only the named guard/condition is changed",
        "rows": rows,
        "all_controls_red": all(row["control_is_red"] for row in rows),
    }
    OUT.write_text(json.dumps(payload, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"all_controls_red": payload["all_controls_red"],
                      "rows": len(rows), "out": str(OUT)}, indent=1))
    return 0 if payload["all_controls_red"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
