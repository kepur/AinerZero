#!/usr/bin/env python3
"""Evidence 6: Mutation testing on isolated copy of commit 34a1753.

Tests 6 distinct mutations across cells.py, candidate generation, and verify_s6p1.py:
  Mutant 1: Unsealed selection (remove sealed() context in select)
  Mutant 2: Arm T pick seed decoupled from Arm R (T picks differently)
  Mutant 3: Corrupted closest_pair score in Z arm (inverting distance metric)
  Mutant 4: Arm P evaluated with non-None z (violates base output evaluation)
  Mutant 5: Candidate states drawn with replacement (allows duplicate states)
  Mutant 6: Verification replay check bypass (always return passed=True in replay_cell)

Runs the native tests against each mutant and confirms all mutants are caught (killed).
"""
import os
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]
LOCK_HARNESS = REPO / "reports/V9-S4-PHASE1/impl-review-r2-recheck/evidence/harness/hold_lock.py"
LOCK_FILE = REPO / "artifacts/locks/m0-worker.lock"
VENV_PY = REPO / ".venv/bin/python"
VENV_PYTEST = REPO / ".venv/bin/pytest"

ARCHIVE_DIR = Path("/tmp/s6_34a1753")


def run_test_under_lock(mutant_dir: Path, test_file: str, test_filter: str | None = None):
    env = dict(os.environ)
    env["PYTHONPATH"] = f"{mutant_dir}/src:{mutant_dir}/reports/V9-S6-PHASE1"
    cmd = [
        str(VENV_PYTEST),
        "--native-mlx",
        f"{mutant_dir}/{test_file}",
        "-v",
    ]
    if test_filter:
        cmd.extend(["-k", test_filter])

    r = subprocess.run(cmd, env=env, capture_output=True, text=True, cwd=str(mutant_dir))
    return r


def main():
    if not ARCHIVE_DIR.is_dir():
        print(f"Error: {ARCHIVE_DIR} does not exist. Run git archive first.")
        sys.exit(1)

    work_dir = Path("/tmp/s6_mutants_work")
    if work_dir.exists():
        shutil.rmtree(work_dir)
    work_dir.mkdir(parents=True)

    mutations = [
        {
            "id": "mutant_1_unsealed_selection",
            "file": "src/ainerzero/v9/experiments/s6/cells.py",
            "target": "        with sealed():\n            st = track.cp.states()",
            "replace": "        if True:\n            st = track.cp.states()",
            "test_file": "tests/v9/experiments/test_s6_cells_static.py",
            "test_filter": "test_select_reads_only_states_and_remaining_from_the_pool_and_runs_sealed",
            "desc": "Remove sealed() context manager during selection in select()",
        },
        {
            "id": "mutant_2_arm_t_pick_seed",
            "file": "src/ainerzero/v9/experiments/s6/cells.py",
            "target": '    return W.derive_seed(cand_ns, "s6-pick", "R" if arm == "T" else arm, k)',
            "replace": '    return W.derive_seed(cand_ns, "s6-pick", arm, k)',
            "test_file": "tests/v9/experiments/test_s6_cells_native.py",
            "test_filter": "test_every_arm_runs_and_records",
            "desc": "Decouple Arm T pick seed from Arm R (pick_seed uses arm instead of R)",
        },
        {
            "id": "mutant_3_z_arm_selection_divergence",
            "file": "src/ainerzero/v9/experiments/s6/cells.py",
            "target": '            elif arm == "Z":\n                score = closest_pair(st)',
            "replace": '            elif arm == "Z":\n                score = -closest_pair(st)',
            "test_file": "tests/v9/experiments/test_s6_cells_native.py",
            "test_filter": "test_z_picks_the_closest_pairs",
            "desc": "Z arm selection in select() deviates from closest_pair (inverted score assigned)",
        },
        {
            "id": "mutant_4_eval_arm_p_perturbed",
            "file": "src/ainerzero/v9/experiments/s6/cells.py",
            "target": "        m.load_weights(str(path))\n        m.z = None",
            "replace": "        m.load_weights(str(path))\n        m.z = mx.zeros((1, E.DZ))",
            "test_file": "tests/v9/experiments/test_s6_cells_native.py",
            "test_filter": "test_evaluation_arithmetic",
            "desc": "Arm P evaluated with non-None z (perturbation vector set) instead of base output",
        },
        {
            "id": "mutant_5_candidate_replacement",
            "file": "src/ainerzero/v9/experiments/s6/cells.py",
            "target": "    pick = np.random.default_rng(pool_seed(cand_ns, k)).choice(len(pairs), sizes.pool, replace=False)",
            "replace": "    pick = np.random.default_rng(pool_seed(cand_ns, k)).choice(len(pairs), sizes.pool, replace=True)",
            "test_file": "tests/v9/experiments/test_s6_cells_native.py",
            "test_filter": "test_candidate_states_distinct_deterministic_and_sorted",
            "desc": "Candidate states drawn with replacement (allows duplicate states in candidate pool)",
        },
        {
            "id": "mutant_6_replay_verification_bypass",
            "file": "reports/V9-S6-PHASE1/verify_s6p1.py",
            "target": '    out["passed"] = bool(out["first_ok"] and all(out["rounds_ok"]))',
            "replace": '    out["passed"] = True',
            "test_file": "tests/v9/experiments/test_s6p1_runner_native.py",
            "test_filter": "test_a_tampered_cell_stops_evaluation_before_any_test_world",
            "desc": "Bypass replay verification in verify_s6p1.py (always return passed=True in replay_cell)",
        },
    ]

    results = []
    print(f"Testing {len(mutations)} mutants on isolated archive of 34a1753...")

    for m in mutations:
        mid = m["id"]
        print(f"\n--- Testing {mid} ---")
        print(f"Description: {m['desc']}")
        mdir = work_dir / mid
        shutil.copytree(ARCHIVE_DIR, mdir)

        # Apply mutation
        target_file = mdir / m["file"]
        content = target_file.read_text(encoding="utf-8")
        if m["target"] not in content:
            print(f"ERROR: target pattern not found in {m['file']}!")
            sys.exit(1)
        mutated_content = content.replace(m["target"], m["replace"], 1)
        target_file.write_text(mutated_content, encoding="utf-8")

        # Run test
        r = run_test_under_lock(mdir, m["test_file"], m["test_filter"])
        killed = (r.returncode != 0)
        print(f"Exit code: {r.returncode}, Mutant killed? {killed}")
        if killed:
            print("Killed with output excerpt:")
            lines = [l for l in (r.stdout + r.stderr).splitlines() if "FAILED" in l or "AssertionError" in l or "assert" in l or "Error" in l]
            for l in lines[:5]:
                print(f"  {l}")
        else:
            print("WARNING: Mutant survived!")
            print(r.stdout[-500:])
            print(r.stderr[-500:])

        results.append({
            "id": mid,
            "desc": m["desc"],
            "target_test": f"{m['test_file']}::{m['test_filter']}",
            "killed": killed,
            "exit_code": r.returncode,
        })

    print("\n================ MUTATION TESTING SUMMARY ================")
    all_killed = all(r["killed"] for r in results)
    for r in results:
        status = "KILLED" if r["killed"] else "SURVIVED"
        print(f"[{status}] {r['id']}: {r['desc']}")
    print(f"Total: {sum(r['killed'] for r in results)}/{len(results)} mutants killed.")
    assert all_killed, "Not all mutants were killed!"
    print("ALL MUTANTS KILLED!")


if __name__ == "__main__":
    main()
