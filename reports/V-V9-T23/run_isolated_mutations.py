"""Independent non-author 4-gate isolated source mutation verification suite for T23.

Auditor: gemini-kzer (non-author)
Guarantees:
- Zero mutations in working tree
- Completely isolated in temp directories
- Does NOT import author's test suite (builds independent 3-way control runner)
- Each mutation is tested under 3-way control:
  1. Positive legal case: Baseline PASS, Mutant PASS
  2. Target bad case: Baseline REJECT, Mutant IMPROPER PASS (TURNS RED)
  3. Unrelated bad case: Baseline REJECT, Mutant REJECT (retains other guard)
- Verified inverse mutation restores byte-identical source SHA256
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
PYTHON_EXE = REPO_ROOT / ".venv/bin/python"


# Harness script executed inside the isolated mutated environment
ISOLATED_TEST_HARNESS_CODE = """
import sys
import os
import argparse
import tempfile
from pathlib import Path

from ainerzero.v9.teachers.benchmark_commands import teacher_benchmark_command
from ainerzero.v9.teachers.benchmark_protocol import (
    EXIT_COMPLETED,
    EXIT_REFUSED_APPROVAL,
    EXIT_REFUSED_BUDGET,
    EXIT_REFUSED_RESOURCE,
    T4_APPROVAL_KEYWORD,
    T4_APPROVAL_SECTION,
    T4_APPROVAL_TARGET,
)
from ainerzero.runtime.lifecycle import RunStore


class MockAdapter:
    def run_benchmark(self, spec):
        return {"status": "completed", "mock": True}


def make_valid_log(path: Path) -> Path:
    path.write_text(
        f"# Research Log\\n\\n## {T4_APPROVAL_SECTION}：批准\\n「{T4_APPROVAL_KEYWORD}」批准对象：{T4_APPROVAL_TARGET}\\n",
        encoding="utf-8"
    )
    return path


