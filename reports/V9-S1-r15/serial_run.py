#!/usr/bin/env python3
"""P55 r15 serial train/eval via relay submit-job (tier-1 claude).

Adapted from reports/V9-S1-r14/serial_run.py.  RESEARCH_LOG R20261028-S1-phase1-r15-budget:
* trains only arm4 s0 (the r14 attempt was lost to a host clamshell sleep; user-approved);
* evaluates arm1 D plus all nine arm2/3/4 cells (eight inherited cells bind their r13/r14
  source runs inside the worker);
* total wall cap 5400 s, enforced *before* every launch against the job's worst case
  (supervision seconds), measured from the first launch; a launch that could cross the
  cap is not made and the remaining items are recorded as not run;
* every launch first checks AC power and an open lid; a launch refused before start stops the driver;
* failures are never retried; only this agent's execs are archived.
Run under ``caffeinate -i -s``.  Writes only reports/V9-S1-r15/.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import subprocess
import time
import urllib.request
from datetime import datetime
from pathlib import Path

AGENT = "claude"
TASK = "ainerzero.V9.P55"
DOC_SHA = "2174de670c844535ce63795a23ba4b413ad70ef3f1c2cf7a929b3de5bb5a99f9"
AUTH = f"ainerzero:registration/{DOC_SHA}"
CWD = "/Users/mac/AinerWorkFlow/AinerZero"
PREREG = "artifacts/v9/s1/phase1/r15/pre_registration.json"
OUT = "artifacts/v9/s1/phase1"
PY = ".venv/bin/python"
RELAY = ["python3", "/Users/mac/AinerWorkFlow/AinerRelay/bin/relay"]
HERE = Path(__file__).resolve().parent
LEDGER = HERE / "run_ledger.json"
LOG = HERE / "serial_run.log"
DB = Path("/Users/mac/AinerWorkFlow/AinerRelay/data/relay.db")
NONBLOCK = ("finished", "stopped", "launch_failed", "abandoned_unknown")

CAP_SECONDS = 5_400.0
WORST = {"train": 1_250.0, "eval": 350.0}  # supervision = deadline + 50 s

TRAINS = [("arm4", 0)]
INHERITED = {("arm2", 0), ("arm2", 1), ("arm2", 2), ("arm3", 0), ("arm3", 1), ("arm3", 2), ("arm4", 1), ("arm4", 2)}
EVALS = [("arm1", None)] + [(arm, seed) for arm in ("arm2", "arm3", "arm4") for seed in (0, 1, 2)]


def now() -> str:
    return datetime.now().astimezone().strftime("%Y-%m-%dT%H:%M:%S%z")


def log(msg: str) -> None:
    line = f"[{datetime.now().strftime('%H:%M:%S')}] {msg}"
    print(line, flush=True)
    with LOG.open("a") as f:
        f.write(line + "\n")


def load() -> dict:
    if LEDGER.exists():
        return json.loads(LEDGER.read_text())
    return {"agent": AGENT, "task": TASK, "document_sha256": DOC_SHA, "trains": [], "evals": [],
            "not_run": [], "cap_seconds": CAP_SECONDS}


def save(state: dict) -> None:
    state["updated_at"] = now()
    LEDGER.write_text(json.dumps(state, indent=2, ensure_ascii=False) + "\n")


def heartbeat(msg: str) -> None:
    res = subprocess.run(RELAY + ["heartbeat", TASK, "--agent", AGENT, "--msg", msg[:500]],
                         check=False, capture_output=True, text=True)
    if res.returncode != 0:
        log(f"heartbeat warn rc={res.returncode}: {(res.stderr or res.stdout)[-300:]}")


def on_ac_power() -> bool:
    out = subprocess.run(["pmset", "-g", "batt"], capture_output=True, text=True).stdout
    return "AC Power" in out


def lid_open() -> bool:
    out = subprocess.run(["ioreg", "-r", "-k", "AppleClamshellState", "-d", "4"], capture_output=True, text=True).stdout
    return '"AppleClamshellState" = No' in out


def archive_blocking_execs() -> list[str]:
    """Archive this agent's own non-terminal execs of this task (never another agent's)."""
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    rows = con.execute(
        "SELECT id,state,detail FROM task_execs WHERE task_id=? AND agent=? AND state NOT IN (?,?,?,?)",
        (TASK, AGENT, *NONBLOCK),
    ).fetchall()
    con.close()
    archived = []
    for r in rows:
        body = json.dumps({"agent": AGENT, "exec_id": r["id"], "state": "finished",
                           "detail": f"archive {r['state']}->finished after confirmed job end; prior={r['detail']}"}).encode()
        req = urllib.request.Request(
            f"http://127.0.0.1:8790/api/tasks/{TASK}/exec/{r['id']}/finish", data=body, method="POST",
            headers={"Content-Type": "application/json", "X-Relay-Agent": AGENT})
        with urllib.request.urlopen(req, timeout=30) as resp:
            resp.read()
        archived.append(r["id"])
        log(f"archived exec {r['id']} (was {r['state']})")
    return archived


def submit(job_type: str, argv: list[str], idem: str, ttl: int) -> dict:
    cmd = RELAY + ["submit-job", "--agent", AGENT, "--project", "ainerzero", "--task", TASK,
                   "--type", job_type, "--cwd", CWD, "--authorization-ref", AUTH,
                   "--idempotency-key", idem, "--gpu-class", "0", "--peak-mem", "8",
                   "--ttl", str(ttl), "--max-attempts", "1", "--json", "--", *argv]
    p = subprocess.run(cmd, capture_output=True, text=True)
    if p.returncode != 0:
        raise RuntimeError(f"submit failed rc={p.returncode}: {p.stderr or p.stdout}")
    return json.loads(p.stdout)


def job_status(job_id: str) -> dict:
    p = subprocess.run(RELAY + ["job-status", "--agent", AGENT, "--json", job_id], capture_output=True, text=True)
    return json.loads(p.stdout)


def wait_done(job_id: str, timeout_s: float = 2_400) -> dict:
    t0 = last_hb = time.monotonic()
    heartbeat(f"等待 job {job_id}")
    while True:
        if time.monotonic() - last_hb > 180:
            heartbeat(f"等待 job {job_id}（已等 {int(time.monotonic() - t0)}s）")
            last_hb = time.monotonic()
        subprocess.run(RELAY + ["job-wait", "--agent", AGENT, "--wait", "60", "--json", job_id],
                       capture_output=True, text=True)
        st = job_status(job_id)
        if st.get("status") in {"completed", "failed", "canceled"}:
            return st
        if time.monotonic() - t0 > timeout_s:
            heartbeat(f"job {job_id} 等待超时 {timeout_s}s")
            return st


def params_sha(run_id: str | None) -> str | None:
    if not run_id:
        return None
    path = Path(CWD) / OUT / "runs" / run_id / "params.npz"
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None


def run_ids_from(st: dict) -> list[str]:
    """All distinct run ids the job's stdout report mentions (the train report names its run)."""
    import re

    path = ((st.get("logs") or {}).get("stdout") or {}).get("path")
    if not path or not Path(path).is_file():
        return []
    text = Path(path).read_text(encoding="utf-8", errors="replace")
    return sorted(set(re.findall(r'"run_id": "([0-9a-f]{32})"', text)))


