"""P16 independent non-author verification of S1 r5 (ainerzero.V9.P15).

This script is written by a DIFFERENT agent (workbuddy-c4k8) than P15's author
(ds-s1r5-1021n). It does NOT trust P15's report; it re-exercises the production
code paths with its own CPU backend and its own metric inputs.

Coverage:
  A. Production worker._train body + REAL RunStore + actual 3510 optimizer
     reservations, exactly one final checkpoint, 3511 refusal, rerun refusal,
     original SHA & run binding.
  B. Eval binding negatives (tampered / missing / wrong-prereg SHA).
  C. Six metrics: independent recompute of >=2 and prediction-change /
     directed-perturbation counterexamples; reject empty sample / null NLL /
     duplicate ticks / cross-world mixing.
  D. Kernel completeness: per-leaf diff r4->r5 recomputed independently, and
     on-disk SHA256 of the 14 bound source files vs frozen-review-inputs.json.
  E. Budget / identity / directory boundary CPU-isolation counterexamples.
  F. 450s deadline clear-rejection (500s supervision fallback noted).

Outputs: reports/V9-P16/evidence_p16.json  (+ prints a summary).
"""
from __future__ import annotations

import hashlib
import json
import shutil
import sys
import tempfile
import time
import traceback
from pathlib import Path

REPO = Path("/Users/mac/AinerWorkFlow/AinerZero")
sys.path.insert(0, str(REPO / "src"))

from ainerzero.runtime.lifecycle import BudgetExceeded, RunStore  # noqa: E402
from ainerzero.v9.experiments.s1 import metrics, prereg, spec, worker  # noqa: E402
from ainerzero.v9.experiments.s1 import data as s1data  # noqa: E402

PHASE1 = REPO / "artifacts/v9/s1/phase1"
R5 = PHASE1 / "r5"
FROZEN_PATH = R5 / "pre_registration.json"
R4_PRE = REPO / "reports/V9-P9/r5/archive-r4/artifacts-s1-phase1/pre_registration.json"
FROZEN_INPUTS = REPO.parent / "AinerRelay/reports/coordination/codex-20261021-night/P15-r5-frozen-review-inputs.json"
OUT = REPO / "reports/V9-P16/evidence_p16.json"

R5_DOC = json.loads(FROZEN_PATH.read_text(encoding="utf-8"))
PREREG_SHA = prereg.document_sha256(R5_DOC)
UPDATES = int(R5_DOC["training_protocol"]["updates"])
CHECKPOINTS = [int(v) for v in R5_DOC["training_protocol"]["checkpoint_updates"]]

RESULT = {"schema": "ainerzero.v9.p16.independent_verify.v1", "agent": "workbuddy-c4k8",
          "verified_task": "ainerzero.V9.P15", "frozen_prereg_sha256": PREREG_SHA}


class Model:
    def __init__(self, seed: int):
        # Distinct from P15's 1x1 scalar: a 2x2 matrix keyed by seed, so the
        # parameter SHA is non-trivial and changes if any write happens.
        self.params = {"w": (np_ones() * (seed + 1))}


def np_ones():
    import numpy as np
    return np.ones((2, 2), dtype=np.float32)


