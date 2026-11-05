"""P21 probe 08: the arm1 (D candidate) evaluation path.

Cases (CPU only, no MLX runtime, no model forward):

A. the D path with the *real* frozen r7 document and the registered eval
   budget (300 s, the CLI default);
B. the same with a tightened budget (2 s = the document's arm1_deadline_seconds);
C. control: a document whose arm1 deadline allows the run budget (the shape the
   project's own r7 test fixture uses) -- the D path then completes with one CPU
   forward substitute and every S1-incomparable metric is ``not_applicable``;
D. a *second* arm1 evaluation after C -- the registered "one D evaluation run"
   limit must refuse it;
E. arm2 evaluation -- must still fail closed on the registered 48-batch budget
   without opening a run and without any forward;
F. the CPU forward substitute may not stand in for the identity check.

``arms.py`` imports ``mlx.core``/``mlx.nn`` at module level, so a stub ``mlx``
package is installed first (p21lib.install_mlx_stub): no MLX runtime is loaded.
"""

from __future__ import annotations

import contextlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(lib_tests := Path("/Users/mac/AinerWorkFlow/AinerZero/tests/v9/experiments")))

import p21lib as lib  # noqa: E402

stub = lib.install_mlx_stub()

from p03_entry_path import isolated_host  # noqa: E402

from ainerzero.v9.experiments.s1 import arms, prereg, resource_gate, spec, worker  # noqa: E402

R7_PREREG = lib.REPO / "artifacts/v9/s1/phase1/r7/pre_registration.json"
EVAL_BUDGET = 300.0  # commands.PREP_BUDGET["eval"], the registered eval budget


class SubstituteBackend:
    """A CPU stand-in for the D candidate forward (no MLX, no model)."""

    name = "p21-cpu-substitute"

    def __init__(self) -> None:
        self.forward_calls = 0

    def eval_d_candidate(self, seed: int = 0):
        self.forward_calls += 1
        return type(
            "Out",
            (),
            {
                "metrics": {
                    "symbol_nll_t0": 1.25,
                    "symbol_nll_t1": 1.5,
                    "observation_loss_t0": 0.5,
                    "observation_loss_t1": 0.75,
                }
            },
        )()

    d_candidate_info = {
        "parameter_count": 393_232,
        "parameter_sha256": spec.ARM_SPECS["arm1"]["identity"]["tensors_sha256"],
    }


@contextlib.contextmanager
def no_mlx_probe():
    """Keep the resource gate's MLX allocator probe from importing MLX."""
    original = resource_gate.mlx_memory_probe
    resource_gate.mlx_memory_probe = lambda: {
        "available": False,
        "active_bytes": 0.0,
        "peak_bytes": 0.0,
        "error": "p21 probe: MLX runtime not loaded (CPU review)",
    }
    try:
        yield
    finally:
        resource_gate.mlx_memory_probe = original


def write_synthetic_document(root: Path) -> tuple[Path, str]:
    """The project's own r7 test fixture document (arm1 deadline 15 s)."""
    from s1_testkit import write_frozen

    path, digest, _document = write_frozen(root / "pre_registration.json")
    return path, digest


