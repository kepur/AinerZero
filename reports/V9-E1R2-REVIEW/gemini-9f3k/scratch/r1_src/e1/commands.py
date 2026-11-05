"""Supervisor commands for E1 Phase 2 entry.

Modes:
- verify: Read-only verification of frozen preregistration and coordinator approval line.
- generate-data: Preflight-guarded dataset generation & export.
- train: Preflight-guarded training for arms 2, 3, 6, families P, S, seeds 42, 43, 44.
- eval: Preflight-guarded development evaluation for all arms (①-⑦).
- final-eval: Preflight-guarded read-once evaluation on sealed final partition (dual family).

All compute modes enforce:
1. Preregistration validation and coordinator approval line in RESEARCH_LOG.md.
2. Read-only preflight inspection: failures refuse BEFORE opening or modifying the ledger.
3. Strict anti-duplicate execution for training cells, data generation, and final-eval.
4. Trainable arm eval requires authentic checkpoint; missing checkpoint refuses in preflight.
5. Per-cell deadline and budget reservation reset.
6. Shared worker lock acquisition (fcntl flock).
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import time
from typing import Any, Callable, Mapping

from ainerzero.cli import WorkerLockBusy, worker_lock

from . import data_runner, export, identity, prereg, spec, worker

EXIT_COMPLETED = 0
EXIT_FAILED = 1
EXIT_REFUSED_RESOURCE = 2
EXIT_REFUSED_APPROVAL = 3
EXIT_LOCK_BUSY = 4


def _resolve_paths(args: Any) -> dict[str, Path]:
    repo_root = Path(getattr(args, "repo_root", None) or spec.REGISTERED_HOST_ROOT).resolve()
    awz_root = Path(getattr(args, "awz_root", None) or spec.AWZ_ROOT).resolve()
    output_root = Path(getattr(args, "output_root", None) or spec.REGISTERED_HOST_PHASE2).resolve()
    ledger_path = Path(getattr(args, "ledger", None) or (output_root / "control.sqlite3")).resolve()
    lock_path = Path(getattr(args, "lock_file", None) or spec.REGISTERED_HOST_LOCK).resolve()
    research_log = Path(getattr(args, "research_log", None) or spec.RESEARCH_LOG).resolve()
    data_dir = Path(getattr(args, "data_dir", None) or (output_root / "datasets")).resolve()

    prereg_path = getattr(args, "prereg", None)
    if prereg_path is not None:
        prereg_file = Path(prereg_path).resolve()
    else:
        prereg_file = output_root / "prereg.json"

    return {
        "repo_root": repo_root,
        "awz_root": awz_root,
        "output_root": output_root,
        "ledger": ledger_path,
        "lock": lock_path,
        "research_log": research_log,
        "data_dir": data_dir,
        "prereg": prereg_file,
    }


def _get_prereg_document(
    prereg_path: Path,
    repo_root: Path | None = None,
    awz_root: Path | None = None,
) -> tuple[dict[str, Any], str]:
    if prereg_path.is_file():
        text = prereg_path.read_text(encoding="utf-8")
        doc = json.loads(text)
        prereg.validate(doc)
        digest = prereg.document_sha256(doc)
        return doc, digest
    # If not written to disk yet, construct and validate standard draft
    draft = prereg.build_draft(repo_root=repo_root, awz_root=awz_root)
    frozen, digest = prereg.freeze(draft)
    return frozen, digest


def _check_approval_preflight(
    research_log: Path,
    prereg_doc: Mapping[str, Any],
    prereg_sha: str,
) -> tuple[bool, dict[str, Any]]:
    try:
        approval_res = prereg.find_approval(research_log, expected_sha256=prereg_sha)
        return True, approval_res
    except prereg.ApprovalRefused as exc:
        return False, {
            "status": "refused",
            "stage": "approval_check",
            "reasons": exc.reasons,
            "detail": exc.detail,
        }
    except Exception as exc:
        return False, {
            "status": "refused",
            "stage": "approval_check",
            "reasons": [f"Unexpected error reading approval: {exc}"],
        }


def _get_cell_budget(mode: str, arm: int | None, requested_budget: float | None = None) -> float:
    if mode == "generate-data":
        default_budget = float(spec.BUDGET_CAPS["data_generation_max_seconds"])
    elif mode == "train":
        default_budget = float(spec.BUDGET_CAPS["train_cell_wall_max_seconds"])
    elif mode == "eval":
        if arm in spec.TRAINABLE_ARM_IDS:
            default_budget = float(spec.BUDGET_CAPS["dev_eval_train_cell_max_seconds"])
        else:
            default_budget = float(spec.BUDGET_CAPS["dev_eval_nontrain_cell_max_seconds"])
    elif mode == "final-eval":
        default_budget = float(spec.BUDGET_CAPS["final_eval_max_seconds"])
    else:
        default_budget = 300.0

    if requested_budget is not None:
        if requested_budget > default_budget:
            raise ValueError(
                f"Requested budget {requested_budget} s exceeds registered ceiling {default_budget} s"
            )
        return float(requested_budget)
    return default_budget


def _check_phase_budget_ceiling(
    ledger_path: Path,
    new_cell_budget: float,
) -> tuple[bool, float, float]:
    """Check whether adding this cell exceeds the total phase wall clock ceiling."""
    total_ceiling = float(spec.BUDGET_CAPS["phase_total_wall_ceiling_seconds"])
    consumed = 0.0

    with worker.ledger_read_snapshot(ledger_path) as store:
        if store is not None:
            placeholders = ", ".join("?" for _ in spec.LEDGER_EXPERIMENT_IDS)
            cursor = store._conn.execute(
                f"SELECT active_seconds, config_json FROM runs WHERE experiment_id IN ({placeholders})",
                spec.LEDGER_EXPERIMENT_IDS,
            )
            for row in cursor.fetchall():
                val = row["active_seconds"]
                if val is not None and float(val) > 0:
                    consumed += float(val)
                else:
                    try:
                        cfg = json.loads(row["config_json"])
                        consumed += float(cfg.get("cell_wall_budget_seconds", 0.0))
                    except Exception:
                        pass

    if consumed + new_cell_budget > total_ceiling:
        return False, consumed, total_ceiling
    return True, consumed, total_ceiling


def e1_phase2_command(args: argparse.Namespace) -> tuple[dict[str, Any], int]:
    """Main CLI entrypoint for ``ainerzero e1-phase2``."""
    mode = getattr(args, "mode", None)
    if not mode:
        return {"status": "error", "message": "Missing required --mode"}, EXIT_FAILED

    paths = _resolve_paths(args)

    # 1. verify mode: completely read-only
    if mode == "verify":
        try:
            doc, digest = _get_prereg_document(paths["prereg"], paths["repo_root"], paths["awz_root"])
        except Exception as exc:
            return {
                "status": "refused",
                "mode": "verify",
                "stage": "prereg_validation",
                "reasons": [str(exc)],
            }, EXIT_FAILED

        # Verify identity in verify mode: report result, do NOT refuse
        try:
            identity_info = identity.verify_frozen_identity(doc, paths["repo_root"], paths["awz_root"])
        except Exception as exc:
            identity_info = {
                "status": "mismatch",
                "reasons": [str(exc)],
                "mismatches": getattr(exc, "mismatches", {}),
            }

        ok, approval_info = _check_approval_preflight(paths["research_log"], doc, digest)
        if not ok:
            return approval_info, EXIT_REFUSED_APPROVAL

        return {
            "status": "verified",
            "mode": "verify",
            "document_sha256": digest,
            "approval": approval_info,
            "identity": identity_info,
        }, EXIT_COMPLETED

    # 2. Compute modes: preflight checks executed BEFORE opening or modifying the ledger
    # Preflight A: prereg & approval line check & identity verification
    try:
        doc, digest = _get_prereg_document(paths["prereg"], paths["repo_root"], paths["awz_root"])
    except Exception as exc:
        return {
            "status": "refused",
            "mode": mode,
            "stage": "prereg_validation",
            "reasons": [str(exc)],
        }, EXIT_FAILED

    # Preflight Identity Verification: strictly refuses on mismatch, before opening ledger or running
    try:
        identity.verify_frozen_identity(doc, paths["repo_root"], paths["awz_root"])
    except Exception as exc:
        return {
            "status": "refused",
            "mode": mode,
            "stage": "identity_verification",
            "reasons": [str(exc)],
            "mismatches": getattr(exc, "mismatches", {}),
        }, EXIT_FAILED

    ok, approval_info = _check_approval_preflight(paths["research_log"], doc, digest)
    if not ok:
        return approval_info, EXIT_REFUSED_APPROVAL

    # Preflight B: validate domain arguments
    arm_raw = getattr(args, "arm", None)
    arm = int(arm_raw) if arm_raw is not None else None
    family = getattr(args, "family", None)
    seed = getattr(args, "seed", None)
    if seed is not None:
        seed = int(seed)

    if mode == "train":
        if arm not in spec.TRAINABLE_ARM_IDS:
            return {
                "status": "refused",
                "mode": mode,
                "stage": "invalid_arm",
                "message": f"Arm {arm} is not trainable; train mode only accepts {spec.TRAINABLE_ARM_IDS}",
            }, EXIT_FAILED
        if family not in spec.FAMILIES:
            return {
                "status": "refused",
                "mode": mode,
                "stage": "invalid_family",
                "message": f"Family {family} must be one of {spec.FAMILIES}",
            }, EXIT_FAILED
        if seed not in spec.TRAINING_SEEDS:
            return {
                "status": "refused",
                "mode": mode,
                "stage": "invalid_seed",
                "message": f"Seed {seed} must be one of registered training seeds {spec.TRAINING_SEEDS}",
            }, EXIT_FAILED

    elif mode == "eval":
        if arm is None or arm not in range(1, 8):
            return {
                "status": "refused",
                "mode": mode,
                "stage": "invalid_arm",
                "message": f"Arm {arm} must be in 1..7 for eval mode",
            }, EXIT_FAILED
        if family not in spec.FAMILIES:
            return {
                "status": "refused",
                "mode": mode,
                "stage": "invalid_family",
                "message": f"Family {family} must be one of {spec.FAMILIES}",
            }, EXIT_FAILED
        if arm in spec.TRAINABLE_ARM_IDS and seed not in spec.TRAINING_SEEDS:
            return {
                "status": "refused",
                "mode": mode,
                "stage": "invalid_seed",
                "message": f"Trainable arm {arm} requires seed in {spec.TRAINING_SEEDS}",
            }, EXIT_FAILED

        # Preflight Checkpoint Check for Trainable Arms (②, ③, ⑥):
        # Must load authentic checkpoint; missing checkpoint refuses BEFORE ledger access.
        if arm in spec.TRAINABLE_ARM_IDS:
            ckpt_path = paths["output_root"] / "checkpoints" / f"arm{arm}_{family}_seed{seed}" / "model_weights.npz"
            if not ckpt_path.is_file():
                return {
                    "status": "refused",
                    "mode": mode,
                    "stage": "missing_checkpoint",
                    "message": f"Checkpoint missing for arm {arm}, family {family}, seed {seed} at {ckpt_path}",
                }, EXIT_FAILED

    elif mode == "final-eval":
        if family is None:
            family = "P"
        if family not in spec.FAMILIES:
            return {
                "status": "refused",
                "mode": mode,
                "stage": "invalid_family",
                "message": f"Family {family} must be one of {spec.FAMILIES}",
            }, EXIT_FAILED

        # Check read-once marker on final partition before opening ledger
        fam_sealed_root = paths["data_dir"] / "sealed_final" / family
        has_marker = False
        if fam_sealed_root.is_dir():
            for sub in fam_sealed_root.iterdir():
                if sub.is_dir():
                    marker = export.final_marker_path(sub)
                    if marker.is_file():
                        has_marker = True
                        break

        legacy_marker = paths["data_dir"] / "final" / f".read_once_{family}"
        global_legacy_marker = paths["data_dir"] / "final" / ".read_once"
        if has_marker or legacy_marker.is_file() or (family == "P" and global_legacy_marker.is_file()):
            return {
                "status": "refused",
                "mode": mode,
                "stage": "final_eval_already_read_once",
                "message": f"Final partition for family {family} has already been read once; further access is permanently forbidden",
            }, EXIT_FAILED

    # Preflight Dataset Identity Verification (train, eval, final-eval)
    if mode in ("train", "eval", "final-eval"):
        runner = getattr(args, "runner", None)
        has_dataset = (paths["data_dir"] / "generator_identity.json").exists() or (paths["data_dir"] / "student").is_dir()
        if runner is None or has_dataset:
            try:
                data_runner.verify_dataset_generator_identity(paths["data_dir"], doc)
            except Exception as exc:
                return {
                    "status": "refused",
                    "mode": mode,
                    "stage": "dataset_identity_verification",
                    "reasons": [str(exc)],
                    "message": str(exc),
                }, EXIT_FAILED

    # Preflight C: check anti-duplicate completed run in ledger (read-only snapshot)
    if worker.check_cell_already_completed(paths["ledger"], mode, arm, family, seed):
        return {
            "status": "refused",
            "mode": mode,
            "stage": "duplicate_execution",
            "message": f"Cell ({mode}, arm={arm}, family={family}, seed={seed}) has already completed",
        }, EXIT_FAILED

    # Preflight D: per-cell budget calculation and phase ceiling check
    try:
        requested_wall = getattr(args, "wall_budget_seconds", None)
        cell_budget = _get_cell_budget(mode, arm, requested_wall)
    except ValueError as exc:
        return {
            "status": "refused",
            "mode": mode,
            "stage": "budget_validation",
            "message": str(exc),
        }, EXIT_REFUSED_RESOURCE

    budget_ok, consumed, ceiling = _check_phase_budget_ceiling(paths["ledger"], cell_budget)
    if not budget_ok:
        return {
            "status": "refused",
            "mode": mode,
            "stage": "phase_budget_exceeded",
            "consumed_seconds": consumed,
            "cell_budget_seconds": cell_budget,
            "ceiling_seconds": ceiling,
            "message": f"Adding cell budget ({cell_budget} s) to consumed ({consumed} s) exceeds ceiling ({ceiling} s)",
        }, EXIT_REFUSED_RESOURCE

    # Preflights passed! Now acquire worker lock and execute cell.
    clock = getattr(args, "fake_clock", None)
    clock_fn = clock.time if hasattr(clock, "time") else (clock if callable(clock) else time.time)
    runner = getattr(args, "runner", None)
    steps = getattr(args, "steps", None)

    try:
        with worker_lock(paths["lock"]):
            if mode == "final-eval":
                # Mark legacy marker on disk as secondary safeguard
                final_dir = paths["data_dir"] / "final"
                final_dir.mkdir(parents=True, exist_ok=True)
                (final_dir / f".read_once_{family}").write_text("READ_ONCE\n", encoding="utf-8")
                (final_dir / ".read_once").write_text("READ_ONCE\n", encoding="utf-8")

            ledger = worker.E1Ledger(paths["ledger"], clock=clock_fn)
            try:
                result = worker.execute_work_cell(
                    ledger=ledger,
                    mode=mode,
                    arm=arm,
                    family=family,
                    seed=seed,
                    cell_wall_budget=cell_budget,
                    data_dir=paths["data_dir"],
                    output_root=paths["output_root"],
                    clock=clock_fn,
                    runner=runner,
                    steps=steps,
                )
                r_status = result.get("status") if isinstance(result, dict) else None
                if r_status == "stopped":
                    return {
                        "status": "stopped",
                        "mode": mode,
                        "result": result,
                    }, EXIT_REFUSED_RESOURCE
                elif r_status == "failed":
                    return {
                        "status": "failed",
                        "mode": mode,
                        "result": result,
                    }, EXIT_FAILED
                return {
                    "status": "completed",
                    "mode": mode,
                    "result": result,
                }, EXIT_COMPLETED
            finally:
                ledger.close()

    except WorkerLockBusy:
        return {
            "status": "refused",
            "mode": mode,
            "stage": "lock_busy",
            "message": f"Worker lock {paths['lock']} is busy",
        }, EXIT_LOCK_BUSY
    except worker.BudgetStop as exc:
        return {
            "status": "stopped",
            "mode": mode,
            "stage": "budget_exhausted",
            "message": str(exc),
        }, EXIT_REFUSED_RESOURCE
    except Exception as exc:
        return {
            "status": "failed",
            "mode": mode,
            "stage": "execution_failed",
            "message": str(exc),
        }, EXIT_FAILED