def run_test_case(gate_name: str, case_type: str) -> dict:
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        valid_log = make_valid_log(tmp / "VALID_LOG.md")
        store_path = tmp / "runs.db"
        lock_path = tmp / "worker.lock"
        weights_root = tmp / "weights"

        adapter = MockAdapter()

        if gate_name == "approval":
            if case_type == "positive_legal":
                args = argparse.Namespace(
                    mode="run", model="vjepa", wall_budget_seconds="500.0",
                    research_log=str(valid_log), store_path=str(store_path),
                    lock_path=str(lock_path), weights_root=str(weights_root)
                )
                rep, code = teacher_benchmark_command(args, adapter=adapter)
                return {"success": (code == EXIT_COMPLETED), "exit_code": code}

            elif case_type == "target_bad":
                # Section present, but approval keyword is missing
                bad_approval_log = tmp / "MISSING_KEYWORD_LOG.md"
                bad_approval_log.write_text(
                    f"# Log\\n## {T4_APPROVAL_SECTION}：待办\\n批准对象：{T4_APPROVAL_TARGET}，等待讨论。\\n",
                    encoding="utf-8"
                )
                args = argparse.Namespace(
                    mode="run", model="vjepa", wall_budget_seconds="500.0",
                    research_log=str(bad_approval_log), store_path=str(store_path),
                    lock_path=str(lock_path), weights_root=str(weights_root)
                )
                rep, code = teacher_benchmark_command(args, adapter=adapter)
                # Baseline rejects with EXIT_REFUSED_APPROVAL (3). If mutant accepts, code == EXIT_COMPLETED (0).
                return {"rejected": (code == EXIT_REFUSED_APPROVAL), "exit_code": code}

            elif case_type == "unrelated_bad":
                # Approval is valid, but budget exceeds per-run limit (650 > 600)
                args = argparse.Namespace(
                    mode="run", model="vjepa", wall_budget_seconds="650.0",
                    research_log=str(valid_log), store_path=str(store_path),
                    lock_path=str(lock_path), weights_root=str(weights_root)
                )
                rep, code = teacher_benchmark_command(args, adapter=adapter)
                return {"rejected": (code == EXIT_REFUSED_BUDGET), "exit_code": code}

        elif gate_name == "per_run_budget":
            if case_type == "positive_legal":
                args = argparse.Namespace(
                    mode="run", model="vjepa", wall_budget_seconds="500.0",
                    research_log=str(valid_log), store_path=str(store_path),
                    lock_path=str(lock_path), weights_root=str(weights_root)
                )
                rep, code = teacher_benchmark_command(args, adapter=adapter)
                return {"success": (code == EXIT_COMPLETED), "exit_code": code}

            elif case_type == "target_bad":
                # Requested budget exceeds per-run limit (650.0 > 600.0)
                args = argparse.Namespace(
                    mode="run", model="vjepa", wall_budget_seconds="650.0",
                    research_log=str(valid_log), store_path=str(store_path),
                    lock_path=str(lock_path), weights_root=str(weights_root)
                )
                rep, code = teacher_benchmark_command(args, adapter=adapter)
                # Baseline rejects with EXIT_REFUSED_BUDGET (5). If mutant accepts, code == EXIT_COMPLETED (0).
                return {"rejected": (code == EXIT_REFUSED_BUDGET), "exit_code": code}

            elif case_type == "unrelated_bad":
                # Budget is 500.0s, but approval is missing
                bad_log = tmp / "BAD_LOG.md"
                bad_log.write_text("# Bad\\n", encoding="utf-8")
                args = argparse.Namespace(
                    mode="run", model="vjepa", wall_budget_seconds="500.0",
                    research_log=str(bad_log), store_path=str(store_path),
                    lock_path=str(lock_path), weights_root=str(weights_root)
                )
                rep, code = teacher_benchmark_command(args, adapter=adapter)
                return {"rejected": (code == EXIT_REFUSED_APPROVAL), "exit_code": code}

        elif gate_name == "cumulative_budget":
            if case_type == "positive_legal":
                # Pre-reserve 1000s in RunStore, request 500s -> 1500s <= 1800s
                with RunStore(store_path) as s:
                    s.create_run({"model": "vjepa", "budget": {"max_wall_seconds": 1800, "timezone": "UTC"}}, request_id="req1", run_id="run1")
                    s.transition("run1", "initializing")
                    s.transition("run1", "validating")
                    s.consume("run1", active_seconds=1000.0)
                args = argparse.Namespace(
                    mode="run", model="vjepa", wall_budget_seconds="500.0",
                    research_log=str(valid_log), store_path=str(store_path),
                    lock_path=str(lock_path), weights_root=str(weights_root)
                )
                rep, code = teacher_benchmark_command(args, adapter=adapter)
                return {"success": (code == EXIT_COMPLETED), "exit_code": code}

            elif case_type == "target_bad":
                # Pre-reserve 1500s in RunStore, request 400s -> 1900s > 1800s
                with RunStore(store_path) as s:
                    s.create_run({"model": "vjepa", "budget": {"max_wall_seconds": 1800, "timezone": "UTC"}}, request_id="req1", run_id="run1")
                    s.transition("run1", "initializing")
                    s.transition("run1", "validating")
                    s.consume("run1", active_seconds=1500.0)
                args = argparse.Namespace(
                    mode="run", model="vjepa", wall_budget_seconds="400.0",
                    research_log=str(valid_log), store_path=str(store_path),
                    lock_path=str(lock_path), weights_root=str(weights_root)
                )
                rep, code = teacher_benchmark_command(args, adapter=adapter)
                with RunStore(store_path) as s:
                    runs = s.list_runs()
                # Baseline rejects at Step 5 with 'Cumulative wall budget exceeded' and len(runs) == 1.
                # Mutant skips Step 5, creates a 2nd run in RunStore, and fails later at Step 6.
                step5_caught = (
                    code == EXIT_REFUSED_BUDGET
                    and "Cumulative wall budget exceeded" in rep.get("error", "")
                    and len(runs) == 1
                )
                return {"rejected": step5_caught, "exit_code": code, "error": rep.get("error", "")}

            elif case_type == "unrelated_bad":
                # Approval is missing
                bad_log = tmp / "BAD_LOG.md"
                bad_log.write_text("# Bad\\n", encoding="utf-8")
                args = argparse.Namespace(
                    mode="run", model="vjepa", wall_budget_seconds="500.0",
                    research_log=str(bad_log), store_path=str(store_path),
                    lock_path=str(lock_path), weights_root=str(weights_root)
                )
                rep, code = teacher_benchmark_command(args, adapter=adapter)
                return {"rejected": (code == EXIT_REFUSED_APPROVAL), "exit_code": code}

        elif gate_name == "resource_rss":
            from ainerzero.v9.teachers.benchmark import check_resource_limits, BenchmarkResourceRefused
            if case_type == "positive_legal":
                # Standard limit 32.0 GiB
                res = check_resource_limits(max_rss_gib=32.0)
                return {"success": (res["status"] == "ok"), "exit_code": EXIT_COMPLETED}

            elif case_type == "target_bad":
                # Low limit 0.0001 GiB forces check_resource_limits to raise BenchmarkResourceRefused
                try:
                    check_resource_limits(max_rss_gib=0.0001)
                    # Improper pass!
                    return {"rejected": False, "exit_code": EXIT_COMPLETED}
                except BenchmarkResourceRefused:
                    return {"rejected": True, "exit_code": EXIT_REFUSED_RESOURCE}

            elif case_type == "unrelated_bad":
                # Missing approval
                bad_log = tmp / "BAD_LOG.md"
                bad_log.write_text("# Bad\\n", encoding="utf-8")
                args = argparse.Namespace(
                    mode="run", model="vjepa", wall_budget_seconds="500.0",
                    research_log=str(bad_log), store_path=str(store_path),
                    lock_path=str(lock_path), weights_root=str(weights_root)
                )
                rep, code = teacher_benchmark_command(args, adapter=adapter)
                return {"rejected": (code == EXIT_REFUSED_APPROVAL), "exit_code": code}

        raise ValueError(f"Unknown gate_name={gate_name} or case_type={case_type}")


