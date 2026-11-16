"""S1 phase-1 final-partition evaluation, read once (ainerzero.V9.P59).

RESEARCH_LOG R20261028-S1-phase1-final-eval.  ``run_worker`` mode ``final-eval`` calls
:func:`preconditions` (CPU only, writes nothing), then opens one central-ledger run, then
:func:`read_once_and_score`, which creates the READ_ONCE marker, reads the sealed final dataset
through a :class:`data.FinalReadToken` and scores arm1 D plus the nine registered cells in this
one process.  A second invocation is refused before any write (marker present, or a run already
exists in the final experiment).  Development scoring is untouched.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any, Mapping

from . import data, prereg, spec

FINAL_EVAL_SCHEMA = "ainerzero.v9.s1.final_eval.v1"


def _refused(stage: str, message: str, **extra: Any) -> dict:
    return {"status": "refused", "refused_stage": stage, "message": message, **extra}


def section_reasons(document: Mapping[str, Any]) -> list[str]:
    """Structural checks of the ``final_eval`` section (prereg.validate calls this)."""
    is_final = document.get("experiment_id") == spec.FINAL_EXPERIMENT_ID
    section = document.get("final_eval")
    if not is_final:
        return [] if section is None else ["only the final evaluation document may carry a final_eval section"]
    if not isinstance(section, Mapping):
        return ["the final evaluation document must carry its final_eval section"]
    reasons = []
    digest = section.get("sealed_dataset_digest")
    if not (isinstance(digest, str) and len(digest) == 64 and all(c in "0123456789abcdef" for c in digest)):
        reasons.append("final_eval.sealed_dataset_digest must be a 64-hex SHA256")
    if section.get("wall_seconds") != spec.FINAL_EVAL_WALL_SECONDS:
        reasons.append(f"final_eval.wall_seconds must be the registered {spec.FINAL_EVAL_WALL_SECONDS}")
    counts = section.get("expected_counts")
    if not isinstance(counts, Mapping) or counts.get("final_worlds") != spec.FINAL_DATA_PLAN["worlds"]:
        reasons.append("final_eval.expected_counts must name the registered final world count")
    if section.get("data_plan") != dict(spec.FINAL_DATA_PLAN, families=list(spec.FINAL_DATA_PLAN["families"])):
        reasons.append("final_eval.data_plan differs from spec.FINAL_DATA_PLAN")
    return reasons


def preconditions(
    *,
    document: Mapping[str, Any],
    verified: Mapping[str, Any],
    output_root: Path,
    ledger_path: Path,
    research_log: Path | None,
    wall_budget_seconds: float,
) -> dict:
    """Every check that can run before the first ledger write and before the final read."""
    from . import identity as identity_module
    from . import worker as w

    if document.get("experiment_id") != spec.FINAL_EXPERIMENT_ID or section_reasons(document):
        return _refused("not_a_final_eval_document", "final-eval only runs the frozen final evaluation document",
                        problems=section_reasons(document))
    section = document["final_eval"]
    budget = float(wall_budget_seconds)
    if not 0 < budget <= float(section["wall_seconds"]):
        return _refused("final_eval_budget_invalid", f"budget {budget} outside (0, {section['wall_seconds']}]")
    canonical_log = Path(spec.RESEARCH_LOG)
    requested = Path(research_log) if research_log is not None else canonical_log
    if requested.resolve() != canonical_log.resolve():
        return _refused("research_log_not_canonical", "final-eval only reads the repository RESEARCH_LOG.md")
    approval = w._require_approval(document, verified["sha256"], research_log)
    if not approval.get("approved"):
        return _refused("preregistration_not_approved", "final-eval requires the coordinator's approval line "
                        "for this exact document SHA256", approval=approval)
    binding = prereg.source_binding_state(document)
    if binding.get("status") != "passed":
        return _refused("source_binding_drift", "bound sources drifted", source_binding=binding)
    dataset = data.dataset_binding_state(output_root, (document.get("data_identity") or {}).get("dataset_digest"))
    if dataset.get("status") != "passed":
        return _refused("dataset_identity_mismatch", "the train/development dataset no longer matches", dataset=dataset)
    sealed_dir = spec.FINAL_SEALED_ROOT / section["sealed_dataset_digest"]
    seal = data.verify_sealed_final(sealed_dir, expected_digest=section["sealed_dataset_digest"])
    if seal.get("status") != "passed":
        return _refused("final_seal_invalid", "the sealed final dataset failed verification", seal=seal)
    if seal.get("already_read"):
        return _refused("final_already_read", "the sealed final dataset has already been read once", seal=seal)
    if dict(seal.get("counts") or {}) != dict(section["expected_counts"]):
        return _refused("final_counts_mismatch", "sealed counts differ from the frozen expected counts", seal=seal)
    with w.ledger_read_snapshot(ledger_path) as snapshot:
        prior = [run.run_id for run in snapshot.store.list_runs()
                 if getattr(run, "experiment_id", None) == spec.FINAL_EXPERIMENT_ID]
    if prior:
        return _refused("final_already_attempted", "the final experiment already holds a run", run_ids=prior)
    try:
        d_identity = identity_module.verify_d_candidate_identity(repo_root=spec.REPO_ROOT)
    except Exception as exc:
        return _refused("arm1_identity_verification_failed", f"{type(exc).__name__}: {exc}")
    updates = int(document["training_protocol"]["updates"])
    bindings = {}
    for cell in document["inheritance"]["cells"]:
        state = w._eval_binding_precondition(
            output_root, arm_id=cell["arm_id"], seed=int(cell["seed"]), prereg_sha256=verified["sha256"],
            updates=updates, ledger_path=ledger_path, document=document,
        )
        bindings[f"{cell['arm_id']}-seed{cell['seed']}"] = state
        if state.get("status") != "ok":
            return _refused("eval_binding_unavailable", f"{cell['arm_id']} seed {cell['seed']} does not bind",
                            bindings=bindings)
    return {"status": "ok", "budget": budget, "section": dict(section), "seal": seal, "approval": approval,
            "bindings": bindings, "d_identity": {"checkpoint_id": d_identity.get("checkpoint_id")}}


def read_once_and_score(
    *,
    document: Mapping[str, Any],
    verified: Mapping[str, Any],
    output_root: Path,
    section: Mapping[str, Any],
    backend=None,
    guard=None,
    run_id: str,
) -> dict:
    """Create READ_ONCE, read the sealed final dataset and score every registered cell once."""
    from . import runtime
    from . import worker as w

    digest = section["sealed_dataset_digest"]
    token = data.open_sealed_final_once(
        spec.FINAL_SEALED_ROOT / digest, expected_digest=digest,
        reader={"run_id": run_id, "document_sha256": verified["sha256"], "mode": "final-eval"},
    )
    view = data.FinalView(token)
    protocol = document["training_protocol"]
    window_count = int(view.windows()["obs"].shape[0])
    checkpoints = len(protocol.get("checkpoint_updates") or []) or 1
    window_batches = checkpoints * math.ceil(window_count / max(1, int(protocol["batch_size"])))
    call_plan = {"final_windows": window_count, "window_probe_batches": window_batches,
                 "registered_eval_batches": int(protocol["eval_batches"])}
    if window_batches > int(protocol["eval_batches"]):
        # The read is consumed; the shortfall is recorded, nothing is scored.
        raise RuntimeError(f"final window probe needs {window_batches} batches > registered {protocol['eval_batches']}")
    backend = backend or runtime.MlxBackend()
    cells: dict[str, Any] = {}
    try:
        cells["arm1"] = w._evaluate_arm(document, output_root, arm_id="arm1", seed=0,
                                        prereg_sha256=verified["sha256"], backend=backend)
    except Exception as exc:  # recorded per cell; the single read is not repeated
        cells["arm1"] = {"status": "error", "error": f"{type(exc).__name__}: {exc}"}
    for cell in document["inheritance"]["cells"]:
        label = f"{cell['arm_id']}-seed{cell['seed']}"
        if guard is not None:
            guard.sample()
        try:
            details = w._evaluate_arm(document, output_root, arm_id=cell["arm_id"], seed=int(cell["seed"]),
                                      prereg_sha256=verified["sha256"], backend=backend, eval_view=view)
            cells[label] = details
        except Exception as exc:
            cells[label] = {"status": "error", "error": f"{type(exc).__name__}: {exc}"}
    completed = sum(1 for v in cells.values() if v.get("status") == "completed")
    return {
        "schema": FINAL_EVAL_SCHEMA,
        "partition": "final",
        "sealed_dataset_digest": digest,
        "read_once_marker": str(token.marker_path),
        "call_plan": call_plan,
        "cells": cells,
        "completed_cells": completed,
        "error_cells": sorted(k for k, v in cells.items() if v.get("status") != "completed"),
    }
