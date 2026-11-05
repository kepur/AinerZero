"""P10 mutation matrix: break one behaviour at a time on a copy and see if the
author's 67-test suite notices.  A mutation that stays green is an uncovered
guarantee, not a pass.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

SB = Path("/private/tmp/v9p11/sandbox")
REAL = Path("/Users/mac/AinerWorkFlow/AinerZero")
MUT = Path("/private/tmp/v9p11/mut")
PY = "/Users/mac/AinerWorkFlow/AinerZero/.venv-ainerzero/bin/python"
OUT = Path("/Users/mac/AinerWorkFlow/AinerZero/reports/V-V9-P9/r2/results")
OUT.mkdir(parents=True, exist_ok=True)

MUTATIONS = [
    ("M1", "worker.py", "pacer 占空比睡眠整段删除",
     "                rest = previous * (1.0 / duty - 1.0)\n                if rest:\n                    time.sleep(min(rest, 2.0))",
     "                pass  # pacer removed by the reviewer",
     "GREEN_EXPECTED_IF_UNCOVERED"),
    ("M2", "resource_gate.py", "evaluate() 的 duty 检查禁用",
     "    if not 0.0 < duty <= registered:",
     "    if False:  # duty check disabled",
     "GREEN_EXPECTED_IF_UNCOVERED"),
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
    ("M10", "commands.py", "CLI 的 train 批准检查禁用（监督侧）",
     "    if document.get(\"status\") != prereg.STATUS_APPROVED:",
     "    if False:",
     "RED_EXPECTED"),
    ("M11", "worker.py", "worker 的 train 批准检查禁用（纵深防御侧）",
     "            if document.get(\"status\") != prereg.STATUS_APPROVED:",
     "            if False:",
     "GREEN_EXPECTED_IF_UNCOVERED"),
    ("M12", "smoke.py", "无更新断言恒为真（伪造 parameters_unchanged）",
     "    result[\"parameters_unchanged\"] = bool(all_unchanged)",
     "    result[\"parameters_unchanged\"] = True  # mutated: always claims no update",
     "GREEN_EXPECTED_IF_UNCOVERED"),
]

results = []
for cid, filename, label, old, new, expectation in MUTATIONS:
    if MUT.exists():
        shutil.rmtree(MUT)
    (MUT / "artifacts" / "locks").mkdir(parents=True)
    subprocess.run(["rsync", "-a", f"{SB}/src/", f"{MUT}/src/"], check=True)
    subprocess.run(["rsync", "-a", f"{REAL}/tests/", f"{MUT}/tests/"], check=True)
    subprocess.run(["find", str(MUT / "src"), "-name", "__pycache__", "-type", "d", "-exec", "rm", "-rf", "{}", "+"],
                   check=False)
    target = MUT / "src" / "ainerzero" / "v9" / "experiments" / "s1" / filename
    text = target.read_text()
    if old not in text:
        results.append({"id": cid, "label": label, "applied": False, "passed": None,
                        "failed": None, "expectation": expectation})
        print(f"SKIP {cid} pattern not found in {filename}", flush=True)
        continue
    target.write_text(text.replace(old, new, 1))
    proc = subprocess.run(
        [PY, "-m", "pytest", "tests/v9/experiments", "-q", "-p", "no:cacheprovider"],
        cwd=str(MUT), capture_output=True, text=True, timeout=600,
        env={"PATH": "/usr/bin:/bin:/usr/sbin:/sbin", "PYTHONPATH": str(MUT / "src"),
             "PYTHONDONTWRITEBYTECODE": "1", "HOME": "/tmp"},
    )
    tail = [ln for ln in proc.stdout.strip().splitlines() if " passed" in ln or " failed" in ln or "error" in ln]
    summary = tail[-1] if tail else proc.stdout[-200:]
    failed = "failed" in summary or "error" in summary or proc.returncode != 0
    caught = failed
    verdict = ("CAUGHT" if caught else "MISSED")
    results.append({"id": cid, "label": label, "applied": True, "passed": not failed,
                    "failed": failed, "expectation": expectation, "summary": summary,
                    "verdict": verdict})
    print(f"{verdict} {cid} {label} -> {summary}", flush=True)

(OUT / "mutations.json").write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")
caught = sum(1 for r in results if r.get("verdict") == "CAUGHT")
print(f"\ncaught {caught}/{len(results)}")
