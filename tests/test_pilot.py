import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

from ainerzero.cli import main, pilot_manifest
from ainerzero.core.pilot import PilotConfig, load_pilot_config, pilot_config_hash

DEFAULT_CONFIG = Path(__file__).resolve().parents[1] / "configs" / "pilot.yaml"


@pytest.fixture
def declaration_project(tmp_path):
    """An isolated source tree makes unintended run/storage writes observable."""
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "ainerzero"\n')
    (tmp_path / "uv.lock").write_text("version = 1\n")
    source = tmp_path / "src" / "ainerzero"
    source.mkdir(parents=True)
    (source / "cli.py").write_text("# source fingerprint fixture\n")
    config = tmp_path / "configs" / "pilot.yaml"
    config.parent.mkdir()
    config.write_text("{}\n")
    return config


def test_checked_in_pilot_matches_resolved_defaults():
    assert load_pilot_config(DEFAULT_CONFIG) == PilotConfig()


def test_registered_duty_cycle_policy_m20261013_09():
    # exact registered values, not "any value in range"
    assert PilotConfig().resources.active.training_duty_cycle == 1.0
    assert PilotConfig().resources.idle.training_duty_cycle == 1.0
    assert load_pilot_config(DEFAULT_CONFIG).resources.active.training_duty_cycle == 1.0


def test_explicit_historical_duty_cycle_still_parses(tmp_path):
    old = PilotConfig.model_validate({"resources": {"active": {"training_duty_cycle": 0.25}}})
    assert old.resources.active.training_duty_cycle == 0.25
    assert old != PilotConfig()
    assert pilot_config_hash(old) != pilot_config_hash(PilotConfig())
    path = tmp_path / "pilot.yaml"
    path.write_text("resources:\n  active:\n    training_duty_cycle: 0.25\n")
    assert load_pilot_config(path).resources.active.training_duty_cycle == 0.25
    for bad in (0, 0.0, -0.25, 1.5, "0.25"):
        with pytest.raises(ValidationError):
            PilotConfig.model_validate({"resources": {"active": {"training_duty_cycle": bad}}})


@pytest.mark.parametrize(
    "raw",
    [
        {"route": "symbolic"},
        {"teacher": "llm"},
        {"mechanisms": {"pretrained_weights": "teacher.safetensors"}},
        {"mechanisms": {"preinstalled_world_knowledge": "AND / OR / XOR"}},
        {"mechanisms": {"hypothesis_grammar": "boolean"}},
        {"mechanisms": {"learning_implementation": "implemented"}},
        {"mechanisms": {"planning_implementation": "implemented"}},
        {"mechanisms": {"environment_implementation": "implemented"}},
        {"mechanisms": {"fixed_mechanisms": []}},
        {"mechanisms": {"mutable_states": ["system_permissions"]}},
        {"model": {"initialization": "pretrained"}},
        {"environment": {"course": "C1"}},
        {"evaluation": {"support_query_weights": "trainable"}},
        {"evaluation": {"probability_aggregation": "mean_nll"}},
    ],
)
def test_declaration_cannot_claim_implementation_or_add_knowledge(raw):
    with pytest.raises(ValidationError):
        PilotConfig.model_validate(raw)


@pytest.mark.parametrize(
    "raw",
    [
        {"model": {"hidden_dim": 1024}},
        {"model": {"embedding_dim": 512}},
        {"model": {"latent_dim": 64}},
        {"model": {"ensemble_heads": 3}},
        {"model": {"action_count": 5}},
        {"training": {"effective_batch_size": 32}},
        {"training": {"precision": "bfloat16"}},
        {"training": {"sequence_steps": 64}},
        {"training": {"prior_prediction_loss_weight": 0}},
        {"training": {"ensemble_loss_weight": 0.1}},
        {"planning": {"horizon": 12}},
        {"planning": {"candidates": 128}},
        {"planning": {"latent_samples": 4}},
        {"evaluation": {"latent_particles": 1}},
        {"evaluation": {"support_ticks": 128}},
    ],
)
def test_first_comparison_cannot_silently_expand_or_change_protocol(raw):
    with pytest.raises(ValidationError):
        PilotConfig.model_validate(raw)


@pytest.mark.parametrize("profile", ["active", "idle"])
@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("project_memory_gib", 8.1),
        ("mlx_memory_gib", 4.1),
        ("mlx_cache_gib", 0.6),
        ("cpu_workers", 2),
        ("vector_environments", 12),
        ("micro_batch_size", 6),
    ],
)
def test_resource_caps_apply_in_both_operating_modes(profile, field, value):
    with pytest.raises(ValidationError):
        PilotConfig.model_validate({"resources": {profile: {field: value}}})


