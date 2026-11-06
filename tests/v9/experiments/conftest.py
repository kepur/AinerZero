"""Fixtures for the S1 phase-1 (ainerzero.V9.P9) CPU test suite.

Synthetic payloads are built by hand (the eight whitelisted ObservationPacket
fields the v9 contract gate enforces); the synthetic producer staging directory
mirrors ``awz_export`` output so ``data.finalize_dataset`` is exercised without
AnimeWorldZero.  Everything is pure CPU.
"""

from __future__ import annotations

import pytest

from ainerzero.v9.experiments.s1 import data

from s1_testkit import make_plan, write_staging


@pytest.fixture(autouse=True)
def _no_real_mlx_in_resource_probe(request, monkeypatch):
    """A39: the default pure-CPU entry imports no real MLX, at collection or at run time.

    ``resource_gate.collect`` calls ``mlx_memory_probe``, which imports ``mlx.core``
    best-effort, whenever a mode passes the start gate.  ``resource_gate.py`` is bound
    by the frozen S1 final preregistration, so it is not edited.  Outside native-marked
    tests the probe returns its own documented degraded record (MLX unavailable)
    instead of loading MLX into the shared test process; the 38 tests that reach it
    were checked to pass with MLX blocked (2026-11-06 report).
    """
    if request.node.get_closest_marker("native_mlx") is not None:
        return
    from ainerzero.v9.experiments.s1 import resource_gate

    def _unavailable() -> dict:
        return {
            "available": False,
            "active_bytes": 0.0,
            "peak_bytes": 0.0,
            "error": "real MLX is not imported in the default pure-CPU test entry (A39)",
        }

    monkeypatch.setattr(resource_gate, "mlx_memory_probe", _unavailable)


@pytest.fixture
def synthetic_dataset(tmp_path):
    """Finalize a synthetic dataset; returns (manifest, dataset_dir, plan)."""
    plan = make_plan()
    staging = tmp_path / "staging"
    write_staging(staging, plan=plan)
    final_dir = tmp_path / "dataset"
    manifest = data.finalize_dataset(
        staging,
        final_dir,
        plan=plan,
        generation_seconds=12.5,
        generation_command=["synthetic-producer"],
    )
    return manifest, final_dir, plan


@pytest.fixture
def canonical_root(tmp_path, monkeypatch):
    """r6: an isolated canonical phase-1 root with a recognised central ledger.

    Bounded modes (train/eval) only run at ``spec.PHASE1_ROOT`` and register in
    the central RunStore below it.  Tests point that constant at an isolated
    directory (with a ledger carrying the phase preparation experiment, so the
    fail-closed identity check recognises it) instead of touching the real
    repository ledger under ``artifacts/v9/s1/phase1/``.
    """
    from ainerzero.v9.experiments.s1 import worker

    # r7: the anchor is one dict; the isolated host must therefore also own the
    # phase-1 directory, so REGISTERED_HOST_ROOT/<artifacts/v9/s1/phase1> is the
    # same directory the fixture hands out as PHASE1_ROOT.
    from s1_testkit import install_test_host

    root = install_test_host(monkeypatch, tmp_path, create_ledger=False)
    # Existing r5/r6 tests spell the canonical root as ``tmp_path/"phase1"``.
    # A symlink keeps that spelling while the anchor derives the same directory.
    alias = tmp_path / "phase1"
    if not alias.exists():
        alias.symlink_to(root, target_is_directory=True)
    ledger = worker.PrepLedger(root / "control.sqlite3")
    try:
        ledger.store.create_experiment(
            worker.prep_experiment_manifest(),
            worker.PREP_REQUEST_ID,
            worker.PREP_EXPERIMENT_ID,
        )
    finally:
        ledger.close()
    return root
