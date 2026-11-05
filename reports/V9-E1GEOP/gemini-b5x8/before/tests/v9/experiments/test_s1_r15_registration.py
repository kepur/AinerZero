"""r15: few-shot query slice fix plus multi-source inheritance (ainerzero.V9.P53).

RESEARCH_LOG R20261028-S1-phase1-r15-budget.  r14's eval matched the full encoder
output (arm3: hidden 192) against topology nodes that store only ``h[:32]``; every
real arm failed.  These tests pin:

* one slicing rule (``spec.memory_key_slices``) whose widths equal the stored node
  widths and differ from ``hidden`` for every real arm (the r14 failure condition),
  and whose write slices equal the literal r14 slices (training math unchanged);
* few-shot with a sliced memory completes through ``probe_query`` and fails with a
  clear error when the full encoding is used (the r14 behaviour);
* the r15 identity and its multi-source inheritance: frozen equal to the spec,
  structurally valid, r14's archived single-source form still valid, tampering
  refused, per-cell source resolution, train refuses all 8 inherited cells, and
  eval binds each cell to its own source experiment and preregistration.
"""

from __future__ import annotations

import copy
import json
import shutil
from pathlib import Path

import numpy as np
import pytest

from ainerzero.v9.experiments.s1 import data, evaluation, prereg, spec, worker

from s1_testkit import FAKE_COUNTS, FAKE_IDENTITY, fake_smoke, write_frozen, write_research_log
from test_s1_r5_ledger import _document, _FakeBackend, _FakeGuard, _patch_data
from test_s1_r5_metrics import _episode

R15 = spec.R15_EXPERIMENT_ID
R14 = spec.R14_EXPERIMENT_ID
R13 = spec.R13_EXPERIMENT_ID
REPO = Path(__file__).resolve().parents[3]


def _draft(experiment_id: str = R15, identity=FAKE_IDENTITY):
    return prereg.build_draft(
        data_identity=identity,
        parameter_counts=FAKE_COUNTS,
        created_unix=1_000.0,
        experiment_id=experiment_id,
        budget_registration=spec.R11_BUDGET_REGISTRATION,
    )


def _frozen(experiment_id: str = R15, identity=FAKE_IDENTITY):
    return prereg.build_frozen(
        _draft(experiment_id, identity), smoke=fake_smoke(), data_identity=identity, created_unix=1_000.0
    )


# --- the one slicing rule -----------------------------------------------------
def test_probe_slices_match_the_stored_node_widths_not_hidden():
    for arm_id in ("arm2", "arm3", "arm4"):
        dims = spec.ARM_SPECS[arm_id]["dims"]
        start, stop = spec.memory_key_slices(arm_id)["probe"]
        node_width = int(dims["memory_channels"] if arm_id == "arm2" else dims["place_dim"])
        assert stop - start == node_width
        assert stop - start != int(dims["hidden"]), "the r14 failure condition"
    with pytest.raises(KeyError):
        spec.memory_key_slices("arm1")


def test_write_slices_equal_the_r14_literal_slices_so_training_is_unchanged():
    d2, d3, d4 = (spec.ARM_SPECS[a]["dims"] for a in ("arm2", "arm3", "arm4"))
    assert spec.memory_key_slices("arm2")["map"] == (0, int(d2["memory_channels"]))
    assert spec.memory_key_slices("arm3")["graph"] == (0, int(d3["place_dim"]))
    ch, pd = int(d4["memory_channels"]), int(d4["place_dim"])
    assert spec.memory_key_slices("arm4")["map"] == (0, ch)
    assert spec.memory_key_slices("arm4")["graph"] == (ch, ch + pd)
    # arms.py derives every write slice from this rule (source check: no literal left)
    text = (REPO / "src/ainerzero/v9/experiments/s1/arms.py").read_text(encoding="utf-8")
    assert "h_np[:, : self.channels]" not in text
    assert "h_np[:, : self.place_dim]" not in text
    assert "h_np[:, self.channels : self.channels + self.place_dim]" not in text
    assert text.count('self.memory_slice("map")') == 2 and text.count('self.memory_slice("graph")') == 2


class _SlicedBackend:
    """Like a real arm: the memory stores only h[:2] while encode returns all of h."""

    WIDTH = 2

    def step_sequence(self, model, sequence, *, stop=None, memory=None, pose=None):
        frames = len(sequence["obs"]) if stop is None else int(stop)
        nodes = np.asarray(sequence["obs"][:frames], dtype=np.float64)[:, : self.WIDTH]
        graph = {
            "nodes": nodes,
            "positions": np.zeros((frames, 2)),
            "edges": {(index, index + 1) for index in range(frames - 1)},
            "threshold": 0.0,
        }
        return {"steps": [], "memory": graph, "pose": np.zeros((1, 4))}

    def probe_graph(self, model, memory, pose=None):
        return memory

    def encode(self, model, obs_row):
        return np.asarray(obs_row, dtype=np.float64)

    def probe_query(self, model, obs_row):
        return self.encode(model, obs_row)[: self.WIDTH]


