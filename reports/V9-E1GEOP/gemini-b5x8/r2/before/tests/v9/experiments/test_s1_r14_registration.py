"""r14 experiment identity plus inheritance of verified cells (ainerzero.V9.P49).

RESEARCH_LOG R20261028-S1-phase1-r14-budget: the user approved r14 with the same
scientific values, a 2.5 h total cap, and inheritance of the three cells whose
params.npz were bitwise identical across r12 and r13.  These tests pin:

* the identity rules (r14 current, r11-r13 history);
* the inheritance section: frozen only for r14, equal to the spec byte for byte,
  structurally valid, and refused when tampered with;
* train refuses an inherited cell before the first ledger write;
* eval binds an inherited cell to its registered source run only, and refuses a
  wrong run, a wrong SHA, a wrong source experiment, a tampered checkpoint or a
  hand-edited section.

Pure CPU; the binding tests use the r5 CPU substitute backend and a ledger in tmp_path.
"""

from __future__ import annotations

import copy
import json
import shutil
from pathlib import Path

import pytest

from ainerzero.v9.experiments.s1 import data, prereg, spec, worker

from s1_testkit import FAKE_COUNTS, FAKE_IDENTITY, fake_smoke, write_frozen, write_research_log
from test_s1_r5_ledger import _document, _FakeBackend, _FakeGuard, _patch_data

R14 = spec.R14_EXPERIMENT_ID
R13 = spec.R13_EXPERIMENT_ID


def _draft(experiment_id: str = R14, identity=FAKE_IDENTITY):
    return prereg.build_draft(
        data_identity=identity,
        parameter_counts=FAKE_COUNTS,
        created_unix=1_000.0,
        experiment_id=experiment_id,
        budget_registration=spec.R11_BUDGET_REGISTRATION,
    )


def _frozen(experiment_id: str = R14, identity=FAKE_IDENTITY):
    return prereg.build_frozen(
        _draft(experiment_id, identity),
        smoke=fake_smoke(),
        data_identity=identity,
        created_unix=1_000.0,
    )


# --- identity --------------------------------------------------------------
def test_r14_is_current_and_r11_to_r13_stay_registered_history():
    assert R14 == "s1-phase1-20261028-r14"
    # r15 (ainerzero.V9.P53): the current identity moved on to r15; r14 stays registered history.
    assert spec.CURRENT_EXPERIMENT_ID == spec.R15_EXPERIMENT_ID
    assert spec.REGISTERED_EXPERIMENT_IDS == (
        spec.R11_EXPERIMENT_ID,
        spec.R12_EXPERIMENT_ID,
        R13,
        R14,
        spec.R15_EXPERIMENT_ID,
        spec.FINAL_EXPERIMENT_ID,  # P59: the eval-only final identity
    )
    assert worker.document_experiment_scope({"experiment_id": R14}) == R14
    assert worker.document_experiment_scope({"experiment_id": R13}) == R13
    # r15 is registered since P53; an unregistered placeholder keeps the whole-ledger scope
    assert worker.document_experiment_scope({"experiment_id": "s1-phase1-20261028-r16"}) is None


# --- inheritance section ----------------------------------------------------
def test_only_r14_freezes_an_inheritance_section_equal_to_the_spec():
    frozen = _frozen(R14)
    assert frozen["inheritance"] == json.loads(json.dumps(spec.R14_INHERITANCE))
    assert prereg.validate(frozen) == []
    for history in (spec.R11_EXPERIMENT_ID, spec.R12_EXPERIMENT_ID, R13):
        assert "inheritance" not in _frozen(history)


