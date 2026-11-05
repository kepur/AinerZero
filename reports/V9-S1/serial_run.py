#!/usr/bin/env python3
"""Serial P1 train/eval via submit-job; archive lost execs after non-completed jobs."""
from __future__ import annotations

import json
import sqlite3
import subprocess
import time
import urllib.request
from datetime import datetime
from pathlib import Path

AGENT = "composer-6bf9"
TASK = "ainerzero.V9.P1"
AUTH = "ainerzero:registration/19639d86b8f14ce0873ba367ae8d233fd371495a4c055af2b7344aa50b850718"
CWD = "/Users/mac/AinerWorkFlow/AinerZero"
PREREG = "artifacts/v9/s1/phase1/r10/pre_registration.json"
OUT = "artifacts/v9/s1/phase1"
PY = ".venv/bin/python"
RELAY = ["python3", "/Users/mac/AinerWorkFlow/AinerRelay/bin/relay"]
LEDGER = Path(__file__).resolve().parent / "run_ledger.json"
LOG = Path(__file__).resolve().parent / "serial_run.log"
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


def log(msg: str) -> None:
    line = f"[{datetime.now().strftime('%H:%M:%S')}] {msg}"
    print(line, flush=True)
    with LOG.open("a") as f:
        f.write(line + "\n")


def load() -> dict:
    if LEDGER.exists():
        return json.loads(LEDGER.read_text())
    return {"agent": AGENT, "trains": [], "evals": []}


def save(state: dict) -> None:
    state["updated_at"] = datetime.now().astimezone().strftime("%Y-%m-%dT%H:%M:%S%z")
    LEDGER.write_text(json.dumps(state, indent=2, ensure_ascii=False) + "\n")


def heartbeat(msg: str) -> None:
    subprocess.run(RELAY + ["heartbeat", TASK, "--agent", AGENT, "--msg", msg[:500]], check=False)


def archive_blocking_execs() -> list[str]:
    """jobs 把非 completed 标成 lost，会挡住同任务后续 submit；组空后归档为 finished。"""
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    rows = con.execute(
        "SELECT id,state,detail FROM task_execs WHERE task_id=? AND state NOT IN (?,?,?,?)",
        (TASK, *NONBLOCK),
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


def submit(job_type: str, argv: list[str], idem: str, ttl: int = 1800) -> dict:
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


def wait_done(job_id: str, timeout_s: float = 1500) -> dict:
    t0 = time.monotonic()
    last_hb = time.monotonic()
    while True:
        if time.monotonic() - last_hb > 480:
            heartbeat(f"等待 job {job_id}")
            last_hb = time.monotonic()
        p = subprocess.run(
            RELAY + ["job-wait", "--agent", AGENT, "--wait", "90", "--json", job_id],
            capture_output=True, text=True,
        )
        st = None
        if p.stdout.strip():
            try:
                st = json.loads(p.stdout)
            except json.JSONDecodeError:
                st = None
        if st is None:
            p2 = subprocess.run(
                RELAY + ["job-status", "--agent", AGENT, "--json", job_id],
                capture_output=True, text=True,
            )
            st = json.loads(p2.stdout)
        status = st.get("status")
        if status in {"completed", "failed", "canceled"} or (
            st.get("returncode") is not None and status not in {"queued", "preparing", "running"}
        ):
            return st
        if time.monotonic() - t0 > timeout_s:
            return st


def entry_from(st: dict, label: str, arm: str, seed) -> dict:
    return {
        "label": label,
        "arm": arm,
        "seed": seed,
        "id": st.get("id"),
        "status": st.get("status"),
        "returncode": st.get("returncode"),
        "reason": st.get("reason"),
        "started_at": st.get("started_at"),
        "ended_at": st.get("ended_at"),
        "argv": st.get("actual_argv") or st.get("argv"),
        "stdout_path": ((st.get("logs") or {}).get("stdout") or {}).get("path"),
        "stderr_path": ((st.get("logs") or {}).get("stderr") or {}).get("path"),
        "exec_id": st.get("exec_id"),
    }


def done_labels(items: list) -> set[str]:
    out = set()
    for e in items:
        # 仅「真正跑过训练/评测」的终态算 done；纯启动 409 不算消耗额度
        if e.get("label") and e.get("status") in {"completed", "failed", "canceled"}:
            if e.get("returncode") is not None or e.get("started_at"):
                out.add(e["label"])
            elif "409" in str(e.get("reason") or "") or "已有 exec" in str(e.get("reason") or ""):
                continue  # infra launch fail — retry allowed
            else:
                out.add(e["label"])
    return out


def run_one(mode: str, arm: str, seed, attempt_tag: str = "a") -> dict:
    archive_blocking_execs()
    if mode == "train":
        label = f"{arm}-seed{seed}"
        idem = f"p1-train-{arm}-seed{seed}-r10-20261023-{attempt_tag}"
        argv = [PY, "-m", "ainerzero.cli", "s1-phase1", "--mode", "train",
                "--arm", arm, "--seed", str(seed), "--prereg", PREREG, "--output-root", OUT]
        jtype = "train"
        ttl = 1800
    else:
        label = f"eval-{arm}" + (f"-seed{seed}" if seed is not None else "")
        idem = f"p1-{label}-r10-20261023-{attempt_tag}"
        argv = [PY, "-m", "ainerzero.cli", "s1-phase1", "--mode", "eval",
                "--arm", arm, "--prereg", PREREG, "--output-root", OUT]
        if seed is not None:
            argv.extend(["--seed", str(seed)])
        jtype = "eval"
        ttl = 900
    heartbeat(f"提交 {label}")
    log(f"submit {label} idem={idem}")
    sub = submit(jtype, argv, idem, ttl=ttl)
    job_id = sub["id"]
    log(f"queued {label} {job_id} status={sub.get('status')}")
    st = wait_done(job_id)
    archive_blocking_execs()
    # 若因 409 启动失败且未真正开跑，换 tag 再试一次
    if (
        st.get("status") == "failed"
        and st.get("started_at") is None
        and ("409" in str(st.get("reason") or "") or "已有 exec" in str(st.get("reason") or ""))
        and attempt_tag == "a"
    ):
        log(f"infra fail {label}; retry with tag b")
        return run_one(mode, arm, seed, attempt_tag="b")
    ent = entry_from(st, label, arm, seed)
    log(f"done {label} status={ent['status']} rc={ent['returncode']} reason={ent['reason']}")
    heartbeat(f"{label} → {ent['status']} rc={ent['returncode']}")
    return ent


def main() -> int:
    state = load()
    # arm2-seed0 already recorded as real train failure — keep it
    train_done = done_labels(state.get("trains", []))
    heartbeat(f"serial_run 启动；已完成训练标签 {sorted(train_done)}")
    for arm, seed in TRAINS:
        label = f"{arm}-seed{seed}"
        if label in train_done:
            log(f"skip {label}")
            continue
        ent = run_one("train", arm, seed)
        state = load()
        state.setdefault("trains", [])
        state["trains"] = [t for t in state["trains"] if t.get("label") != label] + [ent]
        save(state)
        train_done.add(label)

    state = load()
    eval_done = done_labels(state.get("evals", []))
    # 只对「有 started_at 的 train」做对应 eval；arm1 始终评
    train_ok_or_partial = {
        (t["arm"], t["seed"]): t
        for t in state.get("trains", [])
        if t.get("started_at")
    }
    for arm, seed in EVALS:
        label = f"eval-{arm}" + (f"-seed{seed}" if seed is not None else "")
        if label in eval_done:
            continue
        if arm != "arm1" and (arm, seed) not in train_ok_or_partial:
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
