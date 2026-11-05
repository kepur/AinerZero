#!/usr/bin/env python3
"""V9.P14 mutation matrix: P13's 15 carried-over mutations + 3 reviewer-written ones.

M1..M15 are copied verbatim from reports/V9-P9/r4/harness/mutation.py (anchors
re-verified against the current source; a stale anchor is reported as
NOT_APPLIED, never as caught).  V1..V3 are written for this review and target the
three defects this card names explicitly:

  V1  `worker._train` keeps one phase-wide `started` instead of one per run
      ("started moved back outside the loop");
  V2  the supervisor's hard timeout is computed for the whole phase (9 x 500 s)
      instead of per run;
  V3  the duplicate arm x seed guard is removed, so a second call is not refused.

Every mutation runs against a throw-away copy of src/ and tests/ under the
system temp dir; the real tree is only read once, to seed that copy.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REAL = Path("/Users/mac/AinerWorkFlow/AinerZero")
OUT = REAL / "reports" / "V9-P14" / "evidence"
PY = str(REAL / ".venv/bin/python")

CARRY_OVER = [
    ("M1", "worker.py", "pacer 占空比睡眠整段删除",
     "        rest = previous * (1.0 / duty - 1.0)\n        if rest:\n            time.sleep(min(rest, 2.0))",
     "        pass  # pacer removed by the reviewer"),
    ("M2", "resource_gate.py", "evaluate() 的 duty 检查禁用",
     "    if not 0.0 < duty <= registered:",
     "    if False:  # duty check disabled"),
    ("M3", "resource_gate.py", "交换区增长线删除",
     "    growth = snapshot.swap_used_bytes - snapshot.swap_baseline_bytes\n    if growth > float(limits[\"swap_growth_gib\"]) * GIB:",
     "    growth = 0.0\n    if False:"),
    ("M4", "resource_gate.py", "系统余量线删除",
     "    if snapshot.system_available_bytes < float(limits[\"system_reserve_gib\"]) * GIB:",
     "    if False:"),
    ("M5", "resource_gate.py", "进程内存线删除",
     "    if snapshot.process_rss_bytes > float(limits[\"process_memory_gib\"]) * GIB:",
     "    if False:"),
    ("M6", "resource_gate.py", "MLX 峰值线删除",
     "    if snapshot.mlx_peak_bytes > mlx_cap:",
     "    if False:"),
    ("M7", "metrics.py", "定位误差恒为 0",
     "    translation = np.hypot(estimate[:, 0] - truth[:, 0], estimate[:, 2] - truth[:, 2])",
     "    translation = np.zeros(len(estimate))"),
    ("M8", "prereg.py", "arm3 更新预算被单独 +1",
     "        frozen[\"arms\"][arm_id][\"training_updates\"] = budget[\"updates\"]",
     "        frozen[\"arms\"][arm_id][\"training_updates\"] = budget[\"updates\"] + (1 if arm_id == \"arm3\" else 0)"),
    ("M9", "data.py", "final 分区不再抛 FinalPartitionSealed",
     "    if partition == \"final\":\n        raise FinalPartitionSealed(",
     "    if False:\n        raise FinalPartitionSealed("),
    ("M10", "commands.py", "CLI 的 train 批准检查禁用（监督侧）",
     "    approval = _require_approval(document, verified[\"sha256\"], log_path)",
     "    approval = {\"approved\": True, \"line\": \"mutated\", \"document_sha256\": verified[\"sha256\"]}"),
    ("M11", "worker.py", "worker 的 train 批准检查禁用（纵深防御侧）",
     "            approval = _require_approval(document, verified[\"sha256\"], research_log)",
     "            approval = {\"approved\": True}"),
    ("M12", "smoke.py", "无更新断言恒为真（伪造 parameters_unchanged）",
     "    result[\"parameters_unchanged\"] = bool(all_unchanged)",
     "    result[\"parameters_unchanged\"] = True  # mutated: always claims no update"),
    ("M13", "commands.py", "train 的规范日志检查禁用（P-1）",
     "    if refusal is not None:\n        refusal[\"preregistration_path\"]",
     "    if False:\n        refusal[\"preregistration_path\"]"),
    ("M14", "commands.py", "train 的源绑定检查禁用（P-2）",
     "    binding = _source_binding_state(document)\n    if binding[\"status\"] != \"passed\":",
     "    binding = {\"status\": \"passed\", \"drifted\": []}\n    if False:"),
    ("M15", "commands.py", "train 的数据集摘要检查禁用（P-3）",
     "    dataset = data.dataset_binding_state(\n        output_root, (document.get(\"data_identity\") or {}).get(\"dataset_digest\")\n    )\n    if dataset[\"status\"] != \"passed\":",
     "    dataset = {\"status\": \"passed\"}\n    if False:"),
]

REVIEWER = [
    ("V1", "worker.py", "started 移回循环外（阶段共享，跨 run 累积）",
     "    started = time.perf_counter()\n    arm_started = time.perf_counter()",
     "    started = globals().setdefault('_p14_phase_started', time.perf_counter())\n    arm_started = time.perf_counter()"),
    ("V2", "commands.py", "监督时限按整个阶段算（9 x 500 s）",
     "    supervision = float(document[\"timing\"][\"supervision_seconds\"])",
     "    supervision = float(document[\"timing\"][\"supervision_seconds\"]) * 9.0"),
    ("V3", "commands.py", "重复调用没有被拒（already_completed 守卫移除）",
     "                    if cfg.get(\"arm_id\") == arm and int(cfg.get(\"seed\", -1)) == int(seed):",
     "                    if False:  # mutated: duplicate guard removed"),
]


def fresh_copy(root: Path) -> None:
    if root.exists():
        shutil.rmtree(root)
    (root / "artifacts" / "locks").mkdir(parents=True)
    subprocess.run(["rsync", "-a", f"{REAL}/src/", f"{root}/src/"], check=True)
    subprocess.run(["rsync", "-a", f"{REAL}/tests/", f"{root}/tests/"], check=True)
    subprocess.run(["rsync", "-a", f"{REAL}/RESEARCH_LOG.md", f"{root}/RESEARCH_LOG.md"], check=True)
    # `test_full_sequence_9_trains_and_4_evals` reaches arm1's frozen D candidate
    # through spec.REPO_ROOT, so the copy needs those read-only baseline artefacts
    # to reach the same 129/129 baseline as the real tree.
    for rel in ("reports/V9-baseline", "artifacts/pilot"):
        if (REAL / rel).exists():
            (root / rel).mkdir(parents=True, exist_ok=True)
            subprocess.run(["rsync", "-a", f"{REAL}/{rel}/", f"{root}/{rel}/"], check=True)
    subprocess.run(
        ["find", str(root), "-name", "__pycache__", "-type", "d", "-exec", "rm", "-rf", "{}", "+"],
        check=False,
    )


def run_one(base: Path, work: Path, mutation) -> dict:
    cid, filename, label, old, new = mutation
    if work.exists():
        shutil.rmtree(work)
    (work / "artifacts" / "locks").mkdir(parents=True)
    subprocess.run(["rsync", "-a", f"{base}/src/", f"{work}/src/"], check=True)
    subprocess.run(["rsync", "-a", f"{base}/tests/", f"{work}/tests/"], check=True)
    subprocess.run(
        ["find", str(work / "src"), "-name", "__pycache__", "-type", "d", "-exec", "rm", "-rf", "{}", "+"],
        check=False,
    )
    target = work / "src/ainerzero/v9/experiments/s1" / filename
    text = target.read_text(encoding="utf-8")
    if old not in text:
        return {"id": cid, "label": label, "file": filename, "applied": False, "verdict": "NOT_APPLIED"}
    target.write_text(text.replace(old, new, 1), encoding="utf-8")
    proc = subprocess.run(
        [PY, "-m", "pytest", "tests/v9/experiments", "-q", "-p", "no:cacheprovider"],
        cwd=str(work),
        capture_output=True,
        text=True,
        timeout=1800,
        env={
            "PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
            "PYTHONPATH": str(work / "src"),
            "PYTHONDONTWRITEBYTECODE": "1",
            "HOME": str(work),
        },
    )
    lines = proc.stdout.strip().splitlines()
    tail = [ln for ln in lines if " passed" in ln or " failed" in ln or "error" in ln]
    summary = tail[-1] if tail else (proc.stdout[-300:] or proc.stderr[-300:])
    failed_tests = [ln.split(" ")[1] for ln in lines if ln.startswith("FAILED ")]
    red = "failed" in summary or "error" in summary or proc.returncode != 0
    return {
        "id": cid,
        "label": label,
        "file": filename,
        "applied": True,
        "returncode": proc.returncode,
        "summary": summary,
        "failed_test_count": len(failed_tests),
        "failed_tests_sample": failed_tests[:6],
        "verdict": "CAUGHT" if red else "MISSED",
    }


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="p14-mut-", dir=tempfile.gettempdir()))
    base, work = tmp / "sandbox", tmp / "mut"
    fresh_copy(base)
    baseline = subprocess.run(
        [PY, "-m", "pytest", "tests/v9/experiments", "-q", "-p", "no:cacheprovider"],
        cwd=str(base),
        capture_output=True,
        text=True,
        env={
            "PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
            "PYTHONPATH": str(base / "src"),
            "PYTHONDONTWRITEBYTECODE": "1",
            "HOME": str(base),
        },
    )
    baseline_summary = [ln for ln in baseline.stdout.splitlines() if " passed" in ln]
    results = [run_one(base, work, m) for m in CARRY_OVER + REVIEWER]
    caught = sum(1 for r in results if r["verdict"] == "CAUGHT")
    missed = [r["id"] for r in results if r["verdict"] == "MISSED"]
    not_applied = [r["id"] for r in results if r["verdict"] == "NOT_APPLIED"]
    payload = {
        "schema": "ainerzero.v9.p14.mutations.v1",
        "baseline": {
            "command": "pytest tests/v9/experiments -q",
            "summary": baseline_summary[-1] if baseline_summary else "",
            "returncode": baseline.returncode,
        },
        "carry_over_source": "reports/V9-P9/r4/harness/mutation.py (M1-M15)",
        "reviewer_written": ["V1", "V2", "V3"],
        "total": len(results),
        "caught": caught,
        "missed": missed,
        "not_applied": not_applied,
        "results": results,
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "mutations-p14.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
    )
    for row in results:
        print(f'{row["verdict"]:11s} {row["id"]:3s} {row["label"]} -> {row.get("summary", "")}'
              + (f' [{row["failed_tests_sample"][0]}]' if row.get("failed_tests_sample") else ""))
    print(f'\nbaseline: {payload["baseline"]["summary"]}')
    print(f"caught {caught}/{len(results)}; missed={missed}; not_applied={not_applied}")
    return 0 if caught == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
