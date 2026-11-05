"""S07-R1: closeout split (no cross-partition overlap), frozen manifest checker (CPU only)."""

import json
import shutil
import sys
from pathlib import Path

import pytest

from ainerzero.data import gridlab_v1_closeout as c
from ainerzero.data import gridlab_v1_trajectory as gt

ROOT = Path(__file__).resolve().parents[1] / "artifacts" / "gridlab2d"
CLOSEOUT = ROOT / "s07-closeout"
FROZEN_SHA = "1f80c54a5ff3c4089ae902b6862f540ace1513e976a7280917b8e491e46d36d8"


def test_no_mlx():
    # S07-R2: fresh interpreter, so other tests importing MLX cannot affect the result
    import subprocess
    code = ("import sys; import ainerzero.data.gridlab_v1_closeout; "
            "bad = [m for m in sys.modules if m == 'mlx' or m.startswith('mlx.')]; "
            "assert not bad, bad")
    r = subprocess.run([sys.executable, "-B", "-c", code], capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stderr


@pytest.mark.skipif(not CLOSEOUT.exists(), reason="closeout not generated")
def test_frozen_manifest_and_zero_overlap():
    o = c.verify_split_manifest(CLOSEOUT, FROZEN_SHA)
    assert all(v == 0 for v in {**o["content_overlap"], **o["file_identity_overlap"]}.values())
    assert len(o["file_identity_overlap"]) == 9 and len(o["content_overlap"]) == 3
    m = json.loads((CLOSEOUT / c.MANIFEST_NAME).read_bytes())
    assert {e["partition"] for e in m["episodes"]} == {"train", "development", "final"}
    assert all(not any(e["flags"].values()) for e in m["episodes"] if e["partition"] == "train")


def _copy(tmp_path):
    dst = tmp_path / "co"
    shutil.copytree(CLOSEOUT, dst)
    return dst


@pytest.mark.skipif(not CLOSEOUT.exists(), reason="closeout not generated")
def test_checker_rejects_deviations(tmp_path):
    with pytest.raises(ValueError, match="frozen value"):
        c.verify_split_manifest(CLOSEOUT, "0" * 64)
    d = _copy(tmp_path)
    m = json.loads((d / c.MANIFEST_NAME).read_bytes())
    ep = m["episodes"][0]
    priv = d / ep["episode_id"] / "private.json"
    priv.write_bytes(priv.read_bytes() + b" ")
    with pytest.raises(ValueError, match="differs"):
        c.verify_split_manifest(d, FROZEN_SHA)
    d = _copy(tmp_path / "b")
    shutil.rmtree(d / ep["episode_id"])
    with pytest.raises(ValueError, match="directories"):
        c.verify_split_manifest(d, FROZEN_SHA)
    d = _copy(tmp_path / "c")
    (d / "extra.json").write_text("{}")
    with pytest.raises(ValueError, match="directories"):
        c.verify_split_manifest(d, FROZEN_SHA)
    # a re-written manifest with a moved partition no longer matches the frozen SHA
    d = _copy(tmp_path / "d")
    m["episodes"][0]["partition"] = "final" if ep["partition"] != "final" else "train"
    (d / c.MANIFEST_NAME).write_bytes(c.canonical(m) + b"\n")
    with pytest.raises(ValueError, match="frozen value"):
        c.verify_split_manifest(d, FROZEN_SHA)
    # A-F1 counterexample kept: re-signing the tampered manifest and passing its SHA must be
    # rejected by the registered identity gate (caller SHA is only cross-checked), before any
    # consistency check runs.
    new_sha = c.hashlib.sha256((d / c.MANIFEST_NAME).read_bytes()).hexdigest()
    assert new_sha != FROZEN_SHA
    with pytest.raises(ValueError, match="registered frozen value"):
        c.verify_split_manifest(d, new_sha)


def test_original_s07_overlap_reproduced_and_resolved():
    sims = [gt.simulate(s, f, 16) for s, f in gt.SAMPLE_SPECS]
    old = gt.assign_with_heldout(sims)
    new = c.assign_overlap_free(sims)
    by_seed = {s["world"].seed: s["world"].world_id for s in sims}
    assert old[by_seed[27]] != old[by_seed[28]]  # original S07 split put the overlapping pair apart
    assert new[by_seed[27]] == new[by_seed[28]]  # union-find keeps them in one partition
    comps = c.components(sims)
    assert any({s["world"].seed for s in comp} == {27, 28} for comp in comps)


def test_overlap_check_counterexample(tmp_path):
    sims = [gt.simulate(27, "swap_lane", 6), gt.simulate(28, "occlusion_walk", 6)]
    eps = []
    for s, part in zip(sims, (gt.DatasetPartition.DEVELOPMENT, gt.DatasetPartition.FINAL)):
        gt.write_episode(tmp_path, s, run_id=gt.UUID(int=1), partition=part, unseen_paths=False)
        eps.append({"episode_id": str(s["episode_id"]), "partition": str(part), "flags": {},
                    "path_sha256": s["path_sha256"], "unseen_paths": False,
                    "content_digests": sorted({c.v1.public_content_digest(o) for o in s["public"]})})
    with pytest.raises(ValueError, match="cross-partition overlap"):
        c.check_overlaps(tmp_path, eps)
    files = c.file_identity_overlap(tmp_path, eps)
    assert files["frame:development|final"] >= 1


def test_original_sample_untouched():
    s = ROOT / "s07-sample" / "splits.json"
    if s.exists():
        assert c.hashlib.sha256(s.read_bytes()).hexdigest() == \
            "f9d8dbd6af610f941e936eb3fadaf6f49243606e8920d57fbd4be1eb108d5ec5"