def main() -> int:
    document = json.loads(R7_PREREG.read_text(encoding="utf-8"))
    document_sha = prereg.document_sha256(document)
    scratch = lib.scratch_dir("p21-d-eval")
    cases = {}

    def run_eval(host, *, budget, prereg_path, arm, backend, seed=0):
        with no_mlx_probe():
            return worker.run_worker(
                "eval",
                output_root=host["phase1"],
                limits=dict(spec.RESOURCE_LIMITS),
                wall_budget_seconds=budget,
                prereg_path=prereg_path,
                arm=arm,
                seed=seed,
                backend=backend,
            )

    # --- A/B: the real frozen r7 document ----------------------------------
    with isolated_host(
        scratch / "real", approval=True, document_sha=document_sha, seed_attempts_=False
    ) as host:
        backend = SubstituteBackend()
        case_a = run_eval(
            host, budget=EVAL_BUDGET, prereg_path=R7_PREREG, arm="arm1", backend=backend
        )
        cases["A_real_document_default_budget"] = {
            "status": case_a.get("status"),
            "refused_stage": case_a.get("refused_stage"),
            "error": case_a.get("error"),
            "forward_calls": backend.forward_calls,
            "run_opened": bool(case_a.get("run_id")),
            "arm1_deadline_seconds": document["timing"]["arm1_deadline_seconds"],
            "eval_budget_seconds": EVAL_BUDGET,
        }
        backend_b = SubstituteBackend()
        case_b = run_eval(
            host, budget=2.0, prereg_path=R7_PREREG, arm="arm1", backend=backend_b
        )
        cases["B_real_document_tightened_budget"] = {
            "status": case_b.get("status"),
            "refused_stage": case_b.get("refused_stage"),
            "error": case_b.get("error"),
            "forward_calls": backend_b.forward_calls,
            "run_opened": bool(case_b.get("run_id")),
        }

    # --- C/D: a document whose arm1 deadline allows the run budget ---------
    with isolated_host(
        scratch / "synthetic", approval=True, document_sha=document_sha, seed_attempts_=False
    ) as host:
        synthetic_path, synthetic_sha = write_synthetic_document(host["phase1"])
        synthetic_doc = json.loads(synthetic_path.read_text(encoding="utf-8"))
        backend_c = SubstituteBackend()
        case_c = run_eval(
            host, budget=10.0, prereg_path=synthetic_path, arm="arm1", backend=backend_c
        )
        details = case_c.get("eval_details") or {}
        not_applicable = {
            key: (details.get(key) or {}).get("status")
            for key in (
                "localization_error",
                "unseen_map_generalization",
                "topology_recovery",
                "few_shot_unseen_transition",
                "sample_efficiency",
                "m2_memory_interference",
            )
        }
        from ainerzero.runtime.lifecycle import RunStore

        with RunStore(host["ledger"]) as store:
            runs = [
                {
                    "run_id": run.run_id,
                    "state": run.state,
                    "purpose": (run.config_snapshot or {}).get("purpose"),
                    "arm_id": (run.config_snapshot or {}).get("arm_id"),
                    "seed": (run.config_snapshot or {}).get("seed"),
                    "request_id": run.request_id,
                }
                for run in store.list_runs()
            ]
        cases["C_synthetic_document_control"] = {
            "status": case_c.get("status"),
            "error": case_c.get("error"),
            "forward_calls": backend_c.forward_calls,
            "run_opened": bool(case_c.get("run_id")),
            "synthetic_arm1_deadline_seconds": synthetic_doc["timing"][
                "arm1_deadline_seconds"
            ],
            "not_applicable_status": not_applicable,
            "forward_substitute": details.get("forward_substitute"),
            "d_candidate_identity": case_c.get("d_candidate_identity"),
            "ledger_runs": runs,
        }
        # --- D: the second arm1 evaluation -------------------------------
        backend_d = SubstituteBackend()
        case_d = run_eval(
            host, budget=10.0, prereg_path=synthetic_path, arm="arm1", backend=backend_d
        )
        with RunStore(host["ledger"]) as store:
            runs_after = [
                {
                    "run_id": run.run_id,
                    "state": run.state,
                    "purpose": (run.config_snapshot or {}).get("purpose"),
                    "arm_id": (run.config_snapshot or {}).get("arm_id"),
                }
                for run in store.list_runs()
            ]
        cases["D_second_arm1_evaluation"] = {
            "status": case_d.get("status"),
            "refused_stage": case_d.get("refused_stage"),
            "error": case_d.get("error"),
            "forward_calls": backend_d.forward_calls,
            "run_opened": bool(case_d.get("run_id")),
            "ledger_runs_after": runs_after,
        }
        # --- E: arm2 must still fail closed on the 48-batch budget -------
        backend_e = SubstituteBackend()
        case_e = run_eval(
            host, budget=10.0, prereg_path=synthetic_path, arm="arm2", backend=backend_e
        )
        cases["E_arm2_evaluation"] = {
            "status": case_e.get("status"),
            "refused_stage": case_e.get("refused_stage"),
            "call_plan": case_e.get("eval_call_plan"),
            "forward_calls": backend_e.forward_calls,
            "run_opened": bool(case_e.get("run_id")),
        }
        # --- F: the substitute may not stand in for the identity check ---
        original_verify = arms.verify_d_candidate_identity

        def _failing_verify(repo_root=None):
            raise RuntimeError("p21 control: the A2-pinned file changed")

        arms.verify_d_candidate_identity = _failing_verify
        backend_f = SubstituteBackend()
        try:
            case_f = run_eval(
                host, budget=10.0, prereg_path=synthetic_path, arm="arm1", backend=backend_f
            )
        finally:
            arms.verify_d_candidate_identity = original_verify
        cases["F_identity_control"] = {
            "status": case_f.get("status"),
            "refused_stage": case_f.get("refused_stage"),
            "error": case_f.get("error"),
            "forward_calls": backend_f.forward_calls,
            "run_opened": bool(case_f.get("run_id")),
        }

    payload = {
        "schema": "ainerzero.v9.p21.probe08_d_eval_path.v1",
        "mlx_stub": stub,
        "real_mlx_loaded": lib.real_mlx_loaded(),
        "cases": cases,
        "frozen_document_sha256": document_sha,
        "registered_eval_batches": int(document["training_protocol"]["eval_batches"]),
        "registered_d_candidate_eval_runs": int(spec.TIMING["d_candidate_eval_runs"]),
        "mlx_imported": lib.mlx_imported(),
    }
    payload["verdict"] = {
        "real_document_default_budget_completes": cases["A_real_document_default_budget"][
            "status"
        ]
        == "completed",
        "real_document_tightened_budget_completes": cases[
            "B_real_document_tightened_budget"
        ]["status"]
        == "completed",
        "control_document_completes": cases["C_synthetic_document_control"]["status"]
        == "completed",
        "control_used_exactly_one_forward": cases["C_synthetic_document_control"][
            "forward_calls"
        ]
        == 1,
        "second_arm1_evaluation_refused": cases["D_second_arm1_evaluation"]["refused_stage"]
        == "already_attempted",
        "arm2_eval_fails_closed_on_the_budget": cases["E_arm2_evaluation"]["refused_stage"]
        == "eval_call_budget_exceeded",
        "arm2_eval_opened_no_run": not cases["E_arm2_evaluation"]["run_opened"],
        "arm2_eval_ran_no_forward": cases["E_arm2_evaluation"]["forward_calls"] == 0,
        "identity_failure_refuses_before_any_forward": (
            cases["F_identity_control"]["refused_stage"]
            == "arm1_identity_verification_failed"
            and cases["F_identity_control"]["forward_calls"] == 0
        ),
        "identity_failure_opened_no_run": not cases["F_identity_control"]["run_opened"],
        "s1_incomparable_metrics_not_applicable": all(
            value == "not_applicable" for value in cases["C_synthetic_document_control"][
                "not_applicable_status"
            ].values()
        ),
        "no_real_mlx_loaded": not lib.real_mlx_loaded(),
    }
    out = lib.write_json("08-d-eval-path.json", payload)
    print(json.dumps(payload["verdict"], indent=1))
    print(json.dumps(cases["A_real_document_default_budget"], indent=1))
    print(json.dumps(cases["B_real_document_tightened_budget"], indent=1))
    print(json.dumps(cases["D_second_arm1_evaluation"], indent=1))
    print("wrote", out)
    return 0 if all(payload["verdict"].values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
