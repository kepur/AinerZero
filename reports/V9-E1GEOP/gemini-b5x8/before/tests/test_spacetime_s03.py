"""S03 portable CPU contract fixtures; missing data fails, never module-skips."""

import builtins
import hashlib
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

from ainerzero.core.experience import DatasetPartition, OriginKind
from ainerzero.core.spacetime import (
    EvidenceLink,
    TimeOrder,
    compare_time,
    links_visible_at,
    record_digest,
    resolve_link,
    resolved_links_visible_at,
    validate_link_history,
)
from ainerzero.data.trajectory import load_public_trajectory

ROOT = Path(__file__).resolve().parents[1]
FIXTURE_ROOT = ROOT / "tests" / "fixtures" / "c0_spacetime_v1"
EPISODES = [
    FIXTURE_ROOT / "development" / "242b7060-4a2c-4ca9-aa46-e4bbc59f4786",
    FIXTURE_ROOT / "train" / "2d457a1e-c746-48ae-8adb-59b47929d69e",
]
spec = importlib.util.spec_from_file_location("c0_spacetime_refs", ROOT / "examples" / "c0_spacetime_refs.py")
ex = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ex)

def _hashes(d):
    return {n: hashlib.sha256((d / n).read_bytes()).hexdigest() for n in ("public.jsonl", "manifest.json")}


@pytest.fixture(params=EPISODES, ids=lambda p: p.name[:8])
def episode(request):
    assert request.param.is_dir(), f"required public fixture is missing: {request.param}"
    return request.param


def test_real_sample_resolves_and_as_of_view(episode):
    before = _hashes(episode)
    result = ex.run(episode, 0, public_only=True)
    assert _hashes(episode) == before
    assert result["public_jsonl_file_sha256"] == result["manifest_recorded_public_sha256"]
    for ref in result["refs"]:
        assert ref["observation_canonical_sha256"] == ref["recomputed"]
        assert ref["observation_canonical_sha256"] != result["public_jsonl_file_sha256"]
    view = result["as_of_revisions"]
    steps = sorted(int(k) for k in view)
    assert view[str(steps[0])] == []
    assert view[str(steps[-1])] == [0, 1]
    v0_step = result["links"][0]["asserted_at_step"]
    v1_step = result["links"][1]["asserted_at_step"]
    assert v0_step < v1_step and view[str(v0_step)] == [0]


def test_refs_are_same_cell_strictly_later_on_real_data(episode):
    v0, v1 = ex.build_links(load_public_trajectory(episode), 0)
    for s in v1.supports:
        assert s.cell == v1.subject.cell == 0
        assert compare_time(v1.subject.time, s.time) is TimeOrder.BEFORE
        assert s.physical_xyz is None and s.origin is OriginKind.OBSERVED


def test_missing_or_tampered_observations_rejected(episode):
    t = load_public_trajectory(episode)
    m = ex.public_observations(t)
    v0, v1 = ex.build_links(t, 0)
    assert resolved_links_visible_at((v0, v1), 10_000, m) == (v0, v1)
    missing = dict(m)
    del missing[v0.supports[0].observation_id]
    with pytest.raises(ValueError):
        resolve_link(v0, missing)
    sid = v0.supports[0].observation_id
    obs = m[sid]
    sym = list(obs.payload.symbols)
    sym[0] = (sym[0] + 1) % 256
    tampered = {**m, sid: obs.model_copy(update={"payload": obs.payload.model_copy(update={"symbols": tuple(sym)})})}
    with pytest.raises(ValueError):
        resolve_link(v0, tampered)
    other = next(o for k, o in m.items() if k != sid)
    with pytest.raises(ValueError):
        resolve_link(v0, {**m, sid: other})  # key != observation.id
    imagined = {**m, sid: obs.model_copy(update={"origin": OriginKind.IMAGINED})}
    with pytest.raises(ValueError):
        resolve_link(v0, imagined)


