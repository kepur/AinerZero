"""Bad Control Mutations Runner for S2 Phase 1 W1 (Turn #2).

Covers all 9 mutations (5 original + 4 feedback-required):
- W1-M1: Fallback steps to spec.H_TRAIN if smoke steps missing
- W1-M2: Non-world-cut holdout (sequence permutation)
- W1-M3: Model selection interval defaults to 5 instead of 200
- W1-M4: Data dir fallback to output_root / 'data'
- W1-M5: Generate-data allows passing --arm without rejection
- W1-M6 (New): Restore `or status == "completed"` in _resolve_smoke_train_steps
- W1-M7 (New): Restore `Path.cwd()` in _resolve_paths
- W1-M8 (New): Restore `arm or "arm_a"` in _train_runner
- W1-M9 (New): Remove HOLDOUT_WORLDS tamper check in get_holdout_world_indices

Each mutation is verified to turn RED on its specific target test,
and the source file is verified to be restored byte-for-byte (SHA256 checked).
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import sys
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[3]
VENV_PYTHON = REPO_ROOT / ".venv" / "bin" / "python3"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


MUTATIONS = [
    {
        "id": "W1-M1",
        "description": "Fallback step count to spec.H_TRAIN if smoke steps missing",
        "file": REPO_ROOT / "src/ainerzero/v9/experiments/s2/commands.py",
        "target": 'smoke_steps = _resolve_smoke_train_steps(paths["ledger"])',
        "replacement": 'smoke_steps = _resolve_smoke_train_steps(paths["ledger"]) or 16',
        "test": "tests/v9/experiments/test_s2_w1_integration.py::test_w1_train_rejects_missing_or_failed_smoke",
    },
    {
        "id": "W1-M2",
        "description": "Holdout set cut by random sequence permutation instead of world-cut",
        "file": REPO_ROOT / "src/ainerzero/v9/experiments/s2/train_runner.py",
        "target": "holdout_worlds = get_holdout_world_indices(train_root, holdout_fraction=holdout_fraction)",
        "replacement": "holdout_worlds = set()  # MUTATION W1-M2: no world cut",
        "test": "tests/v9/experiments/test_s2_w1_integration.py::test_w1_train_runner_holdout_separation_and_checkpoint_path",
    },
    {
        "id": "W1-M3",
        "description": "Model selection interval defaults to 5 instead of spec.MODEL_SELECTION_EVERY_STEPS",
        "file": REPO_ROOT / "src/ainerzero/v9/experiments/s2/spec.py",
        "target": "MODEL_SELECTION_EVERY_STEPS = 200",
        "replacement": "MODEL_SELECTION_EVERY_STEPS = 5",
        "test": "tests/v9/experiments/test_s2_w1_integration.py::test_w1_model_selection_interval_defaults_to_spec",
    },
    {
        "id": "W1-M4",
        "description": "Training data directory defaults to output_root / 'data' instead of datasets/train",
        "file": REPO_ROOT / "src/ainerzero/v9/experiments/s2/commands.py",
        "target": 'data_dir = kwargs.get("data_dir") or getattr(args, "data_dir", None) or (Path(output_root) / "datasets" / "train")',
        "replacement": 'data_dir = kwargs.get("data_dir") or getattr(args, "data_dir", None) or (Path(output_root) / "data")',
        "test": "tests/v9/experiments/test_s2_w1_integration.py::test_w1_train_resolves_steps_from_passed_smoke_and_executes",
    },
    {
        "id": "W1-M5",
        "description": "Commands generate-data allows passing --arm without rejection",
        "file": REPO_ROOT / "src/ainerzero/v9/experiments/s2/commands.py",
        "target": """        if arm is not None:
            return {
                "status": "refused",
                "mode": mode,
                "stage": "argument_validation",
                "message": "generate-data does not accept --arm; use --partition instead",
            }, EXIT_FAILED""",
        "replacement": """        if arm is not None:
            pass  # MUTATION W1-M5: allow --arm""",
        "test": "tests/v9/experiments/test_s2_w1_integration.py::test_w1_cli_generate_data_argument_validation",
    },
    {
        "id": "W1-M6",
        "description": "Restore 'or status == completed' in _resolve_smoke_train_steps",
        "file": REPO_ROOT / "src/ainerzero/v9/experiments/s2/commands.py",
        "target": """                # Sole criterion: passed must be True
                if metrics.get("passed") is not True:
                    return None""",
        "replacement": """                # MUTATION W1-M6: restore status == completed
                if not (metrics.get("passed") is True or metrics.get("status") == "completed"):
                    return None""",
        "test": "tests/v9/experiments/test_s2_w1_integration.py::test_w1_f1_resolve_smoke_train_steps_rejects_completed_when_passed_is_false",
    },
    {
        "id": "W1-M7",
        "description": "Restore Path.cwd() in _resolve_paths",
        "file": REPO_ROOT / "src/ainerzero/v9/experiments/s2/commands.py",
        "target": """    repo_root = getattr(args, "repo_root", None)
    if repo_root is not None:
        repo_root = Path(repo_root).resolve()
    else:
        repo_root = Path(__file__).resolve().parents[5]
    expected_self = (repo_root / "src/ainerzero/v9/experiments/s2/commands.py").resolve()
    if not expected_self.is_file() or expected_self != Path(__file__).resolve():
        raise RuntimeError(
            f"Code identity mismatch: repo_root {repo_root} does not contain currently executing {Path(__file__).resolve()}"
        )""",
        "replacement": """    # MUTATION W1-M7: restore Path.cwd()
    repo_root = Path(getattr(args, "repo_root", None) or Path.cwd()).resolve()""",
        "test": "tests/v9/experiments/test_s2_w1_integration.py::test_w1_f7_identity_verification_uses_code_location_not_cwd",
    },
    {
        "id": "W1-M8",
        "description": "Restore 'arm or arm_a' fallback in commands and train_runner",
        "file": REPO_ROOT / "src/ainerzero/v9/experiments/s2/commands.py",
        "target": """        if not arm or str(arm).lower() not in allowed_arms:
            return {
                "status": "refused",
                "mode": mode,
                "stage": "argument_validation",
                "message": f"train requires explicit --arm in {('arm_a', 'arm_b', 'arm_c', 'A', 'B', 'C')}; got {arm!r}",
            }, EXIT_FAILED""",
        "replacement": """        # MUTATION W1-M8: allow missing arm
        if arm and str(arm).lower() not in allowed_arms:
            return {
                "status": "refused",
                "mode": mode,
                "stage": "argument_validation",
                "message": f"train requires explicit --arm in {('arm_a', 'arm_b', 'arm_c', 'A', 'B', 'C')}; got {arm!r}",
            }, EXIT_FAILED""",
        "test": "tests/v9/experiments/test_s2_w1_integration.py::test_w1_f3_train_requires_explicit_arm_and_seed_allowed_sets",
    },
    {
        "id": "W1-M9",
        "description": "Remove HOLDOUT_WORLDS tamper comparison check in get_holdout_world_indices",
        "file": REPO_ROOT / "src/ainerzero/v9/experiments/s2/train_runner.py",
        "target": """    if recorded_worlds != set(expected_holdout):
        raise ValueError(
            f"HOLDOUT_WORLDS.json tamper detected in {train_root}: "
            f"recorded {sorted(recorded_worlds)} != expected {expected_holdout}"
        )""",
        "replacement": """    # MUTATION W1-M9: bypass tamper comparison
    pass""",
        "test": "tests/v9/experiments/test_s2_w1_integration.py::test_w1_f5_holdout_worlds_tamper_detection_and_validation",
    },
]


