#!/usr/bin/env python3
"""Submit this report once and preserve the exact Relay return; no --next."""
from pathlib import Path
import datetime as dt
import hashlib
import json
import subprocess
import sys

OUT=Path(__file__).resolve().parent
SUB=OUT/'submission'; SUB.mkdir(exist_ok=True)
if (SUB/'receipt.json').exists():
    raise SystemExit('Submission receipt already exists; do not silently resubmit')
argv=[sys.executable,'/Users/mac/AinerWorkFlow/AinerRelay/bin/relay','report','ainerzero.V9.P44',
      '--agent','cpu-review-p43-20261025','--result-file',str(OUT/'P44-REPORT.md'),'--data-file',str(OUT/'P44-metrics.json')]
start=dt.datetime.now(dt.timezone.utc).isoformat()
proc=subprocess.run(argv,cwd='/Users/mac/AinerWorkFlow/AinerZero',capture_output=True,timeout=60)
(SUB/'stdout').write_bytes(proc.stdout);(SUB/'stderr').write_bytes(proc.stderr)
receipt={'argv':argv,'cwd':'/Users/mac/AinerWorkFlow/AinerZero','started_at':start,
         'ended_at':dt.datetime.now(dt.timezone.utc).isoformat(),'returncode':proc.returncode,
         'stdout_path':str(SUB/'stdout'),'stderr_path':str(SUB/'stderr'),
         'stdout_sha256':hashlib.sha256(proc.stdout).hexdigest(),'stderr_sha256':hashlib.sha256(proc.stderr).hexdigest(),
         'report_sha256':hashlib.sha256((OUT/'P44-REPORT.md').read_bytes()).hexdigest(),
         'metrics_sha256':hashlib.sha256((OUT/'P44-metrics.json').read_bytes()).hexdigest(),'next_requested':False}
(SUB/'receipt.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+'\n')
sys.stdout.buffer.write(proc.stdout);sys.stderr.buffer.write(proc.stderr)
raise SystemExit(proc.returncode)
