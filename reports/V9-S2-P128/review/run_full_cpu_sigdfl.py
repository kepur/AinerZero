#!/usr/bin/env python3
import os, signal
from pathlib import Path
REPO = Path('/Users/mac/AinerWorkFlow/AinerZero').resolve()
os.chdir(REPO)
for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGPIPE, signal.SIGHUP):
    try: signal.signal(sig, signal.SIG_DFL)
    except Exception: pass
py = str(REPO/'.venv/bin/python')
log = REPO/'reports/V9-S2-P128/review/pytest_full_p129.log'
fd = os.open(str(log), os.O_WRONLY|os.O_CREAT|os.O_TRUNC, 0o644)
os.dup2(fd,1); os.dup2(fd,2); os.close(fd)
# default collection; do NOT pass --native-mlx
os.execv(py, [py, '-m', 'pytest', '-q', '--tb=no'])
