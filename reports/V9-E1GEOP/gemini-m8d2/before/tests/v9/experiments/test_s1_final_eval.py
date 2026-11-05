"""Sealed final partition and the read-once final evaluation (ainerzero.V9.P59).

RESEARCH_LOG R20261028-S1-phase1-final-eval.  CPU only: the sealed dataset here is a fixture
built from the synthetic development split relabelled ``final``; the real sealed dataset under
artifacts/v9/s1/final-sealed/ is never opened by these tests.
"""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

import pytest

from ainerzero.v9.experiments.s1 import data, final_eval, prereg, spec, worker

from s1_testkit import FAKE_COUNTS, FAKE_IDENTITY, fake_smoke, write_frozen, write_research_log

FINAL = spec.FINAL_EXPERIMENT_ID


def _final_fixture(dataset_dir: Path, staging: Path) -> dict:
    """A final dataset with the real layout, made from the synthetic development split."""
    for kind in ("packets", "truth"):
        (staging / kind).mkdir(parents=True, exist_ok=True)
        rows = [json.loads(line) for line in (dataset_dir / kind / "development.jsonl").read_text().splitlines() if line]
        with open(staging / kind / "final.jsonl", "w", encoding="utf-8") as handle:
            for row in rows:
                row["partition"] = "final"
                handle.write(json.dumps(row, sort_keys=True) + "\n")
    episodes = {json.loads(line)["episode_id"] for line in (staging / "packets/final.jsonl").read_text().splitlines()}
    packets = len((staging / "packets/final.jsonl").read_text().splitlines())
    counts = {"final_worlds": len(episodes), "final_episodes": len(episodes), "final_packets": packets}
    (staging / "export_meta.json").write_text(json.dumps({"counts": counts}), encoding="utf-8")
    return counts


@pytest.fixture
def sealed(tmp_path, synthetic_dataset):
    _manifest, dataset_dir, _plan = synthetic_dataset
    counts = _final_fixture(dataset_dir, tmp_path / "staging")
    record = data.seal_final_dataset(tmp_path / "staging", sealed_root=tmp_path / "sealed", sealed_by="test", counts=counts)
    yield tmp_path / "sealed" / record["dataset_digest"], record
    for path in (tmp_path / "sealed").rglob("*"):
        os.chmod(path, 0o755 if path.is_dir() else 0o644)
    os.chmod(tmp_path / "sealed", 0o755)


# --- the seal ------------------------------------------------------------------
def test_seal_is_read_only_named_by_digest_and_verifies(sealed):
    sealed_dir, record = sealed
    assert sealed_dir.name == record["dataset_digest"] == data.final_digest(record["files"])
    state = data.verify_sealed_final(sealed_dir, expected_digest=record["dataset_digest"])
    assert state["status"] == "passed" and state["already_read"] is False
    assert not os.access(sealed_dir / "packets/final.jsonl", os.W_OK)
    assert data.verify_sealed_final(sealed_dir, expected_digest="0" * 64)["status"] == "failed"


def test_a_changed_sealed_file_fails_verification(sealed):
    sealed_dir, record = sealed
    target = sealed_dir / "truth/final.jsonl"
    os.chmod(sealed_dir / "truth", 0o755)
    os.chmod(target, 0o644)
    with open(target, "a", encoding="utf-8") as handle:
        handle.write("\n")
    state = data.verify_sealed_final(sealed_dir, expected_digest=record["dataset_digest"])
    assert state["status"] == "failed" and "a sealed file changed after sealing" in state["problems"]
    with pytest.raises(data.FinalPartitionSealed, match="failed verification"):
        data.open_sealed_final_once(sealed_dir, expected_digest=record["dataset_digest"], reader={"t": 1})


def test_sealing_refuses_to_overwrite(sealed, tmp_path, synthetic_dataset):
    _sealed_dir, record = sealed
    with pytest.raises(data.DatasetError, match="refusing to overwrite"):
        data.seal_final_dataset(tmp_path / "staging", sealed_root=tmp_path / "sealed", sealed_by="test",
                                counts=record["counts"])


# --- read once -------------------------------------------------------------------
def test_final_is_unreadable_without_an_issued_token(sealed):
    sealed_dir, record = sealed
    with pytest.raises(data.FinalPartitionSealed):
        data.load_training_episodes(sealed_dir, "final")
    forged = data.FinalReadToken(record["dataset_digest"], sealed_dir, data.final_marker_path(sealed_dir), "f" * 64)
    with pytest.raises(data.FinalPartitionSealed):
        data.load_truth_view(sealed_dir, "final", final_token=forged)
    with pytest.raises(data.FinalPartitionSealed):
        data.FinalView(forged)


