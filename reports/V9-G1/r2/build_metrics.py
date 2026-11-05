#!/usr/bin/env python3
"""从 r2 证据文件聚合 metrics.json（不手抄数字）。

输入（全部由 run_all.sh 生成）：
- evidence/registration-verify.json      F3 消费门结果
- evidence/pytest-r1.xml / pytest-r2.xml 两套 CPU 测试（junit）
- evidence/g2-minimal-repro-r2.json      G2 最小复现转绿结果
- evidence/mutation-results-r2.json      故意改坏必须变红对照
- evidence/replay-vs-r1-diff.json        r2 消费门重放 vs r1 references 差异
- input_registration_r2.json             r2 输入重登记
输出：reports/V9-G1/r2/metrics.json
"""
from __future__ import annotations

import hashlib
import json
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
EVIDENCE = HERE / "evidence"


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def junit_counts(path: Path) -> dict:
    suite = ET.parse(path).getroot()
    if suite.tag == "testsuites":
        suite = suite.find("testsuite")
    return {"tests": int(suite.get("tests", 0)),
            "failures": int(suite.get("failures", 0)),
            "errors": int(suite.get("errors", 0)),
            "skipped": int(suite.get("skipped", 0)),
            "time_s": float(suite.get("time", 0.0))}


def main() -> None:
    verify = read_json(EVIDENCE / "registration-verify.json")
    registration = read_json(HERE / "input_registration_r2.json")
    g2 = read_json(EVIDENCE / "g2-minimal-repro-r2.json")
    mutations = read_json(EVIDENCE / "mutation-results-r2.json")
    replay = read_json(EVIDENCE / "replay-vs-r1-diff.json")
    r1_tests = junit_counts(EVIDENCE / "pytest-r1.xml")
    r2_tests = junit_counts(EVIDENCE / "pytest-r2.xml")

    f1_checks = [c for c in g2["checks"] if c["name"].startswith("F1")]
    f2_checks = [c for c in g2["checks"] if c["name"].startswith("F2")]
    source_mutations = mutations["source_mutations"]
    registration_mutations = mutations["registration_mutations"]

    metrics = {
        "task": "ainerzero.V9.G5",
        "agent": "deepseek-flash-a7k2",
        "date": "2026-10-20",
        "scope": {"cpu_only": True, "gpu": False, "model_budget": 0, "model_calls": 0,
                  "training_runs": 0, "downloads": 0, "installs": 0, "paid_calls": 0,
                  "files_modified": ["src/ainerzero/v9/geometry/belief.py",
                                     "src/ainerzero/v9/geometry/gravity.py",
                                     "src/ainerzero/v9/geometry/pose_graph.py",
                                     "src/ainerzero/v9/geometry/README.md"],
                  "files_added": ["tests/v9/geometry/test_geometry_r2.py",
                                  "reports/V9-G1/r2/"]},
        "f1_semidefinite_relative_tolerance": {
            "status": "fixed",
            "relative_tolerance": "tol = 1e-12 * max(1, ||M||_2)（belief.PSD_RELATIVE_TOL）",
            "exact_psd_rank_deficient_accepted": all(c["green"] for c in f1_checks),
            "checks": f1_checks,
            "pose_graph_clamp": "eigh 后把 [-tol*max(1,||M||_2), 0) 的特征值截为 0 再开方",
            "fail_closed_checks": "缺锚/断图/剩余方向未观测仍抛 ObservabilityError",
        },
        "f2_gravity_reference_direction": {
            "status": "fixed",
            "criterion": "先拒非有限值与精确零向量，再按 |sin theta| < 1e-9 拒绝（gravity.HORIZONTAL_SIN_TOL）",
            "scale_independent": all(c["green"] for c in f2_checks),
            "checks": f2_checks,
            "parallel_reference_still_rejected": True,
        },
        "f3_input_reregistration": {
            "status": "re-registered; documents enforced without exemption",
            "documents": {entry["path"]: {"old_sha256": entry["old_sha256"],
                                          "new_sha256": entry["new_sha256"],
                                          "s0_math_changed": entry["s0_math_changed"]}
                          for entry in registration["documents"]},
            "section_diff": {doc: {"sections": data["sections"],
                                   "s0_math_changed": data["s0_math_changed"]}
                             for doc, data in verify["sections"].items()},
            "survey_appended_lines": verify["survey_appended_lines"],
            "code_inputs_still_enforced": verify["code_inputs"],
            "r1_evidence_freeze": verify["r1_evidence"],
            "r1_registration_sha256": registration["r1_registration"]["sha256"],
            "input_registration_r2_sha256": verify["registration_sha256"],
            "section_changes_sha256": verify["section_changes_sha256"],
        },
        "tests": {
            "r1_delivered_49": {"file": "tests/v9/geometry/test_geometry.py", **r1_tests},
            "r2_new": {"file": "tests/v9/geometry/test_geometry_r2.py", **r2_tests},
        },
        "g2_minimal_repro_f1_f2": {"green": g2["green"],
                                   "f4_out_of_scope": g2.get("f4_out_of_scope")},
        "mutation_controls": {
            "controls_green": mutations["all_controls_green"],
            "source_mutations_red": sum(1 for item in source_mutations if item["red"]),
            "source_mutations_total": len(source_mutations),
            "registration_mutations_red": sum(1 for item in registration_mutations if item["red"]),
            "registration_mutations_total": len(registration_mutations),
            "all_ok": mutations["ok"],
            "sandbox": mutations["sandbox"],
        },
        "reference_replay_r2_gate": replay,
        "source_sha256": {
            "src/ainerzero/v9/geometry/belief.py": sha256_file(ROOT / "src/ainerzero/v9/geometry/belief.py"),
            "src/ainerzero/v9/geometry/gravity.py": sha256_file(ROOT / "src/ainerzero/v9/geometry/gravity.py"),
            "src/ainerzero/v9/geometry/pose_graph.py": sha256_file(ROOT / "src/ainerzero/v9/geometry/pose_graph.py"),
            "src/ainerzero/v9/geometry/README.md": sha256_file(ROOT / "src/ainerzero/v9/geometry/README.md"),
            "tests/v9/geometry/test_geometry_r2.py": sha256_file(
                ROOT / "tests/v9/geometry/test_geometry_r2.py"),
            "reports/V9-G1/r2/build_r2_registration.py": sha256_file(HERE / "build_r2_registration.py"),
            "reports/V9-G1/r2/verify_registration_r2.py": sha256_file(HERE / "verify_registration_r2.py"),
            "reports/V9-G1/r2/run_reference_r2.py": sha256_file(HERE / "run_reference_r2.py"),
            "reports/V9-G1/r2/run_mutations_r2.py": sha256_file(HERE / "run_mutations_r2.py"),
        },
        "failures_and_unverified": [
            "G2 F4（SE2/SE3.exp 超大角泄漏 OverflowError）不在本卡范围，未修；本卡未改变该行为，r2 脚本只报告状态。",
            "一般非线性 SE(2)/SE(3) EKF 全路径确定性界、统计校准（NEES）未验证，G1 亦未声明。",
            "测试通过不等于能力通过；本卡不构成 S1 科学门、训练授权或能力晋升。",
            "r1 49 项是作者回归测试的重跑，不是新的独立复核。",
        ],
        "evidence_dir": "reports/V9-G1/r2/evidence/",
    }
    (HERE / "metrics.json").write_text(json.dumps(metrics, ensure_ascii=False, indent=2) + "\n",
                                       encoding="utf-8")
    print(json.dumps({
        "r1_tests": r1_tests, "r2_tests": r2_tests,
        "g2_minimal_repro_green": g2["green"],
        "source_mutations_red": f"{sum(1 for i in source_mutations if i['red'])}/{len(source_mutations)}",
        "registration_mutations_red":
            f"{sum(1 for i in registration_mutations if i['red'])}/{len(registration_mutations)}",
        "replay_references_equal_r1": replay["references_equal"],
        "r1_evidence_entries_ok": verify["r1_evidence"]["evidence_entries"],
        "metrics": "reports/V9-G1/r2/metrics.json",
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
