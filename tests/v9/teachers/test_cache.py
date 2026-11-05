"""Teacher cache tests covering F1–F4, F8–F12 (CPU only)."""

from __future__ import annotations

import json
import multiprocessing
import os
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, "src")

import ainerzero.v9.teachers.cache as cache_mod
from ainerzero.v9.teachers.cache import (
    CrossPartitionError,
    HashMismatchError,
    ImmutableConflictError,
    MetadataIncompleteError,
    SchemaValidationError,
    TeacherCacheError,
    compute_entry_id,
    set_cache_root,
    sha,
    sha_bytes,
    store_problems,
    train_eligible,
    validate_schema,
)


@pytest.fixture
def temp_cache_dir():
    with tempfile.TemporaryDirectory() as tmpdir:
        cache = set_cache_root(Path(tmpdir))
        yield cache
        cache_mod._default_cache = None


def _license(train: bool = True) -> dict:
    return {
        "license_id": "MIT",
        "source_url": "https://example.com/license",
        "verified_at": "2026-10-20",
        "scope": {
            "reference": True,
            "train": train,
            "eval": True,
            "commercial_output": True,
            "redistribute": True,
        },
        "approval_ref": None,
    }


@pytest.fixture
def sample_key_material():
    return {
        "teacher": {
            "teacher_id": "vjepa2.1-vitl",
            "variant": "synthetic-test",
            "teacher_kind": "feature",
            "weights": [{"file": "model.safetensors", "sha256": "a" * 64}],
            "code_revision": "abcdefg",
            "runtime": {
                "framework": "mlx",
                "framework_version": "0.1.0",
                "compute_units": "gpu",
                "dtype": "float32",
            },
        },
        "preprocess": {
            "spec_sha256": "b" * 64,
            "resolution": [384, 384],
            "frames": 4,
            "normalization": "imagenet",
            "token_policy": {"kind": "none"},
        },
        "input": {
            "sha256": "c" * 64,
            "media_type": "video/x-raw-rgb24",
            "time_domain": {
                "clock": "episode_relative",
                "episode_id": "test-episode-001",
                "epoch_id": "test-epoch-001",
                "tick_hz": 120,
            },
            "timestamps_ticks": [0, 12, 24, 36],
            "timestamps_s": [0.0, 0.1, 0.2, 0.3],
        },
    }


@pytest.fixture
def sample_blob_args(sample_key_material):
    cache_key = sha(sample_key_material)
    return {
        "cache_key": cache_key,
        "key_material": sample_key_material,
        "teacher_license": _license(True),
        "reproducibility": "numeric",
        "generation_info": cache_mod.default_generation(),
        "tolerance": {"metric": "cosine_min", "value": 0.999},
    }


def _make_entry(cache_key: str, sample_key_material, partition="train", train_license=True):
    entry = {
        "schema_version": "az.v9.teacher_cache.v2",
        "record_type": "teacher_entry",
        "cache_key": cache_key,
        "source": {
            "world_key": "test:world",
            "partition": partition,
            "manifest_ref": {"manifest_id": "test-manifest", "source_id": "test-source-1"},
            "timestamps_ticks": [0, 12, 24, 36],
            "timestamps_s": [0.0, 0.1, 0.2, 0.3],
            "time_domain": sample_key_material["input"]["time_domain"],
        },
        "provenance": {
            "source_type": "teacher_feature",
            "upstream": {
                "system": "ainerzero",
                "origin": "observed",
                "actor": {
                    "kind": "student",
                    "actor_id": "student",
                    "policy_revision": "r1",
                },
                "input_ref": {"sha256": "c" * 64, "uri": "test://input"},
                "eligibility": {
                    "train": True,
                    "basis": "admit_training",
                    "revision_ref": None,
                },
            },
            "derivation": {
                "teacher_id": "vjepa2.1-vitl",
                "use": "input",
                "weights_sha256": ["a" * 64],
                "preprocess_spec_sha256": "b" * 64,
            },
        },
        "license": _license(train_license),
        "as_of_t_ticks": 36,
        "as_of_t_s": 0.3,
        "noise_model_ref": None,
        "store": "shared",
    }
    entry["entry_id"] = compute_entry_id(entry)
    return entry


