"""ainerzero.V9.B2 deliberate-break controls (故意改坏必须变红) - r2 update.

Includes mutations for the 8 security bypass fixes (D-021 §3.1-§3.5).
"""

from __future__ import annotations

import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import time

ROOT = pathlib.Path(__file__).resolve().parents[3]
SOURCE_TREE = ROOT / "src"
TEST_DIR = "tests/v9/contracts"
RESULT_FILE = pathlib.Path(__file__).resolve().parent / "mutation-results.json"
PYTHON = sys.executable

# (name, relative file, (old, new), expected failing test id)
MUTATIONS: tuple = (
    (
        "M1-world-brain-envelope-gate-removed",
        "ainerzero/v9/fakes/world_brain.py",
        (
            "        validated = self.validate_payload(payload)\n",
            "        # MUTATED: payload gate bypassed, step() trusts its input\n"
            "        _t = payload.get(\"time\", {}) if hasattr(payload, \"get\") else {}\n"
            "        validated = type(\"_Ungated\", (), {\n"
            "            \"t_ticks\": _t.get(\"t_ticks\", 0),\n"
            "            \"dt_ticks\": _t.get(\"dt_ticks\", 0),\n"
            "            \"dt_s\": _t.get(\"dt_s\", 0.0),\n"
            "            \"sim_hz\": _t.get(\"sim_hz\", 120),\n"
            "            \"channel_kinds\": (),\n"
            "            \"used_pose_sensor\": False,\n"
            "            \"raw\": payload,\n"
            "        })()\n",
        ),
        "test_step_rejects_whole_envelope",
    ),
    (
        "M2-world-brain-clock-jump-allowed",
        "ainerzero/v9/fakes/world_brain.py",
        (
            "            if validated.t_ticks != expected_ticks:\n",
            "            if False and validated.t_ticks != expected_ticks:  # MUTATED\n",
        ),
        "test_probe_time_jump",
    ),
    (
        "M3-ref-traversal-allowed",
        "ainerzero/v9/interfaces/validation.py",
        (
            "    if \"..\" in uri or \"/./\" in uri or uri.endswith(\"/.\"):\n",
            "    if False:  # MUTATED: traversal allowed\n",
        ),
        "test_probe_ref_traversal",
    ),
    (
        "M4-ref-future-tick-allowed",
        "ainerzero/v9/interfaces/validation.py",
        (
            "            if tick > as_of_t_ticks:\n",
            "            if False:  # MUTATED: future tick allowed\n",
        ),
        "test_probe_ref_future_ext",
    ),
    (
        "M5-ref-fail-closed-removed",
        "ainerzero/v9/interfaces/validation.py",
        (
            "        if not found_in_markers:\n"
            "            raise ReferenceRejected(\n",
            "        if False:\n"
            "            raise ReferenceRejected(\n",
        ),
        "test_probe_ref_fail_closed",
    ),
    (
        "M6-key-normalization-removed",
        "ainerzero/v9/interfaces/validation.py",
        (
            "            norm_key = unicodedata.normalize(\"NFKC\", key).lower()\n",
            "            norm_key = key.lower()  # MUTATED: no NFKC\n",
        ),
        "test_probe_truth_nfkc_variant",
    ),
    (
        "M7-producer-registry-bypassed",
        "ainerzero/v9/interfaces/validation.py",
        (
            "    category = PRODUCER_REGISTRY.get(producer)\n"
            "    if category is None:\n",
            "    category = \"baseline\"  # MUTATED: trust all producers\n"
            "    if False:\n",
        ),
        "test_probe_teacher_alias",
    ),
    (
        "M8-forbidden-producer-allowed",
        "ainerzero/v9/interfaces/validation.py",
        (
            "    if category in {\"teacher\", \"llm\", \"assistant\", \"human_unreviewed\"}:\n",
            "    if False:  # MUTATED: teacher/llm allowed to write SLOW\n",
        ),
        "test_probe_llm_alias",
    ),
)

CONTROL = ("control-unmutated-copy", None, None, None)


def build_shadow_tree(base: pathlib.Path) -> pathlib.Path:
    """Copy the whole importable package (minus caches) so relative imports survive."""
    target = base / "src"
    shutil.copytree(
        SOURCE_TREE,
        target,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo"),
    )
    return target


def run_pytest(shadow_src: pathlib.Path, label: str) -> dict:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(shadow_src) + os.pathsep + env.get("PYTHONPATH", "")
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    started = time.time()
    completed = subprocess.run(
        [PYTHON, "-m", "pytest", TEST_DIR, "-q", "--no-header", "-rf"],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=600,
    )
    output = completed.stdout + completed.stderr
    failed = []
    for line in output.splitlines():
        stripped = line.strip()
        if stripped.startswith("FAILED ") or stripped.startswith("ERROR "):
            fields = stripped.split()
            if len(fields) >= 2:
                failed.append(fields[1])  # e.g. tests/v9/contracts/test_x.py::test_y
    passed = None
    for line in output.splitlines():
        if " passed" in line and " failed" not in line:
            passed = line.strip()
        elif " failed" in line or " error" in line:
            passed = line.strip()
    return {
        "label": label,
        "returncode": completed.returncode,
        "failed": failed,
        "summary": passed,
        "seconds": round(time.time() - started, 2),
        "tail": "\n".join(output.splitlines()[-12:]),
    }


def apply_mutation(text: str, old: str, new: str, name: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(
            f"{name}: mutation anchor found {count} times (expected exactly 1); "
            "the source drifted and the harness must not silently no-op"
        )
    mutated = text.replace(old, new, 1)
    if mutated == text:
        raise SystemExit(f"{name}: mutation did not change the file")
    return mutated


def main() -> int:
    results = []
    overall_ok = True
    with tempfile.TemporaryDirectory(prefix="v9b2-mutations-") as tmp:
        base = pathlib.Path(tmp)
        for name, relative, mutation, expected in (CONTROL, *MUTATIONS):
            work = base / name
            work.mkdir()
            shadow_src = build_shadow_tree(work)
            if relative is not None:
                target = shadow_src / relative
                source_text = target.read_text(encoding="utf-8")
                old, new = mutation
                target.write_text(apply_mutation(source_text, old, new, name), encoding="utf-8")
            outcome = run_pytest(shadow_src, name)
            entry = {
                "name": name,
                "mutated_file": relative,
                "expected_red_test": expected,
                **outcome,
            }
            if relative is None:
                ok = outcome["returncode"] == 0 and not outcome["failed"]
            else:
                # mutant must be red AND the expected test must fail
                ok = outcome["returncode"] != 0 and any(expected in f for f in outcome["failed"])
            
            print(f"[{'GREEN' if ok else 'RED'}] {name}: {'control' if relative is None else 'caught' if ok else 'failed'} ({outcome['seconds']}s)")
            if not ok:
                overall_ok = False
            results.append(entry)

    RESULT_FILE.write_text(json.dumps(results, indent=2), encoding="utf-8")
    return 0 if overall_ok else 1


if __name__ == "__main__":
    sys.exit(main())
