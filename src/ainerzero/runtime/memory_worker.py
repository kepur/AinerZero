"""One bounded GRU-only previous-observation retention experiment."""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from pathlib import Path
from uuid import uuid4

import numpy as np
import psutil

from ainerzero.core.experience import TrainingPolicy
from ainerzero.core.pilot import load_pilot_config
from ainerzero.data.augmentation import permute_symbols
from ainerzero.data.pilot_dataset import load_pilot_dataset
from ainerzero.data.sequences import SequenceSampler
from ainerzero.learning.baselines import NoActionBaseline
from ainerzero.learning.memory_codec import audit_bounded_codec
from ainerzero.runtime.c0_collection import RANDOM_ACTOR
from ainerzero.runtime.checkpoints import atomic_write_json, load_checkpoint, save_checkpoint
from ainerzero.runtime.history_worker import validate_history_source
from ainerzero.runtime.lifecycle import TERMINAL_STATES, RunStore


def memory_plan():
    return {
        "protocol": "m2h_one_step_previous_observation_v1",
        "architecture": "pilot_shared_symbol_v1",
        "parameter_count": 393232,
        "trainable_modules": ["gru"],
        "trainable_parameter_count": 222208,
        "readout": "reuse_frozen_symbol_head_on_h_tail_8_by_16_after_next_observation",
        "target": "previous_visible_public_observation_uniform_symbol_cross_entropy",
        "updates": 100,
        "learning_rate": 0.001,
        "batch_size": 16,
        "micro_batch_size": 4,
        "burn_in": 4,
        "sequence_steps": 16,
        "transitions_per_window": 20,
        "training_model_units_per_update": 336,
        "augmentation": "per_window_consistent_byte_permutation_training_only",
        "seeds": {
            "windows": 2101,
            "augmentation": 2307,
            "latent": 2203,
            "memory_train": 3901,
            "memory_development": 4901,
        },
        "evaluation": {"support_ticks": 32, "particles": 8, "query_stride": 1},
        "screen": {
            "minimum_changed_count": 30,
            "overall_accuracy_min": 0.95,
            "changed_accuracy_min": 0.8,
            "per_world_changed_accuracy_min": 0.5,
        },
        "source_optimizer": "reset_AdamW_GRU_only",
        "automatic_promotion": False,
        "new_environment_steps": 0,
        "scope": "explicit_supervised_tail_slots_reused_development_not_autonomous_memory_discovery",
        "resource_seconds": {
            "initialization": 15,
            "compatibility": 15,
            "before_memory_train": 90,
            "before_memory_development": 45,
            "before_action": 60,
            "before_reconstruction": 45,
            "training_update": 5,
            "after_memory_train": 90,
            "after_memory_development": 45,
            "after_action": 60,
            "after_reconstruction": 45,
            "checkpoint": 30,
            "verification": 10,
        },
        "total_reserved_seconds_if_complete": 1050,
        "supervised_deadline_seconds": 1500,
        "selection": "one_fixed_run_no_dev_tuning_no_automatic_retry_or_promotion",
    }


def micro_memory_plan():
    """M2j is a local fit diagnostic, separate from M2h's continuous task."""
    plan = memory_plan()
    plan.update(
        protocol="m2j_fixed_single_edge_tail_fit_v1",
        updates=200,
        trainable_parameter_count=111104,
        optimizer_tensor_parameter_count=222208,
        frozen_parameter_count=282128,
        trainable_scope="GRU_tail_output_rows_only_mask_gradients_project_front_after_AdamW",
        burn_in=0,
        sequence_steps=1,
        transitions_per_window=1,
        training_model_units_per_update=32,
        augmentation="none_fixed_batch_repeated",
        seeds={
            "latent": 2203,
            "local_new_noise": 2603,
            "memory_train": 3901,
            "memory_development": 4901,
        },
        local_checks=[0, 50, 100, 150, 200],
        local_check_model_units=48,
        local_screen={
            "overall_accuracy_min": 0.95,
            "changed_accuracy_min": 0.8,
            "minimum_changed_count": 16,
        },
        sample_selection="exactly_16_train_worlds_sorted_episode_then_world_first_visible_change",
        local_evaluation="one_particle_same_four_micro_batches_same_inputs_two_fixed_noise_seeds",
        source_optimizer="reset_AdamW_GRU_masked_and_projected_front",
        scope="fixed_training_examples_single_feedback_edge_fit_not_general_memory",
        total_reserved_seconds_if_complete=1000,
        expected_total_model_units=92128,
    )
    plan["resource_seconds"]["training_update"] = 2
    plan["resource_seconds"]["local_check"] = 5
    return plan


def diverse_memory_plan():
    """M2l expands the public input distribution at the same update budget."""
    plan = micro_memory_plan()
    plan.update(
        protocol="m2l_diverse_single_edge_tail_fit_v1",
        augmentation="none_fixed_public_pool_cyclic_schedule",
        sample_selection="16_train_worlds_4_changed_12_unchanged_unique_previous_per_world",
        training_pool_size=256,
        training_schedule="world_major_pool_rank_(zero_based_update+world_index)_mod_16",
        training_distribution="four_changed_and_twelve_unchanged_edges_per_batch",
        comparison_caveat="input_diversity_and_changed_edge_mix_both_change_from_M2j",
        scope="diverse_public_training_edges_one_step_retention_not_independent_acceptance",
        paired_evaluation={"seed": 7103, "particles": 8},
        expected_total_model_units=174208,
        total_reserved_seconds_if_complete=1300,
    )
    plan["resource_seconds"]["after_paired"] = 300
    return plan


RELABEL_LEARNING_RATES = {
    0.001: "m2m_consistent_relabel_single_edge_tail_fit_v1",
    0.003: "m2m_c_consistent_relabel_lr0003_single_edge_tail_fit_v1",
}


def relabel_memory_plan(learning_rate=0.001):
    """M2m adds only a per-sample consistent byte relabeling to the M2l protocol.

    M2m-c is the single registered learning-rate variant (0.003); every other
    field is identical to M2m stage B.  No other learning rate is accepted.
    """
    if type(learning_rate) is not float or learning_rate not in RELABEL_LEARNING_RATES:
        raise ValueError("relabel learning rate must be one registered value")
    plan = diverse_memory_plan()
    plan.update(
        protocol="m2m_consistent_relabel_single_edge_tail_fit_v1",
        augmentation="per_sample_consistent_byte_bijection_both_frames_all_visible_cells_permute_symbols",
        augmentation_scope="training_batches_only_local_checks_and_evaluations_unpermuted",
        training_permutations=3200,
        comparison_caveat="single_factor_vs_M2l_relabel_only_same_start_pool_schedule_seeds",
        scope="relabeled_public_training_edges_one_step_retention_not_independent_acceptance",
        relabel_evaluation={
            "seed": 9103,
            "rows": 256,
            "branch": "zero_context_tail",
            "particles": 8,
            "keys": "paired_query_keys_of_each_pool_row_seed_7103",
            "model_units": 4096,
            "disjoint_from_training_permutations": True,
        },
        m2l_comparison={
            "candidate": "frozen_completed_m2l_candidate_no_updates",
            "paired_with_cells_model_units": 82080,
            "relabel_pool_model_units": 4096,
            "paired_must_reproduce_m2l_report_exactly": True,
        },
        stratification={
            "coverage_reference": "visible_previous_frame_targets_of_m2l_256_pool_rows_unpermuted",
            "flags": ["same_position_seen"],
            "frame_novel_buckets": [[0, 0], [1, 2], [3, 5], [6, 8]],
            "branches": ["zero_context_tail", "history_tail"],
            "groups": [
                "all",
                "selected_train",
                "unselected_train_previous_in_pool",
                "unselected_train_previous_not_in_pool",
                "development",
            ],
            "model_units": 0,
        },
        transfer_levels={
            "not_transferred_below": 0.10,
            "transferred_min": 0.80,
            "transferred_changed_min": 0.50,
        },
        regression={
            "reconstruction": "gate_passed_and_all_544_correct",
            "action_accuracy": "not_below_before",
            "action_nll_increase_max": {"1": 0.05, "4": 0.15},
        },
        expected_total_model_units=174208 + 4096 + 82080 + 4096,
        total_reserved_seconds_if_complete=1670,
        supervised_deadline_seconds=1720,
    )
    plan["seeds"].update(augmentation=2307, relabel_evaluation=9103)
    plan["resource_seconds"].update(
        m2l_paired_cells=300, m2l_relabel_pool=30, after_relabel_pool=30, verification=20
    )
    if learning_rate != 0.001:
        plan.update(
            protocol=RELABEL_LEARNING_RATES[learning_rate],
            learning_rate=learning_rate,
            comparison_caveat=(
                "single_factor_vs_M2m_stage_B_learning_rate_only_same_start_pool_schedule_"
                "permutations_seeds_gates"
            ),
            stage_b_comparison="cpu_only_from_saved_stage_b_cells_no_model_calls",
        )
    return plan


def action_preservation_memory_plan():
    """M2m-d: M2m-c lr 0.003 entry plus the frozen keep branch; M2l baselines reused."""
    from ainerzero.learning import action_preservation as ap
    from ainerzero.learning import action_preservation_closure as apc

    plan = relabel_memory_plan(0.003)
    seconds = plan["resource_seconds"]
    del seconds["m2l_paired_cells"], seconds["m2l_relabel_pool"]
    seconds.update(training_update=3, teacher_cache=60, cache_protocol_checks=10)
    embedded = ap.action_preservation_plan()
    if ap.verify_frozen_plan(embedded) != ap.FROZEN_PLAN_SHA256:
        raise RuntimeError("embedded M2m-d plan differs from registration")
    plan.update(
        protocol=ap.PROTOCOL,
        expected_total_model_units=ap.TOTAL_UNITS,
        total_reserved_seconds_if_complete=ap.PREPAID_SECONDS,
        supervised_deadline_seconds=ap.WORK_DEADLINE_SECONDS,
        supervisor_deadline_seconds=ap.SUPERVISOR_DEADLINE_SECONDS,
        student_model_units_per_update="registered_windows_table_137_to_144",
        first_update_keep_loss_max=apc.FIRST_UPDATE_KEEP_LOSS_MAX,
        keep_lambda=ap.LAMBDA_KEEP,
        m2l_baselines="reused_from_m2mc_report_cpu_closure_no_m2l_model_calls",
        action_preservation=embedded,
    )
    counts = {"training_update": plan["updates"], "local_check": 2 * len(plan["local_checks"])}
    total = sum(value * counts.get(name, 1) for name, value in seconds.items())
    if total != ap.PREPAID_SECONDS:
        raise RuntimeError(f"M2m-d stage seconds total {total}, expected {ap.PREPAID_SECONDS}")
    return plan


def action_preservation_lambda10_memory_plan():
    """C07: the registered M2m-d entry with keep lambda 1.0 -> 10.0 only.

    Units, seconds, deadlines, data, seeds, windows, gates and the frozen base
    plan are unchanged; the modified condition plan carries its own SHA.
    """
    from ainerzero.learning import action_preservation as ap
    from ainerzero.learning import action_preservation_closure as apc

    plan = action_preservation_memory_plan()
    condition = apc.c07_condition_plan()
    if condition["base_plan_sha256"] != ap.FROZEN_PLAN_SHA256:
        raise RuntimeError("C07 condition lost the frozen base plan reference")
    if plan["expected_total_model_units"] != ap.TOTAL_UNITS or plan["expected_total_model_units"] != 208_546:
        raise RuntimeError("C07 must keep the registered unit budget")
    plan.update(
        protocol=apc.C07_PROTOCOL,
        keep_lambda=apc.LAMBDA_KEEP_V2,
        single_factor="keep_lambda_only_base_plan_otherwise_identical",
        action_preservation_condition=condition,
    )
    if plan["keep_lambda"] == ap.LAMBDA_KEEP:
        raise RuntimeError("C07 must actually change the keep lambda")
    return plan


def action_preservation_distill_memory_plan():
    """D: M2m-d memory branch with the teacher KL folded into the same batch/forward."""
    from ainerzero.learning import action_preservation as ap
    from ainerzero.learning import action_preservation_closure as apc

    plan = relabel_memory_plan(0.003)
    seconds = plan["resource_seconds"]
    del seconds["m2l_paired_cells"], seconds["m2l_relabel_pool"]
    seconds.update(training_update=3)  # no separate teacher cache / cache-check stages
    condition = apc.d_condition_plan()
    if condition["base_plan_sha256"] != ap.FROZEN_PLAN_SHA256:
        raise RuntimeError("D condition lost the frozen base plan reference")
    plan.update(
        protocol=apc.D_PROTOCOL,
        expected_total_model_units=184_704,
        total_reserved_seconds_if_complete=1_540,
        supervised_deadline_seconds=1_590,
        supervisor_deadline_seconds=1_640,
        training_model_units_per_update=64,  # 32 student + 32 online teacher
        first_update_keep_loss_max=apc.FIRST_UPDATE_KEEP_LOSS_MAX,
        keep_lambda=ap.LAMBDA_KEEP,
        distill="in_batch_same_forward_relabelled_teacher",
        student_model_units_per_update="none_no_separate_keep_branch",
        conditional_total_model_units=condition["units"]["total"],
        action_preservation=ap.action_preservation_plan(),
        action_preservation_condition=condition,
    )
    plan.pop("m2l_baselines", None)
    if ap.verify_frozen_plan(plan["action_preservation"]) != ap.FROZEN_PLAN_SHA256:
        raise RuntimeError("D must carry the unmodified frozen base plan")
    if plan["expected_total_model_units"] != condition["units"]["total"] != 184_704:
        raise RuntimeError("D unit budget differs from its condition plan")
    counts = {"training_update": plan["updates"], "local_check": 2 * len(plan["local_checks"])}
    total = sum(value * counts.get(name, 1) for name, value in seconds.items())
    if total != 1_540:
        raise RuntimeError(f"D stage seconds total {total}, expected 1540")
    if "teacher_cache" in seconds or "cache_protocol_checks" in seconds:
        raise RuntimeError("D must not reserve a separate teacher cache stage")
    return plan


def action_preservation_history_memory_plan():
    """M2n: D's in-batch teacher distillation over multi-step real-history windows."""
    from ainerzero.learning import action_preservation as ap
    from ainerzero.learning import action_preservation_closure as apc

    plan = relabel_memory_plan(0.003)
    seconds = plan["resource_seconds"]
    del seconds["m2l_paired_cells"], seconds["m2l_relabel_pool"]
    seconds.update(training_update=4)  # 4 seconds per 416-unit history update
    condition = apc.m2n_condition_plan()
    if condition["base_plan_sha256"] != ap.FROZEN_PLAN_SHA256:
        raise RuntimeError("M2n condition lost the frozen base plan reference")
    seeds = dict(plan["seeds"])
    seeds["windows"] = 2101  # registered M2h window seed (review finding F1)
    plan.update(
        protocol=apc.M2N_PROTOCOL,
        expected_total_model_units=255_104,
        total_reserved_seconds_if_complete=1_740,
        supervised_deadline_seconds=1_760,
        supervisor_deadline_seconds=1_790,
        training_model_units_per_update=apc.M2N_UNITS_PER_UPDATE,  # 208 + 208 (F2)
        transitions_per_window=apc.M2N_TRANSITIONS,
        burn_in=4,
        sequence_steps=apc.M2N_LOSS_STEPS,
        seeds=seeds,
        first_update_keep_loss_max=apc.FIRST_UPDATE_KEEP_LOSS_MAX,
        keep_lambda=ap.LAMBDA_KEEP,
        distill="in_batch_same_forward_relabelled_teacher",
        memory_windows="sampler_history_windows_burn_in_4_sequence_steps_8",
        action_preservation=ap.action_preservation_plan(),
        action_preservation_condition=condition,
    )
    plan.pop("m2l_baselines", None)
    if ap.verify_frozen_plan(plan["action_preservation"]) != ap.FROZEN_PLAN_SHA256:
        raise RuntimeError("M2n must carry the unmodified frozen base plan")
    frames = plan["burn_in"] + plan["sequence_steps"] + 1
    if plan["transitions_per_window"] != plan["burn_in"] + plan["sequence_steps"]:
        raise RuntimeError("M2n window length must equal burn_in + sequence_steps")
    if plan["training_model_units_per_update"] != 2 * plan["batch_size"] * frames:
        raise RuntimeError("M2n per-update units must cover student and teacher frames")
    expected_units = 171_904 + 200 * plan["training_model_units_per_update"]
    if plan["expected_total_model_units"] != expected_units != 255_104:
        raise RuntimeError(f"M2n unit budget {plan['expected_total_model_units']} != {expected_units}")
    if "windows" not in plan["seeds"]:
        raise RuntimeError("M2n needs the registered window seed")
    counts = {"training_update": plan["updates"], "local_check": 2 * len(plan["local_checks"])}
    total = sum(value * counts.get(name, 1) for name, value in seconds.items())
    if total != 1_740:
        raise RuntimeError(f"M2n stage seconds total {total}, expected 1740")
    if "teacher_cache" in seconds or "cache_protocol_checks" in seconds:
        raise RuntimeError("M2n must not reserve a separate teacher cache stage")
    return plan


