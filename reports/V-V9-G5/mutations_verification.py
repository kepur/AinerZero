#!/usr/bin/env python3
"""独立复核“故意改坏必须变红”对照套件（reports/V-V9-G5/mutations_verification.py）。

通过在 /tmp 沙盒中改坏源码副本，验证 independent_verification.py 中的 7 个不利反例断言有效性：
1. control（无改坏）：必须全绿 exit 0；
2. 每项故意注入的缺陷（mutations）：必须真实变红（exit != 0）；
真实源码保持只读，不被任何修改。
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
GEOMETRY = ROOT / "src" / "ainerzero" / "v9" / "geometry"
VERIFY_SCRIPT = HERE / "independent_verification.py"
PYTHON = ROOT / ".venv-ainerzero" / "bin" / "python"
EVIDENCE = HERE / "evidence"
SANDBOX = Path("/tmp") / f"ainerzero-v9g6-verify-mutation-{time.strftime('%Y%m%dT%H%M%S')}"

SOURCE_FILES = (
    "belief.py",
    "gravity.py",
    "pose_graph.py",
    "lie.py",
    "canonical.py",
    "__init__.py",
    "README.md",
)

# 变异定义：name -> (相对 geometry 文件, 原文本, 替换文本)
MUTATIONS = {
    "m1_psd_revert_to_zero_tol": (
        "belief.py",
        "        if smallest < -psd_tolerance(p):",
        "        if smallest < 0:",
    ),
    "m2_psd_excessive_loose_tol": (
        "belief.py",
        "PSD_RELATIVE_TOL = 1e-12",
        "PSD_RELATIVE_TOL = 1e-3",
    ),
    "m3_pose_graph_remove_clamp": (
        "pose_graph.py",
        "            eig = np.where(negative, 0.0, eig)",
        "            eig = eig  # mutated: no clamp",
    ),
    "m4_pose_graph_bypass_observability": (
        "pose_graph.py",
        '        if rank != len(columns):\n            raise ObservabilityError(f"remaining unobserved directions: rank {rank}/{len(columns)}")',
        "        if False:\n            pass  # mutated: bypass check",
    ),
    "m5_gravity_revert_absolute_norm": (
        "gravity.py",
        "        if sin_theta < HORIZONTAL_SIN_TOL:",
        "        if np.linalg.norm(x) < 1e-12:",
    ),
    "m6_gravity_skip_nonzero_check": (
        "gravity.py",
        "        if h_norm == 0:",
        "        if False:",
    ),
}


def prepare_sandbox() -> Path:
    src_root = SANDBOX / "src"
    if src_root.exists():
        shutil.rmtree(src_root)
    geom_target = src_root / "ainerzero" / "v9" / "geometry"
    geom_target.mkdir(parents=True)
    shutil.copy2(ROOT / "src" / "ainerzero" / "__init__.py", src_root / "ainerzero" / "__init__.py")
    for fname in SOURCE_FILES:
        shutil.copy2(GEOMETRY / fname, geom_target / fname)
    return src_root


def run_test(env: dict) -> subprocess.CompletedProcess:
    return subprocess.run(
        [str(PYTHON), "-B", str(VERIFY_SCRIPT)],
        cwd=str(ROOT),
        env=env,
        capture_output=True,
        text=True,
        timeout=180,
    )


def main():
    SANDBOX.mkdir(parents=True, exist_ok=True)
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    env = dict(
        os.environ,
        PYTHONPATH=str(SANDBOX / "src"),
        PYTHONDONTWRITEBYTECODE="1",
    )

    results: dict = {
        "suite": "V9.G6 独立复核故意改坏变红对照套件",
        "sandbox": str(SANDBOX),
        "control": {},
        "mutations": [],
        "all_controls_green": False,
        "all_mutations_red": False,
        "ok": False,
    }

    # 1. 对照组：未改坏的沙盒副本必须全绿通过 (exit 0)
    prepare_sandbox()
    control_proc = run_test(env)
    control_passed = (control_proc.returncode == 0)
    results["control"] = {
        "exit_code": control_proc.returncode,
        "passed": control_passed,
        "stdout_tail": control_proc.stdout[-500:],
    }
    print(f"[{'GREEN' if control_passed else 'RED(CONTROL_FAILED)'}] control_unmutated: exit={control_proc.returncode}")
    if not control_passed:
        print(control_proc.stderr, file=sys.stderr)

    # 2. 依次测试每个故意改坏项，期望全部变红 (exit != 0)
    mutations_ok = True
    for name, (fname, old_text, new_text) in MUTATIONS.items():
        prepare_sandbox()
        target_file = SANDBOX / "src" / "ainerzero" / "v9" / "geometry" / fname
        content = target_file.read_text(encoding="utf-8")
        if content.count(old_text) != 1:
            raise SystemExit(f"Mutation {name} 失败：目标串在 {fname} 出现 {content.count(old_text)} 次")
        target_file.write_text(content.replace(old_text, new_text, 1), encoding="utf-8")

        proc = run_test(env)
        red = (proc.returncode != 0)
        log_path = EVIDENCE / f"mutation_{name}.log"
        log_path.write_text(f"Command: python {VERIFY_SCRIPT}\n\nSTDOUT:\n{proc.stdout}\n\nSTDERR:\n{proc.stderr}", encoding="utf-8")

        results["mutations"].append({
            "name": name,
            "target": f"src/ainerzero/v9/geometry/{fname}",
            "mutation": f"{old_text.strip()} -> {new_text.strip()}",
            "exit_code": proc.returncode,
            "red": red,
            "log": f"evidence/{log_path.name}",
        })
        print(f"[{'RED(EXPECTED)' if red else 'GREEN(MUTATION_SURVIVED!)'}] {name}: exit={proc.returncode}")
        if not red:
            mutations_ok = False

    results["all_controls_green"] = control_passed
    results["all_mutations_red"] = mutations_ok
    results["ok"] = control_passed and mutations_ok

    (EVIDENCE / "mutation_results_v9g6.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print("---")
    print(f"故意改坏变红对照总结: control_green={control_passed}, all_mutations_red={mutations_ok}")
    sys.exit(0 if results["ok"] else 1)


if __name__ == "__main__":
    main()
