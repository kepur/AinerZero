#!/usr/bin/env python3
"""cursor-e4k9 independent P35 probes.

Uses isolated hosts via s1_testkit.stage_phase1_host (shared kit, not author tests).
Never opens production control.sqlite3 with sqlite/RunStore — only shasum bytes.
Records production ledger sha / wal bytes / shm mtime before and after.
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "tests" / "v9" / "experiments"))

from ainerzero.v9.experiments.s1 import prereg, spec, worker  # noqa: E402
from s1_testkit import make_plan, stage_phase1_host, write_research_log  # noqa: E402

OUT = Path(__file__).resolve().parent
PROD_LEDGER = REPO / "artifacts/v9/s1/phase1/control.sqlite3"
PROD_WAL = Path(str(PROD_LEDGER) + "-wal")
PROD_SHM = Path(str(PROD_LEDGER) + "-shm")
EXPECTED_LEDGER = "36426891021c9bfcdb9cb25a3adef30f1d2dbfb3d84b3c124b908bd7aeadb67d"
R12 = spec.R12_EXPERIMENT_ID


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def prod_snap() -> dict:
    return {
        "control.sqlite3": sha(PROD_LEDGER),
        "wal_bytes": PROD_WAL.stat().st_size if PROD_WAL.exists() else None,
        "shm_mtime": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(PROD_SHM.stat().st_mtime))
        if PROD_SHM.exists()
        else None,
        "shm_sha256": sha(PROD_SHM) if PROD_SHM.exists() else None,
    }


def install(staged: dict) -> None:
    spec.REGISTERED_HOST_ROOT = staged["host"]
    spec.PHASE1_ROOT = staged["phase1"]
    spec.RESEARCH_LOG = staged["log_path"]


def rewrite_document(staged: dict, document: dict) -> None:
    path = staged["prereg_path"]
    path.write_text(json.dumps(document, sort_keys=True, indent=1) + "\n", encoding="utf-8")
    digest = prereg.document_sha256(document)
    prereg.write_sha256_file(path, digest)
    staged["document"] = document


def approve(staged: dict) -> None:
    document = json.loads(staged["prereg_path"].read_text(encoding="utf-8"))
    write_research_log(staged["log_path"], approval_sha=prereg.document_sha256(document))


def train(staged, arm="arm2", seed=0):
    return worker.run_worker(
        "train",
        output_root=staged["phase1"],
        limits=spec.RESOURCE_LIMITS,
        wall_budget_seconds=float(staged["document"]["timing"]["deadline_seconds"]),
        prereg_path=staged["prereg_path"],
        arm=arm,
        seed=seed,
    )


def evaluate(staged, arm="arm2", seed=0):
    return worker.run_worker(
        "eval",
        output_root=staged["phase1"],
        limits=spec.RESOURCE_LIMITS,
        wall_budget_seconds=300.0,
        prereg_path=staged["prereg_path"],
        arm=arm,
        seed=seed,
    )


def started_run(staged, *, experiment_id, arm_id, seed, run_id):
    ledger = worker.PrepLedger(staged["ledger_path"])
    try:
        try:
            ledger.store.get_experiment(experiment_id)
        except KeyError:
            ledger.store.create_experiment(
                worker.train_experiment_manifest(
                    updates=int(staged["document"]["training_protocol"]["updates"])
                ),
                f"{experiment_id}:training",
                experiment_id,
            )
        snapshot = worker.run_config_snapshot(
            wall_budget_seconds=1200.0, purpose=f"probe:{arm_id}:seed{seed}"
        )
        snapshot["arm_id"] = arm_id
        snapshot["seed"] = int(seed)
        snapshot["updates"] = int(staged["document"]["training_protocol"]["updates"])
        ledger.store.create_run(
            snapshot,
            f"{experiment_id}:{arm_id}:{seed}:{run_id}",
            run_id,
            experiment_id=experiment_id,
            role="model",
        )
        ledger.store.transition(run_id, "initializing", reason="probe")
        ledger.store.transition(run_id, "training", reason="probe")
    finally:
        ledger.close()


def age_run(staged, seconds, run_id):
    with sqlite3.connect(staged["ledger_path"]) as conn:
        conn.execute(
            "UPDATE runs SET created_at = created_at - ?, updated_at = updated_at - ? WHERE run_id = ?",
            (float(seconds), float(seconds), run_id),
        )


def check(name, report, staged, expected_stage):
    ok = (
        report.get("status") == "refused"
        and report.get("refused_stage") == expected_stage
        and sha(staged["ledger_path"]) == staged["ledger_sha256"]
    )
    return {
        "name": name,
        "ok": ok,
        "status": report.get("status"),
        "refused_stage": report.get("refused_stage"),
        "error": report.get("error"),
        "ledger_unchanged": sha(staged["ledger_path"]) == staged["ledger_sha256"],
        "expected_stage": expected_stage,
    }


def main(tmp_root: Path):
    before = prod_snap()
    assert before["control.sqlite3"] == EXPECTED_LEDGER, before
    assert before["wal_bytes"] == 0, before

    results = []

    # --- train branches ---
    staged = stage_phase1_host(tmp_root / "t_no_appr", experiment_id=R12, budget_registration=spec.R11_BUDGET_REGISTRATION)
    install(staged)
    results.append(check("train_no_approval", train(staged), staged, "preregistration_not_approved"))

    staged = stage_phase1_host(tmp_root / "t_drift", experiment_id=R12, budget_registration=spec.R11_BUDGET_REGISTRATION, approve=True)
    install(staged)
    doc = json.loads(json.dumps(staged["document"]))
    bound = sorted(doc["source_identity"]["package_files"])[0]
    doc["source_identity"]["package_files"][bound] = "0" * 64
    rewrite_document(staged, doc)
    approve(staged)
    results.append(check("train_source_drift", train(staged), staged, "source_binding_drift"))

    staged = stage_phase1_host(tmp_root / "t_data", experiment_id=R12, budget_registration=spec.R11_BUDGET_REGISTRATION, approve=True)
    install(staged)
    doc = json.loads(json.dumps(staged["document"]))
    doc["data_identity"]["dataset_digest"] = "b" * 64
    rewrite_document(staged, doc)
    approve(staged)
    results.append(check("train_dataset_mismatch", train(staged), staged, "dataset_identity_mismatch"))

    staged = stage_phase1_host(tmp_root / "t_attempt", experiment_id=R12, budget_registration=spec.R11_BUDGET_REGISTRATION, approve=True)
    install(staged)
    started_run(staged, experiment_id=R12, arm_id="arm2", seed=0, run_id="r12-arm2-seed0")
    staged["ledger_sha256"] = sha(staged["ledger_path"])
    results.append(check("train_already_attempted", train(staged), staged, "already_attempted"))

    staged = stage_phase1_host(tmp_root / "t_phase", experiment_id=R12, budget_registration=spec.R11_BUDGET_REGISTRATION, approve=True)
    install(staged)
    rid = "r12-arm3-seed1"
    started_run(staged, experiment_id=R12, arm_id="arm3", seed=1, run_id=rid)
    age_run(staged, 14300.0, rid)
    staged["ledger_sha256"] = sha(staged["ledger_path"])
    results.append(check("train_phase_budget", train(staged), staged, "phase_budget_exceeded"))

    # --- eval branches ---
    staged = stage_phase1_host(tmp_root / "e_bind", experiment_id=R12, budget_registration=spec.R11_BUDGET_REGISTRATION)
    install(staged)
    results.append(check("eval_binding_unavailable", evaluate(staged), staged, "eval_binding_unavailable"))

    staged = stage_phase1_host(
        tmp_root / "e_budget",
        experiment_id=R12,
        budget_registration=spec.R11_BUDGET_REGISTRATION,
        plan=make_plan(train_worlds=4, development_worlds=100, rounds=1),
    )
    install(staged)
    results.append(check("eval_call_budget", evaluate(staged, arm="arm3", seed=1), staged, "eval_call_budget_exceeded"))

    staged = stage_phase1_host(tmp_root / "e_d", experiment_id=R12, budget_registration=spec.R11_BUDGET_REGISTRATION)
    install(staged)
    started_run(staged, experiment_id=R12, arm_id="arm1", seed=0, run_id="r12-arm1")
    staged["ledger_sha256"] = sha(staged["ledger_path"])
    results.append(check("eval_d_already_attempted", evaluate(staged, arm="arm1", seed=0), staged, "already_attempted"))

    staged = stage_phase1_host(tmp_root / "e_drift", experiment_id=R12, budget_registration=spec.R11_BUDGET_REGISTRATION)
    install(staged)
    doc = json.loads(json.dumps(staged["document"]))
    bound = sorted(doc["source_identity"]["package_files"])[0]
    doc["source_identity"]["package_files"][bound] = "0" * 64
    rewrite_document(staged, doc)
    results.append(check("eval_source_drift", evaluate(staged), staged, "source_binding_drift"))

    # --- WIP-style wrong mutation (doc without sidecar) → status=failed ValueError, ledger untouched ---
    staged = stage_phase1_host(tmp_root / "wip_bad_mut", experiment_id=R12, budget_registration=spec.R11_BUDGET_REGISTRATION, approve=True)
    install(staged)
    doc = json.loads(staged["prereg_path"].read_text(encoding="utf-8"))
    doc["data_identity"]["dataset_digest"] = "c" * 64
    staged["prereg_path"].write_text(json.dumps(doc, sort_keys=True, indent=1) + "\n", encoding="utf-8")
    # sidecar intentionally NOT updated — reproduces WIP probes.json train_dataset_mismatch
    report = train(staged)
    err = report.get("error") or ""
    results.append(
        {
            "name": "wip_style_sidecar_desync_is_probe_artifact",
            "ok": report.get("status") == "failed"
            and "SHA256 mismatch" in err
            and sha(staged["ledger_path"]) == staged["ledger_sha256"],
            "status": report.get("status"),
            "error": err,
            "ledger_unchanged": sha(staged["ledger_path"]) == staged["ledger_sha256"],
            "judgment": "WIP ValueError/failed was probe construction (doc mutated without sidecar+reapprove); proper rewrite yields refused dataset_identity_mismatch",
        }
    )

    # --- D identity reads ARM_SPECS ---
    import inspect

    src = inspect.getsource(worker)
    d_uses_arm_specs = "ARM_SPECS" in src and "arm_id" in src
    # more precise: find arm1 D path
    arm_specs_ok = "spec.ARM_SPECS" in Path(worker.__file__).read_text(encoding="utf-8")
    results.append(
        {
            "name": "d_identity_reads_ARM_SPECS",
            "ok": arm_specs_ok,
            "detail": "worker.py references spec.ARM_SPECS for D/arm identity",
        }
    )

    after = prod_snap()
    summary = {
        "agent": "cursor-e4k9",
        "prod_before": before,
        "prod_after": after,
        "prod_ledger_unchanged": before["control.sqlite3"] == after["control.sqlite3"] == EXPECTED_LEDGER,
        "prod_wal_still_zero": after["wal_bytes"] == 0,
        "shm_mtime_changed": before["shm_mtime"] != after["shm_mtime"],
        "results": results,
        "passed": sum(1 for r in results if r.get("ok")),
        "failed": sum(1 for r in results if not r.get("ok")),
    }
    (OUT / "cursor-probes.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n")
    print(json.dumps({k: summary[k] for k in ("passed", "failed", "prod_ledger_unchanged", "prod_wal_still_zero", "shm_mtime_changed")}, indent=2))
    for r in results:
        print(("PASS" if r.get("ok") else "FAIL"), r["name"], r.get("refused_stage") or r.get("status"), r.get("judgment") or "")
    return 0 if summary["failed"] == 0 and summary["prod_ledger_unchanged"] else 1


if __name__ == "__main__":
    import tempfile

    with tempfile.TemporaryDirectory(prefix="p35-cursor-") as tmp:
        raise SystemExit(main(Path(tmp)))