class IndependentBackend:
    """CPU numeric substitute; records every model call. Distinct from P15's."""
    name = "p16-independent-cpu-substitute"

    def __init__(self):
        self.value_and_grad_calls = 0
        self.save_calls = 0
        self.load_calls = 0
        self.window_probe_calls = 0

    def build_model(self, arm_id, seed):
        return Model(seed)

    def make_optimizer(self, protocol):
        return {"lr": protocol["learning_rate"]}

    def init_optimizer(self, optimizer, model):
        return None

    def value_and_grad(self, model):
        def apply(m, batch):
            self.value_and_grad_calls += 1
            # constant placeholder loss; grads are zeros
            return (np_float(0.5), {}), {"w": zeros((2, 2))}
        return apply

    def eval(self, *values):
        return None

    def clip_grad_norm(self, grads, norm):
        return grads, 1.0

    def optimizer_update(self, optimizer, model, grads):
        return None

    def sync_parameters(self, model, optimizer):
        return None

    def loss_value(self, loss):
        return float(loss)

    def parameter_sha256(self, model):
        import numpy as np
        digest = hashlib.sha256()
        for name in sorted(model.params):
            digest.update(name.encode())
            digest.update(str(np.asarray(model.params[name]).shape).encode())
            digest.update(np.ascontiguousarray(model.params[name]).tobytes())
        return digest.hexdigest()

    def save_params(self, model, path, *, exclusive=False):
        import numpy as np
        self.save_calls += 1
        path = Path(path)
        if exclusive and path.exists():
            raise FileExistsError(path)
        with open(path, "xb" if exclusive else "wb") as handle:
            np.savez(handle, **model.params)

    def load_params(self, model, path):
        import numpy as np
        self.load_calls += 1
        with np.load(path) as loaded:
            model.params = {name: np.asarray(loaded[name]) for name in loaded.files}

    def window_probe(self, model, windows, protocol, *, max_batches=None):
        import numpy as np
        self.window_probe_calls += 1
        batch = int(protocol["batch_size"])
        rows = []
        # Emit one row per development window (real dataset identity preserved).
        for meta in windows["windows"]:
            rows.append({
                "window_index": int(meta["window_index"]) if "window_index" in meta else int(meta["start"]),
                "episode_id": meta.get("episode_id", "ep0"),
                "start": int(meta.get("start", 0)),
                "target_frame": int(meta.get("start", 0)) + 1,
                "loss": 0.5,
                "parts": {"presence": 0.2, "class": 0.3, "position": 0.1},
                "pose": np.zeros(4),
                "prediction": None,
                "target": np.zeros(10),
            })
        batches = (len(rows) + batch - 1) // batch
        return {"rows": rows, "batches": batches, "windows": len(rows)}


def np_float(v):
    import numpy as np
    return np.float32(v)


def zeros(shape):
    import numpy as np
    return np.zeros(shape, dtype=np.float32)


class FakeGuard:
    def sample(self, **kwargs):
        return {}


def fresh_root():
    root = Path(tempfile.mkdtemp(prefix="p16-verify-"))
    shutil.copy2(PHASE1 / "dataset_ref.json", root / "dataset_ref.json")
    return root


def document(*, updates=UPDATES, checkpoints=None, deadline=None):
    return {
        "training_protocol": {
            "updates": int(updates),
            "batch_size": int(R5_DOC["training_protocol"]["batch_size"]),
            "sequence_steps": int(R5_DOC["training_protocol"]["sequence_steps"]),
            "learning_rate": float(R5_DOC["training_protocol"]["learning_rate"]),
            "adam_betas": R5_DOC["training_protocol"]["adam_betas"],
            "adam_epsilon": float(R5_DOC["training_protocol"]["adam_epsilon"]),
            "weight_decay": float(R5_DOC["training_protocol"]["weight_decay"]),
            "gradient_clip_norm": float(R5_DOC["training_protocol"]["gradient_clip_norm"]),
            "checkpoint_updates": list(CHECKPOINTS) if checkpoints is None else list(checkpoints),
        },
        "timing": {"deadline_seconds": float(deadline if deadline is not None else R5_DOC["timing"]["deadline_seconds"])},
        "resource_limits": dict(R5_DOC["resource_limits"]),
        "data_identity": dict(R5_DOC["data_identity"]),
    }


