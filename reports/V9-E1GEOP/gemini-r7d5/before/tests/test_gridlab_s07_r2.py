"""S07-R2: identity/held-out split (frame overlap reported only), subprocess MLX isolation (CPU)."""

import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from ainerzero.data import gridlab_v1_r2 as r2
from ainerzero.data import gridlab_v1_trajectory as gt

ROOT = Path(__file__).resolve().parents[1] / "artifacts" / "gridlab2d"
OUT = ROOT / "s07-r2"
FROZEN_SHA = "52eda9a56722eabe1c80e797e969ab33cd371377597fa56a4f61f7450d6eb3b6"
CHECK = ("import sys; import {m}; bad = [x for x in sys.modules if x == 'mlx' or x.startswith('mlx.')]; "
         "assert not bad, bad")


def _run(mod):
    return subprocess.run([sys.executable, "-B", "-c", CHECK.format(m=mod)], capture_output=True, text=True,
                          timeout=120)


def test_no_mlx():
    assert _run("ainerzero.data.gridlab_v1_r2").returncode == 0


def test_isolation_check_detects_mlx_and_ignores_parent_state():
    assert _run("mlx.core").returncode != 0  # positive control: an MLX import is caught
    sys.modules.setdefault("mlx", type(sys)("mlx"))  # parent pollution must not matter
    try:
        assert _run("ainerzero.data.gridlab_v1_r2").returncode == 0
    finally:
        if getattr(sys.modules.get("mlx"), "__file__", None) is None:
            sys.modules.pop("mlx", None)


@pytest.mark.skipif(not OUT.exists(), reason="S07-R2 output not generated")
def test_frozen_manifest_matches_original_s07_partitions():
    checks = r2.verify_r2(OUT, FROZEN_SHA)
    assert all(v == 0 for d in checks["rejected_if_nonzero"].values() for v in d.values())
    assert checks["reported_only"]["frame_content"]["development|final"] == 1  # reported, not acted on
    m = json.loads((OUT / r2.MANIFEST_NAME).read_bytes())
    parts = {e["seed"]: e["partition"] for e in m["episodes"]}
    orig = json.loads((ROOT / "s07-sample" / "splits.json").read_bytes())
    assert parts == {e["seed"]: e["partition"] for e in orig["episodes"]}  # 25/27 swap reverted
    assert parts[25] == "development" and parts[27] == "final"
    assert {e["seed"] for e in m["episodes"] if e["scripted"]} == {27, 28}
    assert all(not any(e["flags"].values()) for e in m["episodes"] if e["partition"] == "train")
    assert m["occlusion_heldout_k"] == 3


@pytest.mark.skipif(not OUT.exists(), reason="S07-R2 output not generated")
def test_checker_rejects_deviations(tmp_path):
    with pytest.raises(ValueError, match="frozen value"):
        r2.verify_r2(OUT, "0" * 64)
    d = tmp_path / "a"
    shutil.copytree(OUT, d)
    m = json.loads((d / r2.MANIFEST_NAME).read_bytes())
    pub = d / m["episodes"][0]["episode_id"] / "public.jsonl"
    pub.write_bytes(pub.read_bytes() + b"\n")
    with pytest.raises(ValueError, match="differs"):
        r2.verify_r2(d, FROZEN_SHA)
    d = tmp_path / "b"
    shutil.copytree(OUT, d)
    m["episodes"][0]["flags"] = {"occlusion": True, "similar_objects": False}
    (d / r2.MANIFEST_NAME).write_bytes(r2.canonical(m) + b"\n")
    sha = hashlib.sha256((d / r2.MANIFEST_NAME).read_bytes()).hexdigest()
    # A-F1: a caller who re-signs a tampered manifest is rejected at the identity gate
    with pytest.raises(ValueError, match="registered frozen value"):
        r2.verify_r2(d, sha)
    with pytest.raises(ValueError, match="registered frozen value"):
        r2.verify_r2(d)


def _episodes(tmp_path, specs_parts):
    """Synthetic episode records with a *consistent* unseen_paths flag.

    unseen_paths must be True exactly when a non-train partition uses a path that the
    train partition does not (the generator's rule, now also a validator invariant).
    """
    sims = [(seed, fam, part, gt.simulate(seed, fam, 6)) for (seed, fam, part) in specs_parts]
    train_paths = {s["path_sha256"] for (_, _, part, s) in sims if part == "train"}
    eps = []
    for (seed, fam, part, s) in sims:
        unseen = part != "train" and s["path_sha256"] not in train_paths
        sub = tmp_path / part
        gt.write_episode(sub, s, run_id=gt.UUID(int=seed), partition=gt.DatasetPartition(part),
                         unseen_paths=unseen)
        eps.append({"world_id": str(s["world"].world_id), "seed": seed, "layout_sha256": s["layout_sha256"],
                    "partition": part, "flags": {}, "unseen_paths": unseen, "path_sha256": s["path_sha256"],
                    "episode_id": f"{part}/{s['episode_id']}", "content_digests": [],
                    "trajectory_sha256": r2.trajectory_sha256(s["public"])})
    return eps


