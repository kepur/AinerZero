#!/usr/bin/env python3
"""Run reviewer mutations against data_runner to verify test sensitivity (ainerzero.V9.P139).

Mutations:
- REV-M1: Weaken guard check from is_relative_to(artifacts_root) to only out_path == artifacts_root.
- REV-M2: Inject goal_episode_specs into sealed_final/LAYOUT_DIGESTS.json.
- REV-M3: Revert disjointness check to open sealed_final/manifest.json instead of LAYOUT_DIGESTS.json.
"""

import hashlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path("/Users/mac/AinerWorkFlow/AinerZero").resolve()
TARGET_FILE = REPO_ROOT / "src" / "ainerzero" / "v9" / "experiments" / "s2" / "data_runner.py"
PYTHON_BIN = REPO_ROOT / ".venv" / "bin" / "python"
VERIFY_SCRIPT = REPO_ROOT / "reports" / "V9-S2-P138" / "review" / "verify_all.py"


def sha256_file(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


MUTATIONS = [
    {
        "id": "REV-M1",
        "name": "weaken_guard_to_exact_artifacts_root_only",
        "description": "Guard checks `out_path == artifacts_root` instead of `is_relative_to(artifacts_root)`, permitting subpaths like s2/other",
        "target": 'if out_path == artifacts_root or out_path.is_relative_to(artifacts_root):',
        "replacement": 'if out_path == artifacts_root:',
        "target_check": "Five guard paths (s2/other rejection)",
    },
    {
        "id": "REV-M2",
        "name": "leak_goal_episode_specs_into_layout_digests",
        "description": "Include goal_episode_specs in sealed_final/LAYOUT_DIGESTS.json payload",
        "target": '"layout_digests": list(manifest_data.get("layout_digests", [])),',
        "replacement": '"layout_digests": list(manifest_data.get("layout_digests", [])),\n                "goal_episode_specs": [{"leaked": True}],',
        "target_check": "LAYOUT_DIGESTS.json strictly 3 fields check",
    },
    {
        "id": "REV-M3",
        "name": "read_sealed_final_manifest_during_disjointness",
        "description": "Disjointness check opens sealed_final/manifest.json instead of LAYOUT_DIGESTS.json",
        "target": 'cand_layout = cand_dir / "LAYOUT_DIGESTS.json"',
        "replacement": 'cand_layout = cand_dir / "manifest.json"',
        "target_check": "Zero readback patching check on sealed_final",
    },
]


def run_mutation(mut: dict) -> dict:
    original_text = TARGET_FILE.read_text(encoding="utf-8")
    original_sha = hashlib.sha256(original_text.encode("utf-8")).hexdigest()

    assert mut["target"] in original_text, f"Target string not found for mutation {mut['id']}"
    mutated_text = original_text.replace(mut["target"], mut["replacement"], 1)

    try:
        # Apply mutation
        TARGET_FILE.write_text(mutated_text, encoding="utf-8")
        mutated_sha = hashlib.sha256(TARGET_FILE.read_bytes()).hexdigest()
        assert mutated_sha != original_sha

        # Run verification suite
        proc = subprocess.run(
            [str(PYTHON_BIN), str(VERIFY_SCRIPT)],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
        )

        # Did it fail (red)?
        killed = (proc.returncode != 0)
        status = "KILLED" if killed else "SURVIVED"

        return {
            "id": mut["id"],
            "name": mut["name"],
            "description": mut["description"],
            "status": status,
            "exit_code": proc.returncode,
            "killed": killed,
            "stdout_tail": proc.stdout[-500:] if proc.stdout else "",
            "stderr_tail": proc.stderr[-500:] if proc.stderr else "",
        }

    finally:
        # Restore original code
        TARGET_FILE.write_text(original_text, encoding="utf-8")
        restored_sha = hashlib.sha256(TARGET_FILE.read_bytes()).hexdigest()
        assert restored_sha == original_sha, f"SHA mismatch on restore for {mut['id']}"


def main():
    print(f"=== Starting Reviewer Mutation Testing for ainerzero.V9.P139 ===")
    initial_sha = sha256_file(TARGET_FILE)
    print(f"Target: {TARGET_FILE}")
    print(f"Initial SHA256: {initial_sha}")

    results = []
    for mut in MUTATIONS:
        print(f"\nRunning mutation {mut['id']}: {mut['name']}...")
        res = run_mutation(mut)
        print(f"  Result: {res['status']} (exit_code={res['exit_code']})")
        results.append(res)

    final_sha = sha256_file(TARGET_FILE)
    assert final_sha == initial_sha, "Final target file SHA does not match initial SHA!"
    print(f"\nAll mutations finished. Target file cleanly restored (SHA256 verified).")

    summary_file = REPO_ROOT / "reports" / "V9-S2-P138" / "review" / "mutation_summary.json"
    with open(summary_file, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    print(f"Saved mutation summary to {summary_file}")

    all_killed = all(r["killed"] for r in results)
    if all_killed:
        print("[SUCCESS] All 3 reviewer mutations were KILLED by verification suite.")
        return 0
    else:
        print("[FAIL] Some mutations SURVIVED!")
        return 1


if __name__ == "__main__":
    sys.exit(main())
