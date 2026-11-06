#!/usr/bin/env python3
"""Run foreground pure-CPU pytest regression for P119 review."""

from __future__ import annotations

import os
import signal
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
LOG_FILE = ROOT / "reports/V9-S2-P118/review/pytest_full.log"

env = os.environ.copy()
env["PYTHONPATH"] = f"{ROOT}:{ROOT / 'src'}"
env["PYTHONDONTWRITEBYTECODE"] = "1"

venv_pytest = ROOT / ".venv" / "bin" / "pytest"
pytest_cmd = [str(venv_pytest) if venv_pytest.exists() else sys.executable, "-m", "pytest"] if not venv_pytest.exists() else [str(venv_pytest)]

print(f"Running pytest cmd: {pytest_cmd}")

with open(LOG_FILE, "w", encoding="utf-8") as f:
    proc = subprocess.Popen(
        pytest_cmd,
        cwd=ROOT,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        preexec_fn=lambda: signal.signal(signal.SIGINT, signal.SIG_DFL),
    )
    for line in proc.stdout:
        sys.stdout.write(line)
        f.write(line)
    proc.wait()

print(f"Finished with exit code: {proc.returncode}")
sys.exit(proc.returncode)