def test_frame_overlap_reported_not_rejected(tmp_path):
    eps = _episodes(tmp_path, [(27, "swap_lane", "development"), (28, "occlusion_walk", "final")])
    checks = r2.identity_checks(tmp_path, eps)
    assert checks["reported_only"]["frame_rgb"]["development|final"] >= 1


def test_world_and_trajectory_duplicates_rejected(tmp_path):
    eps = _episodes(tmp_path, [(22, "open", "train"), (22, "open", "final")])
    with pytest.raises(ValueError, match="leakage"):
        r2.identity_checks(tmp_path, eps)
    # same trajectory under a different world id still rejected
    eps2 = _episodes(tmp_path / "x", [(23, "open", "train"), (23, "open", "development")])
    eps2[1] = {**eps2[1], "world_id": "w-other", "seed": 999, "layout_sha256": "other"}
    with pytest.raises(ValueError, match="trajectory"):
        r2.identity_checks(tmp_path / "x", eps2)


def test_prior_outputs_untouched():
    s = ROOT / "s07-sample" / "splits.json"
    c = ROOT / "s07-closeout" / "split_manifest.json"
    if s.exists():
        assert hashlib.sha256(s.read_bytes()).hexdigest().startswith("f9d8dbd6")
    if c.exists():
        assert hashlib.sha256(c.read_bytes()).hexdigest().startswith("1f80c54a")


# ------------------- S07-R2 hardening regressions: A-F1 / A-F2 / F3


def _signed_copy(tmp_path, name="c"):
    """Copy the frozen output and return (dir, manifest dict) for tampering."""
    d = tmp_path / name
    shutil.copytree(OUT, d)
    return d, json.loads((d / r2.MANIFEST_NAME).read_bytes())


def _rewrite(d, m):
    (d / r2.MANIFEST_NAME).write_bytes(r2.canonical(m) + b"\n")
    return hashlib.sha256((d / r2.MANIFEST_NAME).read_bytes()).hexdigest()


@pytest.mark.skipif(not OUT.exists(), reason="S07-R2 output not generated")
def test_a_f1_caller_supplied_sha_cannot_replace_the_registered_identity(tmp_path):
    """A-F1: re-signing a tampered manifest must not walk through the gate.

    Before the fix, `verify_r2(root, sha_of_tampered_manifest)` returned normally, so
    any caller could bypass validation by recomputing the expected value.
    """
    cases = {
        "metadata_frozen": lambda m: m.update(frozen=False),
        "metadata_rule": lambda m: m.update(rule="partitions chosen by coin flip"),
        "metadata_kind": lambda m: m.update(kind="something_else"),
        "metadata_revision": lambda m: m.update(revision="not-a-revision"),
        "metadata_run_id": lambda m: m.update(run_id=""),
        "duplicate_episode": lambda m: m["episodes"].append(dict(m["episodes"][0])),
        "duplicate_world": lambda m: m["episodes"].append(
            {**m["episodes"][1], "episode_id": "dup-world-record"}),
        "self_report_zeroed": lambda m: m["checks"]["reported_only"].update(
            {"frame_content": {"development|final": 0}}),
        "file_set_pruned": lambda m: m["episodes"][0]["files"].pop("private.json"),
    }
    for index, (name, mutate) in enumerate(sorted(cases.items())):
        d, m = _signed_copy(tmp_path, f"af1-{index}-{name}")
        mutate(m)
        sha = _rewrite(d, m)
        with pytest.raises(ValueError) as info:
            r2.verify_r2(d, sha)
        assert "registered frozen value" in str(info.value), (name, str(info.value))
    # the untampered registered manifest still verifies, with or without the argument
    assert r2.verify_r2(OUT, FROZEN_SHA) == r2.verify_r2(OUT)
    # a wrong caller-side expectation is rejected as well
    with pytest.raises(ValueError, match="registered frozen value"):
        r2.verify_r2(OUT, "1" * 64)