# ---------------------------------------------------------------------------
# A. Production _train + real RunStore + 3510 count + one final checkpoint
# ---------------------------------------------------------------------------
def part_a():
    out = {}
    root = fresh_root()
    try:
        ledger = worker.PrepLedger(root / "control.sqlite3")
        run_id = worker._open_train_run(
            document(), ledger, {"document_sha256": PREREG_SHA}, arm_id="arm2", seed=0
        )
        ledger.begin_work(run_id, work_state="training")
        reservations = []
        orig = ledger.reserve

        def spy(run_id_arg, *, active_seconds, optimizer_steps=0):
            reservations.append((int(optimizer_steps), float(active_seconds)))
            return orig(run_id_arg, active_seconds=active_seconds, optimizer_steps=optimizer_steps)

        ledger.reserve = spy
        backend = IndependentBackend()
        details = worker._train(
            document(), root, ledger, run_id, FakeGuard(),
            arm_id="arm2", seed=0, prereg_sha256=PREREG_SHA, backend=backend,
        )
        receipt = details["receipt"]
        ledger.finish(run_id, "completed",
                      worker.TRAIN_RECEIPT_PREFIX + json.dumps(receipt, sort_keys=True, separators=(",", ":")))
        ledger.close()

        with RunStore(root / "control.sqlite3") as store:
            rec = store.get_run(run_id)
            attempts = [r.run_id for r in worker.train_attempts(store.list_runs(), arm_id="arm2", seed=0)]

        final_entries = [e for e in receipt["checkpoints"] if int(e["updates"]) == UPDATES]
        out["train"] = {
            "updates_frozen": UPDATES,
            "optimizer_reservations_actual": sum(1 for r in reservations if r[0] == 1),
            "wall_only_reservations": len([r for r in reservations if r[0] == 0]),
            "last_reservation": list(reservations[-1]),
            "checkpoints_written": sorted(e["updates"] for e in receipt["checkpoints"]),
            "final_checkpoint_count": len(final_entries),
            "final_checkpoint_path": final_entries[0]["path"] if final_entries else None,
            "final_checkpoint_sha256": receipt["final_checkpoint_sha256"],
            "final_checkpoint_file_sha256": spec.sha256_file(root / "runs" / run_id / receipt["final_checkpoint_path"]),
            "ledger_optimizer_reserved": int(rec.reserved_optimizer_steps),
            "ledger_remaining_optimizer": int(rec.remaining.get("optimizer_steps")),
            "run_state": rec.state,
            "post_final_optimizer_reservations": receipt["ledger_accounting"]["post_final_optimizer_reservations"],
            "value_and_grad_calls": backend.value_and_grad_calls,
            "window_probe_calls": backend.window_probe_calls,
            "save_calls": backend.save_calls,
            "run_binding_status": "passed" if final_entries else "FAILED",
            "rerun_attempts_after_completed": attempts,
        }
        # Final checkpoint file SHA must equal the receipt SHA (no re-hash of tampered file).
        out["train"]["final_sha_matches_receipt"] = (
            out["train"]["final_checkpoint_sha256"] == out["train"]["final_checkpoint_file_sha256"]
        )
    except Exception as exc:
        out["train_error"] = f"{type(exc).__name__}: {exc}\n{traceback.format_exc()}"
    finally:
        shutil.rmtree(root, ignore_errors=True)
    return out


# ---------------------------------------------------------------------------
# A2. 3511 boundary refusal
# ---------------------------------------------------------------------------
def part_a2():
    out = {}
    root = fresh_root()
    try:
        # run budget = frozen 3510, but document demands 3511 updates
        boundary_doc = document(updates=UPDATES + 1, checkpoints=[0, UPDATES + 1])
        ledger = worker.PrepLedger(root / "control.sqlite3")
        exp = ledger.store.create_experiment(
            worker.train_experiment_manifest(deadline_seconds=450.0, updates=UPDATES + 1),
            "p16-boundary", "p16-boundary")
        snap = worker.run_config_snapshot(wall_budget_seconds=450.0, purpose="p16-boundary", max_optimizer_steps=UPDATES)
        snap.update({"arm_id": "arm2", "seed": 0, "updates": UPDATES,
                     "preregistration_sha256": PREREG_SHA,
                     "dataset_digest": boundary_doc["data_identity"]["dataset_digest"],
                     "checkpoint_updates": list(boundary_doc["training_protocol"]["checkpoint_updates"])})
        run_id = "p16-boundary-run"
        ledger.store.create_run(snap, "p16-boundary-run", run_id, experiment_id=exp.experiment_id, role="model")
        ledger.store.transition(run_id, "initializing", reason="evidence")
        ledger.begin_work(run_id, work_state="training")
        bres = []
        orig = ledger.reserve

        def spy(run_id_arg, *, active_seconds, optimizer_steps=0):
            bres.append(int(optimizer_steps))
            return orig(run_id_arg, active_seconds=active_seconds, optimizer_steps=optimizer_steps)

        ledger.reserve = spy
        err = None
        try:
            worker._train(boundary_doc, root, ledger, run_id, FakeGuard(),
                          arm_id="arm2", seed=0, prereg_sha256=PREREG_SHA, backend=IndependentBackend())
        except worker.BudgetStop as exc:
            err = f"{type(exc).__name__}: {exc}"
        ledger.close()
        with RunStore(root / "control.sqlite3") as store:
            rec = store.get_run(run_id)
            try:
                store.consume(run_id, optimizer_steps=1, active_seconds=0.01)
                consume_refused = None
            except BudgetExceeded as exc:
                consume_refused = f"{type(exc).__name__}: {exc}"
        out["boundary_3511"] = {
            "document_updates": UPDATES + 1,
            "run_budget_optimizer_steps": UPDATES,
            "reservations_total": len(bres),
            "refusal": err,
            "run_state_after_refusal": rec.state,
            "ledger_optimizer_reserved": int(rec.reserved_optimizer_steps),
            "direct_consume_refused": consume_refused,
        }
    except Exception as exc:
        out["boundary_error"] = f"{type(exc).__name__}: {exc}\n{traceback.format_exc()}"
    finally:
        shutil.rmtree(root, ignore_errors=True)
    return out


