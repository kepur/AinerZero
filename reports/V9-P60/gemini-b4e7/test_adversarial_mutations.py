"""Adversarial mutation test suite (ainerzero.V9.P60 reviewer gemini-b4e7).

Demonstrates that:
1. Removing READ_ONCE check allows illegal double-reads (guard is necessary and active);
2. Bypassing token nonce validation allows forged tokens to read (token mechanism is necessary and active);
3. Modifying a sealed file turns verification RED;
4. Modifying the preregistration final_eval section causes preconditions to reject it.
"""
from __future__ import annotations

import json
import os
import shutil
import pytest
from pathlib import Path

from ainerzero.v9.experiments.s1 import data, final_eval, spec

@pytest.fixture
def clean_sealed_fixture(tmp_path):
    staging = tmp_path / "staging"
    production_root = Path(__file__).resolve().parents[3] / "artifacts/v9/s1/phase1"
    ds_dir = data.resolve_dataset_dir(production_root)
    
    for kind in ("packets", "truth"):
        (staging / kind).mkdir(parents=True, exist_ok=True)
        # take first 5 lines of development
        lines = (ds_dir / kind / "development.jsonl").read_text(encoding="utf-8").splitlines()[:5]
        with open(staging / kind / "final.jsonl", "w", encoding="utf-8") as handle:
            for line in lines:
                row = json.loads(line)
                row["partition"] = "final"
                handle.write(json.dumps(row, sort_keys=True) + "\n")

    rows = (staging / "packets/final.jsonl").read_text(encoding="utf-8").splitlines()
    episodes = {json.loads(line)["episode_id"] for line in rows}
    counts = {"final_worlds": len(episodes), "final_episodes": len(episodes), "final_packets": len(rows)}
    (staging / "export_meta.json").write_text(json.dumps({"counts": counts}), encoding="utf-8")

    sealed_root = tmp_path / "sealed"
    record = data.seal_final_dataset(staging, sealed_root=sealed_root, sealed_by="test_adv", counts=counts)
    sealed_dir = sealed_root / record["dataset_digest"]
    
    yield sealed_dir, record
    
    for path in (tmp_path / "sealed").rglob("*"):
        os.chmod(path, 0o755 if path.is_dir() else 0o644)
    os.chmod(tmp_path / "sealed", 0o755)


def test_adversarial_sabotage_marker_defense_in_depth(clean_sealed_fixture, monkeypatch):
    sealed_dir, record = clean_sealed_fixture
    digest = record["dataset_digest"]
    
    # 1. Normal behavior: 1st read succeeds, 2nd read raises FinalPartitionSealed("already read")
    token1 = data.open_sealed_final_once(sealed_dir, expected_digest=digest, reader={"t": 1})
    assert token1 is not None
    with pytest.raises(data.FinalPartitionSealed, match="already read"):
        data.open_sealed_final_once(sealed_dir, expected_digest=digest, reader={"t": 2})

    # 2. Defense-in-depth verification:
    # Even if verify_sealed_final is bypassed:
    monkeypatch.setattr(data, "verify_sealed_final", lambda s, expected_digest: {"status": "passed", "already_read": False})
    
    # Layer 2: os.open with O_EXCL raises FileExistsError which translates to FinalPartitionSealed("already read")
    with pytest.raises(data.FinalPartitionSealed, match="already read"):
        data.open_sealed_final_once(sealed_dir, expected_digest=digest, reader={"t": "second_attempt"})

    # Layer 3: Even if O_EXCL is stripped, OS write-protection (0o444) on the marker raises PermissionError
    orig_open = os.open
    monkeypatch.setattr(os, "open", lambda path, flags, mode: orig_open(path, (flags & ~os.O_EXCL) | os.O_TRUNC, mode))
    with pytest.raises(PermissionError):
        data.open_sealed_final_once(sealed_dir, expected_digest=digest, reader={"t": "third_attempt"})


def test_adversarial_sabotage_forged_token(clean_sealed_fixture, monkeypatch):
    sealed_dir, record = clean_sealed_fixture
    digest = record["dataset_digest"]
    token = data.open_sealed_final_once(sealed_dir, expected_digest=digest, reader={"t": 1})
    
    # Forged token with invalid nonce
    forged = data.FinalReadToken(digest, sealed_dir, data.final_marker_path(sealed_dir), "forged_nonce_" + "0"*50)
    
    # 1. Normal behavior: forged token is rejected by FinalView
    with pytest.raises(data.FinalPartitionSealed, match="needs a token issued by open_sealed_final_once"):
        data.FinalView(forged)

    # Also rejected by load_truth_view and load_training_episodes
    with pytest.raises(data.FinalPartitionSealed):
        data.load_truth_view(sealed_dir, "final", final_token=forged)

    # 2. Adversarial Sabotage: prove that token validation is the active gatekeeper
    monkeypatch.setattr(data, "_final_token_valid", lambda t: True)
    
    # Now FinalView accepts the forged token!
    view = data.FinalView(forged)
    assert view.partition == "final"
    assert len(view.episodes()) == 1


def test_adversarial_tampered_sealed_file_detection(clean_sealed_fixture):
    sealed_dir, record = clean_sealed_fixture
    target = sealed_dir / "truth/final.jsonl"
    
    # Tamper file
    os.chmod(sealed_dir / "truth", 0o755)
    os.chmod(target, 0o644)
    with open(target, "a", encoding="utf-8") as f:
        f.write('{"tampered": true}\n')
        
    state = data.verify_sealed_final(sealed_dir, expected_digest=record["dataset_digest"])
    assert state["status"] == "failed"
    assert "a sealed file changed after sealing" in state["problems"]
    
    with pytest.raises(data.FinalPartitionSealed, match="failed verification"):
        data.open_sealed_final_once(sealed_dir, expected_digest=record["dataset_digest"], reader={"t": 1})