@pytest.mark.parametrize(
    "raw",
    [
        {"resources": {"system_reserve_gib": 15}},
        {"resources": {"pause_training_on_battery": False}},
        {"resources": {"active": {"project_memory_gib": 3, "mlx_memory_gib": 4}}},
        {"resources": {"idle": {"mlx_memory_gib": 0.25, "mlx_cache_gib": 0.5}}},
        {"storage": {"disk_budget_gib": 21}},
        {"storage": {"persistent_data_gib": 3}},
        {"storage": {"disk_budget_gib": 1, "persistent_data_gib": 2}},
        {"storage": {"replay_max_transitions": 60_001}},
        {"storage": {"ram_cache_gib": 0.6}},
    ],
)
def test_memory_reserve_and_storage_constraints_are_consistent(raw):
    with pytest.raises(ValidationError):
        PilotConfig.model_validate(raw)


@pytest.mark.parametrize(
    ("section", "field", "value"),
    [
        ("budget", "max_environment_steps", 20_001),
        ("budget", "max_optimizer_steps", 1_001),
        ("budget", "max_model_transitions", 1_000_001),
        ("budget", "max_wall_seconds", 1_801),
        ("experiment_budget", "max_model_runs", 4),
        ("experiment_budget", "max_environment_steps", 60_001),
        ("experiment_budget", "max_optimizer_steps", 3_001),
        ("experiment_budget", "max_model_transitions", 3_000_001),
        ("experiment_budget", "max_wall_seconds", 7_201),
        ("experiment_budget", "max_calibration_seconds", 901),
        ("experiment_budget", "max_model_runs", True),
        ("budget", "max_environment_steps", "20000"),
        ("budget", "max_optimizer_steps", 0),
        ("experiment_budget", "max_wall_seconds", float("inf")),
        ("budget", "max_wall_seconds", float("nan")),
    ],
)
def test_per_run_and_total_budgets_are_strict_and_bounded(section, field, value):
    with pytest.raises(ValidationError):
        PilotConfig.model_validate({section: {field: value}})


@pytest.mark.parametrize(
    "raw",
    [
        {"experiment_budget": {"max_environment_steps": 19_999}},
        {"experiment_budget": {"max_optimizer_steps": 999}},
        {"experiment_budget": {"max_model_transitions": 999_999}},
        {"experiment_budget": {"max_wall_seconds": 1_799}},
        {
            "budget": {"max_wall_seconds": 500},
            "experiment_budget": {"max_wall_seconds": 500, "max_calibration_seconds": 501},
        },
    ],
)
def test_sub_budgets_cannot_exceed_experiment_totals(raw):
    with pytest.raises(ValidationError):
        PilotConfig.model_validate(raw)


def test_lower_caps_and_supported_resource_comparisons_remain_available():
    config = PilotConfig.model_validate(
        {
            "budget": {"max_wall_seconds": 600},
            "experiment_budget": {"max_model_runs": 1, "max_wall_seconds": 1200},
            "resources": {"active": {"micro_batch_size": 8, "vector_environments": 16}},
        }
    )
    assert config.budget.max_wall_seconds == 600
    assert config.resources.active.micro_batch_size == 8


@pytest.mark.parametrize("seed", [True, "0", -1, 3, 0.0])
def test_snapshot_rejects_unregistered_or_noninteger_seed(seed):
    with pytest.raises(ValueError, match="preregistered integer"):
        PilotConfig().snapshot_for_run(seed)


def test_snapshots_preserve_the_registered_declarations_without_mutation():
    config = PilotConfig()
    before = pilot_config_hash(config)
    snapshots = [config.snapshot_for_run(seed) for seed in config.run_seeds]
    assert [snapshot.pop("seed") for snapshot in snapshots] == [0, 1, 2]
    assert all(snapshot == config.model_dump(mode="json") for snapshot in snapshots)
    snapshots[0]["budget"]["max_wall_seconds"] = 1
    assert config.budget.max_wall_seconds == 1800
    assert pilot_config_hash(config) == before


@pytest.mark.parametrize("seeds", [(0, 1), (0, 1, 3), (0, 0, 1), (True, 1, 2)])
def test_seed_preregistration_cannot_be_replaced(seeds):
    with pytest.raises(ValidationError):
        PilotConfig(run_seeds=seeds)


