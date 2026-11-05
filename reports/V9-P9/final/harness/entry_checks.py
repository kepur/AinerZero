"""Final-eval entry checks on an isolated copy -- refusal paths only (ainerzero.V9.P59).

The real sealed final dataset must stay unread, so ``data.open_sealed_final_once`` is replaced by a
tripwire for the whole run and no approved final-eval is ever invoked.  Checks:
CLI verify (completed, binding passed, not approved); worker final-eval unapproved -> refused before
any write; seal integrity passed and unread; with an approval line in the COPY's log only, train is
refused for all nine cells.  Writes only ../logs/entry-checks.json and its own temp directory.
"""
from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(REPO / "src"))

from ainerzero.v9.experiments.s1 import data, prereg, spec, worker  # noqa: E402

PRODUCTION = REPO / "artifacts/v9/s1/phase1"
OUT = Path(__file__).resolve().parents[1] / "logs" / "entry-checks.json"


def sha256(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _tripwire(*_a, **_k):
    raise AssertionError("entry checks must never open the real sealed final dataset")


def main() -> int:
    data.open_sealed_final_once = _tripwire
    production_before = sha256(PRODUCTION / "control.sqlite3")
    doc_path_prod = PRODUCTION / "final/pre_registration.json"
    document = json.loads(doc_path_prod.read_text(encoding="utf-8"))
    digest = prereg.document_sha256(document)
    sealed_dir = spec.FINAL_SEALED_ROOT / document["final_eval"]["sealed_dataset_digest"]
    seal_before = data.verify_sealed_final(sealed_dir, expected_digest=document["final_eval"]["sealed_dataset_digest"])
    workdir = Path(tempfile.mkdtemp(prefix="s1-final-entry-"))
    host = workdir / "host"
    copy_root = host / "artifacts/v9/s1/phase1"
    copy_root.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(PRODUCTION, copy_root)
    shutil.copy2(REPO / "RESEARCH_LOG.md", host / "RESEARCH_LOG.md")
    doc_path = copy_root / "final/pre_registration.json"
    ledger = copy_root / "control.sqlite3"
    copy_before = sha256(ledger)
    cli = subprocess.run([sys.executable, "-m", "ainerzero.cli", "s1-phase1", "--mode", "verify", "--output-root",
                          str(copy_root), "--prereg", str(doc_path)], cwd=str(REPO), capture_output=True, text=True)
    verify = json.loads(cli.stdout) if cli.stdout.strip().startswith("{") else {}
    original = (spec.REGISTERED_HOST_ROOT, spec.PHASE1_ROOT, spec.RESEARCH_LOG)
    spec.REGISTERED_HOST_ROOT, spec.PHASE1_ROOT, spec.RESEARCH_LOG = host, copy_root, host / "RESEARCH_LOG.md"
    runs = {}
    try:
        report = worker.run_worker("final-eval", output_root=copy_root, limits=spec.RESOURCE_LIMITS,
                                   wall_budget_seconds=spec.FINAL_EVAL_WALL_SECONDS, prereg_path=doc_path)
        runs["final_eval_unapproved"] = {"status": report.get("status"), "refused_stage": report.get("refused_stage"),
                                         "ledger_sha": sha256(ledger)}
        log = host / "RESEARCH_LOG.md"
        text = log.read_text(encoding="utf-8")
        current = prereg.APPROVAL_TEMPLATE.format(
            document_sha256=spec.FINAL_INHERITANCE["sources"][spec.R15_EXPERIMENT_ID]["source_preregistration_sha256"])
        assert text.count(current + "\n") == 1
        log.write_text(text.replace(current + "\n", prereg.APPROVAL_TEMPLATE.format(document_sha256=digest) + "\n"),
                       encoding="utf-8")
        assert log.resolve() != (REPO / "RESEARCH_LOG.md").resolve()
        for cell in document["inheritance"]["cells"]:
            report = worker.run_worker("train", output_root=copy_root, limits=spec.RESOURCE_LIMITS,
                                       wall_budget_seconds=1_200, prereg_path=doc_path, arm=cell["arm_id"], seed=cell["seed"])
            runs[f"train_{cell['arm_id']}_s{cell['seed']}"] = {"refused_stage": report.get("refused_stage"),
                                                               "ledger_sha": sha256(ledger)}
    finally:
        spec.REGISTERED_HOST_ROOT, spec.PHASE1_ROOT, spec.RESEARCH_LOG = original
    seal_after = data.verify_sealed_final(sealed_dir, expected_digest=document["final_eval"]["sealed_dataset_digest"])
    checks = {
        "verify_completed_binding_passed_not_approved": verify.get("status") == "completed"
        and (verify.get("source_binding") or {}).get("status") == "passed"
        and (verify.get("approval") or {}).get("approved") is False
        and verify.get("preregistration_sha256") == digest,
        "final_eval_unapproved_refused": runs["final_eval_unapproved"]["refused_stage"] == "preregistration_not_approved",
        "train_refused_for_all_nine_cells": all(v["refused_stage"] == "inherited_cell_not_trainable"
                                                for k, v in runs.items() if k.startswith("train_")) and
        sum(1 for k in runs if k.startswith("train_")) == 9,
        "copy_ledger_untouched": all(v["ledger_sha"] == copy_before for v in runs.values()),
        "seal_passed_and_unread_before_and_after": seal_before["status"] == seal_after["status"] == "passed"
        and not seal_before["already_read"] and not seal_after["already_read"],
        "production_untouched": sha256(PRODUCTION / "control.sqlite3") == production_before,
    }
    payload = {"document_sha256": digest, "verify": {k: verify.get(k) for k in ("status", "preregistration_sha256")},
               "runs": runs, "seal_before": seal_before, "seal_after": seal_after, "checks": checks,
               "all_passed": all(checks.values())}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, indent=1, ensure_ascii=False, default=str) + "\n", encoding="utf-8")
    print(json.dumps({"checks": checks, "all_passed": payload["all_passed"]}, indent=1))
    shutil.rmtree(workdir, ignore_errors=True)
    return 0 if payload["all_passed"] else 9


if __name__ == "__main__":
    raise SystemExit(main())