def action_preservation_mixed_memory_plan():
    """M2n-M: 12 registered single-edge rows plus 4 history windows, same teacher KL."""
    from ainerzero.learning import action_preservation as ap
    from ainerzero.learning import action_preservation_closure as apc

    plan = relabel_memory_plan(0.003)
    seconds = plan["resource_seconds"]
    del seconds["m2l_paired_cells"], seconds["m2l_relabel_pool"]
    seconds.update(training_update=3)
    # Operational amendment (registered 2026-10-13): the evaluation stages get +67%
    # headroom on the two memory partitions and +20% on the other six, because this
    # machine runs a persistent Docker VM plus several Metal-using apps whose
    # contention is invisible to load averages. Two bounded attempts died on the
    # 90 s before_memory_train window at ~96 s while the machine looked idle by load.
    # The prepaid total stays inside the single-run limit (1,740 < 1,760 < 1,780).
    seconds.update(before_memory_train=150, after_memory_train=150,
                   before_memory_development=65, after_memory_development=65,
                   before_action=70, after_action=70,
                   before_reconstruction=55, after_reconstruction=55)
    seeds = dict(plan["seeds"])
    seeds["windows"] = 2101  # registered M2h window seed for the history quarter
    seeds["mixed_history_augmentation"] = 2407  # own stream; keeps the manifest stream intact
    condition = apc.mixed_condition_plan()
    plan.update(
        protocol=apc.MIXED_PROTOCOL,
        expected_total_model_units=202_304,
        total_reserved_seconds_if_complete=1_740,
        supervised_deadline_seconds=1_760,
        supervisor_deadline_seconds=1_780,
        training_model_units_per_update=apc.MIXED_UNITS_PER_UPDATE,
        single_edge_rows=apc.MIXED_SINGLE_ROWS,
        history_rows=apc.MIXED_HISTORY_ROWS,
        history_burn_in=apc.MIXED_HISTORY_BURN_IN,
        history_sequence_steps=apc.MIXED_HISTORY_LOSS_STEPS,
        sampler_geometry={"burn_in": apc.MIXED_HISTORY_BURN_IN,
                          "sequence_steps": apc.MIXED_HISTORY_LOSS_STEPS},
        transitions_per_window=1,  # the single-edge half keeps the strict invariant
        first_update_keep_loss_max=apc.FIRST_UPDATE_KEEP_LOSS_MAX,
        keep_lambda=ap.LAMBDA_KEEP,
        distill="in_batch_same_forward_teacher_on_each_half",
        memory_windows="mixed_12_single_edge_rows_plus_4_sampler_history_windows",
        seeds=seeds,
        action_preservation=ap.action_preservation_plan(),
        action_preservation_condition=condition,
    )
    plan.pop("m2l_baselines", None)
    if ap.verify_frozen_plan(plan["action_preservation"]) != ap.FROZEN_PLAN_SHA256:
        raise RuntimeError("mixed condition must carry the unmodified frozen base plan")
    frames = plan["history_burn_in"] + plan["history_sequence_steps"] + 1
    student = plan["single_edge_rows"] * 2 + plan["history_rows"] * frames
    expected = 2 * student
    if plan["training_model_units_per_update"] != expected != 152:
        raise RuntimeError("mixed per-update units must cover both halves and the teacher")
    total_units = 171_904 + 200 * plan["training_model_units_per_update"]
    if plan["expected_total_model_units"] != total_units != 202_304:
        raise RuntimeError(f"mixed unit budget {plan['expected_total_model_units']} != {total_units}")
    if plan["action_preservation_condition"]["units"]["total"] != total_units:
        raise RuntimeError("mixed condition units must match the plan budget")
    counts = {"training_update": plan["updates"], "local_check": 2 * len(plan["local_checks"])}
    total_seconds = sum(value * counts.get(name, 1) for name, value in seconds.items())
    if total_seconds != 1_740:
        raise RuntimeError(f"mixed stage seconds total {total_seconds}, expected 1740")
    if not plan["total_reserved_seconds_if_complete"] < plan["supervised_deadline_seconds"] \
            < plan["supervisor_deadline_seconds"] <= ap.SINGLE_RUN_LIMIT_SECONDS:
        raise RuntimeError("mixed deadlines must stay inside the single-run limit")
    if "teacher_cache" in seconds or "cache_protocol_checks" in seconds:
        raise RuntimeError("mixed condition must not reserve a separate teacher cache stage")
    if "windows" not in plan["seeds"]:
        raise RuntimeError("mixed condition needs the registered window seed")
    geometry = plan["sampler_geometry"]
    if (geometry["burn_in"], geometry["sequence_steps"]) != (plan["history_burn_in"],
                                                             plan["history_sequence_steps"]):
        raise RuntimeError("mixed sampler geometry must match its history half")
    if (plan["history_burn_in"], plan["history_sequence_steps"]) == (plan["burn_in"],
                                                                     plan["sequence_steps"]):
        raise RuntimeError("mixed single-edge and history geometries must differ")
    return plan


def action_preservation_mixed_weight025_memory_plan():
    """M2n-M2: the E24 mixed batch with the history half's CE+KL scaled by lambda_h=0.25."""
    from ainerzero.learning import action_preservation_closure as apc

    plan = action_preservation_mixed_memory_plan()
    condition = apc.mixed_weight025_condition_plan()
    plan.update(
        protocol=apc.WEIGHT025_PROTOCOL,
        history_weight=apc.MIXED_HISTORY_WEIGHT,
        renormalize_after_scaling=False,
        action_preservation_condition=condition,
    )
    weights, denominator = apc.mixed_half_weights(
        plan["single_edge_rows"], plan["history_rows"], plan["history_weight"]
    )
    if (plan["single_edge_rows"], plan["history_rows"], denominator) != (12, 4, 16.0):
        raise RuntimeError("lambda_h condition must keep the 12/4 rows and the 16-row denominator")
    if weights != {"single_edge": 12.0, "history": 1.0}:
        raise RuntimeError("lambda_h condition weights differ from the A3 registration")
    if condition["mixed_protocol"] != apc.MIXED_PROTOCOL or condition["history_weight"] != 0.25:
        raise RuntimeError("lambda_h condition must derive from the E24 mixed condition")
    if plan["training_model_units_per_update"] != 152 or plan["expected_total_model_units"] != 202_304:
        raise RuntimeError("lambda_h condition must keep the registered unit budget")
    return plan


def action_preservation_mixed_weight0_control_memory_plan():
    """M2n-M3-control: the E24 mixed batch with the history half's CE+KL scaled by lambda_h=0.0."""
    from ainerzero.learning import action_preservation_closure as apc

    plan = action_preservation_mixed_memory_plan()
    condition = apc.mixed_weight0_control_condition_plan()
    plan.update(
        protocol=apc.WEIGHT0_CONTROL_PROTOCOL,
        history_weight=apc.MIXED_CONTROL_HISTORY_WEIGHT,
        renormalize_after_scaling=False,
        action_preservation_condition=condition,
    )
    weights, denominator = apc.mixed_half_weights(
        plan["single_edge_rows"], plan["history_rows"], plan["history_weight"], protocol=apc.WEIGHT0_CONTROL_PROTOCOL
    )
    if (plan["single_edge_rows"], plan["history_rows"], denominator) != (12, 4, 16.0):
        raise RuntimeError("lambda_h condition must keep the 12/4 rows and the 16-row denominator")
    if weights != {"single_edge": 12.0, "history": 0.0}:
        raise RuntimeError("lambda_h condition weights differ from the control registration")
    if condition["mixed_protocol"] != apc.MIXED_PROTOCOL or condition["history_weight"] != 0.0:
        raise RuntimeError("lambda_h condition must derive from the E24 mixed condition")
    if plan["training_model_units_per_update"] != 152 or plan["expected_total_model_units"] != 202_304:
        raise RuntimeError("lambda_h condition must keep the registered unit budget")
    return plan


def action_preservation_mixed_onestep_memory_plan():
    """M2n-M4: the E24 mixed batch with the history half's backward pass truncated to one step.

    Forward, units (152/202304), seconds (1740/1760/1780), gates, seeds, windows,
    schedule, learning rate and clip stay bitwise those of the E24 mixed plan; only the
    history half's backward graph changes (``truncate_each_step``). The single-edge half
    keeps its registered front-row invariant and its full two-frame backward pass.
    """
    from ainerzero.learning import action_preservation_closure as apc

    plan = action_preservation_mixed_memory_plan()
    condition = apc.mixed_onestep_condition_plan()
    plan.update(
        protocol=apc.ONESTEP_PROTOCOL,
        history_weight=apc.MIXED_ONESTEP_HISTORY_WEIGHT,
        renormalize_after_scaling=False,
        truncate_each_step=apc.ONESTEP_TRUNCATE_EACH_STEP,
        action_preservation_condition=condition,
    )
    weights, denominator = apc.mixed_half_weights(
        plan["single_edge_rows"], plan["history_rows"], plan["history_weight"]
    )
    if (plan["single_edge_rows"], plan["history_rows"], denominator) != (12, 4, 16.0):
        raise RuntimeError("onestep condition must keep the 12/4 rows and the 16-row denominator")
    if weights != {"single_edge": 12.0, "history": 4.0}:
        raise RuntimeError("onestep condition weights must stay E24's unscaled 12/4")
    if condition["mixed_protocol"] != apc.MIXED_PROTOCOL or condition["history_weight"] != 1.0:
        raise RuntimeError("onestep condition must derive from the unweighted E24 mixed condition")
    if condition.get("truncate_each_step") is not True:
        raise RuntimeError("onestep condition must register the per-loss-step truncation")
    if plan["training_model_units_per_update"] != 152 or plan["expected_total_model_units"] != 202_304:
        raise RuntimeError("onestep condition must keep the registered unit budget")
    if (plan["total_reserved_seconds_if_complete"], plan["supervised_deadline_seconds"],
            plan["supervisor_deadline_seconds"]) != (1_740, 1_760, 1_780):
        raise RuntimeError("onestep condition must keep the registered seconds and deadlines")
    if condition["units"]["total"] != plan["expected_total_model_units"]:
        raise RuntimeError("onestep condition units must match the plan budget")
    return plan


def action_preservation_mixed_tailself_memory_plan():
    """M2n-M5: the E24 mixed batch with GRU Wh[tail rows, tail cols] frozen at M2d.

    Forward, objective, units (152/202304), seconds (1740/1760/1780), gates, seeds,
    windows, schedule, learning rate and clip stay those of the E24 mixed plan; only the
    trainable scope shrinks from 111,104 to 61,952 elements (331,280 frozen).
    """
    from ainerzero.learning import action_preservation_closure as apc
    from ainerzero.learning import tailself_freeze as tsf

    plan = action_preservation_mixed_memory_plan()
    condition = apc.mixed_tailself_condition_plan()
    plan.update(
        protocol=apc.TAILSELF_PROTOCOL,
        history_weight=apc.MIXED_TAILSELF_HISTORY_WEIGHT,
        renormalize_after_scaling=False,
        trainable_parameter_count=tsf.TAILSELF_TRAINABLE_PARAMETER_COUNT,
        frozen_parameter_count=tsf.TAILSELF_FROZEN_PARAMETER_COUNT,
        frozen_block=condition["frozen_block"],
        action_preservation_condition=condition,
    )
    weights, denominator = apc.mixed_half_weights(
        plan["single_edge_rows"], plan["history_rows"], plan["history_weight"]
    )
    if (plan["single_edge_rows"], plan["history_rows"], denominator) != (12, 4, 16.0):
        raise RuntimeError("tailself condition must keep the 12/4 rows and the 16-row denominator")
    if weights != {"single_edge": 12.0, "history": 4.0}:
        raise RuntimeError("tailself condition weights must stay E24's unscaled 12/4")
    if condition["mixed_protocol"] != apc.MIXED_PROTOCOL or condition["history_weight"] != 1.0:
        raise RuntimeError("tailself condition must derive from the unweighted E24 mixed condition")
    if "truncate_each_step" in condition or plan.get("truncate_each_step"):
        raise RuntimeError("tailself condition keeps E24's full backward pass")
    counts = tsf.mask_counts()
    if (counts["trainable"], counts["frozen"], counts["tailself_block"]) != (61_952, 331_280, 49_152):
        raise RuntimeError("tailself mask element counts differ from the registration")
    if plan["training_model_units_per_update"] != 152 or plan["expected_total_model_units"] != 202_304:
        raise RuntimeError("tailself condition must keep the registered unit budget")
    if (plan["total_reserved_seconds_if_complete"], plan["supervised_deadline_seconds"],
            plan["supervisor_deadline_seconds"]) != (1_740, 1_760, 1_780):
        raise RuntimeError("tailself condition must keep the registered seconds and deadlines")
    if condition["units"]["total"] != plan["expected_total_model_units"]:
        raise RuntimeError("tailself condition units must match the plan budget")
    return plan


def action_preservation_mixed_tailself_halfproj_memory_plan():
    """M2n-M6: the M2n-M5 plan plus the one-sided half-gradient projection.

    Units, seconds, deadlines, rows, weights, frozen block and every guard are
    M2n-M5's; the projection is tensor arithmetic on gradients already computed.
    """
    from ainerzero.learning import action_preservation_closure as apc

    plan = action_preservation_mixed_tailself_memory_plan()
    tailself_condition = plan["action_preservation_condition"]
    condition = apc.mixed_halfproj_condition_plan()
    if condition["tailself_condition_sha256"] != tailself_condition["condition_sha256"]:
        raise RuntimeError("halfproj condition must derive from the M2n-M5 condition")
    plan.update(
        protocol=apc.HALFPROJ_PROTOCOL,
        half_projection=condition["half_projection"],
        action_preservation_condition=condition,
    )
    if condition["units"]["total"] != plan["expected_total_model_units"] or condition["half_projection"]["extra_model_calls"] != 0:
        raise RuntimeError("halfproj condition must keep the M2n-M5 unit budget")
    return plan


def validate_diverse_comparison(report, *, source, identity, queries):
    """Use only a completed frozen M2k report on the same source and queries."""
    from ainerzero.runtime.paired_memory_worker import paired_memory_plan

    if not isinstance(report, dict):
        raise ValueError("diverse comparison must be a report object")
    expected_source = {
        "checkpoint": source["checkpoint"],
        "checkpoint_manifest_sha256": source["checkpoint_manifest_sha256"],
        "run_id": source["parent_run_id"],
    }
    expected = {
        "status": "completed",
        "plan": paired_memory_plan(),
        "source": expected_source,
        "dataset": identity,
        "actual_optimizer_steps": 0,
        "new_environment_steps": 0,
        "logical_model_transitions": 82176,
        "reserved_model_transitions": 82176,
        "weights_unchanged": True,
        "source_files_unchanged": True,
        "local_anchors_reproduced_exactly": True,
        "promoted": False,
        "checkpoint_saved": False,
    }
    paired = report.get("paired", {})
    run = report.get("run", {})
    if not isinstance(paired, dict) or not isinstance(run, dict):
        raise ValueError("diverse comparison requires paired and run objects")
    if (
        any(report.get(k) != v or type(report.get(k)) is not type(v) for k, v in expected.items())
        or run.get("state") != "completed"
        or not report.get("run_id")
        or run.get("run_id") != report["run_id"]
        or not report.get("manifest_hash")
        or paired.get("query_manifest_sha256") != queries["query_manifest_sha256"]
        or paired.get("first_edge_pairs_identical") is not True
        or type(paired.get("first_edge_pair_checks")) is not int
        or paired.get("first_edge_pair_checks") != 20
        or type(paired.get("logical_model_transitions")) is not int
        or paired.get("logical_model_transitions") != 82080
        or not isinstance(paired.get("per_query"), list)
        or len(paired.get("per_query", [])) != 2560
    ):
        raise ValueError("diverse memory requires completed M2k comparison on the same source/data")


def local_memory_screen(result, plan):
    """Whether this measured training micro-batch was fitted; never acceptance."""
    score = result["methods"]["memory_tail"]
    limits = plan["local_screen"]

    def passes(name, threshold):
        value = score.get(name)
        return type(value) in (int, float) and bool(np.isfinite(value)) and threshold <= value <= 1

    checks = {
        "overall_accuracy": passes("accuracy", limits["overall_accuracy_min"]),
        "changed_accuracy": passes("changed_accuracy", limits["changed_accuracy_min"]),
        "sufficient_changed_targets": type(score.get("changed_count")) is int
        and type(score.get("count")) is int
        and limits["minimum_changed_count"] <= score["changed_count"] <= score["count"],
        "training_fit_scope": result.get("partition") == "train"
        and result.get("scope") == "fixed_training_inputs_for_one_edge_memory_fit",
    }
    return {
        "status": "passed" if all(checks.values()) else "failed",
        "checks": checks,
        "scope": "fixed_train_examples_fit_only",
        "promotion": False,
    }


def memory_screen(result, plan):
    """Development screen only; never promotes a model or claims general memory."""
    score = result["methods"]["memory_tail"]
    limits = plan["screen"]
    changed = score["changed_count"]

    def accuracy(value):
        return (
            isinstance(value, (int, float))
            and not isinstance(value, bool)
            and np.isfinite(value)
            and 0 <= value <= 1
        )

    measured = [
        w["methods"]["memory_tail"]
        for w in result["per_world"]
        if w["methods"]["memory_tail"]["changed_count"] > 0
    ]
    checks = {
        "sufficient_changed_targets": changed >= limits["minimum_changed_count"],
        "overall_accuracy": accuracy(score["accuracy"])
        and score["accuracy"] >= limits["overall_accuracy_min"],
        "changed_accuracy": accuracy(score["changed_accuracy"])
        and score["changed_accuracy"] >= limits["changed_accuracy_min"],
        "beats_current_and_reset_changed": accuracy(score["changed_accuracy"])
        and all(
            result["methods"][name]["changed_count"] == changed
            and accuracy(result["methods"][name]["changed_accuracy"])
            and score["changed_accuracy"] > result["methods"][name]["changed_accuracy"]
            for name in ("copy_current", "reset_history")
        ),
        "each_measured_world": bool(measured)
        and sum(w["changed_count"] for w in measured) == changed
        and all(
            accuracy(w["changed_accuracy"])
            and w["changed_accuracy"] >= limits["per_world_changed_accuracy_min"]
            for w in measured
        ),
    }
    return {
        "status": "passed" if all(checks.values()) else "failed",
        "checks": checks,
        "scope": "reused_development_one_step_retention_only",
        "promotion": False,
    }