def test_the_registered_inheritance_is_structurally_valid_and_names_the_r13_runs():
    section = spec.R14_INHERITANCE
    assert prereg.inheritance_structure_reasons(section, own_experiment_id=R14) == []
    assert section["source_experiment_id"] == R13
    assert section["source_preregistration_sha256"] == (
        "1cb98a21052c6db9b8ce4d8ff0ddcaecd996407e26d00143a62bd1e522ff5b30"
    )
    cells = {(c["arm_id"], c["seed"]): c for c in section["cells"]}
    assert set(cells) == {("arm2", 0), ("arm2", 1), ("arm3", 0)}
    # arm2 seed 2 is the A2 re-run, never inherited; nothing of arm4 is inherited
    assert ("arm2", 2) not in cells and not any(arm == "arm4" for arm, _ in cells)
    assert section["approved_total_wall_seconds"] == 9_000


@pytest.mark.parametrize(
    "mutate, needle",
    [
        (lambda s: s["cells"][0].update(params_sha256="0" * 64), "differs from the registered"),
        (lambda s: s["cells"].append({**s["cells"][0], "seed": 2}), "differs from the registered"),
        (lambda s: s["cells"].pop(), "differs from the registered"),
        (lambda s: s.update(source_experiment_id=R14), "differs from the registered"),
    ],
)
def test_a_tampered_inheritance_section_is_refused(mutate, needle):
    frozen = _frozen(R14)
    mutate(frozen["inheritance"])
    assert any(needle in reason for reason in prereg.validate(frozen))


def test_a_missing_or_foreign_inheritance_section_is_refused():
    frozen = _frozen(R14)
    del frozen["inheritance"]
    assert any("must carry its registered inheritance" in r for r in prereg.validate(frozen))
    r13 = _frozen(R13)
    r13["inheritance"] = json.loads(json.dumps(spec.R14_INHERITANCE))
    assert any("has no registered inheritance" in r for r in prereg.validate(r13))


@pytest.mark.parametrize(
    "mutate, needle",
    [
        (lambda s: s.update(source_experiment_id=R14), "another registered identity"),
        (lambda s: s.update(source_experiment_id="s1-phase1-20261021"), "another registered identity"),
        (lambda s: s.update(source_preregistration_sha256="xyz"), "64-hex"),
        (lambda s: s["cells"][0].update(arm_id="arm1"), "not a trainable arm"),
        (lambda s: s["cells"][0].update(seed=3), "not a trainable arm"),
        (lambda s: s["cells"].append(dict(s["cells"][0])), "appears twice"),
        (lambda s: s["cells"][0].update(source_run_id="short"), "not a run id"),
        (lambda s: s["cells"][0].update(params_sha256="A" * 64), "not a SHA256"),
        (lambda s: s.update(cells=[]), "lists no cells"),
    ],
)
def test_structure_checks_catch_each_malformed_field(mutate, needle):
    section = copy.deepcopy(spec.R14_INHERITANCE)
    mutate(section)
    assert any(needle in r for r in prereg.inheritance_structure_reasons(section, own_experiment_id=R14))


def test_inherited_cell_only_trusts_the_registered_section():
    document = _frozen(R14)
    assert worker.inherited_cell(document, arm_id="arm2", seed=0)["source_run_id"] == (
        "19f2d1eb4bf04da4909d87501348028d"
    )
    assert worker.inherited_cell(document, arm_id="arm3", seed=0)["source_experiment_id"] == R13
    assert worker.inherited_cell(document, arm_id="arm2", seed=2) is None
    assert worker.inherited_cell(document, arm_id="arm4", seed=0) is None
    forged = copy.deepcopy(document)
    forged["inheritance"]["cells"].append(
        {"arm_id": "arm4", "seed": 0, "source_run_id": "f" * 32, "params_sha256": "f" * 64}
    )
    assert worker.inherited_cell(forged, arm_id="arm4", seed=0) is None
    assert worker.inherited_cell(forged, arm_id="arm2", seed=0) is None  # whole section untrusted
    assert worker.inherited_cell(_frozen(R13), arm_id="arm2", seed=0) is None


