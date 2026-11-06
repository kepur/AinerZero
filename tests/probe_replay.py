"""Replay a delivered evidence probe without letting it write beside the evidence.

COORDINATION rule 8: a re-run must not rewrite delivered evidence.  The delivered
``artifacts/reports/*/source-full-chain/probe.py`` scripts write ``probe-log.json`` next
to themselves, but only in their ``__main__`` block.  This helper leaves the scripts
untouched: a fresh interpreter (so ``mlx_loaded`` reflects the probe alone) loads the
script under a non-``__main__`` name, points its read-only ledger at a byte copy (so not
even SQLite's ``-shm`` index is touched in place), calls ``run_chain()`` and writes the
log in the probe's own format into a temporary directory.  Callers then compare that
file byte for byte with the delivered ``probe-log.json``.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

_DRIVER = r"""
import importlib.util, json, shutil, sys
from pathlib import Path

script, out, ledger_dir = (Path(arg) for arg in sys.argv[1:4])
spec = importlib.util.spec_from_file_location("_replayed_evidence_probe", script)
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)  # not __main__: the probe's own writer block does not run
copy = ledger_dir / probe.LEDGER.name
shutil.copyfile(probe.LEDGER, copy)
wal = probe.LEDGER.with_name(probe.LEDGER.name + "-wal")
if wal.exists():
    shutil.copyfile(wal, copy.with_name(copy.name + "-wal"))
probe.LEDGER = copy
result = probe.run_chain()
out.write_text(json.dumps(result, indent=2) + "\n")  # the probe's own serialization
"""


def replay_probe(script: Path, tmp_path: Path, *, timeout: int = 600):
    """Run ``script``'s ``run_chain()`` and write its log to ``tmp_path/probe-log.json``."""
    out = tmp_path / "probe-log.json"
    ledger_dir = tmp_path / "ledger-copy"
    ledger_dir.mkdir()
    try:
        proc = subprocess.run(
            [sys.executable, "-P", "-c", _DRIVER, str(script), str(out), str(ledger_dir)],
            cwd=ROOT, capture_output=True, text=True, timeout=timeout,
        )
    finally:
        shutil.rmtree(ledger_dir, ignore_errors=True)
    return proc, out