@pytest.mark.parametrize("boundary", ["snapshot", "hash"])
def test_nested_model_copy_cannot_bypass_validation_at_output_boundaries(boundary):
    config = PilotConfig()
    invalid_profile = config.resources.active.model_copy(update={"mlx_memory_gib": 48})
    invalid_resources = config.resources.model_copy(update={"active": invalid_profile})
    invalid = config.model_copy(update={"resources": invalid_resources})
    with pytest.raises(ValidationError):
        if boundary == "snapshot":
            invalid.snapshot_for_run(0)
        else:
            pilot_config_hash(invalid)


def test_hash_is_format_independent_and_covers_resolved_configuration(tmp_path):
    first = tmp_path / "one.yaml"
    second = tmp_path / "two.yaml"
    first.write_text("teacher: none\nbudget:\n  max_wall_seconds: 1200\n")
    second.write_text(
        "# same resolved declaration\nbudget: {max_wall_seconds: 1200}\nteacher: none\n"
    )
    digest = pilot_config_hash(load_pilot_config(first))
    assert digest == pilot_config_hash(load_pilot_config(second))
    assert len(digest) == 64
    assert digest != pilot_config_hash(PilotConfig())


@pytest.mark.parametrize(
    "content",
    [
        "teacher: none\nteacher: none\n",
        "budget:\n  max_wall_seconds: 1200\n  max_wall_seconds: 1800\n",
        "modle: {}\n",
        "resources:\n  active:\n    unknown_setting: 1\n",
        "- not\n- a mapping\n",
        "",
        "1: wrong-key-type\n",
    ],
)
def test_loader_rejects_ambiguous_or_unknown_yaml(tmp_path, content):
    path = tmp_path / "bad.yaml"
    path.write_text(content)
    with pytest.raises(ValueError):
        load_pilot_config(path)


def test_manifest_fingerprints_source_separately_from_configuration(declaration_project):
    before = pilot_manifest(declaration_project)
    source = declaration_project.parents[1] / "src" / "ainerzero" / "cli.py"
    source.write_text("# changed implementation, same declarations\n")
    after = pilot_manifest(declaration_project)
    assert before["config_hash"] == after["config_hash"]
    assert before["manifest"]["source"]["sha256"] != after["manifest"]["source"]["sha256"]
    assert (
        after["manifest"]["source"]["files"]["src/ainerzero/cli.py"]
        == hashlib.sha256(source.read_bytes()).hexdigest()
    )


def test_cli_only_emits_a_declaration_and_never_starts_a_run(declaration_project, capsys):
    root = declaration_project.parents[1]
    before_files = {path.relative_to(root) for path in root.rglob("*") if path.is_file()}
    assert main(["check-pilot", "--config", str(declaration_project)]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["status"] == "valid"
    assert report["execution_status"] == "not_started"
    assert report["manifest"]["mechanisms"]["learning_implementation"] == "c0_prediction_only"
    assert {path.relative_to(root) for path in root.rglob("*") if path.is_file()} == before_files
    assert not (root / "artifacts").exists()


def test_cli_optional_report_matches_stdout_without_creating_database(declaration_project, capsys):
    root = declaration_project.parents[1]
    output = root / "reports" / "declaration.json"
    assert main(["check-pilot", "--config", str(declaration_project), "--output", str(output)]) == 0
    assert json.loads(output.read_text()) == json.loads(capsys.readouterr().out)
    assert not list(root.rglob("*.sqlite*"))
    assert not list(root.rglob("*.tmp"))


def test_cli_invalid_declaration_fails_without_writing_report(declaration_project, capsys):
    declaration_project.write_text("teacher: llm\n")
    output = declaration_project.parent / "invalid.json"
    assert main(["check-pilot", "--config", str(declaration_project), "--output", str(output)]) == 1
    captured = capsys.readouterr()
    assert not captured.out
    assert json.loads(captured.err)["status"] == "failed"
    assert not output.exists()


def test_check_pilot_does_not_import_a_neural_backend(declaration_project):
    script = """
import sys
from ainerzero.cli import main
result = main(sys.argv[1:])
assert not any(name.split('.')[0] in {'mlx', 'torch'} for name in sys.modules)
raise SystemExit(result)
"""
    result = subprocess.run(
        [sys.executable, "-c", script, "check-pilot", "--config", str(declaration_project)],
        capture_output=True,
        text=True,
        check=False,
        timeout=15,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["execution_status"] == "not_started"
