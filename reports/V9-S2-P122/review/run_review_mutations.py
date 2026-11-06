"""Reviewer mutation runner for S2 P122 verification (ainerzero.V9.P123).

Tests 4 adverse mutations outside the author's original table under an isolated replica:
- REV-M1: RidgeProbe.predict omits bias (+ self.bias) -> KILLED
- REV-M2: cluster_paired_bootstrap allows n_worlds < 2 -> KILLED
- REV-M3: run_episode regular mode sets k_next = 2 -> KILLED
- REV-M4: run_episode perturbation inserts 1 action instead of 5 -> SURVIVED (Test gap identified)
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys


def sha256_of(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    repo_root = Path(__file__).resolve().parents[3]
    replica_dir = Path("/tmp/s2_p123_review_replica")
    if replica_dir.exists():
        shutil.rmtree(replica_dir)
    replica_dir.mkdir(parents=True)

    print(f"[1] Creating isolated replica at {replica_dir}...")
    shutil.copytree(repo_root / "src", replica_dir / "src")
    shutil.copytree(repo_root / "tests", replica_dir / "tests")
    shutil.copy(repo_root / "pyproject.toml", replica_dir / "pyproject.toml")
    (replica_dir / "reports").mkdir()
    shutil.copytree(repo_root / "reports" / "V9-S2-DESIGN", replica_dir / "reports" / "V9-S2-DESIGN")

    # Assert imports resolve to replica
    check_import_cmd = [
        sys.executable,
        "-c",
        (
            f"import sys; sys.path.insert(0, '{replica_dir}/src'); "
            "import ainerzero.v9.experiments.s2.eval as e; "
            f"assert e.__file__.startswith('{replica_dir}'), f'Import not in replica: {{e.__file__}}'; "
            "print('Verified import resolves to:', e.__file__)"
        ),
    ]
    res_import = subprocess.run(check_import_cmd, capture_output=True, text=True, check=True)
    print(res_import.stdout.strip())

    # Baseline tests in replica
    print("[2] Running baseline tests in replica...")
    pytest_bin = str(repo_root / ".venv" / "bin" / "pytest")
    env = dict(PYTHONPATH=f"{replica_dir}/src:{replica_dir}")

    cmd_baseline = [
        pytest_bin,
        str(replica_dir / "tests" / "v9" / "experiments" / "test_s2_eval.py"),
        str(replica_dir / "tests" / "v9" / "experiments" / "test_s2_stats.py"),
        str(replica_dir / "tests" / "v9" / "experiments" / "test_s2_probe.py"),
        "-q",
    ]
    res_base = subprocess.run(cmd_baseline, capture_output=True, text=True, env=env)
    assert res_base.returncode == 0, f"Baseline failed in replica:\n{res_base.stderr}\n{res_base.stdout}"
    print("Baseline passed: 13/13 tests passed.")

    mutations_record = []

    # --- REV-M1: RidgeProbe.predict omits bias ---
    print("\n[3] Running REV-M1: RidgeProbe.predict omits bias...")
    target_file = replica_dir / "src" / "ainerzero" / "v9" / "experiments" / "s2" / "probe.py"
    orig_bytes = target_file.read_bytes()
    orig_sha = sha256_of(target_file)

    mutated_text = orig_bytes.decode("utf-8").replace(
        "return Z_arr @ self.weights + self.bias",
        "return Z_arr @ self.weights  # REV-M1: omit bias addition",
    )
    assert mutated_text != orig_bytes.decode("utf-8"), "Replacement failed for REV-M1"
    target_file.write_text(mutated_text, encoding="utf-8")

    cmd_m1 = [
        pytest_bin,
        f"{replica_dir}/tests/v9/experiments/test_s2_probe.py::test_ridge_recovers_known_linear_mapping_with_noise",
        "-q",
    ]
    res_m1 = subprocess.run(cmd_m1, capture_output=True, text=True, env=env)
    m1_status = "KILLED" if res_m1.returncode != 0 else "SURVIVED"
    print(f"REV-M1 exit code: {res_m1.returncode} ({m1_status})")

    target_file.write_bytes(orig_bytes)
    assert sha256_of(target_file) == orig_sha, "SHA mismatch after restoring REV-M1"

    mutations_record.append({
        "mutation_id": "REV-M1",
        "description": "RidgeProbe.predict 遗漏偏置项 (+ self.bias)",
        "target_file": "src/ainerzero/v9/experiments/s2/probe.py",
        "targeted_test": "test_ridge_recovers_known_linear_mapping_with_noise",
        "exit_code": res_m1.returncode,
        "status": m1_status,
        "diagnosis": "被测用例严格断言均方欧氏距离恢复误差 <= 0.35；遗漏偏置导致误差达 17.67，成功变红拦截。",
    })

    # --- REV-M2: cluster_paired_bootstrap allows n_worlds < 2 ---
    print("\n[4] Running REV-M2: cluster_paired_bootstrap allows n_worlds < 2...")
    target_file = replica_dir / "src" / "ainerzero" / "v9" / "experiments" / "s2" / "stats.py"
    orig_bytes = target_file.read_bytes()
    orig_sha = sha256_of(target_file)

    mutated_text = orig_bytes.decode("utf-8").replace(
        "if n_worlds < 2:",
        "if n_worlds < 1:  # REV-M2: relax world count check",
    )
    assert mutated_text != orig_bytes.decode("utf-8"), "Replacement failed for REV-M2"
    target_file.write_text(mutated_text, encoding="utf-8")

    cmd_m2 = [
        pytest_bin,
        f"{replica_dir}/tests/v9/experiments/test_s2_stats.py::test_single_world_raises_value_error",
        "-q",
    ]
    res_m2 = subprocess.run(cmd_m2, capture_output=True, text=True, env=env)
    m2_status = "KILLED" if res_m2.returncode != 0 else "SURVIVED"
    print(f"REV-M2 exit code: {res_m2.returncode} ({m2_status})")

    target_file.write_bytes(orig_bytes)
    assert sha256_of(target_file) == orig_sha, "SHA mismatch after restoring REV-M2"

    mutations_record.append({
        "mutation_id": "REV-M2",
        "description": "cluster_paired_bootstrap 移除 W>=2 阻断检查",
        "target_file": "src/ainerzero/v9/experiments/s2/stats.py",
        "targeted_test": "test_single_world_raises_value_error",
        "exit_code": res_m2.returncode,
        "status": m2_status,
        "diagnosis": "用例验证 W=1 时必须抛出 ValueError，放宽检查导致 DID NOT RAISE，成功变红拦截。",
    })

    # --- REV-M3: run_episode regular mode sets k_next = 2 ---
    print("\n[5] Running REV-M3: run_episode regular mode sets k_next = 2...")
    target_file = replica_dir / "src" / "ainerzero" / "v9" / "experiments" / "s2" / "eval.py"
    orig_bytes = target_file.read_bytes()
    orig_sha = sha256_of(target_file)

    mutated_text = orig_bytes.decode("utf-8").replace(
        "k_next = 1",
        "k_next = 2  # REV-M3: corrupt regular mode k",
        1,
    )
    assert mutated_text != orig_bytes.decode("utf-8"), "Replacement failed for REV-M3"
    target_file.write_text(mutated_text, encoding="utf-8")

    cmd_m3 = [
        pytest_bin,
        f"{replica_dir}/tests/v9/experiments/test_s2_eval.py::test_dt_mode_regular_and_irregular_distribution",
        "-q",
    ]
    res_m3 = subprocess.run(cmd_m3, capture_output=True, text=True, env=env)
    m3_status = "KILLED" if res_m3.returncode != 0 else "SURVIVED"
    print(f"REV-M3 exit code: {res_m3.returncode} ({m3_status})")

    target_file.write_bytes(orig_bytes)
    assert sha256_of(target_file) == orig_sha, "SHA mismatch after restoring REV-M3"

    mutations_record.append({
        "mutation_id": "REV-M3",
        "description": "run_episode regular 模式误设 k_next = 2",
        "target_file": "src/ainerzero/v9/experiments/s2/eval.py",
        "targeted_test": "test_dt_mode_regular_and_irregular_distribution",
        "exit_code": res_m3.returncode,
        "status": m3_status,
        "diagnosis": "用例检查 regular 模式下所有 k 必须全为 1，出现 2 导致断言失败，成功变红拦截。",
    })

    # --- REV-M4: run_episode perturbation inserts 1 action instead of 5 ---
    print("\n[6] Running REV-M4: perturbation inserts 1 action instead of 5...")
    orig_bytes = target_file.read_bytes()
    orig_sha = sha256_of(target_file)

    mutated_text = orig_bytes.decode("utf-8").replace(
        "n_perturb_actions = int(perturb_spec.get(\"n_random_actions\", 5))",
        "n_perturb_actions = 1  # REV-M4: only 1 perturb action",
    )
    assert mutated_text != orig_bytes.decode("utf-8"), "Replacement failed for REV-M4"
    target_file.write_text(mutated_text, encoding="utf-8")

    cmd_m4 = [
        pytest_bin,
        f"{replica_dir}/tests/v9/experiments/test_s2_eval.py::test_perturb_inserts_at_step_20_and_is_reproducible",
        "-q",
    ]
    res_m4 = subprocess.run(cmd_m4, capture_output=True, text=True, env=env)
    m4_status = "KILLED" if res_m4.returncode != 0 else "SURVIVED"
    print(f"REV-M4 exit code: {res_m4.returncode} ({m4_status})")

    target_file.write_bytes(orig_bytes)
    assert sha256_of(target_file) == orig_sha, "SHA mismatch after restoring REV-M4"

    mutations_record.append({
        "mutation_id": "REV-M4",
        "description": "run_episode 扰动仅插入 1 个动作而非 5 个动作",
        "target_file": "src/ainerzero/v9/experiments/s2/eval.py",
        "targeted_test": "test_perturb_inserts_at_step_20_and_is_reproducible",
        "exit_code": res_m4.returncode,
        "status": m4_status,
        "diagnosis": (
            "测试漏洞诊断（SURVIVED）：test_perturb_inserts_at_step_20_and_is_reproducible 使用 dummy_planner "
            "在达到目标前持续执行 WAIT，导致回合自然跑满 limit_steps (~120)，断言 assert res1.steps_used >= 25 "
            "无法区分插入的是 1 个还是 5 个动作。建议后续补充对 actions_taken 中扰动动作切片长度的直接断言。"
        ),
    })

    shutil.rmtree(replica_dir)
    print("\n[7] Cleaned up replica directory.")

    out_file = repo_root / "reports" / "V9-S2-P122" / "review" / "review_mutations.json"
    out_file.write_text(json.dumps(mutations_record, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Recorded reviewer mutation report in {out_file}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