def _few_shot(backend):
    poses = [(float(i), 0, 0, 0) for i in range(6)]
    episode = _episode("S", "scene-S", "navigation", poses)
    rng = np.random.default_rng(0)
    sequence = {"episode_id": "S", "obs": rng.normal(size=(6, 5)).astype(np.float32)}
    return evaluation.few_shot_report(backend, object(), [sequence], [episode], k_values=(2,), query_limit=8)


def test_few_shot_with_a_sliced_memory_completes_through_probe_query():
    report = _few_shot(_SlicedBackend())
    assert "2" in report["curve"]


def test_the_r14_full_encoding_query_fails_with_a_clear_error():
    class _R14Behaviour(_SlicedBackend):
        def probe_query(self, model, obs_row):  # what r14 effectively did
            return self.encode(model, obs_row)

    with pytest.raises(ValueError, match="few-shot query width 5 does not match the probed memory node width 2"):
        _few_shot(_R14Behaviour())


# --- identity and inheritance -------------------------------------------------
def test_r15_is_current_and_r11_to_r14_stay_registered_history():
    assert R15 == "s1-phase1-20261028-r15"
    assert spec.CURRENT_EXPERIMENT_ID == R15
    # P59 appended the eval-only final identity after r15
    assert spec.REGISTERED_EXPERIMENT_IDS[-3:] == (R14, R15, spec.FINAL_EXPERIMENT_ID)
    assert worker.document_experiment_scope({"experiment_id": R15}) == R15


def test_r15_freezes_its_multi_source_section_and_r14_archive_still_validates():
    frozen = _frozen(R15)
    assert frozen["inheritance"] == json.loads(json.dumps(spec.R15_INHERITANCE))
    assert prereg.validate(frozen) == []
    assert prereg.inheritance_structure_reasons(spec.R15_INHERITANCE, own_experiment_id=R15) == []
    archived = REPO / "artifacts/v9/s1/phase1/r14/pre_registration.json"
    if archived.is_file():
        assert prereg.validate(json.loads(archived.read_text(encoding="utf-8"))) == []
    cells = {(c["arm_id"], c["seed"]): c["source_experiment_id"] for c in spec.R15_INHERITANCE["cells"]}
    assert len(cells) == 8 and ("arm4", 0) not in cells
    assert sorted(set(cells.values())) == sorted([R13, R14])


@pytest.mark.parametrize(
    "mutate, needle",
    [
        (lambda s: s["cells"][0].update(source_experiment_id=spec.R12_EXPERIMENT_ID), "names no listed source"),
        (lambda s: s["sources"].update({R15: s["sources"][R14]}), "another registered identity"),
        (lambda s: s.update(source_experiment_id=R13), "must not also name one source"),
        (lambda s: s.update(sources={}), "lists no sources"),
        (lambda s: s["sources"][R14].update(source_preregistration_sha256="x"), "64-hex"),
    ],
)
def test_multi_source_structure_checks(mutate, needle):
    section = copy.deepcopy(spec.R15_INHERITANCE)
    mutate(section)
    assert any(needle in r for r in prereg.inheritance_structure_reasons(section, own_experiment_id=R15))


def test_single_source_section_refuses_per_cell_sources():
    section = copy.deepcopy(spec.R14_INHERITANCE)
    section["cells"][0]["source_experiment_id"] = R13
    assert any("single-source section" in r for r in prereg.inheritance_structure_reasons(section, own_experiment_id=R14))


def test_inherited_cell_resolves_each_cells_own_source():
    document = _frozen(R15)
    r13_cell = worker.inherited_cell(document, arm_id="arm3", seed=0)
    r14_cell = worker.inherited_cell(document, arm_id="arm3", seed=1)
    assert r13_cell["source_experiment_id"] == R13
    assert r13_cell["source_preregistration_sha256"] == spec.R15_INHERITANCE["sources"][R13]["source_preregistration_sha256"]
    assert r14_cell["source_experiment_id"] == R14
    assert r14_cell["source_preregistration_sha256"] == spec.R15_INHERITANCE["sources"][R14]["source_preregistration_sha256"]
    assert worker.inherited_cell(document, arm_id="arm4", seed=0) is None


def _install_dataset_root(root: Path, tmp_path: Path, manifest: dict, dataset_dir: Path) -> None:
    target = tmp_path / "datasets" / manifest["dataset_digest"]
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(dataset_dir, target)
    data.write_dataset_ref(root, manifest, target)