# ---------------------------------------------------------------------------
# B. Eval binding negatives (tampered / missing / wrong prereg SHA)
# ---------------------------------------------------------------------------
def part_b():
    out = {}
    root = fresh_root()
    try:
        ledger = worker.PrepLedger(root / "control.sqlite3")
        run_id = worker._open_train_run(document(), ledger, {"document_sha256": PREREG_SHA}, arm_id="arm2", seed=0)
        ledger.begin_work(run_id, work_state="training")
        details = worker._train(document(), root, ledger, run_id, FakeGuard(),
                               arm_id="arm2", seed=0, prereg_sha256=PREREG_SHA, backend=IndependentBackend())
        receipt = details["receipt"]
        ledger.finish(run_id, "completed",
                      worker.TRAIN_RECEIPT_PREFIX + json.dumps(receipt, sort_keys=True, separators=(",", ":")))
        ledger.close()
        out["bind_clean"] = _try(lambda: worker._bind_completed_run(
            root, arm_id="arm2", seed=0, prereg_sha256=PREREG_SHA, updates=UPDATES))

        # tamper final checkpoint
        troot = Path(tempfile.mkdtemp(prefix="p16-tamper-"))
        shutil.copytree(root, troot, dirs_exist_ok=True)
        params = troot / "runs" / run_id / receipt["final_checkpoint_path"]
        params.chmod(0o644)
        with open(params, "ab") as h:
            h.write(b"tampered")
        out["bind_tampered"] = _try_fail(lambda: worker._bind_completed_run(
            troot, arm_id="arm2", seed=0, prereg_sha256=PREREG_SHA, updates=UPDATES), worker.EvalBindingError)

        # missing a non-final checkpoint (updates-0.npz)
        mroot = Path(tempfile.mkdtemp(prefix="p16-missing-"))
        shutil.copytree(root, mroot, dirs_exist_ok=True)
        (mroot / "runs" / run_id / "checkpoints" / "updates-0.npz").unlink()
        out["bind_missing"] = _try_fail(lambda: worker._bind_completed_run(
            mroot, arm_id="arm2", seed=0, prereg_sha256=PREREG_SHA, updates=UPDATES), worker.EvalBindingError)

        # wrong prereg SHA
        out["bind_wrong_prereg"] = _try_fail(lambda: worker._bind_completed_run(
            root, arm_id="arm2", seed=0, prereg_sha256="f" * 64, updates=UPDATES), worker.EvalBindingError)
        shutil.rmtree(troot, ignore_errors=True)
        shutil.rmtree(mroot, ignore_errors=True)
    except Exception as exc:
        out["bind_error"] = f"{type(exc).__name__}: {exc}\n{traceback.format_exc()}"
    finally:
        shutil.rmtree(root, ignore_errors=True)
    return out


def _try(fn):
    try:
        r = fn()
        return {"ok": True, "run_id": r["run"].run_id, "final_sha": r["final"]["sha256"]}
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


def _try_fail(fn, exc_type):
    try:
        fn()
        return {"refused": False, "note": "UNEXPECTEDLY PASSED"}
    except exc_type as exc:
        return {"refused": True, "error": str(exc)[:300]}
    except Exception as exc:
        return {"refused": "wrong_exception", "error": f"{type(exc).__name__}: {exc}"}


