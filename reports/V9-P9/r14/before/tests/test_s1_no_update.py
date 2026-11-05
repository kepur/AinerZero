"""No-update proof tests (V9.P10 F4).

The smoke report's ``parameters_unchanged`` flag is a claim the product makes
about itself.  These tests decide it independently: they hash the parameters
themselves, and they also drive a case where a parameter really changed, so a
hard-coded ``True`` cannot survive.
"""

from __future__ import annotations

import hashlib
from types import SimpleNamespace

import numpy as np
import pytest

from ainerzero.v9.experiments.s1 import commands, smoke


class _DigestModel:
    """Minimal model with a mutable parameter block the test can hash itself."""

    ARCHITECTURE = "fake_smoke_model"

    def __init__(self):
        self.weights = {"w": np.zeros((3,), dtype=np.float32)}
        self.forward_calls = 0

    def forward_loss(self, batch):
        self.forward_calls += 1
        return SimpleNamespace(loss=np.float32(0.5), metrics={"prediction": np.float32(0.5)})


def _digest(model: _DigestModel) -> str:
    """Independent recomputation: the test's own hash of the parameter bytes."""
    return hashlib.sha256(np.ascontiguousarray(model.weights["w"]).tobytes()).hexdigest()


def _install_fakes(monkeypatch, *, perturb: bool) -> dict:
    """Install the fake smoke environment; returns the models it created."""
    import mlx.core as mx

    created: dict[str, _DigestModel] = {}

    def _make(arm_id: str) -> _DigestModel:
        model = _DigestModel()
        created[arm_id] = model
        return model

    manifest = {
        "counts": {
            "train_episodes": 4,
            "development_episodes": 4,
            "train_packets": 16,
            "development_packets": 16,
        },
        "generation_seconds": 12.5,
        "total_bytes": 1024,
    }
    monkeypatch.setattr(smoke.data, "load_manifest", lambda dataset_dir: manifest)
    monkeypatch.setattr(
        smoke.data, "dataset_identity", lambda manifest: {"dataset_digest": "a" * 64}
    )
    monkeypatch.setattr(
        smoke.data, "load_training_windows", lambda *a, **k: {"obs": np.zeros((4, 2, 72))}
    )
    monkeypatch.setattr(
        smoke.data, "load_development_windows", lambda *a, **k: {"obs": np.zeros((4, 2, 72))}
    )
    monkeypatch.setattr(smoke.data, "fixed_batch", lambda *a, **k: {"obs": np.zeros((2, 2, 72))})
    monkeypatch.setattr(smoke.arms, "build_trainable_arm", lambda arm_id, seed: _make(arm_id))
    monkeypatch.setattr(smoke.arms, "parameter_sha256", _digest)
    monkeypatch.setattr(smoke.arms, "count_parameters", lambda model: 3)
    monkeypatch.setattr(
        smoke.arms,
        "load_d_candidate",
        lambda: (
            _make("arm1"),
            {
                "architecture": "fake_smoke_model",
                "parameter_count": 3,
                "optimizer_steps": 0,
                "identity": {"stub": True},
            },
        ),
    )
    monkeypatch.setattr(smoke.arms, "d_candidate_fixed_batch", lambda: {"obs": np.zeros((2, 2, 72))})
    monkeypatch.setattr(
        smoke.arms,
        "d_candidate_forward_loss",
        lambda model, batch, seed: SimpleNamespace(
            loss=np.float32(0.5), metrics={"prediction": np.float32(0.5)}
        ),
    )

    def _measure(callable_forward, *, repeats):
        output = callable_forward()
        if perturb:
            # Simulate an accidental optimizer step inside the measured block.
            for candidate in created.values():
                candidate.weights["w"] = candidate.weights["w"] + np.float32(1.0)
        return [0.001] * int(repeats), output, 0.5

    monkeypatch.setattr(smoke, "_measure", _measure)
    monkeypatch.setattr(mx, "set_default_device", lambda *a, **k: None, raising=False)
    monkeypatch.setattr(mx, "reset_peak_memory", lambda *a, **k: None, raising=False)
    monkeypatch.setattr(mx, "get_peak_memory", lambda *a, **k: 1024, raising=False)
    monkeypatch.setattr(mx, "eval", lambda *a, **k: None)
    return created


