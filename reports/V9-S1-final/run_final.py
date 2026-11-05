#!/usr/bin/env python3
"""P61: the one final-eval job via relay submit-job (tier-1 claude).  Writes reports/V9-S1-final/ only."""
import json, subprocess, time
from datetime import datetime
from pathlib import Path
AGENT, TASK = "claude", "ainerzero.V9.P61"
DOC_SHA = "ad21071ec11d3006b9d31e9ac3c0e9a48aa6a94c2efd80807549ca1681e9b60c"
CWD = "/Users/mac/AinerWorkFlow/AinerZero"
RELAY = ["python3", "/Users/mac/AinerWorkFlow/AinerRelay/bin/relay"]
HERE = Path(__file__).resolve().parent
def now(): return datetime.now().astimezone().strftime("%Y-%m-%dT%H:%M:%S%z")
def hb(msg): subprocess.run(RELAY + ["heartbeat", TASK, "--agent", AGENT, "--msg", msg[:400]], capture_output=True)
def main():
    out = {"submitted_at": now()}
    argv = [".venv/bin/python", "-m", "ainerzero.cli", "s1-phase1", "--mode", "final-eval",
            "--prereg", "artifacts/v9/s1/phase1/final/pre_registration.json", "--output-root", "artifacts/v9/s1/phase1"]
    p = subprocess.run(RELAY + ["submit-job", "--agent", AGENT, "--project", "ainerzero", "--task", TASK, "--type", "eval",
                                "--cwd", CWD, "--authorization-ref", f"ainerzero:registration/{DOC_SHA}",
                                "--idempotency-key", "s1-final-eval-once", "--gpu-class", "0", "--peak-mem", "8",
                                "--ttl", "2100", "--max-attempts", "1", "--json", "--", *argv], capture_output=True, text=True)
    if p.returncode != 0:
        out["submit_error"] = p.stderr or p.stdout; (HERE / "run_ledger.json").write_text(json.dumps(out, indent=1)); return 5
    job = json.loads(p.stdout)["id"]; out["job_id"] = job; hb(f"final-eval job {job} 已提交")
    (HERE / "run_ledger.json").write_text(json.dumps(out, indent=1))
    t0 = time.monotonic()
    while True:
        subprocess.run(RELAY + ["job-wait", "--agent", AGENT, "--wait", "60", "--json", job], capture_output=True)
        st = json.loads(subprocess.run(RELAY + ["job-status", "--agent", AGENT, "--json", job], capture_output=True, text=True).stdout)
        if st.get("status") in {"completed", "failed", "canceled"}: break
        if time.monotonic() - t0 > 2400: break
        hb(f"final-eval 运行中（{int(time.monotonic() - t0)}s）")
    out.update({"status": st.get("status"), "returncode": st.get("returncode"), "started_at": st.get("started_at"),
                "ended_at": st.get("ended_at"), "group_empty": st.get("group_empty"),
                "stdout_path": ((st.get("logs") or {}).get("stdout") or {}).get("path"), "finished_at": now()})
    (HERE / "run_ledger.json").write_text(json.dumps(out, indent=1)); hb(f"final-eval 结束：{st.get('status')} rc={st.get('returncode')}")
    return 0
if __name__ == "__main__": raise SystemExit(main())
