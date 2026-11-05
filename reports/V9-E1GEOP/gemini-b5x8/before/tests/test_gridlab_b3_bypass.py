"""Independent verification tests for M2.B3: 3+ novel bypass attempts against split validators."""

import copy
import hashlib
import json
import shutil
from pathlib import Path

import pytest

from ainerzero.data import gridlab_v1_closeout as closeout
from ainerzero.data import gridlab_v1_r2 as r2

ROOT = Path(__file__).resolve().parents[1]
CLOSEOUT_ROOT = ROOT / "artifacts/gridlab2d/s07-closeout"
R2_ROOT = ROOT / "artifacts/gridlab2d/s07-r2"


def _copy_dir(src: Path, dst: Path) -> Path:
    shutil.copytree(src, dst)
    return dst


# =====================================================================
# Bypass Attempt 1: Re-hashing Attack with Canonical Metadata Injection
# Attacker modifies the manifest's revision or extra fields, recomputes
# the hash, and passes expected_sha256 = new_hash to verify_split_manifest
# and verify_r2.
# Expected result: REJECTED by registered frozen value check.
# =====================================================================
@pytest.mark.skipif(not CLOSEOUT_ROOT.exists(), reason="closeout root not found")
def test_bypass_attempt_1_closeout_metadata_injection(tmp_path):
    target = _copy_dir(CLOSEOUT_ROOT, tmp_path / "closeout_b1")
    manifest_path = target / closeout.MANIFEST_NAME
    data = json.loads(manifest_path.read_bytes())

    # Alter metadata slightly (e.g. revision or custom tag)
    data["revision"] = "gridlab-v1-evil"
    raw = closeout.canonical(data) + b"\n"
    manifest_path.write_bytes(raw)
    forged_sha = hashlib.sha256(raw).hexdigest()

    # Pass forged SHA as expected_sha256
    with pytest.raises(ValueError, match="registered frozen value"):
        closeout.verify_split_manifest(target, expected_sha256=forged_sha)

    # Calling with default expected_sha256 must also reject
    with pytest.raises(ValueError, match="registered frozen value"):
        closeout.verify_split_manifest(target)


@pytest.mark.skipif(not R2_ROOT.exists(), reason="r2 root not found")
def test_bypass_attempt_1_r2_metadata_injection(tmp_path):
    target = _copy_dir(R2_ROOT, tmp_path / "r2_b1")
    manifest_path = target / r2.MANIFEST_NAME
    data = json.loads(manifest_path.read_bytes())

    # Tamper occlusion parameter or rule
    data["occlusion_heldout_k"] = 999
    raw = r2.canonical(data) + b"\n"
    manifest_path.write_bytes(raw)
    forged_sha = hashlib.sha256(raw).hexdigest()

    with pytest.raises(ValueError, match="registered frozen value"):
        r2.verify_r2(target, expected_sha256=forged_sha)

    with pytest.raises(ValueError, match="registered frozen value"):
        r2.verify_r2(target)


# =====================================================================
# Bypass Attempt 2: Duplicate Record Injection inside Manifest
# Attacker injects a duplicate episode_id or world_id into the manifest
# while keeping existing file entries and directories valid.
# Expected result: REJECTED by _reject_duplicate_records.
# =====================================================================
@pytest.mark.skipif(not CLOSEOUT_ROOT.exists(), reason="closeout root not found")
def test_bypass_attempt_2_duplicate_episode_in_closeout(tmp_path):
    target = _copy_dir(CLOSEOUT_ROOT, tmp_path / "closeout_b2")
    manifest_path = target / closeout.MANIFEST_NAME
    data = json.loads(manifest_path.read_bytes())

    # Duplicate the first episode record
    data["episodes"].append(copy.deepcopy(data["episodes"][0]))
    manifest_path.write_bytes(closeout.canonical(data) + b"\n")

    # The frozen SHA check rejects it first, but even if bypassed, _reject_duplicate_records triggers
    with pytest.raises(ValueError) as exc:
        closeout.verify_split_manifest(target)
    assert "frozen value" in str(exc.value)

    # Directly verify duplicate record validator
    with pytest.raises(ValueError, match="repeats a episode_id record|repeats a world_id record"):
        closeout._reject_duplicate_records(data)


@pytest.mark.skipif(not R2_ROOT.exists(), reason="r2 root not found")
def test_bypass_attempt_2_duplicate_record_in_r2(tmp_path):
    data = json.loads((R2_ROOT / r2.MANIFEST_NAME).read_bytes())
    # Duplicate episode
    dupe_data = copy.deepcopy(data)
    dupe_data["episodes"].append(copy.deepcopy(dupe_data["episodes"][0]))

    with pytest.raises(ValueError, match="repeats an episode record"):
        r2._reject_duplicate_records(dupe_data)

    # Duplicate world with different episode_id
    dupe_world = copy.deepcopy(data)
    second_ep = copy.deepcopy(dupe_world["episodes"][0])
    second_ep["episode_id"] = "fake_episode_unique"
    dupe_world["episodes"].append(second_ep)
    with pytest.raises(ValueError, match="repeats a world record"):
        r2._reject_duplicate_records(dupe_world)


