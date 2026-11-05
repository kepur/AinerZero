"""Train-mode gate tests added in r3: P-1 (canonical log), P-2 (source binding),
P-3 (dataset digest).

These are the three holes V9.P11 found in r2: ``--research-log`` could redirect
the approval gate, and the gate itself only pinned the document SHA, so the code
and the data that actually run were not bound to the frozen document.  Every
case here drives the real gate (``commands.mode_train`` / ``worker.run_worker``)
and asserts both the refusal reason and that nothing was started.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from types import SimpleNamespace

from ainerzero.v9.experiments.s1 import commands, data, prereg, spec, worker

from s1_testkit import FAKE_COUNTS, fake_smoke, frozen_document, write_frozen, write_research_log

DEADLINE = 450


# --- helpers --------------------------------------------------------------
def _args(
    tmp_path: Path,
    prereg_path: Path,
    *,
    research_log: Path | None = None,
    arm: str = "arm2",
    seed: int = 0,
) -> SimpleNamespace:
    return SimpleNamespace(
        mode="train",
        output_root=tmp_path / "phase1",
        prereg=prereg_path,
        limits_file=None,
        wall_budget_seconds=None,
        research_log=research_log,
        arm=arm,
        seed=seed,
    )


def _install_dataset_root(tmp_path: Path, manifest: dict, dataset_dir: Path) -> Path:
    """A run root whose dataset_ref points at a copy named after its digest."""
    target = tmp_path / "datasets" / manifest["dataset_digest"]
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(dataset_dir, target)
    root = tmp_path / "phase1"
    root.mkdir(parents=True, exist_ok=True)
    data.write_dataset_ref(root, manifest, target)
    return root


def _frozen_with_identity(identity: dict, *, created_unix: float = 1_000.0) -> dict:
    return prereg.build_frozen(
        prereg.build_draft(data_identity=identity, parameter_counts=FAKE_COUNTS),
        smoke=fake_smoke(),
        data_identity=identity,
        created_unix=created_unix,
    )


# --- P-1: train reads spec.RESEARCH_LOG only ------------------------------
def test_a_relocated_research_log_is_refused_even_with_the_right_line(tmp_path, monkeypatch, canonical_root):
    """V9.P11 C5a: an executor-writable log carrying the exact line must not approve."""
    path, digest, _document = write_frozen(tmp_path / "pre_registration.json")
    canonical = write_research_log(tmp_path / "RESEARCH_LOG.md")  # no approval line
    monkeypatch.setattr(spec, "RESEARCH_LOG", canonical)
    forged = write_research_log(tmp_path / "forged" / "RESEARCH_LOG.md", approval_sha=digest)

    def _must_not_start(**_kwargs):  # pragma: no cover - tripwire
        raise AssertionError("train started from a relocated research log")

    monkeypatch.setattr(commands, "_supervised_worker", _must_not_start)
    report, code = commands.s1_phase1_command(_args(tmp_path, path, research_log=forged))
    assert code == commands.EXIT_REFUSED_APPROVAL == 3
    assert report["status"] == "refused"
    assert report["stage"] == "research_log_not_canonical"
    assert report["requested_research_log"] == str(forged)
    assert Path(report["canonical_research_log"]).resolve() == canonical.resolve()


def test_the_canonical_log_is_accepted_when_spelled_differently(tmp_path, monkeypatch, canonical_root):
    """A path that resolves to spec.RESEARCH_LOG is the canonical log, not a redirect."""
    path, digest, _document = write_frozen(tmp_path / "pre_registration.json")
    canonical = write_research_log(tmp_path / "RESEARCH_LOG.md", approval_sha=digest)
    monkeypatch.setattr(spec, "RESEARCH_LOG", canonical)
    monkeypatch.setattr(
        commands.data,
        "dataset_binding_state",
        lambda root, digest_: {"status": "passed", "expected_dataset_digest": digest_,
                               "actual_dataset_digest": digest_},
    )
    monkeypatch.setattr(commands, "_supervised_worker", lambda mode, **kwargs: {"status": "completed"})
    odd_spelling = tmp_path / "sub" / ".." / "RESEARCH_LOG.md"
    report = commands.mode_train(_args(tmp_path, path, research_log=odd_spelling))
    assert report["status"] == "completed"


def test_worker_refuses_a_relocated_research_log(tmp_path, monkeypatch, canonical_root):
    path, digest, _document = write_frozen(tmp_path / "pre_registration.json")
    canonical = write_research_log(tmp_path / "RESEARCH_LOG.md")
    monkeypatch.setattr(spec, "RESEARCH_LOG", canonical)
    forged = write_research_log(tmp_path / "forged" / "RESEARCH_LOG.md", approval_sha=digest)
    (tmp_path / "phase1").mkdir(exist_ok=True)
    monkeypatch.setattr(worker, "_train", _must_not_train)
    report = worker.run_worker(
        "train",
        output_root=tmp_path / "phase1",
        limits=spec.RESOURCE_LIMITS,
        wall_budget_seconds=DEADLINE,
        prereg_path=path,
        research_log=forged,
    )
    assert report["status"] == "refused"
    assert report["refused_stage"] == "research_log_not_canonical"
    assert "run_id" not in report


# --- P-2: the bound sources must still match -----------------------------
def _document_with_drift() -> tuple[dict, str]:
    document = frozen_document()
    document["source_identity"]["package_files"]["src/ainerzero/v9/experiments/s1/spec.py"] = "0" * 64
    return document, prereg.document_sha256(document)


def test_train_refuses_when_a_bound_source_drifted(tmp_path, monkeypatch, canonical_root):
    document, digest = _document_with_drift()
    path, digest, _document = write_frozen(tmp_path / "pre_registration.json", document=document)
    log = write_research_log(tmp_path / "RESEARCH_LOG.md", approval_sha=digest)
    monkeypatch.setattr(spec, "RESEARCH_LOG", log)

    def _must_not_start(**_kwargs):  # pragma: no cover - tripwire
        raise AssertionError("train started although the frozen sources drifted")

    monkeypatch.setattr(commands, "_supervised_worker", _must_not_start)
    report, code = commands.s1_phase1_command(_args(tmp_path, path))
    assert code == commands.EXIT_REFUSED_APPROVAL == 3
    assert report["stage"] == "source_binding_drift"
    assert report["source_binding"]["status"] == "failed"
    assert "src/ainerzero/v9/experiments/s1/spec.py" in report["source_binding"]["drifted"]


def test_worker_refuses_when_a_bound_source_drifted(tmp_path, monkeypatch, canonical_root):
    document, _digest = _document_with_drift()
    path, digest, _document = write_frozen(tmp_path / "pre_registration.json", document=document)
    log = write_research_log(tmp_path / "RESEARCH_LOG.md", approval_sha=digest)
    monkeypatch.setattr(spec, "RESEARCH_LOG", log)
    (tmp_path / "phase1").mkdir(exist_ok=True)
    monkeypatch.setattr(worker, "_train", _must_not_train)
    report = worker.run_worker(
        "train",
        output_root=tmp_path / "phase1",
        limits=spec.RESOURCE_LIMITS,
        wall_budget_seconds=DEADLINE,
        prereg_path=path,
        research_log=None,
    )
    assert report["status"] == "refused"
    assert report["refused_stage"] == "source_binding_drift"


def test_a_missing_bound_file_is_drift(tmp_path):
    document = frozen_document()
    document["source_identity"]["package_files"]["src/ainerzero/v9/experiments/s1/ghost.py"] = "1" * 64
    state = prereg.source_binding_state(document)
    assert state["status"] == "failed"
    assert state["files"]["src/ainerzero/v9/experiments/s1/ghost.py"]["present"] is False


# --- P-3: the dataset must be the frozen one -----------------------------
def test_dataset_binding_fails_without_a_dataset_reference(tmp_path):
    state = data.dataset_binding_state(tmp_path, "a" * 64)
    assert state["status"] == "failed"
    assert "missing dataset reference" in state["reason"]


def test_dataset_binding_passes_and_rejects_another_digest(tmp_path, synthetic_dataset):
    manifest, dataset_dir, _plan = synthetic_dataset
    root = _install_dataset_root(tmp_path, manifest, dataset_dir)
    digest = manifest["dataset_digest"]
    assert data.dataset_binding_state(root, digest)["status"] == "passed"
    other = data.dataset_binding_state(root, "b" * 64)
    assert other["status"] == "failed"
    assert other["actual_dataset_digest"] == digest


def test_train_refuses_when_the_dataset_digest_differs(tmp_path, monkeypatch, canonical_root):
    path, digest, _document = write_frozen(tmp_path / "pre_registration.json")
    log = write_research_log(tmp_path / "RESEARCH_LOG.md", approval_sha=digest)
    monkeypatch.setattr(spec, "RESEARCH_LOG", log)
    (tmp_path / "phase1").mkdir(exist_ok=True)  # no dataset_ref.json -> fail closed

    def _must_not_start(**_kwargs):  # pragma: no cover - tripwire
        raise AssertionError("train started without the frozen dataset")

    monkeypatch.setattr(commands, "_supervised_worker", _must_not_start)
    report, code = commands.s1_phase1_command(_args(tmp_path, path))
    assert code == commands.EXIT_REFUSED_APPROVAL == 3
    assert report["stage"] == "dataset_identity_mismatch"
    assert report["dataset"]["status"] == "failed"


def test_worker_refuses_when_the_dataset_digest_differs(tmp_path, monkeypatch, canonical_root):
    path, digest, _document = write_frozen(tmp_path / "pre_registration.json")
    log = write_research_log(tmp_path / "RESEARCH_LOG.md", approval_sha=digest)
    monkeypatch.setattr(spec, "RESEARCH_LOG", log)
    (tmp_path / "phase1").mkdir(exist_ok=True)
    monkeypatch.setattr(worker, "_train", _must_not_train)
    report = worker.run_worker(
        "train",
        output_root=tmp_path / "phase1",
        limits=spec.RESOURCE_LIMITS,
        wall_budget_seconds=DEADLINE,
        prereg_path=path,
        research_log=None,
    )
    assert report["status"] == "refused"
    assert report["refused_stage"] == "dataset_identity_mismatch"


# --- all gates green ------------------------------------------------------
def test_approved_document_with_matching_sources_and_dataset_is_released(
    tmp_path, monkeypatch, synthetic_dataset
, canonical_root):
    manifest, dataset_dir, _plan = synthetic_dataset
    root = _install_dataset_root(tmp_path, manifest, dataset_dir)
    identity = data.dataset_identity(manifest)
    document = _frozen_with_identity(identity)
    path, digest, _document = write_frozen(root / "pre_registration.json", document=document)
    log = write_research_log(tmp_path / "RESEARCH_LOG.md", approval_sha=digest)
    monkeypatch.setattr(spec, "RESEARCH_LOG", log)
    captured: dict = {}
    monkeypatch.setattr(
        commands,
        "_supervised_worker",
        lambda mode, **kwargs: captured.update(kwargs) or {"status": "completed", "mode": "train"},
    )
    report = commands.mode_train(_args(tmp_path, path))
    assert report["status"] == "completed"
    assert captured["budget"] == DEADLINE
    assert Path(captured["research_log"]).resolve() == log.resolve()
    # Reaching the worker means the approval, source-binding and dataset gates
    # all passed; the stub replaces the worker, so it carries no approval field.


def _must_not_train(*_args, **_kwargs):  # pragma: no cover - tripwire
    raise AssertionError("worker started training although a gate should have refused")
