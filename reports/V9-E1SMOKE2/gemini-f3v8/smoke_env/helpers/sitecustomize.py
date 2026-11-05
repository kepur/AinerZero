"""Helper sitecustomize to inject data generation counts for smoke testing."""
from __future__ import annotations
import json, os
try:
    from ainerzero.v9.experiments.e1 import worker
    _orig = worker.DefaultCellRunner.run_generate_data
    def _patched(self, data_dir, output_root, clock_fn, deadline, budget, **kwargs):
        c = os.environ.get("E1_SMOKE_COUNTS")
        if c and "counts" not in kwargs:
            kwargs["counts"] = json.loads(c)
        return _orig(self, data_dir, output_root, clock_fn, deadline, budget, **kwargs)
    worker.DefaultCellRunner.run_generate_data = _patched
except ImportError:
    pass
