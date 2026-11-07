#!/usr/bin/env python3
"""Run independent reviewer mutations for ainerzero.V9.A23 in an isolated replica sandbox.

Mutations to verify:
1. A23-REV-M1: In tests/conftest.py, assert_session_stat_clean does not assert diff (assert True)
   -> test_session_fixture_assertion_fails_on_tampered_artifacts must fail (RED).
2. A23-REV-M2: In tests/conftest.py, apply_sessionfinish_exitstatus does not set session.exitstatus = 1
   -> test_sessionfinish_sets_exitstatus_on_tampered_artifacts must fail (RED).
3. A23-REV-M3: In tests/conftest.py, remove injection of _HERMETIC_SITE_DIR into PYTHONPATH
   -> test_subprocess_sqlite_connect_intercepted_by_sitecustomize must fail (RED).
"""

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

REPO_ROOT = Path("/Users/mac/AinerWorkFlow/AinerZero").resolve()
PYTHON_BIN = REPO_ROOT / ".venv" / "bin" / "python"
REVIEW_DIR = REPO_ROOT / "reports" / "test-hermetic-20261106" / "A23"
REVIEW_DIR.mkdir(parents=True, exist_ok=True)

MUTATIONS = [
    {
        "id": "A23-REV-M1",
        "name": "fixture_assertion_changed_to_tautology",
        "description": "In assert_session_stat_clean, replace 'assert not diff' with tautology pass",
        "file_rel": "tests/conftest.py",
        "target": """    diff = check_session_stat_diff(before, root=root)
    assert not diff, (""",
        "replacement": """    diff = check_session_stat_diff(before, root=root)
    if False:
        assert not diff, (""",
        "target_test": "tests/test_hermetic_guards.py::test_session_fixture_assertion_fails_on_tampered_artifacts",
    },
    {
        "id": "A23-REV-M2",
        "name": "sessionfinish_exitstatus_omitted",
        "description": "In apply_sessionfinish_exitstatus, do not set session.exitstatus = 1",
        "file_rel": "tests/conftest.py",
        "target": """    if diff:
        session.exitstatus = 1""",
        "replacement": """    if diff:
        pass  # REV-M2: omitted session.exitstatus = 1""",
        "target_test": "tests/test_hermetic_guards.py::test_sessionfinish_sets_exitstatus_on_tampered_artifacts",
    },
    {
        "id": "A23-REV-M3",
        "name": "omit_sitecustomize_pythonpath_injection",
        "description": "In conftest.py, do not inject _HERMETIC_SITE_DIR into child PYTHONPATH",
        "file_rel": "tests/conftest.py",
        "target": """if _HERMETIC_SITE_DIR not in _pp_entries:
    os.environ["PYTHONPATH"] = os.pathsep.join([_HERMETIC_SITE_DIR] + _pp_entries)""",
        "replacement": """if _HERMETIC_SITE_DIR not in _pp_entries:
    pass  # REV-M3: do not inject into child PYTHONPATH""",
        "target_test": "tests/test_hermetic_guards.py::test_subprocess_sqlite_connect_intercepted_by_sitecustomize",
    },
]


def sha256_file(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def main():
    print("=== Setting up isolated replica sandbox for A23 Reviewer Mutations ===")
    with tempfile.TemporaryDirectory() as td:
        sandbox_dir = Path(td) / "ainerzero_sandbox"
        sandbox_dir.mkdir()

        print(f"Copying src/, tests/, pyproject.toml to {sandbox_dir}...")
        shutil.copytree(REPO_ROOT / "src", sandbox_dir / "src")
        shutil.copytree(REPO_ROOT / "tests", sandbox_dir / "tests")
        shutil.copy2(REPO_ROOT / "pyproject.toml", sandbox_dir / "pyproject.toml")

        # Verify conftest path in sandbox
        verify_import_cmd = [
            str(PYTHON_BIN),
            "-c",
            (
                f"import sys\n"
                f"sys.path.insert(0, '{sandbox_dir}/tests')\n"
                f"import conftest\n"
                f"assert '{sandbox_dir}' in str(conftest.__file__)\n"
                f"print('Sandbox conftest path verified:', conftest.__file__)\n"
            ),
        ]
        res_import = subprocess.run(verify_import_cmd, capture_output=True, text=True)
        assert res_import.returncode == 0, f"Sandbox verification failed: {res_import.stderr}"
        print(res_import.stdout.strip())

        results = []
        log_lines = []

        for mut in MUTATIONS:
            print(f"\n--- Running Mutation: {mut['id']} ({mut['name']}) ---")
            target_path = sandbox_dir / mut["file_rel"]
            orig_text = target_path.read_text(encoding="utf-8")
            orig_sha = sha256_file(target_path)

            assert mut["target"] in orig_text, f"Target text not found for {mut['id']}"
            mutated_text = orig_text.replace(mut["target"], mut["replacement"], 1)

            try:
                target_path.write_text(mutated_text, encoding="utf-8")
                mutated_sha = sha256_file(target_path)
                assert mutated_sha != orig_sha

                env = dict(os.environ)
                env["PYTHONPATH"] = f"{sandbox_dir}/src"

                proc = subprocess.run(
                    [str(PYTHON_BIN), "-m", "pytest", mut["target_test"]],
                    cwd=str(sandbox_dir),
                    capture_output=True,
                    text=True,
                    env=env,
                )

                killed = (proc.returncode != 0)
                status = "KILLED" if killed else "SURVIVED"
                print(f"Result for {mut['id']}: {status} (exit code: {proc.returncode})")

                log_entry = (
                    f"=== Mutation {mut['id']} ===\n"
                    f"Name: {mut['name']}\n"
                    f"Target test: {mut['target_test']}\n"
                    f"Status: {status} (exit_code: {proc.returncode})\n"
                    f"Stdout:\n{proc.stdout}\n"
                    f"Stderr:\n{proc.stderr}\n"
                )
                log_lines.append(log_entry)

                results.append({
                    "id": mut["id"],
                    "name": mut["name"],
                    "description": mut["description"],
                    "target_file": mut["file_rel"],
                    "target_test": mut["target_test"],
                    "status": status,
                    "exit_code": proc.returncode,
                    "killed": killed,
                })

            finally:
                target_path.write_text(orig_text, encoding="utf-8")
                restored_sha = sha256_file(target_path)
                assert restored_sha == orig_sha, f"SHA mismatch on restore for {mut['id']}"

        # Write summary and logs
        summary_path = REVIEW_DIR / "mutations.json"
        summary_path.write_text(json.dumps(results, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"\nWrote mutation summary to {summary_path}")

        log_path = REVIEW_DIR / "mutations.log"
        log_path.write_text("\n".join(log_lines), encoding="utf-8")
        print(f"Wrote mutation log to {log_path}")

        all_killed = all(r["killed"] for r in results)
        print(f"\nAll mutations killed: {all_killed} ({len(results)}/{len(results)})")
        if not all_killed:
            sys.exit(1)


if __name__ == "__main__":
    main()
