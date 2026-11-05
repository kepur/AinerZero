import json, sys, traceback
from pathlib import Path
sys.path.insert(0, "/Users/mac/AinerWorkFlow/AinerZero/src")
from ainerzero.v9.experiments.s1 import prereg, spec, worker
host = Path(sys.argv[1]); root = host / "artifacts/v9/s1/phase1"
spec.REGISTERED_HOST_ROOT = host; spec.PHASE1_ROOT = root
worker.canonical_ledger_path = lambda *a, **k: root / "control.sqlite3"
doc = json.loads((root / "r14/pre_registration.json").read_text())
sha = prereg.document_sha256(doc)
arm, seed = sys.argv[2], int(sys.argv[3])
try:
    out = worker._evaluate_arm(doc, root, arm_id=arm, seed=seed, prereg_sha256=sha)
    print("OK", out.get("status"))
except Exception:
    traceback.print_exc()