def main() -> int:
    state = load()
    state["elapsed_rule"] = "wall seconds since the first launch (time.time), checked before every launch"
    save(state)
    done = {e["label"] for e in state["trains"] + state["evals"] if e.get("status") in {"completed", "failed", "canceled"}}
    queue = [("train", a, s) for a, s in TRAINS] + [("eval", a, s) for a, s in EVALS]
    heartbeat(f"r15 serial_run 启动；已结束 {sorted(done)}")
    def label_of(mode, arm, seed):
        return f"{arm}-seed{seed}" if mode == "train" else f"eval-{arm}" + (f"-seed{seed}" if seed is not None else "")

    for index, (mode, arm, seed) in enumerate(queue):
        label = label_of(mode, arm, seed)
        if label in done:
            continue
        state = load()
        first = state.get("first_launch_at_unix")
        elapsed = 0.0 if first is None else time.time() - float(first)
        if elapsed + WORST[mode] > CAP_SECONDS:
            log(f"cap: elapsed {elapsed:.0f}s + worst {WORST[mode]:.0f}s > {CAP_SECONDS:.0f}s; stop before {label}")
            state["not_run"] = [
                {"label": label_of(*item), "reason": "would_exceed_approved_total_wall", "elapsed_s": elapsed}
                for item in queue[index:] if label_of(*item) not in done
            ]
            state["stopped_reason"] = "approved_total_wall_cap"
            save(state)
            heartbeat(f"总墙钟上限：{label} 起不再启动（已用 {elapsed:.0f}s）")
            return 3
        if not on_ac_power() or not lid_open():
            why = "not_on_ac_power" if not on_ac_power() else "lid_closed"
            log(f"{why}; stop before {label}")
            state["stopped_reason"] = why
            save(state)
            heartbeat(f"{why}，{label} 起停止")
            return 4
        archive_blocking_execs()
        if mode == "train":
            idem = f"s1-r15-train-{arm}-s{seed}"
            argv = [PY, "-m", "ainerzero.cli", "s1-phase1", "--mode", "train", "--arm", arm, "--seed", str(seed),
                    "--prereg", PREREG, "--output-root", OUT]
            ttl = 1_800
        else:
            idem = f"s1-r15-eval-{arm}" + (f"-s{seed}" if seed is not None else "")
            argv = [PY, "-m", "ainerzero.cli", "s1-phase1", "--mode", "eval", "--arm", arm,
                    "--prereg", PREREG, "--output-root", OUT] + (["--seed", str(seed)] if seed is not None else [])
            ttl = 900
        if first is None:
            state["first_launch_at_unix"] = time.time()
            state["first_launch_at"] = now()
            save(state)
        heartbeat(f"提交 {label}（已用 {elapsed:.0f}s/{CAP_SECONDS:.0f}s）")
        log(f"submit {label} idem={idem}")
        sub = submit(mode, argv, idem, ttl=ttl)
        log(f"queued {label} job={sub['id']}")
        st = wait_done(sub["id"])
        archive_blocking_execs()
        entry = {
            "label": label, "mode": mode, "arm": arm, "seed": seed, "idempotency_key": idem,
            "id": st.get("id"), "status": st.get("status"), "returncode": st.get("returncode"),
            "reason": st.get("reason"), "started_at": st.get("started_at"),
            "ended_at": st.get("ended_at") or st.get("updated_at"), "group_empty": st.get("group_empty"),
            "argv": st.get("actual_argv") or st.get("argv"), "inherited_cell": (arm, seed) in INHERITED,
        }
        if mode == "train":
            ids = run_ids_from(st)
            entry["run_ids_in_stdout"] = ids
            entry["run_id"] = ids[0] if len(ids) == 1 else None
            entry["params_sha256"] = params_sha(entry["run_id"])
        state = load()
        key = "trains" if mode == "train" else "evals"
        state[key] = [e for e in state[key] if e.get("label") != label] + [entry]
        save(state)
        log(f"done {label} status={entry['status']} rc={entry['returncode']} reason={entry['reason']}")
        if entry["status"] != "completed" and not entry["started_at"]:
            heartbeat(f"{label} 未启动即被拒，驱动停止：{entry['reason']}")
            state["stopped_reason"] = f"launch_refused:{label}"
            save(state)
            return 5
        if mode == "eval" and entry["status"] != "completed":
            # r14 lesson: a systematic eval failure would burn every remaining eval attempt.
            # Stop at the first one; the driver can be relaunched and skips finished items.
            heartbeat(f"{label} 评测失败，驱动停下待诊断：{entry['reason']}")
            state["stopped_reason"] = f"eval_failed:{label}"
            save(state)
            return 6
        heartbeat(f"{label} → {entry['status']} rc={entry['returncode']}")
    state = load()
    state["finished_at"] = now()
    first = state.get("first_launch_at_unix")
    state["total_wall_seconds_since_first_launch"] = None if first is None else time.time() - float(first)
    save(state)
    heartbeat("r15 serial_run 全部结束")
    log("ALL_DONE")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