def test_history_requires_predecessor_on_real_links(episode):
    v0, v1 = ex.build_links(load_public_trajectory(episode), 0)
    assert validate_link_history((v0, v1)) == (v0, v1)
    with pytest.raises(ValueError):
        links_visible_at((v1,), 10_000)
    with pytest.raises(ValueError):
        validate_link_history((v0, v1, v1))
    assert record_digest(EvidenceLink.model_validate_json(ex.to_canonical_json(v1))) == record_digest(v1)


def test_unknown_world_not_invented(episode):
    t = load_public_trajectory(episode)
    ctx = t.initial.context.model_copy(update={"environment_instance_id": None})
    fake = t.model_copy(update={"initial": t.initial.model_copy(update={"context": ctx})})
    with pytest.raises(ValueError):
        ex.build_links(fake, 0)


def test_private_json_never_opened(episode, monkeypatch):
    real_open = builtins.open
    real_read = Path.read_bytes

    def guard_open(file, *a, **k):
        assert Path(str(file)).name != "private.json"
        return real_open(file, *a, **k)

    def guard_read(self):
        assert self.name != "private.json"
        return real_read(self)

    monkeypatch.setattr(builtins, "open", guard_open)
    monkeypatch.setattr(Path, "read_bytes", guard_read)
    monkeypatch.setattr(Path, "open", lambda self, *a, **k: guard_open(self, *a, **k))
    ex.run(episode, 0, public_only=True)


def test_example_imports_without_mlx():
    code = (f"import runpy,sys; runpy.run_path({str(ROOT / 'examples' / 'c0_spacetime_refs.py')!r}); "
            "assert not any(k == 'mlx' or k.startswith('mlx.') for k in sys.modules)")
    subprocess.run([sys.executable, "-c", code], check=True)


def test_fixture_metadata_has_exact_public_bytes_and_preserved_scope():
    metadata = json.loads((FIXTURE_ROOT / "fixture_manifest.json").read_text())
    assert metadata["usage"] == "contract_test_only" and metadata["not_for_training"] is True
    assert metadata["private_files_copied_or_read"] is False
    assert metadata["not_generalization_evidence"] is True
    assert {FIXTURE_ROOT / item["path"] for item in metadata["fixtures"]} == set(EPISODES)
    total = 0
    for item in metadata["fixtures"]:
        path = FIXTURE_ROOT / item["path"]
        assert {p.name for p in path.iterdir()} == {"public.jsonl", "manifest.json"}
        trajectory = load_public_trajectory(path)
        context = trajectory.initial.context
        assert str(context.partition) == item["partition"] == path.parent.name
        assert str(context.episode_id) == item["episode_id"] == path.name
        assert str(context.environment_instance_id) == item["world_id"]
        assert str(context.run_id) == item["run_id"]
        for name, description in item["files"].items():
            data = (path / name).read_bytes()
            total += len(data)
            assert len(data) == description["size_bytes"]
            assert hashlib.sha256(data).hexdigest() == description["sha256"]
    assert total == metadata["total_source_bytes"] == 490577


@pytest.mark.parametrize("cell", [-1, 8, True, False, 1.0, "0", None])
def test_invalid_cell_is_rejected_before_loading(cell, tmp_path):
    with pytest.raises(ValueError, match="cell must"):
        ex.run(tmp_path / "missing", cell, public_only=True)
    with pytest.raises(ValueError, match="cell must"):
        ex.pick_steps([], cell)


def test_hidden_observations_are_not_selected_or_exposed_as_visible():
    trajectory = load_public_trajectory(EPISODES[0])
    observations = list(ex.public_observations(trajectory).values())[:4]
    first = observations[0]
    symbols, visible = list(first.payload.symbols), list(first.payload.visible_mask)
    symbols[0], visible[0] = 0, False
    hidden = first.model_copy(update={"payload": first.payload.model_copy(
        update={"symbols": tuple(symbols), "visible_mask": tuple(visible)})})
    picked = ex.pick_steps([hidden, *observations[1:]], 0)
    assert [o.step for o in picked] == [1, 2, 3]
    with pytest.raises(ValueError, match="fewer than"):
        ex.pick_steps([hidden, *observations[1:3]], 0)


