#!/usr/bin/env python3
"""
ainerzero.V9.P60 独立复核脚本 (gemini-u7w4)
纯 CPU 只读验证，不修改源码、不碰锁、不尝试读取 final.jsonl (保持 000 权限)。
"""
import os, sys, json, hashlib, stat, glob
from pathlib import Path

ROOT = Path("/Users/mac/AinerWorkFlow/AinerZero")
OUT_DIR = ROOT / "reports/V9-P60/gemini-u7w4"

sys.path.insert(0, str(ROOT / "src"))
from ainerzero.v9.experiments.s1 import prereg, spec

def run_verification():
    results = {
        "task_id": "ainerzero.V9.P60",
        "verified_task": "ainerzero.V9.P59",
        "verifier": "gemini-u7w4",
        "checks": {}
    }

    # 1. 生产台账校验
    control_db = ROOT / "artifacts/v9/s1/phase1/control.sqlite3"
    control_sha = hashlib.sha256(control_db.read_bytes()).hexdigest()
    expected_control_sha = "7244149c2bb87096e0dacf75f7151f15c0253f4bd367b23d0ff456090a2d5f53"
    results["checks"]["control_ledger"] = {
        "path": str(control_db),
        "sha256": control_sha,
        "expected": expected_control_sha,
        "passed": control_sha == expected_control_sha
    }
    assert control_sha == expected_control_sha, "Control ledger tampered!"

    # 2. 封存数据与只读一次检查
    sealed_dir = ROOT / "artifacts/v9/s1/final-sealed/057ea6c20f7ec9cadad2e774b21f4b561407cc324114ae8c0e17fc57f82ef887"
    sealed_json_path = sealed_dir / "SEALED.json"
    sealed_data = json.loads(sealed_json_path.read_text())
    
    # export_meta.json
    export_meta_path = sealed_dir / "export_meta.json"
    export_meta_sha = hashlib.sha256(export_meta_path.read_bytes()).hexdigest()
    expected_meta_sha = sealed_data["files"]["export_meta.json"]
    
    # 权限与尺寸检查 (绝不打开读取 final.jsonl)
    packets_st = (sealed_dir / "packets/final.jsonl").stat()
    truth_st = (sealed_dir / "truth/final.jsonl").stat()
    packets_mode = oct(stat.S_IMODE(packets_st.st_mode))
    truth_mode = oct(stat.S_IMODE(truth_st.st_mode))

    # 检查是否有 READ_ONCE 标记
    markers = list(sealed_dir.parent.glob("*.READ_ONCE.json")) + list(sealed_dir.glob("*.READ_ONCE.json"))

    results["checks"]["sealed_dataset"] = {
        "dataset_digest": sealed_data.get("dataset_digest"),
        "expected_digest": "057ea6c20f7ec9cadad2e774b21f4b561407cc324114ae8c0e17fc57f82ef887",
        "counts": sealed_data.get("counts"),
        "export_meta_sha256": export_meta_sha,
        "export_meta_sha256_matches": export_meta_sha == expected_meta_sha,
        "packets_file_mode": packets_mode,
        "packets_file_size": packets_st.st_size,
        "truth_file_mode": truth_mode,
        "truth_file_size": truth_st.st_size,
        "packets_mode_is_000": packets_mode in ("0o0", "0000"),
        "truth_mode_is_000": truth_mode in ("0o0", "0000"),
        "read_once_marker_exists": len(markers) > 0,
        "final_never_read": len(markers) == 0,
        "passed": (
            sealed_data.get("dataset_digest") == "057ea6c20f7ec9cadad2e774b21f4b561407cc324114ae8c0e17fc57f82ef887"
            and export_meta_sha == expected_meta_sha
            and packets_mode in ("0o0", "0000")
            and truth_mode in ("0o0", "0000")
            and len(markers) == 0
        )
    }
    assert results["checks"]["sealed_dataset"]["passed"], "Sealed dataset check failed!"

    # 3. final 预登记冻结检查
    prereg_final_path = ROOT / "artifacts/v9/s1/phase1/final/pre_registration.json"
    prereg_final_bytes = prereg_final_path.read_bytes()
    prereg_final_file_sha = hashlib.sha256(prereg_final_bytes).hexdigest()
    prereg_final_doc = json.loads(prereg_final_bytes)
    prereg_final_doc_sha = prereg.document_sha256(prereg_final_doc)

    expected_doc_sha = "ad21071ec11d3006b9d31e9ac3c0e9a48aa6a94c2efd80807549ca1681e9b60c"
    expected_file_sha = "e93935e093883e8b85713c7de6efb92d814ac1ecc16672d94e2208e930a2974c"

    # 对比 r15 与 final 的科学节
    prereg_r15_doc = json.loads((ROOT / "artifacts/v9/s1/phase1/r15/pre_registration.json").read_bytes())
    scientific_sections = [
        "arms", "evaluation", "metrics", "stop_rules", "training_protocol", "data_identity", "resource_limits"
    ]
    sections_equal = {s: (prereg_final_doc.get(s) == prereg_r15_doc.get(s)) for s in scientific_sections}
    all_sections_equal = all(sections_equal.values())

    results["checks"]["pre_registration"] = {
        "file_sha256": prereg_final_file_sha,
        "expected_file_sha256": expected_file_sha,
        "document_sha256": prereg_final_doc_sha,
        "expected_document_sha256": expected_doc_sha,
        "scientific_sections_equal_r15": sections_equal,
        "all_scientific_sections_equal": all_sections_equal,
        "passed": (
            prereg_final_file_sha == expected_file_sha
            and prereg_final_doc_sha == expected_doc_sha
            and all_sections_equal
        )
    }
    assert results["checks"]["pre_registration"]["passed"], "Pre-registration check failed!"

    # 4. dryrun 预演结果与 r15 dev 逐位比对
    dryrun_data = json.load(open(ROOT / "reports/V9-P9/final/logs/dryrun.json"))
    first_cells = dryrun_data["first"]["cells"]
    nll_comparisons = {}
    all_nll_identical = True

    for k, cell_info in first_cells.items():
        if k == "arm1":
            nll_comparisons[k] = {
                "status": cell_info["status"],
                "incomparable": True
            }
            continue
        dry_nll = cell_info["nll"]
        r15_file = ROOT / f"reports/V9-S1-r15/eval-details/eval-{k}.json"
        r15_data = json.load(open(r15_file))
        dev_nll = r15_data["details"]["sample_efficiency"]["nll_curve"]["last"]
        diff = abs(dry_nll - dev_nll)
        is_exact = (dry_nll == dev_nll)
        nll_comparisons[k] = {
            "dryrun_nll": dry_nll,
            "dev_nll": dev_nll,
            "diff": diff,
            "exact_bit_match": is_exact
        }
        if not is_exact:
            all_nll_identical = False

    results["checks"]["dryrun_vs_r15_dev"] = {
        "first_status": dryrun_data["first"]["status"],
        "completed_cells": dryrun_data["first"]["completed_cells"],
        "second_refused_stage": dryrun_data["second"]["refused_stage"],
        "second_call_rejected": dryrun_data["second"]["refused_stage"] == "final_already_read",
        "nll_comparisons": nll_comparisons,
        "all_nll_identical": all_nll_identical,
        "passed": (
            dryrun_data["first"]["status"] == "completed"
            and dryrun_data["second"]["refused_stage"] == "final_already_read"
            and all_nll_identical
        )
    }
    assert results["checks"]["dryrun_vs_r15_dev"]["passed"], "Dryrun verification failed!"

    # 5. 入口检查 entry-checks.json 审查
    entry_checks_data = json.load(open(ROOT / "reports/V9-P9/final/logs/entry-checks.json"))
    results["checks"]["entry_checks"] = {
        "document_sha256": entry_checks_data["document_sha256"],
        "checks": entry_checks_data["checks"],
        "all_passed": entry_checks_data["all_passed"],
        "passed": entry_checks_data["all_passed"] is True
    }
    assert results["checks"]["entry_checks"]["passed"], "Entry checks failed!"

    # 汇总
    results["all_passed"] = all(c["passed"] for c in results["checks"].values())
    
    with open(OUT_DIR / "verification.json", "w") as f:
        json.dump(results, f, indent=2)
    print("Verification completed successfully. All checks passed.")
    return results

if __name__ == "__main__":
    run_verification()
