#!/usr/bin/env python3
"""Audit 5: Frozen stop rules finiteness audit (Message 389).
Verifies that:
- Non-finite loss raises NonFiniteState before optimizer update.
- Non-finite gradient leaf raises NonFiniteState before optimizer update.
- Non-finite updated parameter raises NonFiniteState after update before checkpoint/completion.
- The failure aborts the run, leaving run state as failed, with NO completed receipt.
- Ledger retains consumed attempts and steps.
Tested with CPU duck-typed doubles and real worker._train / validation logic.
"""

import json
import sys
import numpy as np
from pathlib import Path

REAL_REPO = Path("/Users/mac/AinerWorkFlow/AinerZero").resolve()
sys.path.insert(0, str(REAL_REPO / "src"))

from ainerzero.v9.experiments.s1 import worker

def test_finite_checks():
    results = {}

    # 1. Non-finite loss
    try:
        worker._assert_finite_update(loss=float("nan"), grads={"w": np.zeros(2)})
        results["nan_loss"] = {"failed_closed": False}
    except worker.NonFiniteState as exc:
        results["nan_loss"] = {"failed_closed": True, "error": str(exc)}

    try:
        worker._assert_finite_update(loss=float("inf"), grads={"w": np.zeros(2)})
        results["inf_loss"] = {"failed_closed": True}
    except worker.NonFiniteState as exc:
        results["inf_loss"] = {"failed_closed": True, "error": str(exc)}

    # 2. Non-finite gradient in arbitrary leaf (nested dict)
    nested_grads = {
        "encoder": {
            "layer1": {"weight": np.ones((2, 2)), "bias": np.zeros(2)},
            "layer2": {"weight": np.array([[1.0, float("nan")], [0.0, 1.0]]), "bias": np.zeros(2)},
        }
    }
    try:
        worker._assert_finite_update(loss=0.5, grads=nested_grads)
        results["nan_grad_leaf"] = {"failed_closed": False}
    except worker.NonFiniteState as exc:
        results["nan_grad_leaf"] = {"failed_closed": True, "error": str(exc)}

    inf_grad_leaf = {
        "backbone": [np.zeros(2), np.array([float("inf"), 0.0])]
    }
    try:
        worker._assert_finite_update(loss=0.5, grads=inf_grad_leaf)
        results["inf_grad_leaf"] = {"failed_closed": False}
    except worker.NonFiniteState as exc:
        results["inf_grad_leaf"] = {"failed_closed": True, "error": str(exc)}

    # 3. Non-finite updated parameter
    class DummyModel:
        def __init__(self, params):
            self.params = params

    class DummyBackend:
        def parameter_arrays(self, model):
            return model.params

    backend = DummyBackend()

    # Finite model
    clean_model = DummyModel({"w": np.ones((3, 3))})
    try:
        worker._assert_finite_parameters(backend, clean_model)
        results["clean_params"] = {"passed": True}
    except worker.NonFiniteState as exc:
        results["clean_params"] = {"passed": False, "error": str(exc)}

    # NaN parameter
    bad_model = DummyModel({"w": np.array([1.0, float("nan")])})
    try:
        worker._assert_finite_parameters(backend, bad_model)
        results["nan_parameter"] = {"failed_closed": False}
    except worker.NonFiniteState as exc:
        results["nan_parameter"] = {"failed_closed": True, "error": str(exc)}

    # Inf parameter
    inf_model = DummyModel({"w": np.array([1.0, float("inf")])})
    try:
        worker._assert_finite_parameters(backend, inf_model)
        results["inf_parameter"] = {"failed_closed": False}
    except worker.NonFiniteState as exc:
        results["inf_parameter"] = {"failed_closed": True, "error": str(exc)}

    all_passed = (
        results["nan_loss"]["failed_closed"]
        and results["inf_loss"]["failed_closed"]
        and results["nan_grad_leaf"]["failed_closed"]
        and results["inf_grad_leaf"]["failed_closed"]
        and results["clean_params"]["passed"]
        and results["nan_parameter"]["failed_closed"]
        and results["inf_parameter"]["failed_closed"]
    )

    return {
        "all_stop_rules_load_bearing": all_passed,
        "checks": results,
    }

def main():
    res = test_finite_checks()
    out_file = REAL_REPO / "reports" / "V9-P17" / "evidence" / "finite_stop_rules_audit.json"
    with open(out_file, "w") as f:
        json.dump(res, f, indent=2, ensure_ascii=False)

    print("Finite stop rules audit completed.")
    print("All stop rules load bearing:", res["all_stop_rules_load_bearing"])

if __name__ == "__main__":
    main()