def test_train_refuses_all_eight_inherited_cells_and_lets_arm4_seed0_through(
    tmp_path, monkeypatch, synthetic_dataset, canonical_root
):
    manifest, dataset_dir, _plan = synthetic_dataset
    root = canonical_root
    _install_dataset_root(root, tmp_path, manifest, dataset_dir)
    document = _frozen(R15, identity=data.dataset_identity(manifest))
    path, digest, _ = write_frozen(root / "pre_registration.json", document=document)
    monkeypatch.setattr(spec, "RESEARCH_LOG", write_research_log(tmp_path / "RESEARCH_LOG.md", approval_sha=digest))
    monkeypatch.setattr(worker, "_train", lambda *a, **k: (_ for _ in ()).throw(AssertionError("trained")))
    ledger = root / "control.sqlite3"
    before = ledger.read_bytes()
    for cell in spec.R15_INHERITANCE["cells"]:
        report = worker.run_worker("train", output_root=root, limits=spec.RESOURCE_LIMITS,
                                   wall_budget_seconds=1_200, prereg_path=path,
                                   arm=cell["arm_id"], seed=cell["seed"])
        assert report["refused_stage"] == "inherited_cell_not_trainable", report
        assert report["inherited"]["source_experiment_id"] == cell["source_experiment_id"]
    assert ledger.read_bytes() == before
    monkeypatch.setattr(worker, "phase_total_wall_seconds", lambda *a, **k: 1e9)
    report = worker.run_worker("train", output_root=root, limits=spec.RESOURCE_LIMITS,
                               wall_budget_seconds=1_200, prereg_path=path, arm="arm4", seed=0)
    assert report["refused_stage"] == "phase_budget_exceeded", report
    assert ledger.read_bytes() == before


# --- eval binds each cell to its own source -----------------------------------
def _source_run(root: Path, monkeypatch, *, experiment_id: str, prereg_sha: str, seed: int) -> tuple[str, str]:
    _patch_data(monkeypatch, root)
    ledger = worker.PrepLedger(root / "control.sqlite3")
    run_id = worker._open_train_run({**_document(3), "experiment_id": experiment_id}, ledger,
                                    {"document_sha256": prereg_sha}, arm_id="arm2", seed=seed)
    ledger.begin_work(run_id, work_state="training")
    details = worker._train(_document(3), root, ledger, run_id, _FakeGuard(), arm_id="arm2", seed=seed,
                            prereg_sha256=prereg_sha, backend=_FakeBackend())
    ledger.finish(run_id, "completed",
                  worker.TRAIN_RECEIPT_PREFIX + json.dumps(details["receipt"], sort_keys=True, separators=(",", ":")))
    ledger.close()
    return run_id, spec.sha256_file(root / "runs" / run_id / "params.npz")


def _two_source_section(run13, sha13, run14, sha14) -> dict:
    section = copy.deepcopy(spec.R15_INHERITANCE)
    section["sources"][R13]["source_preregistration_sha256"] = "a" * 64
    section["sources"][R14]["source_preregistration_sha256"] = "c" * 64
    section["cells"] = [
        {"arm_id": "arm2", "seed": 0, "source_experiment_id": R13, "source_run_id": run13, "params_sha256": sha13},
        {"arm_id": "arm2", "seed": 1, "source_experiment_id": R14, "source_run_id": run14, "params_sha256": sha14},
    ]
    return section


def test_eval_binds_each_cell_to_its_own_source_and_refuses_a_swapped_source(tmp_path, monkeypatch):
    root = tmp_path / "host"
    run13, sha13 = _source_run(root, monkeypatch, experiment_id=R13, prereg_sha="a" * 64, seed=0)
    run14, sha14 = _source_run(root, monkeypatch, experiment_id=R14, prereg_sha="c" * 64, seed=1)
    section = _two_source_section(run13, sha13, run14, sha14)
    monkeypatch.setattr(spec, "INHERITANCE_BY_EXPERIMENT", {R15: section})
    document = {"experiment_id": R15, "inheritance": copy.deepcopy(section)}
    for seed, run_id, source in ((0, run13, R13), (1, run14, R14)):
        binding = worker._bind_for_document(document, root, arm_id="arm2", seed=seed, prereg_sha256="b" * 64,
                                            updates=3, ledger_path=root / "control.sqlite3")
        assert binding["run"].run_id == run_id and binding["inherited"]["source_experiment_id"] == source

    swapped = copy.deepcopy(section)
    swapped["cells"][1]["source_experiment_id"] = R13  # r14 run claimed as r13
    monkeypatch.setattr(spec, "INHERITANCE_BY_EXPERIMENT", {R15: swapped})
    with pytest.raises(worker.EvalBindingError):
        worker._bind_for_document({"experiment_id": R15, "inheritance": copy.deepcopy(swapped)}, root,
                                  arm_id="arm2", seed=1, prereg_sha256="b" * 64, updates=3,
                                  ledger_path=root / "control.sqlite3")