def test_open_once_creates_the_marker_reads_and_refuses_a_second_read(sealed):
    sealed_dir, record = sealed
    token = data.open_sealed_final_once(sealed_dir, expected_digest=record["dataset_digest"], reader={"t": 1})
    marker = data.final_marker_path(sealed_dir)
    assert marker.is_file() and json.loads(marker.read_text())["dataset_digest"] == record["dataset_digest"]
    view = data.FinalView(token)
    assert view.partition == "final" and len(view.episodes()) == record["counts"]["final_episodes"]
    assert view.truth_view() and view.windows()["obs"].shape[0] > 0
    assert data.verify_sealed_final(sealed_dir, expected_digest=record["dataset_digest"])["already_read"] is True
    with pytest.raises(data.FinalPartitionSealed, match="already read"):
        data.open_sealed_final_once(sealed_dir, expected_digest=record["dataset_digest"], reader={"t": 2})


def test_a_token_does_not_open_another_directory(sealed, tmp_path):
    sealed_dir, record = sealed
    token = data.open_sealed_final_once(sealed_dir, expected_digest=record["dataset_digest"], reader={"t": 1})
    other = tmp_path / "other"
    shutil.copytree(sealed_dir, other)
    with pytest.raises(data.FinalPartitionSealed, match="different sealed directory"):
        data.load_training_episodes(other, "final", final_token=token)


def test_train_and_development_paths_still_refuse_final():
    with pytest.raises(data.FinalPartitionSealed):
        data.require_partition("final")
    assert data.require_partition("development") == "development"


# --- the frozen document's final_eval section -------------------------------------
def _section(digest: str = "a" * 64) -> dict:
    return {
        "sealed_dataset_digest": digest,
        "wall_seconds": spec.FINAL_EVAL_WALL_SECONDS,
        "expected_counts": {"final_worlds": 200, "final_episodes": 200, "final_packets": 950},
        "data_plan": dict(spec.FINAL_DATA_PLAN, families=list(spec.FINAL_DATA_PLAN["families"])),
        "registration": "RESEARCH_LOG R20261028-S1-phase1-final-eval",
    }


def _final_frozen(identity=FAKE_IDENTITY, section=None):
    draft = prereg.build_draft(data_identity=identity, parameter_counts=FAKE_COUNTS, created_unix=1_000.0,
                               experiment_id=FINAL, budget_registration=spec.R11_BUDGET_REGISTRATION)
    draft["final_eval"] = _section() if section is None else section
    return prereg.build_frozen(draft, smoke=fake_smoke(), data_identity=identity, created_unix=1_000.0)


def test_final_document_freezes_with_its_section_and_nine_inherited_cells():
    frozen = _final_frozen()
    assert prereg.validate(frozen) == []
    assert len(frozen["inheritance"]["cells"]) == 9
    assert ("arm4", 0) in {(c["arm_id"], c["seed"]) for c in frozen["inheritance"]["cells"]}


@pytest.mark.parametrize(
    "mutate, needle",
    [
        (lambda s: s.update(wall_seconds=9_999), "wall_seconds"),
        (lambda s: s.update(sealed_dataset_digest="xyz"), "64-hex"),
        (lambda s: s["expected_counts"].update(final_worlds=10), "expected_counts"),
        (lambda s: s["data_plan"].update(worlds=10), "data_plan"),
    ],
)
def test_a_tampered_final_section_is_refused(mutate, needle):
    frozen = _final_frozen()
    mutate(frozen["final_eval"])
    assert any(needle in r for r in prereg.validate(frozen))


def test_only_the_final_document_may_carry_the_section():
    frozen = _final_frozen()
    del frozen["final_eval"]
    assert any("must carry its final_eval section" in r for r in prereg.validate(frozen))
    r15 = prereg.build_frozen(
        prereg.build_draft(data_identity=FAKE_IDENTITY, parameter_counts=FAKE_COUNTS, created_unix=1_000.0,
                           experiment_id=spec.R15_EXPERIMENT_ID, budget_registration=spec.R11_BUDGET_REGISTRATION),
        smoke=fake_smoke(), data_identity=FAKE_IDENTITY, created_unix=1_000.0)
    r15["final_eval"] = _section()
    assert any("only the final evaluation document" in r for r in prereg.validate(r15))