def test_real_episode_and_partition_scope_cannot_be_mixed():
    left = ex.build_links(load_public_trajectory(EPISODES[0]), 0)[0]
    right = ex.build_links(load_public_trajectory(EPISODES[1]), 0)[0]
    with pytest.raises(ValueError):
        EvidenceLink(kind=left.kind, subject=left.subject, supports=right.supports,
                     asserted_by="scope-negative", asserted_at_step=128)
    partition_alias = left.supports[0].model_copy(update={"time": left.supports[0].time.model_copy(
        update={"partition": DatasetPartition.TRAIN})})
    with pytest.raises(ValueError):
        EvidenceLink(kind=left.kind, subject=left.subject, supports=(partition_alias,),
                     asserted_by="scope-negative", asserted_at_step=128)


def test_archive_roundtrip_is_bound_to_source_code_links_and_files(episode, tmp_path):
    before = _hashes(episode)
    result = ex.run(episode, 0, public_only=True)
    target = ex.archive_snapshot(result, tmp_path / "spacetime")
    assert target.relative_to(tmp_path / "spacetime").parts == (
        result["partition"], result["episode_id"], result["snapshot_digest"])
    assert ex.load_snapshot(target) == {k: v for k, v in result.items() if k != "sidecar_jsonl"}
    manifest = json.loads((target / "manifest.json").read_text())
    assert manifest["identity"] == result["snapshot_identity"]
    assert set(manifest["identity"]["producer"]["source_sha256"]) == ex.PRODUCER_FILES
    assert _hashes(episode) == before
    for name, description in manifest["files"].items():
        data = (target / name).read_bytes()
        assert len(data) == description["size_bytes"]
        assert hashlib.sha256(data).hexdigest() == description["sha256"]
    original = {p.name: p.read_bytes() for p in target.iterdir()}
    with pytest.raises(FileExistsError):
        ex.archive_snapshot(result, tmp_path / "spacetime")
    assert {p.name: p.read_bytes() for p in target.iterdir()} == original


def test_snapshot_identity_changes_with_cell_and_has_no_local_fixture_path():
    left = ex.run(EPISODES[0], 0, public_only=True)
    right = ex.run(EPISODES[0], 1, public_only=True)
    assert left["snapshot_digest"] != right["snapshot_digest"]
    identity = json.dumps(left["snapshot_identity"])
    assert str(ROOT) not in identity and "tests/fixtures" not in identity


@pytest.mark.parametrize("field,value", [
    ("usage", "training"), ("not_for_training", False), ("private_json_opened", True),
    ("partition", "train"), ("world_id", "00000000-0000-0000-0000-000000000001"),
    ("transitions", 1), ("public_jsonl_file_sha256", "0" * 64),
])
def test_snapshot_rejects_summary_markers_and_source_duplicates_out_of_sync(tmp_path, field, value):
    result = ex.run(EPISODES[0], 0, public_only=True)
    result[field] = value
    with pytest.raises(ValueError):
        ex.archive_snapshot(result, tmp_path)
    assert not list(tmp_path.iterdir())


def test_archive_interruption_has_no_completion_manifest_and_cannot_be_consumed(tmp_path, monkeypatch):
    result = ex.run(EPISODES[0], 0, public_only=True)
    real_write = ex._write_new

    def fail_summary(path, data):
        if path.name == "summary.json":
            raise OSError("simulated archive interruption")
        real_write(path, data)

    monkeypatch.setattr(ex, "_write_new", fail_summary)
    root = tmp_path / "archive"
    with pytest.raises(OSError, match="interruption"):
        ex.archive_snapshot(result, root)
    target = root / result["partition"] / result["episode_id"] / result["snapshot_digest"]
    assert target.is_dir() and not (target / "manifest.json").exists()
    with pytest.raises(ValueError):
        ex.load_snapshot(target)
    with pytest.raises(FileExistsError):
        ex.archive_snapshot(result, root)


