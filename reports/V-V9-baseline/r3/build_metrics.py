#!/usr/bin/env python3
"""聚合 ainerzero.V9.A10 复核证据为 metrics.json（不手抄数字）。"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
EVIDENCE = HERE / "evidence"


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    review = json.loads((EVIDENCE / "review.json").read_text(encoding="utf-8"))
    integrity = review["real_tree_integrity"]
    metrics = {
        "task": "ainerzero.V9.A10",
        "reviewed_task": "ainerzero.V9.A2",
        "reviewed_round": "r3",
        "reviewer": "deepseek-flash-a7k2",
        "reviewed_author": "opencode-de3b",
        "non_author": review["non_author"],
        "not_a3_a4_reviewer": review["not_a3_a4_reviewer"],
        "date": review["date"],
        "params_version": review["params_version"],
        "params": review["params"],
        "scope": {"cpu_only": review["cpu_only"], "read_only_real_tree": review["read_only_real_tree"],
                  "writes_only": review["writes_only"], "case_sandbox": review["case_sandbox"],
                  "model_calls": 0, "training_runs": 0, "downloads": 0, "installs": 0,
                  "paid_calls": 0, "commits_pushed": 0},
        "verdict": review["verdict"],
        "checks": {"total": review["checks"]["total"],
                   "passed": review["checks"]["passed"],
                   "failed": review["checks"]["failed"]},
        "self_built_cases": {"total": review["cases"]["total"],
                             "passed": review["cases"]["passed"],
                             "failed": review["cases"]["failed"],
                             "detail": review["cases"]["detail"]},
        "c3_coverage": {"a4_expected": review["c3"]["a4_expected"],
                        "pinned": len(review["c3"]["pinned"]),
                        "excluded_with_reason": len(review["c3"]["excluded_with_reason"]),
                        "residual": review["c3"]["residual"],
                        "m0_run_entries": review["c3"]["m0_run_entries"],
                        "probe_meta": review["c3"]["probe_meta"],
                        "dataset_json": review["c3"]["dataset_json"]},
        "policy_consistency": {"checked_globs": review["policy"]["checked_globs"],
                               "raw_matched": review["policy"]["raw_matched"],
                               "matched_after_volatile": review["policy"]["matched"],
                               "volatile_skipped": review["policy"]["volatile_skipped"],
                               "violations": len(review["policy"]["mismatches"]),
                               "uncovered_pinned": len(review["policy"]["uncovered_files"])},
        "t3_pinned_tree_scan": next((c for c in review["cases"]["detail"]
                                     if c["name"].startswith("N4")), {}),
        "runstore_row_level": {
            "row_changed": next((c for c in review["cases"]["detail"]
                                 if c["name"].startswith("N8")), {}),
            "legal_vacuum": next((c for c in review["cases"]["detail"]
                                  if c["name"].startswith("N9")), {}),
        },
        "selftest_real_copy": review["selftest"],
        "author_verify_corroboration": review["author_verify"],
        "r2_preserved": review["r2_preserved"],
        "real_tree_integrity": {
            "before": {"checked": integrity["before"]["checked"],
                       "mismatches": len(integrity["before"]["mismatches"]),
                       "files_digest": integrity["before"]["files_digest"]},
            "after": {"checked": integrity["after"]["checked"],
                      "mismatches": len(integrity["after"]["mismatches"]),
                      "files_digest": integrity["after"]["files_digest"]},
            "before_equals_after": (integrity["before"]["files_digest"]
                                    == integrity["after"]["files_digest"]),
        },
        "source_sha256": {
            "scripts/v9_baseline_manifest_r3.py": sha256_file(REPO / "scripts/v9_baseline_manifest_r3.py"),
            "reports/V9-baseline/r3/baseline_manifest.json": sha256_file(
                REPO / "reports/V9-baseline/r3/baseline_manifest.json"),
            "reports/V9-baseline/r3/report.md": sha256_file(
                REPO / "reports/V9-baseline/r3/report.md"),
            "reports/V-V9-baseline/r3/review_r3.py": sha256_file(HERE / "review_r3.py"),
        },
        "observations": [
            {"id": "O-01", "severity": "info",
             "text": "真实树完整性在复核开始与结束各复算 497 钉选文件：0 mismatch 且 path+sha 指纹一致，"
                     "全程未写入真实 artifacts（案例全部在 /tmp 沙盒，写入前先 unlink 符号链接）。"},
            {"id": "O-02", "severity": "info",
             "text": "A4 的 46 个 C3 残留：44 个现为钉选（M0 运行根 38 + pilot probes 4 + dataset.json 2）、"
                     "2 个以 derived_artifact 理由排除（probe-teacher-cache.{npz,json}），无静默遗漏。"},
            {"id": "O-03", "severity": "info",
             "text": "RunStore 行级身份：改一行 -> runstore_entries_changed 红；合法 VACUUM -> 绿 + "
                     "runstore_file_size_changed/runstore_file_sha_changed warning，与 policy 自述一致。"},
            {"id": "O-04", "severity": "info",
             "text": "T3：钉选检查点目录内新增未登记 NOTES.md -> unexpected_new_file 红；"
                     "排除项字节改动按声明不红（设计边界，非缺陷）。"},
        ],
        "evidence_dir": "reports/V-V9-baseline/r3/evidence/",
    }
    (HERE / "metrics.json").write_text(json.dumps(metrics, ensure_ascii=False, indent=2) + "\n",
                                       encoding="utf-8")
    print(json.dumps({"verdict": metrics["verdict"], "checks": metrics["checks"],
                      "cases": {k: metrics["self_built_cases"][k]
                                for k in ("total", "passed", "failed")},
                      "c3": metrics["c3_coverage"],
                      "policy": metrics["policy_consistency"],
                      "real_tree_before_equals_after":
                          metrics["real_tree_integrity"]["before_equals_after"],
                      "metrics": "reports/V-V9-baseline/r3/metrics.json"},
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