# --- entry refusals happen before any ledger write ----------------------------------
def _install_dataset_root(root: Path, tmp_path: Path, manifest: dict, dataset_dir: Path) -> None:
    target = tmp_path / "datasets" / manifest["dataset_digest"]
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(dataset_dir, target)
    data.write_dataset_ref(root, manifest, target)


def test_final_eval_refuses_unapproved_already_read_and_a_bad_budget_without_writing(
    tmp_path, monkeypatch, synthetic_dataset, canonical_root
):
    manifest, dataset_dir, _plan = synthetic_dataset
    root = canonical_root
    _install_dataset_root(root, tmp_path, manifest, dataset_dir)
    counts = _final_fixture(dataset_dir, tmp_path / "final-staging")
    record = data.seal_final_dataset(tmp_path / "final-staging", sealed_root=tmp_path / "final-sealed",
                                     sealed_by="test", counts=counts)
    monkeypatch.setattr(spec, "FINAL_SEALED_ROOT", tmp_path / "final-sealed")
    # the fixture is smaller than the registered 200 worlds: register its own plan for this test
    plan = dict(spec.FINAL_DATA_PLAN, worlds=counts["final_worlds"])
    monkeypatch.setattr(spec, "FINAL_DATA_PLAN", plan)
    section = dict(_section(record["dataset_digest"]), expected_counts=counts,
                   data_plan=dict(plan, families=list(plan["families"])))
    document = _final_frozen(identity=data.dataset_identity(manifest), section=section)
    path, digest, _ = write_frozen(root / "final_pre_registration.json", document=document)
    ledger = root / "control.sqlite3"
    before = ledger.read_bytes()

    def run():
        return worker.run_worker("final-eval", output_root=root, limits=spec.RESOURCE_LIMITS,
                                 wall_budget_seconds=spec.FINAL_EVAL_WALL_SECONDS, prereg_path=path)

    monkeypatch.setattr(spec, "RESEARCH_LOG", write_research_log(tmp_path / "RESEARCH_LOG.md"))
    report = run()
    assert report["refused_stage"] == "preregistration_not_approved", report
    assert ledger.read_bytes() == before and not data.final_marker_path(spec.FINAL_SEALED_ROOT / record["dataset_digest"]).exists()

    monkeypatch.setattr(spec, "RESEARCH_LOG", write_research_log(tmp_path / "RESEARCH_LOG.md", approval_sha=digest))
    marker = data.final_marker_path(spec.FINAL_SEALED_ROOT / record["dataset_digest"])
    marker.write_text("{}")
    report = run()
    assert report["refused_stage"] == "final_already_read", report
    marker.unlink()
    assert ledger.read_bytes() == before

    report = worker.run_worker("final-eval", output_root=root, limits=spec.RESOURCE_LIMITS,
                               wall_budget_seconds=spec.FINAL_EVAL_WALL_SECONDS + 1, prereg_path=path)
    assert report["refused_stage"] == "final_eval_budget_invalid", report
    assert ledger.read_bytes() == before and not marker.exists()


def test_train_refuses_every_cell_of_the_final_document(tmp_path, monkeypatch, synthetic_dataset, canonical_root):
    manifest, dataset_dir, _plan = synthetic_dataset
    root = canonical_root
    _install_dataset_root(root, tmp_path, manifest, dataset_dir)
    document = _final_frozen(identity=data.dataset_identity(manifest))
    path, digest, _ = write_frozen(root / "final_pre_registration.json", document=document)
    monkeypatch.setattr(spec, "RESEARCH_LOG", write_research_log(tmp_path / "RESEARCH_LOG.md", approval_sha=digest))
    monkeypatch.setattr(worker, "_train", lambda *a, **k: (_ for _ in ()).throw(AssertionError("trained")))
    for cell in spec.FINAL_INHERITANCE["cells"]:
        report = worker.run_worker("train", output_root=root, limits=spec.RESOURCE_LIMITS, wall_budget_seconds=1_200,
                                   prereg_path=path, arm=cell["arm_id"], seed=cell["seed"])
        assert report["refused_stage"] == "inherited_cell_not_trainable", report


def test_the_section_reasons_and_preconditions_reject_a_non_final_document():
    assert final_eval.section_reasons({"experiment_id": spec.R15_EXPERIMENT_ID}) == []
    pre = final_eval.preconditions(document={"experiment_id": spec.R15_EXPERIMENT_ID}, verified={"sha256": "0" * 64},
                                   output_root=Path("."), ledger_path=Path("."), research_log=None,
                                   wall_budget_seconds=10)
    assert pre["refused_stage"] == "not_a_final_eval_document"
