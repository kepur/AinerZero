import json, sys, traceback, time
from pathlib import Path
import numpy as np
sys.path.insert(0, "/Users/mac/AinerWorkFlow/AinerZero/src")
from ainerzero.v9.experiments.s1 import prereg, spec, worker, evaluation, arms
host = Path(sys.argv[1]); root = host / "artifacts/v9/s1/phase1"
spec.REGISTERED_HOST_ROOT = host; spec.PHASE1_ROOT = root
worker.canonical_ledger_path = lambda *a, **k: root / "control.sqlite3"
doc = json.loads((root / "r14/pre_registration.json").read_text())
sha = prereg.document_sha256(doc)

def place_slice(model, h):
    h = np.asarray(h)
    if isinstance(model, arms.MetricPlusTopologyArm):
        return h[model.channels: model.channels + model.place_dim]
    if isinstance(model, arms.EpisodicTopologyArm):
        return h[: model.place_dim]
    ch = int(model.dims.get("memory_channels", h.shape[-1]))
    return h[:ch]

class PlaceBackend:
    def __init__(self, inner): self.inner = inner
    def __getattr__(self, k): return getattr(self.inner, k)
    def encode(self, model, obs_row): return place_slice(model, self.inner.encode(model, obs_row))

orig = evaluation.few_shot_report
evaluation.few_shot_report = lambda backend, model, *a, **k: orig(PlaceBackend(backend), model, *a, **k)
for arm, seed in [(a, int(s)) for a, s in (x.split(":") for x in sys.argv[2:])]:
    t0 = time.time()
    try:
        out = worker._evaluate_arm(doc, root, arm_id=arm, seed=seed, prereg_sha256=sha)
        print(arm, seed, "OK", out.get("status"), f"{time.time()-t0:.1f}s", "inherited=", (out.get("run_binding") or {}).get("inherited") is not None)
    except Exception:
        print(arm, seed, "FAIL", f"{time.time()-t0:.1f}s"); traceback.print_exc(limit=6)
