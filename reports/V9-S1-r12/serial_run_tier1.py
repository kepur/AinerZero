#!/usr/bin/env python3
"""P32 r12 serial train/eval via relay submit-job (tier-1 hosted continuation).

Adapted from reports/V9-S1/serial_run.py (r10 P1). Continues after the first
holder (deepseekv41f-h3t8) lost its lease to a host sleep: arm2 seed 0/1 are
completed, arm2 seed 2 failed (environmental, not rerun). Those three jobs are
pre-recorded here and skipped; their idempotency keys are reused only so a
re-submission would return the existing job instead of a new run.
File scope: reports/V9-S1-r12/ only. The previous holder's files in this
directory are left untouched.
"""
from __future__ import annotations

import json
import sqlite3
import subprocess
import time
import urllib.request
from datetime import datetime
from pathlib import Path

AGENT = "claude"
TASK = "ainerzero.V9.P36"  # continuation card; P32 is wedged in recovery
LEAD_TASK = "relay.P2.E37"
AUTH = "ainerzero:registration/044d5599ecd7c88600257488866462f666eebde25454ad4e4494f355ccd418dd"
CWD = "/Users/mac/AinerWorkFlow/AinerZero"
PREREG = "artifacts/v9/s1/phase1/r12/pre_registration.json"
OUT = "artifacts/v9/s1/phase1"
PY = ".venv/bin/python"
RELAY = ["python3", "/Users/mac/AinerWorkFlow/AinerRelay/bin/relay"]
HERE = Path(__file__).resolve().parent
LEDGER = HERE / "run_ledger_tier1_p36.json"
LOG = HERE / "serial_run_tier1_p36.log"
DB = Path("/Users/mac/AinerWorkFlow/AinerRelay/data/relay.db")
NONBLOCK = ("finished", "stopped", "launch_failed", "abandoned_unknown")

TRAINS = [
    ("arm2", 0), ("arm2", 1), ("arm2", 2),
    ("arm3", 0), ("arm3", 1), ("arm3", 2),
    ("arm4", 0), ("arm4", 1), ("arm4", 2),
]
EVALS = [
    ("arm1", None),
    ("arm2", 0), ("arm2", 1), ("arm2", 2),
    ("arm3", 0), ("arm3", 1), ("arm3", 2),
    ("arm4", 0), ("arm4", 1), ("arm4", 2),
]

# Jobs run by the first holder before it lost its lease (runner job-status, 10:35).
PRIOR_TRAINS = [
    {"label": "arm2-seed0", "arm": "arm2", "seed": 0, "id": "job-07e97f23098846538ced49a01a0b4519",
     "status": "completed", "returncode": 0, "started_at": "2026-10-24T08:50:30+0300",
     "submitted_by": "deepseekv41f-h3t8"},
    {"label": "arm2-seed1", "arm": "arm2", "seed": 1, "id": "job-796cf5cd72b84d46a96e62f0d6d8778c",
     "status": "completed", "returncode": 0, "started_at": "2026-10-24T09:05:14+0300",
     "submitted_by": "deepseekv41f-h3t8"},
    {"label": "arm2-seed2", "arm": "arm2", "seed": 2, "id": "job-60ff8abd76574c9c8bcdc020011fb575",
     "status": "failed", "returncode": 1, "started_at": "2026-10-24T09:19:59+0300",
     "reason": "budget_exhausted (wall 1209.95 s > 1200 s, 2556/3510 steps); host clamshell sleep "
               "09:30:38 571 s — environmental failure, not rerun (user 10-24)",
     "submitted_by": "deepseekv41f-h3t8"},
]


def log(msg: str) -> None:
    line = f"[{datetime.now().strftime('%H:%M:%S')}] {msg}"
    print(line, flush=True)
    with LOG.open("a") as f:
        f.write(line + "\n")


def load() -> dict:
    if LEDGER.exists():
        return json.loads(LEDGER.read_text())
    return {"agent": AGENT, "task": TASK, "trains": list(PRIOR_TRAINS), "evals": []}


def save(state: dict) -> None:
    state["updated_at"] = datetime.now().astimezone().strftime("%Y-%m-%dT%H:%M:%S%z")
    LEDGER.write_text(json.dumps(state, indent=2, ensure_ascii=False) + "\n")


def heartbeat(msg: str) -> None:
    for task in (TASK, LEAD_TASK):
        subprocess.run(RELAY + ["heartbeat", task, "--agent", AGENT, "--msg", msg[:500]],
                       check=False, capture_output=True)


