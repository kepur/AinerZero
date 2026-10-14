"""Tests for runtime preflight checks, GPU observations, and run_when_quiet guards."""

import hashlib
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from ainerzero.runtime.preflight import (
    POLICY_REVISION,
    PreflightError,
    check_available_memory,
    compute_file_sha256,
    evaluate_gpu_policy,
    probe_external_gpu,
    verify_frozen_identities,
)


def test_check_available_memory_success():
    mock_mem = SimpleNamespace(available=20 * (1024**3))
    avail = check_available_memory(16.0, memory_info=mock_mem)
    assert avail == pytest.approx(20.0)


def test_check_available_memory_insufficient_raises():
    mock_mem = SimpleNamespace(available=15.9 * (1024**3))
    with pytest.raises(PreflightError, match="Available memory 15.90 GiB is below required 16.00 GiB"):
        check_available_memory(16.0, memory_info=mock_mem)


def test_compute_file_sha256_success(tmp_path):
    f = tmp_path / "test.txt"
    content = b"hello world 12345"
    f.write_bytes(content)
    expected = hashlib.sha256(content).hexdigest()
    assert compute_file_sha256(f) == expected


def test_compute_file_sha256_missing_file_raises(tmp_path):
    f = tmp_path / "nonexistent.txt"
    with pytest.raises(PreflightError, match="Target file does not exist"):
        compute_file_sha256(f)


def test_verify_frozen_identities_all_match(tmp_path):
    f1 = tmp_path / "file1.json"
    f2 = tmp_path / "file2.py"
    f1.write_bytes(b'{"key": "val"}')
    f2.write_bytes(b'print("ok")')
    digests = {
        f1: hashlib.sha256(f1.read_bytes()).hexdigest(),
        f2: hashlib.sha256(f2.read_bytes()).hexdigest(),
    }
    verified = verify_frozen_identities(digests)
    assert str(f1) in verified and str(f2) in verified


def test_verify_frozen_identities_mismatch_raises(tmp_path):
    f1 = tmp_path / "file1.json"
    f1.write_bytes(b'{"key": "val"}')
    digests = {
        f1: "0000000000000000000000000000000000000000000000000000000000000000",
    }
    with pytest.raises(PreflightError, match="Frozen identity digest mismatch detected"):
        verify_frozen_identities(digests)


def test_verify_frozen_identities_git_status_match(tmp_path):
    with patch("ainerzero.runtime.preflight.get_git_status_sha256", return_value="abc123sha"):
        verified = verify_frozen_identities({}, expected_git_status_sha256="abc123sha")
        assert verified["git_status_sha256"] == "abc123sha"


def test_verify_frozen_identities_git_status_mismatch_raises(tmp_path):
    with patch("ainerzero.runtime.preflight.get_git_status_sha256", return_value="changed_git_sha"):
        with pytest.raises(PreflightError, match="Working tree git status changed"):
            verify_frozen_identities({}, expected_git_status_sha256="original_git_sha")


# --- C2 External GPU observation and policy tests ---

def test_probe_external_gpu_idle_success():
    mock_payload = '{"free": true, "reason": "", "light": "ok", "ainerzero": ""}'
    obs = probe_external_gpu(
        http_getter=lambda url: mock_payload,
        ltx_probe=lambda: False,
    )
    assert obs["state"] == "free"
    assert obs["relay_gpu_free"] is True
    assert obs["ltx_busy"] is False
    assert obs["policy_revision"] == POLICY_REVISION
    assert not obs["busy_reasons"]


def test_probe_external_gpu_busy_relay_and_ltx():
    # 1. Busy from relay
    busy_payload = '{"free": false, "reason": "heavy task running", "ainerzero": ""}'
    obs1 = probe_external_gpu(
        http_getter=lambda url: busy_payload,
        ltx_probe=lambda: False,
    )
    assert obs1["state"] == "busy"
    assert any("heavy task running" in r for r in obs1["busy_reasons"])

    # 2. Busy from local LTX process
    free_payload = '{"free": true, "reason": "", "ainerzero": ""}'
    obs2 = probe_external_gpu(
        http_getter=lambda url: free_payload,
        ltx_probe=lambda: True,
    )
    assert obs2["state"] == "busy"
    assert any("LTX" in r for r in obs2["busy_reasons"])


def test_probe_external_gpu_unknown_cases():
    # Connection error or malformed payload -> state="unknown"
    def raise_err(url):
        raise ConnectionRefusedError("relay server down")

    obs = probe_external_gpu(
        http_getter=raise_err,
        ltx_probe=lambda: None,
    )
    assert obs["state"] == "unknown"
    assert obs["relay_gpu_free"] is None
    assert obs["ltx_busy"] is None
    assert any("relay /api/gpu query failed" in n for n in obs["notes"])