def _context_with_binding(entry, blob_repro="numeric", teacher_train=True, entry_train=True):
    ctx = {
        "schema_version": "az.v9.teacher_cache.context.v1",
        "context_id": "test-context",
        "synthetic": True,
        "source_manifest": {
            "manifest_id": "test-manifest",
            "sources": [
                {
                    "source_id": "test-source-1",
                    "world_key": "test:world",
                    "partition": entry["source"]["partition"],
                    "upstream": entry["provenance"]["upstream"],
                    "time_domain": entry["source"]["time_domain"],
                }
            ],
        },
        "observation": {
            "packet_ref": {"uri": "test://obs", "sha256": "e" * 64},
            "time_domain": entry["source"]["time_domain"],
            "t_ticks": 36,
            "t_s": 0.3,
        },
        "approval_registry": {
            "registry_id": "adr-0005-current-approved-empty-20261016",
            "entries": [],
        },
        "admission_bindings": [
            {
                "entry_id": entry["entry_id"],
                "cache_key": entry["cache_key"],
                "entry_license": _license(entry_train),
                "teacher_license": _license(teacher_train),
                "reproducibility": blob_repro,
            }
        ],
    }
    return ctx


def test_canonical_json_and_sha():
    assert cache_mod.canon({"b": 2, "a": 1}) == b'{"a":1,"b":2}'
    assert len(sha({"a": 1})) == 64
    assert sha_bytes(b"x") == sha_bytes(b"x")


def test_write_read_blob_schema_compliant(temp_cache_dir, sample_blob_args):
    data = b"test output data"
    record = cache_mod.write_blob(output_data=data, **sample_blob_args)
    assert record["schema_version"] == "az.v9.teacher_cache.v2"
    assert "output" in record and "files" in record["output"]
    assert record["output"]["files"][0]["sha256"] == sha_bytes(data)
    assert "output_sha256" not in record
    errs = validate_schema(record, "teacher_blob")
    assert errs == [], errs
    read = cache_mod.read_blob(sample_blob_args["cache_key"])
    assert read["cache_key"] == sample_blob_args["cache_key"]


def test_validate_schema_blob_and_entry_have_asserts(sample_blob_args, sample_key_material):
    data = b"abc"
    good = cache_mod.build_blob_record(
        cache_key=sample_blob_args["cache_key"],
        key_material=sample_key_material,
        output_data=data,
        teacher_license=_license(True),
        reproducibility="numeric",
        generation_info=cache_mod.default_generation(),
        tolerance={"metric": "cosine_min", "value": 0.999},
    )
    assert validate_schema(good, "teacher_blob") == []
    bad = dict(good)
    bad.pop("schema_version")
    assert len(validate_schema(bad, "teacher_blob")) > 0


def test_blob_cache_key_mismatch_rejected(temp_cache_dir, sample_key_material):
    with pytest.raises(HashMismatchError):
        cache_mod.write_blob(
            cache_key="f" * 64,
            key_material=sample_key_material,
            output_data=b"x",
            teacher_license=_license(True),
            reproducibility="unverified",
            generation_info=cache_mod.default_generation(),
        )


def test_blob_nondeterministic_rejected(temp_cache_dir, sample_blob_args):
    cache_mod.write_blob(output_data=b"first", **sample_blob_args)
    with pytest.raises(TeacherCacheError, match="nondeterministic_output"):
        cache_mod.write_blob(output_data=b"second", **sample_blob_args)


def test_blob_same_output_idempotent(temp_cache_dir, sample_blob_args):
    cache_mod.write_blob(output_data=b"same", **sample_blob_args)
    r2 = cache_mod.write_blob(output_data=b"same", **sample_blob_args)
    assert r2["output"]["files"][0]["sha256"] == sha_bytes(b"same")


def test_blob_broken_on_output_tamper(temp_cache_dir, sample_blob_args):
    cache_mod.write_blob(output_data=b"valid", **sample_blob_args)
    cache = cache_mod.get_cache()
    ck = sample_blob_args["cache_key"]
    (cache.blobs_dir / ck[:2] / ck / "output.bin").write_bytes(b"corrupted")
    with pytest.raises(HashMismatchError):
        cache_mod.read_blob(ck)
    record = json.loads((cache.blobs_dir / ck[:2] / ck / "blob.json").read_text())
    assert record.get("broken") is True


def test_f9_key_material_swap_marks_broken(temp_cache_dir, sample_blob_args, sample_key_material):
    cache_mod.write_blob(output_data=b"valid", **sample_blob_args)
    cache = cache_mod.get_cache()
    ck = sample_blob_args["cache_key"]
    path = cache.blobs_dir / ck[:2] / ck / "blob.json"
    rec = json.loads(path.read_text())
    rec["key_material"]["teacher"]["teacher_id"] = "da3-small-FOREIGN"
    path.write_text(json.dumps(rec))
    with pytest.raises(HashMismatchError, match="cache_key"):
        cache_mod.read_blob(ck)


