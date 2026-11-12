"""Adversarial mutation test harness for S5 teacher extraction review (P232).

Runs 4 new adversarial mutations (C1-C4, non-duplicative with P231 B1-B10)
in an isolated temporary directory using pure CPU pytest.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path("/Users/mac/AinerWorkFlow/AinerZero")
VENV_PY = ROOT / ".venv/bin/python"


def main():
    mutations = {
        "C1_vjepa_input_no_dtype_check": (
            "    if clip.shape != CLIP_SHAPE or clip.dtype != np.uint8:",
            "    if clip.shape != CLIP_SHAPE:",
        ),
        "C2_iter_items_fencepost_drop_lower": (
            "        if worlds is not None and not (worlds[0] <= w < worlds[1]):",
            "        if worlds is not None and not (worlds[0] < w < worlds[1]):",
        ),
        "C3_verify_weights_bypass_mismatch": (
            "        if sha != want:",
            "        if False and sha != want:",
        ),
        "C4_da2_crop_off_by_one": (
            "DA2_CROP = (63, 455)          # middle 392 of 518 columns; matches render.da2_center_crop",
            "DA2_CROP = (63, 454)          # middle 392 of 518 columns; matches render.da2_center_crop",
        ),
    }

    with tempfile.TemporaryDirectory() as td:
        tpath = Path(td)
        shutil.copytree(ROOT / "src", tpath / "src")
        (tpath / "tests/v9/experiments").mkdir(parents=True)
        shutil.copy(ROOT / "tests/v9/experiments/test_s5_extract.py", tpath / "tests/v9/experiments/test_s5_extract.py")
        shutil.copy(ROOT / "tests/conftest.py", tpath / "tests/conftest.py")
        shutil.copy(ROOT / "pyproject.toml", tpath / "pyproject.toml")

        env = dict(os.environ, PYTHONPATH=str(tpath / "src"))
        target_file = tpath / "src/ainerzero/v9/experiments/s5/extract_teachers.py"
        orig_content = target_file.read_text(encoding="utf-8")

        def run_pytest():
            res = subprocess.run(
                [str(VENV_PY), "-m", "pytest", "-q", "-p", "no:cacheprovider", "-rf", "tests/v9/experiments/test_s5_extract.py"],
                cwd=tpath,
                env=env,
                capture_output=True,
                text=True,
            )
            failed_tests = [line.split("::")[-1].split()[0] for line in res.stdout.splitlines() if line.startswith("FAILED")]
            summary_lines = [line for line in res.stdout.splitlines() if "passed" in line or "failed" in line]
            summary = summary_lines[-1] if summary_lines else res.stdout.strip()
            return res.returncode, failed_tests, summary

        print("=== BASELINE TEST ===")
        rc, fails, summary = run_pytest()
        print(f"Baseline return code: {rc}, summary: {summary}")
        assert rc == 0, f"Baseline failed: {fails} {summary}"

        print("\n=== RUNNING MUTATIONS ===")
        for name, (orig_str, mut_str) in mutations.items():
            assert orig_content.count(orig_str) == 1, f"{name}: target string not found exactly once ({orig_content.count(orig_str)})"
            mutated_code = orig_content.replace(orig_str, mut_str)
            target_file.write_text(mutated_code, encoding="utf-8")

            rc, fails, summary = run_pytest()
            status = "KILLED" if rc != 0 else "SURVIVED"
            print(f"{name}: {status}")
            print(f"  Failing tests: {fails}")
            print(f"  Summary: {summary}")

            # Revert to original for next mutation
            target_file.write_text(orig_content, encoding="utf-8")


if __name__ == "__main__":
    main()