def _compare_m2l_paired(observed, expected):
    """The frozen M2l candidate must reproduce its own paired report exactly."""
    for field in ("query_manifest_sha256", "random_schedule_sha256", "seed", "particles"):
        if observed.get(field) != expected.get(field):
            raise RuntimeError(f"M2l paired reproduction differs in {field}")
    if observed["logical_model_transitions"] != 82080 or len(observed["per_query"]) != len(
        expected["per_query"]
    ):
        raise RuntimeError("M2l paired reproduction has the wrong size")
    for row, reference in zip(observed["per_query"], expected["per_query"], strict=True):
        if row != reference:
            raise RuntimeError(
                f"M2l paired score did not reproduce exactly at row {reference['row']}"
            )
    if observed["groups"] != expected["groups"] or observed["per_world"] != expected["per_world"]:
        raise RuntimeError("M2l paired group or world summaries did not reproduce exactly")
    return {
        "exact_match": True,
        "queries": len(observed["per_query"]),
        "random_schedule_sha256": observed["random_schedule_sha256"],
        "logical_model_transitions": observed["logical_model_transitions"],
    }


def _prepare_relabel(
    config,
    episodes,
    identity,
    source,
    source_metadata,
    fixed_samples,
    pool,
    training_evidence,
    queries,
    m2l_report_path,
    m2l_checkpoint_path,
    *,
    weight025_lineage=False,
    weight0_control_lineage=False,
    onestep_lineage=False,
):
    """CPU-only binding to the completed M2l candidate plus all relabel evidence.

    ``weight025_lineage``, ``weight0_control_lineage`` and ``onestep_lineage``
    do not take a caller-supplied config. After the registered duty check
    accepts ``source_metadata["config"]`` against the live dump, that stored
    historical config is the lineage view. The live config object is left unchanged.
    """
    from ainerzero.learning.coverage_diagnostic import (
        classify_query_cells,
        pool_position_symbol_sets,
        query_frames,
        query_labels,
    )
    from ainerzero.learning.micro_memory import _batch_digest
    from ainerzero.learning.relabel_memory import (
        relabel_evaluation_pool,
        training_permutation_manifest,
    )
    from ainerzero.runtime.coverage_worker import POOL_FIELDS, validate_coverage_source

    m2l_tensors, m2l_metadata = load_checkpoint(m2l_checkpoint_path)
    m2l_report_bytes = m2l_report_path.read_bytes()
    m2l_report = json.loads(m2l_report_bytes)
    m2l_candidate = {
        "checkpoint": str(m2l_checkpoint_path.resolve()),
        "run_id": m2l_metadata["run_id"],
        "checkpoint_manifest_sha256": hashlib.sha256(
            (m2l_checkpoint_path / "manifest.json").read_bytes()
        ).hexdigest(),
    }
    live_config = config.model_dump(mode="json")
    lineage_config = live_config
    if weight025_lineage:
        from ainerzero.learning.action_preservation_closure import weight025_source_schedule_compat

        weight025_source_schedule_compat(source_metadata, live_config, identity)
        lineage_config = source_metadata["config"]
    elif weight0_control_lineage:
        from ainerzero.learning.action_preservation_closure import weight0_control_source_schedule_compat

        weight0_control_source_schedule_compat(source_metadata, live_config, identity)
        lineage_config = source_metadata["config"]
    elif onestep_lineage:
        from ainerzero.learning.action_preservation_closure import onestep_source_schedule_compat

        onestep_source_schedule_compat(source_metadata, live_config, identity)
        lineage_config = source_metadata["config"]
    validate_coverage_source(
        source_metadata,
        m2l_metadata,
        lineage_config,
        identity,
        source,
        m2l_candidate,
        m2l_report,
        fixed_samples,
        training_evidence,
        queries,
    )
    run_directory = m2l_checkpoint_path.resolve().parents[1]
    pool_path = run_directory / "training-pool.npz"
    if m2l_report.get("run_directory") != str(run_directory) or m2l_report.get(
        "training_pool_path"
    ) != str(pool_path):
        raise ValueError("M2l pool must be the archive saved beside the M2l checkpoint")
    pool_bytes = pool_path.read_bytes()
    with np.load(pool_path, allow_pickle=False) as archive:
        saved = {name: archive[name] for name in archive.files}
    if (
        set(saved) != set(POOL_FIELDS)
        or any(
            saved[k].dtype != pool[k].dtype or not np.array_equal(saved[k], pool[k])
            for k in POOL_FIELDS
        )
        or _batch_digest(saved) != training_evidence["batch_sha256"]
    ):
        raise ValueError("saved M2l training pool differs from the rebuilt registered pool")
    frames, frame_evidence = query_frames(episodes)
    if frame_evidence["query_manifest_sha256"] != queries["query_manifest_sha256"]:
        raise ValueError("query frames changed after registration")
    labels = query_labels(frame_evidence["queries"], training_evidence)
    symbol_sets = pool_position_symbol_sets(pool)
    classification = classify_query_cells(frames, symbol_sets)
    positions = {
        (row["episode_id"], row["query_tick"]): index
        for index, row in enumerate(frame_evidence["queries"])
    }
    pool_query_rows = [
        positions[(row["episode_id"], row["query_tick"])] for row in training_evidence["samples"]
    ]
    seeds = [
        m2l_report["paired"]["per_query"][row]["paired_random_seeds"] for row in pool_query_rows
    ]
    training_manifest = training_permutation_manifest()
    if training_manifest["unique_count"] != training_manifest["count"]:
        raise ValueError("registered training bijections must be distinct")
    batch, evaluation = relabel_evaluation_pool(pool, training_manifest)
    m2l_reference = {
        "report": {
            "path": str(m2l_report_path.resolve()),
            "sha256": hashlib.sha256(m2l_report_bytes).hexdigest(),
            "run_id": m2l_report["run_id"],
            "experiment_id": m2l_report.get("experiment_id"),
            "manifest_hash": m2l_report["manifest_hash"],
        },
        "candidate": m2l_candidate,
        "training_pool": {
            "path": str(pool_path),
            "sha256": hashlib.sha256(pool_bytes).hexdigest(),
            "batch_sha256": training_evidence["batch_sha256"],
        },
    }
    coverage = {
        "symbol_sets": symbol_sets,
        "classification_sha256": classification["classification_sha256"],
        "query_label_sha256": hashlib.sha256(json.dumps(labels).encode()).hexdigest(),
        "pool_query_rows": pool_query_rows,
        "pool_row_seeds": seeds,
    }
    summary = {
        "m2l": m2l_reference,
        "coverage": coverage,
        "training_permutations": training_manifest,
        "relabel_evaluation": evaluation,
    }
    return {
        "declaration": summary,
        "report": {
            "m2l": m2l_reference,
            "coverage": {k: v for k, v in coverage.items() if k != "pool_row_seeds"},
            "training_permutations_sha256": training_manifest["manifest_sha256"],
            "relabel_evaluation": {k: v for k, v in evaluation.items() if k != "digests"},
        },
        "m2l_report": m2l_report,
        "m2l_report_bytes": m2l_report_bytes,
        "m2l_tensors": m2l_tensors,
        "m2l_candidate": m2l_candidate,
        "pool_path": pool_path,
        "pool_bytes": pool_bytes,
        "training_manifest": training_manifest,
        "batch": batch,
        "seeds": seeds,
        "pool_query_rows": pool_query_rows,
        "classification": classification,
        "labels": labels,
        "targets": frames["previous_symbols"],
    }


def _keep_update(model, keep_grad, keep, cache_arrays, keep_windows, index, memory_sum, memory_targets,
                 guard, *, keep_lambda):
    """Keep rows at B=1, one combined/masked tree for clip and AdamW.

    Shared by the M2m-d training branch and the C06a probe. Returns the float32
    applied tree, logged details, and per-row extra aux outputs (probe only).
    """
    import mlx.core as mx
    from mlx.utils import tree_flatten, tree_unflatten

    from ainerzero.learning import action_preservation as ap
    from ainerzero.learning import action_preservation_closure as apc

    rows = keep["windows"]["schedule"][index]
    pending, keep_trees, losses, per_horizon, extras = [], [], [], [], []
    for position, row in enumerate(rows):
        cached = {name: cache_arrays[name][row] for name in ap.CACHE_ARRAYS}
        (loss, aux), grads = keep_grad(
            model, cached, keep_windows[row], keep["keys"]["rows"][row]["keys"]
        )
        horizons, extra = aux if isinstance(aux, tuple) else (aux, None)
        pending.append((loss, horizons, grads, extra))
        if (position + 1) % ap.KEEP_ROW_ACCUMULATION == 0:
            mx.eval(*[item for entry in pending for item in entry if item is not None])
            for loss, horizons, grads, extra in pending:
                losses.append(float(loss.item()))
                per_horizon.append(np.array(horizons).astype(np.float64).tolist())
                keep_trees.append(
                    {k.removeprefix("gru."): np.asarray(v).astype(np.float64) for k, v in tree_flatten(grads)}
                )
                extras.append(None if extra is None else np.array(extra))
            pending = []
            guard()
    memory_np = {
        k.removeprefix("gru."): np.asarray(v).astype(np.float64) for k, v in tree_flatten(memory_sum)
    }
    combined = (
        ap.combine_branch_gradients(memory_np, memory_targets, keep_trees)
        if keep_lambda == ap.LAMBDA_KEEP
        else apc.combine_branch_gradients_v2(memory_np, memory_targets, keep_trees, lam=keep_lambda)
    )
    applied = {}
    for name, value in combined.items():
        frozen = ap.frozen_row_mask(name)
        applied[name] = np.where(frozen[:, None] if value.ndim == 2 else frozen, 0.0, value)
    front = ap.check_applied_front_gradient(combined, applied)

    def norm(tree, rows_mask=None):
        total = 0.0
        for name, value in tree.items():
            selected = value if rows_mask is None else value[rows_mask(name)]
            total += float(np.sum(selected**2))
        return float(np.sqrt(total))

    memory_mean = {k: v / memory_targets for k, v in memory_np.items()}
    keep_mean = {k: sum(t[k] for t in keep_trees) / len(keep_trees) for k in memory_np}
    details = {
        "keep_loss": float(np.mean(losses)),
        "keep_row_losses": losses,
        "keep_row_horizon_losses": per_horizon,
        "keep_rows": [int(r) for r in rows],
        "student_units": keep["student_units"][index],
        "keep_lambda": float(keep_lambda),
        "memory_gradient_l2": norm(memory_mean),
        "keep_gradient_l2": norm(keep_mean),
        "combined_front_gradient_l2": norm(combined, ap.frozen_row_mask),
        "combined_tail_gradient_l2": norm(combined, lambda name: ~ap.frozen_row_mask(name)),
        # Guard values for the COMBINED (memory + keep) gradient, named explicitly
        # so they cannot clobber the memory-branch-only `raw_front_gradient_l2`
        # logged by the training loop (E16 finding A1).
        "combined_raw_front_gradient_l2": front["raw_front_gradient_l2"],
        "combined_applied_front_gradient_l2": front["applied_front_gradient_l2"],
        "combined_front_applied_gradient_max": front["front_applied_gradient_max"],
    }
    tree = tree_unflatten([(f"gru.{k}", mx.array(v.astype(np.float32))) for k, v in applied.items()])
    return tree, details, extras