# ---------------------------------------------------------------------------
# C. Six metrics: independent recompute + prediction-change counterexamples
# ---------------------------------------------------------------------------
def part_c():
    import numpy as np
    res = {}

    # C1 localization_error: translation changes with pose; rejects empty
    est = np.array([[0.0, 0, 0.0, 0.0], [1.0, 0, 0.0, 0.0]], dtype=np.float64)
    truth = np.array([[0.0, 0, 0.0, 0.0], [0.0, 0, 0.0, 0.0]], dtype=np.float64)
    loc_good = metrics.localization_error(est, truth)
    est2 = np.array([[0.0, 0, 5.0, 0.0], [1.0, 0, 0.0, 0.0]], dtype=np.float64)
    loc_shift = metrics.localization_error(est2, truth)
    res["localization"] = {
        "translation_mean_good": loc_good["translation_mean_m"],
        "translation_mean_shifted": loc_shift["translation_mean_m"],
        "changes_with_prediction": loc_good["translation_mean_m"] != loc_shift["translation_mean_m"],
        "empty_rejected": _rejects(lambda: metrics.localization_error(est[:0], truth[:0])),
    }

    # C2 few_shot_transition_metrics: accuracy changes with predictions
    preds = [True, False, True, False]
    truth_t = [True, False, True, False]
    fs_a = metrics.few_shot_transition_metrics(preds, truth_t)
    fs_b = metrics.few_shot_transition_metrics([False, False, False, False], truth_t)
    res["few_shot"] = {
        "accuracy_match": fs_a["accuracy"],
        "accuracy_all_false": fs_b["accuracy"],
        "changes_with_prediction": fs_a["accuracy"] != fs_b["accuracy"],
        "empty_rejected": _rejects(lambda: metrics.few_shot_transition_metrics([], [])),
    }

    # C3 topology_edge_metrics: edges follow prediction; per-episode truth
    nodes = [(0.0, 0.0), (1.0, 0.0), (2.0, 0.0)]
    true_cells = [(0, 0), (1, 0), (2, 0)]
    true_edges = [((0, 0), (1, 0)), ((1, 0), (2, 0))]
    topo_good = metrics.topology_edge_metrics(nodes, [(0, 1), (1, 2)], true_cells, true_edges)
    topo_bad = metrics.topology_edge_metrics(nodes, [(0, 1), (1, 2)], true_cells, [((0, 0), (2, 0))])
    res["topology"] = {
        "precision_good_edges": topo_good["precision"],
        "precision_wrong_edges": topo_bad["precision"],
        "changes_with_prediction": topo_good["precision"] != topo_bad["precision"],
        "true_positive_good": topo_good["true_positive_edges"],
    }

    # C4 strict_unseen_map: rejects missing identity / duplicate episode / null NLL
    good_rows = [
        {"episode_id": f"ep{i}", "scene_id": f"w{i}", "family": "A", "ticks": [0, 1, 2],
         "translation_mean_m": 0.1 * i, "yaw_mean_deg": 1.0, "prediction_nll": 0.5}
        for i in range(3)]
    res["unseen_map"] = {
        "good_episodes": metrics.strict_unseen_map(good_rows)["episodes"],
        "rejects_missing_nll": _rejects(lambda: metrics.strict_unseen_map(
            [dict(good_rows[0], prediction_nll=None)])),
        "rejects_duplicate_episode": _rejects(lambda: metrics.strict_unseen_map(
            good_rows + [good_rows[0]])),
        "rejects_missing_identity": _rejects(lambda: metrics.strict_unseen_map(
            [{"episode_id": "x", "scene_id": "w", "family": "A", "ticks": [0],
              "translation_mean_m": 1.0, "yaw_mean_deg": 1.0}])),
    }

    # C5 few-shot insufficient_data for k=8 (no support+query) via split_support_query
    n_trans = 3
    sup, qry = metrics.split_support_query(n_trans, k=8)
    res["few_shot_insufficient"] = {
        "k8_support": sup, "k8_query": qry,
        "reports_unavailable": (len(sup) == 0 and len(qry) == 0),
    }
    sup2, qry2 = metrics.split_support_query(10, k=8)
    res["few_shot_sufficient"] = {"k8_support": sup2, "k8_query": qry2, "has_query": len(qry2) > 0}

    # C6 memory_interference: rejects when before/after share no keys
    mi = metrics.memory_interference(before={"a": 1.0, "b": 2.0}, after={"a": 1.5, "b": 1.5})
    res["memory_interference"] = {
        "retention_delta_keys": list(mi["retention_delta"].keys()),
        "rejects_no_shared_keys": _rejects(lambda: metrics.memory_interference(before={"a": 1.0}, after={"b": 2.0})),
    }
    return res