if __name__ == "__main__":
    import json
    gate = sys.argv[1]
    case = sys.argv[2]
    res = run_test_case(gate, case)
    print(json.dumps(res))
"""


MUTATIONS = [
    {
        "id": "MUT-01",
        "name": "approval_gate_sabotage",
        "gate_name": "approval",
        "target_file": "ainerzero/v9/teachers/benchmark.py",
        "target_str": "if T4_APPROVAL_KEYWORD not in section_text:",
        "mutant_str": "if False and T4_APPROVAL_KEYWORD not in section_text:",
        "description": "Bypasses RESEARCH_LOG approval keyword check",
    },
    {
        "id": "MUT-02",
        "name": "per_run_budget_gate_sabotage",
        "gate_name": "per_run_budget",
        "target_file": "ainerzero/v9/teachers/benchmark.py",
        "target_str": "if spec.wall_budget_seconds > T4_MAX_PER_RUN_WALL_SECONDS:",
        "mutant_str": "if False and spec.wall_budget_seconds > T4_MAX_PER_RUN_WALL_SECONDS:",
        "description": "Bypasses 600s per-run wall budget protection",
    },
    {
        "id": "MUT-03",
        "name": "cumulative_budget_gate_sabotage",
        "gate_name": "cumulative_budget",
        "target_file": "ainerzero/v9/teachers/benchmark.py",
        "target_str": "cumulative_reserved + spec.wall_budget_seconds\n                    > T4_MAX_CUMULATIVE_WALL_SECONDS",
        "mutant_str": "False and (\n                        cumulative_reserved + spec.wall_budget_seconds\n                        > T4_MAX_CUMULATIVE_WALL_SECONDS\n                    )",
        "description": "Bypasses 1800s cumulative RunStore budget protection",
    },
    {
        "id": "MUT-04",
        "name": "resource_gate_sabotage",
        "gate_name": "resource_rss",
        "target_file": "ainerzero/v9/teachers/benchmark.py",
        "target_str": "if rss_bytes > max_rss_bytes:",
        "mutant_str": "if False and rss_bytes > max_rss_bytes:",
        "description": "Bypasses 32 GiB process RSS protection",
    },
]


def run_harness_in_isolated_env(python_path: Path, gate_name: str, case_type: str) -> dict:
    """Run test harness against the specified pythonpath."""
    cmd = [
        str(PYTHON_EXE),
        "-c",
        ISOLATED_TEST_HARNESS_CODE,
        gate_name,
        case_type,
    ]
    env = os.environ.copy()
    env["PYTHONPATH"] = str(python_path)

    proc = subprocess.run(
        cmd,
        cwd=str(REPO_ROOT),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    if proc.returncode != 0:
        return {"error": f"Proc returned {proc.returncode}: {proc.stderr}"}
    try:
        return json.loads(proc.stdout.strip().splitlines()[-1])
    except Exception as exc:
        return {"error": f"Failed to parse JSON: {proc.stdout} ({exc})"}


def execute_mutation_verification(mutation: dict) -> dict:
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_src = Path(tmpdir) / "src"
        shutil.copytree(REPO_ROOT / "src", tmp_src)

        target_file = tmp_src / mutation["target_file"]
        original_content = target_file.read_text(encoding="utf-8")
        original_sha = hashlib.sha256(original_content.encode("utf-8")).hexdigest()

        if mutation["target_str"] not in original_content:
            raise ValueError(f"Target string not found in {mutation['target_file']}")

        # 1. Test unmutated baseline
        base_pos = run_harness_in_isolated_env(tmp_src, mutation["gate_name"], "positive_legal")
        base_target = run_harness_in_isolated_env(tmp_src, mutation["gate_name"], "target_bad")
        base_unrel = run_harness_in_isolated_env(tmp_src, mutation["gate_name"], "unrelated_bad")

        # Baseline checks:
        baseline_ok = (
            base_pos.get("success") is True
            and base_target.get("rejected") is True
            and base_unrel.get("rejected") is True
        )

        # 2. Apply mutation
        mutated_content = original_content.replace(mutation["target_str"], mutation["mutant_str"], 1)
        target_file.write_text(mutated_content, encoding="utf-8")

        # 3. Test mutated code
        mut_pos = run_harness_in_isolated_env(tmp_src, mutation["gate_name"], "positive_legal")
        mut_target = run_harness_in_isolated_env(tmp_src, mutation["gate_name"], "target_bad")
        mut_unrel = run_harness_in_isolated_env(tmp_src, mutation["gate_name"], "unrelated_bad")

        # Under mutation:
        # - Positive legal must STILL pass (not broken)
        # - Target bad must FAIL closedness (improperly passes / turns red!)
        # - Unrelated bad must STILL be rejected (isolation guarantee)
        positive_still_passes = mut_pos.get("success") is True
        target_turned_red = mut_target.get("rejected") is False  # Turned red (no longer rejected!)
        unrelated_still_rejected = mut_unrel.get("rejected") is True

        mutation_verified = positive_still_passes and target_turned_red and unrelated_still_rejected

        # 4. Test inverse mutation restores exact SHA
        restored_content = mutated_content.replace(mutation["mutant_str"], mutation["target_str"], 1)
        target_file.write_text(restored_content, encoding="utf-8")
        restored_sha = hashlib.sha256(restored_content.encode("utf-8")).hexdigest()
        sha_restored = (restored_sha == original_sha)

        return {
            "id": mutation["id"],
            "name": mutation["name"],
            "description": mutation["description"],
            "baseline_healthy": baseline_ok,
            "positive_legal_passed": positive_still_passes,
            "target_bad_turned_red": target_turned_red,
            "unrelated_bad_retained_rejection": unrelated_still_rejected,
            "inverse_sha_restored": sha_restored,
            "overall_mutation_passed": mutation_verified and sha_restored and baseline_ok,
            "details": {
                "baseline": {"pos": base_pos, "target": base_target, "unrelated": base_unrel},
                "mutant": {"pos": mut_pos, "target": mut_target, "unrelated": mut_unrel},
            },
        }


def main():
    print("=" * 70)
    print("Running Non-Author Isolated Source Mutation Verification (4 Gates, 3-Way)")
    print("=" * 70)

    results = []
    all_ok = True

    for mut in MUTATIONS:
        print(f"\n[TESTING] {mut['id']}: {mut['name']} ({mut['description']})")
        res = execute_mutation_verification(mut)
        results.append(res)

        status_str = "PASS (3-way verified & turned red)" if res["overall_mutation_passed"] else "FAIL"
        print(f"  -> Result: {status_str}")
        print(f"     Positive Legal: {res['positive_legal_passed']}")
        print(f"     Target Bad Turned Red: {res['target_bad_turned_red']}")
        print(f"     Unrelated Bad Retained: {res['unrelated_bad_retained_rejection']}")
        print(f"     Inverse SHA Restored: {res['inverse_sha_restored']}")

        if not res["overall_mutation_passed"]:
            all_ok = False

    output_path = REPO_ROOT / "reports/V-V9-T23/isolated_mutations_results.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(results, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"\nResults saved to {output_path}")

    if not all_ok:
        print("Isolated Mutation Verification FAILED!")
        sys.exit(1)
    else:
        print("Isolated Mutation Verification PASSED: 4/4 genuine mutations verified under 3-way control.")


if __name__ == "__main__":
    main()
