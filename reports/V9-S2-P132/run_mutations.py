#!/usr/bin/env python3
"""Adversarial mutation test runner for S2 preregistration freeze and identity (P132).

Executes mutations in an isolated temporary sandbox containing copies of:
- src/
- tests/
- pyproject.toml

Mutations:
1. P132-M1: collect_source_digests omits worker.py -> test_freeze_then_verify_passes_and_detects_single_byte_tamper fails (DID NOT RAISE).
2. P132-M2: freeze allows overwriting existing files -> test_freeze_refuses_overwrite fails (DID NOT RAISE).
3. P132-M3: approval_line drops a space -> test_approval_line_matches_commands_scan fails (AssertionError).

Each mutation is verified RED, byte-restored, and SHA-verified.
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

REAL_ROOT = Path("/Users/mac/AinerWorkFlow/AinerZero").resolve()
REPORT_DIR = REAL_ROOT / "reports" / "V9-S2-P132"
REPORT_DIR.mkdir(parents=True, exist_ok=True)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def setup_sandbox(tmp_path: Path) -> Path:
    sandbox = tmp_path / "sandbox"
    sandbox.mkdir(parents=True, exist_ok=True)

    shutil.copytree(REAL_ROOT / "src", sandbox / "src", symlinks=True)
    shutil.copytree(REAL_ROOT / "tests", sandbox / "tests", symlinks=True)
    shutil.copy2(REAL_ROOT / "pyproject.toml", sandbox / "pyproject.toml")

    return sandbox


def run_test_in_sandbox(sandbox: Path, test_name: str) -> tuple[int, str]:
    python_bin = REAL_ROOT / ".venv" / "bin" / "python"
    env = os.environ.copy()
    env["PYTHONPATH"] = f"{sandbox / 'src'}:{sandbox}"
    env["PYTHONDONTWRITEBYTECODE"] = "1"

    cmd = [
        str(python_bin),
        "-m",
        "pytest",
        str(sandbox / "tests" / "v9" / "experiments" / "test_s2_freeze_identity.py"),
        "-k",
        test_name,
        "-v",
    ]

    res = subprocess.run(
        cmd,
        cwd=str(sandbox),
        env=env,
        capture_output=True,
        text=True,
    )
    return res.returncode, res.stdout + "\n" + res.stderr


def main() -> int:
    print("=== P132 Adversarial Mutation Runner ===")
    results = []
    log_lines = []

    with tempfile.TemporaryDirectory(prefix="p132_mut_") as tmp_dir_str:
        tmp_dir = Path(tmp_dir_str)
        sandbox = setup_sandbox(tmp_dir)
        print(f"Created isolated sandbox at: {sandbox}")

        freeze_file = sandbox / "src" / "ainerzero" / "v9" / "experiments" / "s2" / "freeze.py"
        orig_freeze_content = freeze_file.read_text(encoding="utf-8")
        orig_freeze_sha = hashlib.sha256(orig_freeze_content.encode("utf-8")).hexdigest()

        # Pre-check: clean sandbox must pass all tests
        for tname in [
            "test_freeze_then_verify_passes_and_detects_single_byte_tamper",
            "test_freeze_refuses_overwrite",
            "test_approval_line_matches_commands_scan",
        ]:
            ret_clean, out_clean = run_test_in_sandbox(sandbox, tname)
            if ret_clean != 0:
                print(f"[ERROR] Clean sandbox test {tname} failed:\n", out_clean)
                return 1
        print("Clean sandbox pre-check passed for all target tests.")

        mutations = [
            {
                "id": "P132-M1",
                "name": "omit_worker_py_from_source_digests",
                "desc": "collect_source_digests omits worker.py; modifying worker.py is not detected",
                "target_pattern": 'if py_file.is_file() and not py_file.name.startswith("."):',
                "replacement": 'if py_file.is_file() and not py_file.name.startswith(".") and py_file.name != "worker.py":',
                "test_name": "test_freeze_then_verify_passes_and_detects_single_byte_tamper",
            },
            {
                "id": "P132-M2",
                "name": "freeze_allows_overwrite",
                "desc": "freeze bypasses overwrite checks, allowing overwrite of existing prereg files",
                "target_pattern": 'if target_json.exists() or target_sha.exists():\n        raise FileExistsError(f"Target preregistration file already exists in {out_path}")',
                "replacement": "# if target_json.exists() or target_sha.exists(): pass  # P132-M2 bypassed overwrite check",
                "test_name": "test_freeze_refuses_overwrite",
            },
            {
                "id": "P132-M3",
                "name": "approval_line_missing_space",
                "desc": "approval_line drops space between APPROVED and s2-phase1, failing regex scan",
                "target_pattern": 'APPROVAL_PREFIX = "APPROVED s2-phase1 prereg document_sha256="',
                "replacement": 'APPROVAL_PREFIX = "APPROVEDs2-phase1 prereg document_sha256="',
                "test_name": "test_approval_line_matches_commands_scan",
            },
        ]

        for mut in mutations:
            print(f"\n--- Testing Mutation {mut['id']}: {mut['name']} ---")
            assert mut["target_pattern"] in orig_freeze_content, f"Pattern not found: {mut['target_pattern']}"

            mutated_content = orig_freeze_content.replace(mut["target_pattern"], mut["replacement"])
            freeze_file.write_text(mutated_content, encoding="utf-8")
            mut_sha = sha256_file(freeze_file)
            print(f"Applied mutation. Target SHA: {mut_sha}")

            ret, out = run_test_in_sandbox(sandbox, mut["test_name"])
            print(f"Pytest returncode: {ret}")
            is_red = (ret != 0)

            # Restore original content
            freeze_file.write_text(orig_freeze_content, encoding="utf-8")
            restored_sha = sha256_file(freeze_file)
            assert restored_sha == orig_freeze_sha, f"SHA mismatch after restore! {restored_sha} != {orig_freeze_sha}"
            print(f"Restored original file. SHA matches: {restored_sha == orig_freeze_sha}")

            log_entry = (
                f"=== {mut['id']}: {mut['name']} ===\n"
                f"Description: {mut['desc']}\n"
                f"Target Test: {mut['test_name']}\n"
                f"Returncode: {ret} (is_red={is_red})\n"
                f"Output snippet:\n{out[-800:]}\n"
            )
            log_lines.append(log_entry)

            results.append({
                "id": mut["id"],
                "name": mut["name"],
                "desc": mut["desc"],
                "test_name": mut["test_name"],
                "returncode": ret,
                "is_red": is_red,
                "sha_restored": (restored_sha == orig_freeze_sha),
            })

            if not is_red:
                print(f"[ERROR] Mutation {mut['id']} did NOT turn RED! Output:\n{out}")
                return 1

    summary_file = REPORT_DIR / "mutation_summary.json"
    with open(summary_file, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)

    log_file = REPORT_DIR / "mutation_log.txt"
    with open(log_file, "w", encoding="utf-8") as f:
        f.write("\n".join(log_lines))

    print(f"\nAll mutations verified RED and restored. Summary saved to {summary_file}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
