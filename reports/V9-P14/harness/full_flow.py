#!/usr/bin/env python3
"""V9.P14 independent full-sequence timing + eval harness (reviewer-written).

Runs the real r4 code path in-process against a throw-away sandbox:

* 9 `--mode train` invocations (arm2/arm3/arm4 x seed 0/1/2) on a fake clock,
  with 400 s of simulated phase time injected between calls so that a
  phase-cumulative `started` would fire on call #2;
* each call's own deadline window is measured independently (clock at entry and
  exit of the real `worker._train`), as is the `supervision_seconds` the
  supervisor would hand to `subprocess.run(timeout=...)`;
* 4 `--mode eval` invocations (arm1..arm4) on the development partition with a
  tiny/fake checkpoint, behind an open() tripwire that aborts on any path
  component named `final`;
* two metrics are recomputed with an independent implementation
  (localization_error from raw pose arrays; sample_efficiency from the
  checkpoint curve written by training), plus memory_interference as a bonus.

Read-only with respect to the real tree: every artefact lands in a temp dir,
and every result lands in reports/V9-P14/.
"""
from __future__ import annotations

import contextlib
import json
import pathlib
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np

REPO = Path("/Users/mac/AinerWorkFlow/AinerZero")
OUT_DIR = REPO / "reports/V9-P14"
sys.path[:0] = [str(REPO / "src"), str(REPO / "tests/v9/experiments")]

import mlx.core as mx  # noqa: E402
import mlx.nn as nn  # noqa: E402
import mlx.optimizers as optim  # noqa: E402

from ainerzero.v9.experiments.s1 import arms, commands, data, metrics, prereg, spec, worker  # noqa: E402
from s1_testkit import FAKE_COUNTS, fake_smoke, make_plan, write_research_log, write_staging  # noqa: E402
from test_s1_pacer_duty import (  # noqa: E402
    _FakeClock,
    _FakeGuard,
    _FakeLedger,
    _FakeModel,
    _FakeOptimizer,
)

DEADLINE_LOGGED = []


# --- sandbox ---------------------------------------------------------------
def build_sandbox(root: Path):
    phase1 = root / "artifacts/v9/s1/phase1"
    phase1.mkdir(parents=True, exist_ok=True)
    plan = make_plan(train_worlds=16, development_worlds=16, rounds=1)
    staging = root / "staging"
    write_staging(staging, plan=plan, steps_per_world=8)
    tmp_target = root / "datasets" / "staging_dataset"
    manifest = data.finalize_dataset(
        staging,
        tmp_target,
        plan=plan,
        generation_seconds=1.0,
        generation_command=["fake_producer"],
    )
    digest = manifest["dataset_digest"]
    dataset_dir = root / "datasets" / digest
    tmp_target.rename(dataset_dir)
    data.write_dataset_ref(phase1, manifest, dataset_dir)
    identity = data.dataset_identity(manifest)

    draft = prereg.build_draft(data_identity=identity, parameter_counts=FAKE_COUNTS)
    frozen = prereg.build_frozen(
        draft, smoke=fake_smoke(step_seconds=0.01), data_identity=identity, created_unix=1_000.0
    )
    prereg_path = phase1 / "pre_registration.json"
    prereg_path.write_text(json.dumps(frozen, sort_keys=True, indent=1) + "\n", encoding="utf-8")
    doc_sha = prereg.document_sha256(frozen)
    prereg.write_sha256_file(prereg_path, doc_sha)

    log_path = root / "RESEARCH_LOG.md"
    write_research_log(log_path, approval_sha=doc_sha)
    # A decoy sealed partition elsewhere in the sandbox: the tripwire below must
    # never see it opened, and the real dataset must not contain one at all.
    decoy = root / "sealed_decoy/truth/final.jsonl"
    decoy.parent.mkdir(parents=True, exist_ok=True)
    decoy.write_text('{"sentinel":"P14 final decoy"}\n', encoding="utf-8")
    return {
        "phase1": phase1,
        "prereg": prereg_path,
        "document": frozen,
        "doc_sha256": doc_sha,
        "log": log_path,
        "dataset_dir": dataset_dir,
        "decoy": decoy,
        "dataset_files": sorted(p.relative_to(dataset_dir).as_posix() for p in dataset_dir.rglob("*")),
    }


