"""S1 resource gate tests: every registered line must refuse, for real (pure CPU).

Positive cases prove the gate admits a healthy snapshot; the broken controls
prove each line *independently* refuses with an explicit reason, including a
real subprocess invocation of ``ainerzero s1-phase1`` with tightened limits.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

import pytest

from ainerzero.v9.experiments.s1 import resource_gate, spec


def _limits(**overrides):
    limits = dict(spec.RESOURCE_LIMITS)
    limits.update(overrides)
    return limits


def _healthy_snapshot(**overrides):
    snapshot = resource_gate.ResourceSnapshot(
        process_rss_bytes=0.5 * resource_gate.GIB,
        mlx_active_bytes=0.2 * resource_gate.GIB,
        mlx_peak_bytes=0.3 * resource_gate.GIB,
        mlx_available=True,
        system_available_bytes=64.0 * resource_gate.GIB,
        swap_used_bytes=0.1 * resource_gate.GIB,
        swap_baseline_bytes=0.1 * resource_gate.GIB,
        disk_free_bytes=200.0 * resource_gate.GIB,
    )
    return replace(snapshot, **overrides)


def test_registered_limits_are_accepted_and_match_the_card():
    assert resource_gate.validate_limits(_limits()) == []
    assert spec.RESOURCE_LIMITS["process_memory_gib"] == 8.0
    assert spec.RESOURCE_LIMITS["mlx_memory_gib"] == 4.0
    assert spec.RESOURCE_LIMITS["system_reserve_gib"] == 16.0
    assert spec.RESOURCE_LIMITS["swap_growth_gib"] == 1.0
    assert spec.RESOURCE_LIMITS["training_duty_cycle"] == 0.25


@pytest.mark.parametrize(
    "overrides, needle",
    [
        ({"process_memory_gib": 9.0}, "process_memory_gib"),
        ({"mlx_memory_gib": 5.0}, "mlx_memory_gib"),
        ({"system_reserve_gib": 8.0}, "system_reserve_gib"),
        ({"swap_growth_gib": 2.0}, "swap_growth_gib"),
        ({"training_duty_cycle": 1.0}, "training_duty_cycle"),
        ({"disk_min_free_gib": 100.0}, "disk_min_free_gib"),
        ({"training_duty_cycle": 0.0}, "training_duty_cycle"),
    ],
)
def test_loosened_limits_are_refused(overrides, needle):
    reasons = resource_gate.validate_limits(_limits(**overrides))
    assert reasons, overrides
    assert any(needle in reason for reason in reasons), reasons


def test_tightened_limits_are_allowed_and_missing_keys_refused():
    tightened = _limits(process_memory_gib=1.0, mlx_memory_gib=0.5, training_duty_cycle=0.1)
    assert resource_gate.validate_limits(tightened) == []
    missing = _limits()
    del missing["mlx_memory_gib"]
    assert any("missing" in reason for reason in resource_gate.validate_limits(missing))
    extra = _limits(unknown_limit=1.0)
    assert any("unregistered" in reason for reason in resource_gate.validate_limits(extra))


def test_healthy_snapshot_is_admitted():
    assert resource_gate.evaluate(_healthy_snapshot(), _limits()) == []


@pytest.mark.parametrize(
    "overrides, needle",
    [
        ({"process_rss_bytes": 9.0 * resource_gate.GIB}, "process_memory_limit"),
        ({"mlx_active_bytes": 5.0 * resource_gate.GIB}, "mlx_memory_limit: active"),
        ({"mlx_peak_bytes": 5.0 * resource_gate.GIB}, "mlx_memory_limit: peak"),
        ({"system_available_bytes": 8.0 * resource_gate.GIB}, "system_reserve_limit"),
        ({"swap_used_bytes": 1.5 * resource_gate.GIB}, "swap_growth_limit"),
        ({"disk_free_bytes": 10.0 * resource_gate.GIB}, "disk_free_limit"),
    ],
)
def test_each_protection_line_refuses_with_an_explicit_reason(overrides, needle):
    reasons = resource_gate.evaluate(_healthy_snapshot(**overrides), _limits())
    assert reasons
    assert any(needle in reason for reason in reasons), reasons


def test_assert_start_with_injected_probes(tmp_path):
    healthy = _healthy_snapshot()
    probes = dict(
        rss_probe=lambda: healthy.process_rss_bytes,
        mlx_probe=lambda: {
            "available": True,
            "active_bytes": healthy.mlx_active_bytes,
            "peak_bytes": healthy.mlx_peak_bytes,
        },
        memory_probe=lambda: type("M", (), {"available": healthy.system_available_bytes})(),
        swap_probe=lambda: type("S", (), {"used": healthy.swap_used_bytes})(),
        disk_probe=lambda: healthy.disk_free_bytes,
    )
    snapshot = resource_gate.assert_start(_limits(), root=tmp_path, probes=probes)
    assert snapshot.process_rss_bytes == healthy.process_rss_bytes
    with pytest.raises(resource_gate.ResourceGateRefused) as excinfo:
        resource_gate.assert_start(
            _limits(), root=tmp_path, probes={**probes, "rss_probe": lambda: 9.0 * resource_gate.GIB}
        )
    assert "process_memory_limit" in str(excinfo.value)


def test_runtime_guard_stops_on_a_violation(tmp_path):
    healthy = _healthy_snapshot()
    probes = dict(
        rss_probe=lambda: healthy.process_rss_bytes,
        mlx_probe=lambda: {"available": True, "active_bytes": 0.0, "peak_bytes": 0.0},
        memory_probe=lambda: type("M", (), {"available": healthy.system_available_bytes})(),
        swap_probe=lambda: type("S", (), {"used": healthy.swap_used_bytes})(),
        disk_probe=lambda: healthy.disk_free_bytes,
    )
    guard = resource_gate.RuntimeGuard(_limits(), root=tmp_path, probes=probes, min_interval_seconds=0.0)
    assert guard.sample(force=True)["reasons"] == []
    broken = resource_gate.RuntimeGuard(
        _limits(),
        root=tmp_path,
        probes={**probes, "rss_probe": lambda: 20.0 * resource_gate.GIB},
        min_interval_seconds=0.0,
    )
    with pytest.raises(resource_gate.ResourceGateRefused) as excinfo:
        broken.sample(force=True)
    assert "process_memory_limit" in str(excinfo.value)


# --- real CLI refusals (subprocess, no model work) ------------------------
REPO_ROOT = Path(__file__).resolve().parents[3]


def _run_cli(args: list[str], tmp_path: Path) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env["PYTHONPATH"] = str(REPO_ROOT / "src")
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return subprocess.run(
        [sys.executable, "-m", "ainerzero.cli", "s1-phase1", *args],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=180,
    )


def test_cli_refuses_to_start_on_an_unmet_protection_line(tmp_path):
    limits_path = tmp_path / "tight_limits.json"
    limits_path.write_text(json.dumps(_limits(process_memory_gib=0.001)), encoding="utf-8")
    output_root = tmp_path / "out"
    result = _run_cli(
        ["--mode", "data", "--output-root", str(output_root), "--limits-file", str(limits_path)],
        tmp_path,
    )
    assert result.returncode == 2, (result.returncode, result.stdout, result.stderr)
    report = json.loads(result.stdout)
    assert report["status"] == "refused"
    assert report["stage"] == "resource_gate"
    assert any("process_memory_limit" in reason for reason in report["reasons"])
    # No compute artifact is produced when the gate refuses.
    assert not (output_root / "dataset").exists()


def test_cli_refuses_to_loosen_a_protection_line(tmp_path):
    limits_path = tmp_path / "loose_limits.json"
    limits_path.write_text(json.dumps(_limits(mlx_memory_gib=8.0)), encoding="utf-8")
    result = _run_cli(
        [
            "--mode",
            "data",
            "--output-root",
            str(tmp_path / "out"),
            "--limits-file",
            str(limits_path),
        ],
        tmp_path,
    )
    assert result.returncode == 2, (result.returncode, result.stdout, result.stderr)
    report = json.loads(result.stdout)
    assert report["status"] == "refused"
    assert any("loosening refused" in reason for reason in report["reasons"])


def test_cli_refuses_to_raise_the_prep_wall_budget(tmp_path):
    result = _run_cli(
        [
            "--mode",
            "data",
            "--output-root",
            str(tmp_path / "out"),
            "--wall-budget-seconds",
            "99999",
        ],
        tmp_path,
    )
    assert result.returncode == 1
    report = json.loads(result.stdout)
    assert report["status"] == "failed"
    assert "tighten" in report["error"]
