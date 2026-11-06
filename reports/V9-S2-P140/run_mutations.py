#!/usr/bin/env python3
"""Adversarial mutation test runner for S2 freeze CLI digest and approval_line validation (P140).

Executes mutations in an isolated temporary sandbox containing copies of:
- src/
- tests/
- pyproject.toml

Mutations:
1. P140-M1: Omit cli.py snippet digest extraction -> test_p140_cli_snippet_tamper_detected_and_names_cli_py fails (RED).
2. P140-M2: Omit approval_line hex format validation -> test_p140_approval_line_validation fails (RED).

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
REPORT_DIR = REAL_ROOT / "reports" / "V9-S2-P140"
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


def run_test_in_sandbox(sandbox: Path, test_name: str | None = None) -> tuple[int, str]:
    python_bin = REAL_ROOT / ".venv" / "bin" / "python"
    env = os.environ.copy()
    env["PYTHONPATH"] = f"{sandbox / 'src'}:{sandbox}"
    env["PYTHONDONTWRITEBYTECODE"] = "1"

    cmd = [
        str(python_bin),
        "-m",
        "pytest",
        str(sandbox / "tests" / "v9" / "experiments" / "test_s2_freeze_identity.py"),
        "-v",
    ]
    if test_name:
        cmd.extend(["-k", test_name])

    res = subprocess.run(
        cmd,
        cwd=str(sandbox),
        env=env,
        capture_output=True,
        text=True,
    )
    return res.returncode, res.stdout + "\n" + res.stderr


def main() -> int:
    print("=== P140 Adversarial Mutation Runner ===")
    results = []
    log_lines = []

    with tempfile.TemporaryDirectory(prefix="p140_mut_") as tmp_dir_str:
        tmp_dir = Path(tmp_dir_str)
        sandbox = setup_sandbox(tmp_dir)
        print(f"Created isolated sandbox at: {sandbox}")

        freeze_file = sandbox / "src" / "ainerzero" / "v9" / "experiments" / "s2" / "freeze.py"
        orig_content = freeze_file.read_text(encoding="utf-8")
        orig_sha = hashlib.sha256(orig_content.encode("utf-8")).hexdigest()

        # Pre-check: clean sandbox must pass all 8 tests
        ret_clean, out_clean = run_test_in_sandbox(sandbox)
        if ret_clean != 0:
            print("[ERROR] Clean sandbox failed:\n", out_clean)
            return 1
        print("[PASS] Clean sandbox passed all 8 tests")

        # -------------------------------------------------------------------------
        # Mutation 1: P140-M1 Omit cli.py snippet digest extraction
        # -------------------------------------------------------------------------
        print("\n--- Testing Mutation P140-M1: Omit cli.py snippet extraction ---")
        m1_target = """    cli_path = root / "src" / "ainerzero" / "cli.py"
    if cli_path.is_file():
        snippet = extract_cli_s2_snippet(cli_path)
        digests["src/ainerzero/cli.py:s2-phase1"] = hashlib.sha256(snippet.encode("utf-8")).hexdigest()
    else:
        raise FileNotFoundError(f"CLI file missing: {cli_path}")"""
        m1_replacement = """    # Mutation P140-M1: omitted CLI snippet digest extraction
    pass"""

        assert m1_target in orig_content, "m1_target not found in freeze.py"
        m1_content = orig_content.replace(m1_target, m1_replacement, 1)
        freeze_file.write_text(m1_content, encoding="utf-8")

        ret_m1, out_m1 = run_test_in_sandbox(sandbox, "test_p140_cli_snippet_tamper_detected_and_names_cli_py")
        is_red_m1 = ret_m1 != 0
        print(f"P140-M1 Result: returncode={ret_m1}, is_red={is_red_m1}")
        log_lines.append(f"=== P140-M1 Output ===\nReturnCode: {ret_m1}\n{out_m1}\n")

        # Restore
        freeze_file.write_text(orig_content, encoding="utf-8")
        restored_sha_m1 = hashlib.sha256(freeze_file.read_bytes()).hexdigest()
        assert restored_sha_m1 == orig_sha, "Freeze SHA mismatch after M1 restore!"

        results.append(
            {
                "id": "P140-M1",
                "name": "omit_cli_snippet_extraction",
                "description": "Omit collecting digest for src/ainerzero/cli.py:s2-phase1 snippet",
                "target_test": "test_p140_cli_snippet_tamper_detected_and_names_cli_py",
                "returncode": ret_m1,
                "is_red": is_red_m1,
                "status": "KILLED" if is_red_m1 else "SURVIVED",
                "restored_sha256": restored_sha_m1,
            }
        )

        # -------------------------------------------------------------------------
        # Mutation 2: P140-M2 Omit approval_line hex format validation
        # -------------------------------------------------------------------------
        print("\n--- Testing Mutation P140-M2: Omit approval_line hex format validation ---")
        m2_target = """    cleaned = str(sha).strip().lower()
    if len(cleaned) != 64 or not re.fullmatch(r"[0-9a-f]{64}", cleaned):
        raise ValueError(
            f"document_sha256 must be exactly 64 lowercase hexadecimal characters, got {sha!r}"
        )
    return f"{APPROVAL_PREFIX}{cleaned}\""""
        m2_replacement = """    cleaned = str(sha).strip().lower()
    return f"{APPROVAL_PREFIX}{cleaned}\""""

        assert m2_target in orig_content, "m2_target not found in freeze.py"
        m2_content = orig_content.replace(m2_target, m2_replacement, 1)
        freeze_file.write_text(m2_content, encoding="utf-8")

        ret_m2, out_m2 = run_test_in_sandbox(sandbox, "test_p140_approval_line_validation")
        is_red_m2 = ret_m2 != 0
        print(f"P140-M2 Result: returncode={ret_m2}, is_red={is_red_m2}")
        log_lines.append(f"=== P140-M2 Output ===\nReturnCode: {ret_m2}\n{out_m2}\n")

        # Restore
        freeze_file.write_text(orig_content, encoding="utf-8")
        restored_sha_m2 = hashlib.sha256(freeze_file.read_bytes()).hexdigest()
        assert restored_sha_m2 == orig_sha, "Freeze SHA mismatch after M2 restore!"

        results.append(
            {
                "id": "P140-M2",
                "name": "omit_approval_line_hex_validation",
                "description": "Omit 64-hex character validation in freeze.approval_line",
                "target_test": "test_p140_approval_line_validation",
                "returncode": ret_m2,
                "is_red": is_red_m2,
                "status": "KILLED" if is_red_m2 else "SURVIVED",
                "restored_sha256": restored_sha_m2,
            }
        )

    # Post-check: clean restore
    clean_sha = sha256_file(REAL_ROOT / "src" / "ainerzero" / "v9" / "experiments" / "s2" / "freeze.py")
    assert clean_sha == orig_sha

    # Write summary & log
    summary_file = REPORT_DIR / "mutation_summary.json"
    with open(summary_file, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    print(f"\nSaved mutation summary to {summary_file}")

    log_file = REPORT_DIR / "mutation_log.txt"
    with open(log_file, "w", encoding="utf-8") as f:
        f.write("\n".join(log_lines))
    print(f"Saved mutation log to {log_file}")

    all_passed = all(r["is_red"] for r in results)
    print(f"\nAll mutations RED: {all_passed}")
    return 0 if all_passed else 1


if __name__ == "__main__":
    sys.exit(main())
