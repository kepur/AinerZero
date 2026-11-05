#!/usr/bin/env python3
"""P1 serial train/eval driver via relay submit-job. File-scope: reports/V9-S1/ only."""
from __future__ import annotations

import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

RELAY = ["/usr/bin/env", "python3", "/Users/mac/AinerWorkFlow/AinerRelay/bin/relay"]
AGENT = "composer-6bf9"
TASK = "ainerzero.V9.P1"
AUTH = "ainerzero:registration/19639d86b8f14ce0873ba367ae8d233fd371495a4c055af2b7344aa50b850718"
CWD = "/Users/mac/AinerWorkFlow/AinerZero"
PREREG = "artifacts/v9/s1/phase1/r10/pre_registration.json"
OUT = "artifacts/v9/s1/phase1"
PY = ".venv/bin/python"
LEDGER = Path(__file__).resolve().parent / "run_ledger.json"
PROGRESS = Path(__file__).resolve().parent / "PROGRESS.md"

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


def now() -> str:
    return datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%dT%H:%M:%S%z")


def load() -> dict:
    if LEDGER.exists():
        return json.loads(LEDGER.read_text())
    return {
        "agent": AGENT,
        "started_at": now(),
        "verify_job": "job-d1ed6a05ba184ca6be781ec03ae07173",
        "trains": [],
        "evals": [],
        "phase_started_monotonic": time.monotonic(),
    }


def save(state: dict) -> None:
    state["updated_at"] = now()
    LEDGER.write_text(json.dumps(state, indent=2, ensure_ascii=False) + "\n")


def heartbeat(msg: str) -> None:
    subprocess.run(
        RELAY + ["heartbeat", TASK, "--agent", AGENT, "--msg", msg[:500]],
        check=False,
    )


def submit(job_type: str, argv: list[str], idem: str, peak: float = 8.0, ttl: int = 1800) -> dict:
    cmd = RELAY + [
        "submit-job", "--agent", AGENT, "--project", "ainerzero", "--task", TASK,
        "--type", job_type, "--cwd", CWD,
        "--authorization-ref", AUTH, "--idempotency-key", idem,
        "--gpu-class", "0", "--peak-mem", str(peak), "--ttl", str(ttl),
        "--max-attempts", "1", "--json", "--", *argv,
    ]
    p = subprocess.run(cmd, capture_output=True, text=True)
    if p.returncode != 0:
        return {"submit_error": True, "returncode": p.returncode, "stdout": p.stdout, "stderr": p.stderr}
    return json.loads(p.stdout)


def wait_job(job_id: str, wait_s: int = 1500) -> dict:
    try:
        p = subprocess.run(
            RELAY + ["job-wait", "--agent", AGENT, "--wait", str(wait_s), "--json", job_id],
            capture_output=True, text=True, timeout=wait_s + 60,
        )
        if p.stdout.strip():
            try:
                return json.loads(p.stdout)
            except json.JSONDecodeError as e:
                Path(__file__).resolve().parent.joinpath("driver.err").write_text(
                    f"job-wait parse fail {job_id}: {e}\n{p.stdout[:2000]}\n{p.stderr[:2000]}\n"
                )
    except Exception as e:
        Path(__file__).resolve().parent.joinpath("driver.err").write_text(
            f"job-wait exception {job_id}: {e!r}\n"
        )
    p2 = subprocess.run(
        RELAY + ["job-status", "--agent", AGENT, "--json", job_id],
        capture_output=True, text=True,
    )
    if p2.stdout.strip():
        return json.loads(p2.stdout)
    return {"status": "unknown", "id": job_id, "stderr": p2.stderr}


def summarize(job: dict) -> dict:
    logs = job.get("logs") or {}
    return {
        "id": job.get("id"),
        "status": job.get("status"),
        "returncode": job.get("returncode"),
        "reason": job.get("reason"),
        "started_at": job.get("started_at"),
        "ended_at": job.get("ended_at"),
        "argv": job.get("actual_argv") or job.get("argv"),
        "stdout_sha256": (logs.get("stdout") or {}).get("sha256"),
        "stderr_sha256": (logs.get("stderr") or {}).get("sha256"),
        "stdout_path": (logs.get("stdout") or {}).get("path"),
        "stderr_path": (logs.get("stderr") or {}).get("path"),
        "exec_id": job.get("exec_id"),
    }