def run_memory(
    config_path,
    dataset_path,
    checkpoint_path,
    output_root,
    control_db,
    experiment_id,
    *,
    local_fit=False,
    diverse_fit=False,
    comparison_report_path=None,
    relabel_fit=False,
    m2l_report_path=None,
    m2l_checkpoint_path=None,
    relabel_learning_rate=None,
    action_preservation_fit=False,
    m2mc_report_path=None,
    action_preservation_lambda10=False,
    action_preservation_distill=False,
    action_preservation_history=False,
    action_preservation_mixed=False,
    action_preservation_mixed_weight025=False,
    action_preservation_mixed_weight0_control=False,
    action_preservation_mixed_onestep=False,
    action_preservation_mixed_tailself=False,
    action_preservation_mixed_tailself_halfproj=False,
):
    from ainerzero.cli import pilot_manifest

    started = time.perf_counter()
    if action_preservation_lambda10 and action_preservation_distill:
        raise ValueError("choose one action-preservation condition")
    if action_preservation_lambda10:
        if action_preservation_fit:
            raise ValueError("choose one action-preservation condition")
        action_preservation_fit = True  # same branch, registered lambda only
    if action_preservation_history and (action_preservation_distill
                                        or action_preservation_lambda10):
        raise ValueError("choose one action-preservation condition")
    if action_preservation_mixed and (action_preservation_distill or action_preservation_lambda10
                                      or action_preservation_history):
        raise ValueError("choose one action-preservation condition")
    if action_preservation_mixed_weight0_control:
        if (action_preservation_mixed or action_preservation_mixed_weight025 or action_preservation_distill
                or action_preservation_lambda10 or action_preservation_history
                or action_preservation_mixed_onestep):
            raise ValueError("choose one action-preservation condition")
        action_preservation_mixed = True
    if action_preservation_mixed_weight025:
        if (action_preservation_mixed or action_preservation_mixed_weight0_control or action_preservation_distill
                or action_preservation_lambda10 or action_preservation_history
                or action_preservation_mixed_onestep):
            raise ValueError("choose one action-preservation condition")
        action_preservation_mixed = True  # same mixed branch, history half weighted by lambda_h
    if action_preservation_mixed_tailself_halfproj:
        if (action_preservation_mixed_tailself or action_preservation_mixed
                or action_preservation_mixed_weight025
                or action_preservation_mixed_weight0_control or action_preservation_distill
                or action_preservation_lambda10 or action_preservation_history
                or action_preservation_mixed_onestep):
            raise ValueError("choose one action-preservation condition")
        action_preservation_mixed_tailself = True  # M2n-M5 branch + half projection
    if action_preservation_mixed_tailself:
        if (action_preservation_mixed or action_preservation_mixed_weight025
                or action_preservation_mixed_weight0_control or action_preservation_distill
                or action_preservation_lambda10 or action_preservation_history
                or action_preservation_mixed_onestep):
            raise ValueError("choose one action-preservation condition")
        action_preservation_mixed = True  # same mixed branch, Wh tail-self block frozen
    if action_preservation_mixed_onestep:
        if (action_preservation_mixed or action_preservation_mixed_weight025
                or action_preservation_mixed_weight0_control or action_preservation_distill
                or action_preservation_lambda10 or action_preservation_history):
            raise ValueError("choose one action-preservation condition")
        action_preservation_mixed = True  # same mixed branch, history backward truncated to one step
    if action_preservation_distill:
        if action_preservation_fit:
            raise ValueError("choose one action-preservation condition")
        action_preservation_fit = True  # same branch, in-batch loss routing
    if action_preservation_history:
        if action_preservation_fit:
            raise ValueError("choose one action-preservation condition")
        action_preservation_fit = True   # same branch, history windows
        action_preservation_distill = True  # same in-batch teacher distillation
    if action_preservation_mixed:
        if action_preservation_fit:
            raise ValueError("choose one action-preservation condition")
        action_preservation_fit = True      # same branch, mixed batch
        action_preservation_distill = True  # same in-batch teacher distillation
    if bool(action_preservation_fit) != (m2mc_report_path is not None):
        raise ValueError("action preservation requires exactly its M2m-c report")
    if action_preservation_fit:
        if local_fit or diverse_fit or relabel_fit or relabel_learning_rate is not None:
            raise ValueError("action preservation fixes its own protocol; no manual combination")
        relabel_fit = True  # M2m-c memory branch, lr fixed by the M2m-d plan
    if diverse_fit and local_fit:
        raise ValueError("choose one memory training protocol")
    if relabel_fit and (diverse_fit or local_fit):
        raise ValueError("choose one memory training protocol")
    if bool(relabel_fit) != (m2l_report_path is not None) or bool(relabel_fit) != (
        m2l_checkpoint_path is not None
    ):
        raise ValueError("relabel memory requires exactly its M2l report and checkpoint")
    if relabel_learning_rate is not None and not relabel_fit:
        raise ValueError("learning rate variant applies only to relabel memory")
    diverse_fit = diverse_fit or relabel_fit
    if bool(diverse_fit) != (comparison_report_path is not None):
        raise ValueError("diverse memory requires its M2k comparison report only")
    local_fit = local_fit or diverse_fit
    config = load_pilot_config(config_path)
    plan = (
        action_preservation_mixed_tailself_halfproj_memory_plan()
        if action_preservation_mixed_tailself_halfproj
        else action_preservation_mixed_tailself_memory_plan()
        if action_preservation_mixed_tailself
        else action_preservation_mixed_onestep_memory_plan()
        if action_preservation_mixed_onestep
        else action_preservation_mixed_weight0_control_memory_plan()
        if action_preservation_mixed_weight0_control
        else action_preservation_mixed_weight025_memory_plan()
        if action_preservation_mixed_weight025
        else action_preservation_mixed_memory_plan()
        if action_preservation_mixed
        else action_preservation_history_memory_plan()
        if action_preservation_history
        else action_preservation_distill_memory_plan()
        if action_preservation_distill
        else action_preservation_lambda10_memory_plan()
        if action_preservation_lambda10
        else action_preservation_memory_plan()
        if action_preservation_fit
        else relabel_memory_plan(0.001 if relabel_learning_rate is None else relabel_learning_rate)
        if relabel_fit
        else diverse_memory_plan()
        if diverse_fit
        else micro_memory_plan()
        if local_fit
        else memory_plan()
    )
    phase_name = (
        "action_preserved_mixed_tailself_halfproj_memory_fit"
        if action_preservation_mixed_tailself_halfproj
        else "action_preserved_mixed_tailself_memory_fit"
        if action_preservation_mixed_tailself
        else "action_preserved_mixed_onestep_memory_fit"
        if action_preservation_mixed_onestep
        else "action_preserved_mixed_weight0_control_memory_fit"
        if action_preservation_mixed_weight0_control
        else "action_preserved_mixed_weight025_memory_fit"
        if action_preservation_mixed_weight025
        else "action_preserved_mixed_memory_fit"
        if action_preservation_mixed
        else "action_preserved_history_memory_fit"
        if action_preservation_history
        else "action_preserved_distill_memory_fit"
        if action_preservation_distill
        else "action_preserved_lambda10_memory_fit"
        if action_preservation_lambda10
        else "action_preserved_memory_fit"
        if action_preservation_fit
        else "relabel_memory_fit"
        if relabel_fit
        else "diverse_memory_fit"
        if diverse_fit
        else "micro_memory_fit"
        if local_fit
        else "one_step_memory"
    )
    policy = TrainingPolicy(allowed_actors=(RANDOM_ACTOR,))
    paths, episodes, identity = load_pilot_dataset(dataset_path, policy)
    source_tensors, source_metadata = load_checkpoint(checkpoint_path)
    live_config = config.model_dump(mode="json")
    schedule_compat = None
    if action_preservation_mixed_weight025:
        from ainerzero.learning.action_preservation_closure import weight025_source_schedule_compat

        schedule_compat = weight025_source_schedule_compat(source_metadata, live_config, identity)
    elif action_preservation_mixed_weight0_control:
        from ainerzero.learning.action_preservation_closure import weight0_control_source_schedule_compat

        schedule_compat = weight0_control_source_schedule_compat(source_metadata, live_config, identity)
    elif action_preservation_mixed_onestep:
        from ainerzero.learning.action_preservation_closure import onestep_source_schedule_compat

        schedule_compat = onestep_source_schedule_compat(source_metadata, live_config, identity)
    elif action_preservation_mixed_tailself_halfproj:
        from ainerzero.learning.action_preservation_closure import halfproj_source_schedule_compat

        schedule_compat = halfproj_source_schedule_compat(source_metadata, live_config, identity)
    elif action_preservation_mixed_tailself:
        from ainerzero.learning.action_preservation_closure import tailself_source_schedule_compat

        schedule_compat = tailself_source_schedule_compat(source_metadata, live_config, identity)
    else:
        validate_history_source(source_metadata, live_config, identity)
    fixed_batch = sample_evidence = None
    if local_fit:
        from ainerzero.learning.micro_memory import select_micro_memory_samples

        fixed_batch, sample_evidence = select_micro_memory_samples(episodes["train"])
    source = {
        "checkpoint": str(checkpoint_path.resolve()),
        "parent_run_id": source_metadata["run_id"],
        "checkpoint_manifest_sha256": hashlib.sha256(
            (checkpoint_path / "manifest.json").read_bytes()
        ).hexdigest(),
        "dataset": identity,
    }
    if schedule_compat is not None:
        source["schedule_compat"] = schedule_compat
    diverse_pool = training_evidence = comparison = comparison_bytes = None
    if diverse_fit:
        from ainerzero.learning.diverse_evaluation import summarize_diverse_pairs
        from ainerzero.learning.diverse_memory import (
            diverse_training_schedule,
            get_diverse_batch,
            select_diverse_memory_samples,
        )
        from ainerzero.learning.paired_memory import evaluate_paired_memory, paired_memory_samples

        diverse_pool, training_evidence = select_diverse_memory_samples(episodes["train"])
        queries = paired_memory_samples(episodes)
        comparison_bytes = comparison_report_path.read_bytes()
        comparison = json.loads(comparison_bytes)
        validate_diverse_comparison(comparison, source=source, identity=identity, queries=queries)
        # CPU-only regrouping: both candidates will use the same new selection labels.
        comparison_groups = summarize_diverse_pairs(comparison["paired"], training_evidence)
        comparison_reference = {
            "path": str(comparison_report_path.resolve()),
            "sha256": hashlib.sha256(comparison_bytes).hexdigest(),
            "run_id": comparison["run_id"],
        }
    relabel = None
    if relabel_fit:
        relabel = _prepare_relabel(
            config,
            episodes,
            identity,
            source,
            source_metadata,
            sample_evidence,
            diverse_pool,
            training_evidence,
            queries,
            m2l_report_path,
            m2l_checkpoint_path,
            weight025_lineage=action_preservation_mixed_weight025,
            weight0_control_lineage=action_preservation_mixed_weight0_control,
            onestep_lineage=action_preservation_mixed_onestep or action_preservation_mixed_tailself,
        )
    keep = None
    if action_preservation_fit:
        from ainerzero.learning import action_preservation_closure as apc

        # CPU closure before any experiment/run exists; mismatch creates no run.
        keep = apc.production_windows(
            training_evidence["samples"],
            diverse_training_schedule(),
            apc.public_records_from_episodes(episodes["train"]),
        )
        with RunStore(control_db) as closure_store:
            keep["reuse"] = apc.m2l_reuse_closure(
                m2mc_report_path, relabel, closure_store, episodes=episodes
            )
        keep["summary"] = {
            "protocol": plan["protocol"],
            "windows_sha256": keep["windows"]["windows_sha256"],
            "key_manifest_sha256": keep["keys"]["manifest_sha256"],
            "keys_sha256": keep["keys"]["keys_sha256"],
            "student_units": keep["student_units"],
            "m2l_reuse": keep["reuse"]["evidence"],
        }
    declaration = pilot_manifest(config_path)["manifest"]
    declaration.update(
        purpose=f"c0_{phase_name}_training_v1",
        one_step_memory=plan,
        source=declaration["source"],
        student_source=source,
    )
    if local_fit:
        declaration["fixed_samples"] = sample_evidence
    if diverse_fit:
        declaration.update(
            training_samples=training_evidence,
            paired_samples=queries,
            comparison_report=comparison_reference,
        )
    if relabel_fit:
        declaration.update(relabel=relabel["declaration"])
    if action_preservation_fit:
        declaration.update(action_preservation=keep["summary"])
    directory = Path(output_root) / f"pilot-{uuid4().hex}"
    directory.mkdir(parents=True)
    report_path = directory / "report.json"
    report = {
        "status": "running",
        "experiment_id": experiment_id,
        "plan": plan,
        "source": source,
        "dataset": str(dataset_path.resolve()),
        "actual_optimizer_steps": 0,
        "new_environment_steps": 0,
        "training_model_transitions": 0,
        "before": {},
        "after": {},
        "promoted": False,
        "run_directory": str(directory.resolve()),
        "report_path": str(report_path.resolve()),
    }
    if local_fit:
        report.update(
            fixed_samples=sample_evidence,
            local_checks={},
            effective_trainable_parameter_count=111104,
            frozen_parameter_count=282128,
            tail_protection_checks=0,
        )
        if action_preservation_mixed_tailself:
            report.update(
                effective_trainable_parameter_count=plan["trainable_parameter_count"],
                frozen_parameter_count=plan["frozen_parameter_count"],
                tailself_frozen_block=plan["frozen_block"],
            )
    if diverse_fit:
        report.update(
            training_samples=training_evidence,
            comparison_report=comparison_reference,
            comparison_groups=comparison_groups,
        )
    if relabel_fit:
        report.update(
            relabel=relabel["report"],
            relabel_pool={},
            before_matches_m2l=None,
        )
    if action_preservation_fit:
        report.update(action_preservation=keep["summary"], teacher_cache=None, keep_loss_first_update=None)
        report.update(keep_lambda=plan["keep_lambda"],
                      action_preservation_protocol=plan["protocol"],
                      action_preservation_condition=plan.get("action_preservation_condition"),
                      distill=plan.get("distill"))
    store = RunStore(control_db)
    run_id = None
    model = optimizer = None
    stage_started = stage_seconds = None
    last_guard = 0.0
    initial_swap = psutil.swap_memory().used
    completed_units = 0
    reserved_units = 0

    def persist():
        report["elapsed_seconds"] = time.perf_counter() - started
        atomic_write_json(report_path, report)

    def guard(force=False):
        nonlocal last_guard
        now = time.monotonic()
        if stage_started is not None and time.perf_counter() - stage_started > stage_seconds:
            raise RuntimeError("memory experiment exceeded prepaid stage window")
        if time.perf_counter() - started > plan["supervised_deadline_seconds"]:
            raise RuntimeError("memory experiment reached supervised deadline")
        if not force and now - last_guard < 1:
            return
        last_guard = now
        if psutil.virtual_memory().available < config.resources.system_reserve_gib * 2**30:
            raise RuntimeError("memory experiment system memory reserve reached")
        if psutil.Process().memory_info().rss > config.resources.active.project_memory_gib * 2**30:
            raise RuntimeError("memory experiment process memory limit reached")
        if psutil.swap_memory().used - initial_swap > config.resources.swap_growth_gib * 2**30:
            raise RuntimeError("memory experiment swap growth limit reached")
        if psutil.disk_usage(directory).free < config.resources.minimum_disk_free_gib * 2**30:
            raise RuntimeError("memory experiment disk reserve reached")
        # User policy: battery power does not block registered model work.
    def stage(name, *, updates=0, units=0):
        nonlocal stage_started, stage_seconds, reserved_units
        guard(force=True)
        stage_seconds = plan["resource_seconds"][name]
        store.consume(
            run_id, active_seconds=stage_seconds, optimizer_steps=updates, model_transitions=units
        )
        reserved_units += units
        stage_started = time.perf_counter()
        report["current_stage"] = name
        persist()

    def reserve(count):
        nonlocal reserved_units
        guard()
        store.consume(run_id, model_transitions=count)
        reserved_units += count

    try:
        guard(force=True)
        if diverse_fit:
            prior = store.get_run(comparison["run_id"])
            prior_experiment = store.get_experiment(prior.experiment_id)
            if (
                prior.state != "completed"
                or prior.experiment_id != comparison.get("experiment_id")
                or prior.role != "auxiliary"
                or prior.reserved_optimizer_steps != 0
                or prior.reserved_model_transitions != 82176
                or prior_experiment.manifest_hash != comparison["manifest_hash"]
            ):
                raise ValueError("canonical ledger does not confirm M2k comparison")
        if relabel_fit:
            m2l_report = relabel["m2l_report"]
            prior = store.get_run(m2l_report["run_id"])
            prior_experiment = store.get_experiment(prior.experiment_id)
            if (
                prior.state != "completed"
                or prior.experiment_id != m2l_report.get("experiment_id")
                or prior.role != "model"
                or prior.reserved_optimizer_steps != 200
                or prior.reserved_environment_steps != 0
                or prior.reserved_model_transitions != 174208
                or prior_experiment.manifest_hash != m2l_report["manifest_hash"]
            ):
                raise ValueError("canonical ledger does not confirm the completed M2l candidate")
        experiment = store.create_experiment(declaration, experiment_id, experiment_id)
        atomic_write_json(directory / "preregistration.json", declaration)
        run_id = str(uuid4())
        snapshot = config.snapshot_for_run(0)
        snapshot["one_step_memory"] = {"plan": plan, "source": source}
        store.create_run(snapshot, run_id, run_id=run_id, experiment_id=experiment_id, role="model")
        store.transition(run_id, "initializing")
        store.transition(run_id, "validating")
        report.update(run_id=run_id, manifest_hash=experiment.manifest_hash)
        stage("compatibility")
        if local_fit:
            np.savez(directory / "fixed-batch.npz", **fixed_batch)
            report["fixed_batch_path"] = str((directory / "fixed-batch.npz").resolve())
        if diverse_fit:
            np.savez(directory / "training-pool.npz", **diverse_pool)
            np.save(directory / "training-schedule.npy", diverse_training_schedule())
            report["training_pool_path"] = str((directory / "training-pool.npz").resolve())
            report["training_schedule_path"] = str((directory / "training-schedule.npy").resolve())
        report["codec_compatibility"] = audit_bounded_codec(
            source_tensors["model.byte_embedding.weight"],
            source_tensors["model.symbol_readout.weight"],
            source_tensors["model.symbol_readout.bias"],
        )
        persist()
        if not report["codec_compatibility"]["bounded_codec_compatible"]:
            raise RuntimeError(
                "bounded frozen codec compatibility check failed; no student updates"
            )

        stage("initialization")
        import mlx.core as mx
        import mlx.nn as nn
        import mlx.optimizers as optim
        from mlx.utils import tree_flatten, tree_map, tree_unflatten

        from ainerzero.learning.evaluation import evaluate_predictor
        from ainerzero.learning.one_step_memory import (
            evaluate_one_step_memory,
            memory_sequence_loss,
        )
        from ainerzero.learning.pilot_model import SharedSymbolPredictor
        from ainerzero.learning.reconstruction import evaluate_reconstruction

        if not mx.metal.is_available():
            raise RuntimeError("Metal unavailable; no CPU fallback")
        mx.set_default_device(mx.gpu)
        mx.set_memory_limit(int(config.resources.active.mlx_memory_gib * 2**30))
        mx.set_cache_limit(int(config.resources.active.mlx_cache_gib * 2**30))
        mx.reset_peak_memory()
        model = SharedSymbolPredictor(config.model, key=mx.random.key(999))
        expected = {f"model.{k}": v.shape for k, v in tree_flatten(model.parameters())}
        if {k: v.shape for k, v in source_tensors.items() if k.startswith("model.")} != expected:
            raise ValueError("memory source parameter keys/shapes mismatch")
        model.update(
            tree_unflatten(
                [(k[6:], mx.array(v)) for k, v in source_tensors.items() if k.startswith("model.")]
            )
        )
        model.freeze()
        model.gru.unfreeze()
        mx.eval(model.parameters())
        trainable = dict(tree_flatten(model.trainable_parameters()))
        report["parameter_count"] = sum(v.size for _, v in tree_flatten(model.parameters()))
        report["trainable_parameter_count"] = sum(v.size for v in trainable.values())
        report["trainable_keys"] = sorted(trainable)
        if (
            set(trainable) != {"gru.Wx", "gru.Wh", "gru.b", "gru.bhn"}
            or report["trainable_parameter_count"] != 222208
            or report["parameter_count"] != 393232
        ):
            raise RuntimeError("memory experiment trainable scope or parameter count mismatch")
        if local_fit:
            from ainerzero.learning.micro_memory import evaluate_micro_memory
            from ainerzero.learning.tail_update import (
                mask_gru_tail_gradients,
                project_gru_front,
                verify_tail_update,
            )

            # MLX exposes full GRU tensors; only their tail rows may actually change.
            report["optimizer_tensor_parameter_count"] = report["trainable_parameter_count"]
            report["trainable_parameter_count"] = plan["trainable_parameter_count"]
            verify_tail_update(
                source_tensors,
                {f"model.{k}": np.array(v) for k, v in tree_flatten(model.parameters())},
            )
            if action_preservation_mixed_tailself:
                from ainerzero.learning.tailself_freeze import (
                    check_applied_frozen_gradient,
                    mask_tailself_gradients,
                    project_tailself,
                    verify_tailself_update,
                )

                verify_tailself_update(
                    source_tensors,
                    {f"model.{k}": np.array(v) for k, v in tree_flatten(model.parameters())},
                )
        optimizer = optim.AdamW(
            learning_rate=plan["learning_rate"],
            betas=config.training.adam_betas,
            eps=config.training.adam_epsilon,
            weight_decay=config.training.weight_decay,
            bias_correction=True,
        )
        optimizer.init(model.trainable_parameters())
        mx.eval(optimizer.state)
        # The history condition samples multi-step windows, so it needs the sampler
        # even though it runs through the local-fit branch for the registered pool.
        # A condition that samples windows must take its geometry from the plan's
        # explicit sampler geometry: the mixed condition's plan-level burn_in /
        # sequence_steps describe its single-edge half, not its history half
        # (independent review finding B-F1).
        geometry = plan.get("sampler_geometry",
                            {"burn_in": plan["burn_in"], "sequence_steps": plan["sequence_steps"]})
        sampler = (
            SequenceSampler(
                paths["train"],
                policy,
                burn_in=geometry["burn_in"],
                sequence_steps=geometry["sequence_steps"],
            )
            if action_preservation_history or action_preservation_mixed or not local_fit
            else None
        )
        baseline = NoActionBaseline(policy).fit(episodes["train"])

        def evaluate_phase(phase):
            nonlocal completed_units
            for partition in ("train", "development"):
                stage(f"{phase}_memory_{partition}")
                result = evaluate_one_step_memory(
                    model,
                    episodes[partition],
                    partition=partition,
                    before_work=reserve,
                    seed=plan["seeds"][f"memory_{partition}"],
                    support_ticks=32,
                    particles=8,
                )
                report[phase][f"memory_{partition}"] = result
                completed_units += result["logical_model_transitions"]
                guard(force=True)
                persist()
            stage(f"{phase}_action")
            report[phase]["action"] = evaluate_predictor(
                model, episodes["development"], baseline, before_work=reserve
            )
            completed_units += report[phase]["action"]["logical_model_transitions"]
            guard(force=True)
            stage(f"{phase}_reconstruction")
            report[phase]["reconstruction"] = evaluate_reconstruction(
                model, episodes["development"], before_work=reserve
            )
            completed_units += report[phase]["reconstruction"]["observation_encodes"]
            guard(force=True)
            persist()

        def evaluate_local(update):
            nonlocal completed_units
            if not local_fit:
                return
            results = report["local_checks"][str(update)] = {}
            for name, seed in (
                ("training_noise", plan["seeds"]["latent"]),
                ("same_inputs_new_noise", plan["seeds"]["local_new_noise"]),
            ):
                stage("local_check")
                results[name] = evaluate_micro_memory(
                    model,
                    fixed_batch,
                    seed=seed,
                    before_work=reserve,
                    micro_batch_size=plan["micro_batch_size"],
                )
                if results[name]["logical_model_transitions"] != plan["local_check_model_units"]:
                    raise RuntimeError("local memory evaluation exceeded fixed model units")
                completed_units += results[name]["logical_model_transitions"]
                guard(force=True)
                persist()

        if action_preservation_fit and not action_preservation_distill:
            from ainerzero.learning import action_preservation as ap
            from ainerzero.learning import action_preservation_mlx as apm

            m2l_cells = keep["reuse"]["paired_cells"]
            report["relabel_pool"]["m2l"] = keep["reuse"]["relabel_pool"]
            report["relabel_pool"]["m2l_cells"] = keep["reuse"]["relabel_pool_cells"]
            report["m2l_reuse"] = keep["reuse"]["evidence"]
            stage("teacher_cache")
            teacher = SharedSymbolPredictor(config.model, key=mx.random.key(999))
            teacher.update(
                tree_unflatten(
                    [(k[6:], mx.array(v)) for k, v in source_tensors.items() if k.startswith("model.")]
                )
            )
            teacher.freeze()
            mx.eval(teacher.parameters())
            if any(
                not np.array_equal(np.array(v), source_tensors[f"model.{k}"])
                for k, v in tree_flatten(teacher.parameters())
            ) or tree_flatten(teacher.trainable_parameters()):
                raise RuntimeError("frozen M2d teacher did not load exactly")
            cache_arrays = apm.build_teacher_cache(
                teacher, episodes["train"], keep["windows"], keep["keys"], before_work=reserve
            )
            completed_units += ap.TEACHER_UNITS
            del teacher
            cache_binding = apc.expected_cache_binding(
                checkpoint_path=checkpoint_path,
                windows=keep["windows"],
                keys=keep["keys"],
                run_id=run_id,
            )
            cache_manifest = ap.teacher_cache_manifest(cache_binding, cache_arrays)
            cache_path = directory / "teacher-cache.npz"
            cache_manifest_path = directory / "teacher-cache-manifest.json"
            if cache_path.exists() or cache_manifest_path.exists():
                raise RuntimeError("teacher cache files must be new")
            np.savez(cache_path, **cache_arrays)
            cache_bytes = cache_path.read_bytes()
            cache_file = {
                "path": str(cache_path.resolve()),
                "size": len(cache_bytes),
                "sha256": hashlib.sha256(cache_bytes).hexdigest(),
            }
            atomic_write_json(cache_manifest_path, {**cache_manifest, "file": cache_file})
            guard(force=True)
            persist()
            stage("cache_protocol_checks")
            stored = json.loads(cache_manifest_path.read_text())
            reread = cache_path.read_bytes()
            if stored.pop("file") != cache_file or (
                len(reread),
                hashlib.sha256(reread).hexdigest(),
            ) != (cache_file["size"], cache_file["sha256"]):
                raise RuntimeError("teacher cache file identity changed")
            with np.load(cache_path) as loaded:
                cache_arrays = {name: loaded[name] for name in loaded.files}
            ap.verify_teacher_cache(
                stored,
                cache_arrays,
                cache_binding,
                apm.q_visible_mask(episodes["train"], keep["windows"]),
            )
            keep_windows = apm.row_windows(episodes["train"], keep["windows"])
            report["teacher_cache"] = {
                "file": cache_file,
                "manifest_path": str(cache_manifest_path.resolve()),
                "manifest_sha256": cache_manifest["manifest_sha256"],
                "binding": cache_binding,
            }
            guard(force=True)
            persist()
        if relabel_fit:
            # The candidate relabel-pool evaluation runs for BOTH relabel variants
            # (M2m-c and M2m-d); these names must be bound before that branch.
            from ainerzero.learning.paired_memory import evaluate_zero_context_inputs
            from ainerzero.learning.relabel_memory import summarize_relabel_pool
        if action_preservation_distill:
            from ainerzero.learning import action_preservation as ap
            from ainerzero.learning import action_preservation_mlx as apm

            m2l_cells = keep["reuse"]["paired_cells"]
            report["relabel_pool"]["m2l"] = keep["reuse"]["relabel_pool"]
            report["relabel_pool"]["m2l_cells"] = keep["reuse"]["relabel_pool_cells"]
            report["m2l_reuse"] = keep["reuse"]["evidence"]
            # No dedicated stage: the D plan deliberately reserves no teacher-cache
            # window (review finding F1); the load stays inside the open
            # `initialization` window and its own time is recorded.
            guard(force=True)
            teacher_load_started = time.perf_counter()
            teacher = SharedSymbolPredictor(config.model, key=mx.random.key(999))
            teacher.update(
                tree_unflatten(
                    [(k[6:], mx.array(v)) for k, v in source_tensors.items() if k.startswith("model.")]
                )
            )
            teacher.freeze()
            mx.eval(teacher.parameters())
            if any(
                not np.array_equal(np.array(v), source_tensors[f"model.{k}"])
                for k, v in tree_flatten(teacher.parameters())
            ) or tree_flatten(teacher.trainable_parameters()):
                raise RuntimeError("frozen M2d teacher did not load exactly")
            report["teacher_cache"] = {"mode": "none_online_per_update_same_batch",
                                       "teacher_frozen": True, "teacher_in_optimizer": False}
            report["teacher_load_seconds"] = time.perf_counter() - teacher_load_started
            report["distill"] = {"protocol": plan["protocol"], "lambda": plan["keep_lambda"],
                                 "mode": plan["distill"],
                                 "units_per_update": plan["training_model_units_per_update"]}
            guard(force=True)
            persist()
        if relabel_fit and not action_preservation_fit:
            stage("m2l_paired_cells")
            reference = SharedSymbolPredictor(config.model, key=mx.random.key(999))
            reference.update(
                tree_unflatten(
                    [
                        (k[6:], mx.array(v))
                        for k, v in relabel["m2l_tensors"].items()
                        if k.startswith("model.")
                    ]
                )
            )
            reference.freeze()
            mx.eval(reference.parameters())
            loaded = {f"model.{k}": np.array(v) for k, v in tree_flatten(reference.parameters())}
            if set(loaded) != {k for k in relabel["m2l_tensors"] if k.startswith("model.")} or any(
                not np.array_equal(v, relabel["m2l_tensors"][k]) for k, v in loaded.items()
            ):
                raise RuntimeError("frozen M2l comparison weights did not load exactly")
            m2l_paired = evaluate_paired_memory(
                reference,
                episodes,
                before_work=reserve,
                cell_outputs=True,
                **plan["paired_evaluation"],
            )
            completed_units += m2l_paired["logical_model_transitions"]
            m2l_cells = m2l_paired.pop("per_query_cells")
            report["m2l_paired_reproduction"] = _compare_m2l_paired(
                m2l_paired, relabel["m2l_report"]["paired"]
            )
            guard(force=True)
            persist()
            stage("m2l_relabel_pool")
            scored = evaluate_zero_context_inputs(
                reference, relabel["batch"], relabel["seeds"], before_work=reserve
            )
            completed_units += scored["logical_model_transitions"]
            report["relabel_pool"]["m2l"] = summarize_relabel_pool(
                scored["argmax"], scored["nll"], relabel["batch"]
            )
            report["relabel_pool"]["m2l_cells"] = {
                "argmax": scored["argmax"].tolist(),
                "nll": [[None if np.isnan(v) else float(v) for v in row] for row in scored["nll"]],
            }
            del reference
            guard(force=True)
            persist()
        evaluate_phase("before")
        if relabel_fit:
            report["before_matches_m2l"] = report["before"] == relabel["m2l_report"]["before"]
        if report["before"]["reconstruction"]["gate"]["status"] != "passed":
            raise RuntimeError("source current-observation reconstruction gate failed")
        evaluate_local(0)
        window_rng = (
            np.random.default_rng(plan["seeds"]["windows"])
            if action_preservation_history or action_preservation_mixed or not local_fit
            else None
        )
        history_augmentation_rng = (
            np.random.default_rng(plan["seeds"]["mixed_history_augmentation"])
            if action_preservation_mixed
            else None
        )
        augmentation_rng = (
            np.random.default_rng(plan["seeds"]["augmentation"])
            if relabel_fit or not local_fit
            else None
        )
        key = mx.random.key(plan["seeds"]["latent"])
        if action_preservation_distill:
            distill_teacher = teacher
            distill_lambda = plan["keep_lambda"]

            def distill_objective(student, data, *, burn_in, key, truncate_each_step=False):
                return apm.memory_distill_sequence_loss(
                    student, distill_teacher, data, burn_in=burn_in, key=key, lam=distill_lambda,
                    truncate_each_step=truncate_each_step,
                )

            value_grad = nn.value_and_grad(model, distill_objective)
            report["distill_first_update"] = None
        else:
            value_grad = nn.value_and_grad(model, memory_sequence_loss)
        if action_preservation_fit and not action_preservation_distill:
            keep_grad = nn.value_and_grad(model, apm.keep_row_loss)

            def keep_update(index, memory_sum, memory_targets):
                tree, details, _ = _keep_update(
                    model, keep_grad, keep, cache_arrays, keep_windows, index, memory_sum,
                    memory_targets, guard, keep_lambda=plan["keep_lambda"],
                )
                if index == 0:
                    try:
                        first = apc.check_first_update_keep_loss(details["keep_row_losses"])
                    except ValueError as exc:
                        persist()
                        raise RuntimeError(f"first-update keep-loss guard failed: {exc}") from exc
                    report["keep_loss_first_update"] = first
                return tree, details

        store.transition(run_id, "training")
        for index in range(plan["updates"]):
            stage(
                "training_update",
                updates=1,
                units=plan["training_model_units_per_update"]
                + (keep["student_units"][index]
                   if action_preservation_fit and not action_preservation_distill else 0),
            )
            tick = time.perf_counter()
            permutation_digests = None
            if action_preservation_mixed:
                from ainerzero.learning.relabel_memory import relabel_batch

                pool_batch = get_diverse_batch(diverse_pool, index)
                relabelled, permutation_digests = relabel_batch(pool_batch, augmentation_rng)
                registered = relabel["training_manifest"]["digests"][
                    index * plan["batch_size"] : (index + 1) * plan["batch_size"]
                ]
                if permutation_digests != registered:
                    raise RuntimeError("training bijections differ from the registered manifest")
                single_batch = {
                    name: values[: plan["single_edge_rows"]]
                    for name, values in relabelled.items()
                }
                history_batch = permute_symbols(
                    sampler.sample(plan["history_rows"], window_rng), history_augmentation_rng
                )
                window_digests = [
                    hashlib.sha256(
                        history_batch["symbols"].tobytes() + history_batch["actions"].tobytes()
                    ).hexdigest()
                ]
                bijection_digests = list(permutation_digests[: plan["single_edge_rows"]])
                sample_key = key
            elif action_preservation_history:
                batch = permute_symbols(
                    sampler.sample(plan["batch_size"], window_rng), augmentation_rng
                )
                permutation_digests = None
                sample_key = key
                _ = get_diverse_batch  # registered pool stays available for the closure
            elif local_fit:
                batch = get_diverse_batch(diverse_pool, index) if diverse_fit else fixed_batch
                if relabel_fit:
                    from ainerzero.learning.relabel_memory import relabel_batch

                    batch, permutation_digests = relabel_batch(batch, augmentation_rng)
                    registered = relabel["training_manifest"]["digests"][
                        index * plan["batch_size"] : (index + 1) * plan["batch_size"]
                    ]
                    if permutation_digests != registered:
                        raise RuntimeError(
                            "training bijections differ from the registered manifest"
                        )
                sample_key = key  # Fixed training noise is part of the local-fit diagnostic.
            else:
                batch = permute_symbols(
                    sampler.sample(plan["batch_size"], window_rng), augmentation_rng
                )
                key, sample_key = mx.random.split(key)
            micro = plan["micro_batch_size"]
            parts_count = plan["batch_size"] // micro
            keys = mx.random.split(sample_key, parts_count)
            gradients, total, target_count = None, 0.0, 0.0
            distill_kls = []
            mixed_details = None
            if action_preservation_mixed:
                # Two halves, accumulated separately: the single-edge half keeps the
                # registered front-row invariant, and each half is a per-target mean
                # combined by its registered row weight (12:4).
                halves = (
                    ("single_edge", single_batch, plan["burn_in"], plan["single_edge_rows"], 3),
                    ("history", history_batch, plan["history_burn_in"], plan["history_rows"], 1),
                )
                # lambda_h (M2n-M2) scales the history half's CE+KL and gradient; the
                # E24 mixed condition is lambda_h = 1. Denominator stays the 16 rows.
                history_weight = plan["history_weight"] if action_preservation_mixed_weight025 else 1.0
                if action_preservation_mixed_weight0_control:
                    history_weight = plan["history_weight"]
                row_weights = {"single_edge": float(plan["single_edge_rows"]),
                               "history": float(plan["history_rows"])}
                if action_preservation_mixed_weight0_control:
                    # lambda_h = 0 is only allowed through the explicit control-protocol entry.
                    weights, total_weight = apc.mixed_weight0_half_weights(
                        plan["single_edge_rows"], plan["history_rows"]
                    )
                else:
                    weights, total_weight = apc.mixed_half_weights(
                        plan["single_edge_rows"], plan["history_rows"], history_weight
                    )
                half_grads, mixed_details = {}, {}
                # M2n-M4: only the history half's backward pass is truncated to one
                # transition per loss step; the single-edge half keeps its registered
                # two-frame backward pass and the teacher path is unchanged.
                truncate_history = bool(action_preservation_mixed_onestep
                                        and plan.get("truncate_each_step", False))
                for name, half, burn_in, rows, parts in halves:
                    h_grads, h_loss, h_targets, h_kls = None, 0.0, 0.0, []
                    for part in range(parts):
                        data = {
                            k: mx.array(v[part * micro : (part + 1) * micro])
                            for k, v in half.items()
                        }
                        (loss, metrics), grads = value_grad(
                            model, data, burn_in=burn_in, key=keys[part],
                            truncate_each_step=(truncate_history and name == "history"),
                        )
                        mx.eval(loss, metrics, grads)
                        h_kls.append(float(np.array(metrics["distill_kl"])))
                        visible = float(metrics["visible_targets"].item())
                        h_targets += visible
                        h_loss += float(loss.item()) * visible
                        scaled = tree_map(lambda g: g * visible, grads)
                        h_grads = (
                            scaled
                            if h_grads is None
                            else tree_map(lambda a, b: a + b, h_grads, scaled)
                        )
                        mx.eval(h_grads)
                        guard()
                    if h_targets <= 0:
                        raise RuntimeError(f"mixed {name} half has no supervised visible targets")
                    mean_grads = tree_map(lambda g: g / h_targets, h_grads)
                    masked = mask_gru_tail_gradients(mean_grads)
                    half_front = float(
                        np.sqrt(
                            sum(
                                np.sum((np.asarray(a) - np.asarray(b)) ** 2, dtype=np.float64)
                                for (_, a), (_, b) in zip(
                                    tree_flatten(mean_grads), tree_flatten(masked)
                                )
                            )
                        )
                    )
                    if not np.isfinite(half_front):
                        raise RuntimeError(f"mixed {name} front-output gradient is not finite")
                    if name == "single_edge" and half_front > 1e-8:
                        raise RuntimeError(
                            "single-edge memory unexpectedly has front-output gradients"
                        )
                    half_grads[name] = masked
                    mixed_details[name] = {
                        "rows": rows,
                        "targets": h_targets,
                        "ce": h_loss / h_targets - plan["keep_lambda"] * float(np.mean(h_kls)),
                        "kl": float(np.mean(h_kls)),
                        "front_row_gradient_l2": half_front,
                        "gradient_l2": float(
                            np.sqrt(
                                sum(
                                    np.sum(np.asarray(v) ** 2, dtype=np.float64)
                                    for _, v in tree_flatten(masked)
                                )
                            )
                        ),
                    }
                    distill_kls.extend(h_kls)
                if (action_preservation_mixed_weight025 or action_preservation_mixed_weight0_control
                        or action_preservation_mixed_onestep):
                    mixed_details["history_weight"] = history_weight
                    mixed_details["gradient_shares"] = apc.mixed_gradient_shares(
                        {n: {k: np.asarray(v) for k, v in tree_flatten(g)}
                         for n, g in half_grads.items()},
                        row_weights,
                        weights,
                    )
                if action_preservation_mixed_onestep:
                    mixed_details["truncate_each_step"] = {
                        "history": truncate_history,
                        "single_edge": False,
                        "scope": "history_half_backward_one_transition_per_loss_step",
                    }
                if action_preservation_mixed_weight0_control:
                    scaled_history_l2 = float(
                        np.sqrt(
                            sum(
                                np.sum((np.asarray(v) * weights["history"]) ** 2, dtype=np.float64)
                                for _, v in tree_flatten(half_grads["history"])
                            )
                        )
                    )
                    if scaled_history_l2 != 0.0:
                        raise RuntimeError("scaled history gradient must be strictly 0")
                if action_preservation_mixed_tailself_halfproj:
                    # M2n-M6: one-sided projection of the history half off the
                    # single-edge half, before the unchanged 12:4 merge.
                    from ainerzero.learning.halfproj import project_history_half

                    new_history, projection = project_history_half(
                        {"gru": {k.removeprefix("gru."): np.asarray(v)
                                 for k, v in tree_flatten(half_grads["history"])}},
                        {"gru": {k.removeprefix("gru."): np.asarray(v)
                                 for k, v in tree_flatten(half_grads["single_edge"])}},
                    )
                    if projection["projected"]:
                        half_grads["history"] = {
                            "gru": {k: mx.array(v) for k, v in new_history["gru"].items()}
                        }
                    mixed_details["half_projection"] = projection
                gradients = apc.combine_mixed_halves(half_grads, weights, total_weight, tree_map)
                total = sum(
                    weights[name] * (details["ce"] + plan["keep_lambda"] * details["kl"])
                    for name, details in mixed_details.items()
                    if name in weights
                ) / total_weight
                target_count = float(
                    sum(mixed_details[name]["targets"] for name in weights)
                )
                raw_front_gradient_l2 = mixed_details["single_edge"]["front_row_gradient_l2"]
            else:
                for part in range(parts_count):
                    data = {k: mx.array(v[part * micro : (part + 1) * micro]) for k, v in batch.items()}
                    (loss, metrics), grads = value_grad(
                        model, data, burn_in=plan["burn_in"], key=keys[part]
                    )
                    mx.eval(loss, metrics, grads)
                    if action_preservation_distill:
                        distill_kls.append(float(np.array(metrics["distill_kl"])))
                    visible = float(metrics["visible_targets"].item())
                    target_count += visible
                    total += float(loss.item()) * visible
                    scaled = tree_map(lambda g: g * visible, grads)
                    gradients = (
                        scaled
                        if gradients is None
                        else tree_map(lambda a, b: a + b, gradients, scaled)
                    )
                    mx.eval(gradients)
                    guard()
            if target_count <= 0:
                raise RuntimeError("memory training batch has no supervised visible targets")
            memory_sum = gradients
            if not action_preservation_mixed:
                # the mixed branch already combined per-target means by row weight
                gradients = tree_map(lambda g: g / target_count, gradients)
                total /= target_count
            flat_grad = dict(tree_flatten(gradients))
            if (
                set(flat_grad) != set(trainable)
                or not np.isfinite(total)
                or not all(np.isfinite(np.asarray(v)).all() for v in flat_grad.values())
            ):
                raise RuntimeError("memory gradient scope or finite check failed")
            raw_front_gradient_l2 = None
            if local_fit and not action_preservation_mixed:
                masked = mask_gru_tail_gradients(gradients)
                raw_front_gradient_l2 = float(
                    np.sqrt(
                        sum(
                            np.sum(
                                (np.asarray(flat_grad[k]) - np.asarray(v)) ** 2, dtype=np.float64
                            )
                            for k, v in tree_flatten(masked)
                        )
                    )
                )
                if not np.isfinite(raw_front_gradient_l2):
                    raise RuntimeError("memory front-output gradient is not finite")
                # The registered single-edge formulations (M2m-d / C07 / D / probe)
                # have no path from the loss to the GRU front rows, so a nonzero
                # magnitude there means the wiring changed. Multi-step history
                # windows (M2n) reach the front rows through earlier steps, so the
                # invariant is scoped to the registered single-edge formulation and
                # the magnitude is recorded instead. The applied gradient is masked
                # in both cases, so the trainable scope stays tail-only.
                if plan["transitions_per_window"] == 1 and raw_front_gradient_l2 > 1e-8:
                    raise RuntimeError("single-edge memory unexpectedly has front-output gradients")
                gradients = masked
            keep_details = None
            if action_preservation_distill:
                if index == 0:
                    try:
                        first = apc.check_first_update_keep_loss(distill_kls)
                    except ValueError as exc:
                        persist()
                        raise RuntimeError(f"first-update distillation guard failed: {exc}") from exc
                    report["distill_first_update"] = first
            elif action_preservation_fit:
                gradients, keep_details = keep_update(index, memory_sum, target_count)
            tailself_guard = None
            if action_preservation_mixed_tailself:
                # M2n-M5: mask the Wh tail-self block (and front rows) before clipping.
                tailself_raw = {k.removeprefix("gru."): np.asarray(v) for k, v in tree_flatten(gradients)}
                gradients = mask_tailself_gradients(gradients)
            gradients, norm = optim.clip_grad_norm(gradients, config.training.gradient_clip_norm)
            if action_preservation_mixed_tailself:
                mx.eval(gradients, norm)
                # Guard the gradient actually handed to AdamW over all frozen GRU elements.
                tailself_guard = check_applied_frozen_gradient(
                    tailself_raw,
                    {k.removeprefix("gru."): np.asarray(v) for k, v in tree_flatten(gradients)},
                )
            if action_preservation_fit:
                mx.eval(gradients, norm)
                for name, value in tree_flatten(gradients):
                    leaf = name.removeprefix("gru.")
                    if np.any(np.asarray(value)[ap.frozen_row_mask(leaf)] != 0):
                        raise RuntimeError("clipped gradient has nonzero frozen rows")
            params_before = [np.array(v) for _, v in tree_flatten(model.parameters())] if action_preservation_mixed else None
            optimizer.update(model, gradients)
            if local_fit and action_preservation_mixed_tailself:
                # AdamW weight decay also moves the masked block: restore front rows + block.
                project_tailself(model, source_tensors)
            elif local_fit:
                # Gradient masking alone does not stop AdamW's front-row weight decay.
                project_gru_front(model, source_tensors)
            mx.eval(model.parameters(), optimizer.state, norm, key)
            adamw_update_l2 = None
            if params_before is not None:
                params_after = [np.array(v) for _, v in tree_flatten(model.parameters())]
                adamw_update_l2 = float(
                    np.sqrt(
                        sum(
                            np.sum((b - a) ** 2, dtype=np.float64)
                            for a, b in zip(params_before, params_after)
                        )
                    )
                )
            report["actual_optimizer_steps"] += 1
            report["training_model_transitions"] += plan["training_model_units_per_update"] + (
                keep["student_units"][index]
                if action_preservation_fit and not action_preservation_distill else 0
            )
            if local_fit:
                report["latest_tail_protection"] = (
                    verify_tailself_update if action_preservation_mixed_tailself else verify_tail_update
                )(
                    source_tensors,
                    {f"model.{k}": np.array(v) for k, v in tree_flatten(model.parameters())},
                )
                report["tail_protection_checks"] += 1
                if tailself_guard is not None:
                    report["latest_tailself_gradient_guard"] = tailself_guard
            elapsed = time.perf_counter() - tick
            entry = {
                "update": index + 1,
                "loss": total,
                "gradient_norm": float(norm.item()),
                "compute_seconds": elapsed,
            }
            if local_fit:
                entry.update(
                    raw_front_gradient_l2=raw_front_gradient_l2, frozen_parameters_verified=True
                )
            if diverse_fit and not action_preservation_mixed:
                entry["training_sample_rows"] = diverse_training_schedule()[index].tolist()
            if action_preservation_mixed:
                entry["training_sample_rows"] = {
                    "single_edge_rows": diverse_training_schedule()[index][
                        : plan["single_edge_rows"]
                    ].tolist(),
                    "history_windows": {
                        "count": plan["history_rows"],
                        "form": "sampler_uniform_windows_public_train_partition",
                        "sampler_burn_in": plan["sampler_geometry"]["burn_in"],
                        "sampler_sequence_steps": plan["sampler_geometry"]["sequence_steps"],
                        "window_sha256": window_digests,
                    },
                    "unused_schedule_rows": diverse_training_schedule()[index][
                        plan["single_edge_rows"] :
                    ].tolist(),
                    "bijection_digests": bijection_digests,
                }
                if adamw_update_l2 is not None:
                    mixed_details["adamw_update_l2"] = adamw_update_l2
                    entry["adamw_update_l2"] = adamw_update_l2
                entry["mixed"] = mixed_details
            if relabel_fit and not action_preservation_history:
                entry["permutation_sha256"] = permutation_digests
            if action_preservation_distill:
                entry.update(memory_loss=total, distill_kl=float(np.mean(distill_kls)),
                             keep_lambda=plan["keep_lambda"], distill_mode=plan["distill"])
            elif action_preservation_fit:
                # `keep_details` now carries the combined guard values under
                # `combined_*`, so the memory-branch-only `raw_front_gradient_l2`
                # set above keeps its original meaning (E16 finding A1).
                # `keep_details` already carries `keep_lambda`; adding it as an
                # explicit keyword here would raise "multiple values for keyword
                # argument" (C07 review finding F1, HIGH).
                entry.update(memory_loss=total, **keep_details)
            with (directory / "updates.jsonl").open("a") as stream:
                stream.write(json.dumps(entry, allow_nan=False) + "\n")
            report["latest_update"] = entry
            guard(force=True)
            # Duty-cycle idle is not active compute; whole-run deadline still applies.
            stage_started = None
            persist()
            rest = elapsed * (1 / config.resources.active.training_duty_cycle - 1)
            idle_until = time.monotonic() + rest
            while time.monotonic() < idle_until:
                time.sleep(min(1.0, max(0.0, idle_until - time.monotonic())))
                guard()
            if local_fit and index + 1 in plan["local_checks"]:
                evaluate_local(index + 1)
        if action_preservation_distill:
            del teacher, distill_teacher
        store.transition(run_id, "validating")
        if diverse_fit:
            model.freeze()
            if tree_flatten(model.trainable_parameters()):
                raise RuntimeError("diverse candidate must be frozen for final evaluations")
        evaluate_phase("after")
        report["memory_screen"] = memory_screen(report["after"]["memory_development"], plan)
        if local_fit:
            report["local_screens"] = {
                name: local_memory_screen(result, plan)
                for name, result in report["local_checks"][str(plan["updates"])].items()
            }
        if diverse_fit:
            stage("after_paired")
            report["paired"] = evaluate_paired_memory(
                model,
                episodes,
                before_work=reserve,
                **plan["paired_evaluation"],
                **({"cell_outputs": True} if relabel_fit else {}),
            )
            completed_units += report["paired"]["logical_model_transitions"]
            m2m_cells = report["paired"].pop("per_query_cells", None)
            if report["paired"]["query_manifest_sha256"] != queries["query_manifest_sha256"]:
                raise RuntimeError("diverse paired query identities changed after registration")
            report["diverse_groups"] = summarize_diverse_pairs(report["paired"], training_evidence)
            guard(force=True)
            persist()
        if relabel_fit:
            from ainerzero.learning.relabel_memory import (
                compare_strata,
                next_step,
                regression_flags,
                transfer_level,
            )

            if [
                report["paired"]["per_query"][row]["paired_random_seeds"]
                for row in relabel["pool_query_rows"]
            ] != relabel["seeds"]:
                raise RuntimeError("relabel pool keys differ from the paired pool-row keys")
            stage("after_relabel_pool")
            scored = evaluate_zero_context_inputs(
                model, relabel["batch"], relabel["seeds"], before_work=reserve
            )
            completed_units += scored["logical_model_transitions"]
            report["relabel_pool"]["m2m"] = summarize_relabel_pool(
                scored["argmax"], scored["nll"], relabel["batch"]
            )
            report["relabel_pool"]["m2m_cells"] = {
                "argmax": scored["argmax"].tolist(),
                "nll": [[None if np.isnan(v) else float(v) for v in row] for row in scored["nll"]],
            }
            report["cells"] = {"m2m": m2m_cells, "m2l": m2l_cells}
            report["stratified"] = compare_strata(
                relabel["classification"],
                relabel["labels"],
                relabel["targets"],
                m2m_cells,
                m2l_cells,
            )
            report["regression"] = regression_flags(report["before"], report["after"])
            development = report["paired"]["groups"]["development"]["methods"]["zero_context_tail"]
            report["transfer"] = next_step(
                all(item["status"] == "passed" for item in report["local_screens"].values()),
                transfer_level(development),
                transfer_level(report["relabel_pool"]["m2m"]),
                report["regression"]["regression"],
            )
            if action_preservation_fit:
                report["preservation_screen"] = apc.preservation_screen(
                    report["before"], report["after"], report["paired"], report["relabel_pool"]["m2m"]
                )
            guard(force=True)
            persist()

        stage("checkpoint")
        saved = {f"model.{k}": np.array(v) for k, v in tree_flatten(model.parameters())}
        saved.update({f"optimizer.{k}": np.array(v) for k, v in tree_flatten(optimizer.state)})
        saved["rng.mlx_key"] = np.array(key)
        checkpoint = save_checkpoint(
            directory / "checkpoints",
            run_id,
            saved,
            {
                "architecture": "pilot_shared_symbol_v1",
                "phase": phase_name,
                "config": config.model_dump(mode="json"),
                "plan": plan,
                "dataset_source": identity,
                "run_id": run_id,
                "manifest_hash": experiment.manifest_hash,
                "optimizer_steps": report["actual_optimizer_steps"],
                "source": source,
                "rng_states": {
                    "fixed_seed": plan["seeds"]["latent"],
                    "augmentation": augmentation_rng.bit_generator.state,
                }
                if relabel_fit and not action_preservation_history and not action_preservation_mixed
                else {
                    "windows": window_rng.bit_generator.state,
                    "augmentation": augmentation_rng.bit_generator.state,
                    "history_augmentation": (
                        history_augmentation_rng.bit_generator.state
                        if history_augmentation_rng is not None
                        else None
                    ),
                }
                if action_preservation_mixed
                else {
                    "windows": window_rng.bit_generator.state,
                    "augmentation": augmentation_rng.bit_generator.state,
                }
                if action_preservation_history
                else {"fixed_seed": plan["seeds"]["latent"]}
                if local_fit
                else {
                    "windows": window_rng.bit_generator.state,
                    "augmentation": augmentation_rng.bit_generator.state,
                },
                "fixed_samples": sample_evidence,
                **({"training_samples": training_evidence} if diverse_fit else {}),
                **(
                    {
                        "relabel_training_permutations_sha256": relabel["training_manifest"][
                            "manifest_sha256"
                        ]
                    }
                    if relabel_fit
                    else {}
                ),
                **(
                    {
                        "action_preservation": {
                            **keep["summary"],
                            "teacher_cache": report["teacher_cache"],
                            "preservation_screen": report["preservation_screen"],
                            "promoted": False,
                        }
                    }
                    if action_preservation_fit
                    else {}
                ),
                "sampler": {"burn_in": plan["burn_in"], "sequence_steps": plan["sequence_steps"]},
                "readout_protocol": plan["readout"],
                "optimizer": {
                    "kind": "AdamW",
                    "learning_rate": plan["learning_rate"],
                    "betas": list(config.training.adam_betas),
                    "eps": config.training.adam_epsilon,
                    "weight_decay": config.training.weight_decay,
                    "bias_correction": True,
                },
                "state_scope": "offline_windows_start_zero_no_persistent_session; cross_process_training_resume_not_verified",
            },
        )
        restored, metadata = load_checkpoint(checkpoint)
        report["checkpoint"] = str(checkpoint.resolve())
        report["checkpoint_verified"] = (
            set(saved) == set(restored)
            and all(np.array_equal(v, restored[k]) for k, v in saved.items())
            and metadata["optimizer_steps"] == plan["updates"]
        )
        if not report["checkpoint_verified"]:
            raise RuntimeError("memory checkpoint roundtrip failed")
        guard(force=True)
        stage("verification")
        changed = [
            k
            for k, v in saved.items()
            if k.startswith("model.") and not np.array_equal(v, source_tensors[k])
        ]
        report["changed_model_tensors"] = sorted(changed)
        report["frozen_modules_unchanged"] = all(k.startswith("model.gru.") for k in changed)
        report["logical_model_transitions"] = completed_units + report["training_model_transitions"]
        if report["logical_model_transitions"] != reserved_units:
            raise RuntimeError("memory measured work differs from reserved model units")
        if local_fit:
            report["tail_protection"] = (
                verify_tailself_update if action_preservation_mixed_tailself else verify_tail_update
            )(source_tensors, saved)
            if report["logical_model_transitions"] != plan["expected_total_model_units"]:
                raise RuntimeError("micro memory model units differ from fixed plan")
        if diverse_fit:
            load_checkpoint(checkpoint_path)  # Revalidate source weights against their manifest.
            report["source_files_unchanged"] = (
                comparison_report_path.read_bytes() == comparison_bytes
                and hashlib.sha256((checkpoint_path / "manifest.json").read_bytes()).hexdigest()
                == source["checkpoint_manifest_sha256"]
            )
            if relabel_fit:
                load_checkpoint(m2l_checkpoint_path)
                report["source_files_unchanged"] = report["source_files_unchanged"] and (
                    m2l_report_path.read_bytes() == relabel["m2l_report_bytes"]
                    and hashlib.sha256(
                        (m2l_checkpoint_path / "manifest.json").read_bytes()
                    ).hexdigest()
                    == relabel["m2l_candidate"]["checkpoint_manifest_sha256"]
                    and relabel["pool_path"].read_bytes() == relabel["pool_bytes"]
                )
            if action_preservation_fit:
                report["source_files_unchanged"] = (
                    report["source_files_unchanged"]
                    and m2mc_report_path.read_bytes() == keep["reuse"]["m2mc_report_bytes"]
                )
                if not action_preservation_distill:  # no cache file under D (finding F2)
                    report["source_files_unchanged"] = (
                        report["source_files_unchanged"]
                        and hashlib.sha256(cache_path.read_bytes()).hexdigest() == cache_file["sha256"]
                        and cache_path.stat().st_size == cache_file["size"]
                    )
            if not report["source_files_unchanged"]:
                raise RuntimeError("diverse source checkpoint or comparison report changed")
        report["mlx_peak_bytes"] = mx.get_peak_memory()
        if not report["frozen_modules_unchanged"] or not changed:
            raise RuntimeError("memory training changed wrong tensors or did not update GRU")
        if report["after"]["reconstruction"]["gate"]["status"] != "passed":
            raise RuntimeError("memory candidate failed reconstruction regression gate")
        guard(force=True)
        store.transition(
            run_id, "completed", reason=f"{phase_name}_experiment_complete_no_promotion"
        )
        report.update(status="completed", current_stage="completed")
    except BaseException as exc:
        report.update(status="failed", error=f"{type(exc).__name__}: {exc}")
        if run_id is not None and store.get_run(run_id).state not in TERMINAL_STATES:
            store.transition(run_id, "failed", reason=f"{phase_name}_failure")
    finally:
        report["reserved_model_transitions"] = reserved_units
        if run_id is not None:
            report["run"] = store.get_run(run_id).to_dict()
        store.close()
        persist()
    return report


