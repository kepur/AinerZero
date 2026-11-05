"""P10 mutation matrix re-run for the r3 fixes (P-1..P-4).

Copied from ``reports/V-V9-P9/harness/mutation.py`` (the V9.P10 reviewer's
harness).  Changes versus the original, all listed in the r2 report:

* output paths (SB / MUT / OUT / results) point at the r3 sandbox and the
  ``reports/V9-P9/r3/`` result directory;
* M1-M12 are unchanged in anchor, semantics and expectation (the r3 edits kept
  both approval-gate call sites byte-identical);
* M13/M14/M15 are new: they disable the three gates r3 added (canonical log,
  source binding, dataset digest) and must be caught by the r3 tests;
* M10/M11 keep the anchor the r2 harness moved them to (the approval-gate call
  itself); the r3 edits left both call sites byte-identical;
* M1-M9 and M12 are byte-identical to the P10 harness.

A mutation that stays green is an uncovered guarantee, not a pass.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

REAL = Path("/Users/mac/AinerWorkFlow/AinerZero")
SB = Path("/private/tmp/v9p9r3/sandbox")
MUT = Path("/private/tmp/v9p9r3/mut")
PY = str(REAL / ".venv-ainerzero" / "bin" / "python")
OUT = REAL / "reports" / "V9-P9" / "r3" / "harness"
OUT.mkdir(parents=True, exist_ok=True)

MUTATIONS = [
    ("M1", "worker.py", "pacer 占空比睡眠整段删除",
     "                rest = previous * (1.0 / duty - 1.0)\n                if rest:\n                    time.sleep(min(rest, 2.0))",
     "                pass  # pacer removed by the reviewer",
     "RED_EXPECTED"),
    ("M2", "resource_gate.py", "evaluate() 的 duty 检查禁用",
     "    if not 0.0 < duty <= registered:",
     "    if False:  # duty check disabled",
     "RED_EXPECTED"),
    ("M3", "resource_gate.py", "交换区增长线删除",
     "    growth = snapshot.swap_used_bytes - snapshot.swap_baseline_bytes\n    if growth > float(limits[\"swap_growth_gib\"]) * GIB:",
     "    growth = 0.0\n    if False:",
     "RED_EXPECTED"),
    ("M4", "resource_gate.py", "系统余量线删除",
     "    if snapshot.system_available_bytes < float(limits[\"system_reserve_gib\"]) * GIB:",
     "    if False:",
     "RED_EXPECTED"),
    ("M5", "resource_gate.py", "进程内存线删除",
     "    if snapshot.process_rss_bytes > float(limits[\"process_memory_gib\"]) * GIB:",
     "    if False:",
     "RED_EXPECTED"),
    ("M6", "resource_gate.py", "MLX 峰值线删除",
     "    if snapshot.mlx_peak_bytes > mlx_cap:",
     "    if False:",
     "RED_EXPECTED"),
    ("M7", "metrics.py", "定位误差恒为 0",
     "    translation = np.hypot(estimate[:, 0] - truth[:, 0], estimate[:, 2] - truth[:, 2])",
     "    translation = np.zeros(len(estimate))",
     "RED_EXPECTED"),
    ("M8", "prereg.py", "arm3 更新预算被单独 +1",
     "        frozen[\"arms\"][arm_id][\"training_updates\"] = budget[\"updates\"]",
     "        frozen[\"arms\"][arm_id][\"training_updates\"] = budget[\"updates\"] + (1 if arm_id == \"arm3\" else 0)",
     "RED_EXPECTED"),
    ("M9", "data.py", "final 分区不再抛 FinalPartitionSealed",
     "    if partition == \"final\":\n        raise FinalPartitionSealed(",
     "    if False:\n        raise FinalPartitionSealed(",
     "RED_EXPECTED"),
    # r2: F1 replaced the status gate with the RESEARCH_LOG approval gate, so the
    # anchor moved from the status comparison to the gate call itself.
    ("M10", "commands.py", "CLI 的 train 批准检查禁用（监督侧）",
     "    approval = _require_approval(document, verified[\"sha256\"], log_path)",
     "    approval = {\"approved\": True, \"line\": \"mutated\", \"document_sha256\": verified[\"sha256\"]}",
     "RED_EXPECTED"),
    # r2: same move for the worker-side gate.
    ("M11", "worker.py", "worker 的 train 批准检查禁用（纵深防御侧）",
     "            approval = _require_approval(document, verified[\"sha256\"], research_log)",
     "            approval = {\"approved\": True}",
     "RED_EXPECTED"),
    ("M12", "smoke.py", "无更新断言恒为真（伪造 parameters_unchanged）",
     "    result[\"parameters_unchanged\"] = bool(all_unchanged)",
     "    result[\"parameters_unchanged\"] = True  # mutated: always claims no update",
     "RED_EXPECTED"),
    # r3: the three gates added for P-1/P-2/P-3.
    ("M13", "commands.py", "train 的规范日志检查禁用（P-1）",
     "    if refusal is not None:\n        refusal[\"preregistration_path\"]",
     "    if False:\n        refusal[\"preregistration_path\"]",
     "RED_EXPECTED"),
    ("M14", "commands.py", "train 的源绑定检查禁用（P-2）",
     "    binding = _source_binding_state(document)\n    if binding[\"status\"] != \"passed\":",
     "    binding = {\"status\": \"passed\", \"drifted\": []}\n    if False:",
     "RED_EXPECTED"),
    ("M15", "commands.py", "train 的数据集摘要检查禁用（P-3）",
     "    dataset = data.dataset_binding_state(\n        output_root, (document.get(\"data_identity\") or {}).get(\"dataset_digest\")\n    )\n    if dataset[\"status\"] != \"passed\":",
     "    dataset = {\"status\": \"passed\"}\n    if False:",
     "RED_EXPECTED"),
]


def _fresh_sandbox() -> None:
    """Snapshot the live src/ and tests/ once; every mutation copies from here."""
    if SB.exists():
        shutil.rmtree(SB)
    (SB / "artifacts" / "locks").mkdir(parents=True)
    subprocess.run(["rsync", "-a", f"{REAL}/src/", f"{SB}/src/"], check=True)
    subprocess.run(["rsync", "-a", f"{REAL}/tests/", f"{SB}/tests/"], check=True)
    subprocess.run(["rsync", "-a", f"{REAL}/RESEARCH_LOG.md", f"{SB}/RESEARCH_LOG.md"], check=True)
    subprocess.run(
        ["find", str(SB), "-name", "__pycache__", "-type", "d", "-exec", "rm", "-rf", "{}", "+"],
        check=False,
    )


def main() -> int:
    _fresh_sandbox()
    results = []
    for cid, filename, label, old, new, expectation in MUTATIONS:
        if MUT.exists():
            shutil.rmtree(MUT)
        (MUT / "artifacts" / "locks").mkdir(parents=True)
        subprocess.run(["rsync", "-a", f"{SB}/src/", f"{MUT}/src/"], check=True)
        subprocess.run(["rsync", "-a", f"{SB}/tests/", f"{MUT}/tests/"], check=True)
        subprocess.run(
            ["find", str(MUT / "src"), "-name", "__pycache__", "-type", "d", "-exec", "rm", "-rf", "{}", "+"],
            check=False,
        )
        target = MUT / "src" / "ainerzero" / "v9" / "experiments" / "s1" / filename
        text = target.read_text()
        if old not in text:
            results.append({"id": cid, "label": label, "applied": False, "passed": None,
                            "failed": None, "expectation": expectation, "verdict": "NOT_APPLIED"})
            print(f"SKIP {cid} pattern not found in {filename}", flush=True)
            continue
        target.write_text(text.replace(old, new, 1))
        proc = subprocess.run(
            [PY, "-m", "pytest", "tests/v9/experiments", "-q", "-p", "no:cacheprovider"],
            cwd=str(MUT), capture_output=True, text=True, timeout=900,
            env={"PATH": "/usr/bin:/bin:/usr/sbin:/sbin", "PYTHONPATH": str(MUT / "src"),
                 "PYTHONDONTWRITEBYTECODE": "1", "HOME": "/tmp"},
        )
        tail = [ln for ln in proc.stdout.strip().splitlines() if " passed" in ln or " failed" in ln or "error" in ln]
        summary = tail[-1] if tail else proc.stdout[-200:]
        failed = "failed" in summary or "error" in summary or proc.returncode != 0
        verdict = "CAUGHT" if failed else "MISSED"
        results.append({"id": cid, "label": label, "applied": True, "passed": not failed,
                        "failed": failed, "expectation": expectation, "summary": summary,
                        "verdict": verdict})
        print(f"{verdict} {cid} {label} -> {summary}", flush=True)

    (OUT / "mutations.json").write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")
    caught = sum(1 for r in results if r["verdict"] == "CAUGHT")
    print(f"\ncaught {caught}/{len(results)}")
    return 0 if caught == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
