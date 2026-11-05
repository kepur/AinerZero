"""P21 probe 11: the frozen non-finite stop rule still holds (r6 regression).

The frozen stop rules say that a non-finite loss, a non-finite gradient leaf
or a non-finite parameter aborts the run as failed.  The probe drives the real
``worker._train`` with a CPU substitute that injects the fault, at the first
update and at the last update, and checks that no run is completed and no
completion receipt is written.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))

import p21lib as lib  # noqa: E402
import p09_train_flow as p9  # noqa: E402

from ainerzero.v9.experiments.s1 import worker  # noqa: E402


class FaultyBackend(p9.SubstituteBackend):
    """A substitute that injects one non-finite value at a chosen update."""

    def __init__(self, *, kind: str, at_update: int) -> None:
        super().__init__()
        self.kind = kind
        self.at_update = int(at_update)
        self.non_finite_parameters = False

    def value_and_grad(self, model):
        apply = super().value_and_grad(model)

        def apply2(m, batch):
            self.value_and_grad_calls += 1
            m.params["w"] = np.asarray(m.params["w"], dtype=np.float32) + 1.0
            loss = np.float32(0.5)
            grads = {"w": np.zeros((1, 1), dtype=np.float32)}
            if self.value_and_grad_calls == self.at_update:
                if self.kind == "loss":
                    loss = np.float32("nan")
                elif self.kind == "gradient":
                    grads = {"w": np.full((1, 1), np.nan, dtype=np.float32)}
            return (loss, {}), grads

        return apply2

    def sync_parameters(self, model, optimizer):
        if self.kind == "parameters" and self.value_and_grad_calls == self.at_update:
            model.params["w"] = np.full((1, 1), np.nan, dtype=np.float32)
        return None


def run_case(kind: str, at_update: int, *, updates: int = 4) -> dict:
    root = p9.fresh_root(f"p21-nonfinite-{kind}-{at_update}-")
    doc = p9.document(updates=updates, checkpoints=[updates], deadline=20.0)
    ledger, run_id = p9.open_train_run(root, doc)
    backend = FaultyBackend(kind=kind, at_update=at_update)
    outcome = {"kind": kind, "at_update": at_update}
    try:
        details = worker._train(
            doc,
            root,
            ledger,
            run_id,
            p9.Guard(),
            arm_id="arm2",
            seed=0,
            prereg_sha256=p9.PREREG_SHA,
            backend=backend,
        )
        outcome["status"] = details["status"]
    except worker.NonFiniteState as exc:
        outcome["status"] = "aborted"
        outcome["error"] = f"{type(exc).__name__}: {exc}"
    except Exception as exc:  # noqa: BLE001
        outcome["status"] = "aborted"
        outcome["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        ledger.close()
    outcome["receipt_written"] = (root / "runs" / run_id / "completion.json").exists()
    outcome["run_dir_files"] = sorted(
        str(path.relative_to(root / "runs" / run_id))
        for path in (root / "runs" / run_id).rglob("*")
        if path.is_file()
    )
    return outcome


def main() -> int:
    cases = []
    for kind in ("loss", "gradient", "parameters"):
        for at_update in (1, 4):
            cases.append(run_case(kind, at_update))
    control = run_case("none", 1)  # the fault never fires -> the run completes
    payload = {
        "schema": "ainerzero.v9.p21.probe11_nonfinite_stop_rule.v1",
        "cases": cases,
        "control": control,
        "mlx_imported": lib.mlx_imported(),
        "real_mlx_loaded": lib.real_mlx_loaded(),
    }
    payload["verdict"] = {
        "every_fault_aborts_the_run": all(
            case["status"] != "completed" for case in cases
        ),
        "no_receipt_after_a_fault": all(not case["receipt_written"] for case in cases),
        "control_completes": control["status"] == "completed",
        "control_writes_a_receipt": control["receipt_written"],
        "no_real_mlx_loaded": not lib.real_mlx_loaded(),
    }
    out = lib.write_json("11-nonfinite-stop-rule.json", payload)
    print(json.dumps(payload["verdict"], indent=1))
    for case in cases:
        print(case["kind"], case["at_update"], "->", case["status"], "|", case.get("error"))
    print("wrote", out)
    return 0 if all(payload["verdict"].values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
