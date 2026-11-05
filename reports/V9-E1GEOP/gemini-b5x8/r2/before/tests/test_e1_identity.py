"""Tests for E1 frozen source & generator identity verification (ainerzero.V9.P83).

Verifies:
1. verify_frozen_identity happy path against frozen document.
2. Mutating any E1 implementation source file causes verification rejection.
3. Mutating any AWZ E0 generator source file causes verification rejection.
4. Missing implementation or generator source raises FileNotFoundError.
5. commands.py preflight blocks train/eval/generate-data/final-eval when identity is violated,
   without modifying ledger or starting run.
6. commands.py verify mode reports identity mismatch without rejecting.
7. generator_identity.json missing or inconsistent causes commands.py train to refuse.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path
import shutil
import pytest

from ainerzero.v9.experiments.e1 import commands, data_runner, identity, prereg, spec


def _setup_isolated_environment(tmp_path: Path) -> tuple[Path, Path, dict[str, Any], str]:
    """Create isolated copies of repo_root and awz_root with exact source structures."""
    fake_repo = tmp_path / "repo"
    fake_awz = tmp_path / "awz"
    fake_repo.mkdir(parents=True, exist_ok=True)
    fake_awz.mkdir(parents=True, exist_ok=True)

    # 1. Copy implementation sources to fake_repo
    real_repo = Path(spec.REPO_ROOT)
    for rel in spec.IMPLEMENTATION_SOURCES:
        src_file = real_repo / rel
        dst_file = fake_repo / rel
        dst_file.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src_file, dst_file)

    # 2. Copy generator sources to fake_awz
    real_awz = Path(spec.AWZ_ROOT)
    for rel in spec.GENERATOR_SOURCES:
        src_file = real_awz / rel
        dst_file = fake_awz / rel
        dst_file.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src_file, dst_file)

    # 3. Create frozen preregistration document from the isolated sources
    draft = prereg.build_draft(repo_root=fake_repo, awz_root=fake_awz)
    doc, digest = prereg.freeze(draft)
    return fake_repo, fake_awz, doc, digest


def test_verify_frozen_identity_happy_path(tmp_path: Path):
    """Verify happy path where runtime sources match frozen document exactly."""
    fake_repo, fake_awz, doc, digest = _setup_isolated_environment(tmp_path)
    res = identity.verify_frozen_identity(doc, repo_root=fake_repo, awz_root=fake_awz)
    assert res["status"] == "passed"
    assert len(res["source_digests"]) == len(spec.IMPLEMENTATION_SOURCES)
    assert len(res["generator_digests"]) == len(spec.GENERATOR_SOURCES)


def test_mutate_e1_sources_rejected(tmp_path: Path):
    """Verify mutating any of the E1 implementation source files causes verification rejection."""
    fake_repo, fake_awz, doc, digest = _setup_isolated_environment(tmp_path)

    for rel_path in spec.IMPLEMENTATION_SOURCES:
        target_file = fake_repo / rel_path
        orig_bytes = target_file.read_bytes()
        try:
            # Append comment mutation
            target_file.write_bytes(orig_bytes + b"\n# MUTATION_PROBE\n")
            with pytest.raises(identity.FrozenIdentityMismatchError) as exc_info:
                identity.verify_frozen_identity(doc, repo_root=fake_repo, awz_root=fake_awz)
            assert rel_path in exc_info.value.mismatches
            diff = exc_info.value.mismatches[rel_path]
            assert diff["document"] == doc["source_digests"][rel_path]
            assert diff["current"] != diff["document"]
        finally:
            # Restore original
            target_file.write_bytes(orig_bytes)


def test_mutate_generator_sources_rejected(tmp_path: Path):
    """Verify mutating any AWZ generator source file causes verification rejection."""
    fake_repo, fake_awz, doc, digest = _setup_isolated_environment(tmp_path)

    for rel_path in spec.GENERATOR_SOURCES:
        target_file = fake_awz / rel_path
        orig_bytes = target_file.read_bytes()
        try:
            # Append comment mutation
            target_file.write_bytes(orig_bytes + b"\n# MUTATION_GENERATOR_PROBE\n")
            with pytest.raises(identity.FrozenIdentityMismatchError) as exc_info:
                identity.verify_frozen_identity(doc, repo_root=fake_repo, awz_root=fake_awz)
            assert rel_path in exc_info.value.mismatches
            diff = exc_info.value.mismatches[rel_path]
            assert diff["document"] == doc["generator_digests"][rel_path]
            assert diff["current"] != diff["document"]
        finally:
            # Restore original
            target_file.write_bytes(orig_bytes)


def test_missing_source_file_raises_filenotfound(tmp_path: Path):
    """Verify missing implementation or generator source raises FileNotFoundError."""
    fake_repo, fake_awz, doc, digest = _setup_isolated_environment(tmp_path)

    # Missing implementation source
    target_impl = fake_repo / spec.IMPLEMENTATION_SOURCES[0]
    target_impl.unlink()
    with pytest.raises(FileNotFoundError, match="Implementation source file missing"):
        identity.verify_frozen_identity(doc, repo_root=fake_repo, awz_root=fake_awz)

    # Re-create and test missing generator source
    fake_repo, fake_awz, doc, digest = _setup_isolated_environment(tmp_path / "awz_missing")
    target_gen = fake_awz / spec.GENERATOR_SOURCES[0]
    target_gen.unlink()
    with pytest.raises(FileNotFoundError, match="Generator source file missing"):
        identity.verify_frozen_identity(doc, repo_root=fake_repo, awz_root=fake_awz)


def test_commands_preflight_blocks_compute_modes_on_identity_mismatch(tmp_path: Path):
    """Verify commands.py blocks train/eval/generate-data/final-eval when identity is violated."""
    fake_repo, fake_awz, doc, digest = _setup_isolated_environment(tmp_path)

    # Write prereg and research log with valid approval
    prereg_file = tmp_path / "prereg.json"
    prereg_file.write_text(json.dumps(doc), encoding="utf-8")

    research_log = tmp_path / "RESEARCH_LOG.md"
    research_log.write_text(
        f"# Research Log\n## R20261029-E1-approval\nAPPROVED e1-phase2 prereg document_sha256={digest}\n",
        encoding="utf-8",
    )

    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    # Write valid generator_identity.json
    gen_id_payload = {
        "generator_digests": doc["generator_digests"],
        "velocity_injection": doc["required_velocity_injection"],
    }
    (data_dir / "generator_identity.json").write_text(
        json.dumps(gen_id_payload, indent=2), encoding="utf-8"
    )

    # Mutate one implementation file in fake_repo
    mutated_file = fake_repo / spec.IMPLEMENTATION_SOURCES[0]
    mutated_file.write_text("MUTATED CONTENT", encoding="utf-8")

    ledger_file = tmp_path / "control.sqlite3"
    lock_file = tmp_path / "worker.lock"

    compute_modes = [
        {"mode": "generate-data"},
        {"mode": "train", "arm": "2", "family": "P", "seed": "42"},
        {"mode": "eval", "arm": "1", "family": "P"},
        {"mode": "final-eval", "family": "P"},
    ]

    for c_args in compute_modes:
        args = argparse.Namespace(
            repo_root=fake_repo,
            awz_root=fake_awz,
            prereg=prereg_file,
            research_log=research_log,
            data_dir=data_dir,
            output_root=tmp_path,
            ledger=ledger_file,
            lock_file=lock_file,
            **c_args,
        )
        res, code = commands.e1_phase2_command(args)
        assert code == commands.EXIT_FAILED
        assert res["status"] == "refused"
        assert res["stage"] == "identity_verification"
        assert not ledger_file.exists(), f"Ledger was written during refused execution for mode {c_args['mode']}"


def test_commands_verify_mode_reports_mismatch_without_rejecting(tmp_path: Path):
    """Verify commands.py verify mode reports mismatch in result dictionary but does not refuse."""
    fake_repo, fake_awz, doc, digest = _setup_isolated_environment(tmp_path)

    prereg_file = tmp_path / "prereg.json"
    prereg_file.write_text(json.dumps(doc), encoding="utf-8")

    research_log = tmp_path / "RESEARCH_LOG.md"
    research_log.write_text(
        f"# Research Log\n## R20261029-E1-approval\nAPPROVED e1-phase2 prereg document_sha256={digest}\n",
        encoding="utf-8",
    )

    # Mutate a generator file
    mutated_file = fake_awz / spec.GENERATOR_SOURCES[0]
    mutated_file.write_text("MUTATED GENERATOR", encoding="utf-8")

    args = argparse.Namespace(
        mode="verify",
        repo_root=fake_repo,
        awz_root=fake_awz,
        prereg=prereg_file,
        research_log=research_log,
        output_root=tmp_path,
    )
    res, code = commands.e1_phase2_command(args)
    assert code == commands.EXIT_COMPLETED
    assert res["status"] == "verified"
    assert "identity" in res
    assert res["identity"]["status"] == "mismatch"


def test_commands_train_refuses_when_generator_identity_json_mismatches(tmp_path: Path):
    """Verify train mode refuses when generator_identity.json in data_dir does not match prereg."""
    fake_repo, fake_awz, doc, digest = _setup_isolated_environment(tmp_path)

    prereg_file = tmp_path / "prereg.json"
    prereg_file.write_text(json.dumps(doc), encoding="utf-8")

    research_log = tmp_path / "RESEARCH_LOG.md"
    research_log.write_text(
        f"# Research Log\n## R20261029-E1-approval\nAPPROVED e1-phase2 prereg document_sha256={digest}\n",
        encoding="utf-8",
    )

    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    # Write mismatched generator_identity.json
    gen_id_payload = {
        "generator_digests": {"mismatched": "sha"},
        "velocity_injection": doc["required_velocity_injection"],
    }
    (data_dir / "generator_identity.json").write_text(
        json.dumps(gen_id_payload, indent=2), encoding="utf-8"
    )

    ledger_file = tmp_path / "control.sqlite3"
    lock_file = tmp_path / "worker.lock"

    args = argparse.Namespace(
        mode="train",
        arm="2",
        family="P",
        seed="42",
        repo_root=fake_repo,
        awz_root=fake_awz,
        prereg=prereg_file,
        research_log=research_log,
        data_dir=data_dir,
        output_root=tmp_path,
        ledger=ledger_file,
        lock_file=lock_file,
    )
    res, code = commands.e1_phase2_command(args)
    assert code == commands.EXIT_FAILED
    assert res["status"] == "refused"
    assert res["stage"] == "dataset_identity_verification"
    assert not ledger_file.exists()
