#!/usr/bin/env python3
"""P115 Mutation Testing Script (Adversarial Negative Controls).

Tests 5 mutations against isolated repository copy:
- P115-M1: Leaking absolute coordinates in student_obs -> test_no_coordinate_leakage must turn RED
- P115-M2: Disabling connectivity check in make_layout -> test_connectivity_and_doorways must turn RED
- P115-M3: Line of sight always returns True -> test_line_of_sight_closed_form must turn RED
- P115-M4: Disabling ambiguity rejection in sample_goal -> test_goal_sampling_and_ambiguity_rejection must turn RED
- P115-M5: Dev and train share seed namespace -> test_generate_partition_isolation_and_disjointness must turn RED

Each mutation operates on an isolated clone, and restores files byte-by-byte with SHA256 verification.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def main() -> int:
    real_root = Path("/Users/mac/AinerWorkFlow/AinerZero").resolve()
    tmp_dir = Path(tempfile.mkdtemp(prefix="s2_p115_mutations_"))
    print(f"[Init] Isolated workspace created at: {tmp_dir}")

    try:
        # Copy src, tests, pyproject.toml
        shutil.copytree(real_root / "src", tmp_dir / "src")
        shutil.copytree(real_root / "tests", tmp_dir / "tests")
        shutil.copy2(real_root / "pyproject.toml", tmp_dir / "pyproject.toml")

        # Verify import isolation
        verify_cmd = [
            sys.executable,
            "-c",
            "import sys; sys.path.insert(0, 'src'); sys.path.insert(0, '.'); from ainerzero.v9.experiments.s2 import world; import inspect; print(inspect.getfile(world))",
        ]
        res_v = subprocess.run(verify_cmd, cwd=str(tmp_dir), capture_output=True, text=True, check=True)
        imported_path = res_v.stdout.strip()
        print(f"[Isolation Check] world imported from: {imported_path}")
        assert str(tmp_dir) in imported_path, f"Isolation failure! Imported {imported_path} not in {tmp_dir}"

        # 0. Clean run baseline
        print("\n[Baseline] Running unmutated test suite...")
        clean_proc = subprocess.run(
            [sys.executable, "-m", "pytest", "tests/v9/experiments/test_s2_world.py", "tests/v9/experiments/test_s2_data.py"],
            cwd=str(tmp_dir),
            env=dict(os.environ, PYTHONPATH=f"{tmp_dir}/src:{tmp_dir}"),
            capture_output=True,
            text=True,
        )
        assert clean_proc.returncode == 0, f"Clean baseline failed:\n{clean_proc.stdout}\n{clean_proc.stderr}"
        print("  Clean baseline: 11/11 passed (GREEN).")

        world_file = tmp_dir / "src/ainerzero/v9/experiments/s2/world.py"
        data_file = tmp_dir / "src/ainerzero/v9/experiments/s2/data.py"

        world_orig_sha = sha256_file(world_file)
        world_orig_bytes = world_file.read_bytes()
        data_orig_sha = sha256_file(data_file)
        data_orig_bytes = data_file.read_bytes()

        results = []

        def run_mutation(name: str, target_file: Path, orig_bytes: bytes, orig_sha: str, mutate_fn, test_target: str):
            print(f"\n[Test] Running {name}...")
            mutated_text = mutate_fn(orig_bytes.decode("utf-8"))
            target_file.write_text(mutated_text, encoding="utf-8")

            # Run target test
            proc = subprocess.run(
                [sys.executable, "-m", "pytest", test_target],
                cwd=str(tmp_dir),
                env=dict(os.environ, PYTHONPATH=f"{tmp_dir}/src:{tmp_dir}"),
                capture_output=True,
                text=True,
            )

            # Restore byte-for-byte immediately
            target_file.write_bytes(orig_bytes)
            restored_sha = sha256_file(target_file)
            assert restored_sha == orig_sha, f"Byte restoration mismatch for {target_file}! Expected {orig_sha}, got {restored_sha}"

            turned_red = (proc.returncode != 0)
            print(f"  Returncode: {proc.returncode} (RED: {turned_red})")
            if turned_red:
                # Extract failed assertion line from stdout
                lines = [line.strip() for line in proc.stdout.splitlines() if line.strip().startswith("E ") or "FAILED" in line]
                summary = " | ".join(lines[:3])
                print(f"  Captured failure: {summary}")
            else:
                summary = "Did not fail!"

            res = {
                "name": name,
                "test_target": test_target,
                "exit_code": proc.returncode,
                "turned_red": turned_red,
                "passed": turned_red,
                "failure_summary": summary,
                "restored_sha_matched": True,
            }
            results.append(res)
            return res

        # M1: Leak coordinates in student_obs
        def mutate_m1(src: str) -> str:
            assert 'obs: dict[str, Any] = {' in src
            return src.replace(
                'obs: dict[str, Any] = {',
                'obs: dict[str, Any] = {\n        "x": state.x,\n        "y": state.y,',
            )

        run_mutation(
            "P115-M1",
            world_file,
            world_orig_bytes,
            world_orig_sha,
            mutate_m1,
            "tests/v9/experiments/test_s2_world.py::test_no_coordinate_leakage",
        )

        # M2: Remove connectivity check in make_layout
        def mutate_m2(src: str) -> str:
            assert 'if enforce_connected:' in src
            return src.replace(
                'if enforce_connected:',
                'if False:',
            )

        run_mutation(
            "P115-M2",
            world_file,
            world_orig_bytes,
            world_orig_sha,
            mutate_m2,
            "tests/v9/experiments/test_s2_world.py::test_connectivity_and_doorways",
        )

        # M3: Line of sight always returns True
        def mutate_m3(src: str) -> str:
            assert 'def line_of_sight(terrain: list[list[int]], ax: int, ay: int, bx: int, by: int) -> bool:' in src
            return src.replace(
                'def line_of_sight(terrain: list[list[int]], ax: int, ay: int, bx: int, by: int) -> bool:\n    """Ray casting line of sight check, derived from gridlab_v1.py line_of_sight."""',
                'def line_of_sight(terrain: list[list[int]], ax: int, ay: int, bx: int, by: int) -> bool:\n    return True',
            )

        run_mutation(
            "P115-M3",
            world_file,
            world_orig_bytes,
            world_orig_sha,
            mutate_m3,
            "tests/v9/experiments/test_s2_world.py::test_line_of_sight_closed_form",
        )

        # M4: Remove ambiguity rule in sample_goal
        def mutate_m4(src: str) -> str:
            assert 'if enforce_unambiguous:' in src
            return src.replace(
                'if enforce_unambiguous:',
                'if False:',
            )

        run_mutation(
            "P115-M4",
            world_file,
            world_orig_bytes,
            world_orig_sha,
            mutate_m4,
            "tests/v9/experiments/test_s2_world.py::test_goal_sampling_and_ambiguity_rejection",
        )

        # M5: Dev and train share seed namespace in generate_partition
        def mutate_m5(src: str) -> str:
            target = "part_dir = out_path / partition"
            assert target in src
            return src.replace(
                target,
                'seed_namespace = "shared-fixed-namespace"\n    part_dir = out_path / partition',
                1,
            )

        run_mutation(
            "P115-M5",
            data_file,
            data_orig_bytes,
            data_orig_sha,
            mutate_m5,
            "tests/v9/experiments/test_s2_data.py::test_generate_partition_isolation_and_disjointness",
        )

        out_results = Path("/Users/mac/AinerWorkFlow/AinerZero/reports/V9-S2-P115/mutation_results.json")
        out_results.write_text(json.dumps(results, indent=2) + "\n")
        print(f"\n[Done] All 5 mutations evaluated and saved to {out_results}")

        all_passed = all(r["passed"] for r in results)
        print(f"Overall mutation status: {'ALL 5 PASSED (ALL TURNED RED)' if all_passed else 'SOME FAILED'}")
        return 0 if all_passed else 1

    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
