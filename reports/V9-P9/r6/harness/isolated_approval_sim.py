"""r6 CPU-isolated approval simulation (P15 item 6).

Builds a throwaway copy of the repository pieces the S1 run entry needs (the
``ainerzero`` sources, the frozen r6 preregistration, the dataset reference and
bytes, the real central RunStore ledger, and a RESEARCH_LOG.md carrying a
**simulated** coordinator approval line for the r6 document SHA256), then drives
the production ``worker.run_worker("train")`` against that copy in subprocesses.

The point of the exercise: prove that with an approval in effect, the central
RunStore anchoring really is the only budget anchor -- a copied run root, a
changed cwd, a copied preregistration, a failed or stopped attempt and a
deleted/replaced ledger can neither reset the arm x seed attempt guard nor mint
a fresh ledger to retry against.  The real ``RESEARCH_LOG.md`` is never written;
no budget or attempt query is mocked.

CPU only: ``runtime.MlxBackend`` is replaced by a numeric substitute, so no MLX
forward/gradient/optimizer step and no capability claim happens here.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]
HARNESS = Path(__file__).resolve().parent
RUNNER = HARNESS / "_r6_sim_runner.py"
OUT = REPO / "reports/V9-P9/r6/evidence/isolated-approval-sim.json"

PHASE1 = REPO / "artifacts/v9/s1/phase1"
R6 = PHASE1 / "r6"
DATASET_DIGEST = "8234f2f382281f355b662f05f0bb576d5efac4853f732ddf2e1cdfeee083ad26"
APPROVAL_SECTION = "## R20261021-P1-stageA-budget"

# scenario -> (working directory inside the copy, needs_approval_log)
SCENARIOS = [
    ("completed", ""),
    ("second-arm", ""),
    ("cross-root", "elsewhere"),
    ("cwd-change", "elsewhere"),
    ("prereg-copy", "elsewhere"),
    ("failed-then-rerun", ""),
    ("stopped-then-rerun", ""),
    ("ledger-deleted", ""),
    ("ledger-replaced", ""),
    ("ledger-foreign", ""),
]


def build_copy(root: Path, *, ledger: str = "fresh") -> dict:
    """Materialise the isolated repository copy and return its identities.

    ``ledger="fresh"`` builds a recognised central RunStore that carries the
    phase-1 preparation experiment and no runs: every attempt/budget query is a
    real RunStore query, only the r1 auxiliary history is absent.  The
    ``ledger="real"`` mode copies the repository ledger byte-for-byte and is
    used by the dedicated phase-cap scenario.
    """
    copy = root / "repo"
    (copy / "artifacts" / "v9" / "s1").mkdir(parents=True)
    ignore = shutil.ignore_patterns("__pycache__")
    shutil.copytree(REPO / "src" / "ainerzero", copy / "src" / "ainerzero", ignore=ignore)
    shutil.copytree(PHASE1 / "r6", copy / "artifacts" / "v9" / "s1" / "phase1" / "r6", ignore=ignore)
    shutil.copy2(PHASE1 / "dataset_ref.json", copy / "artifacts" / "v9" / "s1" / "phase1" / "dataset_ref.json")
    if ledger == "real":
        # The real central RunStore, byte-identical: attempt and budget queries stay real.
        shutil.copy2(
            PHASE1 / "control.sqlite3",
            copy / "artifacts" / "v9" / "s1" / "phase1" / "control.sqlite3",
        )
    else:
        sys.path.insert(0, str(REPO / "src"))
        from ainerzero.v9.experiments.s1 import worker as _worker  # noqa: PLC0415

        fresh = _worker.PrepLedger(copy / "artifacts" / "v9" / "s1" / "phase1" / "control.sqlite3")
        try:
            fresh.store.create_experiment(
                _worker.prep_experiment_manifest(),
                _worker.PREP_REQUEST_ID,
                _worker.PREP_EXPERIMENT_ID,
            )
        finally:
            fresh.close()
    shutil.copytree(
        REPO / "artifacts" / "v9" / "s1" / "datasets" / DATASET_DIGEST,
        copy / "artifacts" / "v9" / "s1" / "datasets" / DATASET_DIGEST,
        ignore=ignore,
    )
    # The frozen document SHA comes from the frozen sidecar, never recomputed
    # against the real tree.
    digest = (R6 / "pre_registration.json.sha256").read_text(encoding="utf-8").split()[0]
    approval_line = f"APPROVED s1-phase1 prereg document_sha256={digest}"
    log = "\n".join(
        [
            "# RESEARCH_LOG (isolated simulation copy)",
            "",
            APPROVAL_SECTION,
            "",
            "- 本文件是 r6 隔离模拟副本：只有这一行批准是模拟写入，真实 RESEARCH_LOG.md 未改。",
            approval_line,
            "",
        ]
    )
    (copy / "RESEARCH_LOG.md").write_text(log, encoding="utf-8")
    (copy / "elsewhere").mkdir(parents=True, exist_ok=True)
    return {
        "root": str(copy),
        "ledger_mode": ledger,
        "frozen_document_sha256": digest,
        "simulated_approval_line": approval_line,
        "central_ledger_sha256_before": _sha(copy / "artifacts/v9/s1/phase1/control.sqlite3"),
        "real_research_log_sha256": _sha(REPO / "RESEARCH_LOG.md"),
    }


def _sha(path: Path) -> str:
    import hashlib

    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def run_scenario(copy: Path, scenario: str, subdir: str) -> dict:
    env = dict(os.environ)
    env["PYTHONPATH"] = str(copy / "src")
    env["S1_R6_SIM_ROOT"] = str(copy)
    env.pop("PYTHONDONTWRITEBYTECODE", None)
    cwd = copy / subdir if subdir else copy
    completed = subprocess.run(
        [sys.executable, str(RUNNER), scenario],
        cwd=str(cwd),
        env=env,
        capture_output=True,
        text=True,
        timeout=900,
    )
    payload = None
    for line in completed.stdout.splitlines():
        if line.startswith("S1_R6_SIM_JSON "):
            payload = json.loads(line[len("S1_R6_SIM_JSON ") :])
    return {
        "scenario": scenario,
        "cwd": str(cwd),
        "returncode": completed.returncode,
        "payload": payload,
        "stderr_tail": completed.stderr[-2000:] if completed.returncode != 0 else "",
    }


def main() -> int:
    started = time.perf_counter()
    real_ledger_before = _sha(PHASE1 / "control.sqlite3")
    real_log_before = _sha(REPO / "RESEARCH_LOG.md")
    tmp = Path(tempfile.mkdtemp(prefix="s1-r6-approval-sim-"))
    identities = build_copy(tmp)
    copy = Path(identities["root"])
    results = []
    for scenario, subdir in SCENARIOS:
        results.append(run_scenario(copy, scenario, subdir))
    by_name = {row["scenario"]: row for row in results}

    # A second, byte-identical copy of the real central ledger documents what
    # the anchored phase total does with the r1 auxiliary history in place.
    real_tmp = Path(tempfile.mkdtemp(prefix="s1-r6-real-ledger-"))
    real_identities = build_copy(real_tmp, ledger="real")
    real_copy = Path(real_identities["root"])
    real_result = run_scenario(real_copy, "real-ledger-phase-cap", "")
    results.append(real_result)
    by_name["real-ledger-phase-cap"] = real_result

    completed = by_name["completed"]["payload"] or {}
    completed_rows = [row for row in completed.get("ledger_rows", []) if row.get("arm_id")]
    arm2 = [row for row in completed_rows if row["arm_id"] == "arm2" and row["seed"] == 0]

    evidence = {
        "schema": "ainerzero.v9.s1.r6.isolated_approval_sim.v1",
        "cpu_only": True,
        "mlx_forward_or_training": False,
        "isolated_copy": identities,
        "central_ledger_sha256_after": _sha(copy / "artifacts/v9/s1/phase1/control.sqlite3"),
        "real_central_ledger_untouched": real_ledger_before == _sha(PHASE1 / "control.sqlite3"),
        "real_research_log_untouched": real_log_before == _sha(REPO / "RESEARCH_LOG.md"),
        "real_ledger_copy": real_identities,
        "scenarios": results,
        "checks": {
            "approval_effective_and_run_completed": completed.get("report_status") == "completed"
            and len(arm2) == 1
            and arm2[0]["state"] == "completed"
            and arm2[0]["has_train_receipt"],
            "registered_updates_match_frozen": bool(arm2)
            and arm2[0]["updates"] == 3510
            and arm2[0]["reserved_optimizer_steps"] == 3510,
            "cross_root_refused": (by_name["cross-root"]["payload"] or {}).get("refused_stage")
            == "output_root_not_canonical",
            "cwd_change_rerun_refused": (by_name["cwd-change"]["payload"] or {}).get("refused_stage")
            == "already_attempted",
            "prereg_copy_refused_without_new_ledger": (
                (by_name["prereg-copy"]["payload"] or {}).get("refused_stage")
                == "output_root_not_canonical"
                and (by_name["prereg-copy"]["payload"] or {}).get("forged_ledger_created") is False
            ),
            "failed_attempt_then_rerun_refused": (
                (by_name["failed-then-rerun"]["payload"] or {}).get("first_status") == "failed"
                and (by_name["failed-then-rerun"]["payload"] or {}).get("second_refused_stage")
                == "already_attempted"
            ),
            "stopped_attempt_then_rerun_refused": (
                (by_name["stopped-then-rerun"]["payload"] or {}).get("first_status") == "stopped"
                and (by_name["stopped-then-rerun"]["payload"] or {}).get("second_refused_stage")
                == "already_attempted"
            ),
            "deleted_ledger_fails_closed": (
                (by_name["ledger-deleted"]["payload"] or {}).get("refused_stage")
                == "central_ledger_missing"
                and (by_name["ledger-deleted"]["payload"] or {}).get("ledger_recreated") is False
            ),
            "replaced_ledger_fails_closed": (
                (by_name["ledger-replaced"]["payload"] or {}).get("refused_stage")
                == "central_ledger_unreadable"
                and (by_name["ledger-replaced"]["payload"] or {}).get("ledger_bytes_unchanged") is True
            ),
            "foreign_ledger_fails_closed": (by_name["ledger-foreign"]["payload"] or {}).get(
                "refused_stage"
            )
            == "central_ledger_unrecognized",
            "second_arm_seed_still_allowed": (by_name["second-arm"]["payload"] or {}).get(
                "report_status"
            )
            == "completed",
            "real_ledger_phase_cap_finding": (
                (by_name["real-ledger-phase-cap"]["payload"] or {}).get("refused_stage")
                == "phase_budget_exceeded"
            ),
        },
        "elapsed_seconds": time.perf_counter() - started,
        "limitations": [
            "numeric CPU substitute; no MLX forward/gradient/training and no capability claim",
            "the main copy's central ledger is a fresh recognised RunStore carrying only the "
            "phase-1 preparation experiment; the r1 auxiliary history is reproduced byte-for-byte "
            "in the second copy and drives the real-ledger-phase-cap scenario",
            "the approval line exists only inside the isolated copy; the real RESEARCH_LOG.md is untouched",
            "a 3510-update run with a substitute backend proves the control flow and the ledger "
            "accounting, not any scientific metric",
        ],
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(evidence, ensure_ascii=False, sort_keys=True, indent=1) + "\n", encoding="utf-8")
    print(json.dumps(evidence["checks"], indent=1))
    print("wrote", OUT)
    print("elapsed", round(evidence["elapsed_seconds"], 2), "s")
    return 0 if all(evidence["checks"].values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