PROBE_PROTOCOL = "m2m_d_action_preservation_c06a_probe_v1"
PROBE_UPDATES = 3
PROBE_STUDENT_UNITS = (139, 138, 144)


def action_preservation_probe_plan():
    """C06a bounded probe: two teacher caches + 3 full updates, no evaluations/checkpoint."""
    from ainerzero.learning import action_preservation as ap

    plan = action_preservation_memory_plan()
    plan.update(
        protocol=PROBE_PROTOCOL,
        production_protocol=ap.PROTOCOL,
        updates=PROBE_UPDATES,
        local_checks=[],
        resource_seconds={
            "compatibility": 15,
            "initialization": 15,
            "teacher_cache": 60,
            "cache_protocol_checks": 10,
            "teacher_repeat": 60,
            "training_update": 3,
            "verification": 10,
        },
        student_model_units_per_update=list(PROBE_STUDENT_UNITS),
        expected_total_model_units=2 * ap.TEACHER_UNITS
        + PROBE_UPDATES * plan["training_model_units_per_update"]
        + sum(PROBE_STUDENT_UNITS),
        total_reserved_seconds_if_complete=179,
        supervised_deadline_seconds=229,
        supervisor_deadline_seconds=279,
        evaluations="none_no_before_after_local_paired_or_relabel_pool",
        checkpoint="not_saved_parameter_sha_only_probe_weights_never_a_start",
        first_update_invariant="recorded_not_stopping",
        first_update_bound=plan["first_update_keep_loss_max"],
        promotion=False,
    )
    del plan["m2l_baselines"]
    seconds = plan["resource_seconds"]
    total = sum(v * (PROBE_UPDATES if k == "training_update" else 1) for k, v in seconds.items())
    if total != 179 or plan["expected_total_model_units"] != 5025:
        raise RuntimeError("probe plan totals differ from registration (5025 units / 179 s)")
    return plan


