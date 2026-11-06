#!/usr/bin/env python3
"""P115-r2 Mutation Testing Script (Adversarial Negative Controls).

Isolated copy of src/tests/pyproject.toml; each mutation restored byte-for-byte with SHA check.

Original five + r2 additions:
- P115-M1: leak coordinates
- P115-M2: drop connectivity check
- P115-M3: LOS always visible
- P115-M4: drop ambiguity rejection
- P115-M5: shared seed namespace
- P115-M6: restore long-distance fallback
- P115-M7: force k≡3
- P115-M8: force non-BFS ratio to 0 (BFS-only)
- P115-M9: disable world rejection redraw
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
    out_results = real_root / "reports/V9-S2-P115/r2/mutation_results.json"
    tmp_dir = Path(tempfile.mkdtemp(prefix="s2_p115_r2_mutations_"))
    print(f"[Init] Isolated workspace created at: {tmp_dir}")

    try:
        shutil.copytree(real_root / "src", tmp_dir / "src")
        shutil.copytree(real_root / "tests", tmp_dir / "tests")
        shutil.copy2(real_root / "pyproject.toml", tmp_dir / "pyproject.toml")

        verify_cmd = [
            sys.executable,
            "-c",
            "import sys; sys.path.insert(0, 'src'); sys.path.insert(0, '.'); "
            "from ainerzero.v9.experiments.s2 import world; import inspect; "
            "print(inspect.getfile(world))",
        ]
        res_v = subprocess.run(verify_cmd, cwd=str(tmp_dir), capture_output=True, text=True, check=True)
        imported_path = res_v.stdout.strip()
        print(f"[Isolation Check] world imported from: {imported_path}")
        assert str(tmp_dir) in imported_path, f"Isolation failure! Imported {imported_path}"

        print("\n[Baseline] Running unmutated test suite...")
        clean_proc = subprocess.run(
            [
                sys.executable,
                "-m",
                "pytest",
                "tests/v9/experiments/test_s2_world.py",
                "tests/v9/experiments/test_s2_data.py",
                "-q",
            ],
            cwd=str(tmp_dir),
            env=dict(os.environ, PYTHONPATH=f"{tmp_dir}/src:{tmp_dir}"),
            capture_output=True,
            text=True,
        )
        assert clean_proc.returncode == 0, (
            f"Clean baseline failed:\n{clean_proc.stdout}\n{clean_proc.stderr}"
        )
        print("  Clean baseline: GREEN.")

        world_file = tmp_dir / "src/ainerzero/v9/experiments/s2/world.py"
        data_file = tmp_dir / "src/ainerzero/v9/experiments/s2/data.py"
        world_orig_sha = sha256_file(world_file)
        world_orig_bytes = world_file.read_bytes()
        data_orig_sha = sha256_file(data_file)
        data_orig_bytes = data_file.read_bytes()

        results = []

        def run_mutation(name: str, target_file: Path, orig_bytes: bytes, orig_sha: str, mutate_fn, test_target: str):
            print(f"\n[Test] Running {name}...")
            target_file.write_text(mutate_fn(orig_bytes.decode("utf-8")), encoding="utf-8")
            proc = subprocess.run(
                [sys.executable, "-m", "pytest", test_target, "-q"],
                cwd=str(tmp_dir),
                env=dict(os.environ, PYTHONPATH=f"{tmp_dir}/src:{tmp_dir}"),
                capture_output=True,
                text=True,
            )
            target_file.write_bytes(orig_bytes)
            restored_sha = sha256_file(target_file)
            assert restored_sha == orig_sha, f"Byte restoration mismatch for {target_file}"

            turned_red = proc.returncode != 0
            lines = [
                line.strip()
                for line in proc.stdout.splitlines()
                if line.strip().startswith("E ") or "FAILED" in line
            ]
            summary = " | ".join(lines[:3]) if turned_red else "Did not fail!"
            print(f"  Returncode: {proc.returncode} (RED: {turned_red})")
            if turned_red:
                print(f"  Captured failure: {summary}")
            results.append(
                {
                    "name": name,
                    "test_target": test_target,
                    "exit_code": proc.returncode,
                    "turned_red": turned_red,
                    "passed": turned_red,
                    "failure_summary": summary,
                    "restored_sha_matched": True,
                }
            )

        run_mutation(
            "P115-M1",
            world_file,
            world_orig_bytes,
            world_orig_sha,
            lambda src: src.replace(
                'obs: dict[str, Any] = {',
                'obs: dict[str, Any] = {\n        "x": state.x,\n        "y": state.y,',
            ),
            "tests/v9/experiments/test_s2_world.py::test_no_coordinate_leakage",
        )

        run_mutation(
            "P115-M2",
            world_file,
            world_orig_bytes,
            world_orig_sha,
            lambda src: src.replace("if enforce_connected:", "if False:"),
            "tests/v9/experiments/test_s2_world.py::test_connectivity_and_doorways",
        )

        def mutate_m3(src: str) -> str:
            needle = (
                "def line_of_sight(terrain: list[list[int]], ax: int, ay: int, bx: int, by: int) -> bool:\n"
                '    """Ray casting line of sight check, derived from gridlab_v1.py line_of_sight."""'
            )
            assert needle in src
            return src.replace(
                needle,
                "def line_of_sight(terrain: list[list[int]], ax: int, ay: int, bx: int, by: int) -> bool:\n"
                "    return True",
            )

        run_mutation(
            "P115-M3",
            world_file,
            world_orig_bytes,
            world_orig_sha,
            mutate_m3,
            "tests/v9/experiments/test_s2_world.py::test_line_of_sight_closed_form",
        )

        run_mutation(
            "P115-M4",
            world_file,
            world_orig_bytes,
            world_orig_sha,
            lambda src: src.replace("if enforce_unambiguous:", "if False:", 1),
            "tests/v9/experiments/test_s2_world.py::test_goal_sampling_and_ambiguity_rejection",
        )

        run_mutation(
            "P115-M5",
            data_file,
            data_orig_bytes,
            data_orig_sha,
            lambda src: src.replace(
                "part_dir = out_path / partition",
                'seed_namespace = "shared-fixed-namespace"\n    part_dir = out_path / partition',
                1,
            ),
            "tests/v9/experiments/test_s2_data.py::test_generate_partition_isolation_and_disjointness",
        )

        run_mutation(
            "P115-M6",
            world_file,
            world_orig_bytes,
            world_orig_sha,
            lambda src: src.replace(
                "_ALLOW_LONG_DISTANCE_FALLBACK = False",
                "_ALLOW_LONG_DISTANCE_FALLBACK = True",
            ),
            "tests/v9/experiments/test_s2_world.py::test_long_goals_no_fallback_multi_start",
        )

        run_mutation(
            "P115-M7",
            data_file,
            data_orig_bytes,
            data_orig_sha,
            lambda src: src.replace(
                "return rng.choices(list(K_VALUES), weights=list(K_WEIGHTS))[0]",
                "return 3",
            ),
            "tests/v9/experiments/test_s2_data.py::test_k_distribution_chi_square",
        )

        run_mutation(
            "P115-M8",
            data_file,
            data_orig_bytes,
            data_orig_sha,
            lambda src: src.replace(
                "if force_bfs_only:\n        return \"bfs\"",
                "return \"bfs\"\n    if force_bfs_only:\n        return \"bfs\"",
            ),
            "tests/v9/experiments/test_s2_data.py::test_non_bfs_segment_ratio_floor",
        )

        run_mutation(
            "P115-M9",
            world_file,
            world_orig_bytes,
            world_orig_sha,
            lambda src: src.replace(
                "if not enforce:\n        return False\n    return rejection_rate > threshold",
                "if not enforce:\n        return False\n    return False",
            ),
            "tests/v9/experiments/test_s2_world.py::test_world_rejection_redraw_gate",
        )

        out_results.write_text(json.dumps(results, indent=2) + "\n")
        print(f"\n[Done] Mutations saved to {out_results}")
        all_passed = all(r["passed"] for r in results)
        print(
            f"Overall mutation status: "
            f"{'ALL PASSED (ALL TURNED RED)' if all_passed else 'SOME FAILED'} "
            f"({sum(r['passed'] for r in results)}/{len(results)})"
        )
        return 0 if all_passed else 1
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