# --- train refuses an inherited cell before the first ledger write ----------
def _install_dataset_root(root: Path, tmp_path: Path, manifest: dict, dataset_dir: Path) -> None:
    target = tmp_path / "datasets" / manifest["dataset_digest"]
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(dataset_dir, target)
    data.write_dataset_ref(root, manifest, target)


def test_train_refuses_an_inherited_cell_and_writes_nothing(
    tmp_path, monkeypatch, synthetic_dataset, canonical_root
):
    manifest, dataset_dir, _plan = synthetic_dataset
    root = canonical_root
    _install_dataset_root(root, tmp_path, manifest, dataset_dir)
    document = _frozen(R14, identity=data.dataset_identity(manifest))
    path, digest, _ = write_frozen(root / "pre_registration.json", document=document)
    monkeypatch.setattr(spec, "RESEARCH_LOG", write_research_log(tmp_path / "RESEARCH_LOG.md", approval_sha=digest))

    def _must_not_train(*_a, **_k):  # pragma: no cover - tripwire
        raise AssertionError("an inherited cell started training")

    monkeypatch.setattr(worker, "_train", _must_not_train)
    ledger = root / "control.sqlite3"
    before = ledger.read_bytes()
    for arm, seed in (("arm2", 0), ("arm2", 1), ("arm3", 0)):
        report = worker.run_worker(
            "train",
            output_root=root,
            limits=spec.RESOURCE_LIMITS,
            wall_budget_seconds=1_200,
            prereg_path=path,
            arm=arm,
            seed=seed,
        )
        assert report["refused_stage"] == "inherited_cell_not_trainable", report
        assert report["inherited"]["source_experiment_id"] == R13
        assert "run_id" not in report
    assert ledger.read_bytes() == before

    # Control: a non-inherited cell passes the inheritance guard and reaches the
    # next pre-write guard (forced here), so the guard is specific to the cells.
    monkeypatch.setattr(worker, "phase_total_wall_seconds", lambda *a, **k: 1e9)
    report = worker.run_worker(
        "train",
        output_root=root,
        limits=spec.RESOURCE_LIMITS,
        wall_budget_seconds=1_200,
        prereg_path=path,
        arm="arm2",
        seed=2,
    )
    assert report["refused_stage"] == "phase_budget_exceeded", report
    assert ledger.read_bytes() == before


# --- eval binds an inherited cell to its source run only --------------------
def _source_run(root: Path, monkeypatch) -> tuple[str, str]:
    """A completed run of arm2 seed 0 under experiment r13 in an isolated ledger."""
    _patch_data(monkeypatch, root)
    ledger = worker.PrepLedger(root / "control.sqlite3")
    document = {**_document(3), "experiment_id": R13}
    run_id = worker._open_train_run(document, ledger, {"document_sha256": "a" * 64}, arm_id="arm2", seed=0)
    ledger.begin_work(run_id, work_state="training")
    details = worker._train(
        _document(3), root, ledger, run_id, _FakeGuard(),
        arm_id="arm2", seed=0, prereg_sha256="a" * 64, backend=_FakeBackend(),
    )
    ledger.finish(
        run_id,
        "completed",
        worker.TRAIN_RECEIPT_PREFIX
        + json.dumps(details["receipt"], sort_keys=True, separators=(",", ":")),
    )
    ledger.close()
    return run_id, spec.sha256_file(root / "runs" / run_id / "params.npz")


def _fixture_section(run_id: str, params_sha: str, **overrides) -> dict:
    section = copy.deepcopy(spec.R14_INHERITANCE)
    section["source_preregistration_sha256"] = "a" * 64
    section["cells"] = [{"arm_id": "arm2", "seed": 0, "source_run_id": run_id, "params_sha256": params_sha}]
    section.update(overrides)
    return section