def already_done(entries: list, key: str) -> set[str]:
    out = set()
    for e in entries:
        if e.get("status") in {"completed", "failed", "canceled"} or e.get("returncode") is not None:
            if e.get(key):
                out.add(e[key])
    return out


def run_trains(state: dict) -> None:
    done = already_done(state["trains"], "label")
    last_hb = time.monotonic()
    for arm, seed in TRAINS:
        label = f"{arm}-seed{seed}"
        if label in done:
            continue
        elapsed_phase = time.monotonic() - state["phase_started_monotonic"]
        if elapsed_phase > 14400:
            state["phase_wall_exceeded"] = True
            save(state)
            heartbeat(f"阶段墙钟超限 {elapsed_phase:.0f}s；停止提交新训练")
            return
        argv = [
            PY, "-m", "ainerzero.cli", "s1-phase1",
            "--mode", "train", "--arm", arm, "--seed", str(seed),
            "--prereg", PREREG, "--output-root", OUT,
        ]
        idem = f"p1-train-{arm}-seed{seed}-r10-20261023"
        heartbeat(f"提交 train {label}（已完成 {len(done)}/9）")
        t0 = time.monotonic()
        sub = submit("train", argv, idem, peak=8.0, ttl=1800)
        if sub.get("submit_error"):
            entry = {"label": label, "arm": arm, "seed": seed, **sub, "wall_s": 0}
            state["trains"].append(entry)
            save(state)
            heartbeat(f"submit 失败 {label}；按不重跑停训")
            return
        job_id = sub["id"]
        # poll with heartbeats
        while True:
            if time.monotonic() - last_hb > 480:
                heartbeat(f"等待 train {label} job={job_id}")
                last_hb = time.monotonic()
            st = wait_job(job_id, wait_s=120)
            status = st.get("status")
            if status in {"completed", "failed", "canceled"} or st.get("returncode") is not None:
                wall = time.monotonic() - t0
                entry = {
                    "label": label, "arm": arm, "seed": seed,
                    "wall_s": round(wall, 2),
                    **summarize(st),
                }
                state["trains"].append(entry)
                save(state)
                done.add(label)
                rc = st.get("returncode")
                heartbeat(f"train {label} 结束 status={status} rc={rc} wall={wall:.0f}s")
                if status != "completed" or rc not in (0, None):
                    # 失败不重跑、不挪用；继续后续？卡面：失败不重跑不挪额度。
                    # 继续其它 arm×seed（各自独立额度），但记录失败。
                    pass
                break
            if time.monotonic() - t0 > 1500:
                entry = {
                    "label": label, "arm": arm, "seed": seed,
                    "wall_s": round(time.monotonic() - t0, 2),
                    "timeout_waiting": True,
                    **summarize(st),
                }
                state["trains"].append(entry)
                save(state)
                heartbeat(f"train {label} 等待超时；不重跑")
                return


