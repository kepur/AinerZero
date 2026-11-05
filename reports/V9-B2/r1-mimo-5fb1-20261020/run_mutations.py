"""ainerzero.V9.B2 deliberate-break controls (故意改坏必须变红).

Each mutant is one registered textual mutation applied to a **copy** of the
whole ``src/ainerzero/v9`` package in a temporary directory (the copy is placed
first on ``PYTHONPATH`` so it shadows the installed package); pytest then runs
the same contract suite ``tests/v9/contracts``.

Harness guarantees (all enforced, non-zero exit otherwise):

- the unmutated control copy must be green (proves the shadow copy is the one
  under test and the baseline passes);
- every functional mutation must make the suite red with exit != 0, and the
  expected test id must appear among the failures;
- each mutation anchor must occur exactly once before it is applied (so a
  silently drifting source cannot turn the harness into a no-op).

No persistent source file is modified: the shadow tree lives in a temp
directory that is removed afterwards.  Results are written to
``mutation-results.json`` next to this script.
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
        "M2-world-brain-backwards-time-allowed",
        "ainerzero/v9/fakes/world_brain.py",
        (
            "        if validated.t_ticks < self._t_ticks:\n",
            "        if False and validated.t_ticks < self._t_ticks:  # MUTATED\n",
        ),
        "test_step_rejects_backwards_time",
    ),
    (
        "M3-geometry-inverse-returns-transpose",
        "ainerzero/v9/fakes/geometry.py",
        (
            "        rotation = transform[:2, :2].T\n"
            "        out = np.eye(3)\n"
            "        out[:2, :2] = rotation\n"
            "        out[:2, 2] = -(rotation @ transform[:2, 2])\n"
            "        return out\n",
            "        return transform.T  # MUTATED: transpose is not the group inverse\n",
        ),
        "test_compose_inverse_is_identity",
    ),
    (
        "M4-geometry-canonicalize-becomes-identity",
        "ainerzero/v9/fakes/geometry.py",
        (
            "        values = np.asarray(x, dtype=float)\n"
            "        if values.shape[-1] == 3:\n"
            "            result = (values - np.array([belief.mean[0, 2], belief.mean[1, 2], 0.0])) @ _rotation3(\n"
            "                belief.mean\n"
            "            )\n",
            "        return x  # MUTATED: identity canonicalisation (式 9 removed)\n"
            "        values = np.asarray(x, dtype=float)\n"
            "        if values.shape[-1] == 3:\n"
            "            result = (values - np.array([belief.mean[0, 2], belief.mean[1, 2], 0.0])) @ _rotation3(\n"
            "                belief.mean\n"
            "            )\n",
        ),
        "test_canonicalize_actually_changes_coordinates",
    ),
    (
        "M5-timescale-delta-from-frame-index",
        "ainerzero/v9/fakes/timescale.py",
        (
            "        delta_s = dt_ticks / SIM_HZ  # 式 3: the real elapsed time of this step\n",
            "        delta_s = t_ticks / SIM_HZ  # MUTATED: frame index used as time\n",
        ),
        "test_align_reports_real_dt_not_the_stride",
    ),
    (
        "M6-spatial-memory-partition-seal-removed",
        "ainerzero/v9/fakes/spatial_memory.py",
        (
            "        self.require_writable(fragment.partition)\n",
            "        # MUTATED: final partition no longer sealed\n",
        ),
        "test_write_refuses_non_allowlisted_partitions",
    ),
    (
        "M7-spatial-memory-version-fence-removed",
        "ainerzero/v9/fakes/spatial_memory.py",
        (
            "            if float(np.linalg.norm(metric - center)) > float(radius):\n"
            "                continue\n"
            "            if fragment.encoder_version == encoder_version:\n"
            "                hits.append(fragment)\n"
            "            else:\n"
            "                excluded.append(fragment)\n",
            "            if float(np.linalg.norm(metric - center)) > float(radius):\n"
            "                continue\n"
            "            hits.append(fragment)  # MUTATED: foreign latent space read anyway\n",
        ),
        "test_query_excludes_foreign_encoder_version",
    ),
    (
        "M8-perception-reference-cut-removed",
        "ainerzero/v9/fakes/perception.py",
        (
            "            resolve_reference(reference, as_of_t_ticks=validated.t_ticks)\n",
            "            reference  # MUTATED: no namespace / tick cut on references\n",
        ),
        "test_encode_resolves_only_registered_namespaces",
    ),
    (
        "M9-planner-leaks_truth_key_into_subgoal",
        "ainerzero/v9/fakes/planner.py",
        (
            "                assert_no_forbidden_keys(target, origin=\"subgoal\")\n",
            "                assert_no_forbidden_keys(target, origin=\"subgoal\")\n"
            "                target = dict(target, position=[0.0, 0.0])  # MUTATED: truth leak\n",
        ),
        "test_emitted_subgoals_have_no_truth_keys",
    ),
    (
        "M10-scheduler-world_signal_scan-removed",
        "ainerzero/v9/fakes/scheduler.py",
        (
            "            if key in detail:\n",
            "            if False:  # MUTATED: world-side signal keys accepted\n",
        ),
        "test_world_side_signal_payloads_are_refused",
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
                entry["caught"] = None
            else:
                caught = outcome["returncode"] != 0 and any(
                    expected in failed for failed in outcome["failed"]
                )
                entry["caught"] = caught
                ok = caught
                if not caught:
                    entry["debug"] = {
                        "expected": expected,
                        "failed": outcome["failed"],
                    }
            entry["ok"] = ok
            overall_ok = overall_ok and ok
            results.append(entry)
            status = "GREEN" if outcome["returncode"] == 0 else "RED"
            note = "control" if relative is None else ("caught" if entry["caught"] else "NOT CAUGHT")
            print(f"[{status}] {name}: {note} ({outcome['seconds']}s)", flush=True)

    payload = {
        "card": "ainerzero.V9.B2",
        "control": "control-unmutated-copy",
        "pytest_target": TEST_DIR,
        "shadow_strategy": "whole src/ package copy prepended to PYTHONPATH",
        "mutations_registered": len(MUTATIONS),
        "mutations_caught": sum(1 for r in results if r.get("caught")),
        "control_green": bool(results and results[0]["ok"]),
        "all_ok": overall_ok,
        "results": results,
    }
    RESULT_FILE.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    print(
        f"control={'green' if payload['control_green'] else 'RED'}, "
        f"caught={payload['mutations_caught']}/{len(MUTATIONS)}, results={RESULT_FILE}"
    )
    return 0 if overall_ok else 1


if __name__ == "__main__":
    sys.exit(main())
