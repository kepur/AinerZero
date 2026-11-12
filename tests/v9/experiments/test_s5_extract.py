"""Contract tests for the S5 teacher extraction script (P231): pure CPU, fake teachers only."""

from __future__ import annotations

import fcntl
import json
from pathlib import Path

import numpy as np
import pytest

from ainerzero.v9.experiments.s5 import extract_teachers as X


def _make_partition(root: Path, partition: str = "s5test-extract", worlds: int = 2, clips: int = 3,
                    da2: bool = True) -> Path:
    rng = np.random.default_rng(0)
    root.mkdir(parents=True)
    for w in range(worlds):
        wd = root / f"world_{w:04d}"
        wd.mkdir()
        for c in range(clips):
            np.save(wd / f"clip_{c:02d}.npy", rng.integers(0, 256, X.CLIP_SHAPE, dtype=np.uint8))
            if da2:
                np.save(wd / f"da2_{c:02d}.npy", rng.integers(0, 256, X.DA2_IN, dtype=np.uint8))
            np.savez(wd / f"labels_{c:02d}.npz", r2=np.zeros((12, 7), np.uint8))   # must be ignored
    (root / "manifest.json").write_text(json.dumps({"partition": partition}), encoding="utf-8")
    return root


class CountingTeacher:
    """Fake V-JEPA: records inputs, returns a deterministic fp16 [1568, 1024]; can fail at call k."""

    def __init__(self, fail_at: int | None = None):
        self.calls = 0
        self.fail_at = fail_at
        self.seen: list[np.ndarray] = []

    def __call__(self, clip: np.ndarray) -> np.ndarray:
        self.calls += 1
        if self.fail_at is not None and self.calls == self.fail_at:
            raise RuntimeError("simulated crash")
        x = X.vjepa_input(clip)
        self.seen.append(x)
        return np.full(X.VJEPA_OUT, float(x.mean()), dtype=np.float16)


def test_vjepa_preprocess_layout_and_values():
    clip = np.zeros(X.CLIP_SHAPE, dtype=np.uint8)
    clip[5, 10, 20] = (255, 128, 0)
    x = X.vjepa_input(clip)
    assert x.shape == (1, 3, 16, 224, 224) and x.dtype == np.float32
    for ch, v in enumerate((255, 128, 0)):
        want = (v / 255.0 - X.IMAGENET_MEAN[ch]) / X.IMAGENET_STD[ch]
        assert x[0, ch, 5, 10, 20] == pytest.approx(want, abs=1e-6)
    # an untouched pixel is pure normalised black
    assert x[0, 0, 0, 0, 0] == pytest.approx(-X.IMAGENET_MEAN[0] / X.IMAGENET_STD[0], abs=1e-6)
    with pytest.raises(ValueError):
        X.vjepa_input(clip.astype(np.float32))


def test_vjepa_run_feeds_the_preprocessed_clip(tmp_path):
    part = _make_partition(tmp_path / "in", worlds=1, clips=1, da2=False)
    t = CountingTeacher()
    X.run("vjepa", part, tmp_path / "out", t)
    raw = np.load(part / "world_0000" / "clip_00.npy")
    np.testing.assert_allclose(t.seen[0], X.vjepa_input(raw))
    out = np.load(tmp_path / "out" / "world_0000" / "clip_00.vjepa.npy")
    assert out.dtype == np.float16 and out.shape == X.VJEPA_OUT


def test_da2_target_takes_middle_columns_and_area_averages():
    depth = np.zeros((392, 518), dtype=np.float32)
    depth[:, :63] = 100.0                      # left margin: must be cropped away
    depth[:, 455:] = -100.0                    # right margin: must be cropped away
    depth[:, 63:455] = np.arange(392, dtype=np.float32)[None, :]   # column ramp inside the crop
    out = X.da2_target(depth)
    assert out.shape == (56, 56) and out.dtype == np.float16
    # area average of a 7-column block of the ramp = mean of 7 consecutive integers
    want = np.array([np.mean(np.arange(7 * j, 7 * j + 7)) for j in range(56)], dtype=np.float32)
    np.testing.assert_allclose(out[0].astype(np.float32), want, rtol=2e-3)
    np.testing.assert_allclose(out[:, 3].astype(np.float32), np.full(56, want[3]), rtol=2e-3)


def test_da2_run_layout(tmp_path):
    part = _make_partition(tmp_path / "in", worlds=1, clips=2)

    def fake(frames):
        assert frames.shape == X.DA2_IN and frames.dtype == np.uint8
        return np.stack([X.da2_target(f[..., 0].astype(np.float32)) for f in frames])

    m = X.run("da2", part, tmp_path / "out", fake)
    assert m["written"] == 2
    out = np.load(tmp_path / "out" / "world_0000" / "da2_01.da2.npy")
    assert out.shape == (8, 56, 56) and out.dtype == np.float16
    assert not list((tmp_path / "out").rglob("*labels*"))


