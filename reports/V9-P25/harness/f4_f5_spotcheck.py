#!/usr/bin/env python3
"""P25 spot-check F4 (single-attempt guard) and F5 (NaN contract).

Reuses the pinned P24 probe_core cases as-is (read-only import of
reports/V9-P24/harness/probe_core.py which is in must_be_unchanged).
Does not call author test_s1_r9_* assertions.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

REPO = Path("/Users/mac/AinerWorkFlow/AinerZero")
LOGS = REPO / "reports/V9-P25/logs"
CORE = REPO / "reports/V9-P24/harness/probe_core.py"

spec = importlib.util.spec_from_file_location("p24_probe_core", CORE)
mod = importlib.util.module_from_spec(spec)
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "tests/v9/experiments"))
assert spec.loader is not None
spec.loader.exec_module(mod)

out = {
    "schema": "ainerzero.v9.s1.p25.f4_f5_spotcheck.v1",
    "probe_by": "composer-m7k2",
    "source": str(CORE),
    "f4": mod.case_f4(),
    "f5": mod.case_f5(),
}
out["f4_pass"] = bool(out["f4"].get("passed"))
out["f5_pass"] = bool(out["f5"].get("passed"))
out["overall_pass"] = out["f4_pass"] and out["f5_pass"]
LOGS.mkdir(parents=True, exist_ok=True)
path = LOGS / "f4-f5-spotcheck.json"
path.write_text(json.dumps(out, indent=1, sort_keys=True) + "\n")
print(f"f4_pass={out['f4_pass']} second={out['f4'].get('second_status')}/{out['f4'].get('second_refused_stage')}")
print(f"f5_pass={out['f5_pass']} nan_refused={'nan' in out['f5'].get('reserved_refusals', {})} "
      f"reserved_count={len(out['f5'].get('reserved_refusals', {}))} "
      f"ts_count={len(out['f5'].get('timestamp_refusals', {}))}")
print(f"overall_pass={out['overall_pass']}")
print(f"json -> {path}")
sys.exit(0 if out["overall_pass"] else 1)