class _LogitRecorder:
    """Delegates to the student; records each imagine's symbol logits (no extra model calls)."""

    def __init__(self, model):
        self._model, self.symbols = model, []

    def observe(self, *args, **kwargs):
        return self._model.observe(*args, **kwargs)

    def imagine(self, *args, **kwargs):
        out = self._model.imagine(*args, **kwargs)
        self.symbols.append(out["logits"]["symbols"][0])
        return out


def _probe_keep_loss(model, cached_row, window, row_keys):
    import mlx.core as mx

    from ainerzero.learning import action_preservation_mlx as apm

    recorder = _LogitRecorder(model)
    loss, horizons = apm.keep_row_loss(recorder, cached_row, window, row_keys)
    query = recorder.symbols[-4:]
    return loss, (horizons, mx.stack([query[0], query[3]]))


def _array_sha(arrays) -> str:
    digest = hashlib.sha256()
    for name in sorted(arrays):
        value = np.ascontiguousarray(arrays[name])
        digest.update(name.encode() + str(value.dtype).encode() + str(value.shape).encode())
        digest.update(value.tobytes())
    return digest.hexdigest()


def run_action_preservation_probe(
    config_path,
    dataset_path,
    checkpoint_path,
    output_root,
    control_db,
    experiment_id,
    *,
    comparison_report_path,
    m2l_report_path,
    m2l_checkpoint_path,
    m2mc_report_path,
):
    """C06a numerical/resource probe through the shared lock, ledger and guards."""
    from ainerzero.cli import pilot_manifest
    from ainerzero.learning import action_preservation as ap
    from ainerzero.learning import action_preservation_closure as apc
    from ainerzero.learning.diverse_memory import (
        diverse_training_schedule,
        get_diverse_batch,
        select_diverse_memory_samples,
    )
    from ainerzero.learning.micro_memory import select_micro_memory_samples
    from ainerzero.learning.paired_memory import paired_memory_samples
    from ainerzero.learning.relabel_memory import relabel_batch

    started = time.perf_counter()
    if any(
        p is None
        for p in (comparison_report_path, m2l_report_path, m2l_checkpoint_path, m2mc_report_path)
    ):
        raise ValueError("probe requires the same six input paths as the training entry")
    config = load_pilot_config(config_path)
    plan = action_preservation_probe_plan()
    policy = TrainingPolicy(allowed_actors=(RANDOM_ACTOR,))
    paths, episodes, identity = load_pilot_dataset(dataset_path, policy)
    source_tensors, source_metadata = load_checkpoint(checkpoint_path)
    validate_history_source(source_metadata, config.model_dump(mode="json"), identity)
    _, sample_evidence = select_micro_memory_samples(episodes["train"])
    source = {
        "checkpoint": str(checkpoint_path.resolve()),
        "parent_run_id": source_metadata["run_id"],
        "checkpoint_manifest_sha256": hashlib.sha256(
            (checkpoint_path / "manifest.json").read_bytes()
        ).hexdigest(),
        "dataset": identity,
    }
    diverse_pool, training_evidence = select_diverse_memory_samples(episodes["train"])
    queries = paired_memory_samples(episodes)
    comparison_bytes = comparison_report_path.read_bytes()
    comparison = json.loads(comparison_bytes)
    validate_diverse_comparison(comparison, source=source, identity=identity, queries=queries)
    relabel = _prepare_relabel(
        config, episodes, identity, source, source_metadata, sample_evidence, diverse_pool,
        training_evidence, queries, m2l_report_path, m2l_checkpoint_path,
    )
    keep = apc.production_windows(
        training_evidence["samples"],
        diverse_training_schedule(),
        apc.public_records_from_episodes(episodes["train"]),
    )
    if tuple(keep["student_units"][:PROBE_UPDATES]) != PROBE_STUDENT_UNITS:
        raise ValueError("probe student units differ from the registered 139/138/144")
    with RunStore(control_db) as closure_store:
        reuse = apc.m2l_reuse_closure(m2mc_report_path, relabel, closure_store, episodes=episodes)
    summary = {
        "protocol": plan["protocol"],
        "windows_sha256": keep["windows"]["windows_sha256"],
        "key_manifest_sha256": keep["keys"]["manifest_sha256"],
        "keys_sha256": keep["keys"]["keys_sha256"],
        "student_units": list(PROBE_STUDENT_UNITS),
        "m2l_reuse": reuse["evidence"],
    }
    declaration = pilot_manifest(config_path)["manifest"]
    declaration.update(
        purpose="c0_action_preservation_c06a_probe_v1",
        one_step_memory=plan,
        source=declaration["source"],
        student_source=source,
        training_samples=training_evidence,
        relabel=relabel["declaration"],
        action_preservation=summary,
    )
    directory = Path(output_root) / f"pilot-{uuid4().hex}"
    directory.mkdir(parents=True)
    report_path = directory / "report.json"
    report = {
        "status": "running",
        "probe": True,
        "experiment_id": experiment_id,
        "plan": plan,
        "source": source,
        "dataset": str(dataset_path.resolve()),
        "action_preservation": summary,
        "actual_optimizer_steps": 0,
        "training_model_transitions": 0,
        "stage_seconds": [],
        "updates": [],
        "checkpoint_saved": False,
        "promoted": False,
        "run_directory": str(directory.resolve()),
        "report_path": str(report_path.resolve()),
    }
    store = RunStore(control_db)
    run_id = None
    stage_started = stage_seconds = stage_name = None
    last_guard = 0.0
    initial_swap = psutil.swap_memory().used
    completed_units = reserved_units = 0

    def persist():
        report["elapsed_seconds"] = time.perf_counter() - started
        atomic_write_json(report_path, report)

    def guard(force=False):
        nonlocal last_guard
        now = time.monotonic()
        if stage_started is not None and time.perf_counter() - stage_started > stage_seconds:
            raise RuntimeError(f"probe exceeded prepaid stage window ({stage_name})")
        if time.perf_counter() - started > plan["supervised_deadline_seconds"]:
            raise RuntimeError("probe reached supervised deadline")
        if not force and now - last_guard < 1:
            return
        last_guard = now
        if psutil.virtual_memory().available < config.resources.system_reserve_gib * 2**30:
            raise RuntimeError("probe system memory reserve reached")
        if psutil.Process().memory_info().rss > config.resources.active.project_memory_gib * 2**30:
            raise RuntimeError("probe process memory limit reached")
        if psutil.swap_memory().used - initial_swap > config.resources.swap_growth_gib * 2**30:
            raise RuntimeError("probe swap growth limit reached")
        if psutil.disk_usage(directory).free < config.resources.minimum_disk_free_gib * 2**30:
            raise RuntimeError("probe disk reserve reached")
        # User policy: battery power does not block registered model work.
    def close_stage():
        nonlocal stage_started
        if stage_started is not None:
            report["stage_seconds"].append(
                {"stage": stage_name, "seconds": time.perf_counter() - stage_started,
                 "window": stage_seconds}
            )
        stage_started = None

    def stage(name, *, updates=0, units=0):
        nonlocal stage_started, stage_seconds, stage_name, reserved_units
        close_stage()
        guard(force=True)
        stage_seconds = plan["resource_seconds"][name]
        store.consume(
            run_id, active_seconds=stage_seconds, optimizer_steps=updates, model_transitions=units
        )
        reserved_units += units
        stage_name, stage_started = name, time.perf_counter()
        report["current_stage"] = name
        persist()

    def reserve(count):
        nonlocal reserved_units
        guard()
        store.consume(run_id, model_transitions=count)
        reserved_units += count

    try:
        guard(force=True)
        prior = store.get_run(comparison["run_id"])
        prior_experiment = store.get_experiment(prior.experiment_id)
        if (
            prior.state != "completed"
            or prior.experiment_id != comparison.get("experiment_id")
            or prior.role != "auxiliary"
            or prior.reserved_optimizer_steps != 0
            or prior.reserved_model_transitions != 82176
            or prior_experiment.manifest_hash != comparison["manifest_hash"]
        ):
            raise ValueError("canonical ledger does not confirm M2k comparison")
        experiment = store.create_experiment(declaration, experiment_id, experiment_id)
        atomic_write_json(directory / "preregistration.json", declaration)
        run_id = str(uuid4())
        snapshot = config.snapshot_for_run(0)
        snapshot["one_step_memory"] = {"plan": plan, "source": source}
        store.create_run(snapshot, run_id, run_id=run_id, experiment_id=experiment_id, role="model")
        store.transition(run_id, "initializing")
        store.transition(run_id, "validating")
        report.update(run_id=run_id, manifest_hash=experiment.manifest_hash)
        stage("compatibility")
        report["codec_compatibility"] = audit_bounded_codec(
            source_tensors["model.byte_embedding.weight"],
            source_tensors["model.symbol_readout.weight"],
            source_tensors["model.symbol_readout.bias"],
        )
        if not report["codec_compatibility"]["bounded_codec_compatible"]:
            raise RuntimeError("bounded frozen codec compatibility check failed")

        stage("initialization")
        import mlx.core as mx
        import mlx.nn as nn
        import mlx.optimizers as optim
        from mlx.utils import tree_flatten, tree_map, tree_unflatten

        from ainerzero.learning import action_preservation_mlx as apm
        from ainerzero.learning.one_step_memory import memory_sequence_loss
        from ainerzero.learning.pilot_model import SharedSymbolPredictor
        from ainerzero.learning.tail_update import (
            mask_gru_tail_gradients,
            project_gru_front,
            verify_tail_update,
        )

        if not mx.metal.is_available():
            raise RuntimeError("Metal unavailable; no CPU fallback")
        mx.set_default_device(mx.gpu)
        mx.set_memory_limit(int(config.resources.active.mlx_memory_gib * 2**30))
        mx.set_cache_limit(int(config.resources.active.mlx_cache_gib * 2**30))
        mx.reset_peak_memory()

        def load_m2d():
            loaded = SharedSymbolPredictor(config.model, key=mx.random.key(999))
            loaded.update(
                tree_unflatten(
                    [(k[6:], mx.array(v)) for k, v in source_tensors.items() if k.startswith("model.")]
                )
            )
            return loaded

        model = load_m2d()
        model.freeze()
        model.gru.unfreeze()
        mx.eval(model.parameters())
        trainable = dict(tree_flatten(model.trainable_parameters()))
        if set(trainable) != {"gru.Wx", "gru.Wh", "gru.b", "gru.bhn"} or sum(
            v.size for _, v in tree_flatten(model.parameters())
        ) != 393232:
            raise RuntimeError("probe trainable scope or parameter count mismatch")
        verify_tail_update(
            source_tensors, {f"model.{k}": np.array(v) for k, v in tree_flatten(model.parameters())}
        )
        optimizer = optim.AdamW(
            learning_rate=plan["learning_rate"],
            betas=config.training.adam_betas,
            eps=config.training.adam_epsilon,
            weight_decay=config.training.weight_decay,
            bias_correction=True,
        )
        optimizer.init(model.trainable_parameters())
        mx.eval(optimizer.state)

        stage("teacher_cache")
        teacher = load_m2d()
        teacher.freeze()
        mx.eval(teacher.parameters())
        if any(
            not np.array_equal(np.array(v), source_tensors[f"model.{k}"])
            for k, v in tree_flatten(teacher.parameters())
        ) or tree_flatten(teacher.trainable_parameters()):
            raise RuntimeError("frozen M2d teacher did not load exactly")
        first_calls = keep["keys"]["teacher_online"][0]["keys"][:3]
        recorded = []
        for name, tick, offset, seed in first_calls:
            value = apm._key(seed)
            recorded.append({"call": name, "tick": tick, "offset": offset, "seed_u32": seed,
                             "shape": list(value.shape), "dtype": str(value.dtype),
                             "value": np.array(value).tolist()})
        report["mx_random_key_first_calls"] = recorded
        cache_arrays = apm.build_teacher_cache(
            teacher, episodes["train"], keep["windows"], keep["keys"], before_work=reserve
        )
        completed_units += ap.TEACHER_UNITS
        cache_binding = apc.expected_cache_binding(
            checkpoint_path=checkpoint_path, windows=keep["windows"], keys=keep["keys"], run_id=run_id
        )
        cache_manifest = ap.teacher_cache_manifest(cache_binding, cache_arrays)
        cache_path = directory / "probe-teacher-cache.npz"
        cache_manifest_path = directory / "probe-teacher-cache-manifest.json"
        if cache_path.exists() or cache_manifest_path.exists():
            raise RuntimeError("probe cache files must be new")
        np.savez(cache_path, **cache_arrays)
        cache_bytes = cache_path.read_bytes()
        cache_file = {
            "path": str(cache_path.resolve()),
            "size": len(cache_bytes),
            "sha256": hashlib.sha256(cache_bytes).hexdigest(),
        }
        atomic_write_json(cache_manifest_path, {**cache_manifest, "file": cache_file})
        guard(force=True)
        persist()

        stage("cache_protocol_checks")
        stored = json.loads(cache_manifest_path.read_text())
        reread = cache_path.read_bytes()
        if stored.pop("file") != cache_file or (
            len(reread), hashlib.sha256(reread).hexdigest()
        ) != (cache_file["size"], cache_file["sha256"]):
            raise RuntimeError("probe cache file identity changed")
        with np.load(cache_path) as loaded:
            cache_arrays = {name: loaded[name] for name in loaded.files}
        ap.verify_teacher_cache(
            stored, cache_arrays, cache_binding, apm.q_visible_mask(episodes["train"], keep["windows"])
        )
        keep_windows = apm.row_windows(episodes["train"], keep["windows"])
        report["teacher_cache"] = {
            "file": cache_file,
            "manifest_path": str(cache_manifest_path.resolve()),
            "manifest_sha256": cache_manifest["manifest_sha256"],
            "binding_run_id": run_id,
            "production_use": "rejected_by_design_run_id_is_the_probe_run",
        }
        persist()

        stage("teacher_repeat")
        repeat = apm.build_teacher_cache(
            teacher, episodes["train"], keep["windows"], keep["keys"], before_work=reserve
        )
        completed_units += ap.TEACHER_UNITS
        del teacher
        report["teacher_repeat"] = {
            name: {
                "bitwise_equal": bool(np.array_equal(cache_arrays[name], repeat[name])),
                "max_abs_diff": float(
                    np.max(np.abs(cache_arrays[name].astype(np.float64) - repeat[name].astype(np.float64)))
                ),
            }
            for name in ap.CACHE_ARRAYS
        }
        report["teacher_repeat_bitwise_equal"] = all(
            v["bitwise_equal"] for v in report["teacher_repeat"].values()
        )
        guard(force=True)
        persist()

        augmentation_rng = np.random.default_rng(plan["seeds"]["augmentation"])
        key = mx.random.key(plan["seeds"]["latent"])
        value_grad = nn.value_and_grad(model, memory_sequence_loss)
        keep_grad = nn.value_and_grad(model, _probe_keep_loss)
        store.transition(run_id, "training")
        for index in range(PROBE_UPDATES):
            stage(
                "training_update",
                updates=1,
                units=plan["training_model_units_per_update"] + keep["student_units"][index],
            )
            tick = time.perf_counter()
            batch, permutation_digests = relabel_batch(
                get_diverse_batch(diverse_pool, index), augmentation_rng
            )
            if permutation_digests != relabel["training_manifest"]["digests"][
                index * plan["batch_size"] : (index + 1) * plan["batch_size"]
            ]:
                raise RuntimeError("training bijections differ from the registered manifest")
            micro = plan["micro_batch_size"]
            parts_count = plan["batch_size"] // micro
            keys = mx.random.split(key, parts_count)
            gradients, total, target_count = None, 0.0, 0.0
            for part in range(parts_count):
                data = {k: mx.array(v[part * micro : (part + 1) * micro]) for k, v in batch.items()}
                (loss, metrics), grads = value_grad(
                    model, data, burn_in=plan["burn_in"], key=keys[part]
                )
                mx.eval(loss, metrics, grads)
                visible = float(metrics["visible_targets"].item())
                target_count += visible
                total += float(loss.item()) * visible
                scaled = tree_map(lambda g: g * visible, grads)
                gradients = (
                    scaled if gradients is None else tree_map(lambda a, b: a + b, gradients, scaled)
                )
                mx.eval(gradients)
                guard()
            if target_count <= 0:
                raise RuntimeError("probe memory batch has no supervised visible targets")
            memory_sum = gradients
            gradients = tree_map(lambda g: g / target_count, gradients)
            total /= target_count
            flat_grad = dict(tree_flatten(gradients))
            if set(flat_grad) != set(trainable) or not np.isfinite(total):
                raise RuntimeError("probe memory gradient scope or finite check failed")
            masked = mask_gru_tail_gradients(gradients)
            memory_front = float(
                np.sqrt(
                    sum(
                        np.sum((np.asarray(flat_grad[k]) - np.asarray(v)) ** 2, dtype=np.float64)
                        for k, v in tree_flatten(masked)
                    )
                )
            )
            if not np.isfinite(memory_front) or memory_front > 1e-8:
                raise RuntimeError("single-edge memory unexpectedly has front-output gradients")
            gradients, details, extras = _keep_update(
                model, keep_grad, keep, cache_arrays, keep_windows, index, memory_sum,
                target_count, guard, keep_lambda=plan["keep_lambda"],
            )
            if index == 0:
                rows = details["keep_rows"]
                losses = details["keep_row_losses"]
                report["first_update"] = {
                    "keep_row_losses": losses,
                    "max_keep_loss": max(losses),
                    "max_abs_keep_loss": max(abs(v) for v in losses),
                    "all_exact_zero": all(v == 0.0 for v in losses),
                    "registered_max_abs": apc.FIRST_UPDATE_KEEP_LOSS_MAX,
                    "within_registered_bound": max(abs(v) for v in losses)
                    <= apc.FIRST_UPDATE_KEEP_LOSS_MAX,
                    "student_teacher_logits_max_abs_diff": [
                        float(np.max(np.abs(e.astype(np.float64) - cache_arrays["teacher_logits"][r])))
                        for e, r in zip(extras, rows, strict=True)
                    ],
                    "kl_cache_to_repeat_per_row": ap.keep_loss_reference(
                        cache_arrays["teacher_logits"][rows],
                        repeat["teacher_logits"][rows],
                        cache_arrays["visible_mask"][rows],
                    )["per_row_horizon"].mean(axis=1).tolist(),
                    "stopping": False,
                }
                report["first_update"]["kl_cache_to_repeat_max"] = max(
                    report["first_update"]["kl_cache_to_repeat_per_row"]
                )
            gradients, norm = optim.clip_grad_norm(gradients, config.training.gradient_clip_norm)
            mx.eval(gradients, norm)
            for name, value in tree_flatten(gradients):
                if np.any(np.asarray(value)[ap.frozen_row_mask(name.removeprefix("gru."))] != 0):
                    raise RuntimeError("clipped gradient has nonzero frozen rows")
            optimizer.update(model, gradients)
            project_gru_front(model, source_tensors)
            mx.eval(model.parameters(), optimizer.state, norm, key)
            protection = verify_tail_update(
                source_tensors,
                {f"model.{k}": np.array(v) for k, v in tree_flatten(model.parameters())},
            )
            state_keys = [k for k, _ in tree_flatten(optimizer.state)]
            gru_state = [k for k in state_keys if k not in ("step", "learning_rate")]
            if not gru_state or any(
                k.split(".")[0] != "gru" or k.split(".")[1] not in ap.GRU_LEAVES for k in gru_state
            ):
                raise RuntimeError("optimizer state holds non-student-GRU leaves")
            report["actual_optimizer_steps"] += 1
            report["training_model_transitions"] += (
                plan["training_model_units_per_update"] + keep["student_units"][index]
            )
            elapsed = time.perf_counter() - tick
            entry = {
                "update": index + 1,
                "memory_loss": total,
                "gradient_norm": float(norm.item()),
                "memory_raw_front_gradient_l2": memory_front,
                "clipped_frozen_rows_exact_zero": True,
                "tail_protection": protection,
                "optimizer_state_keys": state_keys,
                "compute_seconds": elapsed,
                "permutation_sha256": permutation_digests,
                **details,
            }
            report["updates"].append(entry)
            with (directory / "updates.jsonl").open("a") as stream:
                stream.write(json.dumps(entry, allow_nan=False) + "\n")
            guard(force=True)
            close_stage()
            persist()
            rest = elapsed * (1 / config.resources.active.training_duty_cycle - 1)
            idle_until = time.monotonic() + rest
            while time.monotonic() < idle_until:
                time.sleep(min(1.0, max(0.0, idle_until - time.monotonic())))
                guard()
        store.transition(run_id, "validating")
        stage("verification")
        params = {k: np.array(v) for k, v in tree_flatten(model.parameters())}
        report["parameter_sha256"] = _array_sha(params)
        report["changed_model_tensors"] = sorted(
            k for k, v in params.items() if not np.array_equal(v, source_tensors[f"model.{k}"])
        )
        report["logical_model_transitions"] = completed_units + report["training_model_transitions"]
        if not (
            report["logical_model_transitions"] == reserved_units == plan["expected_total_model_units"]
        ):
            raise RuntimeError("probe measured work differs from reserved/registered units")
        load_checkpoint(checkpoint_path)
        report["source_files_unchanged"] = (
            comparison_report_path.read_bytes() == comparison_bytes
            and m2mc_report_path.read_bytes() == reuse["m2mc_report_bytes"]
            and m2l_report_path.read_bytes() == relabel["m2l_report_bytes"]
            and hashlib.sha256(cache_path.read_bytes()).hexdigest() == cache_file["sha256"]
        )
        if not report["source_files_unchanged"]:
            raise RuntimeError("probe source files changed")
        report["mlx_peak_bytes"] = mx.get_peak_memory()
        guard(force=True)
        close_stage()
        store.transition(run_id, "completed", reason="action_preservation_probe_complete_no_promotion")
        report.update(status="completed", current_stage="completed")
    except BaseException as exc:
        report.update(status="failed", error=f"{type(exc).__name__}: {exc}")
        if stage_started is not None:
            close_stage()
        if run_id is not None and store.get_run(run_id).state not in TERMINAL_STATES:
            store.transition(run_id, "failed", reason="action_preservation_probe_failure")
    finally:
        report["reserved_model_transitions"] = reserved_units
        if run_id is not None:
            report["run"] = store.get_run(run_id).to_dict()
        store.close()
        persist()
    return report


