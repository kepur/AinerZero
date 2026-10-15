"""Fixed-current residual readouts under the existing frozen-worker budgets."""

from __future__ import annotations

import hashlib
import time

import numpy as np

from ainerzero.learning.recall_probe import (
    DELAYS,
    FEATURE_KINDS,
    collect_probe_features,
    feature_summary,
)
from ainerzero.learning.residual_probe import (
    fit_residual_rows,
    fit_zero_delay_dense,
    make_residual_rows,
    score_residual_rows,
    score_zero_delay_controls,
)
from ainerzero.runtime.checkpoints import load_checkpoint, save_checkpoint
from ainerzero.runtime.recall_diagnostics import recall_plan


def residual_plan() -> dict:
    plan = recall_plan()
    plan.update(
        protocol="m2g_current_anchored_residual_v1",
        prediction="masked_current_embedding_plus_predicted_residual_for_every_sample",
        fit_target="past_embedding_minus_masked_current_embedding",
        probe_fits=10,
        linear_system_solves=80,
        external_probe_coefficients_total=349440,
        zero_delay_dense_control="one_original_current_only_absolute_embedding_readout",
        zero_delay_fixed_control="zero_residual_pipeline_check_without_fit_not_memory_evidence",
        checkpoint_architecture="external_residual_recall_probe_v1",
        diagnostic_scope="reused_development_worlds_exploratory_not_fresh_acceptance",
        references=[
            "fixed_current_codec",
            "copy_current_with_1percent_smoothing",
            "target_embedding_codec_oracle_not_model_input",
        ],
    )
    return plan


def run_residual_probes(
    model, episodes, tensors, *, plan, source, directory, stage, reserve, guard, progress
):
    """Fit ten train-only readouts; restore them before any development work."""
    embedding = np.asarray(tensors["model.byte_embedding.weight"], dtype=np.float64)
    weight = np.asarray(tensors["model.symbol_readout.weight"], dtype=np.float64)
    bias = np.asarray(tensors["model.symbol_readout.bias"], dtype=np.float64)
    result = {
        "completed_probe_fits": 0,
        "completed_linear_systems": 0,
        "student_optimizer_steps": 0,
        "logical_model_units": 0,
        "training": {},
        "development": {},
        "zero_delay": {},
        "stage_elapsed_seconds": {},
    }

    def begin(name):
        stage(name)
        return time.perf_counter()

    def finish(name, tick):
        guard(force=True)
        result["stage_elapsed_seconds"][name] = time.perf_counter() - tick
        progress(result)

    def score_zero(probe, rows, partition):
        score = score_zero_delay_controls(probe, rows, embedding, weight, bias)
        result["zero_delay"][partition] = score
        progress(result)
        checks = score.get("pipeline_checks", {})
        required = {"zero_residual_preserves_embedding", "zero_residual_preserves_decoding"}
        if not required.issubset(checks) or not all(value is True for value in checks.values()):
            raise RuntimeError("zero-delay fixed-current pipeline check failed")

    tick = begin("train_features")
    train = collect_probe_features(
        model,
        episodes["train"],
        embedding,
        partition="train",
        seed=plan["train_feature_seed"],
        before_work=reserve,
    )
    result["logical_model_units"] += train["logical_model_units"]
    train_rows = {
        d: make_residual_rows(train, delay=d, minimum_tick=plan["train_minimum_tick"])
        for d in (0, *DELAYS)
    }
    finish("train_features", tick)

    tick = begin("fit")
    result["training_feature_statistics"] = {
        kind: feature_summary(train_rows[0]["features"][kind]) for kind in FEATURE_KINDS
    }
    dense = fit_zero_delay_dense(train_rows[0], embedding, ridge=plan["ridge"])
    result["completed_probe_fits"] = 1
    result["completed_linear_systems"] = 8
    guard(force=True)
    progress(result)
    probes = {}
    for delay in DELAYS:
        guard()
        probes[delay] = fit_residual_rows(train_rows[delay], embedding, ridge=plan["ridge"])
        result["completed_probe_fits"] += 3
        result["completed_linear_systems"] += 24
        guard(force=True)
        progress(result)
    finish("fit", tick)

    tick = begin("train_score")
    score_zero(dense, train_rows[0], "training")
    for delay in DELAYS:
        guard()
        result["training"][str(delay)] = score_residual_rows(
            probes[delay], train_rows[delay], embedding, weight, bias
        )
        guard(force=True)
    finish("train_score", tick)

    tick = begin("probe_save")
    saved = {
        f"residual.d{d}.{kind}.{key}": value
        for d, kinds in probes.items()
        for kind, probe in kinds.items()
        for key, value in probe.items()
    }
    saved.update({f"dense.d0.current_only.{key}": value for key, value in dense.items()})
    path = save_checkpoint(
        directory / "probes",
        "residual-probes",
        saved,
        {
            "architecture": plan["checkpoint_architecture"],
            "phase": "diagnostic_probe",
            "student_source": source,
            "plan": plan,
            "completed_probe_fits": result["completed_probe_fits"],
            "student_optimizer_steps": 0,
            "fit_partition": "train",
            "not_a_student_checkpoint": True,
        },
    )
    restored, _ = load_checkpoint(path)
    if set(restored) != set(saved) or not all(
        np.array_equal(restored[k], v) for k, v in saved.items()
    ):
        raise RuntimeError("external residual probe checkpoint roundtrip mismatch")
    dense = {k: restored[f"dense.d0.current_only.{k}"] for k in dense}
    probes = {
        d: {
            kind: {k: restored[f"residual.d{d}.{kind}.{k}"] for k in probe}
            for kind, probe in kinds.items()
        }
        for d, kinds in probes.items()
    }
    result.update(
        probe_checkpoint=str(path.resolve()),
        probe_checkpoint_verified=True,
        probes_frozen_before_development=True,
        probe_manifest_sha256=hashlib.sha256((path / "manifest.json").read_bytes()).hexdigest(),
    )
    finish("probe_save", tick)

    tick = begin("development_features")
    dev = collect_probe_features(
        model,
        episodes["development"],
        embedding,
        partition="development",
        seed=plan["development_feature_seed"],
        before_work=reserve,
    )
    result["logical_model_units"] += dev["logical_model_units"]
    finish("development_features", tick)

    tick = begin("development_score")
    zero_rows = make_residual_rows(dev, delay=0, minimum_tick=plan["development_minimum_tick"])
    score_zero(dense, zero_rows, "development")
    for delay in DELAYS:
        guard()
        rows = make_residual_rows(dev, delay=delay, minimum_tick=plan["development_minimum_tick"])
        result["development"][str(delay)] = score_residual_rows(
            probes[delay], rows, embedding, weight, bias
        )
        guard(force=True)
    after_scoring = {
        f"residual.d{d}.{kind}.{key}": value
        for d, kinds in probes.items()
        for kind, probe in kinds.items()
        for key, value in probe.items()
    }
    after_scoring.update({f"dense.d0.current_only.{key}": value for key, value in dense.items()})
    result["probe_arrays_unchanged_during_development"] = set(after_scoring) == set(saved) and all(
        np.array_equal(after_scoring[k], v) for k, v in saved.items()
    )
    if not result["probe_arrays_unchanged_during_development"]:
        raise RuntimeError("development scoring changed frozen residual probe coefficients")
    finish("development_score", tick)
    return result
