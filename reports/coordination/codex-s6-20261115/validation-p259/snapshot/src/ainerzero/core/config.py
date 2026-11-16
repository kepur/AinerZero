"""Validated, serializable experiment settings shared by every entry point.

These are experiment defaults, not measured hardware performance. M0 validates
the future training settings without starting training or allocating GPU memory.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import tempfile
from pathlib import Path
from typing import Annotated, Literal, Self
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

PositiveInt = Annotated[int, Field(strict=True, gt=0)]
NonNegativeInt = Annotated[int, Field(strict=True, ge=0)]
PositiveFloat = Annotated[float, Field(strict=True, gt=0, allow_inf_nan=False)]
NonNegativeFloat = Annotated[float, Field(strict=True, ge=0, allow_inf_nan=False)]
Probability = Annotated[float, Field(strict=True, ge=0, le=1, allow_inf_nan=False)]
StrictBool = Annotated[bool, Field(strict=True)]


class Settings(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        validate_default=True,
        allow_inf_nan=False,
        revalidate_instances="always",
    )


class BudgetConfig(Settings):
    max_environment_steps: PositiveInt = 1_000_000
    max_optimizer_steps: PositiveInt = 20_000
    max_wall_seconds: PositiveFloat = 21_600
    max_daily_active_seconds: PositiveFloat = 21_600
    timezone: str = "Europe/Belgrade"

    @field_validator("timezone")
    @classmethod
    def valid_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError("timezone must be an installed IANA timezone") from exc
        return value

    @model_validator(mode="after")
    def daily_limit_fits_day(self) -> Self:
        if self.max_daily_active_seconds > 86_400:
            raise ValueError("daily active budget must not exceed 24 hours")
        return self


class ModelConfig(Settings):
    architecture: Literal["brain0_rssm"] = "brain0_rssm"
    initialization: Literal["random"] = "random"
    cells: Annotated[int, Field(strict=True, ge=8, le=8)] = 8
    symbol_vocabulary: Annotated[int, Field(strict=True, ge=256, le=256)] = 256
    action_count: Annotated[int, Field(strict=True, ge=4, le=4)] = 4
    byte_embedding_dim: PositiveInt = 16
    encoder_hidden_dim: PositiveInt = 512
    embedding_dim: PositiveInt = 512
    hidden_dim: PositiveInt = 1024
    latent_dim: PositiveInt = 64
    action_embedding_dim: PositiveInt = 32
    prior_hidden_dim: PositiveInt = 1024
    posterior_hidden_dim: PositiveInt = 1024
    decoder_hidden_dim: PositiveInt = 1024
    ensemble_heads: PositiveInt = 5
    ensemble_hidden_dim: PositiveInt = 512
    minimum_std: PositiveFloat = 0.1
    activation: Literal["silu"] = "silu"


class ReplayMixture(Settings):
    recent: Probability = 0.5
    reservoir: Probability = 0.3
    failure: Probability = 0.2

    @model_validator(mode="after")
    def normalized(self) -> Self:
        if not math.isclose(self.recent + self.reservoir + self.failure, 1, abs_tol=1e-9):
            raise ValueError("replay mixture proportions must sum to 1")
        return self


class TrainingConfig(Settings):
    precision: Literal["float32"] = "float32"
    effective_batch_size: PositiveInt = 32
    burn_in_steps: NonNegativeInt = 16
    sequence_steps: PositiveInt = 64
    optimizer: Literal["adamw"] = "adamw"
    learning_rate: PositiveFloat = 3e-4
    adam_betas: tuple[Probability, Probability] = (0.9, 0.999)
    adam_epsilon: PositiveFloat = 1e-8
    weight_decay: NonNegativeFloat = 1e-4
    bias_correction: StrictBool = True
    gradient_clip_norm: PositiveFloat = 1.0
    symbol_loss_weight: PositiveFloat = 1.0
    visibility_loss_weight: NonNegativeFloat = 0.2
    cursor_loss_weight: NonNegativeFloat = 0.2
    kl_loss_weight: NonNegativeFloat = 0.1
    kl_warmup_updates: PositiveInt = 1000
    kl_free_nats: NonNegativeFloat = 1.0
    ensemble_loss_weight: NonNegativeFloat = 0.1
    ema_decay: Probability = 0.99
    bootstrap_probability: Probability = 0.8
    warmup_transitions: PositiveInt = 10_000
    initial_fit_updates: PositiveInt = 500
    collect_transitions: PositiveInt = 1024
    updates_per_collection: PositiveInt = 8
    validation_interval_updates: PositiveInt = 500
    checkpoint_interval_updates: PositiveInt = 1000
    replay: ReplayMixture = Field(default_factory=ReplayMixture)

    @field_validator("bias_correction")
    @classmethod
    def bias_correction_required(cls, value: bool) -> bool:
        if not value:
            raise ValueError("Brain-0 AdamW requires bias correction")
        return value

    @field_validator("adam_betas")
    @classmethod
    def betas_below_one(cls, values: tuple[float, float]) -> tuple[float, float]:
        if any(value >= 1 for value in values):
            raise ValueError("Adam betas must be less than 1")
        return values

    @field_validator("ema_decay", "bootstrap_probability")
    @classmethod
    def meaningful_probability(cls, value: float) -> float:
        if not 0 < value < 1:
            raise ValueError("probability must be strictly between 0 and 1")
        return value


class ResourceProfile(Settings):
    cpu_workers: Annotated[int, Field(strict=True, ge=1, le=6)]
    vector_environments: PositiveInt
    micro_batch_size: PositiveInt
    project_memory_gib: PositiveFloat
    mlx_memory_gib: PositiveFloat
    mlx_cache_gib: NonNegativeFloat
    training_duty_cycle: Annotated[float, Field(strict=True, gt=0, le=1)]

    @model_validator(mode="after")
    def memory_limits_consistent(self) -> Self:
        if self.mlx_memory_gib > self.project_memory_gib:
            raise ValueError("MLX memory budget cannot exceed project memory budget")
        if self.mlx_cache_gib > self.mlx_memory_gib:
            raise ValueError("MLX cache budget cannot exceed MLX memory budget")
        return self


class ResourceConfig(Settings):
    mode: Literal["adaptive", "active", "idle"] = "adaptive"
    active: ResourceProfile = Field(
        default_factory=lambda: ResourceProfile(
            cpu_workers=2,
            vector_environments=8,
            micro_batch_size=8,
            project_memory_gib=16,
            mlx_memory_gib=8,
            mlx_cache_gib=1,
            training_duty_cycle=0.25,
        )
    )
    idle: ResourceProfile = Field(
        default_factory=lambda: ResourceProfile(
            cpu_workers=4,
            vector_environments=32,
            micro_batch_size=32,
            project_memory_gib=64,
            mlx_memory_gib=48,
            mlx_cache_gib=4,
            training_duty_cycle=1.0,
        )
    )
    idle_after_seconds: PositiveFloat = 300
    activity_poll_seconds: PositiveFloat = 2
    duty_window_seconds: PositiveFloat = 2
    target_micro_step_seconds: PositiveFloat = 0.5
    system_reserve_gib: PositiveFloat = 16
    pause_below_available_gib: PositiveFloat = 8
    minimum_disk_free_gib: PositiveFloat = 50
    pause_training_on_battery: StrictBool = True
    swap_growth_gib: PositiveFloat = 1
    swap_sample_seconds: PositiveFloat = 10
    swap_growth_samples: PositiveInt = 3

    @model_validator(mode="after")
    def thresholds_ordered(self) -> Self:
        if self.pause_below_available_gib >= self.system_reserve_gib:
            raise ValueError("pause memory threshold must be below reserve threshold")
        return self


class StorageConfig(Settings):
    data_dir: str = "artifacts"
    disk_budget_gib: PositiveFloat = 20
    replay_max_transitions: PositiveInt = 1_000_000
    ram_cache_gib: PositiveFloat = 2
    trajectory_shard_mib: PositiveInt = 256
    keep_recent_checkpoints: PositiveInt = 3
    keep_best_versions: PositiveInt = 2

    @field_validator("data_dir")
    @classmethod
    def project_relative_directory(cls, value: str) -> str:
        path = Path(value)
        if not value.strip() or path.is_absolute() or ".." in path.parts or path == Path("."):
            raise ValueError("data_dir must be a non-empty relative project subdirectory")
        return path.as_posix()


class EnvironmentConfig(Settings):
    name: Literal["switchlab_v1"] = "switchlab_v1"
    course: Literal["C0", "C1", "C2", "C3", "C4"] = "C0"
    max_episode_ticks: PositiveInt = 128
    hidden_placeholder_byte: Annotated[int, Field(strict=True, ge=0, le=0)] = 0


class PlanningConfig(Settings):
    horizon: PositiveInt = 12
    candidates: PositiveInt = 128
    elites: PositiveInt = 16
    iterations: PositiveInt = 3
    latent_samples: PositiveInt = 4
    old_distribution_weight: Probability = 0.2
    action_cost: NonNegativeFloat = 0.01
    disagreement_penalty: NonNegativeFloat = 0.1

    @model_validator(mode="after")
    def elite_count_valid(self) -> Self:
        if self.elites > self.candidates:
            raise ValueError("planning elites must not exceed candidates")
        return self


class TeachingConfig(Settings):
    mode: Literal["guided", "assisted", "independent"] = "guided"
    allow_teacher_demonstrations: StrictBool = True


class EvaluationConfig(Settings):
    development_seed_count: PositiveInt = 3
    final_seed_count: PositiveInt = 5
    episodes_per_course_per_seed: PositiveInt = 100


class ProjectConfig(Settings):
    schema_version: Annotated[int, Field(strict=True, ge=1, le=1)] = 1
    project_name: Literal["ainerzero"] = "ainerzero"
    seed: Annotated[int, Field(strict=True, ge=0, lt=2**32)] = 0
    budget: BudgetConfig = Field(default_factory=BudgetConfig)
    model: ModelConfig = Field(default_factory=ModelConfig)
    training: TrainingConfig = Field(default_factory=TrainingConfig)
    resources: ResourceConfig = Field(default_factory=ResourceConfig)
    storage: StorageConfig = Field(default_factory=StorageConfig)
    environment: EnvironmentConfig = Field(default_factory=EnvironmentConfig)
    planning: PlanningConfig = Field(default_factory=PlanningConfig)
    teaching: TeachingConfig = Field(default_factory=TeachingConfig)
    evaluation: EvaluationConfig = Field(default_factory=EvaluationConfig)

    @model_validator(mode="after")
    def batch_sizes_consistent(self) -> Self:
        for name in ("active", "idle"):
            profile = getattr(self.resources, name)
            if self.training.effective_batch_size % profile.micro_batch_size:
                raise ValueError(f"{name} micro batch must divide effective_batch_size")
        return self


class _UniqueKeyLoader(yaml.SafeLoader):
    """A duplicated YAML setting is an error, not a silent last-value override."""


def _unique_mapping(loader: _UniqueKeyLoader, node: yaml.MappingNode, deep: bool = False) -> dict:
    loader.flatten_mapping(node)
    mapping = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if not isinstance(key, str):
            raise ValueError("configuration keys must be strings")
        if key in mapping:
            raise ValueError(f"duplicate configuration key: {key}")
        mapping[key] = loader.construct_object(value_node, deep=deep)
    return mapping


_UniqueKeyLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _unique_mapping)


def load_config(path: str | Path) -> ProjectConfig:
    """Load safe YAML (or JSON) and reject misspellings and invalid combinations."""
    with Path(path).open("r", encoding="utf-8") as stream:
        raw = yaml.load(stream, Loader=_UniqueKeyLoader)
    if not isinstance(raw, dict):
        raise ValueError("configuration must contain a mapping")
    return ProjectConfig.model_validate(raw)


def config_hash(config: ProjectConfig) -> str:
    """SHA-256 of all resolved defaults, independent of YAML formatting/key order."""
    encoded = json.dumps(
        config.model_dump(mode="json"),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def save_config_snapshot(config: ProjectConfig, path: str | Path) -> None:
    """Atomically save the complete validated settings; hashes are reproducible."""
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=destination.parent,
            prefix=f".{destination.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary:
            temporary_path = Path(temporary.name)
            yaml.safe_dump(config.model_dump(mode="json"), temporary, sort_keys=True)
            temporary.flush()
            os.fsync(temporary.fileno())
        os.replace(temporary_path, destination)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
