"""``ainerzero s1-phase1`` command implementation.

Modes (one explicit mode per invocation; nothing is implied):

``preregister``  build the static draft preregistration from the frozen dataset
``data``         generate + validate the train/development dataset (AWZ producer)
``smoke``        no-update forward+loss measurement for every arm
``freeze``       combine draft + smoke into the frozen preregistration + SHA256
``verify``       re-verify the frozen preregistration, dataset and resource gate
``train``        refused (exit 3) unless, in this order: the repository
                 ``RESEARCH_LOG.md`` (``spec.RESEARCH_LOG`` only) carries exactly one
                 coordinator approval line inside its registered section for the exact
                 frozen document SHA256 (P-1/P-4), every bound source file still hashes
                 to the frozen digest (P-2), and the run root's dataset digest equals
                 ``data_identity.dataset_digest`` (P-3); the document's ``status``
                 field is never an approval

Every compute mode runs under the project-wide shared lock and is supervised by
this process: the worker subprocess gets a hard timeout equal to the frozen
budget (or the card's prep budget) plus the imported ``supervision_extra``
seconds, and the RunStore ledger is reconciled to terminal states afterwards.
The resource gate runs *before* the lock is taken and before any run is
registered, so an unmet protection line cannot start compute.

No CLI option can raise the registered resource limits, the deadline, the
supervision timeout or the update counts: ``--wall-budget-seconds`` only tightens
the prep-run wall budget, ``--limits-file`` is validated tighten-only, and the
run entry always re-reads the frozen preregistration.
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Mapping

from . import data, prereg, resource_gate, spec

PREP_BUDGET = {"data": 600.0, "smoke": 300.0, "verify": 120.0, "eval": 300.0}
EXIT_COMPLETED = 0
EXIT_FAILED = 1
EXIT_REFUSED_RESOURCE = 2
EXIT_REFUSED_APPROVAL = 3
EXIT_LOCK_BUSY = 4


def _output_root(args) -> Path:
    root = Path(getattr(args, "output_root", None) or spec.PHASE1_ROOT)
    root.mkdir(parents=True, exist_ok=True)
    return root


def _research_log(args) -> Path:
    return Path(getattr(args, "research_log", None) or spec.RESEARCH_LOG)


def _canonical_research_log(args) -> tuple[Path, dict | None]:
    """P-1: ``train`` only ever reads ``spec.RESEARCH_LOG``.

    ``--research-log`` stays available for ``verify`` diagnostics, but a value
    that resolves anywhere else is refused instead of silently redirecting the
    approval gate to a file the executor can write.
    """
    canonical = Path(spec.RESEARCH_LOG)
    requested = getattr(args, "research_log", None)
    if requested is None:
        return canonical, None
    requested = Path(requested)
    try:
        same = requested.resolve() == canonical.resolve()
    except OSError:  # pragma: no cover - unreadable path
        same = False
    if same:
        return canonical, None
    return canonical, {
        "status": "refused",
        "stage": "research_log_not_canonical",
        "refused_stage": "research_log_not_canonical",
        "mode": "train",
        "requested_research_log": str(requested),
        "canonical_research_log": str(canonical),
        "message": "train only reads the repository RESEARCH_LOG.md; a --research-log that "
        "resolves elsewhere cannot approve a run (exit 3, no run started)",
    }


def _require_approval(document: Mapping[str, Any], document_sha256: str, log_path: Path) -> dict:
    """Supervisor-side approval gate: a no-op dict on success, refusal otherwise."""
    try:
        return prereg.require_coordinator_approval(
            document, document_sha256, log_path=log_path
        )
    except prereg.ApprovalRefused as exc:
        return {
            "approved": False,
            "reasons": exc.reasons,
            "detail": exc.detail,
            "status_field_is_authoritative": False,
        }


def _load_limits(args) -> dict:
    path = getattr(args, "limits_file", None)
    if path:
        limits = json.loads(Path(path).read_text(encoding="utf-8"))
    else:
        limits = dict(spec.RESOURCE_LIMITS)
    reasons = resource_gate.validate_limits(limits)
    if reasons:
        raise resource_gate.ResourceGateRefused(reasons)
    return limits


def _prep_budget(args, mode: str) -> float:
    default = PREP_BUDGET[mode]
    requested = getattr(args, "wall_budget_seconds", None)
    if requested is None:
        return default
    requested = float(requested)
    if not 0 < requested <= default:
        raise ValueError(
            f"--wall-budget-seconds {requested} must be in (0, {default}]; the CLI can only "
            "tighten the registered preparation budget, never raise it"
        )
    return requested


def _lock_path() -> Path:
    return spec.REPO_ROOT / "artifacts" / "locks" / "m0-worker.lock"


def _worker_command(
    mode: str,
    *,
    output_root: Path,
    limits: Mapping,
    budget: float,
    prereg_path: Path | None = None,
    research_log: Path | None = None,
    arm: str | None = None,
    seed: int | None = None,
) -> list[str]:
    command = [
        sys.executable,
        "-m",
        "ainerzero.v9.experiments.s1.worker",
        "--mode",
        mode,
        "--output-root",
        str(Path(output_root).resolve()),
        "--limits-json",
        json.dumps(dict(limits), sort_keys=True),
        "--wall-budget-seconds",
        str(float(budget)),
    ]
    if prereg_path is not None:
        command.extend(["--prereg", str(Path(prereg_path).resolve())])
    if research_log is not None:
        command.extend(["--research-log", str(Path(research_log).resolve())])
    if arm is not None:
        command.extend(["--arm", str(arm)])
    if seed is not None:
        command.extend(["--seed", str(seed)])
    return command


def _reconcile_after_worker(control_db: Path, prior_runs: set[str], reason: str) -> list[str]:
    from ainerzero.runtime.lifecycle import TERMINAL_STATES, RunStore

    if not Path(control_db).is_file():
        return []
    interrupted: list[str] = []
    with RunStore(control_db) as store:
        for run in store.list_runs():
            if run.run_id not in prior_runs and run.state not in TERMINAL_STATES:
                store.transition(run.run_id, "failed", reason=reason)
                interrupted.append(run.run_id)
    return interrupted


def _supervised_worker(
    mode: str,
    *,
    output_root: Path,
    limits: Mapping,
    budget: float,
    supervision_seconds: float,
    prereg_path: Path | None = None,
    research_log: Path | None = None,
    arm: str | None = None,
    seed: int | None = None,
) -> dict:
    """Run the worker under the shared lock; reconcile the ledger afterwards."""
    from ainerzero.cli import worker_lock

    if mode in ("data", "smoke", "verify", "eval") and supervision_seconds <= 0:
        supervision_seconds = budget + spec.TIMING["supervision_extra_seconds"]
    control_db = output_root / "control.sqlite3"
    prior_runs: set[str] = set()
    interrupted: list[str] = []
    exit_code = EXIT_FAILED
    stdout_lines: list[str] = []
    stderr_tail = ""
    with worker_lock(_lock_path()):
        try:
            from ainerzero.runtime.lifecycle import RunStore

            if control_db.is_file():
                with RunStore(control_db) as store:
                    prior_runs = {run.run_id for run in store.list_runs()}
            result = subprocess.run(
                _worker_command(
                    mode,
                    output_root=output_root,
                    limits=limits,
                    budget=budget,
                    prereg_path=prereg_path,
                    research_log=research_log,
                    arm=arm,
                    seed=seed,
                ),
                capture_output=True,
                text=True,
                timeout=float(supervision_seconds),
            )
            exit_code = result.returncode
            stdout_lines = [line for line in result.stdout.strip().splitlines() if line.strip()]
            stderr_tail = result.stderr.strip()[-2000:]
        except subprocess.TimeoutExpired as exc:
            exit_code = 124
            stdout_lines = []
            stderr_tail = f"supervisor timeout after {supervision_seconds:.0f}s: {exc}"
        finally:
            interrupted = _reconcile_after_worker(control_db, prior_runs, "supervisor_timeout" if exit_code == 124 else "worker_interrupted")
    report: dict[str, Any] | None = None
    if stdout_lines:
        try:
            parsed = json.loads(stdout_lines[-1])
            report = parsed if isinstance(parsed, dict) else None
        except json.JSONDecodeError:
            report = None
    if report is None:
        report = {
            "status": "failed",
            "mode": mode,
            "error": "worker ended without a valid JSON report",
            "worker_exit_code": exit_code,
            "stderr_tail": stderr_tail,
        }
    report.setdefault("spec", spec.SPEC_NAME)
    report.setdefault("mode", mode)
    report["worker_exit_code"] = exit_code
    if interrupted:
        report["interrupted_run_ids"] = interrupted
        if report.get("status") == "completed":
            report["status"] = "failed"
            report["error"] = "worker exited with unfinished RunStore runs"
    report_path = output_root / f"{mode}_report.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, sort_keys=True, indent=1) + "\n", encoding="utf-8"
    )
    report["report_path"] = str(report_path.resolve())
    return report


def _exit_code_for(report: Mapping[str, Any]) -> int:
    status = report.get("status")
    if status == "completed":
        return EXIT_COMPLETED
    if report.get("refused_stage") or report.get("stage") == "preregistration_not_approved":
        return EXIT_REFUSED_APPROVAL
    if report.get("stage") == "lock_busy":
        return EXIT_LOCK_BUSY
    if status == "refused":
        return EXIT_REFUSED_RESOURCE
    if status == "stopped" and "BudgetExceeded" in str(report.get("error", "")):
        return EXIT_FAILED
    if status == "stopped" and "resource_gate" in str(report.get("error", "")):
        return EXIT_REFUSED_RESOURCE
    return EXIT_FAILED


# --- modes ----------------------------------------------------------------
def mode_data(args) -> dict:
    output_root = _output_root(args)
    limits = _load_limits(args)
    budget = _prep_budget(args, "data")
    try:
        snapshot = resource_gate.assert_start(limits, root=output_root)
    except resource_gate.ResourceGateRefused as exc:
        return {
            "status": "refused",
            "stage": "resource_gate",
            "mode": "data",
            "reasons": exc.reasons,
            "snapshot": exc.snapshot,
        }
    report = _supervised_worker(
        "data",
        output_root=output_root,
        limits=limits,
        budget=budget,
        supervision_seconds=budget + spec.TIMING["supervision_extra_seconds"],
    )
    report["start_gate"] = snapshot.to_dict()
    return report


def mode_smoke(args) -> dict:
    output_root = _output_root(args)
    limits = _load_limits(args)
    budget = _prep_budget(args, "smoke")
    try:
        data.resolve_dataset_dir(output_root)
    except data.DatasetError as exc:
        return {
            "status": "refused",
            "stage": "dataset_missing",
            "mode": "smoke",
            "message": f"run --mode data first; smoke needs the frozen dataset ({exc})",
        }
    try:
        snapshot = resource_gate.assert_start(limits, root=output_root)
    except resource_gate.ResourceGateRefused as exc:
        return {
            "status": "refused",
            "stage": "resource_gate",
            "mode": "smoke",
            "reasons": exc.reasons,
            "snapshot": exc.snapshot,
        }
    report = _supervised_worker(
        "smoke",
        output_root=output_root,
        limits=limits,
        budget=budget,
        supervision_seconds=budget + spec.TIMING["supervision_extra_seconds"],
    )
    report["start_gate"] = snapshot.to_dict()
    return report


def mode_preregister(args) -> dict:
    from ainerzero.cli import worker_lock

    output_root = _output_root(args)
    limits = _load_limits(args)
    dataset_dir = data.resolve_dataset_dir(output_root)
    manifest = data.load_manifest(dataset_dir)
    with worker_lock(_lock_path()):
        return _build_draft(output_root, limits, manifest)


def _build_draft(output_root: Path, limits: Mapping, manifest: Mapping) -> dict:
    identity = data.dataset_identity(manifest)
    from . import arms

    counts = arms.arm_parameter_counts()
    draft = prereg.build_draft(data_identity=identity, parameter_counts=counts)  # noqa: F821
    draft_path = output_root / "draft_preregistration.json"
    draft_path.write_text(
        json.dumps(draft, ensure_ascii=False, sort_keys=True, indent=1) + "\n", encoding="utf-8"
    )
    return {
        "status": "completed",
        "mode": "preregister",
        "draft_path": str(draft_path.resolve()),
        "draft_sha256": prereg.document_sha256(draft),
        "parameter_counts": counts,
        "dataset_digest": identity["dataset_digest"],
        "resource_limits": limits,
    }


def mode_freeze(args) -> dict:
    from ainerzero.cli import worker_lock

    output_root = _output_root(args)
    limits = _load_limits(args)
    requested = getattr(args, "smoke_metrics", None)
    smoke_path = Path(requested) if requested else (output_root / "smoke_metrics.json")
    with worker_lock(_lock_path()):
        return _freeze(output_root, limits, smoke_path=smoke_path)


def _freeze(output_root: Path, limits: Mapping, *, smoke_path: Path | None = None) -> dict:
    draft_path = output_root / "draft_preregistration.json"
    smoke_path = Path(smoke_path) if smoke_path is not None else (output_root / "smoke_metrics.json")
    if not draft_path.is_file() or not smoke_path.is_file():
        return {
            "status": "refused",
            "stage": "inputs_missing",
            "mode": "freeze",
            "message": f"needs {draft_path.name} and {smoke_path.name}",
        }
    try:
        snapshot = resource_gate.assert_start(limits, root=output_root)
    except resource_gate.ResourceGateRefused as exc:
        return {
            "status": "refused",
            "stage": "resource_gate",
            "mode": "freeze",
            "reasons": exc.reasons,
            "snapshot": exc.snapshot,
        }
    draft = json.loads(draft_path.read_text(encoding="utf-8"))
    smoke_metrics = json.loads(smoke_path.read_text(encoding="utf-8"))
    manifest = data.load_manifest(data.resolve_dataset_dir(output_root))
    identity = data.dataset_identity(manifest)
    frozen = prereg.build_frozen(draft, smoke=smoke_metrics, data_identity=identity)
    frozen["timing"]["smoke_source"] = _smoke_source_record(smoke_path, output_root)
    recheck = _smoke_recheck_record(smoke_path, output_root)
    if recheck is not None:
        frozen["timing"]["smoke_recheck"] = recheck
    out_path = output_root / "pre_registration.json"
    out_path.write_text(
        json.dumps(frozen, ensure_ascii=False, sort_keys=True, indent=1) + "\n", encoding="utf-8"
    )
    digest = prereg.document_sha256(frozen)
    checksum_path = prereg.write_sha256_file(out_path, digest)
    verified = prereg.verify_frozen_file(out_path)
    return {
        "status": "completed",
        "mode": "freeze",
        "preregistration_path": str(out_path.resolve()),
        "preregistration_sha256": digest,
        "checksum_path": str(checksum_path.resolve()),
        "reverified": verified["sha256"] == digest,
        "timing": frozen["timing"],
        "status_field": frozen["status"],
        "updates": frozen["training_protocol"]["updates"],
        "start_gate": snapshot.to_dict(),
        "final_partition": "not_generated_not_read",
    }


def _smoke_source_record(smoke_path: Path, output_root: Path) -> dict:
    """Name the measurement of record that the frozen budget was derived from."""
    smoke_path = Path(smoke_path)
    return {
        "path": str(smoke_path.resolve()),
        "sha256": spec.sha256_file(smoke_path),
        "in_run_root": smoke_path.resolve() == (Path(output_root) / "smoke_metrics.json").resolve(),
        "role": "measurement of record: the frozen deadline/updates are derived from this file "
        "only; no command line value can replace it",
    }


def _smoke_recheck_record(smoke_path: Path, output_root: Path) -> dict | None:
    """If the run root holds a *newer* smoke run, record it as a cross-check.

    A re-measured forward+loss step time moves the derived update count because
    the frozen rule targets a fixed active budget.  The re-check is recorded next
    to the measurement of record instead of silently re-freezing the protocol.
    """
    local = Path(output_root) / "smoke_metrics.json"
    if not local.is_file():
        return None
    if spec.sha256_file(local) == spec.sha256_file(smoke_path):
        return None
    smoke = json.loads(local.read_text(encoding="utf-8"))
    try:
        budget = prereg.estimate_budget(smoke)
    except ValueError as exc:
        return {
            "path": str(local.resolve()),
            "sha256": spec.sha256_file(local),
            "usable": False,
            "error": f"{type(exc).__name__}: {exc}",
        }
    return {
        "path": str(local.resolve()),
        "sha256": spec.sha256_file(local),
        "usable": True,
        "measured_step_seconds": budget["measured_forward_loss_step_seconds"],
        "derived_updates_if_recheck_used": budget["updates"],
        "derived_deadline_if_recheck_used": budget["deadline_seconds"],
        "note": "same protocol, same arm code; the difference is measurement noise on the "
        "forward+loss step. The frozen document keeps the registered measurement of record so "
        "the update count and budget do not drift between r1 and r2.",
    }


def mode_verify(args) -> dict:
    output_root = _output_root(args)
    limits = _load_limits(args)
    path = Path(getattr(args, "prereg", None) or (output_root / "pre_registration.json"))
    if not path.is_file():
        return {"status": "refused", "stage": "prereg_missing", "path": str(path)}
    try:
        snapshot = resource_gate.assert_start(limits, root=output_root)
    except resource_gate.ResourceGateRefused as exc:
        return {
            "status": "refused",
            "stage": "resource_gate",
            "mode": "verify",
            "reasons": exc.reasons,
            "snapshot": exc.snapshot,
        }
    verified = prereg.verify_frozen_file(path)
    binding = _source_binding_state(verified["document"])
    if binding["status"] != "passed":
        return {
            "status": "failed",
            "stage": "source_binding_drift",
            "mode": "verify",
            "preregistration_path": str(Path(path).resolve()),
            "preregistration_sha256": verified["sha256"],
            "source_binding": binding,
            "message": "the frozen document binds source files whose SHA256 no longer match the "
            "files on disk; re-freeze instead of verifying a stale binding",
        }
    dataset = data.verify_dataset(data.resolve_dataset_dir(output_root))
    smoke_path = output_root / "smoke_metrics.json"
    smoke_metrics = (
        json.loads(smoke_path.read_text(encoding="utf-8")) if smoke_path.is_file() else None
    )
    return {
        "status": "completed",
        "mode": "verify",
        "preregistration_path": str(Path(path).resolve()),
        "preregistration_sha256": verified["sha256"],
        "preregistration_status": verified["document"]["status"],
        "dataset": dataset,
        "resource_gate": snapshot.to_dict(),
        "smoke_parameters_unchanged": (smoke_metrics or {}).get("parameters_unchanged"),
        "frozen_smoke_source": _frozen_smoke_source_state(verified["document"]),
        "source_binding": binding,
        "independent_parameter_check": _independent_parameter_check(smoke_metrics),
        "approval": _approval_state(path, verified, _research_log(args)),
        "final_partition": "not_generated_not_read",
    }


def _source_binding_state(document: Mapping[str, Any]) -> dict:
    """Re-hash every source file the frozen document binds.

    A mismatch means the code that would run is not the code that was frozen, so
    ``verify`` fails instead of reporting a clean pass, and ``train`` refuses to
    start (P-2).  The rule lives in :mod:`prereg` so the worker applies the same
    one.
    """
    return prereg.source_binding_state(document)


def _frozen_smoke_source_state(document: Mapping[str, Any]) -> dict:
    """Check that the frozen measurement of record is still the file it names."""
    source = ((document.get("timing") or {}).get("smoke_source")) or {}
    raw = source.get("path")
    if not raw:
        return {"present": False}
    path = Path(raw)
    if not path.is_file():
        return {"present": True, "path": raw, "file_present": False, "match": False}
    actual = spec.sha256_file(path)
    return {
        "present": True,
        "path": raw,
        "file_present": True,
        "sha256": actual,
        "match": actual == source.get("sha256"),
    }


def _approval_state(path: Path, verified: Mapping[str, Any], log_path: Path) -> dict:
    """Report whether a coordinator approval line covers this document (no run)."""
    try:
        record = prereg.require_coordinator_approval(
            verified["document"], verified["sha256"], log_path=log_path
        )
    except prereg.ApprovalRefused as exc:
        return {
            "approved": False,
            "reasons": exc.reasons,
            "detail": exc.detail,
            "preregistration_path": str(Path(path).resolve()),
        }
    return {**record, "preregistration_path": str(Path(path).resolve())}


def _independent_parameter_check(smoke_metrics: Mapping[str, Any] | None) -> dict:
    """Rebuild every arm and hash its parameters; compare with the smoke report.

    The smoke report's own ``parameters_unchanged`` flag is not trusted: this
    recomputes the digests from the frozen spec in a separate process and checks
    that the recorded before/after digests equal them (V9.P10 F4).
    """
    if not smoke_metrics:
        return {"status": "not_available", "reason": "no smoke metrics to check against"}
    from . import smoke as smoke_module

    seed = int(smoke_metrics.get("smoke_seed", 0))
    recomputed = smoke_module.parameter_digests(seed=seed)
    rows: dict[str, dict] = {}
    ok = True
    for arm_id, digest in recomputed.items():
        section = "d_candidate" if arm_id == "arm1" else None
        block = (
            (smoke_metrics.get("d_candidate") or {})
            if section
            else (smoke_metrics.get("trainable_arms") or {}).get(arm_id, {})
        )
        before = block.get("parameter_sha256_before")
        after = block.get("parameter_sha256_after")
        match = before == digest and after == digest
        ok = ok and bool(match)
        rows[arm_id] = {
            "recomputed_sha256": digest,
            "smoke_before": before,
            "smoke_after": after,
            "match": bool(match),
        }
    return {
        "status": "passed" if ok else "failed",
        "rule": "rebuild from the frozen spec (same seed), hash parameters only, no "
        "forward pass, no dataset read; both smoke digests must equal the recomputation",
        "seed": seed,
        "arms": rows,
    }


def mode_train(args) -> dict:
    output_root = _output_root(args)
    limits = _load_limits(args)
    path = Path(getattr(args, "prereg", None) or (output_root / "pre_registration.json"))
    if not path.is_file():
        return {"status": "refused", "stage": "prereg_missing", "path": str(path)}
    verified = prereg.verify_frozen_file(path)
    document = verified["document"]
    # P-1: the approval gate reads spec.RESEARCH_LOG and nothing else.
    log_path, refusal = _canonical_research_log(args)
    if refusal is not None:
        refusal["preregistration_path"] = str(Path(path).resolve())
        refusal["preregistration_sha256"] = verified["sha256"]
        return refusal
    approval = _require_approval(document, verified["sha256"], log_path)
    if not approval.get("approved"):
        return {
            "status": "refused",
            "stage": "preregistration_not_approved",
            "refused_stage": "preregistration_not_approved",
            "mode": "train",
            "preregistration_path": str(Path(path).resolve()),
            "preregistration_sha256": verified["sha256"],
            "preregistration_status": document.get("status"),
            "status_field_is_authoritative": False,
            "approval": approval,
            "message": "S1 phase-1 training needs the coordinator's approval line "
            f"'{prereg.APPROVAL_TEMPLATE.format(document_sha256=verified['sha256'])}' "
            f"inside the '## {prereg.APPROVAL_SECTION}' section of {log_path}; the "
            "preregistration status field is not an approval. No parameters were updated.",
        }
    # P-2: the code on disk must still be the code the document froze.
    binding = _source_binding_state(document)
    if binding["status"] != "passed":
        return {
            "status": "refused",
            "stage": "source_binding_drift",
            "refused_stage": "source_binding_drift",
            "mode": "train",
            "preregistration_path": str(Path(path).resolve()),
            "preregistration_sha256": verified["sha256"],
            "source_binding": binding,
            "message": "the frozen document binds source files whose SHA256 no longer match "
            f"the files on disk ({', '.join(binding.get('drifted') or ['(none listed)'])}); "
            "train refuses to start and no parameters were updated",
        }
    # P-3: the dataset the run root points at must be the frozen dataset.
    dataset = data.dataset_binding_state(
        output_root, (document.get("data_identity") or {}).get("dataset_digest")
    )
    if dataset["status"] != "passed":
        return {
            "status": "refused",
            "stage": "dataset_identity_mismatch",
            "refused_stage": "dataset_identity_mismatch",
            "mode": "train",
            "preregistration_path": str(Path(path).resolve()),
            "preregistration_sha256": verified["sha256"],
            "dataset": dataset,
            "message": "the dataset this run root resolves to does not match "
            "data_identity.dataset_digest in the frozen preregistration; train refuses to "
            "start and no parameters were updated",
        }

    arm = getattr(args, "arm", None)
    seed = getattr(args, "seed", None)
    if arm not in ("arm2", "arm3", "arm4"):
        return {
            "status": "refused",
            "stage": "invalid_arguments",
            "refused_stage": "invalid_arguments",
            "mode": "train",
            "message": f"train requires --arm in ('arm2', 'arm3', 'arm4'), got {arm!r}",
        }
    if seed is None or seed not in (0, 1, 2):
        return {
            "status": "refused",
            "stage": "invalid_arguments",
            "refused_stage": "invalid_arguments",
            "mode": "train",
            "message": f"train requires --seed in (0, 1, 2), got {seed!r}",
        }

    # Guard: any started arm x seed attempt forbids an unauthorized rerun.
    control_db = output_root / "control.sqlite3"
    if control_db.is_file():
        from ainerzero.runtime.lifecycle import RunStore

        from . import worker as worker_module

        with RunStore(control_db) as store:
            attempts = worker_module.train_attempts(
                store.list_runs(), arm_id=arm, seed=int(seed)
            )
        if attempts:
            first = attempts[0]
            return {
                "status": "refused",
                "stage": "already_attempted",
                "refused_stage": "already_attempted",
                "mode": "train",
                "arm": arm,
                "seed": seed,
                "run_id": first.run_id,
                "attempt_states": [run.state for run in attempts],
                "attempt_run_ids": [run.run_id for run in attempts],
                "message": f"arm {arm} seed {seed} already has a registered attempt "
                f"({first.run_id}, state={first.state}); rerun is forbidden",
            }

    # Guard: phase total wall clock budget <= 14400 s
    deadline = float(document["timing"]["deadline_seconds"])
    phase_cap = float(document["timing"].get("phase_wall_max_seconds", 14400.0))
    if control_db.is_file():
        from ainerzero.runtime.lifecycle import RunStore

        with RunStore(control_db) as store:
            total_wall = sum(
                float(r.wall_seconds)
                for r in store.list_runs()
                # Include auxiliary eval/verify reservations; the phase cap is not
                # a training-experiment-only allowance.
            )
        if total_wall + deadline > phase_cap:
            return {
                "status": "refused",
                "stage": "phase_budget_exceeded",
                "refused_stage": "phase_budget_exceeded",
                "mode": "train",
                "total_wall_seconds": total_wall,
                "deadline_seconds": deadline,
                "phase_wall_max_seconds": phase_cap,
                "message": f"phase wall budget would be exceeded: accumulated {total_wall:.1f}s + deadline {deadline:.1f}s > {phase_cap:.1f}s",
            }

    # Approved path: the worker owns the registered loop
    try:
        resource_gate.assert_start(limits, root=output_root)
    except resource_gate.ResourceGateRefused as exc:
        return {"status": "refused", "stage": "resource_gate", "reasons": exc.reasons}
    supervision = float(document["timing"]["supervision_seconds"])
    return _supervised_worker(
        "train",
        output_root=output_root,
        limits=limits,
        budget=deadline,
        supervision_seconds=supervision,
        prereg_path=path,
        research_log=log_path,
        arm=arm,
        seed=seed,
    )


def mode_eval(args) -> dict:
    output_root = _output_root(args)
    limits = _load_limits(args)
    arm = getattr(args, "arm", None)
    if arm not in ("arm1", "arm2", "arm3", "arm4"):
        return {
            "status": "refused",
            "stage": "invalid_arguments",
            "refused_stage": "invalid_arguments",
            "mode": "eval",
            "message": f"eval requires --arm in ('arm1', 'arm2', 'arm3', 'arm4'), got {arm!r}",
        }
    seed = getattr(args, "seed", None)
    if seed is None and arm in ("arm2", "arm3", "arm4"):
        seed = 0
    path = Path(getattr(args, "prereg", None) or (output_root / "pre_registration.json"))
    if not path.is_file():
        return {"status": "refused", "stage": "prereg_missing", "path": str(path)}
    try:
        snapshot = resource_gate.assert_start(limits, root=output_root)
    except resource_gate.ResourceGateRefused as exc:
        return {
            "status": "refused",
            "stage": "resource_gate",
            "mode": "eval",
            "reasons": exc.reasons,
            "snapshot": exc.snapshot,
        }
    budget = _prep_budget(args, "eval")
    report = _supervised_worker(
        "eval",
        output_root=output_root,
        limits=limits,
        budget=budget,
        supervision_seconds=budget + spec.TIMING["supervision_extra_seconds"],
        prereg_path=path,
        arm=arm,
        seed=seed,
    )
    report["start_gate"] = snapshot.to_dict()
    return report


MODES = {
    "data": mode_data,
    "smoke": mode_smoke,
    "preregister": mode_preregister,
    "freeze": mode_freeze,
    "verify": mode_verify,
    "train": mode_train,
    "eval": mode_eval,
}


def s1_phase1_command(args) -> tuple[dict, int]:
    mode = getattr(args, "mode", None)
    if mode not in MODES:
        return {"status": "failed", "error": f"unknown mode {mode!r}"}, EXIT_FAILED
    started = time.perf_counter()
    try:
        report = MODES[mode](args)
    except resource_gate.ResourceGateRefused as exc:
        report = {
            "status": "refused",
            "stage": "resource_gate",
            "mode": mode,
            "reasons": exc.reasons,
            "snapshot": exc.snapshot,
        }
    except (OSError, ValueError, KeyError, RuntimeError) as exc:
        from ainerzero.cli import WorkerLockBusy

        if isinstance(exc, WorkerLockBusy):
            report = {"status": "refused", "stage": "lock_busy", "mode": mode, "error": str(exc)}
        else:
            report = {"status": "failed", "mode": mode, "error": f"{type(exc).__name__}: {exc}"}
    report.setdefault("spec", spec.SPEC_NAME)
    report["mode"] = mode
    report["elapsed_seconds"] = time.perf_counter() - started
    return report, _exit_code_for(report)
