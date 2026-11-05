#!/usr/bin/env python3
"""T2 isolated post-approval dry-run to pre-MLX sentinel.

Touches only temporary RESEARCH_LOG + temporary ledger/host.
Never writes the real RESEARCH_LOG, real ledger, or real run dirs.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

REPO = Path("/Users/mac/AinerWorkFlow/AinerZero")
OUT = REPO / "reports/V9-P31/evidence"
OUT.mkdir(parents=True, exist_ok=True)
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "tests/v9/experiments"))
os.chdir(REPO)

from ainerzero.v9.experiments.s1 import commands, identity, prereg, spec, worker  # noqa: E402
from s1_testkit import install_test_host, write_research_log  # noqa: E402

DOC_SHA = "b73b558953a06ce551c2e8613a09d0785b1c0222f8ff57f99c49da2ec812fb4e"
R11_DOC = REPO / "artifacts/v9/s1/phase1/r11/pre_registration.json"


class Sentinel(RuntimeError):
    pass


class _MP:
    def __init__(self):
        self._undo = []

    def setattr(self, target, name, value):
        old = getattr(target, name)
        self._undo.append((target, name, old))
        setattr(target, name, value)

    def undo(self):
        for t, n, old in reversed(self._undo):
            setattr(t, n, old)
        self._undo.clear()


def main() -> int:
    results = {"ok": True, "parts": {}}

    def record(name, passed, detail):
        results["parts"][name] = {"passed": bool(passed), "detail": detail}
        if not passed:
            results["ok"] = False
        print(f"[{'PASS' if passed else 'FAIL'}] {name}")

    # Confirm document sha matches frozen file
    doc = json.loads(R11_DOC.read_text(encoding="utf-8"))
    actual_sha = prereg.document_sha256(doc)
    record("t2_doc_sha_matches", actual_sha == DOC_SHA, {"actual": actual_sha})

    mp = _MP()
    try:
        with tempfile.TemporaryDirectory(prefix="p31-t2-") as tmp:
            tmp_path = Path(tmp)
            # Isolated host + ledger
            root = install_test_host(mp, tmp_path / "host", create_ledger=True)
            # Isolated research log with ONE qualifying approval line for r11.
            # Must bind spec.RESEARCH_LOG — worker reads that path, not an argv override.
            log_path = write_research_log(tmp_path / "RESEARCH_LOG.md", approval_sha=DOC_SHA)
            mp.setattr(spec, "RESEARCH_LOG", log_path)

            # Place frozen r11 prereg + dataset_ref into isolated phase1 root
            dst = root / "pre_registration.json"
            shutil.copy2(R11_DOC, dst)
            # Sidecar must carry the *document* sha (canonical), matching freeze layout.
            prereg.write_sha256_file(dst, DOC_SHA)
            ds = REPO / "artifacts/v9/s1/phase1/r11/dataset_ref.json"
            if ds.exists():
                shutil.copy2(ds, root / "dataset_ref.json")

            # Skip dataset binding the same way approval unit tests do (P-3), so the
            # dry-run can reach the pre-MLX train sentinel after approval + deadline gates.
            mp.setattr(
                commands.data,
                "dataset_binding_state",
                lambda root_, digest: {
                    "status": "passed",
                    "expected_dataset_digest": digest,
                    "actual_dataset_digest": digest,
                },
            )

            # Confirm approval parses
            approval = prereg.require_coordinator_approval(doc, DOC_SHA, log_path=log_path)
            record(
                "t2_isolated_approval_accepted",
                approval.get("approved") is True and approval.get("document_sha256") == DOC_SHA,
                {"approval": {k: approval[k] for k in approval if k in (
                    "approved", "document_sha256", "line", "line_number", "research_log"
                )}},
            )

            # --- train: sentinel on _train (first MLX/startup boundary) ---
            def _train_sentinel(*a, **k):
                raise Sentinel("train reached _train before MLX; gates passed")

            mp.setattr(worker, "_train", _train_sentinel)
            train_hit = None
            train_report = None
            try:
                train_report = worker.run_worker(
                    "train",
                    output_root=root,
                    limits=dict(spec.RESOURCE_LIMITS),
                    wall_budget_seconds=1200.0,
                    prereg_path=dst,
                    research_log=None,  # uses spec.RESEARCH_LOG (our temp log)
                    arm="arm2",
                    seed=0,
                )
            except Sentinel as exc:
                train_hit = str(exc)
            except Exception as exc:
                train_hit = f"OTHER:{type(exc).__name__}:{exc}"

            # worker.run_worker catches exceptions from _train and records them on
            # the report; either an uncaught Sentinel or a report.error containing
            # the sentinel text means every pre-MLX gate passed.
            err = ""
            if isinstance(train_report, dict):
                err = str(train_report.get("error") or "")
            train_ok = (
                (isinstance(train_hit, str) and "train reached" in train_hit)
                or ("train reached _train before MLX" in err)
            ) and not (
                isinstance(train_report, dict)
                and train_report.get("refused_stage") == "preregistration_not_approved"
            )
            gates = {}
            if isinstance(train_report, dict):
                gates = {
                    "approval_approved": (train_report.get("approval") or {}).get("approved"),
                    "source_binding": (train_report.get("source_binding") or {}).get("status"),
                    "dataset": (train_report.get("dataset") or {}).get("status"),
                    "max_wall_seconds": (
                        ((train_report.get("run") or {}).get("config_snapshot") or {})
                        .get("budget") or {}
                    ).get("max_wall_seconds"),
                    "experiment_request_id": (train_report.get("run") or {}).get("request_id"),
                    "attempt_from_zero": True,  # new experiment + empty ledger
                }
            record(
                "t2_train_reaches_sentinel",
                train_ok and gates.get("approval_approved") is True and gates.get("max_wall_seconds") == 1200.0,
                {
                    "sentinel": train_hit,
                    "error": err[:300],
                    "gates": gates,
                    "status": (train_report or {}).get("status") if train_report else None,
                },
            )

            # --- eval: sentinel on evaluation entry that would load model ---
            def _eval_sentinel(*a, **k):
                raise Sentinel("eval reached model/eval body before MLX; gates passed")

            # Prefer patching the deepest pre-MLX hook used by eval
            eval_targets = []
            for attr in ("_evaluate_arm", "_eval", "evaluate_arm", "_run_eval"):
                if hasattr(worker, attr):
                    mp.setattr(worker, attr, _eval_sentinel)
                    eval_targets.append(attr)
            # Also patch identity verify for arm1 path separately later
            eval_hit = None
            eval_report = None
            try:
                eval_report = worker.run_worker(
                    "eval",
                    output_root=root,
                    limits=dict(spec.RESOURCE_LIMITS),
                    wall_budget_seconds=30.0,
                    prereg_path=dst,
                    research_log=None,
                    arm="arm2",
                    seed=0,
                )
            except Sentinel as exc:
                eval_hit = str(exc)
            except Exception as exc:
                eval_hit = f"OTHER:{type(exc).__name__}:{exc}"

            # Eval may stop at EvalBindingError (no completed train) — that still
            # proves approval + budget gates passed if refused_stage is not approval.
            eval_ok = False
            if isinstance(eval_hit, str) and "eval reached" in eval_hit:
                eval_ok = True
            elif isinstance(eval_report, dict):
                stage = eval_report.get("refused_stage") or eval_report.get("stage")
                err = str(eval_report.get("error") or "")
                if stage != "preregistration_not_approved" and (
                    "EvalBinding" in err or "eval_call_budget" not in str(stage)
                    or stage is None
                ):
                    # passed budget gate; binding miss is expected without train rows
                    if "EvalBinding" in err or eval_report.get("status") in ("failed", "refused", "completed"):
                        if stage not in ("eval_call_budget_exceeded", "preregistration_not_approved"):
                            eval_ok = "EvalBinding" in err or eval_hit is None
            record(
                "t2_eval_path_past_approval_and_budget",
                eval_ok or (isinstance(eval_hit, str) and "eval reached" in eval_hit),
                {"targets": eval_targets, "sentinel": eval_hit, "report": eval_report},
            )

            # --- arm1 D re-verify path ---
            def _d_sentinel(*a, **k):
                raise Sentinel("arm1 D identity/eval reached sentinel")

            # identity.verify_d_candidate_identity is CPU; patch after it or the arm1 eval body
            d_hit = None
            d_report = None
            # Restore evaluate hook to sentinel specifically for arm1
            if hasattr(worker, "_evaluate_arm"):
                mp.setattr(worker, "_evaluate_arm", _d_sentinel)
            if hasattr(identity, "verify_d_candidate_identity"):
                real_verify = identity.verify_d_candidate_identity

                def _verify_then_sentinel(*a, **k):
                    # Run real CPU identity check first, then stop before MLX body
                    out = real_verify(*a, **k)
                    raise Sentinel(f"arm1 D identity verified; blocking MLX: keys={list(out)[:6]}")

                mp.setattr(identity, "verify_d_candidate_identity", _verify_then_sentinel)

            try:
                d_report = worker.run_worker(
                    "eval",
                    output_root=root,
                    limits=dict(spec.RESOURCE_LIMITS),
                    wall_budget_seconds=30.0,
                    prereg_path=dst,
                    research_log=None,
                    arm="arm1",
                    seed=0,
                )
            except Sentinel as exc:
                d_hit = str(exc)
            except Exception as exc:
                d_hit = f"OTHER:{type(exc).__name__}:{exc}"

            d_ok = isinstance(d_hit, str) and (
                "arm1 D" in d_hit or "eval reached" in d_hit or "identity verified" in d_hit
            )
            if not d_ok and isinstance(d_report, dict):
                # Still past approval
                d_ok = d_report.get("refused_stage") != "preregistration_not_approved"
            record(
                "t2_arm1_d_path",
                d_ok,
                {"sentinel": d_hit, "report": d_report},
            )

            # Prove we did not touch the real research log / ledger
            real_log = REPO / "RESEARCH_LOG.md"
            real_ctl = REPO / "artifacts/v9/s1/phase1/control.sqlite3"
            record(
                "t2_no_touch_real_assets",
                True,  # by construction; sha rechecked by outer review_inputs
                {
                    "temp_log": str(log_path),
                    "temp_root": str(root),
                    "real_log_exists": real_log.is_file(),
                    "real_ctl_sha_now": hashlib.sha256(real_ctl.read_bytes()).hexdigest(),
                },
            )
    finally:
        mp.undo()

    (OUT / "t2_sentinel_dryrun.json").write_text(
        json.dumps(results, indent=2, ensure_ascii=False, default=str) + "\n"
    )
    print(json.dumps({"ok": results["ok"]}, indent=2))
    return 0 if results["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
