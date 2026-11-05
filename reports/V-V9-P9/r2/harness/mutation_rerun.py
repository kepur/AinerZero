"""V9.P11 reviewer harness: 12-item mutation matrix re-run + attribution probes.

Pass A (``mutation_p10_copy.py``) is a byte-faithful copy of the V9.P10 harness
with only sandbox/output paths changed; it shows M10/M11 can no longer be
applied at all because the F1 fix deleted the ``status`` gate they anchored on.

Pass B (this file) re-runs the same 12 mutations, moving *only* the M10/M11
anchors onto the new approval-gate call, and additionally records which tests
go red (a mutation caught by an unrelated test would be a false catch).  It
also adds four reviewer probes against guarantees that r2 claims are covered:

  X1  any approval line approves (SHA binding dropped)
  X2  ``verify`` source binding always reports passed
  X3  ``verify`` independent parameter re-hash always reports passed
  X5  the RunStore run snapshot drops the approval line it recorded

Every mutation is applied to a throwaway copy; the real tree is only read.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

REAL = Path("/Users/mac/AinerWorkFlow/AinerZero")
SB = Path("/private/tmp/v9p11/sandbox")
MUT = Path("/private/tmp/v9p11/mut2")
PY = str(REAL / ".venv-ainerzero" / "bin" / "python")
OUT = REAL / "reports" / "V-V9-P9" / "r2" / "results"

S1 = "src/ainerzero/v9/experiments/s1/"

MUTATIONS = [
    ("M1", S1 + "worker.py", "pacer 占空比睡眠整段删除", "RED",
     "                rest = previous * (1.0 / duty - 1.0)\n                if rest:\n                    time.sleep(min(rest, 2.0))",
     "                pass  # pacer removed by the reviewer"),
    ("M2", S1 + "resource_gate.py", "evaluate() 的 duty 检查禁用", "RED",
     "    if not 0.0 < duty <= registered:", "    if False:  # duty check disabled"),
    ("M3", S1 + "resource_gate.py", "交换区增长线删除", "RED",
     '    growth = snapshot.swap_used_bytes - snapshot.swap_baseline_bytes\n    if growth > float(limits["swap_growth_gib"]) * GIB:',
     "    growth = 0.0\n    if False:"),
    ("M4", S1 + "resource_gate.py", "系统余量线删除", "RED",
     '    if snapshot.system_available_bytes < float(limits["system_reserve_gib"]) * GIB:',
     "    if False:"),
    ("M5", S1 + "resource_gate.py", "进程内存线删除", "RED",
     '    if snapshot.process_rss_bytes > float(limits["process_memory_gib"]) * GIB:',
     "    if False:"),
    ("M6", S1 + "resource_gate.py", "MLX 峰值线删除", "RED",
     "    if snapshot.mlx_peak_bytes > mlx_cap:", "    if False:"),
    ("M7", S1 + "metrics.py", "定位误差恒为 0", "RED",
     "    translation = np.hypot(estimate[:, 0] - truth[:, 0], estimate[:, 2] - truth[:, 2])",
     "    translation = np.zeros(len(estimate))"),
    ("M8", S1 + "prereg.py", "arm3 更新预算被单独 +1", "RED",
     '        frozen["arms"][arm_id]["training_updates"] = budget["updates"]',
     '        frozen["arms"][arm_id]["training_updates"] = budget["updates"] + (1 if arm_id == "arm3" else 0)'),
    ("M9", S1 + "data.py", "final 分区不再抛 FinalPartitionSealed", "RED",
     '    if partition == "final":\n        raise FinalPartitionSealed(',
     "    if False:\n        raise FinalPartitionSealed("),
    # P10 anchor was `document.get("status") != prereg.STATUS_APPROVED`; F1 deleted
    # that gate, so the same mutation ("disable the supervisor approval gate") is
    # applied at the new gate call.  Semantics, id and expectation unchanged.
    ("M10", S1 + "commands.py", "CLI 的 train 批准检查禁用（监督侧，anchor 移到新批准门）", "RED",
     '    approval = _require_approval(document, verified["sha256"], log_path)',
     '    approval = {"approved": True, "line": "mutated", "document_sha256": verified["sha256"]}'),
    ("M11", S1 + "worker.py", "worker 的 train 批准检查禁用（纵深防御侧，anchor 移到新批准门）", "RED",
     '            approval = _require_approval(document, verified["sha256"], research_log)',
     '            approval = {"approved": True}'),
    ("M12", S1 + "smoke.py", "无更新断言恒为真（伪造 parameters_unchanged）", "RED",
     '    result["parameters_unchanged"] = bool(all_unchanged)',
     '    result["parameters_unchanged"] = True  # mutated: always claims no update'),
    # --- reviewer probes (not part of the inherited 12) -------------------
    ("X1", S1 + "prereg.py", "批准行不再比对 document SHA（任何批准行都放行）", "RED",
     '    matching = [row for row in rows if row["document_sha256"] == document_sha256]',
     "    matching = list(rows)"),
    ("X2", S1 + "commands.py", "verify 源绑定恒报 passed", "RED",
     '        "status": "passed" if ok else "failed",\n        "rule": "re-hash the bound files',
     '        "status": "passed",\n        "rule": "re-hash the bound files'),
    ("X3", S1 + "commands.py", "verify 独立参数重算恒报 passed", "RED",
     '        "status": "passed" if ok else "failed",\n        "rule": "rebuild from the frozen spec',
     '        "status": "passed",\n        "rule": "rebuild from the frozen spec'),
    ("X5", S1 + "worker.py", "RunStore 快照不记批准行原文", "RED",
     '        "line": approval.get("line"),',
     '        "line": None,'),
]


def fresh_sandbox() -> None:
    if SB.exists():
        shutil.rmtree(SB)
    (SB / "artifacts" / "locks").mkdir(parents=True)
    subprocess.run(["rsync", "-a", f"{REAL}/src/", f"{SB}/src/"], check=True)
    subprocess.run(["rsync", "-a", f"{REAL}/tests/", f"{SB}/tests/"], check=True)
    subprocess.run(["rsync", "-a", f"{REAL}/RESEARCH_LOG.md", f"{SB}/RESEARCH_LOG.md"], check=True)
    subprocess.run(["find", str(SB), "-name", "__pycache__", "-type", "d", "-exec", "rm", "-rf", "{}", "+"], check=False)


def run_suite(cwd: Path) -> dict:
    proc = subprocess.run(
        [PY, "-m", "pytest", "tests/v9/experiments", "-q", "-rf", "-p", "no:cacheprovider"],
        cwd=str(cwd), capture_output=True, text=True, timeout=900,
        env={"PATH": "/usr/bin:/bin:/usr/sbin:/sbin", "PYTHONPATH": str(cwd / "src"),
             "PYTHONDONTWRITEBYTECODE": "1", "HOME": "/private/tmp/v9p11"},
    )
    failed = [line.split(" ", 1)[1].split(" - ")[0].strip()
              for line in proc.stdout.splitlines() if line.startswith("FAILED ")]
    tail = [ln for ln in proc.stdout.strip().splitlines() if " passed" in ln or " failed" in ln or "error" in ln]
    return {
        "summary": tail[-1] if tail else proc.stdout[-300:],
        "returncode": proc.returncode,
        "failed_tests": failed,
        "failed_count": len(failed),
    }


def main() -> int:
    fresh_sandbox()
    OUT.mkdir(parents=True, exist_ok=True)
    results = []

    # baseline: the untouched suite must be green before any mutation
    baseline_dir = Path("/private/tmp/v9p11/baseline")
    if baseline_dir.exists():
        shutil.rmtree(baseline_dir)
    (baseline_dir / "artifacts" / "locks").mkdir(parents=True)
    subprocess.run(["rsync", "-a", f"{SB}/src/", f"{baseline_dir}/src/"], check=True)
    subprocess.run(["rsync", "-a", f"{SB}/tests/", f"{baseline_dir}/tests/"], check=True)
    baseline = run_suite(baseline_dir)
    print(f"BASELINE {baseline['summary']}", flush=True)

    for cid, rel, label, expectation, old, new in MUTATIONS:
        if MUT.exists():
            shutil.rmtree(MUT)
        (MUT / "artifacts" / "locks").mkdir(parents=True)
        subprocess.run(["rsync", "-a", f"{SB}/src/", f"{MUT}/src/"], check=True)
        subprocess.run(["rsync", "-a", f"{SB}/tests/", f"{MUT}/tests/"], check=True)
        subprocess.run(["find", str(MUT / "src"), "-name", "__pycache__", "-type", "d",
                        "-exec", "rm", "-rf", "{}", "+"], check=False)
        target = MUT / rel
        text = target.read_text()
        if old not in text:
            results.append({"id": cid, "label": label, "expectation": expectation,
                            "applied": False, "verdict": "NOT_APPLIED", "summary": "anchor not found"})
            print(f"NOT_APPLIED {cid} {label}", flush=True)
            continue
        assert text.count(old) == 1, f"{cid}: anchor not unique"
        target.write_text(text.replace(old, new, 1))
        run = run_suite(MUT)
        verdict = "CAUGHT" if run["failed_count"] or run["returncode"] != 0 else "MISSED"
        results.append({
            "id": cid, "label": label, "expectation": expectation, "applied": True,
            "file": rel, "verdict": verdict, "summary": run["summary"],
            "failed_tests": run["failed_tests"], "failed_count": run["failed_count"],
        })
        print(f"{verdict} {cid} {label} -> {run['summary']}", flush=True)
        for test in run["failed_tests"][:4]:
            print(f"        {test}", flush=True)

    caught12 = [r for r in results if r["id"].startswith("M") and r["verdict"] == "CAUGHT"]
    payload = {
        "harness": "reports/V-V9-P9/r2/harness/mutation_rerun.py",
        "sandbox": str(SB),
        "baseline": baseline,
        "matrix": results,
        "inherited_12_caught": f"{len(caught12)}/12",
        "reviewer_probes_caught": sum(1 for r in results if r["id"].startswith("X") and r["verdict"] == "CAUGHT"),
    }
    (OUT / "mutations-v9p11.json").write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\ninherited 12: {len(caught12)}/12 caught; probes: {payload['reviewer_probes_caught']}/{len([r for r in results if r['id'].startswith('X')])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
