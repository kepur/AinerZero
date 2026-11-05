"""External linear-probe orchestration inside the supervised frozen worker."""

from __future__ import annotations

import hashlib
import time

import numpy as np

from ainerzero.learning.recall_probe import (
    DELAYS,
    FEATURE_KINDS,
    collect_probe_features,
    feature_summary,
    fit_probe_rows,
    make_probe_rows,
    score_probe_rows,
)
from ainerzero.runtime.checkpoints import load_checkpoint, save_checkpoint


def recall_plan() -> dict:
    return {
        "architecture": "pilot_shared_symbol_v1",
        "parameter_count": 393232,
        "student_optimizer_steps": 0,
        "new_environment_steps": 0,
        "delays": list(DELAYS),
        "feature_kinds": list(FEATURE_KINDS),
        "feature_width": 272,
        "feature_reduction": "mean_of_8_posterior_h_z_particles_after_current_observation",
        "current_only": "masked_frozen_byte_embeddings_128_plus_mask8_cursor8_padded_with128_zeros",
        "capacity_caveat": "same_affine_dimensions_different_effective_rank_report_train_rank_and_constant_columns",
        "ridge": 0.01,
        "ridge_objective": "mean_samples_squared_error_per_output_plus_0.01_weight_norm; intercept_unpenalized",
        "standardization": "train_rows_only; std_at_most_1e-6_replaced_with1",
        "train_minimum_tick": 4,
        "development_minimum_tick": 32,
        "query_stride": 1,
        "train_feature_seed": 1901,
        "development_feature_seed": 2901,
        "probe_fits": 9,
        "linear_system_solves": 72,
        "external_probe_coefficients_each": 34944,
        "external_probe_coefficients_total": 314496,
        "fit_weighting": "uniform_visible_past_targets_no_change_reweighting",
        "fit_order": "all_train_only_fits_saved_before_development_feature_extraction",
        "label": "public_observation_at_t_minus_delay; changed_means_past_differs_from_current",
        "references": [
            "copy_current_with_1percent_smoothing",
            "target_embedding_codec_oracle_not_model_input",
        ],
        "resource_seconds": {
            "initialization": 15,
            "train_features": 180,
            "fit": 90,
            "train_score": 60,
            "probe_save": 15,
            "development_features": 90,
            "development_score": 45,
            "reconstruction": 45,
            "verification": 5,
        },
        "supervised_deadline_seconds": 620,
        "selection": "fixed_single_ridge_no_dev_tuning_no_student_update_or_promotion",
    }


def run_recall_probes(
    model, episodes, tensors, *, plan, source, directory, stage, reserve, guard, progress
):
    """All state inference, fits and readouts stay in prepaid bounded stages."""
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
        "stage_elapsed_seconds": {},
    }

    def begin(name):
        stage(name)
        return time.perf_counter()

    def finish(name, tick):
        guard(force=True)
        result["stage_elapsed_seconds"][name] = time.perf_counter() - tick
        progress(result)

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
        delay: make_probe_rows(train, delay=delay, minimum_tick=plan["train_minimum_tick"])
        for delay in DELAYS
    }
    finish("train_features", tick)

    tick = begin("fit")
    # All delays use the same t>=4 training features, so their feature statistics match.
    result["training_feature_statistics"] = {
        kind: feature_summary(train_rows[1]["features"][kind]) for kind in FEATURE_KINDS
    }
    probes = {}
    for delay in DELAYS:
        guard()
        probes[delay] = fit_probe_rows(train_rows[delay], embedding, ridge=plan["ridge"])
        result["completed_probe_fits"] += len(FEATURE_KINDS)
        result["completed_linear_systems"] += 8 * len(FEATURE_KINDS)
        guard(force=True)
        progress(result)
    finish("fit", tick)

    tick = begin("train_score")
    for delay in DELAYS:
        guard()
        result["training"][str(delay)] = score_probe_rows(
            probes[delay], train_rows[delay], embedding, weight, bias
        )
        guard(force=True)
    finish("train_score", tick)

    tick = begin("probe_save")
    saved_arrays = {
        f"probe.d{delay}.{kind}.{key}": value
        for delay, kinds in probes.items()
        for kind, fitted in kinds.items()
        for key, value in fitted.items()
    }
    checkpoint = save_checkpoint(
        directory / "probes",
        "ridge-probes",
        saved_arrays,
        {
            "architecture": "external_recall_probe_v1",
            "phase": "diagnostic_probe",
            "student_source": source,
            "plan": plan,
            "completed_probe_fits": result["completed_probe_fits"],
            "student_optimizer_steps": 0,
            "fit_partition": "train",
            "not_a_student_checkpoint": True,
        },
    )
    restored, _ = load_checkpoint(checkpoint)
    if set(restored) != set(saved_arrays) or not all(
        np.array_equal(restored[k], v) for k, v in saved_arrays.items()
    ):
        raise RuntimeError("external probe checkpoint roundtrip mismatch")
    # Development uses the saved-and-restored coefficients, not a transient fit.
    probes = {
        delay: {
            kind: {key: restored[f"probe.d{delay}.{kind}.{key}"] for key in fitted}
            for kind, fitted in kinds.items()
        }
        for delay, kinds in probes.items()
    }
    result.update(
        probe_checkpoint=str(checkpoint.resolve()),
        probe_checkpoint_verified=True,
        probes_frozen_before_development=True,
        probe_manifest_sha256=hashlib.sha256(
            (checkpoint / "manifest.json").read_bytes()
        ).hexdigest(),
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
    for delay in DELAYS:
        guard()
        rows = make_probe_rows(dev, delay=delay, minimum_tick=plan["development_minimum_tick"])
        result["development"][str(delay)] = score_probe_rows(
            probes[delay], rows, embedding, weight, bias
        )
        guard(force=True)
    result["probe_arrays_unchanged_during_development"] = all(
        np.array_equal(probes[delay][kind][key], saved_arrays[f"probe.d{delay}.{kind}.{key}"])
        for delay, kinds in probes.items()
        for kind, fitted in kinds.items()
        for key in fitted
    )
    if not result["probe_arrays_unchanged_during_development"]:
        raise RuntimeError("development scoring changed frozen probe coefficients")
    finish("development_score", tick)
    return result