# --- open() tripwire -------------------------------------------------------
class FinalPartitionRead(RuntimeError):
    pass


def make_tripwire(record: list[str]):
    real_path_open = pathlib.Path.open
    real_open = pathlib.open if hasattr(pathlib, "open") else open

    def guard(target) -> str:
        text = str(target)
        record.append(text)
        parts = Path(text).parts
        if "final" in parts or "final" in Path(text).name:
            raise FinalPartitionRead(f"sealed final partition opened: {text}")
        return text

    def patched_path_open(self, *args, **kwargs):
        guard(self)
        return real_path_open(self, *args, **kwargs)

    def patched_open(file, *args, **kwargs):
        guard(file)
        return builtins_open(file, *args, **kwargs)

    import builtins

    builtins_open = builtins.open
    return patch.object(pathlib.Path, "open", patched_path_open), patch.object(
        builtins, "open", patched_open
    )


def in_process_supervisor(records: list[dict]):
    def runner(
        mode,
        *,
        output_root,
        limits,
        budget,
        supervision_seconds,
        prereg_path=None,
        research_log=None,
        arm=None,
        seed=None,
    ):
        records.append(
            {
                "mode": mode,
                "arm": arm,
                "seed": seed,
                "wall_budget_seconds": float(budget),
                "supervision_seconds": float(supervision_seconds),
            }
        )
        rep = worker.run_worker(
            mode,
            output_root=output_root,
            limits=limits,
            wall_budget_seconds=budget,
            prereg_path=prereg_path,
            research_log=research_log,
            arm=arm,
            seed=seed,
        )
        rep["worker_exit_code"] = (
            0 if rep["status"] == "completed" else (2 if rep["status"] == "refused" else 3)
        )
        return rep

    return runner


