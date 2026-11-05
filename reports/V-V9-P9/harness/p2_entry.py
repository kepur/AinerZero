"""P10 adversarial suite, part 2: deadline/supervision, approval, lock, RunStore."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace

SB = Path("/private/tmp/vp9rev/sandbox")
PY = "/Users/mac/AinerWorkFlow/AinerZero/.venv-ainerzero/bin/python"
OUT = Path("/private/tmp/vp9rev/results")
OUT.mkdir(parents=True, exist_ok=True)
ENV = {**os.environ, "PYTHONPATH": str(SB / "src"), "PYTHONDONTWRITEBYTECODE": "1"}
REPORTS = SB / "reports" / "V9-P9"
sys.path.insert(0, str(SB / "src"))

from ainerzero.v9.experiments.s1 import commands, prereg, spec  # noqa: E402

rows: list[dict] = []


def add(cid, name, ok, exit_code, detail, evidence=None):
    rows.append({"id": cid, "name": name, "ok": bool(ok), "exit": exit_code,
                 "detail": detail, "evidence": evidence or {}})
    print(f"{'PASS' if ok else 'FAIL'} {cid} exit={exit_code} {detail}", flush=True)


def cli(args, env=None, timeout=300):
    proc = subprocess.run([PY, "-m", "ainerzero.cli", "s1-phase1", *args], cwd=str(SB),
                          env=env or ENV, capture_output=True, text=True, timeout=timeout)
    try:
        report = json.loads(proc.stdout)
    except Exception:
        report = {"raw": proc.stdout[-600:] + proc.stderr[-600:]}
    return {"exit": proc.returncode, "report": report}


# --- C7 the CLI cannot raise the prep wall budget -------------------------
r = cli(["--mode", "data", "--output-root", str(OUT / "c7"), "--wall-budget-seconds", "99999"])
add("C7", "CLI 不能放宽准备墙钟预算（99999 s）",
    r["exit"] == 1 and "tighten" in str(r["report"].get("error", "")),
    r["exit"], f"error={r['report'].get('error')}")

r = cli(["--mode", "data", "--output-root", str(OUT / "c7b"), "--wall-budget-seconds", "-5"])
add("C7b", "负预算被拒", r["exit"] == 1, r["exit"], f"error={r['report'].get('error')}")

# --- C8 environment variables cannot move the frozen numbers --------------
env_probe = dict(ENV)
env_probe.update({
    "S1_DEADLINE_SECONDS": "99999", "AINERZERO_DEADLINE_SECONDS": "99999",
    "S1_SUPERVISION_SECONDS": "99999", "AINERZERO_WALL_BUDGET_SECONDS": "99999",
    "PREREG_STATUS": "approved", "AINERZERO_PREREG_STATUS": "approved",
    "S1_UPDATES": "99999", "AINERZERO_APPROVED": "1", "RELAY_WALL_BUDGET": "99999",
})
r = cli(["--mode", "verify", "--output-root", str(REPORTS)], env=env_probe)
add("C8a", "环境变量不能改截止/监督/更新数（verify 仍读冻结文件）",
    r["exit"] == 0 and r["report"].get("preregistration_sha256")
    == "32c30f5005a438f759e14641f5ea77b635eb4020af7fa9ba823b7ad05bb74de6",
    r["exit"], f"sha={r['report'].get('preregistration_sha256')}")

grep_env = subprocess.run(
    ["grep", "-rnE", "os\\.environ|getenv", str(SB / "src/ainerzero/v9/experiments/s1")],
    capture_output=True, text=True)
hits = [ln.split("experiments/s1/")[-1] for ln in grep_env.stdout.splitlines() if ln.strip()]
# The single hit must be generation_environment(), which *writes* the producer env;
# no module reads an env var into a frozen number (deadline/supervision/updates/limits).
override_reads = [h for h in hits if "generation_environment" not in h and "env = dict(os.environ)" not in h]
add("C8b", "S1 包内没有把环境变量读成冻结参数（唯一命中是给生产者子进程写 env）",
    override_reads == [], 0, f"hits={hits}")

# --- C9 train is refused without approval --------------------------------
r = cli(["--mode", "train", "--output-root", str(REPORTS),
         "--prereg", str(REPORTS / "pre_registration.json")])
add("C9", "train 未获批准 → 拒绝（exit 3）",
    r["exit"] == 3 and r["report"].get("stage") == "preregistration_not_approved",
    r["exit"], f"stage={r['report'].get('stage')} status={r['report'].get('preregistration_status')}")

# --- C10 approval forgery + CLI cannot loosen the frozen budget ----------
forged = REPORTS / "pre_registration_forged.json"
doc_forged = json.loads((REPORTS / "pre_registration.json").read_text())
doc_forged["status"] = "approved"
forged.write_text(json.dumps(doc_forged, ensure_ascii=False, sort_keys=True, indent=1) + "\n",
                  encoding="utf-8")
forged_sha = prereg.document_sha256(doc_forged)
(REPORTS / "pre_registration_forged.json.sha256").write_text(
    f"{forged_sha}  {forged.name}\n", encoding="utf-8")
verified = prereg.verify_frozen_file(forged)

captured: dict = {}
original = commands._supervised_worker


def fake_supervised(mode, **kwargs):
    captured.update({"mode": mode, **kwargs})
    return {"status": "completed", "mode": mode, "fake": True}


commands._supervised_worker = fake_supervised
args = SimpleNamespace(output_root=REPORTS, limits_file=None, wall_budget_seconds=5,
                       prereg=forged, mode="train")
try:
    rep10 = commands.mode_train(args)
finally:
    commands._supervised_worker = original

add("C10a", "批准标志只能由文件状态伪造（改 status 重算 SHA 即通过），无独立批准凭据",
    verified["sha256"] == forged_sha and rep10.get("status") == "completed"
    and forged_sha != "32c30f5005a438f759e14641f5ea77b635eb4020af7fa9ba823b7ad05bb74de6",
    0, f"forged_sha={forged_sha[:16]}… captured_budget={captured.get('budget')}")
add("C10b", "CLI --wall-budget-seconds 5 不能放宽 train 的冻结截止/监督（仍为 450/500）",
    captured.get("budget") == 450.0 and captured.get("supervision_seconds") == 500.0,
    0, f"budget={captured.get('budget')} supervision={captured.get('supervision_seconds')}")

# --- C11 shared lock: two processes, only one runs -----------------------
lock_path = SB / "artifacts" / "locks" / "m0-worker.lock"
holder = subprocess.Popen(
    [PY, "-c",
     "import sys, time; sys.path.insert(0, %r)\n"
     "from ainerzero.cli import worker_lock\n"
     "from ainerzero.v9.experiments.s1 import spec\n"
     "with worker_lock(spec.REPO_ROOT / 'artifacts' / 'locks' / 'm0-worker.lock'):\n"
     "    print('HELD', flush=True); time.sleep(5)\n" % str(SB / "src")],
    cwd=str(SB), env=ENV, stdout=subprocess.PIPE, text=True)
assert holder.stdout.readline().strip() == "HELD"
r = cli(["--mode", "smoke", "--output-root", str(REPORTS), "--wall-budget-seconds", "5"])
holder.wait(timeout=20)
busy_ok = r["exit"] != 0 and "already running" in json.dumps(r["report"], ensure_ascii=False)
add("C11", "两个进程同时启动只有一个能运行（第二个被拒）",
    busy_ok, r["exit"],
    f"error={r['report'].get('error')} EXIT_LOCK_BUSY_constant={commands.EXIT_LOCK_BUSY}")

# --- C12 real smoke through the CLI, then RunStore completeness ----------
for stale in ("smoke_metrics.json", "control.sqlite3", "smoke_report.json"):
    (REPORTS / stale).unlink(missing_ok=True)
r = cli(["--mode", "smoke", "--output-root", str(REPORTS), "--wall-budget-seconds", "120"])
add("C12a", "smoke 经真实入口完成（沙箱锁/沙箱 RunStore）",
    r["exit"] == 0 and r["report"].get("status") == "completed",
    r["exit"], f"status={r['report'].get('status')} elapsed={r['report'].get('elapsed_seconds')}")

from ainerzero.runtime.lifecycle import TERMINAL_STATES, RunStore  # noqa: E402

with RunStore(REPORTS / "control.sqlite3") as store:
    runs = [run.to_dict() for run in store.list_runs()]
bad = [x for x in runs if x["state"] not in TERMINAL_STATES]
aux = [x for x in runs if x.get("role") != "auxiliary"]
steps = [x for x in runs if (x.get("reserved_optimizer_steps") or 0) != 0]
add("C12b", "RunStore 记录完整：全部终态、role=auxiliary、0 optimizer steps",
    not bad and not aux and not steps, 0,
    f"runs={len(runs)} non_terminal={len(bad)} non_aux={len(aux)} nonzero_steps={len(steps)}",
    {"states": sorted({x["state"] for x in runs})})

# --- C12c the re-run smoke still shows no parameter update ---------------
smoke = json.loads((REPORTS / "smoke_metrics.json").read_text())
recorded = json.loads((Path("/Users/mac/AinerWorkFlow/AinerZero/reports/V9-P9/smoke_metrics.json")).read_text())
same_sha = all(
    smoke["trainable_arms"][a]["parameter_sha256_before"]
    == smoke["trainable_arms"][a]["parameter_sha256_after"] for a in smoke["trainable_arms"]
)
add("C12c", "独立重跑冒烟：参数 SHA 前后一致、无梯度、无更新",
    smoke.get("parameters_unchanged") is True and smoke.get("gradients_computed") is False
    and smoke.get("updated_parameters") is False and same_sha,
    0, f"unchanged={smoke.get('parameters_unchanged')} same_sha={same_sha} "
       f"step_s={smoke.get('trainable_arms', {}).get('arm2', {}).get('forward_loss_step_seconds')}",
    {"recorded_step_s": recorded["trainable_arms"]["arm2"]["forward_loss_step_seconds"]})

(OUT / "p2.json").write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
print(f"\n{sum(r['ok'] for r in rows)}/{len(rows)} passed")
