"""V9.P12 independent re-run of the S1 mutation matrix (M1-M15).

Written by the P12 reviewer (not a P9 author).  The mutation set, anchors and
expectations are the ones registered by V9.P10 and carried through P9 r2/r3;
this script re-applies each anchor against the *current* frozen source inside a
/private/tmp copy and runs the s1 test suite for every mutation.

A mutation that stays green is an uncovered guarantee, not a pass.

Differences versus the r3 harness (reviewer's own runner):
* own sandbox (/private/tmp/v9p12), own results directory (reports/V9-P12/);
* every anchor is checked against the current file before applying; a missing
  anchor is reported as ANCHOR_MISSING (a finding, never silently skipped);
* per-mutation failed test names are captured from the pytest report, not just
  the summary line;
* the mutation source tree is re-snapshotted from the live repo for every
  mutation (no cross-mutation contamination).
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

REAL = Path("/Users/mac/AinerWorkFlow/AinerZero")
SB = Path("/private/tmp/v9p12/sandbox")
MUT = Path("/private/tmp/v9p12/mut")
PY = str(REAL / ".venv-ainerzero" / "bin" / "python")
OUT = REAL / "reports" / "V9-P12" / "harness"

S1 = "src/ainerzero/v9/experiments/s1"

MUTATIONS = [
    ("M1", "worker.py", "pacer duty-cycle sleep deleted",
     "                rest = previous * (1.0 / duty - 1.0)\n                if rest:\n                    time.sleep(min(rest, 2.0))",
     "                pass  # pacer removed by the reviewer",
     "RED_EXPECTED"),
    ("M2", "resource_gate.py", "evaluate() duty check disabled",
     "    if not 0.0 < duty <= registered:",
     "    if False:  # duty check disabled",
     "RED_EXPECTED"),
    ("M3", "resource_gate.py", "swap growth line deleted",
     '    growth = snapshot.swap_used_bytes - snapshot.swap_baseline_bytes\n    if growth > float(limits["swap_growth_gib"]) * GIB:',
     "    growth = 0.0\n    if False:",
     "RED_EXPECTED"),
    ("M4", "resource_gate.py", "system reserve line deleted",
     '    if snapshot.system_available_bytes < float(limits["system_reserve_gib"]) * GIB:',
     "    if False:",
     "RED_EXPECTED"),
    ("M5", "resource_gate.py", "process memory line deleted",
     '    if snapshot.process_rss_bytes > float(limits["process_memory_gib"]) * GIB:',
     "    if False:",
     "RED_EXPECTED"),
    ("M6", "resource_gate.py", "MLX peak line deleted",
     "    if snapshot.mlx_peak_bytes > mlx_cap:",
     "    if False:",
     "RED_EXPECTED"),
    ("M7", "metrics.py", "localization error forced to zero",
     "    translation = np.hypot(estimate[:, 0] - truth[:, 0], estimate[:, 2] - truth[:, 2])",
     "    translation = np.zeros(len(estimate))",
     "RED_EXPECTED"),
    ("M8", "prereg.py", "arm3 update budget silently +1",
     '        frozen["arms"][arm_id]["training_updates"] = budget["updates"]',
     '        frozen["arms"][arm_id]["training_updates"] = budget["updates"] + (1 if arm_id == "arm3" else 0)',
     "RED_EXPECTED"),
    ("M9", "data.py", "final partition no longer sealed",
     '    if partition == "final":\n        raise FinalPartitionSealed(',
     '    if False:\n        raise FinalPartitionSealed(',
     "RED_EXPECTED"),
    ("M10", "commands.py", "supervisor-side train approval check disabled",
     '    approval = _require_approval(document, verified["sha256"], log_path)',
     '    approval = {"approved": True, "line": "mutated", "document_sha256": verified["sha256"]}',
     "RED_EXPECTED"),
    ("M11", "worker.py", "worker-side train approval check disabled",
     '            approval = _require_approval(document, verified["sha256"], research_log)',
     '            approval = {"approved": True}',
     "RED_EXPECTED"),
    ("M12", "smoke.py", "no-update assertion forged true",
     '    result["parameters_unchanged"] = bool(all_unchanged)',
     '    result["parameters_unchanged"] = True  # mutated: always claims no update',
     "RED_EXPECTED"),
    ("M13", "commands.py", "canonical research-log gate disabled (P-1)",
     '    if refusal is not None:\n        refusal["preregistration_path"]',
     '    if False:\n        refusal["preregistration_path"]',
     "RED_EXPECTED"),
    ("M14", "commands.py", "source-binding gate disabled (P-2)",
     '    binding = _source_binding_state(document)\n    if binding["status"] != "passed":',
     '    binding = {"status": "passed", "drifted": []}\n    if False:',
     "RED_EXPECTED"),
    ("M15", "commands.py", "dataset-digest gate disabled (P-3)",
     '    dataset = data.dataset_binding_state(\n        output_root, (document.get("data_identity") or {}).get("dataset_digest")\n    )\n    if dataset["status"] != "passed":',
     '    dataset = {"status": "passed"}\n    if False:',
     "RED_EXPECTED"),
]


def snapshot_fresh_mut() -> None:
    if MUT.exists():
        shutil.rmtree(MUT)
    (MUT / "artifacts" / "locks").mkdir(parents=True)
    subprocess.run(["rsync", "-a", f"{SB}/src/", f"{MUT}/src/"], check=True)
    subprocess.run(["rsync", "-a", f"{SB}/tests/", f"{MUT}/tests/"], check=True)
    subprocess.run(
        ["find", str(MUT / "src"), "-name", "__pycache__", "-type", "d", "-exec", "rm", "-rf", "{}", "+"],
        check=False,
    )


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    results = []
    for cid, filename, label, old, new, expectation in MUTATIONS:
        snapshot_fresh_mut()
        target = MUT / S1 / filename
        text = target.read_text(encoding="utf-8")
        if old not in text:
            results.append({
                "id": cid, "file": filename, "label": label, "applied": False,
                "expectation": expectation, "verdict": "ANCHOR_MISSING",
                "note": "anchor text not found in the current source; mutation cannot be applied",
            })
            print(f"ANCHOR_MISSING {cid} {filename}", flush=True)
            continue
        target.write_text(text.replace(old, new, 1), encoding="utf-8")
        proc = subprocess.run(
            [PY, "-m", "pytest", "tests/v9/experiments", "-q", "-p", "no:cacheprovider",
             "--tb=no", "-rf"],
            cwd=str(MUT), capture_output=True, text=True, timeout=900,
            env={"PATH": "/usr/bin:/bin:/usr/sbin:/sbin", "PYTHONPATH": str(MUT / "src"),
                 "PYTHONDONTWRITEBYTECODE": "1", "HOME": "/private/tmp/v9p12"},
        )
        out = proc.stdout
        summary = ""
        for line in reversed(out.strip().splitlines()):
            if (" passed" in line or " failed" in line or " error" in line) and ("=" in line or "passed" in line):
                summary = line.strip()
                break
        if not summary:
            summary = out.strip().splitlines()[-1] if out.strip() else "(no output)"
        failed_names = sorted(set(re.findall(r"^FAILED\s+(\S+)", out, flags=re.M)))
        error_names = sorted(set(re.findall(r"^ERROR\s+(\S+)", out, flags=re.M)))
        failed = proc.returncode != 0
        results.append({
            "id": cid, "file": filename, "label": label, "applied": True,
            "expectation": expectation,
            "returncode": proc.returncode, "summary": summary,
            "failed_tests": failed_names, "error_tests": error_names,
            "failed_count": len(failed_names) + len(error_names),
            "verdict": "CAUGHT" if failed else "MISSED",
        })
        print(f"{'CAUGHT' if failed else 'MISSED'} {cid} {label} -> {summary}", flush=True)

    (OUT / "mutations-p12.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")
    caught = sum(1 for r in results if r["verdict"] == "CAUGHT")
    applied = sum(1 for r in results if r["applied"])
    print(f"\ncaught {caught}/{applied} applied ({len(results)} total)")
    return 0 if caught == applied == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