def run_evals(state: dict) -> None:
    done = already_done(state["evals"], "label")
    last_hb = time.monotonic()
    for arm, seed in EVALS:
        label = f"eval-{arm}" + (f"-seed{seed}" if seed is not None else "")
        if label in done:
            continue
        argv = [
            PY, "-m", "ainerzero.cli", "s1-phase1",
            "--mode", "eval", "--arm", arm,
            "--prereg", PREREG, "--output-root", OUT,
        ]
        if seed is not None:
            argv.extend(["--seed", str(seed)])
        idem = f"p1-{label}-r10-20261023"
        heartbeat(f"提交 {label}")
        t0 = time.monotonic()
        sub = submit("eval", argv, idem, peak=8.0, ttl=900)
        if sub.get("submit_error"):
            state["evals"].append({"label": label, "arm": arm, "seed": seed, **sub})
            save(state)
            return
        job_id = sub["id"]
        while True:
            if time.monotonic() - last_hb > 480:
                heartbeat(f"等待 {label} job={job_id}")
                last_hb = time.monotonic()
            st = wait_job(job_id, wait_s=120)
            status = st.get("status")
            if status in {"completed", "failed", "canceled"} or st.get("returncode") is not None:
                entry = {
                    "label": label, "arm": arm, "seed": seed,
                    "wall_s": round(time.monotonic() - t0, 2),
                    **summarize(st),
                }
                state["evals"].append(entry)
                save(state)
                done.add(label)
                heartbeat(f"{label} 结束 status={status} rc={st.get('returncode')}")
                break
            if time.monotonic() - t0 > 900:
                state["evals"].append({
                    "label": label, "arm": arm, "seed": seed,
                    "timeout_waiting": True, **summarize(st),
                })
                save(state)
                return


def main() -> int:
    err_path = Path(__file__).resolve().parent / "driver.err"
    try:
        state = load()
        if "phase_started_monotonic" not in state:
            state["phase_started_monotonic"] = time.monotonic()
        # 恢复：若有在途 train 作业（驱动曾退出），挂到 ledger 再等
        recover_running(state)
        save(state)
        heartbeat("driver 启动/恢复：串行 train×9 然后 eval")
        run_trains(state)
        state = load()
        train_ok = sum(1 for t in state["trains"] if t.get("status") == "completed" and t.get("returncode") == 0)
        heartbeat(f"训练段结束 ok={train_ok}/9；开始 eval")
        run_evals(state)
        state = load()
        state["finished_at"] = now()
        save(state)
        heartbeat(f"全部作业结束 trains={len(state['trains'])} evals={len(state['evals'])}")
        return 0
    except Exception as e:
        import traceback
        err_path.write_text(traceback.format_exc())
        heartbeat(f"driver 异常：{e!r}")
        raise


def recover_running(state: dict) -> None:
    """Idempotent re-attach to first unfinished train via known idempotency keys."""
    done = already_done(state["trains"], "label")
    for arm, seed in TRAINS:
        label = f"{arm}-seed{seed}"
        if label in done:
            continue
        idem = f"p1-train-{arm}-seed{seed}-r10-20261023"
        # re-submit returns existing job if same idempotency key
        argv = [
            PY, "-m", "ainerzero.cli", "s1-phase1",
            "--mode", "train", "--arm", arm, "--seed", str(seed),
            "--prereg", PREREG, "--output-root", OUT,
        ]
        sub = submit("train", argv, idem, peak=8.0, ttl=1800)
        if sub.get("submit_error"):
            return
        job_id = sub["id"]
        status = sub.get("status")
        if status in {"queued", "preparing", "running", "completed", "failed", "canceled"}:
            # wait out this one before continuing the normal loop (which will see it via idempotency)
            t0 = time.monotonic()
            last_hb = time.monotonic()
            while True:
                if time.monotonic() - last_hb > 480:
                    heartbeat(f"恢复等待 train {label} job={job_id}")
                    last_hb = time.monotonic()
                st = wait_job(job_id, wait_s=120)
                st_status = st.get("status")
                if st_status in {"completed", "failed", "canceled"} or st.get("returncode") is not None:
                    entry = {
                        "label": label, "arm": arm, "seed": seed,
                        "wall_s": round(time.monotonic() - t0, 2),
                        "recovered": True,
                        **summarize(st),
                    }
                    # avoid duplicate label
                    state["trains"] = [t for t in state["trains"] if t.get("label") != label]
                    state["trains"].append(entry)
                    save(state)
                    heartbeat(f"恢复 train {label} 结束 status={st_status} rc={st.get('returncode')}")
                    return  # run_trains will continue with remaining
                if time.monotonic() - t0 > 1500:
                    return
        return  # only recover the first unfinished


if __name__ == "__main__":
    sys.exit(main())