def test_resume_after_crash_does_not_recompute(tmp_path):
    part = _make_partition(tmp_path / "in", worlds=2, clips=3, da2=False)   # 6 items
    first = CountingTeacher(fail_at=4)
    with pytest.raises(RuntimeError, match="simulated crash"):
        X.run("vjepa", part, tmp_path / "out", first)
    assert first.calls == 4
    second = CountingTeacher()
    m = X.run("vjepa", part, tmp_path / "out", second)
    assert second.calls == 3 and m["written"] == 3 and m["skipped_already_done"] == 3
    ledger = (tmp_path / "out" / "progress.jsonl").read_text().splitlines()
    assert len(ledger) == 6 and len({json.loads(l)["file"] for l in ledger}) == 6


def test_tampered_output_is_refused(tmp_path):
    part = _make_partition(tmp_path / "in", worlds=1, clips=2, da2=False)
    X.run("vjepa", part, tmp_path / "out", CountingTeacher())
    victim = tmp_path / "out" / "world_0000" / "clip_01.vjepa.npy"
    raw = bytearray(victim.read_bytes())
    raw[-1] ^= 0xFF
    victim.write_bytes(bytes(raw))
    with pytest.raises(RuntimeError, match="tampered"):
        X.run("vjepa", part, tmp_path / "out", CountingTeacher())


def test_stray_output_not_in_ledger_is_refused(tmp_path):
    part = _make_partition(tmp_path / "in", worlds=1, clips=1, da2=False)
    stray = tmp_path / "out" / "world_0000" / "clip_00.vjepa.npy"
    stray.parent.mkdir(parents=True)
    np.save(stray, np.zeros(X.VJEPA_OUT, np.float16))
    with pytest.raises(RuntimeError, match="not in the ledger"):
        X.run("vjepa", part, tmp_path / "out", CountingTeacher())


@pytest.mark.parametrize("partition", sorted(X.REGISTERED_PARTITIONS))
def test_registered_partitions_are_refused(tmp_path, partition):
    part = _make_partition(tmp_path / "in", partition=partition, worlds=1, clips=1, da2=False)
    with pytest.raises(PermissionError):
        X.run("vjepa", part, tmp_path / "out", CountingTeacher())
    assert not (tmp_path / "out").exists()


def test_wrong_teacher_output_is_refused(tmp_path):
    part = _make_partition(tmp_path / "in", worlds=1, clips=1, da2=False)
    with pytest.raises(RuntimeError, match="expected float16"):
        X.run("vjepa", part, tmp_path / "out", lambda c: np.zeros(X.VJEPA_OUT, np.float32))


def test_lock_busy_exits_75_and_writes_nothing(tmp_path):
    part = _make_partition(tmp_path / "in", worlds=1, clips=1, da2=False)
    lock = tmp_path / "test.lock"
    built = []
    factories = {"vjepa": lambda: (built.append(1) or (CountingTeacher(), {}))}
    with open(lock, "a+") as holder:
        fcntl.flock(holder, fcntl.LOCK_EX | fcntl.LOCK_NB)
        rc = X.main(["--teacher", "vjepa", "--in", str(part), "--out", str(tmp_path / "out")],
                    lock_path=lock, factories=factories)
    assert rc == X.EXIT_LOCK_BUSY
    assert not (tmp_path / "out").exists() and not built
    rc = X.main(["--teacher", "vjepa", "--in", str(part), "--out", str(tmp_path / "out")],
                lock_path=lock, factories=factories)
    assert rc == 0 and built == [1]
    assert (tmp_path / "out" / "world_0000" / "clip_00.vjepa.npy").exists()


def test_world_range_and_manifest(tmp_path):
    part = _make_partition(tmp_path / "in", worlds=3, clips=1, da2=False)
    m = X.run("vjepa", part, tmp_path / "out", CountingTeacher(), worlds=(1, 3))
    assert m["written"] == 2
    assert sorted(p.name for p in (tmp_path / "out").iterdir() if p.is_dir()) == ["world_0001", "world_0002"]
    disk = json.loads((tmp_path / "out" / "manifest.json").read_text())
    assert disk["input_manifest_sha256"] == X.sha256_file(part / "manifest.json")
    assert disk["code"]["extract_teachers.py"] == X.sha256_file(Path(X.__file__))
    assert disk["preprocess"]["mean"] == list(X.IMAGENET_MEAN)


def test_weight_sha_check_rejects_mismatch(tmp_path):
    (tmp_path / "w.bin").write_bytes(b"not the weights")
    with pytest.raises(RuntimeError, match="SHA mismatch"):
        X.verify_weights(tmp_path, {"w.bin": "0" * 64})
