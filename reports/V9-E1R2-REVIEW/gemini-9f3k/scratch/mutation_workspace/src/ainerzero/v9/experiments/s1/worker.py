"""Worker half of the S1 phase-1 run entry.

The supervisor (``commands.py``) holds the project-wide shared lock
``artifacts/locks/m0-worker.lock`` and starts this module as a subprocess with a
hard wall timeout (frozen supervision time).  This worker then:

1. re-checks the resource gate (defence in depth; the supervisor already refused
   before any compute if a line was unmet),
2. registers an *auxiliary* run in a card-local RunStore ledger
   (``reports/V9-P9/control.sqlite3``) -- deliberately not the A2-pinned
   ``artifacts/control.sqlite3`` whose row digests are frozen baseline,
3. reserves wall budget *before* each work unit (pre-work reservation; a
   ``BudgetExceeded`` stops the run and is recorded),
4. samples the runtime guard during compute,
5. moves the run to a terminal state and prints one JSON report.

The training branch refuses to run unless the frozen preregistration file is in
the coordinator-approved state; this card never approves it, so S1 phase 1
cannot be trained from here (that is V9.P1).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import shutil
import sqlite3
import sys
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Mapping
from uuid import uuid4

from . import completion, data, evaluation, prereg, resource_gate, runtime, spec

PREP_EXPERIMENT_ID = "s1-phase1-prereg-prep-20261021"
PREP_REQUEST_ID = "s1-phase1-prereg-prep"
TIMEZONE = "Europe/Belgrade"
PER_RUN_BUDGET = {"data": 600.0, "smoke": 300.0, "verify": 120.0}
TRAIN_EXPERIMENT_ID = spec.EXPERIMENT_ID


class BudgetStop(RuntimeError):
    """The run exhausted its reserved budget (never silently extended)."""


class LedgerAccountingError(ValueError):
    """The central ledger contains a row the conservative accounting refuses.

    r8 (S1-R8-DECISION F2/F5): a refusal must say *what* is wrong.  A state the
    product cannot write is not a timestamp problem, and a NaN reservation is not
    an unknown state, so the two families have distinct types and the entry
    reports distinct ``refused_stage`` values.
    """


class LedgerStateInvalid(LedgerAccountingError):
    """A ledger row carries a state the RunStore lifecycle cannot produce."""


class LedgerTimestampInvalid(LedgerAccountingError):
    """A ledger row carries a missing, unrepresentable, non-finite or unordered timestamp."""


class ExperimentManifestMismatch(LedgerAccountingError):
    """The shared experiment ID already exists with a different manifest (r9 R1).

    The RunStore registers an experiment once.  A second caller that only looks
    the experiment up (instead of registering it) could silently attach its runs
    to an experiment whose ceilings, purpose or identity belong to somebody
    else's registration.  r9 refuses that: reusing an existing experiment is
    legal only when its canonical manifest digest equals the manifest this
    caller would have registered.
    """


class EvalBindingError(RuntimeError):
    """A completed run/checkpoint/preregistration binding is missing or inconsistent."""


class NonFiniteState(RuntimeError):
    """A frozen stop rule fired: loss, a gradient leaf or an updated parameter is not finite."""


def _flatten_leaves(value, prefix: str = "leaf", out: list | None = None) -> list:
    """Flatten a nested mapping/list pytree into ``(name, leaf)`` pairs."""
    if out is None:
        out = []
    if isinstance(value, Mapping):
        for key in value:
            _flatten_leaves(value[key], f"{prefix}.{key}", out)
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            _flatten_leaves(item, f"{prefix}[{index}]", out)
    elif value is not None:
        out.append((prefix, value))
    return out


def _non_finite_leaves(values, label: str) -> list:
    """Names of leaves that are not finite (the frozen STOP_RULES trigger)."""
    import numpy as np

    bad: list[str] = []
    for name, value in _flatten_leaves(values, label):
        array = np.asarray(value)
        if array.dtype.kind not in "fc":
            raise NonFiniteState(f"{name} is not a real numeric array (dtype={array.dtype})")
        if not np.all(np.isfinite(array)):
            bad.append(name)
    return bad


def _assert_finite_update(loss, grads) -> None:
    """Frozen stop rule: non-finite loss or any gradient leaf fails the run.

    This is a load-bearing check inside the training loop, not a check of the
    final JSON: the run is aborted before any optimizer update and can never
    write a completion receipt.
    """
    bad = _non_finite_leaves({"loss": loss}, "loss")
    if not bad:
        bad = _non_finite_leaves(grads, "grads")
    if not bad:
        return
    raise NonFiniteState(
        "non-finite training state at update boundary: " + ", ".join(sorted(bad))
    )


def _assert_finite_parameters(backend, model) -> None:
    """Frozen stop rule: every updated parameter must stay finite."""
    if hasattr(backend, "parameter_arrays"):
        parameters = backend.parameter_arrays(model)
    else:  # test doubles keep a plain dict
        parameters = getattr(model, "params", None)
        if parameters is None:
            raise NonFiniteState("the backend exposes no parameter arrays to inspect")
    bad = _non_finite_leaves(parameters, "params")
    if bad:
        raise NonFiniteState(
            "non-finite updated parameters: " + ", ".join(sorted(bad))
        )



TRAIN_RECEIPT_PREFIX = "s1_train_completed:"
CHECKPOINT_RESERVE_SECONDS = 2.0
FINAL_SAVE_RESERVE_SECONDS = 0.5

# Modes whose budget (arm x seed attempts, phase wall total, optimizer steps)
# is anchored to the one central RunStore under the canonical phase-1 root.
# Preparation modes (data/smoke/verify) keep their per-root diagnostic ledger.
BOUNDED_MODES = ("train", "eval", "final-eval")  # P59: the final read is bounded too
LEDGER_TABLES = {"metadata", "runs", "daily_budget", "run_transitions", "experiments"}


def canonical_ledger_path() -> Path:
    """The unique central RunStore for S1 phase 1 (notice #297 layout).

    Every bounded run registers here, never in a per-output-root copy: a new
    output root, a different cwd, another checkout or a copied preregistration
    must not be able to reset the attempt guard or the phase wall total.
    """
    return spec.PHASE1_ROOT / "control.sqlite3"


def canonical_ledger_state(path: Path | None = None) -> dict:
    """Read-only identity check of the central ledger (fail closed).

    A missing, unreadable, schema-less or unrecognised ledger is never opened
    for writing and never re-created: a bounded run fails closed instead of
    starting against a fresh, empty ledger.
    """
    ledger_path = Path(path) if path is not None else canonical_ledger_path()
    state: dict[str, Any] = {"path": str(ledger_path), "status": "ok"}
    if not ledger_path.is_file():
        state.update({"status": "missing", "reason": "no RunStore ledger file"})
        return state
    try:
        connection = sqlite3.connect(f"file:{ledger_path}?mode=ro", uri=True)
    except sqlite3.Error as exc:
        state.update({"status": "unreadable", "reason": f"{type(exc).__name__}: {exc}"})
        return state
    try:
        tables = {
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        if not LEDGER_TABLES <= tables:
            state.update(
                {
                    "status": "unrecognized",
                    "reason": f"not a RunStore ledger (tables present: {sorted(tables)})",
                }
            )
            return state
        experiments = [
            row[0] for row in connection.execute("SELECT experiment_id FROM experiments")
        ]
        if PREP_EXPERIMENT_ID not in experiments:
            state.update(
                {
                    "status": "unrecognized",
                    "reason": "the phase-1 preparation experiment is absent; this is not the "
                    "central S1 phase-1 ledger",
                    "experiments": experiments,
                }
            )
            return state
        runs = int(connection.execute("SELECT COUNT(*) FROM runs").fetchone()[0])
        state.update({"experiments": experiments, "runs": runs})
        return state
    except sqlite3.Error as exc:
        state.update({"status": "unreadable", "reason": f"{type(exc).__name__}: {exc}"})
        return state
    finally:
        connection.close()


def document_experiment_id(document: Mapping[str, Any]) -> str | None:
    """The experiment a frozen document registers its runs under, if it names one.

    The r11 re-freeze (RESEARCH_LOG R20261023-S1-phase1-r11-budget) registers a
    new experiment ID so its runs are recorded under the new registration while
    the old experiment ``s1-phase1-20261021`` keeps its runs, attempts and
    failures untouched.  Documents without an experiment id fall back to the
    module constant at the call site.
    """
    experiment_id = (document or {}).get("experiment_id")
    return str(experiment_id) if experiment_id else None


def document_experiment_scope(document: Mapping[str, Any]) -> str | None:
    """The experiment the phase guards are scoped to, or ``None`` for no scoping.

    Only a *registered* identity scopes (``spec.REGISTERED_EXPERIMENT_IDS``):
    those are the registrations the user approved as a fresh phase-1 attempt
    with their own attempt counts and phase budget (RESEARCH_LOG
    R20261023-S1-phase1-r11-budget).  r11 was frozen first and its identity was
    then consumed by the P31 ledger incident; r12 is the same registration
    under a fresh identity (P31-LEDGER-INCIDENT-RULING).  Every other document
    -- including the old experiment id, whose rows are the shared history the
    r1-r10 guards were built against -- keeps the whole-ledger behaviour, so no
    previously established refusal is weakened.  An unregistered experiment id
    therefore never gets a fresh attempt count.
    """
    experiment_id = (document or {}).get("experiment_id")
    if experiment_id in spec.REGISTERED_EXPERIMENT_IDS:
        return str(experiment_id)
    return None


def inherited_cell(document: Mapping[str, Any], *, arm_id: str, seed: int) -> dict | None:
    """r14 (ainerzero.V9.P49): the registered inheritance row for this arm x seed.

    Only a document whose inheritance section equals the registered one in
    ``spec.INHERITANCE_BY_EXPERIMENT`` can name an inherited cell; any other
    section is ignored here and refused by ``prereg.validate`` at verify time,
    so a hand-edited document cannot smuggle a cell in.
    """
    section = (document or {}).get("inheritance")
    if not section:
        return None
    expected = spec.INHERITANCE_BY_EXPERIMENT.get((document or {}).get("experiment_id"))
    if expected is None or json.loads(json.dumps(section)) != json.loads(json.dumps(expected)):
        return None
    for cell in section.get("cells") or ():
        if cell.get("arm_id") == arm_id and int(cell.get("seed", -1)) == int(seed):
            # r15: a multi-source section names the source per cell; r14 per section.
            if "sources" in section:
                source = str(cell["source_experiment_id"])
                record = section["sources"][source]
            else:
                source = str(section["source_experiment_id"])
                record = section
            return {
                "arm_id": arm_id,
                "seed": int(seed),
                "source_run_id": str(cell["source_run_id"]),
                "params_sha256": str(cell["params_sha256"]),
                "source_experiment_id": source,
                "source_preregistration_sha256": str(record["source_preregistration_sha256"]),
            }
    return None


def train_attempts(runs, *, arm_id: str, seed: int, experiment_id: str | None = None) -> list:
    """Runs that already *started* an arm x seed attempt.

    ``created`` is the only pre-start state.  Any other state (initializing,
    training, pausing, paused, completed, failed, stopped) means a real attempt
    was registered, so an unauthorized rerun must be refused.  A run that
    already reserved optimizer steps is also an attempt, even if a later
    lifecycle repair left it in a non-terminal state.

    r11: ``experiment_id`` scopes the count to one registration.  The new
    experiment starts from zero attempts (the user approved a fresh phase-1
    run), while the old experiment's rows still refuse a rerun of the same
    arm x seed under the old registration.  ``None`` counts every row, which is
    the pre-r11 behaviour.
    """
    attempts = []
    for run in runs:
        if experiment_id is not None and getattr(run, "experiment_id", None) != experiment_id:
            continue
        config = run.config_snapshot or {}
        if config.get("arm_id") != arm_id:
            continue
        try:
            run_seed = int(config.get("seed", -1))
        except (TypeError, ValueError):
            continue
        if run_seed != int(seed):
            continue
        if run.state != "created" or int(run.reserved_optimizer_steps) > 0:
            attempts.append(run)
    return attempts


TERMINAL_STATES = frozenset({"completed", "stopped", "failed"})
# Every state the RunStore lifecycle may persist (``runtime.lifecycle``:
# ``WORK_STATES`` = collecting/training/validating, plus the initializing,
# pausing, paused and stopping transition states).  r7 omitted collecting,
# validating and stopping, so rows the product itself writes (prep data ->
# collecting, prep smoke/verify and every eval -> validating) were refused as
# "unknown" (P21 F2).  A state outside this set is a corrupt/foreign row: it must
# be refused, never counted as "still active" and never counted as zero.
ACTIVE_STATES = frozenset(
    {
        "created",
        "initializing",
        "collecting",
        "training",
        "validating",
        "pausing",
        "paused",
        "stopping",
    }
)
KNOWN_STATES = TERMINAL_STATES | ACTIVE_STATES
# Names only, used by tests/evidence to show the accounting covers what the
# generic lifecycle can actually write.
LIFECYCLE_WORK_STATES = frozenset({"collecting", "training", "validating"})


def d_candidate_attempt_state(runs, *, experiment_id: str | None = None) -> dict:
    """Whether the frozen D candidate has already been evaluated (r8 F4).

    r7 filtered on ``config_snapshot["arm_id"] == "arm1"``, but the product's own
    ``open_aux_run`` never wrote that field, so the guard could not see the row it
    had just created and a second arm1 evaluation was admitted.  r8 writes the
    identity fields in ``open_aux_run``; this guard additionally fails closed on
    an older row that *looks* like a D attempt but carries no ``arm_id`` (a row in
    the shared training/evaluation experiment of auxiliary role, or any purpose
    naming arm1 / d_candidate).  Rows are never deleted, rewritten or "repaired";
    an ambiguous history needs a coordinator, not an automatic fix-up.

    r11: ``experiment_id`` scopes the guard to one registration, so the new
    experiment may run its own single D evaluation while the old experiment's
    completed D row stays recorded under the old id.  ``None`` keeps the
    whole-ledger behaviour.
    """
    target_experiment = experiment_id if experiment_id is not None else TRAIN_EXPERIMENT_ID
    # A scoped guard also counts D rows recorded in the preparation experiment:
    # an arm1 row there is ambiguous history for any registration, so the
    # fail-closed r7 behaviour (refuse, never silently ignore) is preserved.
    targets = None if experiment_id is None else {experiment_id, PREP_EXPERIMENT_ID}
    attempted: list = []
    unidentifiable: list = []
    for run in runs:
        config = run.config_snapshot or {}
        arm_id = config.get("arm_id")
        reserved = int(getattr(run, "reserved_optimizer_steps", 0) or 0)
        started = getattr(run, "state", None) != "created" or reserved > 0
        if not started:
            continue
        if targets is not None and getattr(run, "experiment_id", None) not in targets:
            # r11: a D row registered under another experiment is that
            # registration's history, not an attempt of this one.
            continue
        if arm_id == "arm1":
            attempted.append(run)
            continue
        if arm_id is not None:
            continue
        purpose = str(config.get("purpose") or "")
        if "arm1" in purpose or "d_candidate" in purpose.lower():
            unidentifiable.append(run)
            continue
        if getattr(run, "experiment_id", None) == target_experiment and getattr(
            run, "role", None
        ) == "auxiliary":
            unidentifiable.append(run)
    if attempted:
        return {
            "status": "already_attempted",
            "run_ids": [run.run_id for run in attempted],
            "states": [run.state for run in attempted],
            "registered_max_runs": int(spec.TIMING["d_candidate_eval_runs"]),
        }
    if unidentifiable:
        return {
            "status": "unidentifiable",
            "run_ids": [run.run_id for run in unidentifiable],
            "states": [run.state for run in unidentifiable],
            "registered_max_runs": int(spec.TIMING["d_candidate_eval_runs"]),
        }
    return {"status": "ok", "registered_max_runs": int(spec.TIMING["d_candidate_eval_runs"])}


def _parse_timestamp(val: Any) -> float:
    """A ledger timestamp as a finite, representable epoch second (r8 F5).

    ''Missing'' (``None``) is distinct from "unparsable" only in the message; both
    refuse.  A value that cannot be rendered as a real datetime (``1e308``,
    NaN/inf, out-of-range) is refused *here*, not silently truncated later.
    """
    if val is None:
        raise LedgerTimestampInvalid("missing timestamp")
    if isinstance(val, bool):
        raise LedgerTimestampInvalid(f"boolean timestamp {val!r}")
    if isinstance(val, (int, float)):
        value = float(val)
    elif isinstance(val, str):
        from datetime import datetime

        try:
            value = datetime.fromisoformat(val).timestamp()
        except (TypeError, ValueError, OverflowError, OSError) as exc:
            raise LedgerTimestampInvalid(f"unparsable timestamp {val!r}: {exc}") from exc
    else:
        raise LedgerTimestampInvalid(f"unsupported timestamp type {type(val).__name__}")
    if not math.isfinite(value):
        raise LedgerTimestampInvalid(f"non-finite timestamp {value!r}")
    from datetime import datetime, timezone

    try:
        datetime.fromtimestamp(value, timezone.utc)
    except (ValueError, OverflowError, OSError) as exc:
        raise LedgerTimestampInvalid(f"unrepresentable timestamp {value!r}: {exc}") from exc
    return value


def _validate_reserved(run) -> float:
    """Raw ``reserved_active_seconds`` validated *before* any ``max`` (r8 F5).

    r7 normalised with ``max(0.0, float(value) or 0.0)``; ``max(0.0, nan)`` is
    ``0.0`` in Python, so a NaN/inf/negative reservation was silently charged as
    zero and the later ``isfinite`` guard could never fire.  Presence, numeric
    type, finiteness and sign are therefore checked first.
    """
    run_id = getattr(run, "run_id", "?")
    if not hasattr(run, "reserved_active_seconds"):
        raise LedgerStateInvalid(f"run {run_id} has no reserved_active_seconds field")
    value = getattr(run, "reserved_active_seconds")
    if value is None:
        raise LedgerStateInvalid(f"run {run_id} has a null reserved_active_seconds")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise LedgerStateInvalid(
            f"run {run_id} reserved_active_seconds is not numeric: {type(value).__name__}"
        )
    value = float(value)
    if not math.isfinite(value):
        raise LedgerStateInvalid(f"run {run_id} has a non-finite reserved_active_seconds {value!r}")
    if value < 0:
        raise LedgerStateInvalid(f"run {run_id} has a negative reserved_active_seconds {value!r}")
    return value


def run_conservative_wall_seconds(run, *, instant: float | None = None) -> float:
    """Conservative wall-clock consumption for a single run (S1 r7/r8).

    - For terminal runs (completed, stopped, failed): max(reserved_active, terminal_at - created_at)
    - For every other lifecycle state: max(reserved_active, now - created_at)
    - Rejects non-finite/unrepresentable/reverse timestamps and a raw
      reservation that is absent, non-numeric, non-finite or negative.
    """
    now = time.time() if instant is None else float(instant)
    if not math.isfinite(now):
        raise LedgerTimestampInvalid(f"accounting instant is not finite: {now!r}")
    run_id = getattr(run, "run_id", "?")
    created_at = _parse_timestamp(getattr(run, "created_at", None))
    updated_at = _parse_timestamp(getattr(run, "updated_at", None))

    if updated_at < created_at:
        raise LedgerTimestampInvalid(
            f"run {run_id} has reverse timestamps: updated {updated_at} < created {created_at}"
        )

    state = getattr(run, "state", None)
    if state is None:
        raise LedgerStateInvalid(f"run {run_id} has no state")
    if state not in KNOWN_STATES:
        raise LedgerStateInvalid(
            f"run {run_id} has an unknown state {state!r}; a corrupt or foreign ledger row "
            "is refused instead of being charged as active or as zero"
        )

    reserved_active = _validate_reserved(run)

    if state in TERMINAL_STATES:
        terminal_elapsed = max(0.0, updated_at - created_at)
        return max(reserved_active, terminal_elapsed)
    # An active row may legitimately have a clock high-water ahead of ``now``
    # (the RunStore keeps one); a negative age is a real zero, not a refusal.
    active_elapsed = max(0.0, now - created_at)
    return max(reserved_active, active_elapsed)


def phase_total_wall_seconds(
    runs, *, instant: float | None = None, experiment_id: str | None = None
) -> float:
    """Total conservative wall-clock time consumed across the phase's runs.

    r11: ``experiment_id`` scopes the total to one registration, so the new
    experiment's 9 x 1200 s budget is measured against its own runs only (the
    old experiment's ~1.2 h stays recorded but is not charged to it).  ``None``
    sums every row, the pre-r11 behaviour.
    """
    rows = runs
    if experiment_id is not None:
        rows = [run for run in runs if getattr(run, "experiment_id", None) == experiment_id]
    return sum(run_conservative_wall_seconds(r, instant=instant) for r in rows)


def phase_ledger_breakdown(
    runs, *, instant: float | None = None, experiment_id: str | None = None
) -> dict:
    """Per-row conservative accounting, for evidence and refusals (S1 r7/r8).

    Each row reports the two candidate quantities separately so a reader can see
    that the terminal interval and the reserved allowance are ``max``-ed per row
    and then summed -- never ``max`` of two global totals, and never the
    calendar age of a terminal row.

    r11: ``experiment_id`` scopes the breakdown to one registration, matching
    :func:`phase_total_wall_seconds`; ``None`` reports every row.
    """
    now = time.time() if instant is None else float(instant)
    if experiment_id is not None:
        runs = [run for run in runs if getattr(run, "experiment_id", None) == experiment_id]
    rows = []
    total = 0.0
    for run in runs:
        counted = run_conservative_wall_seconds(run, instant=now)
        state = getattr(run, "state", None)
        reserved = _validate_reserved(run)
        created_at = _parse_timestamp(run.created_at)
        updated_at = _parse_timestamp(run.updated_at)
        terminal_interval = max(0.0, updated_at - created_at)
        active_age = max(0.0, now - created_at)
        rows.append(
            {
                "run_id": getattr(run, "run_id", None),
                "state": state,
                "reserved_active_seconds": reserved,
                "terminal_interval_seconds": terminal_interval if state in TERMINAL_STATES else None,
                "active_age_seconds": active_age if state in ACTIVE_STATES else None,
                "counted_seconds": counted,
                "rule": "max(reserved, terminal_interval)" if state in TERMINAL_STATES
                else "max(reserved, now-created)",
            }
        )
        total += counted
    return {"total_seconds": total, "rows": rows}



def _budget_block(max_wall_seconds: float, *, max_optimizer_steps: int = 1) -> dict:
    return {
        "max_environment_steps": 1,
        "max_optimizer_steps": int(max_optimizer_steps),
        "max_model_transitions": 0,
        "max_wall_seconds": float(max_wall_seconds),
        "max_daily_active_seconds": 14_400.0,
        "timezone": TIMEZONE,
    }


def _experiment_budget_block(max_wall_seconds: float) -> dict:
    # RunStore requires every experiment-budget field to be positive; the run
    # snapshot keeps model_transitions at 0, which is <= this ceiling.
    return {
        "max_model_runs": 3,
        "max_environment_steps": 1,
        "max_optimizer_steps": 1,
        "max_model_transitions": 1,
        "max_wall_seconds": float(max_wall_seconds),
        "max_calibration_seconds": 60.0,
    }


def prep_experiment_manifest() -> dict:
    return {
        "spec": spec.SPEC_NAME,
        "purpose": "S1 phase-1 preregistration preparation (data generation, no-update smoke)",
        "purpose_kind": "auxiliary_no_training",
        "budget": _budget_block(3_600.0),
        "experiment_budget": _experiment_budget_block(3_600.0),
    }


def train_experiment_manifest(
    *, updates: int, deadline_seconds: float | None = None
) -> dict:
    """The one shared, *stable* training/evaluation experiment manifest (r8 F3).

    r7 built this manifest from the per-run deadline and update count, so the D
    sub-run (``arm1_deadline_seconds``=2 s, 0 updates) and a training run (450 s,
    3510 updates) produced different payloads for the same ``request_id``.  The
    first caller froze the experiment; the second was refused with
    ``request_id was already used for a different payload`` -- and with the D
    values frozen first, the 450 s run exceeded the experiment run-limit and was
    refused with ``run budget exceeds experiment run limits``.

    r8 therefore freezes the *ceiling* only: the experiment admits every
    registered run of the phase (450 s / 3510 updates and the 2 s / 0-update D
    sub-run), while each run snapshot keeps its own, smaller budget.  The payload
    depends on no per-caller value, so D-before-train and train-before-D both hit
    the same immutable experiment and neither resets attempts or the ledger.

    ``deadline_seconds`` is accepted for backward compatibility with the r5
    boundary tests and is deliberately ignored: honouring it is exactly the r8
    F3 defect (a per-run deadline leaking into the shared experiment ceiling).
    """
    ceiling = float(spec.TIMING["phase_wall_max_seconds"])
    bounded_updates = max(1, int(updates))
    return {
        "spec": spec.SPEC_NAME,
        "purpose": "S1 phase-1 registered training/evaluation experiment",
        "budget": _budget_block(ceiling, max_optimizer_steps=bounded_updates),
        "experiment_budget": {
            **_experiment_budget_block(ceiling),
            "max_optimizer_steps": bounded_updates * 12,
            "max_model_runs": 20,
            "max_environment_steps": 1,
            # The ledger requires every experiment ceiling to be positive; the run
            # itself still declares max_model_transitions=0, so this ceiling is a
            # guard, not an allowance (fixed in r2 after the F3 test exposed it).
            "max_model_transitions": 1,
        },
    }



def _canonical_manifest_digest(manifest: Mapping[str, Any]) -> str:
    """The RunStore's own experiment digest (canonical JSON, sorted, compact).

    Mirrors ``RunStore.create_experiment`` exactly: the digest the ledger stores
    in ``experiments.manifest_hash`` is the SHA256 of this canonical payload.
    """
    payload = json.dumps(
        manifest, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _manifest_digest_matches(existing_hash: str | None, expected_hash: str) -> bool:
    """The single comparison that decides whether an existing experiment is reusable.

    Kept as one named function so the r9 sabotage control can remove *only* the
    comparison and show that the refusal then disappears.
    """
    return existing_hash == expected_hash


def ensure_shared_experiment(
    store,
    *,
    manifest: Mapping[str, Any],
    request_id: str,
    experiment_id: str,
):
    """Get-or-create the one shared experiment, verifying its manifest (r9 R1).

    r8 let the D sub-run *create* the shared TRAIN experiment through
    ``open_aux_run`` while the training path called ``create_experiment``
    directly.  ``create_experiment`` is idempotent only for the same
    ``request_id``; with a different request_id and the same experiment ID it
    raises ``experiment_id already exists``.  D-before-train therefore failed,
    and the D path never compared the manifest it found -- it would happily
    attach a 2 s run to whatever experiment carried that ID.

    Both paths now go through this function:

    * experiment absent -> create it with this manifest;
    * experiment present -> reuse it only when the stored ``manifest_hash``
      equals the canonical digest of this manifest; otherwise fail closed with
      :class:`ExperimentManifestMismatch`.

    The generic ``RunStore`` is not modified: no new experiment ID, no reset of
    attempts or totals, no relaxed ``request_id`` protection.
    """
    from ainerzero.runtime.lifecycle import LifecycleError

    expected = _canonical_manifest_digest(manifest)

    def _refuse(existing) -> ExperimentManifestMismatch:
        return ExperimentManifestMismatch(
            f"experiment {experiment_id} already exists with manifest "
            f"{(existing.manifest_hash or '')[:16]}… (request_id "
            f"{existing.request_id!r}), but this caller would register "
            f"{expected[:16]}…; refusing to reuse an experiment with a different manifest"
        )

    try:
        existing = store.get_experiment(experiment_id)
    except KeyError:
        existing = None
    if existing is not None:
        if not _manifest_digest_matches(existing.manifest_hash, expected):
            raise _refuse(existing)
        return existing
    try:
        return store.create_experiment(dict(manifest), request_id, experiment_id)
    except LifecycleError as exc:
        # A concurrent caller may have inserted the same ID between the lookup
        # and the insert.  Re-read and verify; never retry blindly.
        try:
            existing = store.get_experiment(experiment_id)
        except KeyError:
            raise exc
        if not _manifest_digest_matches(existing.manifest_hash, expected):
            raise _refuse(existing) from exc
        return existing


def run_config_snapshot(
    *, wall_budget_seconds: float, purpose: str, max_optimizer_steps: int = 1
) -> dict:
    return {
        "spec": spec.SPEC_NAME,
        "purpose": purpose,
        "budget": _budget_block(
            wall_budget_seconds, max_optimizer_steps=int(max_optimizer_steps)
        ),
        "experiment_budget": _experiment_budget_block(wall_budget_seconds),
    }


class PrepLedger:
    """Card-local RunStore ledger for the preregistration preparation runs."""

    def __init__(self, db_path: Path):
        from ainerzero.runtime.lifecycle import RunStore

        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.store = RunStore(self.db_path)

    def close(self) -> None:
        self.store.close()

    def open_aux_run(
        self,
        *,
        mode: str,
        wall_budget_seconds: float,
        manifest: Mapping[str, Any] | None = None,
        request_id: str | None = None,
        experiment_id: str | None = None,
        snapshot_extra: Mapping[str, Any] | None = None,
    ) -> str:
        target_exp_id = PREP_EXPERIMENT_ID if experiment_id is None else experiment_id
        target_req_id = PREP_REQUEST_ID if request_id is None else request_id
        # r9 R1: an existing experiment is reused only when its manifest digest
        # matches the manifest this caller would register.  r8 looked the
        # experiment up and silently attached the run to it, so the D sub-run
        # could ride on a training experiment registered with different values.
        experiment = ensure_shared_experiment(
            self.store,
            manifest=prep_experiment_manifest() if manifest is None else manifest,
            request_id=target_req_id,
            experiment_id=target_exp_id,
        )
        run_id = uuid4().hex
        snapshot = run_config_snapshot(
            wall_budget_seconds=wall_budget_seconds, purpose=f"preregistration_prep:{mode}"
        )
        # r8 F4: the run snapshot must carry the *product's own* identity fields.
        # r7 relied on a hand-built ``arm_id`` row that no product path created, so
        # the "only one D evaluation" guard could never match the row it had just
        # opened.  ``snapshot_extra`` is filled by the caller with the registered
        # arm/seed/purpose; it is still the same immutable run record.
        if snapshot_extra:
            snapshot.update(dict(snapshot_extra))
        self.store.create_run(
            snapshot,
            f"{target_req_id}:{mode}:{run_id}",
            run_id,
            experiment_id=experiment.experiment_id,
            role="auxiliary",
        )
        self.store.transition(run_id, "initializing", reason=f"prep_mode={mode}")
        return run_id


    def begin_work(self, run_id: str, *, work_state: str) -> None:
        self.store.transition(run_id, work_state, reason="worker_started")

    def reserve(self, run_id: str, *, active_seconds: float, optimizer_steps: int = 0) -> None:
        from ainerzero.runtime.lifecycle import BudgetExceeded

        try:
            self.store.consume(
                run_id, active_seconds=float(active_seconds), optimizer_steps=int(optimizer_steps)
            )
        except BudgetExceeded as exc:
            raise BudgetStop(f"{exc.reason}") from exc

    def finish(self, run_id: str, state: str, reason: str) -> dict:
        from ainerzero.runtime.lifecycle import TERMINAL_STATES

        record = self.store.get_run(run_id)
        if record.state in TERMINAL_STATES:
            return record.to_dict()
        if state == "stopped" and record.state not in ("stopping",):
            # The lifecycle has no direct work-state -> stopped edge; stop via stopping.
            self.store.transition(run_id, "stopping", reason=reason)
        self.store.transition(run_id, state, reason=reason)
        return self.store.get_run(run_id).to_dict()

    def get(self, run_id: str) -> dict:
        return self.store.get_run(run_id).to_dict()


def _run_dir_for(output_root: Path, run_id: str) -> Path:
    return Path(output_root) / "runs" / run_id


@contextmanager
def ledger_read_snapshot(ledger_path: Path):
    """Open a throw-away read-only *snapshot* of the ledger for the entry preflight.

    r12 order fix (P31-LEDGER-INCIDENT-RULING): every CPU-only entry
    precondition must be decided before the first ledger write, and a refusal
    must leave the ledger bytes untouched.  ``RunStore`` cannot be used for that
    read: its ``_initialize`` opens a transaction and rewrites the file even when
    the caller only lists runs (measured: the SHA256 changes on open/close).  The
    preflight therefore copies the ledger through SQLite's online backup API into
    a temporary directory and opens the *copy* with the ordinary
    :class:`PrepLedger`, so the product's row mapping and every guard stay the
    same code and only the file they read differs.

    This is not a write path: every real write still goes through
    ``PrepLedger``/``RunStore`` on the central ledger after the preflight passes.
    """
    ledger_path = Path(ledger_path)
    temporary = Path(tempfile.mkdtemp(prefix="s1-ledger-preflight-"))
    snapshot = temporary / ledger_path.name
    try:
        source = sqlite3.connect(f"file:{ledger_path}?mode=ro", uri=True)
        try:
            target = sqlite3.connect(snapshot)
            try:
                source.backup(target)
            finally:
                target.close()
        finally:
            source.close()
        snapshot_ledger = PrepLedger(snapshot)
        try:
            yield snapshot_ledger
        finally:
            snapshot_ledger.close()
    finally:
        shutil.rmtree(temporary, ignore_errors=True)


def _completion_precondition(
    *,
    report: dict,
    ledger: "PrepLedger",
    run_id: str,
    protocol: "completion.CompletionProtocol",
    output_root: Path,
    kind: str,
) -> dict | None:
    """Refuse a completion attempt that must not become ``completed`` (r9 R2).

    P24's F1 probe called the internal ``_complete_run`` a second time, after a
    truncation point had already been refused and had written
    ``completion_invalid.json``.  The second call walked straight to
    ``ledger.finish(run_id, "completed")``; the row was already terminal, so the
    ledger returned it unchanged and the report claimed ``completed`` -- even
    when the row said ``failed``.  A marker on disk was never consulted.

    The rule enforced here, before anything else runs:

    * an existing invalidation marker -> refuse (the run is already invalid for
      every consumer);
    * a terminal ledger state other than ``completed`` -> refuse and report that
      state;
    * otherwise continue (a re-read of an already ``completed`` run without a
      marker stays legal: it changes nothing and claims nothing new).

    Nothing is deleted, rewritten or refunded: the existing marker and the
    terminal row are left exactly as they are, and no new marker is invented.
    Returns the refusal report, or ``None`` when the attempt may proceed.
    """
    run_dir = _run_dir_for(output_root, run_id)
    markers = completion.invalid_markers(run_dir)
    try:
        state = ledger.get(run_id).get("state")
    except Exception:  # pragma: no cover - ledger unreadable
        state = None

    if markers:
        stage = "completion_already_invalid"
        detail = (
            f"{len(markers)} invalidation marker(s) already exist for this run; it was "
            "refused earlier and may not be reported as completed"
        )
    elif state in TERMINAL_STATES and state != "completed":
        stage = "ledger_terminal_not_completed"
        detail = (
            f"the ledger already holds terminal state {state!r}; a completion claim on a "
            "terminal row that is not 'completed' is not a completion"
        )
    else:
        return None

    report.update(
        {
            "status": "refused",
            "refused_stage": stage,
            "ledger_state": state,
            "ledger_state_is_completed": state == "completed",
            "completion_invalid_markers": [str(path) for path in markers],
            "completion_protocol": protocol.record(phase=f"{kind}:refused_precondition"),
            "rolled_back": False,
            "message": detail
            + ". The marker and the terminal row are left untouched; this adapter neither "
            "rewrites a terminal state nor refunds a budget.",
        }
    )
    return report


def _complete_run(
    *,
    report: dict,
    ledger: "PrepLedger",
    run_id: str,
    protocol: completion.CompletionProtocol,
    output_root: Path,
    reason: str,
    kind: str,
) -> dict:
    """Unified terminal commit for every bounded mode (S1-R8-DECISION F1).

    The success path is one protocol: a pre-commit deadline check, the commit
    itself under an in-flight watchdog, and a post-commit check.  A refusal never
    returns ``completed``.  When the commit already happened, the row is left as
    it is (append-only) and an immutable ``completion_invalid.json`` marker makes
    every consumer refuse the run; the report says so explicitly.

    r9 R2: the attempt is additionally refused up front when the run is already
    invalid (marker on disk) or already terminal in a non-``completed`` state.
    """
    run_dir = _run_dir_for(output_root, run_id)
    blocked = _completion_precondition(
        report=report,
        ledger=ledger,
        run_id=run_id,
        protocol=protocol,
        output_root=output_root,
        kind=kind,
    )
    if blocked is not None:
        return blocked

    def _ledger_state() -> str | None:
        try:
            return ledger.get(run_id).get("state")
        except Exception:  # pragma: no cover - ledger unreadable
            return None

    def _refuse(exc: Exception, *, stage: str, reason_text: str) -> dict:
        state_before = _ledger_state()
        marker = completion.write_invalid_marker(
            run_dir,
            protocol=protocol,
            phase=f"{kind}:terminal_commit",
            reason=reason_text,
            ledger_state=state_before,
            detail=f"{type(exc).__name__}: {exc}",
        )
        # If the terminal row was never written, record an honest failure.  A
        # committed terminal row is never rewritten or refunded.
        if state_before not in TERMINAL_STATES:
            try:
                ledger.finish(run_id, "failed", f"{kind}_completion_invalid:{reason_text}")
            except Exception:
                pass
        report.update(
            {
                "status": "failed",
                "refused_stage": stage,
                "error": f"{type(exc).__name__}: {exc}",
                "completion_protocol": protocol.record(phase=f"{kind}:refused"),
                "completion_invalid_marker": str(marker),
                "ledger_state_at_refusal": _ledger_state(),
                "ledger_state_before_refusal": state_before,
                "rolled_back": False,
                "message": "the frozen per-run deadline/completion protocol refused this "
                "run; the run is not completed and no consumer may accept it. A terminal "
                "row that was already committed is left untouched (append-only).",
            }
        )
        return report

    try:
        protocol.check(f"{kind}:pre_terminal_commit")
        record = ledger.get(run_id)
        budget = ((record.get("config_snapshot") or {}).get("budget") or {})
        wall_cap = float(budget.get("max_wall_seconds", 0.0) or 0.0)
        reserved = float(record.get("reserved_active_seconds", 0.0) or 0.0)
        if wall_cap <= 0 or reserved > wall_cap + 1e-9:
            raise completion.CompletionUncertain(
                f"the run reserved {reserved}s against a {wall_cap}s wall allowance; a "
                "completion claim would exceed the registered run budget"
            )
        report["completion_protocol"] = protocol.record(phase=f"{kind}:pre_terminal_commit")
    except completion.CompletionDeadlineExceeded as exc:
        return _refuse(exc, stage="completion_deadline_exceeded", reason_text="deadline_exceeded")
    except completion.CompletionError as exc:
        return _refuse(exc, stage="completion_budget_inconsistent", reason_text="budget_inconsistent")

    try:
        finished = protocol.run_monitored(
            f"{kind}:terminal_commit", lambda: ledger.finish(run_id, "completed", reason)
        )
    except completion.CompletionDeadlineExceeded as exc:
        return _refuse(
            exc, stage="completion_deadline_exceeded", reason_text="deadline_exceeded_in_commit"
        )
    except Exception as exc:  # a commit error is not a completed run
        return _refuse(exc, stage="completion_commit_error", reason_text="commit_error")

    report["run"] = finished
    report["completion_protocol"] = protocol.record(phase=f"{kind}:terminal_commit")
    report["status"] = "completed"
    return report


def _prepare_limits(limits: Mapping[str, Any]) -> dict:
    reasons = resource_gate.validate_limits(limits)
    if reasons:
        raise resource_gate.ResourceGateRefused(reasons)
    return dict(limits)


def _require_approval(
    document: Mapping[str, Any], document_sha256: str, research_log: Path | None
) -> dict:
    """Worker-side approval gate (defence in depth, independent of the supervisor).

    Returns ``{"approved": True, ...}`` or a refusal record; never raises, so the
    refusal can be written to the ledger report instead of escaping as a crash.
    """
    try:
        return prereg.require_coordinator_approval(
            document, document_sha256, log_path=research_log
        )
    except prereg.ApprovalRefused as exc:
        return {
            "approved": False,
            "reasons": exc.reasons,
            "detail": exc.detail,
            "status_field_is_authoritative": False,
        }


def run_worker(
    mode: str,
    *,
    output_root: Path,
    limits: Mapping[str, Any],
    wall_budget_seconds: float,
    prereg_path: Path | None = None,
    research_log: Path | None = None,
    run_id: str | None = None,
    arm: str | None = None,
    seed: int | None = None,
    backend: Any = None,
) -> dict:
    """Execute one prep mode inside the RunStore ledger and return its report."""
    output_root = Path(output_root)
    limits = _prepare_limits(limits)
    if mode not in ("data", "smoke", "verify", "train", "eval", "final-eval"):
        raise ValueError(f"unknown worker mode {mode!r}")
    # r6 budget anchor: a bounded run (train/eval) registers in the one central
    # RunStore under the canonical phase-1 root and only runs at that root.  A
    # copied output root, a different cwd, another checkout or a copied
    # preregistration must not reset the arm x seed attempt guard or the phase
    # wall total; a missing/unreadable/unrecognized central ledger fails closed
    # and is never re-created.
    ledger_path = output_root / "control.sqlite3"
    if mode in BOUNDED_MODES:
        anchor_state = spec.host_anchor_state()
        if anchor_state["status"] != "ok":
            return {
                "schema": "ainerzero.v9.s1.worker_report.v1",
                "spec": spec.SPEC_NAME,
                "mode": mode,
                "no_update": mode != "train",
                "control_db": str(ledger_path.resolve()),
                "status": "refused",
                "refused_stage": f"host_anchor_{anchor_state['status']}",
                "host_anchor": anchor_state,
                "message": "the registered host anchor is missing, unreadable or "
                "inconsistent; a bounded run fails closed instead of inventing an anchor",
            }
        ledger_path = canonical_ledger_path()
        anchor_ledger = Path(anchor_state["ledger"])
        if Path(ledger_path).resolve() != anchor_ledger.resolve():
            return {
                "schema": "ainerzero.v9.s1.worker_report.v1",
                "spec": spec.SPEC_NAME,
                "mode": mode,
                "no_update": mode != "train",
                "control_db": str(ledger_path.resolve()),
                "status": "refused",
                "refused_stage": "host_anchor_mismatch",
                "host_anchor": anchor_state,
                "message": "the phase-1 root and the registered host anchor disagree; every "
                "bounded path (run root, ledger, approval log, lock) must use the same anchor",
            }
        ledger_state = canonical_ledger_state(ledger_path)
        if ledger_state["status"] != "ok":
            return {
                "schema": "ainerzero.v9.s1.worker_report.v1",
                "spec": spec.SPEC_NAME,
                "mode": mode,
                "no_update": mode != "train",
                "control_db": str(ledger_path.resolve()),
                "status": "refused",
                "refused_stage": f"central_ledger_{ledger_state['status']}",
                "ledger": ledger_state,
                "message": "the central S1 phase-1 RunStore is missing, unreadable or "
                "unrecognized; a bounded run fails closed and never creates a new ledger",
            }
        if output_root.resolve() != spec.PHASE1_ROOT.resolve():
            return {
                "schema": "ainerzero.v9.s1.worker_report.v1",
                "spec": spec.SPEC_NAME,
                "mode": mode,
                "no_update": mode != "train",
                "control_db": str(ledger_path.resolve()),
                "status": "refused",
                "refused_stage": "output_root_not_canonical",
                "output_root": str(output_root.resolve()),
                "canonical_output_root": str(spec.PHASE1_ROOT.resolve()),
                "message": "train/eval only run at the canonical S1 phase-1 root; the "
                "central RunStore ledger and the phase budget are anchored there and a "
                "copied run root cannot reset them",
            }
    started = time.perf_counter()
    report: dict[str, Any] = {
        "schema": "ainerzero.v9.s1.worker_report.v1",
        "spec": spec.SPEC_NAME,
        "mode": mode,
        "no_update": mode != "train",
        "control_db": str(Path(ledger_path).resolve()),
        "status": "failed",
    }
    # Startup gate before any ledger or compute.
    gate_snapshot = resource_gate.assert_start(limits, root=output_root)
    report["resource_gate"] = {
        "status": "passed",
        "limits": limits,
        "snapshot": gate_snapshot.to_dict(),
    }
    guard = resource_gate.RuntimeGuard(
        limits, root=output_root, initial_swap_bytes=gate_snapshot.swap_used_bytes, min_interval_seconds=0.0
    )
    # r12 order fix: the ledger object is created only after every CPU-only
    # entry precondition passed.  Opening a RunStore runs a transaction and
    # rewrites the ledger file, so constructing it up front made every refusal
    # below leave different bytes behind even though nothing was registered
    # (P31-LEDGER-INCIDENT-RULING).  ``ledger`` therefore starts as None and the
    # guards read a read-only snapshot instead.
    ledger: PrepLedger | None = None
    active_run = run_id
    try:
        if mode == "train":
            # The training branch is implemented but only runs on a coordinator-
            # approved frozen file; this card never approves it.
            if prereg_path is None:
                raise SystemExit("train mode requires --prereg")

            verified = prereg.verify_frozen_file(prereg_path)
            document = verified["document"]
            # P-1: the worker reads the same canonical log as the supervisor; a
            # redirected path is refused instead of being honoured.
            canonical_log = Path(spec.RESEARCH_LOG)
            requested_log = Path(research_log) if research_log is not None else canonical_log
            if requested_log.resolve() != canonical_log.resolve():
                report.update(
                    {
                        "status": "refused",
                        "refused_stage": "research_log_not_canonical",
                        "prereg_path": str(prereg_path),
                        "prereg_sha256": verified["sha256"],
                        "requested_research_log": str(requested_log),
                        "canonical_research_log": str(canonical_log),
                        "message": "train only reads the repository RESEARCH_LOG.md",
                    }
                )
                return report
            approval = _require_approval(document, verified["sha256"], research_log)
            if not approval.get("approved"):
                report.update(
                    {
                        "status": "refused",
                        "refused_stage": "preregistration_not_approved",
                        "prereg_path": str(prereg_path),
                        "prereg_sha256": verified["sha256"],
                        "approval": approval,
                        "message": "S1 phase-1 training requires the coordinator's approval "
                        f"line inside the '## {prereg.APPROVAL_SECTION}' section of "
                        "RESEARCH_LOG.md for this exact document SHA256; the "
                        "preregistration status field is not an approval",
                    }
                )
                return report
            # P-2 / P-3: the code and the data must still be the frozen ones.
            binding = prereg.source_binding_state(document)
            if binding["status"] != "passed":
                report.update(
                    {
                        "status": "refused",
                        "refused_stage": "source_binding_drift",
                        "prereg_path": str(prereg_path),
                        "prereg_sha256": verified["sha256"],
                        "source_binding": binding,
                        "message": "the frozen document binds source files whose SHA256 no "
                        "longer match the files on disk",
                    }
                )
                return report
            dataset = data.dataset_binding_state(
                output_root, (document.get("data_identity") or {}).get("dataset_digest")
            )
            if dataset["status"] != "passed":
                report.update(
                    {
                        "status": "refused",
                        "refused_stage": "dataset_identity_mismatch",
                        "prereg_path": str(prereg_path),
                        "prereg_sha256": verified["sha256"],
                        "dataset": dataset,
                        "message": "the dataset this run root resolves to does not match "
                        "data_identity.dataset_digest",
                    }
                )
                return report

            if arm not in ("arm2", "arm3", "arm4"):
                raise ValueError(f"train mode requires --arm in ('arm2', 'arm3', 'arm4'), got {arm!r}")
            if seed is None or seed not in (0, 1, 2):
                raise ValueError(f"train mode requires --seed in (0, 1, 2), got {seed!r}")

            # r14 (ainerzero.V9.P49): an inherited cell is never retrained under the
            # new identity; eval binds it to its source run.  Decided before the
            # first ledger write.
            inherited = inherited_cell(document, arm_id=arm, seed=seed)
            if inherited is not None:
                report.update(
                    {
                        "status": "refused",
                        "refused_stage": "inherited_cell_not_trainable",
                        "arm": arm,
                        "seed": seed,
                        "inherited": inherited,
                        "message": f"arm {arm} seed {seed} is inherited from "
                        f"{inherited['source_experiment_id']} run {inherited['source_run_id']}; "
                        "it is not retrained under this registration",
                    }
                )
                return report

            # Guard: any *started* arm x seed attempt forbids an unauthorized rerun,
            # not only a completed one.  A pre-start resource refusal never reaches
            # this point (no run row exists), so the ledger stays authoritative.
            # r11: the count is scoped to the registered experiment; every other
            # document keeps the whole-ledger guard (see document_experiment_scope).
            # r12: the guard reads a read-only snapshot, so this refusal cannot
            # change a single ledger byte.
            experiment_id = document_experiment_id(document) or TRAIN_EXPERIMENT_ID
            scope = document_experiment_scope(document)
            # Guard: check phase total wall clock budget <= 14400s (conservative S1 r7/r8 accounting)
            # r11: scoped to this registration's experiment (the new experiment's
            # 9 x 1200 s budget is not charged with the old experiment's runs).
            phase_cap = float(document["timing"].get("phase_wall_max_seconds", 14400.0))
            deadline = float(document["timing"]["deadline_seconds"])
            with ledger_read_snapshot(ledger_path) as preflight:
                runs = preflight.store.list_runs()
                attempts = train_attempts(runs, arm_id=arm, seed=seed, experiment_id=scope)
                try:
                    total_wall = phase_total_wall_seconds(runs, experiment_id=scope)
                except (LedgerAccountingError, OverflowError) as exc:
                    # r8 F2/F5: say *what* is wrong instead of always blaming timestamps.
                    stage = (
                        "ledger_state_invalid"
                        if isinstance(exc, LedgerStateInvalid)
                        else "ledger_timestamp_invalid"
                    )
                    report.update(
                        {
                            "status": "refused",
                            "refused_stage": stage,
                            "accounting_error_type": type(exc).__name__,
                            "message": f"central ledger contains a row the conservative phase "
                            f"accounting refuses: {exc}",
                        }
                    )
                    return report
            if attempts:
                first = attempts[0]
                report.update(
                    {
                        "status": "refused",
                        "refused_stage": "already_attempted",
                        "arm": arm,
                        "seed": seed,
                        "run_id": first.run_id,
                        "attempt_states": [r.state for r in attempts],
                        "attempt_run_ids": [r.run_id for r in attempts],
                        "message": f"arm {arm} seed {seed} already has a registered attempt "
                        f"({first.run_id}, state={first.state}); rerun is forbidden",
                    }
                )
                return report

            if total_wall + deadline > phase_cap:
                report.update(
                    {
                        "status": "refused",
                        "refused_stage": "phase_budget_exceeded",
                        "total_wall_seconds": total_wall,
                        "deadline_seconds": deadline,
                        "phase_wall_max_seconds": phase_cap,
                        "message": f"phase wall budget would be exceeded: total {total_wall:.1f}s + deadline {deadline:.1f}s > {phase_cap:.1f}s",
                    }
                )
                return report

            report["prereg_sha256"] = verified["sha256"]
            report["approval"] = approval
            report["source_binding"] = {"status": binding["status"]}
            report["dataset"] = {
                "status": dataset["status"],
                "dataset_digest": dataset.get("actual_dataset_digest"),
            }
            # r12: every CPU-only precondition above is decided; the first
            # ledger write may now happen.
            ledger = PrepLedger(ledger_path)
            if active_run is None:
                try:
                    active_run = _open_train_run(
                        document, ledger, approval, arm_id=arm, seed=seed
                    )
                except ExperimentManifestMismatch as exc:
                    # r9 R1: the shared experiment ID already exists with a
                    # different manifest.  Reusing it would put this run's
                    # registered budget under somebody else's registration.
                    report.update(
                        {
                            "status": "refused",
                            "refused_stage": "train_experiment_manifest_mismatch",
                            "experiment_id": experiment_id,
                            "error": f"{type(exc).__name__}: {exc}",
                            "message": "the shared phase-1 experiment already exists with a "
                            "different manifest; the training path refuses to reuse it",
                        }
                    )
                    return report
            report["run_id"] = active_run
            ledger.begin_work(active_run, work_state="training")
            # r8 F1: one timer for the whole bounded run -- training loop, final
            # metadata/receipt IO and the ledger terminal commit share it.
            protocol = completion.CompletionProtocol(deadline_seconds=deadline)
            details = _train(
                document,
                output_root,
                ledger,
                active_run,
                guard,
                arm_id=arm,
                seed=seed,
                prereg_sha256=verified["sha256"],
                deadline_protocol=protocol,
                # r8 F8: the public run_worker train branch forwards the CPU test
                # double into _train, so the *whole* public control flow (gate,
                # attempts, ledger, completion protocol) is reviewable without MLX.
                # This is an internal seam; the CLI never exposes it.
                backend=backend,
            )
            report["details"] = details
            receipt = details.get("receipt") if isinstance(details, Mapping) else None
            if receipt:
                reason = TRAIN_RECEIPT_PREFIX + json.dumps(
                    receipt, ensure_ascii=False, sort_keys=True, separators=(",", ":")
                )
            else:
                # Only a test double returns no receipt; a real _train always does.
                # Eval refuses such a run because it cannot bind an original SHA.
                reason = "s1_train_completed"
            return _complete_run(
                report=report,
                ledger=ledger,
                run_id=active_run,
                protocol=protocol,
                output_root=output_root,
                reason=reason,
                kind="train",
            )


        if mode == "final-eval":
            # ainerzero.V9.P59: every precondition is CPU-only and writes nothing; the
            # first ledger write opens the one final run; only then is READ_ONCE created
            # and the sealed final partition read, inside read_once_and_score.
            from . import final_eval as final_module

            if prereg_path is None or not Path(prereg_path).is_file():
                raise SystemExit("final-eval mode needs the frozen final evaluation document (--prereg)")
            verified = prereg.verify_frozen_file(prereg_path)
            document = verified["document"]
            pre = final_module.preconditions(
                document=document,
                verified=verified,
                output_root=output_root,
                ledger_path=ledger_path,
                research_log=research_log,
                wall_budget_seconds=float(wall_budget_seconds),
            )
            if pre.get("status") != "ok":
                report.update(pre)
                return report
            report["final_preconditions"] = {k: v for k, v in pre.items() if k not in ("section", "approval")}
            report["approval"] = pre["approval"]
            ledger = PrepLedger(ledger_path)
            active_run = active_run or ledger.open_aux_run(
                mode="eval",
                wall_budget_seconds=pre["budget"],
                manifest=train_experiment_manifest(updates=int(document["training_protocol"]["updates"])),
                request_id=f"{spec.FINAL_EXPERIMENT_ID}:final-eval",
                experiment_id=spec.FINAL_EXPERIMENT_ID,
                snapshot_extra={
                    "arm_id": "final-suite",
                    "seed": 0,
                    "purpose": "s1_phase1_final_eval",
                    "preregistration_sha256": verified["sha256"],
                    "sealed_dataset_digest": pre["section"]["sealed_dataset_digest"],
                },
            )
            report["run_id"] = active_run
            report["experiment_id"] = spec.FINAL_EXPERIMENT_ID
            ledger.begin_work(active_run, work_state="validating")
            protocol = completion.CompletionProtocol(deadline_seconds=pre["budget"])
            ledger.reserve(active_run, active_seconds=min(600.0, pre["budget"]))
            guard.sample(force=True)
            report["details"] = final_module.read_once_and_score(
                document=document,
                verified=verified,
                output_root=output_root,
                section=pre["section"],
                backend=backend,
                guard=guard,
                run_id=active_run,
            )
            return _complete_run(
                report=report,
                ledger=ledger,
                run_id=active_run,
                protocol=protocol,
                output_root=output_root,
                reason="s1_final_eval_completed",
                kind="final_eval",
            )

        if mode == "eval":
            if prereg_path is None:
                prereg_path = output_root / "pre_registration.json"
            if not prereg_path.is_file():
                raise SystemExit("eval mode needs a frozen preregistration file")
            verified = prereg.verify_frozen_file(prereg_path)
            document = verified["document"]
            if arm not in ("arm1", "arm2", "arm3", "arm4"):
                raise ValueError(f"eval mode requires --arm in ('arm1', 'arm2', 'arm3', 'arm4'), got {arm!r}")
            eval_seed = 0 if seed is None else int(seed)
            budget = float(wall_budget_seconds)
            # r6 fail-closed evaluation gates (coordinator messages 386): the r5
            # eval entry only verified the frozen file, then started a suite whose
            # call volume is far beyond the registered eval_batches=48.  A real
            # eval must verify the current source binding, refuse the arm1
            # candidate path (it has no trained checkpoint to bind), and refuse
            # before starting when the registered call budget cannot cover even
            # the frozen window-probe batches.  No unaccounted suite is started.
            source_state = prereg.source_binding_state(document)
            if source_state.get("status") != "passed":
                report.update(
                    {
                        "status": "refused",
                        "refused_stage": "source_binding_drift",
                        "source_binding": source_state,
                        "message": "the frozen document no longer matches the bound "
                        "sources; eval refuses instead of scoring drifted code",
                    }
                )
                return report
            # r11: the registered experiment scopes the D-candidate guard and the
            # aux-run registration below; every other document keeps the
            # whole-ledger guard (see document_experiment_scope).  r12: the D
            # guard reads a read-only snapshot, so its refusal writes nothing.
            eval_experiment_id = document_experiment_id(document) or TRAIN_EXPERIMENT_ID
            eval_scope = document_experiment_scope(document)
            if arm == "arm1":
                # r8 F7: the identity check is a stdlib-only byte operation, so the
                # CPU entry path does not import MLX through ``arms``.
                from . import identity as identity_module

                # Verify A2-pinned D candidate identity (manifest bytes + original
                # self digest + every pinned file + registered field digests)
                try:
                    d_identity = identity_module.verify_d_candidate_identity(
                        repo_root=spec.REPO_ROOT
                    )
                except Exception as exc:
                    report.update(
                        {
                            "status": "refused",
                            "refused_stage": "arm1_identity_verification_failed",
                            "error": f"{type(exc).__name__}: {exc}",
                            "message": f"arm1 A2 pinned manifest or tensor identity verification failed: {exc}",
                        }
                    )
                    return report

                # r8 F4: the "only one D evaluation" guard reads the *product's own*
                # rows (``arm_id`` is written by open_aux_run below), and fails closed
                # on an older row that looks like a D attempt but carries no arm_id.
                # r11: scoped to this document's experiment registration (None keeps
                # the pre-r11 whole-ledger behaviour).  r12: read-only snapshot.
                with ledger_read_snapshot(ledger_path) as preflight:
                    guard_state = d_candidate_attempt_state(
                        preflight.store.list_runs(), experiment_id=eval_scope
                    )
                report["d_candidate_attempts"] = guard_state
                if guard_state["status"] == "unidentifiable":
                    report.update(
                        {
                            "status": "refused",
                            "refused_stage": "d_candidate_attempt_unidentifiable",
                            "message": "the central ledger holds an older row that may be a D "
                            "candidate attempt but carries no arm_id; it must be verified by a "
                            "coordinator before another D run. History is not deleted or rewritten.",
                        }
                    )
                    return report
                if guard_state["status"] == "already_attempted":
                    report.update(
                        {
                            "status": "refused",
                            "refused_stage": "already_attempted",
                            "attempt_states": guard_state["states"],
                            "attempt_run_ids": guard_state["run_ids"],
                            "message": "arm1 (frozen D candidate) evaluation has already been "
                            "attempted in the central ledger (registered max is 1 run)",
                        }
                    )
                    return report

                # r8 F3: the D sub-run is registered with the *frozen* arm1 budget
                # (2 s work deadline, supervision 52 s outside), never with the
                # generic eval entry budget (300 s), and its single pre-work
                # reservation fits inside that 2 s ceiling.
                d_budget = float(document["timing"]["arm1_deadline_seconds"])
                if not (0 < d_budget <= float(document["timing"]["per_run_wall_max_seconds"])):
                    raise ValueError(
                        f"frozen arm1_deadline_seconds {d_budget!r} is not a usable run budget"
                    )
                # r12: the D path has no further CPU-only precondition; its first
                # ledger write may now happen.
                ledger = PrepLedger(ledger_path)
                if active_run is None:
                    try:
                        active_run = ledger.open_aux_run(
                            mode="eval",
                            wall_budget_seconds=d_budget,
                            manifest=train_experiment_manifest(
                                updates=int(document["training_protocol"]["updates"])
                            ),
                            request_id=f"{eval_experiment_id}:eval:arm1",
                            experiment_id=eval_experiment_id,
                            snapshot_extra={
                                "arm_id": "arm1",
                                "seed": int(eval_seed),
                                "purpose": "s1_phase1_d_candidate_eval:arm1",
                                "preregistration_sha256": verified["sha256"],
                                "d_candidate_identity": {
                                    "frozen_manifest_digest": d_identity["frozen_manifest_digest"],
                                    "tensors_sha256": d_identity["tensors_sha256"],
                                    "checkpoint_id": d_identity["checkpoint_id"],
                                },
                                "d_eval_runs_registered": int(spec.TIMING["d_candidate_eval_runs"]),
                            },
                        )
                    except ExperimentManifestMismatch as exc:
                        # r9 R1: D reuses the training experiment only when the
                        # manifest digest matches; a foreign manifest fails closed
                        # here instead of attaching the run to it.
                        report.update(
                            {
                                "status": "refused",
                                "refused_stage": "train_experiment_manifest_mismatch",
                                "experiment_id": eval_experiment_id,
                                "error": f"{type(exc).__name__}: {exc}",
                                "message": "the shared phase-1 experiment already exists with a "
                                "different manifest; the D sub-run refuses to reuse it",
                            }
                        )
                        return report
                report["run_id"] = active_run
                report["experiment_id"] = eval_experiment_id
                ledger.begin_work(active_run, work_state="validating")
                protocol = completion.CompletionProtocol(deadline_seconds=d_budget)
                # Pre-work reservation, bounded by the same frozen 2 s allowance:
                # the old floor of 5 s silently exceeded the D death line (P21 F3).
                # Half of the frozen allowance (1 s of 2 s) is one unit that fits
                # inside the run budget with headroom: reserving the *remaining*
                # allowance exactly is refused, because the wall clock advances
                # between reading ``remaining`` and the atomic consume (the same
                # "pre-work reservations arrive faster than the clock" race the
                # store documents), and that refusal would stop the D run before
                # its work.
                reserved_now = float(ledger.get(active_run)["remaining"]["wall_seconds"])
                ledger.reserve(
                    active_run,
                    active_seconds=min(0.5 * d_budget, max(0.0, reserved_now)),
                )
                guard.sample(force=True)

                eval_details = _evaluate_arm(
                    document,
                    output_root,
                    arm_id="arm1",
                    seed=eval_seed,
                    prereg_sha256=verified["sha256"],
                    backend=backend,
                )
                report["eval_details"] = eval_details
                report["details"] = eval_details
                report["d_candidate_identity"] = d_identity
                return _complete_run(
                    report=report,
                    ledger=ledger,
                    run_id=active_run,
                    protocol=protocol,
                    output_root=output_root,
                    reason="arm1_d_candidate_evaluated",
                    kind="eval_arm1",
                )
            protocol = document["training_protocol"]
            registered_batches = int(protocol.get("eval_batches", 0))
            try:
                windows = data.load_development_windows(
                    data.resolve_dataset_dir(output_root)
                )
                window_count = int(windows["obs"].shape[0])
            except Exception as exc:  # missing/unreadable dataset -> fail closed
                report.update(
                    {
                        "status": "refused",
                        "refused_stage": "eval_dataset_unavailable",
                        "error": f"{type(exc).__name__}: {exc}",
                        "message": "the development windows needed to account the "
                        "evaluation call volume are unavailable; eval fails closed",
                    }
                )
                return report
            batch_size = max(1, int(protocol["batch_size"]))
            checkpoints = len(
                [int(v) for v in protocol.get("checkpoint_updates") or []]
            ) or 1
            window_batches = checkpoints * math.ceil(window_count / batch_size)
            call_plan = {
                "development_windows": window_count,
                "window_batches_per_checkpoint": math.ceil(window_count / batch_size),
                "checkpoints": checkpoints,
                "window_probe_batches": window_batches,
                "registered_eval_batches": registered_batches,
                "suite_groups_beyond_window_probe": [
                    "topology step_sequence/probe_graph",
                    "few-shot support/query step_sequence + 2 encodes per query",
                    "M2 three-condition probes",
                    "sample-efficiency reload probes",
                ],
            }
            if registered_batches <= 0 or window_batches > registered_batches:
                report.update(
                    {
                        "status": "refused",
                        "refused_stage": "eval_call_budget_exceeded",
                        "eval_call_plan": call_plan,
                        "message": f"the frozen eval_batches={registered_batches} cannot "
                        f"cover the frozen window-probe batches ({window_batches}); the "
                        "r5 disclosure said the suite exceeds this registration. Eval "
                        "fails closed until a coordinator registers a sufficient eval "
                        "call budget (no silent expansion).",
                    }
                )
                return report
            # r12 (P31-LEDGER-INCIDENT-RULING): the arm x seed binding is a
            # CPU-only precondition -- the ledger and the bound run directory are
            # all it reads -- so it is decided *before* the first ledger write.
            # Until r11 the entry registered the experiment, the run, the
            # begin_work transition and the reservation first and only then let
            # ``_evaluate_arm`` raise ``EvalBindingError``, which is how the P31
            # review wrote three production ledger rows for an eval that could
            # never run.  Same check, earlier position; the refusal writes
            # nothing.
            binding_precondition = _eval_binding_precondition(
                output_root,
                arm_id=arm,
                seed=eval_seed,
                prereg_sha256=verified["sha256"],
                updates=int(document["training_protocol"]["updates"]),
                ledger_path=ledger_path,
                document=document,
            )
            if binding_precondition["status"] != "ok":
                report.update(
                    {
                        "status": "refused",
                        "refused_stage": binding_precondition["refused_stage"],
                        "eval_binding": binding_precondition,
                        "message": binding_precondition["message"],
                    }
                )
                return report
            report["eval_binding"] = binding_precondition
            # r12: every CPU-only precondition passed; the first ledger write may
            # now happen.
            ledger = PrepLedger(ledger_path)
            # r6: evaluation consumption is registered inside the same
            # experiment as the training runs it scores, so the phase total
            # sees it.  The r1 preparation experiment's wall window has long
            # closed, so reusing it would refuse every eval at the canonical
            # root with an expired experiment wall budget.
            active_run = active_run or ledger.open_aux_run(
                mode="eval",
                wall_budget_seconds=budget,
                manifest=train_experiment_manifest(
                    updates=int(document["training_protocol"]["updates"])
                ),
                request_id=f"{eval_experiment_id}:training",
                experiment_id=eval_experiment_id,
                snapshot_extra={
                    "arm_id": arm,
                    "seed": int(eval_seed),
                    "purpose": f"s1_phase1_eval:{arm}",
                    "preregistration_sha256": verified["sha256"],
                },
            )
            report["run_id"] = active_run
            report["experiment_id"] = eval_experiment_id
            ledger.begin_work(active_run, work_state="validating")
            protocol = completion.CompletionProtocol(deadline_seconds=budget)
            ledger.reserve(active_run, active_seconds=min(120.0, max(10.0, 0.5 * budget)))
            guard.sample(force=True)
            eval_details = _evaluate_arm(
                document,
                output_root,
                arm_id=arm,
                seed=eval_seed,
                prereg_sha256=verified["sha256"],
                backend=backend,
            )
            report["details"] = eval_details
            return _complete_run(
                report=report,
                ledger=ledger,
                run_id=active_run,
                protocol=protocol,
                output_root=output_root,
                reason="s1_eval_completed",
                kind=f"eval_{arm}",
            )

        budget = float(wall_budget_seconds)
        if budget <= 0:
            raise ValueError("wall budget must be positive")
        # Prep modes are not bounded runs: they have no entry preconditions, so
        # the ledger is opened here and nowhere earlier.
        ledger = PrepLedger(ledger_path)
        active_run = active_run or ledger.open_aux_run(mode=mode, wall_budget_seconds=budget)
        report["run_id"] = active_run
        report["experiment_id"] = PREP_EXPERIMENT_ID
        work_state = "collecting" if mode == "data" else "validating"
        ledger.begin_work(active_run, work_state=work_state)
        protocol = completion.CompletionProtocol(deadline_seconds=budget)
        ledger.reserve(active_run, active_seconds=0.5 * budget)

        guard.sample(force=True)
        if mode == "data":
            manifest = data.generate_dataset(
                output_root,
                timeout_seconds=max(120.0, budget - 60.0),
            )
            identity = data.dataset_identity(manifest)
            report["details"] = {
                "dataset_dir": str(data.resolve_dataset_dir(output_root)),
                "dataset_digest": identity["dataset_digest"],
                "counts": identity["counts"],
                "generation_seconds": identity["generation_seconds"],
                "source_identity": identity["source_identity"],
            }
        elif mode == "smoke":
            from . import smoke as smoke_module

            dataset_dir = data.resolve_dataset_dir(output_root)
            # Pre-work reservation: the no-update smoke is bounded by this unit, so a
            # budget smaller than the reservation stops before any model work starts.
            ledger.reserve(active_run, active_seconds=30.0)
            metrics = smoke_module.run_smoke(dataset_dir)
            path = smoke_module.write_smoke(metrics, output_root / "smoke_metrics.json")
            report["details"] = {"smoke_metrics": str(path.resolve()), "smoke": metrics}
        elif mode == "verify":
            if prereg_path is None:
                if not (output_root / "pre_registration.json").is_file():
                    raise SystemExit("verify mode needs a frozen preregistration file")
                prereg_path = output_root / "pre_registration.json"
            verified = prereg.verify_frozen_file(prereg_path)
            dataset = data.verify_dataset(data.resolve_dataset_dir(output_root))
            report["details"] = {
                "preregistration": {"path": str(Path(prereg_path).resolve()), "sha256": verified["sha256"]},
                "dataset": dataset,
            }
        guard.sample(force=True)
        # r8 F1: the work reservation uses the same protocol timer as the commit.
        elapsed = protocol.elapsed()
        record = ledger.get(active_run)
        remaining = float(record.get("remaining", {}).get("wall_seconds", 0.0))
        actual = min(max(elapsed, 0.0), max(remaining, 0.0))
        if actual > 0:
            ledger.reserve(active_run, active_seconds=actual)
        report["elapsed_seconds"] = elapsed
        report["guard_samples"] = len(guard.samples)
        report["peak_rss_gib"] = guard.peak_rss_bytes / float(2**30)
        report["peak_mlx_gib"] = guard.peak_mlx_bytes / float(2**30)
        return _complete_run(
            report=report,
            ledger=ledger,
            run_id=active_run,
            protocol=protocol,
            output_root=output_root,
            reason=f"{mode}_prep_completed",
            kind=f"prep_{mode}",
        )

    except BudgetStop as exc:
        report["status"] = "stopped"
        report["error"] = f"BudgetExceeded: {exc}"
        if active_run and ledger is not None:
            report["run"] = ledger.finish(active_run, "stopped", "budget_exhausted")
        return report
    except resource_gate.ResourceGateRefused as exc:
        report["status"] = "stopped"
        report["error"] = f"resource_gate: {exc}"
        report["resource_gate"] = {"status": "refused", "reasons": exc.reasons}
        if active_run and ledger is not None:
            report["run"] = ledger.finish(active_run, "failed", "resource_gate_refused")
        return report
    except BaseException as exc:
        report["status"] = "failed"
        report["error"] = f"{type(exc).__name__}: {exc}"
        if active_run and ledger is not None:
            try:
                report["run"] = ledger.finish(active_run, "failed", "worker_failure")
            except Exception as finish_error:  # pragma: no cover - ledger failure
                report["finish_error"] = f"{type(finish_error).__name__}: {finish_error}"
        return report
    finally:
        report["elapsed_seconds"] = time.perf_counter() - started
        if ledger is not None:
            ledger.close()


def _open_train_run(
    document: Mapping[str, Any],
    ledger: PrepLedger,
    approval: Mapping[str, Any],
    *,
    arm_id: str,
    seed: int,
) -> str:
    # r11: the run is registered under the document's experiment id; the new
    # registration gets its own experiment row (same stable manifest), and the
    # old experiment's rows, attempts and failures stay untouched.
    experiment_id = document_experiment_id(document) or TRAIN_EXPERIMENT_ID
    experiment = ensure_shared_experiment(
        ledger.store,
        # One stable manifest for the whole phase: D (0 updates, its own frozen
        # arm1 deadline) and every training run (3510 updates, the registered
        # deadline) must resolve to the same experiment, so the payload may
        # depend on neither the caller's deadline nor role.
        manifest=train_experiment_manifest(
            updates=int(document["training_protocol"]["updates"]),
        ),
        request_id=f"{experiment_id}:training",
        experiment_id=experiment_id,
    )
    run_id = uuid4().hex
    updates = int(document["training_protocol"]["updates"])
    snapshot = run_config_snapshot(
        wall_budget_seconds=float(document["timing"]["deadline_seconds"]),
        purpose=f"s1_phase1_training_run:{arm_id}:seed{seed}",
        # The run ledger must carry the *actual* frozen update count.  The old
        # default of 1 made the second optimizer reservation fail immediately;
        # the tail checkpoint reservation then failed as well because a zero
        # optimizer reserve is still rejected once the remaining count is 0.
        max_optimizer_steps=updates,
    )
    snapshot["arm_id"] = arm_id
    snapshot["seed"] = int(seed)
    snapshot["updates"] = updates
    snapshot["preregistration_sha256"] = approval.get("document_sha256")
    snapshot["dataset_digest"] = (document.get("data_identity") or {}).get("dataset_digest")
    snapshot["checkpoint_updates"] = [
        int(value) for value in document["training_protocol"].get("checkpoint_updates") or []
    ]
    # The approval credential is part of the immutable run record: the exact log
    # line, its line number, the log SHA256 and the document SHA256 it covers.
    snapshot["approval"] = {
        "line": approval.get("line"),
        "line_number": approval.get("line_number"),
        "document_sha256": approval.get("document_sha256"),
        "research_log": approval.get("research_log"),
        "research_log_sha256": approval.get("research_log_sha256"),
        "status_field": approval.get("status_field"),
        "status_field_is_authoritative": False,
    }
    ledger.store.create_run(
        snapshot,
        f"{experiment_id}:{arm_id}:{seed}:{run_id}",
        run_id,
        experiment_id=experiment.experiment_id,
        role="model",
    )
    # created -> initializing -> training is the only legal edge into a work state;
    # r1 skipped the first step, which the F3 test exposed.
    ledger.store.transition(run_id, "initializing", reason="train_prereg_approved")
    return run_id


def _exclusive_write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path = Path(path)
    if path.exists():
        raise FileExistsError(f"refusing to overwrite immutable metadata {path}")
    with open(path, "x", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, sort_keys=True, indent=2)
        handle.write("\n")


def _exclusive_write_text(path: Path, text: str) -> None:
    path = Path(path)
    if path.exists():
        raise FileExistsError(f"refusing to overwrite immutable metadata {path}")
    with open(path, "x", encoding="utf-8") as handle:
        handle.write(text)


def _checkpoint_path(output_root: Path, run_id: str, updates: int, update: int) -> Path:
    run_dir = Path(output_root) / "runs" / run_id
    if int(update) == int(updates):
        return run_dir / "params.npz"
    return run_dir / "checkpoints" / f"updates-{int(update)}.npz"


def _read_only(path: Path) -> None:
    try:
        Path(path).chmod(0o444)
    except OSError:
        pass


def _train(
    document: Mapping[str, Any],
    output_root: Path,
    ledger: PrepLedger,
    run_id: str,
    guard: resource_gate.RuntimeGuard,
    *,
    arm_id: str = "arm2",
    seed: int = 0,
    prereg_sha256: str | None = None,
    backend=None,
    deadline_protocol: completion.CompletionProtocol | None = None,
) -> dict:
    """Registered single arm x seed training loop for V9.P1 (r6 control flow).

    The ledger budget is the frozen update count, exactly.  Every one of the
    ``updates`` optimizer reservations also pre-reserves the wall allowance for
    the checkpoint probe/save that follows that update; no consume happens after
    the final optimizer step (the lifecycle rejects *any* reservation, including
    a zero-optimizer one, once an exhausted counter is at zero).

    r6 deadline semantics: the loop-top guard alone let the final gradient, the
    final checkpoint probe/save, the duty sleep and the receipt/metadata IO run
    past the frozen per-run deadline and still report ``completed``.  The real
    total wall clock is therefore re-checked before any authoritative receipt
    is written and again after the trailing metadata IO, so a timeout, a save
    failure or a guard refusal can never produce a legal ``completed`` run.
    """
    import numpy as np

    backend = backend or runtime.MlxBackend()
    protocol = document["training_protocol"]
    timing = document["timing"]
    updates = int(protocol["updates"])
    if updates <= 0:
        raise ValueError("the frozen training protocol has no updates")
    deadline = float(timing["deadline_seconds"])
    duty = float(document["resource_limits"]["training_duty_cycle"])
    dataset_dir = data.resolve_dataset_dir(output_root)
    train_windows = data.load_training_windows(dataset_dir)
    development_windows = data.load_development_windows(dataset_dir)

    declared = [int(value) for value in protocol.get("checkpoint_updates") or []]
    if any(value < 0 or value > updates for value in declared):
        raise ValueError(f"checkpoint updates {declared!r} are outside 0..{updates}")
    checkpoint_set = set(declared)

    started = time.perf_counter()
    arm_started = started
    # r8 F1: the deadline belongs to one protocol shared with run_worker's
    # terminal commit.  When a caller runs the loop without one (only reachable
    # from tests that drive _train directly), the local protocol still covers the
    # loop and the receipt, and the caller keeps its own commit check.
    deadline_protocol = deadline_protocol or completion.CompletionProtocol(
        deadline_seconds=deadline,
        started=started,
        # Use the same clock object the caller measured ``started`` with, so a
        # caller that injects a deterministic clock (tests) stays coherent.
        clock=time.perf_counter,
    )

    def _enforce_deadline() -> None:
        # Exactly at the deadline is still inside budget; only strictly past it
        # aborts the run as failed (the 500 s supervision timeout stays the
        # outer hard fallback in commands.py).  r8: this raises through the shared
        # completion protocol, so the loop, the receipt IO and the terminal commit
        # all read the same monotonic clock.
        deadline_protocol.check("train_loop")

    model = backend.build_model(arm_id, seed=int(seed))
    optimizer = backend.make_optimizer(protocol)
    backend.init_optimizer(optimizer, model)
    value_grad = backend.value_and_grad(model)
    batches = data.iter_batches(
        train_windows, int(protocol["batch_size"]), seed=int(seed) + 17
    )

    run_dir = Path(output_root) / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    losses: list[float] = []
    curve: list[dict] = []
    saved: list[dict] = []
    checkpoint_wall_reservations = 0.0

    def _probe_and_save(update: int) -> None:
        nonlocal checkpoint_wall_reservations
        probe = backend.window_probe(model, development_windows, protocol)
        rows = probe.get("rows") or []
        if not rows:
            raise runtime.BackendError(
                f"checkpoint {update} development probe produced no rows; "
                "a missing NLL is not a zero"
            )
        development_nll = float(np.mean([float(row["loss"]) for row in rows]))
        curve.append(
            {
                "updates": int(update),
                "development_nll": development_nll,
                "nll_samples": len(rows),
                "batches": int(probe.get("batches", 0)),
            }
        )
        path = _checkpoint_path(output_root, run_id, updates, update)
        path.parent.mkdir(parents=True, exist_ok=True)
        backend.save_params(model, path, exclusive=True)
        _read_only(path)
        saved.append(
            {
                "updates": int(update),
                "path": str(path.relative_to(run_dir)),
                "sha256": spec.sha256_file(path),
                "parameter_sha256": backend.parameter_sha256(model),
                "development_nll": development_nll,
                "nll_samples": len(rows),
            }
        )

    # Checkpoint 0 is the pre-training measurement of record.  It is a wall-only
    # reservation: the optimizer counter is still untouched and positive.
    if 0 in checkpoint_set:
        ledger.reserve(run_id, active_seconds=CHECKPOINT_RESERVE_SECONDS)
        checkpoint_wall_reservations += CHECKPOINT_RESERVE_SECONDS
        _probe_and_save(0)

    previous = 0.05
    for update in range(1, updates + 1):
        _enforce_deadline()
        guard.sample()
        batch = next(batches)
        if update in checkpoint_set:
            extra = CHECKPOINT_RESERVE_SECONDS
        elif update == updates:
            extra = FINAL_SAVE_RESERVE_SECONDS
        else:
            extra = 0.0
        reservation = max(0.05, min(1.0, previous * 2.0)) + extra
        # Exactly one optimizer reservation per update, including the final one.
        ledger.reserve(run_id, active_seconds=reservation, optimizer_steps=1)
        if extra:
            checkpoint_wall_reservations += extra
        tick = time.perf_counter()
        (loss, _parts), grads = value_grad(model, batch)
        backend.eval(loss, grads)
        # Frozen non-finite stop rule, checked at the boundary where the state is
        # visible: a NaN/Inf loss or any NaN/Inf gradient leaf fails the run here,
        # before an optimizer update and before any completion receipt exists.
        _assert_finite_update(loss, grads)
        clipped, _norm = backend.clip_grad_norm(
            grads, float(protocol["gradient_clip_norm"])
        )
        backend.optimizer_update(optimizer, model, clipped)
        backend.sync_parameters(model, optimizer)
        # The same rule must cover the parameters after the update; failing only
        # when the final JSON is serialised would be too late (steps consumed,
        # completion already claimed).
        _assert_finite_parameters(backend, model)
        previous = time.perf_counter() - tick
        losses.append(backend.loss_value(loss))
        if update in checkpoint_set:
            _probe_and_save(update)
        elif update == updates:
            path = _checkpoint_path(output_root, run_id, updates, update)
            path.parent.mkdir(parents=True, exist_ok=True)
            backend.save_params(model, path, exclusive=True)
            _read_only(path)
            saved.append(
                {
                    "updates": int(update),
                    "path": str(path.relative_to(run_dir)),
                    "sha256": spec.sha256_file(path),
                    "parameter_sha256": backend.parameter_sha256(model),
                    "development_nll": None,
                    "nll_samples": 0,
                }
            )
        rest = previous * (1.0 / duty - 1.0)
        if rest:
            time.sleep(min(rest, 2.0))

    # r6: the last gradient, the final checkpoint probe/save and the duty sleep
    # all happen after the final loop-top check, so the real total wall clock is
    # verified here, before any receipt or authoritative completion exists.
    _enforce_deadline()
    wall_seconds = time.perf_counter() - arm_started
    final_entries = [entry for entry in saved if int(entry["updates"]) == updates]
    if len(final_entries) != 1:
        raise RuntimeError(
            f"the final checkpoint was written {len(final_entries)} times (expected exactly once)"
        )
    final = final_entries[0]
    final_path = run_dir / final["path"]
    sha_text = f"{final['sha256']}  {Path(final['path']).name}\n"
    _exclusive_write_text(run_dir / "params.npz.sha256", sha_text)
    _read_only(run_dir / "params.npz.sha256")

    receipt = {
        "schema": "ainerzero.v9.s1.completion.v1",
        "spec": spec.SPEC_NAME,
        "run_id": run_id,
        "arm_id": arm_id,
        "seed": int(seed),
        "updates": updates,
        "preregistration_sha256": prereg_sha256,
        "dataset_digest": (document.get("data_identity") or {}).get("dataset_digest"),
        "checkpoint_updates": sorted(entry["updates"] for entry in saved),
        "checkpoints": sorted(saved, key=lambda entry: int(entry["updates"])),
        "final_checkpoint_updates": updates,
        "final_checkpoint_path": final["path"],
        "final_checkpoint_sha256": final["sha256"],
        "final_parameter_sha256": final["parameter_sha256"],
        "sample_efficiency_curve": curve,
        "final_training_loss": losses[-1] if losses else None,
        "wall_seconds": wall_seconds,
        "backend": getattr(backend, "name", type(backend).__name__),
        "completion_protocol": deadline_protocol.record(phase="train_receipt"),
        "ledger_accounting": {
            "optimizer_reservations": updates,
            "checkpoint_wall_reservations_seconds": checkpoint_wall_reservations,
            "post_final_optimizer_reservations": 0,
        },
        "checkpoint_policy": "one optimizer reservation per update; the final update's "
        "reservation includes the checkpoint probe/save wall allowance; no ledger "
        "consume is issued after the final optimizer step",
    }
    _exclusive_write_json(run_dir / "completion.json", receipt)
    run_info = {
        "schema": "ainerzero.v9.s1.run_info.v1",
        "authoritative": False,
        "authoritative_receipt": "completion.json",
        "note": "convenience copy only; eval binds the completed RunStore run, the "
        "frozen preregistration, the arm/seed and the original checkpoint SHA",
        **{key: receipt[key] for key in (
            "run_id",
            "arm_id",
            "seed",
            "updates",
            "preregistration_sha256",
            "dataset_digest",
            "final_checkpoint_sha256",
            "final_parameter_sha256",
            "sample_efficiency_curve",
            "final_training_loss",
            "wall_seconds",
        )},
        "checkpoint_path": str(final_path.resolve()),
        "checkpoint_sha256": final["sha256"],
        "parameter_sha256": final["parameter_sha256"],
    }
    _exclusive_write_json(run_dir / "run_info.json", run_info)
    # The ledger transition to ``completed`` happens after this return; trailing
    # metadata IO must not be able to cross the deadline unnoticed either.
    _enforce_deadline()

    return {
        "arm_id": arm_id,
        "seed": int(seed),
        "updates": updates,
        "final_training_loss": losses[-1] if losses else None,
        "sample_efficiency_curve": curve,
        "parameter_sha256": final["parameter_sha256"],
        "checkpoint_path": str(final_path.resolve()),
        "checkpoint_sha256": final["sha256"],
        "checkpoints": sorted(saved, key=lambda entry: int(entry["updates"])),
        "receipt": receipt,
        "wall_seconds": wall_seconds,
        "status": "completed",
    }


def _parse_receipt(reason: str | None) -> dict:
    if not reason:
        raise EvalBindingError("completed run has no completion receipt")
    if not reason.startswith(TRAIN_RECEIPT_PREFIX):
        raise EvalBindingError("completed run reason is not an r5 completion receipt")
    try:
        receipt = json.loads(reason[len(TRAIN_RECEIPT_PREFIX) :])
    except (TypeError, ValueError) as exc:
        raise EvalBindingError("completion receipt is not valid JSON") from exc
    if not isinstance(receipt, dict):
        raise EvalBindingError("completion receipt is not an object")
    return receipt


def _bind_completed_run(
    output_root: Path,
    *,
    arm_id: str,
    seed: int,
    prereg_sha256: str | None,
    updates: int,
    ledger_path: Path | None = None,
) -> dict:
    """Bind eval to the ledger's completed run and its original checkpoint SHA.

    The expected checkpoint digest comes from the immutable transition reason
    written when the run completed, never from ``run_info.json`` (which is only a
    convenience copy) and never from a re-hash of a tampered file.

    r6: the ledger is the one central RunStore by default, so a copied run root
    cannot bind against its own ledger copy; tests may pass an explicit
    ``ledger_path`` for an isolated fixture.
    """
    output_root = Path(output_root)
    control_db = (
        Path(ledger_path) if ledger_path is not None else canonical_ledger_path()
    )
    if not control_db.is_file():
        raise EvalBindingError(f"no RunStore ledger at {control_db}")
    from ainerzero.runtime.lifecycle import RunStore

    with RunStore(control_db) as store:
        runs = store.list_runs()
    matches = []
    for run in runs:
        config = run.config_snapshot or {}
        if run.state != "completed" or run.role != "model":
            continue
        if config.get("arm_id") != arm_id:
            continue
        try:
            if int(config.get("seed", -1)) != int(seed):
                continue
            if int(config.get("updates", -1)) != int(updates):
                continue
        except (TypeError, ValueError):
            continue
        if prereg_sha256 is not None and config.get("preregistration_sha256") != prereg_sha256:
            continue
        matches.append(run)
    if not matches:
        raise EvalBindingError(
            f"no completed run binds arm={arm_id} seed={seed} updates={updates} "
            f"preregistration={prereg_sha256}"
        )
    if len(matches) > 1:
        raise EvalBindingError(
            "more than one completed run matches this arm/seed/preregistration: "
            + ", ".join(sorted(run.run_id for run in matches))
        )
    run = matches[0]
    config = run.config_snapshot or {}
    budget_steps = int((config.get("budget") or {}).get("max_optimizer_steps", -1))
    if budget_steps != int(updates):
        raise EvalBindingError(
            f"run {run.run_id} budget max_optimizer_steps={budget_steps} does not equal "
            f"the frozen updates={updates}"
        )
    if int(run.reserved_optimizer_steps) != int(updates):
        raise EvalBindingError(
            f"run {run.run_id} reserved {run.reserved_optimizer_steps} optimizer steps, "
            f"not the frozen {updates}"
        )
    receipt = _parse_receipt(run.reason)
    for field, expected in (
        ("run_id", run.run_id),
        ("arm_id", arm_id),
        ("seed", int(seed)),
        ("updates", int(updates)),
    ):
        if receipt.get(field) != expected:
            raise EvalBindingError(
                f"completion receipt {field}={receipt.get(field)!r} does not match {expected!r}"
            )
    if prereg_sha256 is not None and receipt.get("preregistration_sha256") != prereg_sha256:
        raise EvalBindingError(
            "completion receipt is bound to a different preregistration SHA"
        )
    run_dir = (output_root / "runs" / run.run_id).resolve()
    # r8 F1: a ``completed`` ledger row plus a ``completion.json`` file is not by
    # itself a successful completion.  The completion protocol is what makes the
    # run accepted; a run it refused carries an immutable invalid marker and any
    # receipt that self-declares an over-budget completion is refused here too.
    from . import completion as completion_module

    markers = completion_module.invalid_markers(run_dir)
    if markers:
        raise EvalBindingError(
            "the completed run carries a completion-protocol invalidation marker "
            f"({markers[0].name}); the ledger row is not evidence of a valid completion"
        )
    protocol_record = receipt.get("completion_protocol")
    if not isinstance(protocol_record, dict) or protocol_record.get("schema") != (
        completion_module.SCHEMA
    ):
        raise EvalBindingError(
            "the completion receipt carries no completion-protocol record; a run without "
            "the unified pre/in-flight/post commit check is not a valid completion"
        )
    elapsed = protocol_record.get("elapsed_at_record_seconds")
    recorded_deadline = protocol_record.get("deadline_seconds")
    if not isinstance(elapsed, (int, float)) or not isinstance(recorded_deadline, (int, float)):
        raise EvalBindingError("the completion-protocol record has no numeric timing")
    if float(elapsed) > float(recorded_deadline):
        raise EvalBindingError(
            f"the completion receipt was written at {elapsed}s, past its own "
            f"{recorded_deadline}s deadline"
        )
    if protocol_record.get("expired_in_flight"):
        raise EvalBindingError(
            "the completion protocol observed the deadline pass while the commit was in flight"
        )
    entries = receipt.get("checkpoints") or []
    if not entries:
        raise EvalBindingError("completion receipt lists no checkpoints")
    checkpoints: dict[int, dict] = {}
    for entry in entries:
        try:
            update = int(entry["updates"])
            relative = Path(str(entry["path"]))
            expected_sha = str(entry["sha256"])
            expected_param = str(entry["parameter_sha256"])
        except (KeyError, TypeError, ValueError) as exc:
            raise EvalBindingError("malformed checkpoint entry in completion receipt") from exc
        if relative.is_absolute() or ".." in relative.parts:
            raise EvalBindingError(f"checkpoint path escapes the run directory: {relative}")
        path = (run_dir / relative).resolve()
        if run_dir not in path.parents:
            raise EvalBindingError(f"checkpoint path escapes the run directory: {relative}")
        if not path.is_file():
            raise EvalBindingError(f"bound checkpoint is missing: {relative}")
        actual = spec.sha256_file(path)
        if actual != expected_sha:
            raise EvalBindingError(
                f"checkpoint {relative} SHA {actual} does not match the original "
                f"receipt SHA {expected_sha}"
            )
        if update in checkpoints:
            raise EvalBindingError(f"checkpoint update {update} appears twice")
        checkpoints[update] = {
            "updates": update,
            "path": path,
            "sha256": actual,
            "parameter_sha256": expected_param,
        }
    if int(updates) not in checkpoints:
        raise EvalBindingError("the completion receipt has no final checkpoint")
    if checkpoints[int(updates)]["path"].name != "params.npz":
        raise EvalBindingError("the final checkpoint is not runs/<run_id>/params.npz")
    if receipt.get("final_checkpoint_sha256") != checkpoints[int(updates)]["sha256"]:
        raise EvalBindingError("completion receipt final SHA disagrees with its checkpoint list")
    if receipt.get("dataset_digest") != (
        (config.get("dataset_digest") or None)
    ):
        raise EvalBindingError("completion receipt dataset digest disagrees with the run record")
    return {
        "run": run,
        "receipt": receipt,
        "checkpoints": checkpoints,
        "final": checkpoints[int(updates)],
        "run_dir": run_dir,
    }


def _bind_for_document(
    document: Mapping[str, Any] | None,
    output_root: Path,
    *,
    arm_id: str,
    seed: int,
    prereg_sha256: str | None,
    updates: int,
    ledger_path: Path | None = None,
) -> dict:
    """Bind eval to this registration's run, or (r14) to an inherited source run.

    A non-inherited cell binds exactly as before.  An inherited cell binds through
    the same :func:`_bind_completed_run` checks under the *source* preregistration
    SHA, and then must also be the registered source run of the registered source
    experiment with the registered ``params.npz`` SHA; anything else refuses.
    """
    cell = inherited_cell(document or {}, arm_id=arm_id, seed=int(seed))
    if cell is None:
        return _bind_completed_run(
            output_root,
            arm_id=arm_id,
            seed=int(seed),
            prereg_sha256=prereg_sha256,
            updates=int(updates),
            ledger_path=ledger_path,
        )
    binding = _bind_completed_run(
        output_root,
        arm_id=arm_id,
        seed=int(seed),
        prereg_sha256=cell["source_preregistration_sha256"],
        updates=int(updates),
        ledger_path=ledger_path,
    )
    run = binding["run"]
    if run.run_id != cell["source_run_id"]:
        raise EvalBindingError(
            f"inherited arm {arm_id} seed {seed} bound run {run.run_id}, not the "
            f"registered source run {cell['source_run_id']}"
        )
    if getattr(run, "experiment_id", None) != cell["source_experiment_id"]:
        raise EvalBindingError(
            f"inherited run {run.run_id} belongs to experiment "
            f"{getattr(run, 'experiment_id', None)!r}, not {cell['source_experiment_id']!r}"
        )
    if binding["final"]["sha256"] != cell["params_sha256"]:
        raise EvalBindingError(
            f"inherited run {run.run_id} params.npz SHA {binding['final']['sha256']} does not "
            f"equal the registered {cell['params_sha256']}"
        )
    binding["inherited"] = cell
    return binding


def _eval_binding_precondition(
    output_root: Path,
    *,
    arm_id: str,
    seed: int,
    prereg_sha256: str | None,
    updates: int,
    ledger_path: Path | None = None,
    document: Mapping[str, Any] | None = None,
) -> dict:
    """CPU-only precondition: a completed training run must bind this arm x seed.

    r12 (P31-LEDGER-INCIDENT-RULING): the r5-r11 eval entry called
    ``open_aux_run`` -- which creates the experiment, the run, the
    ``begin_work`` transition and the pre-work reservation -- and only then let
    ``_evaluate_arm`` raise ``EvalBindingError`` because no completed training
    run binds the arm x seed.  That precondition needs nothing but the ledger
    and the run directory, so it is decided here, *before* the first write; a
    refusal therefore leaves the ledger bytes untouched.

    The check is the same :func:`_bind_completed_run` the evaluation itself uses
    (no new gate, no changed threshold): only its position moved.  The ledger is
    read through :func:`ledger_read_snapshot`, so the probe itself cannot write.
    """
    control_db = Path(ledger_path) if ledger_path is not None else canonical_ledger_path()
    try:
        with ledger_read_snapshot(control_db) as snapshot:
            binding = _bind_for_document(
                document,
                output_root,
                arm_id=arm_id,
                seed=int(seed),
                prereg_sha256=prereg_sha256,
                updates=int(updates),
                ledger_path=snapshot.db_path,
            )
    except EvalBindingError as exc:
        return {
            "status": "refused",
            "refused_stage": "eval_binding_unavailable",
            "error": f"{type(exc).__name__}: {exc}",
            "message": "no completed training run binds this arm x seed to the frozen "
            "preregistration; eval refuses before the first ledger write and the "
            "central ledger keeps its bytes",
        }
    return {
        "status": "ok",
        "bound_run_id": binding["run"].run_id,
        "final_checkpoint": str(binding["final"]["path"]),
        "inherited": binding.get("inherited"),
    }


def _evaluate_arm(
    document: Mapping[str, Any],
    output_root: Path,
    *,
    arm_id: str,
    seed: int = 0,
    prereg_sha256: str | None = None,
    backend=None,
    eval_view=None,
) -> dict:
    """Score one arm x seed on development, or (P59) on ``eval_view``, a ``data.FinalView``."""
    import numpy as np

    from . import metrics

    backend = backend or runtime.MlxBackend()
    dataset_dir = data.resolve_dataset_dir(output_root)
    protocol = document["training_protocol"]
    updates = int(protocol["updates"])

    if arm_id == "arm1":
        # arm1 is the only frozen D-candidate path.  r8 F7: the identity check and
        # the CPU substitute path are MLX-free; only a real load imports ``arms``.
        from . import identity as identity_module

        # r7: the real A2 byte-level identity validator always runs, including
        # when a CPU substitute supplies the forward.  A substitute may stand in
        # for MLX; it may never stand in for the candidate identity.
        d_identity = identity_module.verify_d_candidate_identity(
            repo_root=Path(spec.REPO_ROOT)
        )
        substitute = bool(backend is not None and hasattr(backend, "eval_d_candidate"))
        if substitute:
            out = backend.eval_d_candidate(seed=int(seed))
            info = getattr(
                backend,
                "d_candidate_info",
                {"parameter_count": 147584, "parameter_sha256": "cbb14d878dfda5af816dbc4903c7fb811aabbcfb17ce494f00e994ab3d6b286a"},
            )
        else:
            from . import arms

            model, info = arms.load_d_candidate()
            batch = arms.d_candidate_fixed_batch()
            out = arms.d_candidate_forward_loss(model, batch, seed=int(seed))

        nll0 = float(out.metrics["symbol_nll_t0"])
        nll1 = float(out.metrics["symbol_nll_t1"])
        incomparable = list(spec.ARM_SPECS["arm1"]["incomparable"])
        not_applicable = {"status": "not_applicable", "reason": "incomparable input layout"}
        return {
            "arm_id": arm_id,
            "seed": int(seed),
            "kind": "frozen_candidate",
            "name": spec.ARM_SPECS["arm1"]["name"],
            "parameter_count": info["parameter_count"],
            "parameter_sha256": info["parameter_sha256"],
            "localization_error": not_applicable,
            "unseen_map_generalization": not_applicable,
            "topology_recovery": not_applicable,
            "few_shot_unseen_transition": not_applicable,
            "sample_efficiency": not_applicable,
            "m2_memory_interference": {
                "status": "not_applicable",
                "reason": "the frozen D candidate is a single fixed C0 probe; it has no "
                "S1 episodic memory to probe",
                "d_candidate_symbol_nll_t0": nll0,
                "d_candidate_symbol_nll_t1": nll1,
            },
            "d_candidate_c0_metrics": out.metrics,
            "d_candidate_identity": d_identity,
            "forward_substitute": substitute,
            "incomparable": incomparable,
            "run_binding": {"status": "not_applicable", "kind": "frozen_candidate"},
            "status": "completed",
        }

    binding = _bind_for_document(
        document,
        output_root,
        arm_id=arm_id,
        seed=int(seed),
        prereg_sha256=prereg_sha256,
        updates=updates,
    )
    receipt = binding["receipt"]
    document_digest = (document.get("data_identity") or {}).get("dataset_digest")
    if receipt.get("dataset_digest") != document_digest:
        raise EvalBindingError(
            "the completed run was trained on a different dataset digest than the "
            "frozen document"
        )
    actual_dataset = data.dataset_binding_state(output_root, document_digest)
    if actual_dataset.get("status") != "passed":
        raise EvalBindingError(
            f"dataset binding is {actual_dataset.get('status')}, expected passed"
        )

    model = backend.build_model(arm_id, seed=int(seed))
    final = binding["final"]
    backend.load_params(model, final["path"])
    loaded_param_sha = backend.parameter_sha256(model)
    if loaded_param_sha != final["parameter_sha256"]:
        raise EvalBindingError(
            "loaded parameters do not match the original receipt parameter SHA"
        )

    if eval_view is None:
        development_windows = data.load_development_windows(dataset_dir)
        truth_view = data.load_truth_view(dataset_dir, "development")
    else:
        development_windows = eval_view.windows()
        truth_view = eval_view.truth_view()
    if not truth_view:
        raise evaluation.EvaluationError("no development truth rows")

    final_probe = backend.window_probe(model, development_windows, protocol)
    final_rows = evaluation.development_rows(final_probe, truth_view)
    localization = evaluation.localization_report(final_rows)

    # Dual sample-efficiency curve: every frozen checkpoint is re-loaded from its
    # bound path and scored on the same development windows with the evaluator
    # truth sidecar (NLL + localization at each checkpoint).
    sample_rows = []
    for update in sorted(binding["checkpoints"]):
        entry = binding["checkpoints"][update]
        backend.load_params(model, entry["path"])
        loaded = backend.parameter_sha256(model)
        if loaded != entry["parameter_sha256"]:
            raise EvalBindingError(
                f"checkpoint {update} parameter SHA {loaded} does not match the "
                f"original receipt SHA {entry['parameter_sha256']}"
            )
        if update == updates:
            probe = final_probe
            rows = final_rows
        else:
            probe = backend.window_probe(model, development_windows, protocol)
            rows = evaluation.development_rows(probe, truth_view)
        unseen = metrics.strict_unseen_map(rows)
        sample_rows.append(
            {
                "updates": int(update),
                "development_nll": float(
                    np.mean([float(row["prediction_nll"]) for row in rows])
                ),
                "localization_translation_mean_m": float(
                    unseen["translation_mean_m"]
                ),
                "nll_samples": len(rows),
                "localization_samples": int(unseen["episodes"]),
            }
        )
    # Leave the model at the final checkpoint for the episodic probes.
    backend.load_params(model, final["path"])
    if backend.parameter_sha256(model) != final["parameter_sha256"]:
        raise EvalBindingError("final checkpoint reload changed the parameter SHA")

    development_episodes = (
        data.load_training_episodes(dataset_dir, "development") if eval_view is None else eval_view.episodes()
    )
    sequences = [data.build_episode_sequence(episode) for episode in development_episodes]
    topology = evaluation.topology_report(backend, model, sequences, truth_view)
    few_shot = evaluation.few_shot_report(
        backend, model, sequences, truth_view, preregistration=document
    )
    if len(sequences) < 5:
        raise evaluation.EvaluationError(
            "the M2 probe needs at least five development worlds"
        )
    probe_sequences = sequences[:3]
    history_sequence = sequences[3]
    new_world_sequence = sequences[4]
    interference = evaluation.m2_interference(
        backend,
        model,
        probe_sequences,
        truth_view,
        history_sequence,
        new_world_sequence,
    )
    sample_efficiency = evaluation.sample_efficiency(sample_rows)

    suite = metrics.metric_suite_report(
        localization=localization,
        unseen=localization["unseen"],
        topology=topology,
        few_shot=few_shot,
        sample_efficiency=sample_efficiency,
        interference=interference,
        arm_id=arm_id,
        seed=int(seed),
    )
    suite.update(
        {
            "name": spec.ARM_SPECS[arm_id]["name"],
            "kind": "trainable",
            "preregistration_sha256": prereg_sha256,
            "dataset_digest": document_digest,
            "run_binding": {
                "status": "passed",
                "run_id": binding["run"].run_id,
                "state": binding["run"].state,
                "reserved_optimizer_steps": int(binding["run"].reserved_optimizer_steps),
                "checkpoint_updates": sorted(binding["checkpoints"]),
                "final_checkpoint_path": str(final["path"]),
                "final_checkpoint_sha256": final["sha256"],
                "final_parameter_sha256": final["parameter_sha256"],
                "expected_sha_source": "immutable completed-run reason receipt",
                "run_info_used_for_binding": False,
                # r14: inherited cells name their registered source run; None otherwise.
                "inherited": binding.get("inherited"),
            },
            "checkpoint_path": str(final["path"]),
            "checkpoint_sha256": final["sha256"],
            "parameter_sha256": final["parameter_sha256"],
            "incomparable": list(spec.ARM_SPECS[arm_id]["incomparable"]),
            "partition": "development" if eval_view is None else eval_view.partition,
            "status": "completed",
        }
    )
    return suite



def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", required=True, choices=("data", "smoke", "verify", "train", "eval", "final-eval"))
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--limits-json", required=True)
    parser.add_argument("--wall-budget-seconds", type=float, required=True)
    parser.add_argument("--prereg", type=Path, default=None)
    parser.add_argument("--research-log", type=Path, default=None)
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--arm", choices=("arm1", "arm2", "arm3", "arm4"), default=None)
    parser.add_argument("--seed", type=int, default=None)
    args = parser.parse_args(argv)
    limits = json.loads(args.limits_json)
    report = run_worker(
        args.mode,
        output_root=args.output_root,
        limits=limits,
        wall_budget_seconds=args.wall_budget_seconds,
        prereg_path=args.prereg,
        research_log=args.research_log,
        run_id=args.run_id,
        arm=args.arm,
        seed=args.seed,
    )
    report["worker_exit"] = 0 if report["status"] == "completed" else (
        2 if report["status"] == "refused" else 3
    )
    print(json.dumps(report, ensure_ascii=False))
    return int(report["worker_exit"])


if __name__ == "__main__":
    raise SystemExit(main())
