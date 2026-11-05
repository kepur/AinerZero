"""Reproduce P18 r2's two analysis scripts in an isolated P20 output dir.

The originals are read-only.  build_r2_metrics.py has a hard-coded OUT path,
so this runner imports it and rebinds module.OUT before calling main(); no
original file is edited and nothing is written under reports/V9-P18/.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
from pathlib import Path

REPO = Path("/Users/mac/AinerWorkFlow/AinerZero")
SRC = REPO / "reports/V9-P18/r2/analysis"
OUT = REPO / "reports/V9-P20/workbuddy-q7t2/analysis/repro"
OUT.mkdir(parents=True, exist_ok=True)


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    run_dir = OUT / "run"
    # truth check supports V9P18R2_OUT directly
    os.environ["V9P18R2_OUT"] = str(run_dir)
    truth = load("p20_truth", SRC / "independent_truth_check.py")
    truth.main()

    # build script: rebind OUT to the isolated dir (it reads the truth JSON there)
    build = load("p20_build", SRC / "build_r2_metrics.py")
    build.OUT = run_dir
    build.main()

    result = {
        "truth_json_sha_original": sha(REPO / "reports/V9-P18/r2/analysis/independent_truth_check.json"),
        "truth_json_sha_repro": sha(run_dir / "analysis/independent_truth_check.json"),
        "truth_byte_identical": sha(REPO / "reports/V9-P18/r2/analysis/independent_truth_check.json")
        == sha(run_dir / "analysis/independent_truth_check.json"),
        "metrics_json_sha_original": sha(REPO / "reports/V9-P18/r2/metrics.json"),
        "metrics_json_sha_repro": sha(run_dir / "metrics.json"),
        "metrics_byte_identical": sha(REPO / "reports/V9-P18/r2/metrics.json")
        == sha(run_dir / "metrics.json"),
        "input_identity_byte_identical": sha(REPO / "reports/V9-P18/r2/analysis/input_identity.json")
        == sha(run_dir / "analysis/input_identity.json"),
    }
    (OUT / "repro_summary.json").write_text(json.dumps(result, indent=2))
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
