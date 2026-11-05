"""V9.P11 reviewer harness: exit-code contract at the real CLI (sandbox tree).

P9 r2 changed two externally visible contracts (lock busy 1 -> 4, duty line now
reachable) and kept "the CLI can only tighten".  This re-checks the four cheap
refusals through ``python -m ainerzero.cli s1-phase1`` inside the sandbox copy;
none of them reaches model work, so no MLX run and no real lock is involved.
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

REAL = Path("/Users/mac/AinerWorkFlow/AinerZero")
SANDBOX = Path("/private/tmp/v9p11/sandbox")
PY = str(REAL / ".venv-ainerzero" / "bin" / "python")
OUT = REAL / "reports" / "V-V9-P9" / "r2" / "evidence"
LIMITS = {
    "process_memory_gib": 8.0, "mlx_memory_gib": 4.0, "system_reserve_gib": 16.0,
    "swap_growth_gib": 1.0, "training_duty_cycle": 0.25, "disk_min_free_gib": 50.0,
}


def run(args, cwd=SANDBOX, env_extra=None):
    env = {"PATH": "/usr/bin:/bin:/usr/sbin:/sbin", "PYTHONPATH": str(cwd / "src"),
           "PYTHONDONTWRITEBYTECODE": "1", "HOME": "/private/tmp/v9p11"}
    env.update(env_extra or {})
    proc = subprocess.run([PY, "-m", "ainerzero.cli", "s1-phase1", *args], cwd=str(cwd),
                          capture_output=True, text=True, timeout=300, env=env)
    try:
        report = json.loads(proc.stdout)
    except json.JSONDecodeError:
        report = {"unparsed": proc.stdout[-800:]}
    return {"args": args, "exit_code": proc.returncode, "status": report.get("status"),
            "stage": report.get("stage"), "error": report.get("error"),
            "reasons": report.get("reasons")}


def main() -> int:
    root = SANDBOX / "artifacts" / "v9" / "s1" / "phase1"
    tmp = Path("/private/tmp/v9p11/refusals")
    tmp.mkdir(parents=True, exist_ok=True)

    def limits_file(name, **overrides):
        payload = dict(LIMITS, **overrides)
        path = tmp / name
        path.write_text(json.dumps(payload), encoding="utf-8")
        return path

    cases = []
    cases.append(run(["--mode", "smoke", "--output-root", str(root),
                      "--limits-file", str(limits_file("tight-mem.json", process_memory_gib=0.01))]))
    cases[-1]["id"] = "R1 收紧进程内存 0.01 GiB"
    cases[-1]["expect"] = "exit 2 process_memory_limit"
    cases.append(run(["--mode", "smoke", "--output-root", str(root),
                      "--limits-file", str(limits_file("loose-mem.json", process_memory_gib=16.0))]))
    cases[-1]["id"] = "R2 放宽进程内存 16 GiB"
    cases[-1]["expect"] = "exit 2 loosening refused"
    cases.append(run(["--mode", "smoke", "--output-root", str(root),
                      "--limits-file", str(limits_file("loose-duty.json", training_duty_cycle=1.0))]))
    cases[-1]["id"] = "R3 放宽占空比 1.0"
    cases[-1]["expect"] = "exit 2 duty loosening refused"
    cases.append(run(["--mode", "smoke", "--output-root", str(root), "--wall-budget-seconds", "99999"]))
    cases[-1]["id"] = "R4 墙钟预算 99999（只能收紧）"
    cases[-1]["expect"] = "exit 1 tighten-only"

    # R5: another process holds the sandbox shared lock -> exit 4 (r2 changed this from 1)
    holder = subprocess.Popen(
        [PY, "-c",
         "import fcntl,time,pathlib\n"
         f"p=pathlib.Path({str(SANDBOX / 'artifacts/locks/m0-worker.lock')!r})\n"
         "p.parent.mkdir(parents=True,exist_ok=True)\n"
         "h=p.open('a+')\n"
         "fcntl.flock(h,fcntl.LOCK_EX)\n"
         "print('held',flush=True)\n"
         "time.sleep(25)\n"],
        stdout=subprocess.PIPE, text=True,
    )
    assert holder.stdout.readline().strip() == "held"
    try:
        time.sleep(0.2)
        cases.append(run(["--mode", "smoke", "--output-root", str(root)]))
        cases[-1]["id"] = "R5 另一进程持沙箱共享锁"
        cases[-1]["expect"] = "exit 4 lock_busy"
    finally:
        holder.kill()
        holder.wait(timeout=10)

    cases.append(run(["--mode", "train", "--output-root", str(root),
                      "--prereg", str(root / "pre_registration.json"),
                      "--research-log", str(SANDBOX / "RESEARCH_LOG.md")]))
    cases[-1]["id"] = "R6 未批准 train（sandbox 日志无批准行）"
    cases[-1]["expect"] = "exit 3 preregistration_not_approved"

    payload = {"harness": "reports/V-V9-P9/r2/harness/refusals.py", "sandbox": str(SANDBOX),
               "lock_path": str(SANDBOX / "artifacts/locks/m0-worker.lock"), "cases": cases}
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "cli-refusals.json").write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    for case in cases:
        print(f"{case['id']}: exit={case['exit_code']} stage={case['stage']} expect={case['expect']}")
        if case.get("reasons"):
            print("   ", str(case["reasons"])[:160])
        if case.get("error"):
            print("   ", str(case["error"])[:160])
    return 0


if __name__ == "__main__":
    sys.exit(main())