def test_write_read_entry(temp_cache_dir, sample_blob_args, sample_key_material):
    cache_mod.write_blob(output_data=b"out", **sample_blob_args)
    entry = _make_entry(sample_blob_args["cache_key"], sample_key_material)
    assert validate_schema(entry, "teacher_entry") == []
    cache_mod.write_entry(entry)
    got = cache_mod.read_entry(entry["entry_id"])
    assert got["entry_id"] == entry["entry_id"]


def test_f1_same_entry_id_different_content_rejected(
    temp_cache_dir, sample_blob_args, sample_key_material
):
    cache_mod.write_blob(output_data=b"out", **sample_blob_args)
    entry = _make_entry(sample_blob_args["cache_key"], sample_key_material, train_license=True)
    cache_mod.write_entry(entry)
    forged = json.loads(json.dumps(entry))
    forged["license"] = _license(False)
    # entry_id unchanged (license not in identity)
    assert forged["entry_id"] == entry["entry_id"]
    with pytest.raises(ImmutableConflictError):
        cache_mod.write_entry(forged)


def test_f8_derivation_teacher_swap_rejected(
    temp_cache_dir, sample_blob_args, sample_key_material
):
    cache_mod.write_blob(output_data=b"out", **sample_blob_args)
    entry = _make_entry(sample_blob_args["cache_key"], sample_key_material)
    entry["provenance"]["derivation"]["teacher_id"] = "da3-small-FOREIGN"
    entry["provenance"]["derivation"]["weights_sha256"] = ["f" * 64]
    # entry_id unchanged
    entry["entry_id"] = compute_entry_id(entry)
    with pytest.raises(HashMismatchError, match="derivation"):
        cache_mod.write_entry(entry)


def test_cross_partition_serial_rejected(
    temp_cache_dir, sample_blob_args, sample_key_material
):
    cache_mod.write_blob(output_data=b"out", **sample_blob_args)
    e1 = _make_entry(sample_blob_args["cache_key"], sample_key_material, partition="train")
    cache_mod.write_entry(e1)
    e2 = _make_entry(sample_blob_args["cache_key"], sample_key_material, partition="development")
    # different world so entry_id differs — but same cache_key cross partition
    e2["source"]["world_key"] = "test:world-b"
    e2["entry_id"] = compute_entry_id(e2)
    with pytest.raises(CrossPartitionError):
        cache_mod.write_entry(e2)


def _mp_write_blob(root, args, data, q, barrier):
    sys.path.insert(0, "src")
    import ainerzero.v9.teachers.cache as cm

    cm.set_cache_root(Path(root))
    barrier.wait()
    try:
        cm.write_blob(output_data=data, **args)
        q.put(("ok", None))
    except Exception as exc:
        q.put(("err", type(exc).__name__ + ":" + str(exc)))


def test_f4_concurrent_different_outputs_reject(temp_cache_dir, sample_blob_args):
    """≥20 Barrier rounds: at most one distinct output accepted."""
    root = str(cache_mod.get_cache().root)
    ctx = multiprocessing.get_context("spawn")
    broken = 0
    for round_i in range(20):
        # fresh subdir per round
        round_root = Path(root) / f"r{round_i}"
        round_root.mkdir()
        barrier = ctx.Barrier(2)
        q = ctx.Queue()
        args = dict(sample_blob_args)
        p1 = ctx.Process(
            target=_mp_write_blob, args=(str(round_root), args, b"AAA", q, barrier)
        )
        p2 = ctx.Process(
            target=_mp_write_blob, args=(str(round_root), args, b"BBB", q, barrier)
        )
        p1.start()
        p2.start()
        p1.join(10)
        p2.join(10)
        results = [q.get() for _ in range(2)]
        oks = [r for r in results if r[0] == "ok"]
        errs = [r for r in results if r[0] == "err"]
        # exactly one ok OR both err is fine; two oks = broken rejection
        if len(oks) == 2:
            broken += 1
        else:
            assert len(errs) >= 1
    assert broken == 0, f"nondeterministic rejection failed in {broken}/20 rounds"


def _mp_write_entry(root, blob_args, entry, q, barrier):
    sys.path.insert(0, "src")
    import ainerzero.v9.teachers.cache as cm

    cm.set_cache_root(Path(root))
    # blob must exist
    try:
        cm.write_blob(output_data=b"shared-out", **blob_args)
    except Exception:
        pass
    barrier.wait()
    try:
        cm.write_entry(entry)
        q.put(("ok", entry["source"]["partition"]))
    except Exception as exc:
        q.put(("err", type(exc).__name__))


