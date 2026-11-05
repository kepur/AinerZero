#!/usr/bin/env python3
"""P32 作业记账：从 relay job 目录与 run 产物抽取 argv/键/rc/时间/墙钟/组空证据。

用法: python3 ledger.py <job_id> <label> <idempotency_key> <run_dir_name>
只写 reports/V9-S1-r12/run_ledger.json（append/update 按 label 幂等）。
"""
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

RELAY = Path("/Users/mac/AinerWorkFlow/AinerRelay/data/runs/jobs-v1")
AZ = Path("/Users/mac/AinerWorkFlow/AinerZero")
OUT = AZ / "reports/V9-S1-r12/run_ledger.json"


def parse_ts(s: str | None):
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("+0300", "+03:00").replace("+0000", "+00:00"))
    except Exception:
        return None


def main() -> int:
    job_id, label, key, run_name = sys.argv[1:5]
    task_id = sys.argv[5] if len(sys.argv) > 5 else "ainerzero.V9.P32"
    jdir = RELAY / job_id
    job = json.loads((jdir / "job.json").read_text())
    attempts = sorted((jdir / "attempts").glob("*/"))
    att = attempts[-1] if attempts else None
    state = json.loads((att / "state.json").read_text()) if att and (att / "state.json").is_file() else {}
    launch = json.loads((att / "launch.json").read_text()) if att and (att / "launch.json").is_file() else {}

    stdout_tail = {}
    if att and (att / "stdout.log").is_file():
        raw = (att / "stdout.log").read_text(errors="replace")
        i = raw.rfind("{")
        # 训练入口最后输出一个 JSON 摘要；用括号配平找起点
        depth, start = 0, None
        for pos in range(len(raw) - 1, -1, -1):
            ch = raw[pos]
            if ch == "}":
                depth += 1
            elif ch == "{":
                depth -= 1
                if depth == 0:
                    start = pos
                    break
        if start is not None:
            try:
                stdout_tail = json.loads(raw[start:])
            except Exception:
                stdout_tail = {}

    budget = stdout_tail.get("run") or {}
    details = stdout_tail.get("details") or {}
    run_dir = AZ / "artifacts/v9/s1/phase1/runs" / run_name if run_name != "-" else None
    completion = {}
    if run_dir and (run_dir / "completion.json").is_file():
        completion = json.loads((run_dir / "completion.json").read_text())

    rec = {
        "label": label,
        "task": task_id,
        "idempotency_key": key,
        "job_id": job_id,
        "argv": launch.get("argv") or job.get("argv"),
        "cwd": launch.get("cwd") or job.get("cwd"),
        "submitted_at": state.get("submitted_at") or job.get("submitted_at"),
        "started_at": state.get("started_at"),
        "ended_at": state.get("ended_at"),
        "status": state.get("status"),
        "leader_returncode": state.get("leader_returncode"),
        "attempt": state.get("attempt_count"),
        "max_attempts": job.get("max_attempts"),
        "supervision": state.get("supervision"),
        "group_empty": state.get("group_empty"),
        "wall_seconds_job": (
            (parse_ts(state.get("ended_at")) - parse_ts(state.get("started_at"))).total_seconds()
            if state.get("ended_at") and state.get("started_at")
            else None
        ),
        "wall_seconds_worker": stdout_tail.get("elapsed_seconds"),
        "worker_exit_code": stdout_tail.get("worker_exit_code"),
        "reserved_optimizer_steps": budget.get("reserved_optimizer_steps"),
        "remaining_optimizer_steps": (budget.get("remaining") or {}).get("optimizer_steps"),
        "reserved_active_seconds": budget.get("reserved_active_seconds"),
        "daily_remaining_seconds": (budget.get("remaining") or {}).get("daily_active_seconds"),
        "sample_efficiency_curve": details.get("sample_efficiency_curve"),
        "run_dir": run_name if run_name != "-" else None,
        "final_training_loss": (completion.get("final_training_loss") if completion else None),
        "checkpoints": [
            {"updates": c.get("updates"), "development_nll": c.get("development_nll"),
             "sha256": (c.get("sha256") or "")[:16]}
            for c in (completion.get("checkpoints") or [])
        ],
        "completion_elapsed_at_record": (completion.get("completion_protocol") or {}).get("elapsed_at_record_seconds")
        if isinstance(completion.get("completion_protocol"), dict) else None,
    }

    data = {"task": "ainerzero.V9.P32", "agent": "deepseekv41f-h3t8",
            "experiment_id": "s1-phase1-20261023-r12",
            "prereg_document_sha256": "044d5599ecd7c88600257488866462f666eebde25454ad4e4494f355ccd418dd",
            "jobs": []}
    if OUT.is_file():
        data = json.loads(OUT.read_text())
    data["jobs"] = [j for j in data["jobs"] if j.get("label") != label] + [rec]
    order = {lbl: i for i, lbl in enumerate([
        "verify", "arm2-s0", "arm2-s1", "arm2-s2", "arm3-s0", "arm3-s1", "arm3-s2",
        "arm4-s0", "arm4-s1", "arm4-s2", "eval-arm1", "eval-arm2", "eval-arm3", "eval-arm4"])}
    data["jobs"].sort(key=lambda j: order.get(j.get("label"), 99))
    data["updated_at"] = datetime.now().astimezone().isoformat(timespec="seconds")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({k: rec[k] for k in ("label", "job_id", "status", "leader_returncode",
                                          "wall_seconds_job", "wall_seconds_worker",
                                          "reserved_optimizer_steps", "remaining_optimizer_steps",
                                          "final_training_loss")}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