def _forge_public_path(src_episode: Path, dst_episode: Path) -> None:
    """Copy src's public trajectory into dst, keeping dst internally consistent.

    The declared path is then updated to the copied (real) value, so the only thing left
    to catch the replay is the *recomputed* path set (task M2.B6 counter-example).
    """
    import copy

    src_manifest = json.loads((src_episode / "manifest.json").read_bytes())
    dst_manifest = json.loads((dst_episode / "manifest.json").read_bytes())
    header, *obs = [json.loads(x) for x in (src_episode / "public.jsonl").read_bytes().splitlines()]
    header["episode_id"] = dst_manifest["episode_id"]
    lines = [header]
    for i, o in enumerate(obs):
        item = {k: v for k, v in o.items() if k != "observation_sha256"}
        item["step"] = i
        item["observation_sha256"] = r2.digest(item)
        lines.append(item)
    payload = b"\n".join(json.dumps(x, sort_keys=True, separators=(",", ":")).encode() for x in lines) + b"\n"
    (dst_episode / "public.jsonl").write_bytes(payload)
    dst_manifest["transition_count"] = src_manifest["transition_count"]
    dst_manifest["files"]["public.jsonl"] = {
        "size_bytes": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
    }
    (dst_episode / "manifest.json").write_bytes(r2.canonical(dst_manifest) + b"\n")
    private = json.loads((dst_episode / "private.json").read_bytes())
    src_private = json.loads((src_episode / "private.json").read_bytes())
    private["path_sha256"] = src_private["path_sha256"]
    private["states"] = src_private["states"]  # keep private consistent with the copied path
    priv_payload = r2.canonical(private) + b"\n"
    (dst_episode / "private.json").write_bytes(priv_payload)
    dst_manifest["files"]["private.json"] = {
        "size_bytes": len(priv_payload),
        "sha256": hashlib.sha256(priv_payload).hexdigest(),
    }
    (dst_episode / "manifest.json").write_bytes(r2.canonical(dst_manifest) + b"\n")
    _ = copy  # keep the helper dependency-free for readers


def test_a_f2_public_path_is_recomputed_and_reuse_is_rejected(tmp_path):
    """A-F2 (closed in M2.B6): decisions use the path recomputed from public.jsonl.

    Three cases, in the order the reviewer demanded:
    1. both self-declared paths changed consistently while public.jsonl is untouched
       -> rejected by the recomputation;
    2. a real (public) path replayed across partitions with matching declarations
       -> rejected by the recomputed cross-partition set;
    3. reuse inside one partition stays allowed.
    """
    # (1) declared-only tamper
    declared = _episodes(tmp_path, [(51, "open", "train"), (52, "open", "final")])
    declared[1]["path_sha256"] = declared[0]["path_sha256"]
    declared[1]["unseen_paths"] = False
    with pytest.raises(ValueError, match="declared path differs"):
        r2.identity_checks(tmp_path, declared)

    # (2) real cross-partition replay: forge the public trajectory, declarations follow it
    forged = _episodes(tmp_path / "forged", [(53, "open", "train"), (54, "open", "final")])
    a = tmp_path / "forged" / forged[0]["episode_id"]
    b = tmp_path / "forged" / forged[1]["episode_id"]
    _forge_public_path(a, b)
    forged[1]["path_sha256"] = forged[0]["path_sha256"]
    forged[1]["trajectory_sha256"] = forged[0]["trajectory_sha256"]
    forged[1]["unseen_paths"] = False
    assert r2.recompute_path_sha256(gt.load_public(b)) == forged[0]["path_sha256"]
    with pytest.raises(ValueError, match="path|trajectory"):
        r2.identity_checks(tmp_path / "forged", forged)

    # (3) the same reuse inside one partition is not a leak
    within = _episodes(tmp_path / "within", [(55, "open", "train"), (56, "open", "train")])
    _forge_public_path(tmp_path / "within" / within[0]["episode_id"],
                       tmp_path / "within" / within[1]["episode_id"])
    within[1]["path_sha256"] = within[0]["path_sha256"]
    within[1]["trajectory_sha256"] = within[0]["trajectory_sha256"]
    checks = r2.identity_checks(tmp_path / "within", within)
    assert all(v == 0 for d in checks["rejected_if_nonzero"].values() for v in d.values())


def test_unseen_paths_flag_follows_the_recomputed_path_set(tmp_path):
    """The unseen_paths invariant is judged on recomputed paths, not declarations."""
    eps = _episodes(tmp_path, [(57, "open", "train"), (58, "open", "final")])
    assert eps[1]["unseen_paths"] is True
    eps[1]["unseen_paths"] = False  # contradicts the recomputed train path set
    with pytest.raises(ValueError, match="unseen_paths contradicts"):
        r2.identity_checks(tmp_path, eps)


def _isolation(mod):
    proc = _run(mod)
    return proc.returncode, (proc.stderr or "") + (proc.stdout or "")


def test_f3_negative_control_separates_importerror_from_assertion():
    """F3: the isolation control must prove the detector fired, not that an import failed."""
    rc_mlx, err_mlx = _isolation("mlx.core")
    assert rc_mlx != 0 and "AssertionError" in err_mlx, err_mlx[-200:]
    assert "ModuleNotFoundError" not in err_mlx and "ImportError" not in err_mlx, err_mlx[-200:]
    rc_missing, err_missing = _isolation("definitely_not_a_module_xyz")
    assert rc_missing != 0
    assert "ModuleNotFoundError" in err_missing or "ImportError" in err_missing, err_missing[-200:]
    assert "AssertionError" not in err_missing, err_missing[-200:]
    rc_clean, err_clean = _isolation("ainerzero.data.gridlab_v1_r2")
    assert rc_clean == 0, err_clean[-200:]