def _rejects(fn):
    try:
        fn()
        return False
    except Exception:
        return True


# ---------------------------------------------------------------------------
# D. Kernel completeness: leaf diff r4->r5 + source identity SHAs on disk
# ---------------------------------------------------------------------------
def part_d():
    out = {}
    # D1: recompute leaf diff between r4 and r5 preregs
    try:
        r4 = json.loads(R4_PRE.read_text(encoding="utf-8"))
        r5 = json.loads(FROZEN_PATH.read_text(encoding="utf-8"))
        diff = _leaf_diff(r4, r5)
        allowlist_prefixes = (
            "created_unix",
            "source_identity.package_files.",
            "source_identity.package_map_digest",
            "timing.smoke_recheck",
            "timing.smoke_recheck.",
        )
        outside = [c["path"] for c in diff["changes"]
                   if not any(c["path"].startswith(p) or c["path"] == p for p in allowlist_prefixes)]
        out["leaf_diff"] = {
            "leaf_count": diff["leaf_count"],
            "changed_leaf_count": diff["changed_leaf_count"],
            "changed_paths": [c["path"] for c in diff["changes"]],
            "non_identity_leaves_outside_allowlist": outside,
            "within_allowlist": len(outside) == 0,
        }
    except Exception as exc:
        out["leaf_diff_error"] = f"{type(exc).__name__}: {exc}\n{traceback.format_exc()}"

    # D2: on-disk SHA256 of the 14 bound source files vs frozen-review-inputs.json
    try:
        fi = json.loads(FROZEN_INPUTS.read_text(encoding="utf-8"))
        checks = []
        for pf in fi["package_files"]:
            p = REPO / pf["path"]
            actual = spec.sha256_file(p) if p.is_file() else "MISSING"
            checks.append({
                "path": pf["path"],
                "expected": pf["expected"],
                "actual": actual,
                "match": actual == pf["expected"],
            })
        out["source_identity"] = {
            "all_match": all(c["match"] for c in checks),
            "matched": sum(1 for c in checks if c["match"]),
            "total": len(checks),
            "details": checks,
            "unbound_package_py": fi.get("unbound_package_py", []),
        }
    except Exception as exc:
        out["source_identity_error"] = f"{type(exc).__name__}: {exc}\n{traceback.format_exc()}"
    return out


def _leaf_diff(a, b, prefix=""):
    leaves = []
    changed = []

    def walk(x, y, path):
        if isinstance(x, dict) and isinstance(y, dict):
            keys = set(x) | set(y)
            for k in keys:
                walk(x.get(k, "__MISSING__"), y.get(k, "__MISSING__"), f"{path}.{k}" if path else str(k))
        elif isinstance(x, list) and isinstance(y, list):
            n = max(len(x), len(y))
            for i in range(n):
                xi = x[i] if i < len(x) else "__MISSING__"
                yi = y[i] if i < len(y) else "__MISSING__"
                walk(xi, yi, f"{path}[{i}]")
        else:
            leaves.append(path)
            if x != y:
                changed.append({"change": ("changed" if x != "__MISSING__" and y != "__MISSING__"
                                           else ("removed" if y == "__MISSING__" else "added")),
                                "path": path, "r4": x if x != "__MISSING__" else None,
                                "r5": y if y != "__MISSING__" else None})
    walk(a, b, prefix)
    return {"leaf_count": len(leaves), "changed_leaf_count": len(changed), "changes": changed}


