#!/usr/bin/env python3
"""Real CLI entry: verify / train (no approval) / eval (175) — CPU only, no MLX.

Mirrors P30's proven invocation:
  verify --output-root .../r11
  train  --output-root .../phase1 --prereg .../r11/pre_registration.json
  eval   via isolated worker harness (same as P30 entry_eval_check) so the
         production control.sqlite3 main DB is not opened for a binding miss.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

REPO = Path("/Users/mac/AinerWorkFlow/AinerZero")
OUT = REPO / "reports/V9-P31/evidence"
LOG = REPO / "reports/V9-P31/logs"
OUT.mkdir(parents=True, exist_ok=True)
LOG.mkdir(parents=True, exist_ok=True)
os.chdir(REPO)

PY = str(REPO / ".venv/bin/python")
R11 = "artifacts/v9/s1/phase1/r11"
CANON = "artifacts/v9/s1/phase1"
PREREG = f"{R11}/pre_registration.json"


def run(args: list[str]) -> dict:
    proc = subprocess.run(
        [PY, "-m", "ainerzero.cli", "s1-phase1", *args],
        cwd=REPO,
        capture_output=True,
        text=True,
    )
    stdout = proc.stdout
    stderr = proc.stderr
    parsed = None
    for chunk in (stdout, stderr):
        chunk = chunk.strip()
        if not chunk:
            continue
        try:
            parsed = json.loads(chunk)
        except Exception:
            start = chunk.find("{")
            end = chunk.rfind("}")
            if start >= 0 and end > start:
                try:
                    parsed = json.loads(chunk[start : end + 1])
                except Exception:
                    pass
    return {
        "exit_code": proc.returncode,
        "stdout_tail": stdout[-4000:],
        "stderr_tail": stderr[-2000:],
        "report": parsed,
    }


def main() -> int:
    results = {"ok": True, "modes": {}}

    def record(name, passed, detail):
        results["modes"][name] = {"passed": bool(passed), **detail}
        if not passed:
            results["ok"] = False
        print(f"[{'PASS' if passed else 'FAIL'}] {name}")

    verify = run(["--mode", "verify", "--output-root", R11])
    (LOG / "entry-verify.json").write_text(json.dumps(verify, indent=2, ensure_ascii=False) + "\n")
    vrep = verify.get("report") or {}
    record(
        "verify",
        verify["exit_code"] == 0 and vrep.get("status") == "completed",
        {
            "exit_code": verify["exit_code"],
            "status": vrep.get("status"),
            "approval_approved": (vrep.get("approval") or {}).get("approved"),
            "document_sha": vrep.get("preregistration_sha256"),
        },
    )

    train = run(
        [
            "--mode",
            "train",
            "--arm",
            "arm2",
            "--seed",
            "0",
            "--output-root",
            CANON,
            "--prereg",
            PREREG,
        ]
    )
    (LOG / "entry-train.json").write_text(json.dumps(train, indent=2, ensure_ascii=False) + "\n")
    trep = train.get("report") or {}
    record(
        "train_refused_without_approval",
        train["exit_code"] == 3
        and (
            trep.get("refused_stage") == "preregistration_not_approved"
            or trep.get("stage") == "preregistration_not_approved"
        ),
        {
            "exit_code": train["exit_code"],
            "status": trep.get("status"),
            "refused_stage": trep.get("refused_stage") or trep.get("stage"),
            "approval_approved": (trep.get("approval") or {}).get("approved"),
        },
    )

    # Eval: reuse P30's isolated entry_eval_check (real worker entry, temp host)
    # so we do not reopen production control.sqlite3 just to hit EvalBindingError.
    ev_proc = subprocess.run(
        [PY, str(REPO / "reports/V9-P9/r11/harness/entry_eval_check.py")],
        cwd=REPO,
        capture_output=True,
        text=True,
    )
    ev_out = {
        "exit_code": ev_proc.returncode,
        "stdout": ev_proc.stdout[-6000:],
        "stderr": ev_proc.stderr[-2000:],
    }
    ev_json = None
    try:
        ev_json = json.loads(ev_proc.stdout.strip())
    except Exception:
        start = ev_proc.stdout.find("{")
        end = ev_proc.stdout.rfind("}")
        if start >= 0 and end > start:
            try:
                ev_json = json.loads(ev_proc.stdout[start : end + 1])
            except Exception:
                ev_json = None
    (LOG / "entry-eval.json").write_text(
        json.dumps({"proc": ev_out, "parsed": ev_json}, indent=2, ensure_ascii=False, default=str) + "\n"
    )

    results_block = (ev_json or {}).get("results") or {}
    e175 = results_block.get("eval_batches_175") or {}
    e48 = results_block.get("eval_batches_48_control") or {}
    err = str(e175.get("error") or e175.get("message") or "")
    stage = e175.get("refused_stage") or e175.get("stage")
    passed_budget = bool((ev_json or {}).get("passed_budget_gate_175")) or "EvalBinding" in err
    not_batches = stage != "eval_call_budget_exceeded" and "eval_call_budget" not in err
    control_ok = e48.get("refused_stage") == "eval_call_budget_exceeded"
    record(
        "eval_175_not_refused_for_batches",
        ev_proc.returncode == 0 and not_batches and passed_budget and "EvalBinding" in err and control_ok,
        {
            "exit_code": ev_proc.returncode,
            "stage": stage,
            "error": err[:400],
            "experiment_id": e175.get("experiment_id"),
            "passed_budget_gate_175": (ev_json or {}).get("passed_budget_gate_175"),
            "control_48_refused_stage": e48.get("refused_stage"),
            "checks": (ev_json or {}).get("checks"),
        },
    )

    # Also run CLI eval against canonical root (read-only binding miss) for "真实入口"
    cli_eval = run(
        [
            "--mode",
            "eval",
            "--arm",
            "arm2",
            "--seed",
            "0",
            "--output-root",
            CANON,
            "--prereg",
            PREREG,
        ]
    )
    (LOG / "entry-eval-cli.json").write_text(json.dumps(cli_eval, indent=2, ensure_ascii=False) + "\n")
    crep = cli_eval.get("report") or {}
    cstage = crep.get("refused_stage") or crep.get("stage")
    cerr = str(crep.get("error") or crep.get("message") or "")
    record(
        "eval_cli_canonical_not_batches_gate",
        cstage != "eval_call_budget_exceeded" and "eval_call_budget" not in cerr,
        {
            "exit_code": cli_eval["exit_code"],
            "status": crep.get("status"),
            "stage": cstage,
            "error": cerr[:400],
            "experiment_id": crep.get("experiment_id"),
        },
    )

    (OUT / "entry_modes.json").write_text(json.dumps(results, indent=2, ensure_ascii=False) + "\n")
    print(json.dumps({"ok": results["ok"]}, indent=2))
    return 0 if results["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
