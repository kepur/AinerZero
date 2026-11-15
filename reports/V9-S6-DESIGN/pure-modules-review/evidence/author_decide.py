#!/usr/bin/env python3
"""P256 review, item 2: analysis.decide() on the same data as indep_gates.py.

Also checks that indep_data.my_make_data gives bit-for-bit the arrays of the test's make_data.
Usage: author_decide.py OUT_JSON BOOT_DIR"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "tests/v9/experiments"))
import indep_data as D  # noqa: E402
import test_s6_analysis as TA  # noqa: E402  (the test module: make_data)
from ainerzero.v9.experiments.s6 import analysis as AN  # noqa: E402

print("analysis from", AN.__file__)


def same(a, b):
    for t in D.TEST_SETS:
        if not (np.array_equal(a[t]["counts"], b[t]["counts"]) and np.array_equal(a[t]["eb"], b[t]["eb"])):
            return False
        if sorted(a[t]["sums"]) != sorted(b[t]["sums"]):
            return False
        if not all(np.array_equal(a[t]["sums"][k], b[t]["sums"][k]) for k in a[t]["sums"]):
            return False
    return True


def main():
    out_json, boot_dir = Path(sys.argv[1]), Path(sys.argv[2])
    result = {}
    for name, cfg in D.CONFIGS.items():
        data = D.build(cfg)
        if cfg["kind"] in ("make", "zero_wall"):
            ref = TA.make_data(**cfg["kw"])
            if cfg["kind"] == "zero_wall":
                ref["main6"]["counts"][:, 2] = 0
            print(f"{name}: my_make_data == test make_data (bit for bit): {same(data, ref)}")
        res = AN.decide(data, n=cfg["n"])
        boots = AN.world_bootstrap(data, n=cfg["n"], seed=AN.SEED)
        np.savez(boot_dir / f"author-{name.split()[0]}.npz", **{g: np.asarray(v, float) for g, v in boots.items()})
        result[name] = res
    out_json.write_text(json.dumps(result, indent=1, sort_keys=True, default=float), encoding="utf-8")
    print("GATES:", json.dumps({g: {k: v for k, v in s.items()} for g, s in AN.GATES.items()}))
    print("M", AN.M, "ALPHA", AN.ALPHA, "N_BOOT", AN.N_BOOT, "SEED", AN.SEED)


if __name__ == "__main__":
    main()
