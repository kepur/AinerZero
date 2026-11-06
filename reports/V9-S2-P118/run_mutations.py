#!/usr/bin/env python3
"""Adversarial mutation verification for S2 Planner ForwardCounter (P118).

Tests DESIGN-r2 §4 episode-scoped goal embedding caching:
- Replica isolation: copies src/, tests/, pyproject.toml to a temporary directory.
- Asserts that import resolution resolves strictly to the replica copy.
- 3 Mutations directly applied to replica's src/ainerzero/v9/experiments/s2/fwd_counter.py:
    P118-M1: begin_episode does not clear cache -> RED (fails new episode test)
    P118-M2: cache hit still charges count -> RED (fails 1-charge assertion)
    P118-M3: changing goal silently reuses old cache -> RED (fails ValueError raise assertion)
- Each mutation is restored byte-by-byte with SHA-256 validation.
- Verifies real repository artifacts/ stat remains untouched (0 diffs).
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

REAL_ROOT = Path(__file__).resolve().parents[2]
REPORT_DIR = REAL_ROOT / "reports/V9-S2-P118"


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
        elif list(before[k]) != list(after[k]):
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


def sha256_file(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def run_mutations() -> dict:
    log_lines = []

    def log(msg: str) -> None:
        print(msg)
        log_lines.append(msg)

    log("=== S2 FORWARD COUNTER ADVERSARIAL MUTATION VERIFICATION (P118) ===")

    # 1. Real artifacts stat snapshot BEFORE mutations
    log("\n[Step 1] Recording pre-mutation snapshot of real artifacts/ ...")
    t0_stat = time.time()
    real_stat_before = snapshot_artifacts(REAL_ROOT)
    log(f"Pre-mutation real artifacts recorded: {len(real_stat_before)} entries ({time.time() - t0_stat:.2f}s)")

    venv_pytest = REAL_ROOT / ".venv" / "bin" / "pytest"
    assert venv_pytest.exists(), f"Virtualenv pytest not found at {venv_pytest}"
    pytest_cmd = [str(venv_pytest)]

    mutation_results = {}

    with tempfile.TemporaryDirectory(prefix="p118-mut-iso-") as tmpdir:
        replica_dir = Path(tmpdir) / "replica"
        replica_dir.mkdir(parents=True, exist_ok=True)

        log(f"\n[Step 2] Staging isolated replica under {replica_dir} ...")
        shutil.copytree(REAL_ROOT / "src", replica_dir / "src")
        shutil.copytree(REAL_ROOT / "tests", replica_dir / "tests")
        if (REAL_ROOT / "pyproject.toml").exists():
            shutil.copy2(REAL_ROOT / "pyproject.toml", replica_dir / "pyproject.toml")

        # Assert replica isolation
        env = os.environ.copy()
        src_path = str(replica_dir / "src")
        env["PYTHONPATH"] = f"{replica_dir}:{src_path}"

        check_code = (
            "import sys, ainerzero.v9.experiments.s2.fwd_counter as m; "
            f"assert str(m.__file__).startswith({str(replica_dir)!r}), "
            f"'Import leak: ' + str(m.__file__)"
        )
        proc_check = subprocess.run(
            [sys.executable, "-c", check_code],
            env=env,
            cwd=str(replica_dir),
            capture_output=True,
            text=True,
        )
        assert proc_check.returncode == 0, f"Replica import isolation check failed: {proc_check.stderr}"
        log("[Step 3] Replica import isolation verified successfully.")

        target_file = replica_dir / "src/ainerzero/v9/experiments/s2/fwd_counter.py"
        assert target_file.exists(), f"Target file not found: {target_file}"
        orig_bytes = target_file.read_bytes()
        orig_sha = sha256_file(target_file)
        orig_text = orig_bytes.decode("utf-8")
        log(f"Original fwd_counter.py SHA256: {orig_sha}")

        # Baseline run on clean replica
        log("\n[Step 4] Running baseline test on unmutated replica...")
        res_baseline = subprocess.run(
            pytest_cmd + ["tests/v9/experiments/test_s2_planner.py", "-v"],
            cwd=str(replica_dir),
            env=env,
            capture_output=True,
            text=True,
        )
        assert res_baseline.returncode == 0, f"Clean baseline failed:\n{res_baseline.stdout}\n{res_baseline.stderr}"
        log("Baseline: 10 passed (GREEN).")

        # Define 3 mutations
        mutations = [
            (
                "P118-M1",
                "Cache never cleared on begin_episode (begin_episode does not reset _goal_sha/_goal_cache)",
                (
                    "    def begin_episode(self) -> None:\n"
                    '        """Begin a new episode: clear episode-scoped caches."""\n'
                    "        self._goal_cache = None\n"
                    "        self._goal_sha = None\n"
                ),
                (
                    "    def begin_episode(self) -> None:\n"
                    '        """Begin a new episode: clear episode-scoped caches."""\n'
                    "        pass  # MUTATION P118-M1: do not clear cache\n"
                ),
                "test_goal_embedding_cached_across_decisions_in_episode",
            ),
            (
                "P118-M2",
                "Cache hit still charges encode (charge count unconditionally)",
                (
                    "        if self._goal_sha is not None:\n"
                    "            if sha != self._goal_sha:\n"
                    "                raise ValueError(\n"
                    '                    f"goal observation changed within the same episode: "\n'
                    '                    f"cached {self._goal_sha[:16]}... vs new {sha[:16]}..."\n'
                    "                )\n"
                    "            return self._goal_cache\n"
                ),
                (
                    "        if self._goal_sha is not None:\n"
                    "            if sha != self._goal_sha:\n"
                    "                raise ValueError(\n"
                    '                    f"goal observation changed within the same episode: "\n'
                    '                    f"cached {self._goal_sha[:16]}... vs new {sha[:16]}..."\n'
                    "                )\n"
                    "            self.charge('encode', 1)  # MUTATION P118-M2: charge on hit\n"
                    "            return self._goal_cache\n"
                ),
                "test_goal_embedding_cached_across_decisions_in_episode",
            ),
            (
                "P118-M3",
                "Changing goal observation in same episode silently returns old cache without raising",
                (
                    "        if self._goal_sha is not None:\n"
                    "            if sha != self._goal_sha:\n"
                    "                raise ValueError(\n"
                    '                    f"goal observation changed within the same episode: "\n'
                    '                    f"cached {self._goal_sha[:16]}... vs new {sha[:16]}..."\n'
                    "                )\n"
                    "            return self._goal_cache\n"
                ),
                (
                    "        if self._goal_sha is not None:\n"
                    "            # MUTATION P118-M3: do not raise on goal change, return old cache\n"
                    "            return self._goal_cache\n"
                ),
                "test_goal_embedding_changed_goal_in_same_episode_raises",
            ),
        ]

        log(f"\n[Step 5] Executing {len(mutations)} adversarial mutations...")
        for m_id, desc, orig_sub, mut_sub, expected_failure_test in mutations:
            log(f"\n--- Running Mutation {m_id}: {desc} ---")
            assert orig_sub in orig_text, f"Mutation target substring not found for {m_id}"
            mutated_text = orig_text.replace(orig_sub, mut_sub, 1)
            target_file.write_text(mutated_text, encoding="utf-8")
            mut_sha = sha256_file(target_file)
            log(f"Applied mutation {m_id}. Mutated file SHA256: {mut_sha}")

            # Run test
            res = subprocess.run(
                pytest_cmd + ["tests/v9/experiments/test_s2_planner.py"],
                cwd=str(replica_dir),
                env=env,
                capture_output=True,
                text=True,
            )

            is_red = res.returncode != 0
            has_expected_fail = expected_failure_test in res.stdout or expected_failure_test in res.stderr
            log(f"Result for {m_id}: exit_code={res.returncode}, red={is_red}, detected={has_expected_fail}")
            if not (is_red and has_expected_fail):
                log("STDOUT:\n" + res.stdout)
                log("STDERR:\n" + res.stderr)
                raise AssertionError(f"Mutation {m_id} FAILED to turn RED as expected!")

            mutation_results[m_id] = {
                "id": m_id,
                "description": desc,
                "expected_failure_test": expected_failure_test,
                "returncode": res.returncode,
                "red": is_red,
                "detected": has_expected_fail,
                "summary": [line for line in res.stdout.splitlines() if "FAILED" in line or "passed" in line][-3:],
            }

            # Restore byte-for-byte and verify SHA
            target_file.write_bytes(orig_bytes)
            restored_sha = sha256_file(target_file)
            assert restored_sha == orig_sha, f"SHA mismatch after restoring from {m_id}: {restored_sha} != {orig_sha}"
            log(f"Restored fwd_counter.py: SHA256 verified identical ({restored_sha}).")

            # Verify clean restore passes tests
            res_restored = subprocess.run(
                pytest_cmd + ["tests/v9/experiments/test_s2_planner.py"],
                cwd=str(replica_dir),
                env=env,
                capture_output=True,
                text=True,
            )
            assert res_restored.returncode == 0, f"Tests failed after restore for {m_id}!"
            log(f"Verification after restore: GREEN.")

    # Post-mutation snapshot of real artifacts
    log("\n[Step 6] Recording post-mutation snapshot of real artifacts/ ...")
    t0_stat_post = time.time()
    real_stat_after = snapshot_artifacts(REAL_ROOT)
    log(f"Post-mutation real artifacts recorded: {len(real_stat_after)} entries ({time.time() - t0_stat_post:.2f}s)")

    diffs = compare_snapshots(real_stat_before, real_stat_after)
    log(f"Real artifacts stat differences count: {len(diffs)}")
    assert len(diffs) == 0, f"Real artifacts were modified during mutations: {diffs}"
    log("ZERO real artifact changes confirmed.")

    out_log = REPORT_DIR / "mutation_log.txt"
    out_log.write_text("\n".join(log_lines) + "\n", encoding="utf-8")
    print(f"\nWritten mutation log to {out_log}")

    return mutation_results


if __name__ == "__main__":
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    results = run_mutations()
    out_json = REPORT_DIR / "mutation_summary.json"
    out_json.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(f"Saved mutation summary to {out_json}")
