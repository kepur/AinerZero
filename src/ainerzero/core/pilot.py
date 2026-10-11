"""Bounded first-experiment declarations, not a learner or a resource enforcer.

The existing v1 configuration is unchanged. A persisted experiment must also
record its actual source fingerprint; this path-independent configuration hash
does not identify the code that executed it.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Annotated, Literal, Self

import yaml
from pydantic import Field, field_validator, model_validator

from ainerzero.core.config import (
    BudgetConfig,
    EnvironmentConfig,
    ModelConfig,
    PlanningConfig,
    ResourceConfig,
    ResourceProfile,
    Settings,
    StorageConfig,
    TrainingConfig,
    _UniqueKeyLoader,
)


class MechanismManifest(Settings):
    """What is supplied by the researcher versus changed by future experience."""

    revision: Literal["pilot_mechanisms_v1"] = "pilot_mechanisms_v1"
    learning_implementation: Literal["c0_prediction_only"] = "c0_prediction_only"
    planning_implementation: Literal["planned"] = "planned"
    environment_implementation: Literal["c0_only"] = "c0_only"
    experience_contract: Literal["experience_v2"] = "experience_v2"
    pretrained_weights: Literal["none"] = "none"
    preinstalled_world_knowledge: Literal["none"] = "none"
    hypothesis_grammar: Literal["none"] = "none"
    fixed_mechanisms: tuple[
        Literal["rssm_architecture_and_random_initialization"],
        Literal["observation_action_contract"],
        Literal["posterior_reconstruction_and_action_conditioned_prior_loss"],
        Literal["adamw_parameter_updates_and_kl_schedule"],
        Literal["replay_selection_and_episode_state_reset"],
        Literal["bounded_local_cem_planning"],
        Literal["fixed_curriculum_and_random_collection"],
        Literal["evaluation_and_promotion_rules"],
    ] = (
        "rssm_architecture_and_random_initialization",
        "observation_action_contract",
        "posterior_reconstruction_and_action_conditioned_prior_loss",
        "adamw_parameter_updates_and_kl_schedule",
        "replay_selection_and_episode_state_reset",
        "bounded_local_cem_planning",
        "fixed_curriculum_and_random_collection",
        "evaluation_and_promotion_rules",
    )
    mutable_states: tuple[
        Literal["network_parameters"],
        Literal["optimizer_and_rng_state"],
        Literal["episode_belief"],
        Literal["observed_experience_replay"],
    ] = (
        "network_parameters",
        "optimizer_and_rng_state",
        "episode_belief",
        "observed_experience_replay",
    )


class PilotBudget(BudgetConfig):
    max_environment_steps: Annotated[int, Field(strict=True, gt=0, le=20_000)] = 20_000
    max_optimizer_steps: Annotated[int, Field(strict=True, gt=0, le=1_000)] = 1_000
    max_model_transitions: Annotated[int, Field(strict=True, gt=0, le=1_000_000)] = 1_000_000
    max_wall_seconds: Annotated[float, Field(strict=True, gt=0, le=1_800)] = 1_800
    max_daily_active_seconds: Annotated[float, Field(strict=True, gt=0, le=21_600)] = 21_600


class ExperimentBudget(Settings):
    max_model_runs: Annotated[int, Field(strict=True, gt=0, le=3)] = 3
    max_environment_steps: Annotated[int, Field(strict=True, gt=0, le=60_000)] = 60_000
    max_optimizer_steps: Annotated[int, Field(strict=True, gt=0, le=3_000)] = 3_000
    max_model_transitions: Annotated[int, Field(strict=True, gt=0, le=3_000_000)] = 3_000_000
    max_wall_seconds: Annotated[float, Field(strict=True, gt=0, le=7_200)] = 7_200
    max_calibration_seconds: Annotated[float, Field(strict=True, gt=0, le=900)] = 900

    @model_validator(mode="after")
    def calibration_fits(self) -> Self:
        if self.max_calibration_seconds > self.max_wall_seconds:
            raise ValueError("calibration budget must fit experiment wall budget")
        return self


class PilotModel(ModelConfig):
    byte_embedding_dim: Annotated[int, Field(strict=True, ge=16, le=16)] = 16
    encoder_hidden_dim: Annotated[int, Field(strict=True, ge=128, le=128)] = 128
    embedding_dim: Annotated[int, Field(strict=True, ge=128, le=128)] = 128
    hidden_dim: Annotated[int, Field(strict=True, ge=256, le=256)] = 256
    latent_dim: Annotated[int, Field(strict=True, ge=16, le=16)] = 16
    action_embedding_dim: Annotated[int, Field(strict=True, ge=16, le=16)] = 16
    prior_hidden_dim: Annotated[int, Field(strict=True, ge=128, le=128)] = 128
    posterior_hidden_dim: Annotated[int, Field(strict=True, ge=128, le=128)] = 128
    decoder_hidden_dim: Annotated[int, Field(strict=True, ge=128, le=128)] = 128
    ensemble_heads: Annotated[int, Field(strict=True, ge=0, le=0)] = 0
    ensemble_hidden_dim: Annotated[int, Field(strict=True, ge=128, le=128)] = 128


class PilotTraining(TrainingConfig):
    effective_batch_size: Annotated[int, Field(strict=True, ge=16, le=16)] = 16
    burn_in_steps: Annotated[int, Field(strict=True, ge=4, le=4)] = 4
    sequence_steps: Annotated[int, Field(strict=True, ge=16, le=16)] = 16
    kl_warmup_updates: Annotated[int, Field(strict=True, ge=100, le=100)] = 100
    prior_prediction_loss_weight: Annotated[float, Field(strict=True, ge=1, le=1)] = 1
    ensemble_loss_weight: Annotated[float, Field(strict=True, ge=0, le=0)] = 0
    validation_interval_updates: Annotated[int, Field(strict=True, ge=100, le=100)] = 100
    checkpoint_interval_updates: Annotated[int, Field(strict=True, gt=0, le=1_000)] = 100


class PilotResourceProfile(ResourceProfile):
    cpu_workers: Annotated[int, Field(strict=True, ge=1, le=1)] = 1
    vector_environments: Annotated[int, Field(strict=True, ge=8, le=16)] = 8
    micro_batch_size: Annotated[int, Field(strict=True, ge=4, le=8)] = 4
    project_memory_gib: Annotated[float, Field(strict=True, gt=0, le=8)] = 8
    mlx_memory_gib: Annotated[float, Field(strict=True, gt=0, le=4)] = 4
    mlx_cache_gib: Annotated[float, Field(strict=True, ge=0, le=0.5)] = 0.5
    training_duty_cycle: Annotated[float, Field(strict=True, gt=0, le=1)] = 0.25

    @field_validator("vector_environments", "micro_batch_size")
    @classmethod
    def bounded_comparisons(cls, value: int, info) -> int:
        allowed = (8, 16) if info.field_name == "vector_environments" else (4, 8)
        if value not in allowed:
            raise ValueError(f"{info.field_name} must be one of {allowed}")
        return value


class PilotResources(ResourceConfig):
    active: PilotResourceProfile = Field(default_factory=PilotResourceProfile)
    idle: PilotResourceProfile = Field(
        default_factory=lambda: PilotResourceProfile(
            vector_environments=16, micro_batch_size=8, training_duty_cycle=1
        )
    )
    system_reserve_gib: Annotated[float, Field(strict=True, ge=16)] = 16
    pause_training_on_battery: Annotated[bool, Field(strict=True)] = True

    @field_validator("pause_training_on_battery")
    @classmethod
    def mains_power_required(cls, value: bool) -> bool:
        if not value:
            raise ValueError("pilot requires mains power")
        return value


class PilotStorage(StorageConfig):
    disk_budget_gib: Annotated[float, Field(strict=True, gt=0, le=20)] = 20
    persistent_data_gib: Annotated[float, Field(strict=True, gt=0, le=2)] = 2
    replay_max_transitions: Annotated[int, Field(strict=True, gt=0, le=60_000)] = 60_000
    ram_cache_gib: Annotated[float, Field(strict=True, gt=0, le=0.5)] = 0.25
    trajectory_shard_mib: Annotated[int, Field(strict=True, gt=0, le=256)] = 16

    @model_validator(mode="after")
    def data_fits_storage(self) -> Self:
        if self.persistent_data_gib > self.disk_budget_gib:
            raise ValueError("persistent data budget must fit project disk budget")
        return self


class PilotEnvironment(EnvironmentConfig):
    course: Literal["C0"] = "C0"
    max_episode_ticks: Annotated[int, Field(strict=True, ge=128, le=128)] = 128


class PilotPlanning(PlanningConfig):
    horizon: Annotated[int, Field(strict=True, ge=4, le=4)] = 4
    candidates: Annotated[int, Field(strict=True, ge=32, le=32)] = 32
    elites: Annotated[int, Field(strict=True, ge=4, le=4)] = 4
    iterations: Annotated[int, Field(strict=True, ge=2, le=2)] = 2
    latent_samples: Annotated[int, Field(strict=True, ge=1, le=1)] = 1
    disagreement_penalty: Annotated[float, Field(strict=True, ge=0, le=0)] = 0


class PilotEvaluation(Settings):
    latent_particles: Annotated[int, Field(strict=True, ge=8, le=8)] = 8
    support_ticks: Annotated[int, Field(strict=True, ge=32, le=32)] = 32
    support_query_weights: Literal["frozen"] = "frozen"
    probability_aggregation: Literal["mean_probabilities_then_nll"] = "mean_probabilities_then_nll"


class PilotConfig(Settings):
    schema_version: Annotated[int, Field(strict=True, ge=1, le=1)] = 1
    profile: Literal["pilot_predictor"] = "pilot_predictor"
    project_name: Literal["ainerzero"] = "ainerzero"
    route: Literal["neural"] = "neural"
    teacher: Literal["none"] = "none"
    run_seeds: tuple[Annotated[int, Field(strict=True)], ...] = (0, 1, 2)
    mechanisms: MechanismManifest = Field(default_factory=MechanismManifest)
    budget: PilotBudget = Field(default_factory=PilotBudget)
    experiment_budget: ExperimentBudget = Field(default_factory=ExperimentBudget)
    model: PilotModel = Field(default_factory=PilotModel)
    training: PilotTraining = Field(default_factory=PilotTraining)
    resources: PilotResources = Field(default_factory=PilotResources)
    storage: PilotStorage = Field(default_factory=PilotStorage)
    environment: PilotEnvironment = Field(default_factory=PilotEnvironment)
    planning: PilotPlanning = Field(default_factory=PilotPlanning)
    evaluation: PilotEvaluation = Field(default_factory=PilotEvaluation)

    @field_validator("run_seeds")
    @classmethod
    def preregistered_seeds(cls, value: tuple[int, ...]) -> tuple[int, ...]:
        if value != (0, 1, 2):
            raise ValueError("pilot run_seeds must remain the preregistered (0, 1, 2)")
        return value

    @model_validator(mode="after")
    def run_limits_fit_experiment(self) -> Self:
        for key in (
            "max_environment_steps",
            "max_optimizer_steps",
            "max_model_transitions",
            "max_wall_seconds",
        ):
            if getattr(self.budget, key) > getattr(self.experiment_budget, key):
                raise ValueError(f"run {key} must fit experiment budget")
        if self.evaluation.support_ticks >= self.environment.max_episode_ticks:
            raise ValueError("support must leave query ticks inside the episode")
        return self

    def snapshot_for_run(self, seed: int) -> dict:
        config = PilotConfig.model_validate(self)
        if type(seed) is not int or seed not in config.run_seeds:
            raise ValueError("run seed must be a preregistered integer: 0, 1, or 2")
        return {**config.model_dump(mode="json"), "seed": seed}


def load_pilot_config(path: str | Path) -> PilotConfig:
    """Load strict safe YAML without changing the existing v1 loader."""
    with Path(path).open("r", encoding="utf-8") as stream:
        raw = yaml.load(stream, Loader=_UniqueKeyLoader)
    if not isinstance(raw, dict):
        raise ValueError("pilot configuration must contain a mapping")
    return PilotConfig.model_validate(raw)


def pilot_config_hash(config: PilotConfig) -> str:
    """Hash resolved declarations; executable source needs a separate fingerprint."""
    payload = PilotConfig.model_validate(config).model_dump(mode="json")
    encoded = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