def test_smoke_reports_no_update_when_the_digests_match(monkeypatch, tmp_path):
    created = _install_fakes(monkeypatch, perturb=False)
    result = smoke.run_smoke(tmp_path, batch_size=2, repeats=1)
    assert result["parameters_unchanged"] is True
    for arm_id in ("arm2", "arm3", "arm4"):
        block = result["trainable_arms"][arm_id]
        assert block["parameters_unchanged"] is True
        assert block["parameter_sha256_before"] == block["parameter_sha256_after"]
        assert block["parameter_sha256_after"] == _digest(created[arm_id])
    assert result["d_candidate"]["parameter_sha256_before"] == _digest(created["arm1"])


def test_smoke_reports_an_update_when_a_parameter_really_changed(monkeypatch, tmp_path):
    """A hard-coded ``parameters_unchanged = True`` must fail here (P10 M12)."""
    created = _install_fakes(monkeypatch, perturb=True)
    result = smoke.run_smoke(tmp_path, batch_size=2, repeats=1)
    assert result["parameters_unchanged"] is False
    initial = hashlib.sha256(np.zeros((3,), dtype=np.float32).tobytes()).hexdigest()
    for arm_id in ("arm2", "arm3", "arm4"):
        block = result["trainable_arms"][arm_id]
        assert block["parameters_unchanged"] is False
        # The test recomputes the initial state itself instead of trusting the report.
        assert block["parameter_sha256_before"] == initial
        assert block["parameter_sha256_after"] != initial
    # The D candidate is measured last, so its after-digest is still observable.
    assert result["d_candidate"]["parameter_sha256_after"] == _digest(created["arm1"])
    assert result["d_candidate"]["parameters_unchanged"] is False


def _metrics(digest_by_arm: dict) -> dict:
    return {
        "smoke_seed": 0,
        "trainable_arms": {
            arm_id: {
                "parameter_sha256_before": digest,
                "parameter_sha256_after": digest,
            }
            for arm_id, digest in digest_by_arm.items()
            if arm_id != "arm1"
        },
        "d_candidate": {
            "parameter_sha256_before": digest_by_arm["arm1"],
            "parameter_sha256_after": digest_by_arm["arm1"],
        },
    }


def test_verify_recomputes_parameters_instead_of_trusting_the_flag(monkeypatch):
    good = {"arm1": "1" * 64, "arm2": "2" * 64, "arm3": "3" * 64, "arm4": "4" * 64}
    monkeypatch.setattr(smoke, "parameter_digests", lambda seed=0: dict(good))
    assert commands._independent_parameter_check(_metrics(good))["status"] == "passed"

    stale = dict(good, arm3="9" * 64)
    report = commands._independent_parameter_check(_metrics(stale))
    assert report["status"] == "failed"
    assert report["arms"]["arm3"]["match"] is False
    assert report["arms"]["arm2"]["match"] is True

    assert commands._independent_parameter_check(None)["status"] == "not_available"


def test_verify_flags_a_smoke_report_that_claims_an_update(monkeypatch):
    good = {"arm1": "1" * 64, "arm2": "2" * 64, "arm3": "3" * 64, "arm4": "4" * 64}
    monkeypatch.setattr(smoke, "parameter_digests", lambda seed=0: dict(good))
    metrics = _metrics(good)
    metrics["trainable_arms"]["arm2"]["parameter_sha256_after"] = "0" * 64
    report = commands._independent_parameter_check(metrics)
    assert report["status"] == "failed"
    assert report["arms"]["arm2"]["match"] is False
