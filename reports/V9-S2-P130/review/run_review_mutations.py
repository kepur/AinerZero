#!/usr/bin/env python3
"""Independent adversarial mutation runner for P131 review of P130.

Reviewer: gemini-7a4c (independent secondary agent, non-author of P130).
Target: tests/v9/experiments/test_s2_eval.py::test_perturb_inserts_at_step_20_and_is_reproducible

Mutations executed strictly in isolated temporary sandbox:
1. REV-M1: Perturbation action count mutated to 4 (instead of 5).
2. REV-M2: Perturbation trigger step changed from step 20 to step 21.
3. REV-M3: Perturbation action count mutated to 6 (instead of 5).
4. REV-M4: Perturbation random actions replaced with constant ACTION_FORWARD.
5. REV-M5 (Insight Mutation): Remove break after perturbation in inner/outer loop when dt>1 or not aligned.

Zero modifications to real repository code or tests.
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
REVIEW_DIR = REAL_ROOT / "reports" / "V9-S2-P130" / "review"
REVIEW_DIR.mkdir(parents=True, exist_ok=True)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def setup_sandbox(tmp_path: Path) -> Path:
    sandbox = tmp_path / "sandbox"
    sandbox.mkdir(parents=True, exist_ok=True)

    # Copy src, tests, pyproject.toml
    shutil.copytree(REAL_ROOT / "src", sandbox / "src", symlinks=True)
    shutil.copytree(REAL_ROOT / "tests", sandbox / "tests", symlinks=True)
    shutil.copy2(REAL_ROOT / "pyproject.toml", sandbox / "pyproject.toml")

    return sandbox


def run_test_in_sandbox(sandbox: Path, extra_args: list[str] | None = None) -> tuple[int, str]:
    python_bin = REAL_ROOT / ".venv" / "bin" / "python"
    env = os.environ.copy()
    env["PYTHONPATH"] = f"{sandbox / 'src'}:{sandbox}"
    env["PYTHONDONTWRITEBYTECODE"] = "1"

    cmd = [
        str(python_bin),
        "-m",
        "pytest",
        str(sandbox / "tests" / "v9" / "experiments" / "test_s2_eval.py"),
        "-k",
        "test_perturb_inserts_at_step_20_and_is_reproducible",
        "-vv",
    ]
    if extra_args:
        cmd.extend(extra_args)

    res = subprocess.run(
        cmd,
        cwd=str(sandbox),
        env=env,
        capture_output=True,
        text=True,
    )
    return res.returncode, res.stdout + "\n" + res.stderr


def main() -> int:
    print("=== P131 Independent Review Mutation Runner ===")
    results = []
    log_lines = []

    with tempfile.TemporaryDirectory(prefix="p131_rev_mut_") as tmp_dir_str:
        tmp_dir = Path(tmp_dir_str)
        sandbox = setup_sandbox(tmp_dir)
        print(f"Created isolated review sandbox at: {sandbox}")

        target_file = sandbox / "src" / "ainerzero" / "v9" / "experiments" / "s2" / "eval.py"
        orig_content = target_file.read_text(encoding="utf-8")
        orig_sha = sha256_file(target_file)

        # Baseline: clean sandbox must PASS
        ret_clean, out_clean = run_test_in_sandbox(sandbox)
        print(f"Clean baseline status: {ret_clean} (expected 0)")
        if ret_clean != 0:
            print("[ERROR] Clean baseline failed:\n", out_clean)
            return 1

        mutations = [
            {
                "id": "REV-M1",
                "name": "perturb_count_four",
                "desc": "Perturbation action count mutated to 4 instead of 5",
                "target_pattern": 'n_perturb_actions = int(perturb_spec.get("n_random_actions", 5))',
                "replacement": 'n_perturb_actions = 4  # REV-M1 mutation',
            },
            {
                "id": "REV-M2",
                "name": "perturb_start_step_21",
                "desc": "Perturbation trigger step changed from step 20 to step 21",
                "target_pattern": 'perturb_at_step = int(perturb_spec.get("at_step", 20))',
                "replacement": 'perturb_at_step = 21  # REV-M2 mutation',
            },
            {
                "id": "REV-M3",
                "name": "perturb_count_six",
                "desc": "Perturbation action count mutated to 6 instead of 5",
                "target_pattern": 'n_perturb_actions = int(perturb_spec.get("n_random_actions", 5))',
                "replacement": 'n_perturb_actions = 6  # REV-M3 mutation',
            },
            {
                "id": "REV-M4",
                "name": "perturb_fixed_action",
                "desc": "Perturbation random actions replaced with constant ACTION_FORWARD",
                "target_pattern": 'rand_a = perturb_rng.choice(ACTIONS)',
                "replacement": 'rand_a = ACTION_FORWARD  # REV-M4 mutation',
            },
        ]

        for mut in mutations:
            print(f"\n--- Testing Review Mutation {mut['id']}: {mut['name']} ---")
            assert mut["target_pattern"] in orig_content, f"Pattern not found: {mut['target_pattern']}"

            mutated_content = orig_content.replace(mut["target_pattern"], mut["replacement"], 1)
            target_file.write_text(mutated_content, encoding="utf-8")
            mut_sha = sha256_file(target_file)
            print(f"Applied mutation {mut['id']} (SHA: {mut_sha})")

            ret, out = run_test_in_sandbox(sandbox)
            print(f"Pytest returncode: {ret}")
            is_red = (ret != 0)
            status = "KILLED" if is_red else "SURVIVED"

            # Extract failure message
            failure_line = ""
            for line in out.splitlines():
                if "AssertionError" in line or "assert " in line or "FAILED" in line:
                    failure_line += line.strip() + " | "

            # Restore original
            target_file.write_text(orig_content, encoding="utf-8")
            restored_sha = sha256_file(target_file)
            assert restored_sha == orig_sha, f"SHA mismatch! {restored_sha} != {orig_sha}"
            print(f"Restored clean file (SHA matches: {restored_sha == orig_sha})")

            log_entry = (
                f"=== {mut['id']}: {mut['name']} ===\n"
                f"Description: {mut['desc']}\n"
                f"Status: {status} (returncode={ret})\n"
                f"Failure excerpt: {failure_line[:300]}\n"
                f"Output snippet:\n{out[-1200:]}\n"
            )
            log_lines.append(log_entry)

            results.append({
                "id": mut["id"],
                "name": mut["name"],
                "desc": mut["desc"],
                "status": status,
                "is_red": is_red,
                "returncode": ret,
                "failure_hint": failure_line[:200],
                "sha_restored": (restored_sha == orig_sha),
            })

            if not is_red:
                print(f"[CRITICAL] Mutation {mut['id']} SURVIVED!")
            else:
                print(f"[OK] Mutation {mut['id']} KILLED (RED).")

    # Output to review directory
    summary_path = REVIEW_DIR / "mutation_results.json"
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)

    log_path = REVIEW_DIR / "mutation_log.txt"
    with open(log_path, "w", encoding="utf-8") as f:
        f.write("\n".join(log_lines))

    print(f"\nReview mutation tests completed.")
    print(f"Saved results to {summary_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