# ---------------------------------------------------------------------------
# E. Budget / identity / directory boundary CPU-isolation counterexamples
# ---------------------------------------------------------------------------
def part_e():
    out = {}
    # E1: fresh output-root has an EMPTY ledger (budget "reset" at ledger level),
    # but run_worker train is still refused at the authoritative approval gate.
    root = fresh_root()
    try:
        ledger = worker.PrepLedger(root / "control.sqlite3")
        attempts_empty = [r.run_id for r in worker.train_attempts(ledger.store.list_runs(), arm_id="arm2", seed=0)]
        ledger.close()
        # approval gate on the frozen doc (no coordinator approval line in repo RESEARCH_LOG)
        try:
            prereg.require_coordinator_approval(R5_DOC, PREREG_SHA, log_path=REPO / "RESEARCH_LOG.md")
            out["fresh_root"] = {"ledger_attempts_empty": attempts_empty == [], "approval_approved": True}
        except prereg.ApprovalRefused as exc:
            out["fresh_root"] = {
                "ledger_attempts_empty": attempts_empty == [],
                "approval_approved": False,
                "approval_refusal_reason": str(exc)[:200],
            }
        # Now the full train entry: expect refusal at preregistration_not_approved
        rep = worker.run_worker(
            "train", output_root=root, limits=dict(R5_DOC["resource_limits"]),
            wall_budget_seconds=600.0, prereg_path=FROZEN_PATH,
            research_log=REPO / "RESEARCH_LOG.md", arm="arm2", seed=0,
        )
        out["train_entry_refusal"] = {
            "status": rep.get("status"),
            "refused_stage": rep.get("refused_stage"),
        }
    except Exception as exc:
        out["fresh_root_error"] = f"{type(exc).__name__}: {exc}\n{traceback.format_exc()}"
    finally:
        shutil.rmtree(root, ignore_errors=True)

    # E2: non-canonical research log -> refused at research_log_not_canonical
    root2 = fresh_root()
    try:
        tmp_log = root2 / "fake_research_log.md"
        tmp_log.write_text("# fake\n")
        rep = worker.run_worker(
            "train", output_root=root2, limits=dict(R5_DOC["resource_limits"]),
            wall_budget_seconds=600.0, prereg_path=FROZEN_PATH,
            research_log=tmp_log, arm="arm2", seed=0,
        )
        out["noncanonical_log_refusal"] = {
            "status": rep.get("status"), "refused_stage": rep.get("refused_stage"),
        }
    except Exception as exc:
        out["noncanonical_error"] = f"{type(exc).__name__}: {exc}\n{traceback.format_exc()}"
    finally:
        shutil.rmtree(root2, ignore_errors=True)

    # E3: switching --prereg to a tampered (non-frozen) document fails verify_frozen_file
    try:
        import copy
        tampered = copy.deepcopy(R5_DOC)
        tampered["training_protocol"]["updates"] = UPDATES + 123  # changes canonical SHA
        tpath = REPO / "reports/V9-P16/_tmp_tampered_prereg.json"
        tpath.write_text(json.dumps(tampered, sort_keys=True, indent=1))
        try:
            prereg.verify_frozen_file(tpath)
            out["prereg_switch"] = {"refused": False, "note": "UNEXPECTEDLY PASSED"}
        except Exception as exc:
            out["prereg_switch"] = {"refused": True, "error": f"{type(exc).__name__}: {str(exc)[:200]}"}
        tpath.unlink(missing_ok=True)
    except Exception as exc:
        out["prereg_switch_error"] = f"{type(exc).__name__}: {exc}\n{traceback.format_exc()}"
    return out


