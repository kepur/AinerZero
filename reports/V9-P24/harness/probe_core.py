#!/usr/bin/env python3
"""P24 independent probes for S1 r8 (F1-F8) -- author-independent.

Each case is deliberately written from the S1-R8-DECISION text, not from the
author's test assertions: different numbers, different injection points, and an
explicit result object (``passed`` + observations) so a guard-broken copy of
the source can be shown to turn the same probe red.

Run one case:  .venv/bin/python reports/V9-P24/harness/probe_core.py --case f2
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import traceback
from pathlib import Path
from types import SimpleNamespace

REPO = Path("/Users/mac/AinerWorkFlow/AinerZero")
SRC = Path(os.environ.get("P24_SRC", str(REPO / "src"))).resolve()
sys.path.insert(0, str(SRC))
sys.path.insert(0, str(REPO / "tests" / "v9" / "experiments"))

import numpy as np  # noqa: E402

from ainerzero.v9.experiments.s1 import completion, data, identity, prereg, spec, worker  # noqa: E402
import s1_testkit as tk  # noqa: E402

UPDATES = 3510
DEADLINE = 450.0
D_DEADLINE = 2.0


# --------------------------------------------------------------------------- host
def setup_host(tmp: Path) -> tuple[Path, Path]:
    host = Path(tmp)
    root = host / "artifacts" / "v9" / "s1" / "phase1"
    root.mkdir(parents=True, exist_ok=True)
    (host / "RESEARCH_LOG.md").write_text("# P24 isolated probe host (no approval)\n", encoding="utf-8")
    spec.REGISTERED_HOST_ROOT = host.resolve()
    spec.PHASE1_ROOT = root
    spec.RESEARCH_LOG = host / "RESEARCH_LOG.md"
    ledger = worker.PrepLedger(root / "control.sqlite3")
    try:
        ledger.store.create_experiment(
            worker.prep_experiment_manifest(), worker.PREP_REQUEST_ID, worker.PREP_EXPERIMENT_ID
        )
    finally:
        ledger.close()
    return host, root


def _frozen_timing() -> dict:
    path = REPO / "artifacts" / "v9" / "s1" / "phase1" / "r8" / "pre_registration.json"
    return json.loads(path.read_text(encoding="utf-8"))["timing"]


def _registered_step() -> float:
    return float(_frozen_timing()["measured_step_seconds"])


def _d_step() -> float:
    return float(_frozen_timing()["smoke"]["d_candidate"]["forward_loss_step_seconds"])


def frozen_probe_document(identity_payload: dict | None = None) -> dict:
    """The registered production shape, built from the frozen measurement of record."""
    identity_payload = identity_payload or tk.FAKE_IDENTITY
    smoke = tk.fake_smoke(_registered_step())
    smoke["d_candidate"]["forward_loss_step_seconds"] = _d_step()
    document = prereg.build_frozen(
        prereg.build_draft(data_identity=identity_payload, parameter_counts=tk.FAKE_COUNTS),
        smoke=smoke,
        data_identity=identity_payload,
        created_unix=1_000.0,
    )
    assert int(document["training_protocol"]["updates"]) == UPDATES
    assert float(document["timing"]["deadline_seconds"]) == DEADLINE
    assert float(document["timing"]["arm1_deadline_seconds"]) == D_DEADLINE
    return document


def eval_root(tmp: Path) -> tuple[Path, Path, dict]:
    host, root = setup_host(tmp)
    manifest, final = make_synthetic_dataset(tmp)
    ident = data.dataset_identity(manifest)
    target = Path(tmp) / "datasets" / manifest["dataset_digest"]
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(final, target)
    data.write_dataset_ref(root, manifest, target)
    document = frozen_probe_document(ident)
    path, digest, _ = tk.write_frozen(root / "pre_registration.json", document=document)
    return root, path, document


def make_synthetic_dataset(tmp: Path):
    plan = tk.make_plan()
    staging = Path(tmp) / "staging"
    tk.write_staging(staging, plan=plan)
    final = Path(tmp) / "dataset"
    manifest = data.finalize_dataset(
        staging, final, plan=plan, generation_seconds=12.5, generation_command=["p24-probe"]
    )
    return manifest, final


def train_root(tmp: Path) -> tuple[Path, Path, str, Path]:
    host, root = setup_host(tmp)
    manifest, final = make_synthetic_dataset(tmp)
    ident = data.dataset_identity(manifest)
    target = Path(tmp) / "datasets" / manifest["dataset_digest"]
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(final, target)
    data.write_dataset_ref(root, manifest, target)
    document = frozen_probe_document(ident)
    path, digest, _ = tk.write_frozen(root / "pre_registration.json", document=document)
    log = tk.write_research_log(host / "RESEARCH_LOG.md", approval_sha=digest)
    spec.RESEARCH_LOG = log
    return root, path, digest, log


# --------------------------------------------------------------------------- CPU doubles
class Clock:
    def __init__(self, start: float = 1_000.0) -> None:
        self.now = start
        self.sleeps: list[float] = []

    def perf_counter(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(float(seconds))
        self.now += float(seconds)

    def advance(self, seconds: float) -> None:
        self.now += float(seconds)


class FakeModel:
    def __init__(self, seed: int) -> None:
        self.params = {"w": np.zeros(4, dtype=np.float32)}


class TrainDouble:
    name = "p24-cpu-train-double"

    def __init__(self, clock: Clock) -> None:
        self.clock = clock
        self.gradient_calls = 0
        self.saves: list[int] = []

    def build_model(self, arm_id, seed):
        return FakeModel(seed)

    def make_optimizer(self, protocol):
        return {}

    def init_optimizer(self, optimizer, model):
        return None

    def value_and_grad(self, model):
        def apply(m, batch):
            self.gradient_calls += 1
            self.clock.advance(0.01)
            return (np.float32(1.0), {}), {"w": np.zeros(4, dtype=np.float32)}

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
        return "0" * 64

    def window_probe(self, model, windows, protocol, *, max_batches=None):
        return {"rows": [{"loss": 2.5}], "batches": 1}

    def save_params(self, model, path, *, exclusive=False):
        path = Path(path)
        if exclusive and path.exists():
            raise FileExistsError(path)
        self.saves.append(int(path.stem.split("-")[-1]) if "-" in path.stem else UPDATES)
        with open(path, "xb" if exclusive else "wb") as handle:
            np.savez(handle, **model.params)


class DCandidateDouble:
    name = "p24-cpu-d-double"

    def __init__(self) -> None:
        self.calls = 0
        self.d_candidate_info = {
            "parameter_count": tk.FAKE_COUNTS["arm1"],
            "parameter_sha256": "cbb14d878dfda5af816dbc4903c7fb811aabbcfb17ce494f00e994ab3d6b286a",
        }

    def eval_d_candidate(self, *, seed: int):
        self.calls += 1
        return SimpleNamespace(
            metrics={
                "symbol_nll_t0": 0.17,
                "symbol_nll_t1": 2.61,
                "observation_loss_t0": 0.21,
                "observation_loss_t1": 2.88,
            }
        )


def open_train_ledger(root: Path) -> tuple[worker.PrepLedger, str]:
    ledger = worker.PrepLedger(Path(root) / "control.sqlite3")
    document = {
        "training_protocol": {"updates": UPDATES, "checkpoint_updates": [0, UPDATES]},
        "timing": {"deadline_seconds": DEADLINE},
        "data_identity": {"dataset_digest": "e" * 64},
    }
    run_id = worker._open_train_run(
        document,
        ledger,
        {"document_sha256": "d" * 64, "line": "probe", "line_number": 1},
        arm_id="arm2",
        seed=0,
    )
    ledger.begin_work(run_id, work_state="training")
    return ledger, run_id


# --------------------------------------------------------------------------- cases
def case_f2() -> dict:
    """F2: every product-writable lifecycle state is accounted; unknown refused."""
    active = ["created", "initializing", "collecting", "training", "validating", "pausing", "paused", "stopping"]
    rows = {}
    ok = True
    for state in active:
        run = SimpleNamespace(
            run_id=f"probe-{state}", state=state, reserved_active_seconds=12.0,
            created_at=5_000.0, updated_at=5_100.0,
        )
        counted = worker.run_conservative_wall_seconds(run, instant=6_000.0)
        rows[state] = counted
        if abs(counted - 1_000.0) > 1e-9:  # max(12, now-created=1000)
            ok = False
    terminal = {}
    for state in ["completed", "stopped", "failed"]:
        run = SimpleNamespace(
            run_id=f"probe-{state}", state=state, reserved_active_seconds=12.0,
            created_at=5_000.0, updated_at=5_125.0,
        )
        counted = worker.run_conservative_wall_seconds(run, instant=9_999_999.0)
        terminal[state] = counted
        if abs(counted - 125.0) > 1e-9:  # max(12, updated-created) not calendar age
            ok = False
    errors = {}
    for bad in ["quarantined", None]:
        try:
            worker.run_conservative_wall_seconds(
                SimpleNamespace(run_id="probe-bad", state=bad, reserved_active_seconds=1.0,
                                created_at=5_000.0, updated_at=5_100.0),
                instant=6_000.0,
            )
            ok = False
            errors[str(bad)] = "ACCEPTED (bad)"
        except Exception as exc:  # noqa: BLE001
            errors[str(bad)] = type(exc).__name__
            if type(exc).__name__ != "LedgerStateInvalid":
                ok = False
    return {"passed": ok, "active_counts": rows, "terminal_counts": terminal, "unknown_refusals": errors}


def case_f5() -> dict:
    """F5: raw reservation/timestamps validated before max; NaN never charged zero."""
    bad_reserved = [float("nan"), float("inf"), float("-inf"), -7.0, None, "9.5", True]
    reserved = {}
    ok = True
    for value in bad_reserved:
        run = SimpleNamespace(
            run_id="probe-reserved", state="training", reserved_active_seconds=value,
            created_at=5_000.0, updated_at=5_050.0,
        )
        try:
            counted = worker.run_conservative_wall_seconds(run, instant=5_500.0)
            ok = False
            reserved[repr(value)] = f"ACCEPTED counted={counted}"
        except Exception as exc:  # noqa: BLE001
            reserved[repr(value)] = type(exc).__name__
            if type(exc).__name__ != "LedgerStateInvalid":
                ok = False
    missing = SimpleNamespace(run_id="no-field", state="completed", created_at=5_000.0, updated_at=5_050.0)
    try:
        worker.run_conservative_wall_seconds(missing, instant=5_500.0)
        ok = False
        reserved["<missing field>"] = "ACCEPTED"
    except Exception as exc:  # noqa: BLE001
        reserved["<missing field>"] = type(exc).__name__
    timestamps = {}
    for value in [float("nan"), float("inf"), 1e308, -1e308, None, "not-a-time"]:
        run = SimpleNamespace(
            run_id="probe-ts", state="completed", reserved_active_seconds=1.0,
            created_at=value, updated_at=5_050.0,
        )
        try:
            worker.run_conservative_wall_seconds(run, instant=5_500.0)
            ok = False
            timestamps[repr(value)] = "ACCEPTED"
        except Exception as exc:  # noqa: BLE001
            timestamps[repr(value)] = type(exc).__name__
            if type(exc).__name__ != "LedgerTimestampInvalid":
                ok = False
    reverse = SimpleNamespace(
        run_id="probe-reverse", state="completed", reserved_active_seconds=1.0,
        created_at=6_000.0, updated_at=5_000.0,
    )
    try:
        worker.run_conservative_wall_seconds(reverse, instant=7_000.0)
        ok = False
        rev = "ACCEPTED"
    except Exception as exc:  # noqa: BLE001
        rev = type(exc).__name__
        if rev != "LedgerTimestampInvalid":
            ok = False
    future = SimpleNamespace(
        run_id="probe-future", state="training", reserved_active_seconds=7.0,
        created_at=6_000.0, updated_at=6_000.0,
    )
    future_counted = worker.run_conservative_wall_seconds(future, instant=5_000.0)
    if abs(future_counted - 7.0) > 1e-9:
        ok = False
    return {
        "passed": ok,
        "reserved_refusals": reserved,
        "timestamp_refusals": timestamps,
        "reverse": rev,
        "legitimate_future_high_water_counted": future_counted,
    }


def _load_r3_builder():
    path = REPO / "scripts" / "v9_baseline_manifest_r3.py"
    module_spec = importlib.util.spec_from_file_location("v9_baseline_manifest_r3", path)
    module = importlib.util.module_from_spec(module_spec)
    assert module_spec.loader is not None
    module_spec.loader.exec_module(module)
    return module


def case_f6() -> dict:
    """F6: original A2 digest algorithm + pinned bytes + every negative path."""
    builder = _load_r3_builder()
    report = identity.verify_d_candidate_identity()
    manifest_path = Path(spec.ARM_SPECS["arm1"]["identity"]["frozen_manifest"])
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    original = builder.digest(
        {k: v for k, v in manifest.items() if k not in ("generated_at", "manifest_digest", "policy_check")}
    )
    registered = spec.ARM_SPECS["arm1"]["identity"]["frozen_manifest_digest"]
    ok = (
        report["frozen_manifest_file_sha256"] == "2c991f052f322112fa97c57f52585bd99779c3178b21108efdc494596184be5b"
        and original == registered == report["frozen_manifest_digest"]
        and report["manifest_digest_match"] is True
        and report["entries_verified"] == 9
        and report["mlx_imported"] is False
        and all(v["match"] for v in report["registered_fields"].values())
    )
    negatives = {}
    identity_dict = spec.ARM_SPECS["arm1"]["identity"]
    saved = dict(identity_dict)

    # a) replaced manifest bytes are refused
    forged = Path(tempfile.mkdtemp()) / "baseline_manifest.json"
    tampered = json.loads(json.dumps(manifest))
    tampered["files"] = tampered["files"][:-1]
    forged.write_text(json.dumps(tampered, sort_keys=True, indent=1) + "\n", encoding="utf-8")
    try:
        spec.ARM_SPECS["arm1"]["identity"]["frozen_manifest"] = str(forged)
        identity.verify_d_candidate_identity()
        negatives["replaced_bytes"] = "ACCEPTED (bad)"
        ok = False
    except Exception as exc:  # noqa: BLE001
        negatives["replaced_bytes"] = f"{type(exc).__name__}: {exc}"
    finally:
        spec.ARM_SPECS["arm1"]["identity"].update(saved)

    # b) digest-only: bytes pinned to the forged file, registered digest unchanged
    forged_bytes_sha = hashlib.sha256(forged.read_bytes()).hexdigest()
    spec.ARM_SPECS["arm1"]["identity"]["frozen_manifest"] = str(forged)
    spec.ARM_SPECS["arm1"]["identity"]["frozen_manifest_file_sha256"] = forged_bytes_sha
    try:
        identity.verify_d_candidate_identity()
        negatives["digest_mismatch"] = "ACCEPTED (bad)"
        ok = False
    except Exception as exc:  # noqa: BLE001
        negatives["digest_mismatch"] = f"{type(exc).__name__}: {exc}"
        if "self digest does not match" not in str(exc):
            ok = False
    finally:
        spec.ARM_SPECS["arm1"]["identity"].update(saved)

    # c) one flipped byte under the pinned pilot tree
    tmp_repo = Path(tempfile.mkdtemp()) / "repo"
    pilot_rel = saved["pilot_dir"]
    shutil.copytree(REPO / pilot_rel, tmp_repo / pilot_rel)
    victim = next(
        row["path"] for row in manifest["files"]
        if row["path"].startswith(f"{pilot_rel}/checkpoints/") and row["path"].endswith("metadata.json")
    )
    target = tmp_repo / victim
    target.write_bytes(target.read_bytes() + b"\n")
    try:
        identity.verify_d_candidate_identity(repo_root=tmp_repo)
        negatives["flipped_byte"] = "ACCEPTED (bad)"
        ok = False
    except Exception as exc:  # noqa: BLE001
        negatives["flipped_byte"] = f"{type(exc).__name__}: {exc}"
        if "A2-pinned file changed" not in str(exc):
            ok = False
    return {
        "passed": ok,
        "original_r3_digest": original,
        "registered_digest": registered,
        "identity_digest": report["frozen_manifest_digest"],
        "manifest_file_sha256": report["frozen_manifest_file_sha256"],
        "entries_verified": report["entries_verified"],
        "negatives": negatives,
    }


def case_f7() -> dict:
    """F7: the CPU identity/worker import path does not import MLX or arms."""
    src_dir = Path(worker.__file__).resolve().parents[4]
    script = (
        "import sys, json;"
        "from ainerzero.v9.experiments.s1 import identity, worker, completion, prereg, data, evaluation, metrics;"
        "from ainerzero.v9.experiments.s1 import identity as i;"
        "r=i.verify_d_candidate_identity();"
        "print(json.dumps({'mlx': 'mlx' in sys.modules,"
        "'arms': any(m.endswith('.arms') for m in sys.modules),"
        "'entries': r['entries_verified'],'mlx_imported': r['mlx_imported']}))"
    )
    env = {"PYTHONPATH": str(src_dir), "PATH": "/usr/bin:/bin"}
    out = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True, env=env, cwd=str(REPO)
    )
    payload = {"returncode": out.returncode, "stderr": out.stderr[-800:]}
    if out.returncode == 0:
        payload.update(json.loads(out.stdout))
    passed = (
        out.returncode == 0
        and payload.get("mlx") is False
        and payload.get("arms") is False
        and payload.get("entries") == 9
        and payload.get("mlx_imported") is False
    )
    return {"passed": passed, **payload,
            "scope_note": "identity/worker/completion/prereg/data/evaluation/metrics are the CPU "
                          "bookkeeping and identity entry path; smoke is the real MLX forward+loss "
                          "measurement and is out of the F7 lazy-isolation scope"}


def _run_train_chain() -> dict:
    """Drive the real public run_worker train branch twice with a CPU double."""
    tmp = Path(tempfile.mkdtemp())
    root, path, digest, log = train_root(tmp)
    clock = Clock()
    double = TrainDouble(clock)
    saved_time = worker.time
    saved_batches = worker.data.iter_batches

    def _batches(*args, **kwargs):
        while True:
            yield {"obs": None}

    worker.time = clock
    worker.data.iter_batches = _batches
    try:
        report = worker.run_worker(
            "train", output_root=root, limits=spec.RESOURCE_LIMITS,
            wall_budget_seconds=DEADLINE, prereg_path=path, research_log=log,
            arm="arm2", seed=0, backend=double,
        )
        first_mlx = "mlx" in sys.modules
        first_arms = any(m.endswith(".arms") for m in sys.modules)
        ledger = worker.PrepLedger(root / "control.sqlite3")
        try:
            run = ledger.get(report.get("run_id")) if report.get("run_id") else None
            rows_after_first = len(ledger.store.list_runs())
        finally:
            ledger.close()
        second = worker.run_worker(
            "train", output_root=root, limits=spec.RESOURCE_LIMITS,
            wall_budget_seconds=DEADLINE, prereg_path=path, research_log=log,
            arm="arm2", seed=0, backend=TrainDouble(Clock()),
        )
        ledger = worker.PrepLedger(root / "control.sqlite3")
        try:
            rows_after_second = len(ledger.store.list_runs())
            arm_rows = [
                r for r in ledger.store.list_runs()
                if (r.config_snapshot or {}).get("arm_id") == "arm2"
                and int((r.config_snapshot or {}).get("seed", -1)) == 0
            ]
        finally:
            ledger.close()
    finally:
        worker.time = saved_time
        worker.data.iter_batches = saved_batches

    receipt = (report.get("details") or {}).get("receipt") or {}
    accounting = receipt.get("ledger_accounting") or {}
    phases = [e["phase"] for e in (report.get("completion_protocol") or {}).get("events", [])]
    return {
        "first_status": report.get("status"),
        "first_error": report.get("error"),
        "gradient_calls": double.gradient_calls,
        "saves": double.saves,
        "run_state": None if run is None else run["state"],
        "reserved_optimizer_steps": None if run is None else int(run["reserved_optimizer_steps"]),
        "ledger_accounting": accounting,
        "completion_phase_tail": phases[-4:],
        "mlx_imported_in_process": first_mlx,
        "arms_imported_in_process": first_arms,
        "second_status": second.get("status"),
        "second_refused_stage": second.get("refused_stage"),
        "rows_after_first": rows_after_first,
        "rows_after_second": rows_after_second,
        "arm2_seed0_rows": len(arm_rows),
        "mlx_usable": _mlx_usable(),
    }


def _mlx_usable() -> bool:
    try:
        import mlx.core  # noqa: F401
        return True
    except Exception:  # noqa: BLE001
        return False


def _chain_passed(result: dict, *, require_mlx_absent: bool) -> bool:
    ok = (
        result["first_status"] == "completed"
        and result["gradient_calls"] == UPDATES
        and result["saves"] == [0, 439, 878, 1755, UPDATES]
        and result["run_state"] == "completed"
        and result["reserved_optimizer_steps"] == UPDATES
        and int((result["ledger_accounting"] or {}).get("optimizer_reservations", -1)) == UPDATES
        and int((result["ledger_accounting"] or {}).get("post_final_optimizer_reservations", -1)) == 0
        and result["second_status"] == "refused"
        and result["second_refused_stage"] == "already_attempted"
        and result["rows_after_first"] == result["rows_after_second"]
        and result["arm2_seed0_rows"] == 1
    )
    if require_mlx_absent:
        ok = ok and result["mlx_imported_in_process"] is False and result["mlx_usable"] is False
    else:
        # No model code may be loaded: mlx.core may appear only through the
        # resource guard's allocator probe, never through ``arms``.
        ok = ok and result["arms_imported_in_process"] is False
    return ok


def case_f8() -> dict:
    """F8: public run_worker train branch runs the whole CPU control flow; rerun blocked."""
    baseline = _run_train_chain()
    # A child with a shim that makes ``mlx`` unimportable proves the CPU chain
    # does not *require* MLX; the shim only changes the probe environment.
    shim = Path(tempfile.mkdtemp()) / "shim"
    (shim / "mlx").mkdir(parents=True)
    (shim / "mlx" / "__init__.py").write_text(
        "raise ImportError('P24 probe: MLX intentionally unavailable')\n", encoding="utf-8"
    )
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join(
        [str(shim), str(SRC), str(REPO / "tests" / "v9" / "experiments")]
    )
    child = subprocess.run(
        [sys.executable, str(Path(__file__).resolve()), "--case", "f8_nomlx"],
        capture_output=True, text=True, env=env, cwd=str(REPO),
    )
    try:
        child_payload = json.loads(child.stdout.strip().splitlines()[-1])
    except Exception:  # noqa: BLE001
        child_payload = {"passed": False, "stdout_tail": child.stdout[-800:], "stderr_tail": child.stderr[-800:]}
    passed = _chain_passed(baseline, require_mlx_absent=False) and child_payload.get("passed") is True
    return {
        "passed": passed,
        "baseline": baseline,
        "baseline_passed": _chain_passed(baseline, require_mlx_absent=False),
        "no_mlx_child": child_payload,
        "no_mlx_child_returncode": child.returncode,
        "note": "in the real environment mlx is imported by resource_gate.mlx_memory_probe "
                "(a local allocator probe), never by model code (arms is absent); with mlx "
                "unimportable the same public chain still completes",
    }


def case_f8_nomlx() -> dict:
    result = _run_train_chain()
    result["passed"] = _chain_passed(result, require_mlx_absent=True)
    return result


# ---- F1: three slow-motion cut points + no second registration row --------
def _f1_rerun(root: Path, ledger, run_id: str) -> dict:
    """Retry the terminal transaction after the cut; it must not add a run row."""
    rerun = worker._complete_run(
        report={"schema": "probe", "mode": "train"},
        ledger=ledger,
        run_id=run_id,
        protocol=completion.CompletionProtocol(deadline_seconds=20.0),
        output_root=root,
        reason="s1_train_completed",
        kind="train",
    )
    rows = ledger.store.list_runs()
    mine = [row for row in rows if row.run_id == run_id]
    return {
        "report_status": rerun.get("status"),
        "rows_after_rerun": len(rows),
        "rows_for_run": len(mine),
        "state_after_rerun": mine[0].state if mine else None,
        "markers_after_rerun": [m.name for m in completion.invalid_markers(root / "runs" / run_id)],
    }


def _f1_before(tmp: Path) -> dict:
    root = setup_host(tmp)[1]
    ledger, run_id = open_train_ledger(root)
    protocol = completion.CompletionProtocol(deadline_seconds=20.0)
    armed = {"done": False}

    def seam(phase, elapsed):
        if phase == "train:pre_terminal_commit" and not armed["done"]:
            armed["done"] = True
            protocol.started -= 21.0  # 21 s stall measured from the commit check

    completion.TEST_SEAM = seam
    try:
        report = worker._complete_run(
            report={"schema": "probe", "mode": "train"}, ledger=ledger, run_id=run_id,
            protocol=protocol, output_root=root, reason="s1_train_completed", kind="train",
        )
    finally:
        completion.TEST_SEAM = None
    state = ledger.get(run_id)["state"]
    markers = completion.invalid_markers(root / "runs" / run_id)
    rows = len(ledger.store.list_runs())
    rerun = _f1_rerun(root, ledger, run_id)
    ledger.close()
    return {
        "cut": "before_commit",
        "report_status": report["status"],
        "refused_stage": report.get("refused_stage"),
        "ledger_state": state,
        "markers": [m.name for m in markers],
        "rows": rows,
        "rerun": rerun,
        "passed": (
            report["status"] == "failed"
            and state == "failed"
            and rows == 1
            and rerun["rows_after_rerun"] == rows
            and rerun["rows_for_run"] == 1
            and rerun["state_after_rerun"] == state
            and bool(rerun["markers_after_rerun"])
        ),
    }


def _f1_inside(tmp: Path) -> dict:
    root = setup_host(tmp)[1]
    ledger, run_id = open_train_ledger(root)
    protocol = completion.CompletionProtocol(deadline_seconds=0.30)
    state = {}
    released = threading.Event()

    def seam(phase, elapsed):
        if phase != "train:terminal_commit:before" or "holder" in state:
            return
        holder = sqlite3.connect(root / "control.sqlite3", timeout=6.0, isolation_level=None,
                                 check_same_thread=False)
        holder.execute("BEGIN IMMEDIATE")
        state["holder"] = holder

        def _release():
            time.sleep(0.65)
            holder.execute("COMMIT")
            released.set()

        threading.Thread(target=_release, daemon=True).start()

    completion.TEST_SEAM = seam
    try:
        report = worker._complete_run(
            report={"schema": "probe", "mode": "train"}, ledger=ledger, run_id=run_id,
            protocol=protocol, output_root=root, reason="s1_train_completed", kind="train",
        )
        released.wait(timeout=10.0)
    finally:
        completion.TEST_SEAM = None
        state.get("holder") and state["holder"].close()
    record = ledger.get(run_id)
    markers = completion.invalid_markers(root / "runs" / run_id)
    rows = len(ledger.store.list_runs())
    marker_payload = json.loads(markers[0].read_text(encoding="utf-8")) if markers else {}
    rerun = _f1_rerun(root, ledger, run_id)
    ledger.close()
    return {
        "cut": "inside_commit_sql_lock",
        "report_status": report["status"],
        "refused_stage": report.get("refused_stage"),
        "expired_in_flight": (report.get("completion_protocol") or {}).get("expired_in_flight"),
        "ledger_state": record["state"],
        "ledger_reason": record["reason"],
        "markers": [m.name for m in markers],
        "marker_ledger_state": marker_payload.get("ledger_state_at_invalidation"),
        "rolled_back": report.get("rolled_back"),
        "rows": rows,
        "rerun": rerun,
        "passed": (
            report["status"] == "failed"
            and (report.get("completion_protocol") or {}).get("expired_in_flight") is True
            and record["state"] == "completed"
            and record["reason"] == "s1_train_completed"
            and report.get("rolled_back") is False
            and bool(markers)
            and rows == 1
            and rerun["rows_after_rerun"] == rows
            and rerun["rows_for_run"] == 1
            and rerun["state_after_rerun"] == "completed"
            and bool(rerun["markers_after_rerun"])
        ),
    }


class _AfterCommitLedger:
    """Delegating ledger that advances the probe clock *after* the commit lands."""

    def __init__(self, ledger, clock: Clock, jump: float) -> None:
        self._ledger = ledger
        self._clock = clock
        self._jump = jump

    def get(self, run_id):
        return self._ledger.get(run_id)

    def finish(self, run_id, state, reason):
        record = self._ledger.finish(run_id, state, reason)
        self._clock.advance(self._jump)  # slow post-commit step, after the row landed
        return record

    def reserve(self, *a, **k):
        return self._ledger.reserve(*a, **k)

    def begin_work(self, *a, **k):
        return self._ledger.begin_work(*a, **k)

    def close(self):
        return self._ledger.close()


def _f1_after(tmp: Path) -> dict:
    root = setup_host(tmp)[1]
    ledger, run_id = open_train_ledger(root)
    clock = Clock(start=1_000.0)
    protocol = completion.CompletionProtocol(deadline_seconds=1.0, clock=clock.perf_counter)
    proxy = _AfterCommitLedger(ledger, clock, jump=2.0)
    report = worker._complete_run(
        report={"schema": "probe", "mode": "train"}, ledger=proxy, run_id=run_id,
        protocol=protocol, output_root=root, reason="s1_train_completed", kind="train",
    )
    record = ledger.get(run_id)
    markers = completion.invalid_markers(root / "runs" / run_id)
    rows = len(ledger.store.list_runs())
    rerun = _f1_rerun(root, ledger, run_id)
    ledger.close()
    return {
        "cut": "after_commit_write_returned",
        "report_status": report["status"],
        "refused_stage": report.get("refused_stage"),
        "expired_in_flight": (report.get("completion_protocol") or {}).get("expired_in_flight"),
        "ledger_state": record["state"],
        "ledger_reason": record["reason"],
        "markers": [m.name for m in markers],
        "rolled_back": report.get("rolled_back"),
        "rows": rows,
        "rerun": rerun,
        "passed": (
            report["status"] == "failed"
            and (report.get("completion_protocol") or {}).get("expired_in_flight") is True
            and record["state"] == "completed"
            and report.get("rolled_back") is False
            and bool(markers)
            and rows == 1
            and rerun["rows_after_rerun"] == rows
            and rerun["rows_for_run"] == 1
            and rerun["state_after_rerun"] == "completed"
            and bool(rerun["markers_after_rerun"])
        ),
    }


def case_f1() -> dict:
    base = Path(tempfile.mkdtemp())
    results = {}
    for name, fn in (("before", _f1_before), ("inside", _f1_inside), ("after", _f1_after)):
        sub = base / name
        sub.mkdir()
        try:
            results[name] = fn(sub)
        except Exception:  # noqa: BLE001
            results[name] = {"passed": False, "error": traceback.format_exc()[-1200:]}
    return {"passed": all(r.get("passed") for r in results.values()), "cuts": results}


# ---- F3/F4 + both registration orders ------------------------------------
def case_f3() -> dict:
    tmp = Path(tempfile.mkdtemp())
    root, path, _doc = eval_root(tmp)
    double = DCandidateDouble()
    report = worker.run_worker(
        "eval", output_root=root, limits=spec.RESOURCE_LIMITS,
        wall_budget_seconds=300.0, prereg_path=path, arm="arm1", seed=0, backend=double,
    )
    ledger = worker.PrepLedger(root / "control.sqlite3")
    try:
        run = ledger.get(report.get("run_id")) if report.get("run_id") else None
    finally:
        ledger.close()
    snapshot = (run or {}).get("config_snapshot", {})
    budget = snapshot.get("budget", {})
    passed = (
        report.get("status") == "completed"
        and double.calls == 1
        and run is not None
        and float(budget.get("max_wall_seconds", -1)) == D_DEADLINE
        and 0 < float(run.get("reserved_active_seconds", -1)) <= D_DEADLINE
        and int(run.get("reserved_optimizer_steps", -1)) == 0
        and snapshot.get("arm_id") == "arm1"
    )
    return {
        "passed": passed,
        "status": report.get("status"),
        "refused_stage": report.get("refused_stage"),
        "error": report.get("error"),
        "d_forward_calls": double.calls,
        "run_snapshot_budget": budget,
        "reserved_active_seconds": (run or {}).get("reserved_active_seconds"),
        "reserved_optimizer_steps": (run or {}).get("reserved_optimizer_steps"),
        "snapshot_arm_id": snapshot.get("arm_id"),
        "experiment_manifest": worker.train_experiment_manifest(updates=UPDATES)["experiment_budget"],
    }


def case_f4() -> dict:
    tmp = Path(tempfile.mkdtemp())
    root, path, _doc = eval_root(tmp)
    first = worker.run_worker(
        "eval", output_root=root, limits=spec.RESOURCE_LIMITS,
        wall_budget_seconds=300.0, prereg_path=path, arm="arm1", seed=0,
        backend=DCandidateDouble(),
    )
    ledger = worker.PrepLedger(root / "control.sqlite3")
    try:
        rows_first = [
            r for r in ledger.store.list_runs() if (r.config_snapshot or {}).get("arm_id") == "arm1"
        ]
    finally:
        ledger.close()
    second = worker.run_worker(
        "eval", output_root=root, limits=spec.RESOURCE_LIMITS,
        wall_budget_seconds=300.0, prereg_path=path, arm="arm1", seed=0,
        backend=DCandidateDouble(),
    )
    ledger = worker.PrepLedger(root / "control.sqlite3")
    try:
        rows_second = [
            r for r in ledger.store.list_runs() if (r.config_snapshot or {}).get("arm_id") == "arm1"
        ]
        all_rows = len(ledger.store.list_runs())
    finally:
        ledger.close()
    # legacy row that only *looks* like D: no arm_id, D-ish purpose
    legacy_db = Path(tempfile.mkdtemp()) / "legacy.sqlite3"
    from ainerzero.runtime.lifecycle import RunStore

    store = RunStore(legacy_db)
    try:
        exp = store.create_experiment(
            worker.train_experiment_manifest(updates=UPDATES),
            f"{worker.TRAIN_EXPERIMENT_ID}:training", worker.TRAIN_EXPERIMENT_ID,
        )
        snap = worker.run_config_snapshot(wall_budget_seconds=2.0, purpose="s1_phase1_d_candidate_eval:arm1")
        store.create_run(snap, "legacy-request", "run-legacy-p24", experiment_id=exp.experiment_id, role="auxiliary")
        store.transition("run-legacy-p24", "initializing", reason="legacy")
        store.transition("run-legacy-p24", "validating", reason="legacy")
        legacy_state = worker.d_candidate_attempt_state(store.list_runs())
    finally:
        store.close()
    # an arm2 row is not mistaken for D
    store = RunStore(Path(tempfile.mkdtemp()) / "other.sqlite3")
    try:
        exp = store.create_experiment(
            worker.train_experiment_manifest(updates=UPDATES),
            f"{worker.TRAIN_EXPERIMENT_ID}:training", worker.TRAIN_EXPERIMENT_ID,
        )
        snap = worker.run_config_snapshot(wall_budget_seconds=300.0, purpose="s1_phase1_eval:arm2")
        snap["arm_id"] = "arm2"
        store.create_run(snap, "other-request", "run-arm2-p24", experiment_id=exp.experiment_id, role="auxiliary")
        store.transition("run-arm2-p24", "initializing", reason="x")
        store.transition("run-arm2-p24", "validating", reason="x")
        other_state = worker.d_candidate_attempt_state(store.list_runs())
    finally:
        store.close()
    passed = (
        first.get("status") == "completed"
        and len(rows_first) == 1
        and second.get("status") == "refused"
        and second.get("refused_stage") == "already_attempted"
        and len(rows_second) == 1
        and legacy_state["status"] == "unidentifiable"
        and legacy_state["run_ids"] == ["run-legacy-p24"]
        and other_state["status"] == "ok"
        and all_rows == 1
    )
    return {
        "passed": passed,
        "first_status": first.get("status"),
        "second_status": second.get("status"),
        "second_refused_stage": second.get("refused_stage"),
        "arm1_rows_before": len(rows_first),
        "arm1_rows_after": len(rows_second),
        "all_rows": all_rows,
        "legacy_state": legacy_state,
        "other_arm_state": other_state,
    }


def _order_train_then_d() -> dict:
    from ainerzero.runtime.lifecycle import RunStore

    ledger = worker.PrepLedger(Path(tempfile.mkdtemp()) / "order-train-d.sqlite3")
    document = {"training_protocol": {"updates": UPDATES, "checkpoint_updates": []},
                "timing": {"deadline_seconds": DEADLINE}, "data_identity": {"dataset_digest": "e" * 64}}
    try:
        tr = worker._open_train_run(document, ledger, {"document_sha256": "d" * 64}, arm_id="arm2", seed=0)
        ledger.begin_work(tr, work_state="validating")
        ledger.finish(tr, "completed", "probe")
        rid = ledger.open_aux_run(
            mode="eval", wall_budget_seconds=D_DEADLINE,
            manifest=worker.train_experiment_manifest(updates=UPDATES),
            request_id=f"{worker.TRAIN_EXPERIMENT_ID}:eval:arm1",
            experiment_id=worker.TRAIN_EXPERIMENT_ID,
            snapshot_extra={"arm_id": "arm1", "seed": 0, "purpose": "d"},
        )
        return {"passed": True, "train_run": tr, "d_run": rid, "error": None}
    except Exception as exc:  # noqa: BLE001
        return {"passed": False, "error": f"{type(exc).__name__}: {exc}"}
    finally:
        ledger.close()


def _order_d_then_train() -> dict:
    ledger = worker.PrepLedger(Path(tempfile.mkdtemp()) / "order-d-train.sqlite3")
    document = {"training_protocol": {"updates": UPDATES, "checkpoint_updates": []},
                "timing": {"deadline_seconds": DEADLINE}, "data_identity": {"dataset_digest": "e" * 64}}
    try:
        rid = ledger.open_aux_run(
            mode="eval", wall_budget_seconds=D_DEADLINE,
            manifest=worker.train_experiment_manifest(updates=UPDATES),
            request_id=f"{worker.TRAIN_EXPERIMENT_ID}:eval:arm1",
            experiment_id=worker.TRAIN_EXPERIMENT_ID,
            snapshot_extra={"arm_id": "arm1", "seed": 0, "purpose": "d"},
        )
        ledger.begin_work(rid, work_state="validating")
        ledger.finish(rid, "completed", "probe")
        tr = worker._open_train_run(document, ledger, {"document_sha256": "d" * 64}, arm_id="arm2", seed=0)
        return {"passed": True, "train_run": tr, "d_run": rid, "error": None}
    except Exception as exc:  # noqa: BLE001
        return {"passed": False, "error": f"{type(exc).__name__}: {exc}"}
    finally:
        ledger.close()


def case_order() -> dict:
    train_then_d = _order_train_then_d()
    d_then_train = _order_d_then_train()
    return {
        "passed": bool(train_then_d["passed"] and d_then_train["passed"]),
        "train_then_d": train_then_d,
        "d_then_train": d_then_train,
        "note": "S1-R8-DECISION F3 requires both registration orders to coexist in one experiment",
    }


CASES = {
    "f1": case_f1,
    "f2": case_f2,
    "f3": case_f3,
    "f4": case_f4,
    "f5": case_f5,
    "f6": case_f6,
    "f7": case_f7,
    "f8": case_f8,
    "f8_nomlx": case_f8_nomlx,
    "order": case_order,
}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--case", required=True, choices=sorted(CASES))
    ns = ap.parse_args()
    try:
        result = CASES[ns.case]()
    except Exception:  # noqa: BLE001
        result = {"passed": False, "error": traceback.format_exc()[-2000:]}
    result["case"] = ns.case
    print(json.dumps(result, default=str, sort_keys=True))
    return 0 if result.get("passed") else 1


if __name__ == "__main__":
    raise SystemExit(main())