def run_all_mutations() -> dict[str, Any]:
    results = []
    all_turned_red = True

    for m in MUTATIONS:
        m_id = m["id"]
        target_file = Path(m["file"])
        orig_text = target_file.read_text(encoding="utf-8")
        orig_sha = _sha256(target_file)

        assert m["target"] in orig_text, f"Target text not found for {m_id} in {target_file}"

        # Apply mutation
        mutated_text = orig_text.replace(m["target"], m["replacement"])
        target_file.write_text(mutated_text, encoding="utf-8")

        try:
            # Run pytest on specific test
            cmd = [str(VENV_PYTHON), "-m", "pytest", m["test"], "-v", "--no-header"]
            proc = subprocess.run(cmd, cwd=REPO_ROOT, capture_output=True, text=True)
            turned_red = proc.returncode != 0
            if not turned_red:
                all_turned_red = False

            # Extract failure line
            fail_line = "Test failed as expected"
            for line in proc.stdout.splitlines():
                if "FAILED" in line or "AssertionError" in line or "Failed:" in line or "ValueError" in line:
                    fail_line = line.strip()
                    break

            results.append({
                "id": m_id,
                "description": m["description"],
                "file": str(target_file.relative_to(REPO_ROOT)),
                "target_test": m["test"].split("::")[-1],
                "turned_red": turned_red,
                "exit_code": proc.returncode,
                "failure_summary": fail_line,
            })
            print(f"[{m_id}] Turned RED: {turned_red} (exit {proc.returncode}): {fail_line}")
        finally:
            # Restore file
            target_file.write_text(orig_text, encoding="utf-8")
            restored_sha = _sha256(target_file)
            assert restored_sha == orig_sha, f"Restoration SHA mismatch for {target_file}: {restored_sha} != {orig_sha}"

    summary = {
        "mutations": results,
        "total_mutations": len(results),
        "all_turned_red": all_turned_red,
    }
    out_json = REPO_ROOT / "reports/V9-S2-W1/r2/mutation_summary.json"
    out_json.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(f"\nAll {len(results)} mutations verified! all_turned_red={all_turned_red}")
    return summary


if __name__ == "__main__":
    run_all_mutations()
