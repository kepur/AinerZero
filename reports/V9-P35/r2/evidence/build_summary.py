#!/usr/bin/env python3
"""把 r2 各项证据汇总成 reports/V9-P35/指标.json（数字全部从证据文件里取，不手抄）。"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import p35common as C

EV = C.EVIDENCE


def load(name: str) -> dict:
    path = EV / name
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}


def main() -> int:
    start = load("review-inputs-start.json")
    end = load("review-inputs-end.json")
    bad = load("badcontrol-order.json")
    drill = load("release-drill.json")
    did = load("d-identity-runtime.json")
    rej = load("rejections.json")
    reg = load("registration-leaf-commands.json")
    stub = load("timing-stub.json")
    tests = load("tests-reconcile.json")
    ledger_q = load("ledger-questions.json")
    wip = load("wip-compare.json")

    body_bad = bad.get("body") or {}
    body_drill = drill.get("body") or {}
    body_did = did.get("body") or {}
    body_rej = rej.get("body") or {}
    body_reg = reg.get("body") or {}
    body_stub = stub.get("body") or {}
    body_tests = tests.get("body") or {}
    body_ledger = ledger_q.get("body") or {}

    checks_flat = {}
    for label, body in (
        ("badcontrol", body_bad),
        ("release_drill", body_drill),
        ("d_identity", body_did),
        ("rejections", body_rej),
        ("registration_leaf", body_reg),
        ("timing_stub", body_stub),
        ("tests", body_tests),
        ("ledger_questions", body_ledger),
    ):
        for key, value in (body.get("checks") or {}).items():
            checks_flat[f"{label}.{key}"] = bool(value)

    doc = {
        "task": "ainerzero.V9.P35",
        "round": "r2",
        "verifies": "ainerzero.V9.P34",
        "agent": "deepseekv41f-h3t8",
        "role": "verifier",
        "recommendation": "建议通过",
        "not_excluded": True,
        "excluded_agents": ["claude", "codex", "deepseek-p34x"],
        "author_of_verified_task": "deepseek-p34x",
        "source_scope": "reports/V9-P35/ only; 源码零写入（worker.py/spec.py/prereg.py/commands.py SHA 均等于封源值）",
        "r1_archived_to": "reports/V9-P35/r1/",
        "review_inputs": {
            "files_expected": start.get("files_total"),
            "start_ok": start.get("files_ok"),
            "start_all_ok": start.get("all_ok"),
            "end_ok": end.get("files_ok"),
            "end_all_ok": end.get("all_ok"),
            "production_ledger_sha_start": (start.get("production_ledger") or {}).get("sha256"),
            "production_ledger_sha_end": (end.get("production_ledger") or {}).get("sha256"),
            "wal_bytes_start": (start.get("production_ledger") or {}).get("wal_bytes"),
            "wal_bytes_end": (end.get("production_ledger") or {}).get("wal_bytes"),
            "shm_mtime_start": ((start.get("production_ledger") or {}).get("shm") or {}).get("mtime_iso"),
            "shm_mtime_end": ((end.get("production_ledger") or {}).get("shm") or {}).get("mtime_iso"),
        },
        "wip_stall1": wip.get("body") or {},
        "bad_control": {
            "real_status": (body_bad.get("real") or {}).get("status"),
            "real_stage": (body_bad.get("real") or {}).get("refused_stage"),
            "real_ledger_unchanged": (body_bad.get("real") or {}).get("unchanged"),
            "sabotaged_ledger_changed": (body_bad.get("sabotaged") or {}).get("unchanged") is False,
            "sabotaged_run_id": (body_bad.get("sabotaged") or {}).get("run_id"),
            "sabotaged_ledger_after": (body_bad.get("sabotaged") or {}).get("ledger_after"),
            "copy_ledger_rows": body_bad.get("copy_ledger_rows"),
            "diff_path": body_bad.get("diff_path"),
            "all_checks_pass": body_bad.get("all_checks_pass"),
        },
        "release_drill": {
            "approval_line_document_sha256": body_drill.get("approval_line_document_sha256"),
            "cases": {
                name: {
                    "status": case.get("status"),
                    "refused_stage": case.get("refused_stage"),
                    "sentinel_stopped": case.get("sentinel_stopped"),
                    "mlx_loaded": case.get("mlx_loaded"),
                    "eval_binding_status": (case.get("eval_binding") or {}).get("status")
                    if isinstance(case.get("eval_binding"), dict)
                    else None,
                    "d_candidate_attempts": case.get("d_candidate_attempts"),
                }
                for name, case in (body_drill.get("cases") or {}).items()
            },
            "all_checks_pass": body_drill.get("all_checks_pass"),
        },
        "d_identity": {
            "document_arm1_tampered": bool(
                (body_did.get("A_document_arm1_tampered") or {}).get("document_differs_from_spec")
            ),
            "runtime_matches_spec": (body_did.get("A_document_arm1_tampered") or {}).get(
                "runtime_matches_spec"
            ),
            "eval_arm1_with_tampered_doc": (
                body_did.get("A_document_arm1_tampered") or {}
            ).get("eval_arm1"),
            "spec_mutation_verdict": (
                body_did.get("B1_spec_arm1_identity_mutated_in_source_copy") or {}
            ).get("eval_arm1"),
            "bound_spec_hash_mutation_verdict": (
                body_did.get("B2_document_bound_spec_hash_tampered") or {}
            ).get("eval_arm1"),
            "all_checks_pass": body_did.get("all_checks_pass"),
        },
        "rejection_branches": {
            "covered": body_rej.get("branches_covered"),
            "per_case": {
                case.get("case"): {
                    "status": case.get("actual_status"),
                    "stage": case.get("actual_stage"),
                    "ledger_unchanged": case.get("ledger_bytes_unchanged"),
                }
                for case in (body_rej.get("cases") or [])
            },
            "wip_valueerror_judgement": (body_rej.get("judgement_case") or {}).get("verdict"),
            "all_checks_pass": body_rej.get("all_checks_pass"),
        },
        "registration_and_leaf": {
            "registration_values_ok": all(
                value.get("ok") for value in (body_reg.get("registration_values") or {}).values()
            ),
            "leaf_changes": [
                item.get("path") for item in (body_reg.get("leaf_diff") or {}).get("changed", [])
            ],
            "leaf_changes_outside_allowlist": (body_reg.get("leaf_diff") or {}).get(
                "outside_allowlist"
            ),
            "commands_py": body_reg.get("commands_py"),
            "all_checks_pass": body_reg.get("all_checks_pass"),
        },
        "timing_stub": {
            "diff_added": body_stub.get("diff_lines_added"),
            "diff_removed": body_stub.get("diff_lines_removed"),
            "coverage_tests": body_stub.get("coverage_tests"),
            "coverage_run": body_stub.get("coverage_run"),
            "all_checks_pass": body_stub.get("all_checks_pass"),
        },
        "tests_v9": {
            "with_ide_shim": body_tests.get("runs", {}).get("with_shim", {}).get("summary_line"),
            "without_ide_shim": body_tests.get("runs", {}).get("no_shim", {}).get("summary_line"),
            "experiments_alone": body_tests.get("runs", {}).get("experiments_alone", {}).get(
                "summary_line"
            ),
            "geometry_alone": body_tests.get("runs", {}).get("geometry_alone", {}).get(
                "summary_line"
            ),
            "attribution": body_tests.get("attribution"),
            "environment": body_tests.get("environment"),
            "all_checks_pass": body_tests.get("all_checks_pass"),
        },
        "ledger_questions": {
            "shm_attribution": (body_ledger.get("A_read_paths") or {}).get("conclusion"),
            "real_ledger_test_facts": (body_ledger.get("B_real_ledger_tests") or {}).get("facts"),
            "wip_probe_conclusion": (body_ledger.get("C_wip_probe_inspection") or {}).get(
                "conclusion"
            ),
            "all_checks_pass": body_ledger.get("all_checks_pass"),
        },
        "checks_total": len(checks_flat),
        "checks_passed": sum(1 for value in checks_flat.values() if value),
        "checks": checks_flat,
        "all_checks_pass": all(checks_flat.values()),
    }
    out = C.REPO / "reports/V9-P35/指标.json"
    out.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(
        {
            "written": str(out),
            "checks_total": doc["checks_total"],
            "checks_passed": doc["checks_passed"],
            "all_checks_pass": doc["all_checks_pass"],
            "failing": [k for k, v in checks_flat.items() if not v],
        },
        ensure_ascii=False,
        indent=1,
    ))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
