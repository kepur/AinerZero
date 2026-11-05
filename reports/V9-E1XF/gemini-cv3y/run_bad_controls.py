#!/usr/bin/env python3
"""Isolated source-mutation bad controls runner for E1 export B25 S-family support (ainerzero.V9.P77).

Executes 2 isolated source-mutation bad controls in temporary sandbox copies:
1. Remove non-object keys filtering in export_sequence (treat hidden_parameters items as bodies)
   -> RED (AttributeError: 'list' object has no attribute 'get' on mechanisms list).
2. Leak mechanisms directly into student_view
   -> RED (LeakageError: Leakage detected: prohibited keys present in student view: {'mechanisms'}).
"""

from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from typing import Any

REPO_ROOT = Path("/Users/mac/AinerWorkFlow/AinerZero")
PYTEST_BIN = REPO_ROOT / ".venv-ainerzero" / "bin" / "pytest"


def run_mutation_test(
    name: str,
    description: str,
    mutations: list[tuple[str, str]],
    test_target: str,
) -> dict[str, Any]:
    print(f"\n[MUTATION] {name}: {description}")
    with tempfile.TemporaryDirectory() as td:
        tdp = Path(td)
        shutil.copytree(REPO_ROOT / "src", tdp / "src")
        shutil.copytree(REPO_ROOT / "tests", tdp / "tests")
        shutil.copy(REPO_ROOT / "pyproject.toml", tdp / "pyproject.toml")

        export_file = tdp / "src" / "ainerzero" / "v9" / "experiments" / "e1" / "export.py"
        code = export_file.read_text(encoding="utf-8")

        for target, replacement in mutations:
            if target not in code:
                raise RuntimeError(f"Target pattern not found in export.py for mutation {name}:\n{target[:60]}")
            code = code.replace(target, replacement, 1)

        export_file.write_text(code, encoding="utf-8")

        proc = subprocess.run(
            [str(PYTEST_BIN), test_target, "-v"],
            cwd=tdp,
            env={"PYTHONPATH": "src", "PATH": "/usr/bin:/bin"},
            capture_output=True,
            text=True,
        )

        is_red = proc.returncode != 0
        status = "RED (FAILED as expected)" if is_red else "GREEN (UNEXPECTED PASS)"
        print(f"Status: {status} (exit code {proc.returncode})")

        return {
            "name": name,
            "description": description,
            "test_target": test_target,
            "exit_code": proc.returncode,
            "is_red": is_red,
            "status": status,
            "stdout_tail": "\n".join(proc.stdout.strip().splitlines()[-12:]),
        }


def main():
    print("=" * 70)
    print("RUNNING ISOLATED BAD CONTROLS FOR E1 EXPORT B25 (ainerzero.V9.P77)")
    print("=" * 70)

    # Mutation 1: Remove non-object keys filtering
    m1_target = """    first_frame_objs = frames[0].get("objects", {})
    object_hidden_params = {
        k: v for k, v in hidden_params.items()
        if k not in NON_OBJECT_HIDDEN_KEYS and isinstance(v, Mapping)
    }
    all_obj_names = sorted(list(set(list(object_hidden_params.keys()) + list(first_frame_objs.keys()))))"""
    m1_replacement = """    first_frame_objs = frames[0].get("objects", {})
    object_hidden_params = hidden_params
    all_obj_names = sorted(list(set(list(hidden_params.keys()) + list(first_frame_objs.keys()))))"""

    m1 = run_mutation_test(
        "bad_control_1_remove_non_object_keys_filtering",
        "Remove NON_OBJECT_HIDDEN_KEYS filtering in export_sequence (revert to treating all hidden_params as bodies)",
        [(m1_target, m1_replacement)],
        "tests/test_e1_export.py::test_real_b25_s_family_hidden_parameters_export",
    )

    # Mutation 2: Leak mechanisms into student view
    m2_target = """    student_view: dict[str, Any] = {
        "sequence_id": opaque_id,
        "scenario_type": scenario_type,
        "static_environment": student_static_geo,
        "active_bodies": active_bodies_info,
        "frames": student_frames,
    }"""
    m2_replacement = """    student_view: dict[str, Any] = {
        "sequence_id": opaque_id,
        "scenario_type": scenario_type,
        "static_environment": student_static_geo,
        "active_bodies": active_bodies_info,
        "frames": student_frames,
        "mechanisms": [{"id": "quadratic_drag_v1"}],  # bad control: leak mechanisms to student view
    }"""

    m2 = run_mutation_test(
        "bad_control_2_leak_mechanisms_into_student_view",
        "Inject mechanisms into student_view to verify assert_no_leakage intercepts forbidden key",
        [(m2_target, m2_replacement)],
        "tests/test_e1_export.py::test_real_b25_s_family_hidden_parameters_export",
    )

    results = [m1, m2]
    all_passed = all(r["is_red"] for r in results)

    output_summary = REPO_ROOT / "reports" / "V9-E1XF" / "gemini-cv3y" / "bad_controls_summary.json"
    output_summary.write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")

    print("\n" + "=" * 70)
    print(f"SUMMARY: {'ALL RED (PASSED)' if all_passed else 'SOME FAILED TO TRIGGER RED'}")
    print(f"Summary written to: {output_summary}")
    print("=" * 70)

    if not all_passed:
        sys.exit(1)


if __name__ == "__main__":
    main()
