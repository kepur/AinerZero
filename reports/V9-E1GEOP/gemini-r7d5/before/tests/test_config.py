from pathlib import Path

import pytest
from pydantic import ValidationError

from ainerzero.core.config import (
    BudgetConfig,
    ProjectConfig,
    config_hash,
    load_config,
    save_config_snapshot,
)

DEFAULT_CONFIG = Path(__file__).resolve().parents[1] / "configs" / "brain0.yaml"


def test_checked_in_defaults_match_resolved_defaults():
    assert load_config(DEFAULT_CONFIG) == ProjectConfig()


def test_snapshot_round_trip_retains_full_configuration_and_hash(tmp_path):
    original = ProjectConfig(seed=42, budget=BudgetConfig(max_wall_seconds=123))
    target = tmp_path / "run" / "config.yaml"
    save_config_snapshot(original, target)
    restored = load_config(target)
    assert restored == original
    assert config_hash(restored) == config_hash(original)
    assert config_hash(ProjectConfig(seed=43)) != config_hash(original)
    assert "gradient_clip_norm" in target.read_text()
    assert not list(target.parent.glob("*.tmp"))


def test_yaml_formatting_and_key_order_do_not_change_hash(tmp_path):
    first = tmp_path / "first.yaml"
    second = tmp_path / "second.yaml"
    first.write_text("seed: 7\nbudget:\n  max_wall_seconds: 300\n")
    second.write_text("# same effective settings\nbudget: {max_wall_seconds: 300}\nseed: 7\n")
    assert config_hash(load_config(first)) == config_hash(load_config(second))


@pytest.mark.parametrize(
    "raw",
    [
        {"modle": {}},
        {"training": {"learing_rate": 0.01}},
        {"resources": {"active": {"secret": True}}},
        {"model": {"pretrained_weights": "something"}},
        {"evaluation": {"final_seeds": [1, 2, 3]}},
    ],
)
def test_unknown_fields_are_not_silently_ignored(raw):
    with pytest.raises(ValidationError):
        ProjectConfig.model_validate(raw)


@pytest.mark.parametrize("value", [0, -1, True, "5", float("nan"), float("inf")])
def test_environment_step_budget_is_a_positive_integer(value):
    with pytest.raises(ValidationError):
        BudgetConfig(max_environment_steps=value)


@pytest.mark.parametrize("value", [0, -1, True, "5", float("nan"), float("inf"), -float("inf")])
def test_duration_budget_is_finite_and_positive(value):
    with pytest.raises(ValidationError):
        BudgetConfig(max_wall_seconds=value)


@pytest.mark.parametrize(
    "raw",
    [
        {"training": {"learning_rate": float("nan")}},
        {"training": {"weight_decay": float("inf")}},
        {"training": {"adam_betas": [0.9, 1.0]}},
        {"training": {"replay": {"recent": 0.7}}},
        {"training": {"ema_decay": 1}},
        {"training": {"bootstrap_probability": 0}},
        {"training": {"bias_correction": False}},
        {"training": {"bias_correction": 1}},
        {"schema_version": True},
        {"environment": {"hidden_placeholder_byte": False}},
        {"resources": {"pause_below_available_gib": 32}},
        {"planning": {"elites": 200, "candidates": 128}},
        {"training": {"effective_batch_size": 12}},
        {"storage": {"data_dir": "../other-project"}},
        {"storage": {"data_dir": "/tmp/other-project"}},
        {"storage": {"data_dir": "."}},
        {"budget": {"max_daily_active_seconds": 100000}},
        {"budget": {"timezone": "unknown/timezone"}},
        {"budget": {"timezone": "/etc/passwd"}},
    ],
)
def test_inconsistent_or_unsafe_settings_fail_early(raw):
    with pytest.raises(ValidationError):
        ProjectConfig.model_validate(raw)


def test_profile_memory_and_gradient_accumulation_consistency():
    raw = ProjectConfig().model_dump()
    raw["resources"]["active"]["mlx_memory_gib"] = 24
    with pytest.raises(ValidationError, match="MLX memory"):
        ProjectConfig.model_validate(raw)
    raw = ProjectConfig().model_dump()
    raw["resources"]["idle"]["micro_batch_size"] = 64
    with pytest.raises(ValidationError, match="micro batch"):
        ProjectConfig.model_validate(raw)
    config = ProjectConfig()
    assert config.training.effective_batch_size // config.resources.active.micro_batch_size == 4
    assert config.training.effective_batch_size // config.resources.idle.micro_batch_size == 1


@pytest.mark.parametrize(
    "content",
    [
        "seed: 1\nseed: 2\n",
        "budget:\n  max_wall_seconds: 12\n  max_wall_seconds: 99\n",
        "- not\n- a\n- mapping\n",
        "",
        "1: invalid-key\n",
    ],
)
def test_ambiguous_yaml_is_rejected(tmp_path, content):
    path = tmp_path / "bad.yaml"
    path.write_text(content)
    with pytest.raises(ValueError):
        load_config(path)


def test_settings_cannot_change_after_a_hash_was_recorded():
    config = ProjectConfig()
    with pytest.raises(ValidationError):
        config.budget.max_wall_seconds = 1


def test_preconstructed_invalid_subconfig_is_revalidated():
    invalid = BudgetConfig().model_copy(update={"max_wall_seconds": float("inf")})
    with pytest.raises(ValidationError):
        ProjectConfig(budget=invalid)
