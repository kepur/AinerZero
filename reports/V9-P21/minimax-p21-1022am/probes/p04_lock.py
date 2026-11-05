"""P21 probe 04: the shared m0-worker lock is one lock for every checkout.

Two CPU subprocesses are started from two *different real source checkouts*.
The first one takes the lock that the product resolves from the registered host
anchor; the second one must be refused (``WorkerLockBusy``) and must report the
same lock path.  No model work, no ledger write; the lock file is opened
``a+`` and stays byte-identical.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import p21lib as lib  # noqa: E402

HOLD_SCRIPT = (
    "import json,sys,time,pathlib;"
    "from ainerzero.cli import worker_lock;"
    "from ainerzero.v9.experiments.s1 import commands;"
    "lock=commands._lock_path();"
    "ready=pathlib.Path(sys.argv[1]);"
    "f=open(ready,'w');"
    "ctx=worker_lock(lock);"
    "ctx.__enter__();"
    "f.write('HELD');f.close();"
    "time.sleep(float(sys.argv[2]));"
    "ctx.__exit__(None,None,None);"
    "print(json.dumps({'held':True,'lock':str(lock)}))"
)

TRY_SCRIPT = (
    "import json,sys;"
    "from ainerzero.cli import worker_lock, WorkerLockBusy;"
    "from ainerzero.v9.experiments.s1 import commands;"
    "lock=commands._lock_path();"
    "result={'lock':str(lock)};"
    "\ntry:\n"
    "    ctx=worker_lock(lock);ctx.__enter__();ctx.__exit__(None,None,None);result['acquired']=True\n"
    "except WorkerLockBusy as exc:\n"
    "    result['acquired']=False;result['busy']=str(exc)\n"
    "print(json.dumps(result))"
)


def run(script: str, checkout: Path, *args: str) -> dict:
    env = dict(os.environ)
    env["PYTHONPATH"] = str(Path(checkout) / "src")
    proc = subprocess.run(
        [sys.executable, "-c", script, *args],
        cwd=str(checkout),
        env=env,
        capture_output=True,
        text=True,
    )
    out = {"returncode": proc.returncode, "stdout": proc.stdout.strip(), "stderr": proc.stderr.strip()[-1500:]}
    if proc.returncode == 0 and proc.stdout.strip():
        out.update(json.loads(proc.stdout.strip().splitlines()[-1]))
    return out


def main() -> int:
    scratch = lib.scratch_dir("p21-lock")
    checkout_a = lib.make_checkout(scratch / "checkout-a")
    checkout_b = lib.make_checkout(scratch / "checkout-b")
    ready = scratch / "ready"

    before = lib.host_ledger_identities()
    holder = subprocess.Popen(
        [sys.executable, "-c", HOLD_SCRIPT, str(ready), "6"],
        cwd=str(checkout_a),
        env={**os.environ, "PYTHONPATH": str(checkout_a / "src")},
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    deadline = time.time() + 20
    while not ready.exists() and time.time() < deadline:
        time.sleep(0.05)
    time.sleep(0.3)
    second = run(TRY_SCRIPT, checkout_b)
    holder_out, holder_err = holder.communicate(timeout=30)
    after = lib.host_ledger_identities()

    payload = {
        "schema": "ainerzero.v9.p21.probe04_shared_lock.v1",
        "checkout_a": str(checkout_a),
        "checkout_b": str(checkout_b),
        "holder": {
            "returncode": holder.returncode,
            "stdout": (holder_out or "").strip(),
            "stderr": (holder_err or "").strip()[-1500:],
        },
        "second_try_from_other_checkout": second,
        "lock_file_before": before["m0-worker.lock"],
        "lock_file_after": after["m0-worker.lock"],
        "lock_file_unchanged": before["m0-worker.lock"] == after["m0-worker.lock"],
        "real_lock_path": str(lib.REPO / "artifacts/locks/m0-worker.lock"),
        "mlx_imported": lib.mlx_imported(),
    }
    payload["verdict"] = {
        "second_checkout_refused_while_locked": second.get("acquired") is False,
        "both_used_the_registered_lock": (
            second.get("lock") == payload["real_lock_path"]
            and payload["real_lock_path"] in (holder_out or "")
        ),
        "lock_file_byte_identical": payload["lock_file_unchanged"],
    }
    out = lib.write_json("04-shared-lock.json", payload)
    print(json.dumps(payload["verdict"], indent=1))
    print(json.dumps(second, indent=1))
    print("wrote", out)
    return 0 if all(payload["verdict"].values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