def _bind(root: Path, section: dict, monkeypatch, *, document_section=None, seed: int = 0):
    monkeypatch.setattr(spec, "INHERITANCE_BY_EXPERIMENT", {R14: section})
    document = {"experiment_id": R14, "inheritance": copy.deepcopy(section if document_section is None else document_section)}
    return worker._bind_for_document(
        document, root, arm_id="arm2", seed=seed, prereg_sha256="b" * 64, updates=3,
        ledger_path=root / "control.sqlite3",
    )


def test_eval_binds_an_inherited_cell_to_its_registered_source_run(tmp_path, monkeypatch):
    root = tmp_path / "host"
    run_id, params_sha = _source_run(root, monkeypatch)
    binding = _bind(root, _fixture_section(run_id, params_sha), monkeypatch)
    assert binding["run"].run_id == run_id
    assert binding["inherited"]["source_experiment_id"] == R13
    assert binding["final"]["sha256"] == params_sha
    # the same cell under the r14 SHA alone (no inheritance) has nothing to bind
    with pytest.raises(worker.EvalBindingError, match="no completed run binds"):
        worker._bind_for_document(
            {"experiment_id": R14}, root, arm_id="arm2", seed=0, prereg_sha256="b" * 64,
            updates=3, ledger_path=root / "control.sqlite3",
        )


@pytest.mark.parametrize(
    "case, needle",
    [
        ("wrong_run", "not the registered source run"),
        ("wrong_sha", "does not equal the registered"),
        ("wrong_source_experiment", "belongs to experiment"),
        ("wrong_source_prereg", "no completed run binds"),
        ("hand_edited_document", "no completed run binds"),
        ("tampered_checkpoint", "does not match the original receipt SHA"),
    ],
)
def test_eval_refuses_every_inherited_binding_that_does_not_match(tmp_path, monkeypatch, case, needle):
    root = tmp_path / "host"
    run_id, params_sha = _source_run(root, monkeypatch)
    section = _fixture_section(run_id, params_sha)
    document_section = None
    if case == "wrong_run":
        section["cells"][0]["source_run_id"] = "0" * 32
    elif case == "wrong_sha":
        section["cells"][0]["params_sha256"] = "0" * 64
    elif case == "wrong_source_experiment":
        section["source_experiment_id"] = spec.R12_EXPERIMENT_ID
    elif case == "wrong_source_prereg":
        section["source_preregistration_sha256"] = "c" * 64
    elif case == "hand_edited_document":
        # the document's section differs from the registered one: not trusted at all
        document_section = _fixture_section(run_id, params_sha, approved_total_wall_seconds=99_999)
    elif case == "tampered_checkpoint":
        params = root / "runs" / run_id / "params.npz"
        params.chmod(0o644)
        with open(params, "ab") as handle:
            handle.write(b"tampered")
    with pytest.raises(worker.EvalBindingError, match=needle):
        _bind(root, section, monkeypatch, document_section=document_section)


def test_a_non_inherited_cell_keeps_the_original_binding(tmp_path, monkeypatch):
    root = tmp_path / "host"
    run_id, params_sha = _source_run(root, monkeypatch)
    section = _fixture_section(run_id, params_sha)
    monkeypatch.setattr(spec, "INHERITANCE_BY_EXPERIMENT", {R14: section})
    document = {"experiment_id": R14, "inheritance": copy.deepcopy(section)}
    # arm2 seed 0 under the source SHA without going through inheritance still binds the
    # same way the original function does (the wrapper adds checks, never removes them)
    direct = worker._bind_completed_run(
        root, arm_id="arm2", seed=0, prereg_sha256="a" * 64, updates=3,
        ledger_path=root / "control.sqlite3",
    )
    wrapped = worker._bind_for_document(
        document, root, arm_id="arm2", seed=0, prereg_sha256="b" * 64, updates=3,
        ledger_path=root / "control.sqlite3",
    )
    assert direct["run"].run_id == wrapped["run"].run_id == run_id
    assert "inherited" not in direct and wrapped["inherited"]["seed"] == 0