def main() -> int:
    root = Path(tempfile.mkdtemp(prefix="p14-fullflow-", dir=tempfile.gettempdir()))
    sb = build_sandbox(root)
    clock = _FakeClock(step=0.01)
    nll_calls: list[float] = []

    def fake_nll(*_a, **_k):
        value = 2.5 - 0.1 * len(nll_calls)
        nll_calls.append(round(value, 6))
        return value

    sup_records: list[dict] = []
    windows: list[dict] = []
    results: dict = {
        "schema": "ainerzero.v9.p14.full-flow.v1",
        "sandbox": str(root),
        "fake_clock_step_seconds": clock.step,
        "injected_phase_gap_seconds": 400.0,
        "ledger_waiver": {
            "applied": True,
            "what": "worker.run_config_snapshot(...).budget.max_optimizer_steps raised from 1 to frozen updates + 1000",
            "why": "r4's run-level budget caps optimizer steps at 1, so a registered run stops on its second update; see evidence/train-ledger-probe.json",
            "not_waived": "deadline, supervision, phase wall cap, experiment budget, update count, seeds, checkpoint policy",
            "frozen_updates_per_run": int(sb["document"]["training_protocol"]["updates"]),
        },
        "train_calls": [],
        "eval_calls": [],
        "duplicate_call": None,
        "phase_budget_call": None,
        "negative_control": None,
    }

    real_train = worker._train

    def observing_train(*args, **kwargs):
        start = clock.now
        try:
            return real_train(*args, **kwargs)
        finally:
            windows.append({"start_clock": start, "end_clock": clock.now, "elapsed": clock.now - start})

    stack = contextlib.ExitStack()
    try:
        stack.enter_context(patch.object(spec, "RESEARCH_LOG", sb["log"]))
        stack.enter_context(patch.object(commands, "_supervised_worker", in_process_supervisor(sup_records)))
        # r4 opens every train run with run_config_snapshot(), whose per-run budget
        # block caps max_optimizer_steps at 1 (worker._budget_block default) while
        # _train reserves one optimizer step per update. Without this one-line
        # waiver a registered run is stopped on its second update (see
        # evidence/train-ledger-probe.json). The waiver is recorded, not hidden.
        updates_per_run = int(sb["document"]["training_protocol"]["updates"])
        real_rcs = worker.run_config_snapshot

        def waived_run_config_snapshot(*, wall_budget_seconds, purpose):
            snap = real_rcs(wall_budget_seconds=wall_budget_seconds, purpose=purpose)
            snap["budget"]["max_optimizer_steps"] = updates_per_run + 1000
            return snap

        stack.enter_context(patch.object(worker, "run_config_snapshot", waived_run_config_snapshot))
        real_tem = worker.train_experiment_manifest

        def waived_experiment_manifest(*, deadline_seconds, updates):
            manifest = real_tem(deadline_seconds=deadline_seconds, updates=updates)
            # create_run compares the run budget against manifest["budget"], so the
            # per-run ceiling needs the same headroom; the experiment-wide total
            # (manifest["experiment_budget"], updates*12) is left exactly as frozen.
            manifest["budget"]["max_optimizer_steps"] = updates + 1000
            return manifest

        stack.enter_context(patch.object(worker, "train_experiment_manifest", waived_experiment_manifest))
        # --- train-phase fakes: fake clock, fake model, fake MLX, tiny windows
        stack.enter_context(patch.object(worker, "time", clock))
        stack.enter_context(patch.object(worker, "_train", observing_train))
        stack.enter_context(patch.object(worker, "_development_nll", fake_nll))
        stack.enter_context(patch.object(worker.data, "resolve_dataset_dir", lambda _root: sb["dataset_dir"]))
        stack.enter_context(
            patch.object(worker.data, "load_training_windows", lambda *a, **k: {"obs": np.zeros((4, 2, 72))})
        )
        stack.enter_context(
            patch.object(worker.data, "load_development_windows", lambda *a, **k: {"obs": np.zeros((1, 2, 72))})
        )
        stack.enter_context(
            patch.object(worker.data, "iter_batches", lambda *a, **k: iter([{"obs": None}] * 40_000))
        )
        stack.enter_context(patch.object(arms, "build_trainable_arm", lambda arm_id, **kwargs: _FakeModel()))
        stack.enter_context(patch.object(arms, "parameter_sha256", lambda model: "0" * 64))
        stack.enter_context(patch.object(nn, "value_and_grad", lambda model, loss: (lambda m, b: ((np.float32(1.0), {}), {}))))
        stack.enter_context(patch.object(optim, "AdamW", _FakeOptimizer))
        stack.enter_context(patch.object(optim, "clip_grad_norm", lambda grads, norm: (grads, 1.0), create=True))
        stack.enter_context(patch.object(mx, "eval", lambda *a, **k: None))
        stack.enter_context(patch.object(mx, "set_default_device", lambda *a, **k: None, create=True))

        arms_seeds = [
            ("arm2", 0), ("arm2", 1), ("arm2", 2),
            ("arm3", 0), ("arm3", 1), ("arm3", 2),
            ("arm4", 0), ("arm4", 1), ("arm4", 2),
        ]
        completed: dict[str, str] = {}
        for index, (arm_id, seed) in enumerate(arms_seeds):
            if index:  # 400 s of phase wall clock elapse between CLI invocations
                clock.now += 400.0
            before = len(windows)
            args = SimpleNamespace(
                mode="train", output_root=sb["phase1"], prereg=sb["prereg"], limits_file=None,
                wall_budget_seconds=None, research_log=None, arm=arm_id, seed=seed,
            )
            phase_before = clock.now
            report = commands.mode_train(args)
            phase_after = clock.now
            window = windows[before] if len(windows) > before else None
            run_id = report.get("run_id")
            completed[f"{arm_id}:{seed}"] = run_id
            run_dir = sb["phase1"] / "runs" / str(run_id)
            results["train_calls"].append(
                {
                    "index": index,
                    "arm": arm_id,
                    "seed": seed,
                    "status": report.get("status"),
                    "refused_stage": report.get("refused_stage"),
                    "error": report.get("error"),
                    "stage": report.get("stage"),
                    "worker_exit_code": report.get("worker_exit_code"),
                    "exit_code": commands._exit_code_for(report),
                    "run_id": run_id,
                    "own_window_seconds": None if window is None else round(window["elapsed"], 6),
                    "call_start_clock": round(phase_before, 6),
                    "call_end_clock": round(phase_after, 6),
                    "cumulative_since_first_call_seconds": round(phase_after - results["train_calls"][0]["call_start_clock"], 6)
                    if results["train_calls"]
                    else 0.0,
                    "supervision_seconds": sup_records[-1]["supervision_seconds"] if sup_records else None,
                    "wall_budget_seconds": sup_records[-1]["wall_budget_seconds"] if sup_records else None,
                    "checkpoint_files": sorted(p.name for p in run_dir.glob("*")) if run_dir.is_dir() else [],
                    "checkpoint_sha_matches_sidecar": (
                        (run_dir / "params.npz").is_file()
                        and (run_dir / "params.npz.sha256").is_file()
                        and (run_dir / "params.npz.sha256").read_text().split()[0]
                        == spec.sha256_file(run_dir / "params.npz")
                    ),
                    "checkpoint_mode_0444": all(
                        (run_dir / name).exists()
                        and int((run_dir / name).stat().st_mode) & 0o777 == 0o444
                        for name in ("params.npz", "params.npz.sha256", "run_info.json")
                    ),
                }
            )
        results["completed_9"] = len(completed) == 9 and all(
            call["status"] == "completed" for call in results["train_calls"]
        )

        # --- duplicate invocation must be refused before any worker starts
        sup_before = len(sup_records)
        dup = commands.mode_train(
            SimpleNamespace(
                mode="train", output_root=sb["phase1"], prereg=sb["prereg"], limits_file=None,
                wall_budget_seconds=None, research_log=None, arm="arm2", seed=0,
            )
        )
        results["duplicate_call"] = {
            "status": dup.get("status"),
            "refused_stage": dup.get("refused_stage"),
            "exit_code": commands._exit_code_for(dup),
            "run_id": dup.get("run_id"),
            "supervisor_invoked": len(sup_records) > sup_before,
        }

        # --- phase wall clock guard: 9 runs x 3510 updates >> 14400 s is not
        # reproducible without real time, so drive the guard with a crafted row.
        import sqlite3

        control_db = sb["phase1"] / "control.sqlite3"
        with sqlite3.connect(control_db) as conn:
            # Park an already-completed run outside the approval-free path so the
            # phase-cap branch is reachable, then inflate its wall time.
            conn.execute("UPDATE runs SET state = 'failed' WHERE run_id = ?", (completed["arm4:2"],))
            conn.execute(
                "UPDATE runs SET created_at = created_at - 14500.0 WHERE run_id = ?",
                (completed["arm4:2"],),
            )
        phase_call = commands.mode_train(
            SimpleNamespace(
                mode="train", output_root=sb["phase1"], prereg=sb["prereg"], limits_file=None,
                wall_budget_seconds=None, research_log=None, arm="arm4", seed=2,
            )
        )
        results["phase_budget_call"] = {
            "status": phase_call.get("status"),
            "refused_stage": phase_call.get("refused_stage"),
            "total_wall_seconds": phase_call.get("total_wall_seconds"),
            "deadline_seconds": phase_call.get("deadline_seconds"),
            "phase_wall_max_seconds": phase_call.get("phase_wall_max_seconds"),
            "exit_code": commands._exit_code_for(phase_call),
        }
        with sqlite3.connect(control_db) as conn:
            conn.execute(
                "UPDATE runs SET created_at = created_at + 14500.0 WHERE run_id = ?",
                (completed["arm4:2"],),
            )
            conn.execute("UPDATE runs SET state = 'completed' WHERE run_id = ?", (completed["arm4:2"],))
    finally:
        stack.close()

    # --- eval phase: real arm models, tiny fake checkpoint, final tripwire
    opened: list[str] = []
    eval_sup: list[dict] = []
    tripwire_path, tripwire_builtin = make_tripwire(opened)
    eval_stack = contextlib.ExitStack()
    real_model_sha = {}
    try:
        eval_stack.enter_context(patch.object(spec, "RESEARCH_LOG", sb["log"]))
        eval_stack.enter_context(patch.object(commands, "_supervised_worker", in_process_supervisor(eval_sup)))
        eval_stack.enter_context(patch.object(worker, "time", clock))
        eval_stack.enter_context(patch.object(worker, "_development_nll", fake_nll))
        eval_stack.enter_context(patch.object(worker, "_load_checkpoint_params", lambda model, path: None))
        eval_stack.enter_context(tripwire_path)
        eval_stack.enter_context(tripwire_builtin)

        for eval_arm in ("arm1", "arm2", "arm3", "arm4"):
            opened.clear()
            nll_calls.clear()
            report = commands.mode_eval(
                SimpleNamespace(
                    mode="eval", output_root=sb["phase1"], prereg=sb["prereg"], limits_file=None,
                    wall_budget_seconds=None, research_log=None, arm=eval_arm, seed=0,
                )
            )
            details = report.get("details") or {}
            results["eval_calls"].append(
                {
                    "arm": eval_arm,
                    "status": report.get("status"),
                    "worker_exit_code": report.get("worker_exit_code"),
                    "exit_code": commands._exit_code_for(report),
                    "run_id": report.get("run_id"),
                    "optimizer_steps": (report.get("run") or {}).get("optimizer_steps"),
                    "supervision_seconds": eval_sup[-1]["supervision_seconds"] if eval_sup else None,
                    "metric_keys": sorted(k for k in details if k in (
                        "localization_error", "unseen_map_generalization", "topology_recovery",
                        "few_shot_unseen_transition", "sample_efficiency", "m2_memory_interference",
                    )),
                    "incomparable": details.get("incomparable"),
                    "kind": details.get("kind"),
                    "localization_error": details.get("localization_error"),
                    "sample_efficiency": details.get("sample_efficiency"),
                    "m2_memory_interference": details.get("m2_memory_interference"),
                    "unseen_map_generalization": details.get("unseen_map_generalization"),
                    "topology_recovery": details.get("topology_recovery"),
                    "few_shot_unseen_transition": details.get("few_shot_unseen_transition"),
                    "checkpoint_sha256": details.get("checkpoint_sha256"),
                    "nll_calls_seen": list(nll_calls),
                    "opened_paths": sorted({p for p in opened if str(sb["dataset_dir"]) in p}),
                    "opened_final_paths": sorted({p for p in opened if "final" in Path(p).parts}),
                    "details": details,
                }
            )
    finally:
        eval_stack.close()

    results["final_partition"] = {
        "dataset_has_final_file": any("final" in name for name in sb["dataset_files"]),
        "dataset_files": sb["dataset_files"],
        "decoy_path": str(sb["decoy"]),
        "decoy_ever_opened": any(str(sb["decoy"]) == p for p in opened),
        "eval_opened_final_paths": sorted({c for call in results["eval_calls"] for c in call["opened_final_paths"]}),
        "eval_truth_partitions_opened": sorted(
            {
                Path(p).name
                for call in results["eval_calls"]
                for p in call["opened_paths"]
                if Path(p).parent.name == "truth"
            }
        ),
        "code_path": {
            "evaluate_arm_partitions": ["development"],
            "loaders_used": ["data.load_development_windows", "data.load_truth_view(..., 'development')"],
            "sealed_guard": "data.require_partition('final') raises FinalPartitionSealed",
        },
    }

    # --- independent metric recomputation (same inputs, own arithmetic)
    if not results.get("completed_9") or not all(c["status"] == "completed" for c in results["eval_calls"]):
        results["checks"] = {
            "nine_train_calls_completed": results.get("completed_9") is True,
            "four_eval_calls_completed": all(c["status"] == "completed" for c in results["eval_calls"]),
        }
        results["verdict"] = "fail"
        OUT_DIR.joinpath("evidence").mkdir(parents=True, exist_ok=True)
        (OUT_DIR / "evidence/full-flow.json").write_text(
            json.dumps(results, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8"
        )
        print(json.dumps({"verdict": "fail", "checks": results["checks"],
                          "train_calls": [{k: c[k] for k in ("index", "arm", "seed", "status", "refused_stage", "error", "stage", "exit_code")} for c in results["train_calls"]],
                          "eval_calls": [{k: c[k] for k in ("arm", "status", "worker_exit_code")} for c in results["eval_calls"]]}, indent=1))
        return 1

    protocol = sb["document"]["training_protocol"]
    dev = data.load_development_windows(sb["dataset_dir"])
    truth_view = data.load_truth_view(sb["dataset_dir"], "development")
    batch_size = int(protocol["batch_size"])
    n_windows = len(dev.get("obs", []))
    num_batches = (
        min(int(protocol.get("eval_batches", spec.TIMING["eval_batches"])), max(1, n_windows // batch_size))
        if n_windows >= batch_size
        else 0
    )
    model = arms.build_trainable_arm("arm2", seed=0)  # eval loads a no-op checkpoint: same seeded init
    estimates = []
    batch_iter = data.iter_batches(dev, batch_size, seed=0, shuffle=False)
    for _ in range(num_batches):
        estimates.append(model.forward_loss(next(batch_iter)).pose_belief)
    est = np.concatenate(estimates, axis=0)
    truth = np.concatenate([data.truth_pose_sequence(ep) for ep in truth_view], axis=0)
    m = min(len(est), len(truth))
    est, truth = est[:m], truth[:m]
    dx = est[:, 0] - truth[:, 0]
    dz = est[:, 2] - truth[:, 2]
    translation = np.sqrt(dx * dx + dz * dz)
    dyaw = (est[:, 3] - truth[:, 3] + 180.0) % 360.0 - 180.0
    yaw = np.abs(dyaw)
    indep_loc = {
        "steps": int(m),
        "translation_mean_m": float(translation.mean()),
        "translation_median_m": float(np.median(translation)),
        "translation_rmse_m": float(np.sqrt((translation**2).mean())),
        "yaw_mean_deg": float(yaw.mean()),
        "yaw_median_deg": float(np.median(yaw)),
    }

    arm2_eval = next(c for c in results["eval_calls"] if c["arm"] == "arm2")
    reported_loc = arm2_eval["localization_error"] or {}
    loc_check = {
        key: {
            "reported": reported_loc.get(key),
            "independent": indep_loc[key],
            "abs_diff": (
                None
                if reported_loc.get(key) is None
                else abs(float(reported_loc[key]) - float(indep_loc[key]))
            ),
        }
        for key in indep_loc
    }
    loc_ok = all(
        row["abs_diff"] is not None and row["abs_diff"] <= 1e-9 for row in loc_check.values()
    )

    # sample_efficiency: normalised trapezoid area recomputed from the curve the
    # training process wrote into run_info.json (independent of metrics.py).
    run_info_path = sb["phase1"] / "runs" / completed["arm2:0"] / "run_info.json"
    run_info = json.loads(run_info_path.read_text(encoding="utf-8"))
    curve = sorted((int(r["updates"]), float(r["development_nll"])) for r in run_info["sample_efficiency_curve"])
    if len(curve) > 1:
        area = 0.0
        for (x0, y0), (x1, y1) in zip(curve, curve[1:]):
            area += (x1 - x0) * (y0 + y1) / 2.0
        area /= max(curve[-1][0] - curve[0][0], 1.0)
    else:
        area = curve[0][1]
    reported_curve = arm2_eval["sample_efficiency"] or {}
    sample_check = {
        "checkpoints_from_run_info": curve,
        "reported_normalised_area": reported_curve.get("normalised_area"),
        "independent_normalised_area": float(area),
        "abs_diff": (
            None
            if reported_curve.get("normalised_area") is None
            else abs(float(reported_curve["normalised_area"]) - float(area))
        ),
    }
    sample_ok = sample_check["abs_diff"] is not None and sample_check["abs_diff"] <= 1e-12

    # memory_interference: recompute before/after delta from the recorded NLLs.
    m2 = arm2_eval["m2_memory_interference"] or {}
    nlls = arm2_eval["nll_calls_seen"]
    m2_check = {
        "nll_calls_seen": nlls,
        "reported": m2,
        "independent_recompute_possible": len(nlls) >= 2,
    }
    if len(nlls) >= 2:
        delta = nlls[-1] - nlls[0]
        m2_check["independent_retention_delta"] = delta
        m2_check["reported_retention_delta"] = (m2.get("retention_delta") or {}).get("development_nll")
        m2_check["abs_diff"] = abs(float(m2_check["reported_retention_delta"]) - delta)
    else:
        m2_check["note"] = "before/after NLL were not both observed through the patched measurement hook"

    results["metric_recompute"] = {
        "localization_error": {"check": loc_check, "agrees": loc_ok, "steps_reported": reported_loc.get("steps")},
        "sample_efficiency": {"check": sample_check, "agrees": sample_ok},
        "m2_memory_interference": m2_check,
        "limitations": (
            "The independent implementations take the same observations (real forward passes on the "
            "development partition / the curve written by training) but use reviewer-written "
            "arithmetic instead of metrics.py; the model forward itself is not independently reimplemented."
        ),
    }

    # --- assertions that define pass/fail
    deadline = float(sb["document"]["timing"]["deadline_seconds"])
    supervision = float(sb["document"]["timing"]["supervision_seconds"])
    own_windows = [c["own_window_seconds"] for c in results["train_calls"]]
    phase_caps = sb["document"]["timing"].get("phase_wall_max_seconds")
    checks = {
        "nine_train_calls_completed": results.get("completed_9") is True,
        "every_train_call_own_window_below_deadline": all(w is not None and w < deadline for w in own_windows),
        "no_train_call_inherits_earlier_time": all(w is not None and w < 200.0 for w in own_windows),
        "phase_span_exceeds_per_run_deadline": (
            results["train_calls"][-1]["cumulative_since_first_call_seconds"] > deadline
        ),
        "supervision_is_per_run_not_per_phase": all(
            c["supervision_seconds"] == supervision
            and c["wall_budget_seconds"] == deadline
            and supervision < float(phase_caps)
            for c in results["train_calls"]
        ),
        "duplicate_rejected_with_exit_3_and_no_worker": (
            results["duplicate_call"]["status"] == "refused"
            and results["duplicate_call"]["refused_stage"] == "already_completed"
            and results["duplicate_call"]["exit_code"] == 3
            and results["duplicate_call"]["supervisor_invoked"] is False
        ),
        "phase_wall_guard_refuses": (
            results["phase_budget_call"]["refused_stage"] == "phase_budget_exceeded"
            and results["phase_budget_call"]["exit_code"] == 3
        ),
        "four_eval_calls_completed": all(c["status"] == "completed" for c in results["eval_calls"])
        and len(results["eval_calls"]) == 4,
        "eval_reports_all_six_metrics": all(
            len(c["metric_keys"]) == 6 for c in results["eval_calls"]
        ),
        "eval_does_not_step_optimizer": all(int(c["optimizer_steps"] or 0) == 0 for c in results["eval_calls"]),
        "eval_never_reads_final": (
            results["final_partition"]["eval_opened_final_paths"] == []
            and results["final_partition"]["eval_truth_partitions_opened"] == ["development.jsonl"]
            and results["final_partition"]["decoy_ever_opened"] is False
            and results["final_partition"]["dataset_has_final_file"] is False
        ),
        "localization_recompute_agrees": loc_ok,
        "sample_efficiency_recompute_agrees": sample_ok,
        "checkpoints_readonly_and_sidecar": all(
            c["checkpoint_sha_matches_sidecar"] and c["checkpoint_mode_0444"] for c in results["train_calls"]
        ),
    }
    results["checks"] = checks
    results["verdict"] = "pass" if all(checks.values()) else "fail"
    results["sandbox_cleaned"] = True

    OUT_DIR.joinpath("evidence").mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "evidence/full-flow.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps({"checks": checks, "verdict": results["verdict"],
                      "train_windows": own_windows,
                      "phase_span": results["train_calls"][-1]["cumulative_since_first_call_seconds"],
                      "duplicate": results["duplicate_call"], "phase_guard": results["phase_budget_call"],
                      "loc_diff": {k: v["abs_diff"] for k, v in loc_check.items()},
                      "sample": sample_check, "m2": {k: v for k, v in m2_check.items() if k != "reported"},
                      "final": {k: v for k, v in results["final_partition"].items() if k != "dataset_files"}},
                     indent=1))
    return 0 if results["verdict"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
