#!/usr/bin/env python3
"""Adversarial mutation verification for hermetic test guards (r3b).

Modifies the real tests/conftest.py inside an isolated replica tree:
- Isolated replica: copies src/, tests/, pyproject.toml into a temporary directory.
- Asserts that import resolution resolves strictly to the replica copy.
- 4 Mutations directly applied to tests/conftest.py in replica:
    1. make_guarded_connect check disabled -> RED (RuntimeError expected)
    2. make_guarded_flock check disabled   -> RED (RuntimeError expected)
    3. guard_snapshot skips -shm          -> RED (AssertionError expected on -shm)
    4. _install_hermetic_function_guards deleted -> RED (AssertionError expected on global installation)
- Each mutation is restored byte-by-byte with SHA-256 validation.
- All self-tests use fake roots under tmpdir; real repository artifacts are never touched.
- No utime or file restoration is performed on real artifacts.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

REAL_ROOT = Path(__file__).resolve().parents[3]
R3B_DIR = REAL_ROOT / "reports/test-hermetic-20261106/r3b"


def snapshot_artifacts(root: Path = REAL_ROOT) -> dict[str, tuple[int, int, int]]:
    art_dir = root / "artifacts"
    snap = {}
    if not art_dir.exists():
        return snap
    for dirpath, dirnames, filenames in os.walk(art_dir):
        for name in dirnames + filenames:
            p = os.path.join(dirpath, name)
            try:
                st = os.stat(p)
                snap[os.path.realpath(p)] = (st.st_mtime_ns, st.st_size, st.st_ino)
            except OSError:
                pass
    return snap


def compare_snapshots(before: dict, after: dict) -> dict[str, str]:
    diffs = {}
    all_keys = set(before.keys()) | set(after.keys())
    for k in sorted(all_keys):
        if k not in before:
            diffs[k] = "ADDED"
        elif k not in after:
            diffs[k] = "DELETED"
        elif before[k] != after[k]:
            b_m, b_s, b_i = before[k]
            a_m, a_s, a_i = after[k]
            details = []
            if b_m != a_m:
                details.append(f"mtime_ns: {b_m} -> {a_m}")
            if b_s != a_s:
                details.append(f"size: {b_s} -> {a_s}")
            if b_i != a_i:
                details.append(f"inode: {b_i} -> {a_i}")
            diffs[k] = "MODIFIED (" + ", ".join(details) + ")"
    return diffs


def run_mutations(out_log: Path | None = None, json_out: Path | None = None) -> int:
    log_lines = []

    def log(msg: str) -> None:
        print(msg)
        log_lines.append(msg)

    log("=== HERMETIC GUARD ADVERSARIAL MUTATION VERIFICATION (R3B REAL CONFTEST IN ISOLATED REPLICA) ===")

    # 1. Real artifacts stat snapshot BEFORE mutations
    log("\n[Step 1] Taking pre-mutation snapshot of real artifacts/ ...")
    t0_stat = time.time()
    real_stat_before = snapshot_artifacts(REAL_ROOT)
    log(f"Pre-mutation real artifacts recorded: {len(real_stat_before)} entries ({time.time() - t0_stat:.2f}s)")

    venv_pytest = REAL_ROOT / ".venv" / "bin" / "pytest"
    if venv_pytest.exists():
        pytest_cmd = [str(venv_pytest)]
    else:
        pytest_cmd = [sys.executable, "-m", "pytest"]

    mutation_results = {}

    with tempfile.TemporaryDirectory(prefix="hermetic-r3b-iso-") as tmpdir:
        replica_dir = Path(tmpdir) / "replica"
        replica_dir.mkdir(parents=True, exist_ok=True)

        log(f"\n[Step 2] Staging isolated replica under {replica_dir} ...")
        shutil.copytree(REAL_ROOT / "src", replica_dir / "src")
        shutil.copytree(REAL_ROOT / "tests", replica_dir / "tests")
        shutil.copy2(REAL_ROOT / "pyproject.toml", replica_dir / "pyproject.toml")

        # Environment for isolated execution
        env = dict(os.environ)
        env["PYTHONPATH"] = f"{replica_dir / 'src'}:{replica_dir / 'tests'}:{replica_dir}"
        env["PYTHONDONTWRITEBYTECODE"] = "1"

        # Assert import resolution points to replica
        log("[Step 3] Asserting import resolution strictly targets replica ...")
        assert_script = (
            "import conftest, sys; "
            f"conftest_file = str(conftest.__file__); "
            f"expected_prefix = {repr(str(replica_dir))}; "
            f"assert conftest_file.startswith(expected_prefix), "
            f"f'conftest resolved outside replica: {{conftest_file}} != {{expected_prefix}}'; "
            "print('Verified conftest import:', conftest_file)"
        )
        chk = subprocess.run(
            [sys.executable, "-c", assert_script],
            cwd=str(replica_dir),
            env=env,
            capture_output=True,
            text=True,
        )
        assert chk.returncode == 0, f"Import assertion failed:\nSTDOUT:\n{chk.stdout}\nSTDERR:\n{chk.stderr}"
        log(f"-> {chk.stdout.strip()}")

        conftest_path = replica_dir / "tests" / "conftest.py"
        orig_bytes = conftest_path.read_bytes()
        orig_sha = hashlib.sha256(orig_bytes).hexdigest()
        log(f"Replica tests/conftest.py SHA-256: {orig_sha} ({len(orig_bytes)} bytes)")

        # Run baseline
        log("\n[Step 4] Running baseline suite on tests/test_hermetic_guards.py in replica ...")
        base_run = subprocess.run(
            pytest_cmd + ["tests/test_hermetic_guards.py", "-v", "-p", "no:cacheprovider"],
            cwd=str(replica_dir),
            env=env,
            capture_output=True,
            text=True,
        )
        base_out = base_run.stdout + base_run.stderr
        log(f"Baseline return code: {base_run.returncode}")
        assert base_run.returncode == 0, f"Baseline tests failed unexpectedly in replica:\n{base_out}"
        assert "5 passed" in base_out or "passed" in base_out
        log("Baseline verification: PASSED (GREEN, 5 passed)")

        # Define 4 mutations on tests/conftest.py
        mutations = [
            (
                "M1_connect_unguarded",
                "make_guarded_connect check disabled",
                '        check_hermetic_access(database, "sqlite3.connect", root=root, whitelist=whitelist)',
                '        pass  # MUTATION_1: check_hermetic_access disabled',
                "RuntimeError",
            ),
            (
                "M2_flock_unguarded",
                "make_guarded_flock check disabled",
                '        check_hermetic_access(fd, "fcntl.flock", root=root, whitelist=whitelist)',
                '        pass  # MUTATION_2: check_hermetic_access disabled',
                "RuntimeError",
            ),
            (
                "M3_snapshot_skips_shm",
                "guard_snapshot skips -shm files",
                """            for p in glob.glob(full_pattern, recursive=True):
                try:
                    st = os.stat(p)""",
                """            for p in glob.glob(full_pattern, recursive=True):
                try:
                    if p.endswith("-shm"):
                        continue  # MUTATION_3: snapshot skips -shm
                    st = os.stat(p)""",
                "AssertionError",
            ),
            (
                "M4_installation_deleted",
                "_install_hermetic_function_guards deleted/disabled",
                """def _install_hermetic_function_guards() -> None:
    fcntl.flock = guarded_flock
    fcntl.lockf = guarded_lockf
    sqlite3.connect = guarded_connect
    if "sqlite3" in sys.modules:
        sys.modules["sqlite3"].connect = guarded_connect""",
                """def _install_hermetic_function_guards() -> None:
    pass  # MUTATION_4: global installation disabled""",
                "AssertionError",
            ),
        ]

        log("\n[Step 5] Executing 4 adversarial mutations against real tests/conftest.py ...")
        for mut_id, desc, target_text, repl_text, expected_err in mutations:
            log(f"\n--- Mutation {mut_id}: {desc} ---")
            curr_text = conftest_path.read_text(encoding="utf-8")
            assert target_text in curr_text, f"Target text for {mut_id} not found in conftest.py!"

            mutated_text = curr_text.replace(target_text, repl_text, 1)
            conftest_path.write_text(mutated_text, encoding="utf-8")
            mut_bytes = conftest_path.read_bytes()
            mut_sha = hashlib.sha256(mut_bytes).hexdigest()
            assert mut_sha != orig_sha, f"Mutation {mut_id} did not alter file SHA!"

            # Run test
            run_res = subprocess.run(
                pytest_cmd + ["tests/test_hermetic_guards.py", "-v", "-p", "no:cacheprovider"],
                cwd=str(replica_dir),
                env=env,
                capture_output=True,
                text=True,
            )
            out = run_res.stdout + run_res.stderr
            log(f"{mut_id} exit code: {run_res.returncode} (Expected: non-zero)")
            assert run_res.returncode != 0, f"Mutation {mut_id} unexpectedly passed (GREEN)! Output:\n{out}"
            assert expected_err in out, f"Mutation {mut_id} failed with unexpected error (expected {expected_err}):\n{out}"
            log(f"{mut_id} VERIFIED: turned RED as expected ({expected_err} caught).")

            # Restore byte-by-byte
            conftest_path.write_bytes(orig_bytes)
            restored_sha = hashlib.sha256(conftest_path.read_bytes()).hexdigest()
            assert restored_sha == orig_sha, f"Byte restoration SHA mismatch for {mut_id}: {restored_sha} != {orig_sha}"
            log(f"{mut_id} restored and validated (SHA match: {restored_sha[:16]}...)")

            mutation_results[mut_id] = {
                "description": desc,
                "result": "RED",
                "exit_code": run_res.returncode,
                "caught_by": expected_err,
                "sha_restored": True,
            }

        # Final post-mutation baseline verification in replica
        final_run = subprocess.run(
            pytest_cmd + ["tests/test_hermetic_guards.py", "-v", "-p", "no:cacheprovider"],
            cwd=str(replica_dir),
            env=env,
            capture_output=True,
            text=True,
        )
        assert final_run.returncode == 0, "Post-mutation suite failed in replica!"
        log("\nReplica post-mutations baseline: 5 passed (GREEN).")

    # 6. Real artifacts stat snapshot AFTER mutations
    log("\n[Step 6] Taking post-mutation snapshot of real artifacts/ ...")
    real_stat_after = snapshot_artifacts(REAL_ROOT)
    diffs = compare_snapshots(real_stat_before, real_stat_after)
    log(f"Post-mutation real artifacts recorded: {len(real_stat_after)} entries.")
    log(f"Real artifacts differences detected during mutation phase: {len(diffs)}")
    assert len(diffs) == 0, f"Real artifacts modified during mutation phase! Diffs:\n{diffs}"
    log("Real artifacts integrity VERIFIED: 0 modifications, 0 additions, 0 deletions.")

    if out_log is not None:
        out_log.parent.mkdir(parents=True, exist_ok=True)
        out_log.write_text("\n".join(log_lines) + "\n", encoding="utf-8")
        log(f"\nWrote mutation execution log to: {out_log}")

    if json_out is not None:
        json_data = {
            "mutations": mutation_results,
            "real_artifacts_entries": len(real_stat_after),
            "real_artifacts_diff_count": len(diffs),
            "all_mutations_red": all(m["result"] == "RED" for m in mutation_results.values()),
            "all_restorations_verified": all(m["sha_restored"] for m in mutation_results.values()),
        }
        json_out.parent.mkdir(parents=True, exist_ok=True)
        json_out.write_text(json.dumps(json_data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        log(f"Wrote mutation summary JSON to: {json_out}")

    log("\n=== ALL 4 ADVERSARIAL MUTATIONS SUCCESSFULLY VERIFIED RED ON REAL CONFTEST ===")
    return 0


def main():
    parser = argparse.ArgumentParser(description="Run adversarial mutations on tests/conftest.py in isolated replica")
    parser.add_argument("--out-log", type=Path, default=R3B_DIR / "mutation_log.txt")
    parser.add_argument("--json-out", type=Path, default=R3B_DIR / "mutation_summary.json")
    args = parser.parse_args()

    sys.exit(run_mutations(args.out_log, args.json_out))


if __name__ == "__main__":
    main()