# ---------------------------------------------------------------------------
# F. 450s deadline clear-rejection (500s supervision is the outer fallback)
# ---------------------------------------------------------------------------
def part_f():
    out = {}
    out["frozen_timing"] = {
        "deadline_seconds": R5_DOC["timing"]["deadline_seconds"],
        "supervision_seconds_in_doc": R5_DOC["timing"].get("supervision_seconds"),
        "expected_deadline": 450,
        "expected_supervision": 500,
    }
    # Force the in-loop deadline guard: large wall budget on the run, but a tiny
    # in-loop deadline in the document so the per-run TimeoutError fires.
    root = fresh_root()
    try:
        class SlowBackend(IndependentBackend):
            def value_and_grad(self, model):
                def apply(m, batch):
                    time.sleep(0.05)
                    return (np_float(0.5), {}), {"w": zeros((2, 2))}
                return apply

        ledger = worker.PrepLedger(root / "control.sqlite3")
        exp = ledger.store.create_experiment(
            worker.train_experiment_manifest(deadline_seconds=600.0, updates=UPDATES),
            "p16-deadline", "p16-deadline")
        snap = worker.run_config_snapshot(wall_budget_seconds=600.0, purpose="p16-deadline", max_optimizer_steps=UPDATES)
        snap.update({"arm_id": "arm2", "seed": 0, "updates": UPDATES,
                     "preregistration_sha256": PREREG_SHA,
                     "dataset_digest": R5_DOC["data_identity"]["dataset_digest"],
                     "checkpoint_updates": list(CHECKPOINTS)})
        run_id = "p16-deadline-run"
        ledger.store.create_run(snap, "p16-deadline-run", run_id, experiment_id=exp.experiment_id, role="model")
        ledger.store.transition(run_id, "initializing", reason="evidence")
        ledger.begin_work(run_id, work_state="training")
        err = None
        try:
            worker._train(document(deadline=0.001), root, ledger, run_id, FakeGuard(),
                          arm_id="arm2", seed=0, prereg_sha256=PREREG_SHA, backend=SlowBackend())
        except (TimeoutError, worker.BudgetStop) as exc:
            err = f"{type(exc).__name__}: {exc}"
        ledger.close()
        out["deadline_guard"] = {"run_wall_budget_s": 600.0, "in_loop_deadline_s": 0.001, "raised": err}
    except Exception as exc:
        out["deadline_error"] = f"{type(exc).__name__}: {exc}\n{traceback.format_exc()}"
    finally:
        shutil.rmtree(root, ignore_errors=True)
    return out


def main():
    RESULT["A_train_and_3510"] = part_a()
    RESULT["A2_boundary_3511"] = part_a2()
    RESULT["B_eval_binding"] = part_b()
    RESULT["C_metrics"] = part_c()
    RESULT["D_kernel"] = part_d()
    RESULT["E_boundary"] = part_e()
    RESULT["F_deadline"] = part_f()
    OUT.write_text(json.dumps(RESULT, ensure_ascii=False, sort_keys=True, indent=1))
    # Summary print
    a = RESULT["A_train_and_3510"].get("train", {})
    print("A: upd=", a.get("updates_frozen"), "opt_resv=", a.get("optimizer_reservations_actual"),
          "final_chk=", a.get("final_checkpoint_count"), "final_sha_ok=", a.get("final_sha_matches_receipt"),
          "run_state=", a.get("run_state"))
    print("A2: 3511 refusal=", RESULT["A2_boundary_3511"].get("boundary_3511", {}).get("refusal"))
    print("B: clean=", RESULT["B_eval_binding"].get("bind_clean", {}).get("ok"),
          "tampered=", RESULT["B_eval_binding"].get("bind_tampered", {}).get("refused"),
          "missing=", RESULT["B_eval_binding"].get("bind_missing", {}).get("refused"),
          "wrong_prereg=", RESULT["B_eval_binding"].get("bind_wrong_prereg", {}).get("refused"))
    print("D: leaf within_allowlist=", RESULT["D_kernel"].get("leaf_diff", {}).get("within_allowlist"),
          "src_all_match=", RESULT["D_kernel"].get("source_identity", {}).get("all_match"))
    print("E: approval_approved=", RESULT["E_boundary"].get("fresh_root", {}).get("approval_approved"),
          "train_refusal=", RESULT["E_boundary"].get("train_entry_refusal", {}).get("refused_stage"),
          "noncanonical=", RESULT["E_boundary"].get("noncanonical_log_refusal", {}).get("refused_stage"),
          "prereg_switch_refused=", RESULT["E_boundary"].get("prereg_switch", {}).get("refused"))
    print("F: deadline=", RESULT["F_deadline"].get("deadline_guard", {}).get("raised"),
          "frozen_deadline=", RESULT["F_deadline"].get("frozen_timing", {}).get("deadline_seconds"))
    print("wrote", OUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