def archive_blocking_execs() -> list[str]:
    """jobs 把非 completed 标成 lost，会挡住同任务后续 submit；组空后归档为 finished。"""
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    # Only our own execs can be archived (relay finish_exec is owner-only); the first
    # holder's lost exec for the failed arm2-seed2 job stays as it is.
    rows = con.execute(
        "SELECT id,state,detail FROM task_execs WHERE task_id=? AND agent=? AND state NOT IN (?,?,?,?)",
        (TASK, AGENT, *NONBLOCK),
    ).fetchall()
    con.close()
    archived = []
    for r in rows:
        eid = r["id"]
        body = json.dumps({
            "agent": AGENT,
            "exec_id": eid,
            "state": "finished",
            "detail": f"archive {r['state']}→finished after confirmed job end; prior={r['detail']}",
        }).encode()
        req = urllib.request.Request(
            f"http://127.0.0.1:8790/api/tasks/{TASK}/exec/{eid}/finish",
            data=body, method="POST",
            headers={"Content-Type": "application/json", "X-Relay-Agent": AGENT},
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            resp.read()
        archived.append(eid)
        log(f"archived exec {eid} (was {r['state']})")
    return archived


def submit(job_type: str, argv: list[str], idem: str, ttl: int) -> dict:
    cmd = RELAY + [
        "submit-job", "--agent", AGENT, "--project", "ainerzero", "--task", TASK,
        "--type", job_type, "--cwd", CWD, "--authorization-ref", AUTH,
        "--idempotency-key", idem, "--gpu-class", "0", "--peak-mem", "8",
        "--ttl", str(ttl), "--max-attempts", "1", "--json", "--", *argv,
    ]
    p = subprocess.run(cmd, capture_output=True, text=True)
    if p.returncode != 0:
        raise RuntimeError(f"submit failed rc={p.returncode}: {p.stderr or p.stdout}")
    return json.loads(p.stdout)


def job_status(job_id: str) -> dict:
    p = subprocess.run(RELAY + ["job-status", "--agent", AGENT, "--json", job_id],
                       capture_output=True, text=True)
    return json.loads(p.stdout)


def wait_done(job_id: str, timeout_s: float = 1500) -> dict:
    t0 = time.monotonic()
    last_hb = 0.0
    while True:
        if time.monotonic() - last_hb > 300:
            heartbeat(f"等待 job {job_id}")
            last_hb = time.monotonic()
        subprocess.run(RELAY + ["job-wait", "--agent", AGENT, "--wait", "90", "--json", job_id],
                       capture_output=True, text=True)
        st = job_status(job_id)
        if st.get("status") in {"completed", "failed", "canceled"}:
            return st
        if time.monotonic() - t0 > timeout_s:
            return st


def entry_from(st: dict, label: str, arm: str, seed, idem: str) -> dict:
    return {
        "label": label,
        "arm": arm,
        "seed": seed,
        "idempotency_key": idem,
        "id": st.get("id"),
        "status": st.get("status"),
        "returncode": st.get("returncode"),
        "reason": st.get("reason"),
        "started_at": st.get("started_at"),
        "ended_at": st.get("ended_at") or st.get("updated_at"),
        "argv": st.get("actual_argv") or st.get("argv"),
        "group_empty": st.get("group_empty"),
        "exec_id": st.get("exec_id"),
        "submitted_by": AGENT,
    }


def done_labels(items: list) -> set[str]:
    return {e["label"] for e in items if e.get("label") and e.get("status") in {"completed", "failed", "canceled"}}


def run_one(mode: str, arm: str, seed) -> dict:
    archive_blocking_execs()
    if mode == "train":
        label = f"{arm}-seed{seed}"
        idem = f"s1-r12b-train-{arm}-s{seed}"
        argv = [PY, "-m", "ainerzero.cli", "s1-phase1", "--mode", "train",
                "--arm", arm, "--seed", str(seed), "--prereg", PREREG, "--output-root", OUT]
        ttl = 1800
    else:
        label = f"eval-{arm}" + (f"-seed{seed}" if seed is not None else "")
        idem = f"s1-r12b-eval-{arm}" + (f"-s{seed}" if seed is not None else "")
        argv = [PY, "-m", "ainerzero.cli", "s1-phase1", "--mode", "eval",
                "--arm", arm, "--prereg", PREREG, "--output-root", OUT]
        if seed is not None:
            argv.extend(["--seed", str(seed)])
        ttl = 900
    heartbeat(f"提交 {label}")
    log(f"submit {label} idem={idem}")
    sub = submit(mode, argv, idem, ttl=ttl)
    job_id = sub["id"]
    log(f"queued {label} {job_id} status={sub.get('status')}")
    st = wait_done(job_id)
    archive_blocking_execs()
    ent = entry_from(st, label, arm, seed, idem)
    log(f"done {label} status={ent['status']} rc={ent['returncode']} reason={ent['reason']}")
    if ent["status"] != "completed" and not ent["started_at"]:
        # Launch-level refusal (never started): stop everything instead of burning the next keys.
        heartbeat(f"{label} 未启动即被拒，驱动停止：{ent['reason']}")
        raise SystemExit(f"launch refused for {label}: {ent['reason']}")
    heartbeat(f"{label} → {ent['status']} rc={ent['returncode']}")
    return ent


def main() -> int:
    state = load()
    save(state)
    train_done = done_labels(state.get("trains", []))
    heartbeat(f"一级托管 serial_run 启动；已完成训练 {sorted(train_done)}")
    log(f"start; prior trains {sorted(train_done)}")
    for arm, seed in TRAINS:
        label = f"{arm}-seed{seed}"
        if label in train_done:
            log(f"skip {label}")
            continue
        ent = run_one("train", arm, seed)
        state = load()
        state["trains"] = [t for t in state["trains"] if t.get("label") != label] + [ent]
        save(state)
        train_done.add(label)

    state = load()
    eval_done = done_labels(state.get("evals", []))
    started = {(t["arm"], t["seed"]) for t in state.get("trains", []) if t.get("started_at")}
    for arm, seed in EVALS:
        label = f"eval-{arm}" + (f"-seed{seed}" if seed is not None else "")
        if label in eval_done:
            continue
        if arm != "arm1" and (arm, seed) not in started:
            log(f"skip {label}: no train attempt")
            continue
        ent = run_one("eval", arm, seed)
        state = load()
        state.setdefault("evals", [])
        state["evals"] = [e for e in state["evals"] if e.get("label") != label] + [ent]
        save(state)

    state = load()
    state["finished_at"] = datetime.now().astimezone().strftime("%Y-%m-%dT%H:%M:%S%z")
    save(state)
    heartbeat("serial_run 全部结束")
    log("ALL_DONE")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
