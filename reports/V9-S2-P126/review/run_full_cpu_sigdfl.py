#!/usr/bin/env python3
"""P127 reviewer: full pure-CPU pytest via SIG_DFL + os.execv (no subprocess wrapper)."""
from __future__ import annotations
import os
import signal
import sys
from pathlib import Path

REPO = Path("/Users/mac/AinerWorkFlow/AinerZero").resolve()
os.chdir(REPO)
for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGPIPE, signal.SIGHUP):
    try:
        signal.signal(sig, signal.SIG_DFL)
    except Exception:
        pass

py = str(REPO / ".venv/bin/python")
log = REPO / "reports/V9-S2-P126/review/pytest_full_p127.log"
# Redirect stdout/stderr to log while still using execv: open fd and dup
fd = os.open(str(log), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o644)
os.dup2(fd, 1)
os.dup2(fd, 2)
os.close(fd)
os.execv(py, [py, "-m", "pytest", "-q", "--tb=no"])