def test_evaluate_gpu_policy_lightweight_tier_always_allows():
    # Lightweight tasks (AinerZero / Godot) are purely informational per ADR-0009
    # Even if GPU is busy or unknown, lightweight tasks are allowed without rejection
    busy_obs = {"state": "busy", "busy_reasons": ["heavy diffusion running"]}
    ok, reasons = evaluate_gpu_policy(busy_obs, is_heavy=False)
    assert ok is True
    assert reasons == []

    unknown_obs = {"state": "unknown", "busy_reasons": []}
    ok, reasons = evaluate_gpu_policy(unknown_obs, is_heavy=False)
    assert ok is True
    assert reasons == []


def test_evaluate_gpu_policy_heavy_tier_rejects_busy_and_unknown():
    # Heavy tasks (LTX, large diffusion) require mutual exclusion
    free_obs = {"state": "free", "busy_reasons": []}
    ok, reasons = evaluate_gpu_policy(free_obs, is_heavy=True)
    assert ok is True
    assert reasons == []

    busy_obs = {"state": "busy", "busy_reasons": ["external LTX active"]}
    ok, reasons = evaluate_gpu_policy(busy_obs, is_heavy=True)
    assert ok is False
    assert any("external LTX active" in r for r in reasons)

    unknown_obs = {"state": "unknown", "busy_reasons": []}
    ok, reasons = evaluate_gpu_policy(unknown_obs, is_heavy=True)
    assert ok is False
    assert any("unknown" in r for r in reasons)


def test_run_when_quiet_preflight_integration(tmp_path):
    import importlib.util

    script_path = Path(__file__).resolve().parents[1] / "artifacts/reports/E24-mixed/run_when_quiet.py"
    spec = importlib.util.spec_from_file_location("rwq", script_path)
    rwq = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(rwq)

    # The registered E24 anchors stay the old freeze. Success uses a temp snapshot.
    assert rwq.REGISTERED_FROZEN_DIGESTS["src/ainerzero/cli.py"] == (
        "544a512241fd26d974d747c6c5636ccb6be36ac0b569a445c966d09ee35fac51"
    )
    snapshot = {}
    for index in range(13):
        path = tmp_path / f"snapshot-{index}.bin"
        path.write_bytes(f"known-snapshot-{index}".encode())
        snapshot[str(path)] = hashlib.sha256(path.read_bytes()).hexdigest()

    # Normal lightweight preflight check passes
    mock_free_gpu = {"state": "free", "busy_reasons": [], "policy_revision": POLICY_REVISION}
    res = rwq.preflight_check(frozen_digests=snapshot, external_gpu_obs=mock_free_gpu)
    assert res["status"] == "passed"
    assert res["available_gib"] >= 16.0
    assert res["verified_identities_count"] == 13
    assert res["is_heavy"] is False
    assert res["gpu_observation"]["state"] == "free"

    # Lightweight check allows busy GPU
    mock_busy_gpu = {"state": "busy", "busy_reasons": ["busy"], "policy_revision": POLICY_REVISION}
    res_light_busy = rwq.preflight_check(frozen_digests=snapshot, external_gpu_obs=mock_busy_gpu, is_heavy=False)
    assert res_light_busy["status"] == "passed"

    # Heavy check rejects busy GPU
    with pytest.raises(PreflightError, match="External GPU policy rejected launch"):
        rwq.preflight_check(frozen_digests=snapshot, external_gpu_obs=mock_busy_gpu, is_heavy=True)

    with pytest.raises(PreflightError, match="below required"):
        rwq.preflight_check(min_memory_gib=999999.0, frozen_digests=snapshot)

    bad = dict(snapshot)
    bad[next(iter(bad))] = "bad" * 16
    with pytest.raises(PreflightError, match="Frozen identity digest mismatch detected"):
        rwq.preflight_check(frozen_digests=bad)

    missing = dict(snapshot)
    missing[str(tmp_path / "absent.bin")] = "ab" * 32
    with pytest.raises(PreflightError, match="does not exist"):
        rwq.preflight_check(frozen_digests=missing)

    with pytest.raises(PreflightError, match="Frozen identity digest mismatch detected"):
        rwq.preflight_check()

    with pytest.raises(PreflightError, match="Working tree git status changed"):
        rwq.preflight_check(frozen_digests=snapshot, expected_git_sha="outdated_git_status_sha")