def test_f3_concurrent_cross_partition_reject(temp_cache_dir, sample_blob_args, sample_key_material):
    root = str(cache_mod.get_cache().root)
    # pre-write blob once in parent
    cache_mod.write_blob(output_data=b"shared-out", **sample_blob_args)
    ctx = multiprocessing.get_context("spawn")
    cross = 0
    for round_i in range(20):
        round_root = Path(root) / f"cp{round_i}"
        # copy blob into round root by using same cache... use dedicated TeacherCache
        cache = cache_mod.TeacherCache(round_root)
        cache.write_blob(output_data=b"shared-out", **sample_blob_args)
        e_train = _make_entry(sample_blob_args["cache_key"], sample_key_material, "train")
        e_dev = _make_entry(sample_blob_args["cache_key"], sample_key_material, "development")
        e_dev["source"]["world_key"] = "test:world-dev"
        e_dev["entry_id"] = compute_entry_id(e_dev)
        barrier = ctx.Barrier(2)
        q = ctx.Queue()
        p1 = ctx.Process(
            target=_mp_write_entry,
            args=(str(round_root), sample_blob_args, e_train, q, barrier),
        )
        p2 = ctx.Process(
            target=_mp_write_entry,
            args=(str(round_root), sample_blob_args, e_dev, q, barrier),
        )
        p1.start()
        p2.start()
        p1.join(10)
        p2.join(10)
        results = [q.get() for _ in range(2)]
        oks = [r for r in results if r[0] == "ok"]
        if len(oks) == 2:
            cross += 1
        # verify disk
        parts = set()
        for f in (round_root / "entries").rglob("*.json"):
            parts.add(json.loads(f.read_text())["source"]["partition"])
        if len(parts) > 1:
            cross += 1
    assert cross == 0, f"cross_partition escaped in {cross} checks"


def test_f11_f12_disk_forgery_cannot_flip_eligibility(
    temp_cache_dir, sample_blob_args, sample_key_material
):
    # honest: unverified + binding unverified → not eligible
    args = dict(sample_blob_args)
    args["reproducibility"] = "unverified"
    args["tolerance"] = None
    blob = cache_mod.write_blob(output_data=b"out", **args)
    entry = _make_entry(args["cache_key"], sample_key_material)
    cache_mod.write_entry(entry)
    ctx = _context_with_binding(entry, blob_repro="unverified", teacher_train=True, entry_train=True)
    expected = sha(ctx)
    records = [blob, entry]
    assert train_eligible(entry, records, ctx, expected) is False

    # forge disk repro → still False because binding says unverified
    forged_blob = json.loads(json.dumps(blob))
    forged_blob["reproducibility"] = "bitwise"
    forged_records = [forged_blob, entry]
    assert train_eligible(entry, forged_records, ctx, expected) is False
    # with bindings present, store_problems must flag mismatch
    probs = store_problems(forged_records, ctx, expected)
    assert "admission_reproducibility_mismatch" in probs

    # forge entry license train True on disk while binding False
    ctx2 = _context_with_binding(entry, blob_repro="numeric", teacher_train=True, entry_train=False)
    # need numeric blob
    args2 = dict(sample_blob_args)
    # new key material to avoid nondeterministic conflict — reuse same with numeric already written path
    # use binding-only path: construct records in memory
    blob_n = dict(blob)
    blob_n["reproducibility"] = "numeric"
    blob_n["tolerance"] = {"metric": "cosine_min", "value": 0.999}
    entry_forged = json.loads(json.dumps(entry))
    entry_forged["license"] = _license(True)
    expected2 = sha(ctx2)
    assert train_eligible(entry_forged, [blob_n, entry_forged], ctx2, expected2) is False
    probs2 = store_problems([blob_n, entry_forged], ctx2, expected2)
    assert "admission_entry_license_mismatch" in probs2


def test_missing_metadata_rejected(temp_cache_dir, sample_key_material):
    with pytest.raises(MetadataIncompleteError):
        cache_mod.write_blob(
            cache_key=sha(sample_key_material),
            key_material=sample_key_material,
            output_data=b"",
            teacher_license={},
            reproducibility="unverified",
        )


def test_schema_reject_prevents_disk_write(temp_cache_dir, sample_blob_args):
    # monkeypatch build to skip — call write with invalid generation via direct path
    cache = cache_mod.get_cache()
    bad_gen = {"mode": "teacher"}  # incomplete
    with pytest.raises(SchemaValidationError):
        cache.write_blob(
            output_data=b"x",
            generation_info=bad_gen,
            **{k: v for k, v in sample_blob_args.items() if k != "generation_info"},
        )
    ck = sample_blob_args["cache_key"]
    assert not (cache.blobs_dir / ck[:2] / ck / "blob.json").exists()