@pytest.mark.parametrize("name", ["evidence_links.jsonl", "summary.json"])
def test_archive_rejects_data_hash_tampering(tmp_path, name):
    target = ex.archive_snapshot(ex.run(EPISODES[0], 0, public_only=True), tmp_path)
    with (target / name).open("ab") as handle:
        handle.write(b" ")
    with pytest.raises(ValueError, match="integrity"):
        ex.load_snapshot(target)


@pytest.mark.parametrize("change", ["version", "digest", "file_traversal", "missing_key"])
def test_archive_rejects_manifest_identity_and_filename_tampering(tmp_path, change):
    target = ex.archive_snapshot(ex.run(EPISODES[0], 0, public_only=True), tmp_path)
    manifest = json.loads((target / "manifest.json").read_text())
    if change == "version":
        manifest["schema_version"] = 99
    elif change == "digest":
        manifest["identity"]["cell"] = 1
    elif change == "file_traversal":
        manifest["files"]["../outside"] = manifest["files"].pop("summary.json")
    else:
        del manifest["identity"]
    (target / "manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(ValueError):
        ex.load_snapshot(target)


def test_archive_rejects_resigned_links_not_bound_to_snapshot(tmp_path):
    target = ex.archive_snapshot(ex.run(EPISODES[0], 0, public_only=True), tmp_path)
    evidence = target / "evidence_links.jsonl"
    raw = [json.loads(line) for line in evidence.read_text().splitlines()]
    raw[1]["asserted_by"] = "another-producer"
    evidence.write_text("".join(json.dumps(line) + "\n" for line in raw))
    manifest = json.loads((target / "manifest.json").read_text())
    data = evidence.read_bytes()
    manifest["files"][evidence.name] = {"sha256": hashlib.sha256(data).hexdigest(), "size_bytes": len(data)}
    (target / "manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="links do not match"):
        ex.load_snapshot(target)


@pytest.mark.parametrize("mode", ["root_symlink", "partition_symlink", "traversal"])
def test_archive_rejects_symlink_and_path_traversal(tmp_path, mode):
    result = ex.run(EPISODES[0], 0, public_only=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    root = tmp_path / "archive"
    if mode == "root_symlink":
        root.symlink_to(outside, target_is_directory=True)
    elif mode == "partition_symlink":
        root.mkdir()
        (root / result["partition"]).symlink_to(outside, target_is_directory=True)
    else:
        root = tmp_path / ".." / "archive-escape"
    with pytest.raises(ValueError):
        ex.archive_snapshot(result, root)
    assert list(outside.iterdir()) == []


def test_archive_rejects_symlinked_file_and_wrong_partition_directory(tmp_path):
    result = ex.run(EPISODES[0], 0, public_only=True)
    target = ex.archive_snapshot(result, tmp_path)
    summary = target / "summary.json"
    external = tmp_path / "external-summary"
    summary.rename(external)
    summary.symlink_to(external)
    with pytest.raises(ValueError, match="regular"):
        ex.load_snapshot(target)
    summary.unlink()
    external.rename(summary)
    wrong_parent = tmp_path / "train" / result["episode_id"]
    wrong_parent.mkdir(parents=True)
    target.rename(wrong_parent / target.name)
    with pytest.raises(ValueError, match="source scope"):
        ex.load_snapshot(wrong_parent / target.name)


def test_public_fixture_missing_fails_and_default_example_stays_complete(tmp_path):
    missing = tmp_path / EPISODES[0].name
    with pytest.raises(ValueError):
        ex.run(missing, public_only=True)
    with pytest.raises(ValueError, match="missing or unexpected"):
        ex.run(EPISODES[0])


def test_public_only_cli_is_explicit_and_writes_a_new_archive(tmp_path):
    completed = subprocess.run(
        [sys.executable, "-B", str(ROOT / "examples" / "c0_spacetime_refs.py"),
         str(EPISODES[0]), "--public-only", "--archive-root", str(tmp_path)],
        check=True, capture_output=True, text=True)
    result = json.loads(completed.stdout)
    assert result["load_profile"] == "public_only"
    assert ex.load_snapshot(Path(result["archive_path"]))["snapshot_digest"] == result["snapshot_digest"]