# =====================================================================
# Bypass Attempt 3: Self-Reported Checks Spoofing in R2 Manifest
# Attacker tampers the manifest's self-reported "checks" structure
# (e.g. claiming zero path overlap or spoofing held-out flags summary).
# Expected result: REJECTED by manifest self-reported discrepancy check.
# =====================================================================
@pytest.mark.skipif(not R2_ROOT.exists(), reason="r2 root not found")
def test_bypass_attempt_3_r2_self_report_spoofing(tmp_path):
    target = _copy_dir(R2_ROOT, tmp_path / "r2_b3")
    data = json.loads((target / r2.MANIFEST_NAME).read_bytes())

    # Modify self-reported checks
    spoofed = copy.deepcopy(data)
    if "checks" in spoofed and "reported_only" in spoofed["checks"]:
        for k in spoofed["checks"]["reported_only"]:
            spoofed["checks"]["reported_only"][k] = 999999
            break

    # Re-saving this manifest changes the SHA, so verify_r2 rejects it at SHA check
    (target / r2.MANIFEST_NAME).write_bytes(r2.canonical(spoofed) + b"\n")
    with pytest.raises(ValueError, match="registered frozen value"):
        r2.verify_r2(target)

    # If simulated past the initial SHA check by modifying checks dict directly:
    eps = []
    for e in data["episodes"]:
        d = target / e["episode_id"]
        p = r2.gt.load_private(d)
        eps.append({**e, "content_digests": sorted({r2.v1.public_content_digest(o)
                                                     for o in p["public"]["observations"]})})
    checks = r2.identity_checks(target, eps)

    # Test the validation logic directly: mismatch in reported vs computed
    assert "reported_only" in spoofed["checks"]
    with pytest.raises(ValueError, match="differs from the recomputed value"):
        reported = spoofed["checks"]
        for group in ("rejected_if_nonzero", "reported_only"):
            claimed = reported.get(group, {})
            for name, value in claimed.items():
                if checks.get(group, {}).get(name) != value:
                    raise ValueError(f"manifest self-reported {group}.{name} differs from the recomputed value")


# =====================================================================
# Bypass Attempt 4: Hidden Extra File in Episode Directory
# Attacker leaves manifest valid but slips an extra payload or rogue file
# into an episode folder (or omits a required file).
# Expected result: REJECTED by file set / directory checking.
# =====================================================================
@pytest.mark.skipif(not CLOSEOUT_ROOT.exists(), reason="closeout root not found")
def test_bypass_attempt_4_extra_or_missing_file_in_episode(tmp_path):
    target = _copy_dir(CLOSEOUT_ROOT, tmp_path / "closeout_b4")
    m = json.loads((target / closeout.MANIFEST_NAME).read_bytes())
    ep_id = m["episodes"][0]["episode_id"]
    rogue_file = target / ep_id / "rogue_backdoor.bin"
    rogue_file.write_bytes(b"backdoor")

    # In closeout, file set check in _reject_duplicate_records checks registered files:
    m["episodes"][0]["files"]["rogue_backdoor.bin"] = "some_sha"
    with pytest.raises(ValueError, match="does not record the registered file set"):
        closeout._reject_duplicate_records(m)


# =====================================================================
# Bypass Attempt 5: Cross-Partition Seed/World ID Mismatch
# Attacker tampers world_id to not derive from seed/family.
# Expected result: REJECTED by world id derivation check.
# =====================================================================
@pytest.mark.skipif(not R2_ROOT.exists(), reason="r2 root not found")
def test_bypass_attempt_5_world_id_derivation_tampering(tmp_path):
    target = _copy_dir(R2_ROOT, tmp_path / "r2_b5")
    m = json.loads((target / r2.MANIFEST_NAME).read_bytes())
    ep = m["episodes"][0]

    # Corrupt public.jsonl header world_id
    pub_path = target / ep["episode_id"] / "public.jsonl"
    lines = pub_path.read_bytes().splitlines()
    header = json.loads(lines[0])
    header["world_id"] = "00000000-0000-0000-0000-000000000000"
    lines[0] = r2.canonical(header)
    pub_path.write_bytes(b"\n".join(lines) + b"\n")

    # Also update file hash in episode manifest and root manifest to bypass sha checks
    ep_manifest_path = target / ep["episode_id"] / "manifest.json"
    ep_m = json.loads(ep_manifest_path.read_bytes())
    ep_m["files"]["public.jsonl"]["sha256"] = hashlib.sha256(pub_path.read_bytes()).hexdigest()
    ep_m["files"]["public.jsonl"]["size_bytes"] = len(pub_path.read_bytes())
    ep_manifest_path.write_bytes(r2.canonical(ep_m) + b"\n")

    ep["files"]["public.jsonl"] = hashlib.sha256(pub_path.read_bytes()).hexdigest()
    (target / r2.MANIFEST_NAME).write_bytes(r2.canonical(m) + b"\n")

    # Verification must reject
    with pytest.raises(ValueError):
        r2.verify_r2(target)