def main():
    parser = argparse.ArgumentParser()
    for name in ("config", "dataset", "checkpoint", "output-dir", "control-db"):
        parser.add_argument(f"--{name}", type=Path, required=True)
    parser.add_argument("--experiment-id", required=True)
    parser.add_argument("--local-fit", action="store_true")
    parser.add_argument("--diverse-fit", action="store_true")
    parser.add_argument("--comparison-report", type=Path)
    parser.add_argument("--relabel-fit", action="store_true")
    parser.add_argument("--m2l-report", type=Path)
    parser.add_argument("--m2l-checkpoint", type=Path)
    parser.add_argument("--relabel-learning-rate", choices=("0.001", "0.003"))
    parser.add_argument("--action-preservation-fit", action="store_true")
    parser.add_argument("--m2mc-report", type=Path)
    parser.add_argument("--action-preservation-probe", action="store_true")
    parser.add_argument("--action-preservation-lambda10", action="store_true")
    parser.add_argument("--action-preservation-distill", action="store_true")
    parser.add_argument("--action-preservation-history", action="store_true")
    parser.add_argument("--action-preservation-mixed", action="store_true")
    parser.add_argument("--action-preservation-mixed-weight025", action="store_true")
    parser.add_argument("--action-preservation-mixed-weight0-control", action="store_true")
    parser.add_argument("--action-preservation-mixed-onestep", action="store_true")
    parser.add_argument("--action-preservation-mixed-tailself", action="store_true")
    parser.add_argument("--action-preservation-mixed-tailself-halfproj", action="store_true")
    args = parser.parse_args()
    if args.action_preservation_mixed_tailself_halfproj and (
        args.local_fit
        or args.diverse_fit
        or args.relabel_fit
        or args.relabel_learning_rate is not None
        or args.action_preservation_fit
        or args.action_preservation_probe
        or args.action_preservation_lambda10
        or args.action_preservation_distill
        or args.action_preservation_history
        or args.action_preservation_mixed
        or args.action_preservation_mixed_weight025
        or args.action_preservation_mixed_weight0_control
        or args.action_preservation_mixed_onestep
        or args.action_preservation_mixed_tailself
    ):
        raise SystemExit("the half-projection mixed condition is exclusive with every other protocol flag")
    if args.action_preservation_mixed_tailself and (
        args.local_fit
        or args.diverse_fit
        or args.relabel_fit
        or args.relabel_learning_rate is not None
        or args.action_preservation_fit
        or args.action_preservation_probe
        or args.action_preservation_lambda10
        or args.action_preservation_distill
        or args.action_preservation_history
        or args.action_preservation_mixed
        or args.action_preservation_mixed_weight025
        or args.action_preservation_mixed_weight0_control
        or args.action_preservation_mixed_onestep
    ):
        raise SystemExit("the tail-self-frozen mixed condition is exclusive with every other protocol flag")
    if args.action_preservation_mixed_onestep and (
        args.local_fit
        or args.diverse_fit
        or args.relabel_fit
        or args.relabel_learning_rate is not None
        or args.action_preservation_fit
        or args.action_preservation_probe
        or args.action_preservation_lambda10
        or args.action_preservation_distill
        or args.action_preservation_history
        or args.action_preservation_mixed
        or args.action_preservation_mixed_weight025
        or args.action_preservation_mixed_weight0_control
    ):
        raise SystemExit("the one-step-truncation mixed condition is exclusive with every other protocol flag")
    if args.action_preservation_mixed_weight0_control and (
        args.local_fit
        or args.diverse_fit
        or args.relabel_fit
        or args.relabel_learning_rate is not None
        or args.action_preservation_fit
        or args.action_preservation_probe
        or args.action_preservation_lambda10
        or args.action_preservation_distill
        or args.action_preservation_history
        or args.action_preservation_mixed
        or args.action_preservation_mixed_weight025
        or args.action_preservation_mixed_onestep
    ):
        raise SystemExit("the lambda_h mixed control condition is exclusive with every other protocol flag")
    if args.action_preservation_mixed_weight025 and (
        args.local_fit
        or args.diverse_fit
        or args.relabel_fit
        or args.relabel_learning_rate is not None
        or args.action_preservation_fit
        or args.action_preservation_probe
        or args.action_preservation_lambda10
        or args.action_preservation_distill
        or args.action_preservation_history
        or args.action_preservation_mixed
        or args.action_preservation_mixed_weight0_control
        or args.action_preservation_mixed_onestep
    ):
        raise SystemExit("the lambda_h mixed condition is exclusive with every other protocol flag")
    if args.action_preservation_mixed and (
        args.local_fit
        or args.diverse_fit
        or args.relabel_fit
        or args.relabel_learning_rate is not None
        or args.action_preservation_fit
        or args.action_preservation_probe
        or args.action_preservation_lambda10
        or args.action_preservation_distill
        or args.action_preservation_history
        or args.action_preservation_mixed_weight0_control
        or args.action_preservation_mixed_onestep
    ):
        raise SystemExit("the mixed condition is exclusive with every other protocol flag")
    if args.action_preservation_history and (
        args.local_fit
        or args.diverse_fit
        or args.relabel_fit
        or args.relabel_learning_rate is not None
        or args.action_preservation_fit
        or args.action_preservation_probe
        or args.action_preservation_lambda10
        or args.action_preservation_distill
    ):
        raise SystemExit("the history condition is exclusive with every other protocol flag")
    if args.action_preservation_distill and (
        args.local_fit
        or args.diverse_fit
        or args.relabel_fit
        or args.relabel_learning_rate is not None
        or args.action_preservation_fit
        or args.action_preservation_probe
        or args.action_preservation_lambda10
        or args.action_preservation_history
        or args.action_preservation_mixed
    ):
        raise SystemExit("the distill condition is exclusive with every other protocol flag")
    if args.action_preservation_lambda10 and (
        args.local_fit
        or args.diverse_fit
        or args.relabel_fit
        or args.relabel_learning_rate is not None
        or args.action_preservation_fit
        or args.action_preservation_probe
        or args.action_preservation_distill
        or args.action_preservation_history
        or args.action_preservation_mixed
    ):
        raise SystemExit("the lambda10 condition is exclusive with every other protocol flag")
    if args.action_preservation_probe:
        if (
            args.local_fit
            or args.diverse_fit
            or args.relabel_fit
            or args.relabel_learning_rate is not None
            or args.action_preservation_fit
            or args.action_preservation_lambda10
            or args.action_preservation_distill
            or args.action_preservation_history
            or args.action_preservation_mixed
        ):
            raise SystemExit("the probe is exclusive with every training protocol flag")
        report = run_action_preservation_probe(
            args.config,
            args.dataset,
            args.checkpoint,
            args.output_dir,
            args.control_db,
            args.experiment_id,
            comparison_report_path=args.comparison_report,
            m2l_report_path=args.m2l_report,
            m2l_checkpoint_path=args.m2l_checkpoint,
            m2mc_report_path=args.m2mc_report,
        )
        print(json.dumps(report, ensure_ascii=False))
        return 0 if report["status"] == "completed" else 1
    report = run_memory(
        args.config,
        args.dataset,
        args.checkpoint,
        args.output_dir,
        args.control_db,
        args.experiment_id,
        local_fit=args.local_fit,
        diverse_fit=args.diverse_fit,
        comparison_report_path=args.comparison_report,
        relabel_fit=args.relabel_fit,
        m2l_report_path=args.m2l_report,
        m2l_checkpoint_path=args.m2l_checkpoint,
        relabel_learning_rate=(
            None if args.relabel_learning_rate is None else float(args.relabel_learning_rate)
        ),
        action_preservation_fit=args.action_preservation_fit,
        m2mc_report_path=args.m2mc_report,
        action_preservation_lambda10=args.action_preservation_lambda10,
        action_preservation_distill=args.action_preservation_distill,
        action_preservation_history=args.action_preservation_history,
        action_preservation_mixed=args.action_preservation_mixed,
        action_preservation_mixed_weight025=args.action_preservation_mixed_weight025,
        action_preservation_mixed_weight0_control=args.action_preservation_mixed_weight0_control,
        action_preservation_mixed_onestep=args.action_preservation_mixed_onestep,
        action_preservation_mixed_tailself=args.action_preservation_mixed_tailself,
        action_preservation_mixed_tailself_halfproj=args.action_preservation_mixed_tailself_halfproj,
    )
    print(json.dumps(report, ensure_ascii=False))
    return 0 if report["status"] == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
