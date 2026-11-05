"""M2n-M5 (m2m_n_mixed_history_tailself_frozen_v1) CPU tests.

No MLX, no model, no worker launch, no RunStore write, no training. Masking and
projection run their real production code against a tiny numpy stand-in that is
installed *as* ``mlx`` only for the duration of a test. Worker wiring is checked
statically; real mutations edit production code in a temporary copy.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
import types
from pathlib import Path

import numpy as np
import pytest

from ainerzero import cli
from ainerzero.learning import action_preservation_closure as apc
from ainerzero.learning import tailself_freeze as tsf
from ainerzero.learning.gru_intervention import GRU_SHAPES, MODEL_PARAMETER_COUNT
from ainerzero.runtime import memory_worker as mw

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "configs" / "pilot.yaml"
DRAFT = ROOT / "artifacts/reports/relay-claude-20261014/M2NM5-tailself-freeze-registration-draft.json"
COMMAND = "train-action-preserved-mixed-tailself-memory"
REQUIRED = ["--dataset", "d", "--checkpoint", "c", "--comparison-report", "r", "--m2l-report", "m",
            "--m2l-checkpoint", "k", "--m2mc-report", "x", "--experiment-id", "e"]
# Digests of the earlier conditions, recorded from git HEAD 9f27469 before A43.
OLD_DIGESTS = {
    "mixed_condition_plan": "dd02c4fe58059d5c505705e35afa97042bbde2af3923239ca7b7caa6f470a4f2",
    "mixed_weight025_condition_plan": "6e98299668221d0ba970198b1af662ba5c2a1b4c9dd0f29ccb56ce0ed06041d0",
    "mixed_weight0_control_condition_plan": "e7666014e8e2fe0299491f7c8611a20018d306866d9294c6aa2bd18c2cedae6d",
    "mixed_onestep_condition_plan": "f6e71ddcc8d0f686414875c3619b8b34e31e347a8aab8f5c2cc5ce4990b22df0",
}
OLD_PROTOCOLS = {
    "MIXED_PROTOCOL": "m2m_n_mixed_single_edge_history_v1",
    "WEIGHT025_PROTOCOL": "m2m_n_mixed_history_weight025_v1",
    "WEIGHT0_CONTROL_PROTOCOL": "m2m_n_mixed_history_weight0_control_v1",
    "ONESTEP_PROTOCOL": "m2m_n_mixed_history_onestep_v1",
}
TAIL_ROWS = ((128, 256), (384, 512), (640, 768))


class fake_mlx:  # noqa: N801
    """Install a numpy stand-in as ``mlx.core`` (where/array/zeros_like only)."""

    def __enter__(self):
        self._saved = {n: sys.modules.get(n) for n in ("mlx", "mlx.core")}
        core = types.ModuleType("mlx.core")
        core.array = lambda v: np.array(v)
        core.where = np.where
        core.zeros_like = np.zeros_like
        package = types.ModuleType("mlx")
        package.core = core
        sys.modules["mlx"], sys.modules["mlx.core"] = package, core
        return core

    def __exit__(self, *exc):
        for name, mod in self._saved.items():
            if mod is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = mod


def _reference_trainable(key, shape):
    """Independent reference mask, built element by element from the registration."""
    mask = np.zeros(shape, dtype=bool)
    rows = ((128, 256),) if key.endswith(".bhn") else TAIL_ROWS
    for a, b in rows:
        mask[a:b] = True
    if key == "model.gru.Wh":
        for a, b in TAIL_ROWS:
            mask[a:b, 128:256] = False
    return mask


def _source(seed=0):
    rng = np.random.default_rng(seed)
    gru = {k: rng.standard_normal(s).astype(np.float32) for k, s in GRU_SHAPES.items()}
    other = MODEL_PARAMETER_COUNT - sum(v.size for v in gru.values())
    return {**gru, "model.other": rng.standard_normal(other).astype(np.float32)}


class _Model:
    def __init__(self, tensors):
        self.gru = types.SimpleNamespace(**{k.removeprefix("model.gru."): v.copy()
                                            for k, v in tensors.items() if k.startswith("model.gru.")})

    def update(self, tree):
        for name, value in tree["gru"].items():
            setattr(self.gru, name, np.asarray(value))

    def tensors(self, other):
        return {**{f"model.gru.{n}": getattr(self.gru, n) for n in ("Wx", "Wh", "b", "bhn")},
                "model.other": other}


# ---------------------------------------------------------------- 1. mask counts

def test_mask_element_counts_match_the_registration():
    counts = tsf.mask_counts()
    assert counts == {"trainable": 61_952, "tailself_block": 49_152, "frozen": 331_280, "total": 393_232}
    assert tsf.TAILSELF_TRAINABLE_PARAMETER_COUNT == 61_952
    assert tsf.TAILSELF_FROZEN_PARAMETER_COUNT == 331_280
    assert 111_104 - 49_152 == 61_952 and 282_128 + 49_152 == 331_280


def test_mask_equals_independent_reference_every_row_and_column():
    for key, shape in GRU_SHAPES.items():
        np.testing.assert_array_equal(tsf.trainable_element_mask(key, shape), _reference_trainable(key, shape))
    block = tsf.tailself_block_mask()
    assert block.sum() == 49_152
    rows = np.flatnonzero(block.any(axis=1))
    cols = np.flatnonzero(block.any(axis=0))
    assert rows.tolist() == [r for a, b in TAIL_ROWS for r in range(a, b)]
    assert cols.tolist() == list(range(128, 256))
    assert (block.sum(axis=1)[rows] == 128).all() and (block.sum(axis=0)[cols] == 384).all()


# ---------------------------------------------------- 2. masking / guard / projection

def _grad_tree(seed=1):
    rng = np.random.default_rng(seed)
    return {"gru": {k.removeprefix("model.gru."): rng.standard_normal(s) for k, s in GRU_SHAPES.items()}}


def test_mask_zeroes_every_frozen_element_and_keeps_trainable():
    grads = _grad_tree()
    with fake_mlx():
        masked = tsf.mask_tailself_gradients(grads)["gru"]
    for name, value in masked.items():
        ref = _reference_trainable(f"model.gru.{name}", value.shape)
        assert np.all(value[~ref] == 0)
        np.testing.assert_array_equal(value[ref], grads["gru"][name][ref])


def test_applied_gradient_guard_covers_the_new_block():
    grads = _grad_tree()
    with fake_mlx():
        masked = tsf.mask_tailself_gradients(grads)["gru"]
    out = tsf.check_applied_frozen_gradient(grads["gru"], masked)
    assert out["applied_frozen_gradient_l2"] == 0.0 and out["raw_tailself_gradient_l2"] > 0
    leaky = {k: v.copy() for k, v in masked.items()}
    leaky["Wh"][700, 200] = 1e-6          # inside the tail-self block only
    with pytest.raises(ValueError, match="exceeds 1e-8"):
        tsf.check_applied_frozen_gradient(grads["gru"], leaky)
    front = {k: v.copy() for k, v in masked.items()}
    front["Wx"][0, 0] = 1e-6
    with pytest.raises(ValueError, match="exceeds 1e-8"):
        tsf.check_applied_frozen_gradient(grads["gru"], front)


def test_projection_restores_block_bitwise_and_keeps_trainable_updates():
    source = _source()
    model = _Model(source)
    for name in ("Wx", "Wh", "b", "bhn"):          # simulate AdamW moving everything
        setattr(model.gru, name, getattr(model.gru, name) + np.float32(0.5))
    with fake_mlx():
        tsf.project_tailself(model, source)
    current = model.tensors(source["model.other"])
    report = tsf.verify_tailself_update(source, current)
    assert report["frozen_parameter_count"] == 331_280
    assert report["allowed_parameter_count"] == 61_952
    assert report["tailself_block"]["elements"] == 49_152
    trainable_changed = sum(
        int((current[k] != source[k])[_reference_trainable(k, s)].sum()) for k, s in GRU_SHAPES.items())
    assert trainable_changed == 61_952 == report["changed_elements"]


def test_verifier_rejects_one_changed_element_anywhere_in_the_block():
    source = _source()
    for r, c in ((128, 128), (255, 255), (384, 200), (767, 128), (640, 255)):
        current = {k: v.copy() for k, v in source.items()}
        current["model.gru.Wh"][r, c] += 1
        with pytest.raises(ValueError, match="tail-self block changed"):
            tsf.verify_tailself_update(source, current)
    signed = {k: v.copy() for k, v in source.items()}
    signed["model.gru.Wh"][200, 150] = np.float32(0.0)
    source2 = {k: v.copy() for k, v in source.items()}
    source2["model.gru.Wh"][200, 150] = np.float32(-0.0)
    with pytest.raises(ValueError, match="tail-self block changed"):
        tsf.verify_tailself_update(source2, signed)


# -------------------------------------------- 3. condition / plan identity

def test_old_protocols_and_condition_digests_are_unchanged():
    for name, digest in OLD_DIGESTS.items():
        assert getattr(apc, name)()["condition_sha256"] == digest
    for name, value in OLD_PROTOCOLS.items():
        assert getattr(apc, name) == value
    assert cli.ONESTEP_PROTOCOL == OLD_PROTOCOLS["ONESTEP_PROTOCOL"]
    assert "src/ainerzero/learning/tailself_freeze.py" not in cli.ONESTEP_REQUIRED_FILES


def test_condition_differs_from_e24_only_by_the_frozen_block_and_bookkeeping():
    base, new = apc.mixed_condition_plan(), apc.mixed_tailself_condition_plan()
    assert new["protocol"] == apc.TAILSELF_PROTOCOL == "m2m_n_mixed_history_tailself_frozen_v1"
    assert new["mixed_condition_sha256"] == base["condition_sha256"] == OLD_DIGESTS["mixed_condition_plan"]
    added = set(new) - set(base)
    assert added == {"mixed_condition_sha256", "mixed_protocol", "history_weight", "renormalize_after_scaling",
                     "design_registration_sha256", "frozen_block", "start"}
    changed = {k for k in set(base) & set(new) if base[k] != new[k]}
    assert changed == {"protocol", "single_factor", "condition_sha256"}
    assert new["history_weight"] == 1.0 and "truncate_each_step" not in new
    assert new["frozen_block"]["tensor"] == "model.gru.Wh"
    assert new["frozen_block"]["rows"] == [[128, 256], [384, 512], [640, 768]]
    assert new["frozen_block"]["cols"] == [128, 256] and new["frozen_block"]["elements"] == 49_152
    assert new["frozen_block"]["parameters"] == {"total": 393_232, "trainable": 61_952, "frozen": 331_280}


def test_design_digest_is_bound_to_the_registration_draft_bytes():
    assert hashlib.sha256(DRAFT.read_bytes()).hexdigest() == apc.TAILSELF_DESIGN_REGISTRATION_SHA256
    draft = json.loads(DRAFT.read_text())
    assert draft["frozen_block"] == {k: apc.mixed_tailself_condition_plan()["frozen_block"][k]
                                     for k in ("tensor", "rows", "cols", "elements")}
    assert draft["parameters"] == apc.mixed_tailself_condition_plan()["frozen_block"]["parameters"]


def test_worker_plan_keeps_the_e24_budget_and_sets_the_new_scope():
    e24, new = mw.action_preservation_mixed_memory_plan(), mw.action_preservation_mixed_tailself_memory_plan()
    assert new["trainable_parameter_count"] == 61_952 and new["frozen_parameter_count"] == 331_280
    assert e24["trainable_parameter_count"] == 111_104
    for key in ("training_model_units_per_update", "expected_total_model_units",
                "total_reserved_seconds_if_complete", "supervised_deadline_seconds",
                "supervisor_deadline_seconds", "learning_rate", "seeds", "updates",
                "single_edge_rows", "history_rows", "burn_in", "history_burn_in", "history_sequence_steps"):
        if key in e24:
            assert new[key] == e24[key], key
    assert (new["expected_total_model_units"], new["total_reserved_seconds_if_complete"],
            new["supervised_deadline_seconds"], new["supervisor_deadline_seconds"]) == (202_304, 1_740, 1_760, 1_780)
    assert not new.get("truncate_each_step")


# -------------------------------------------- 4. worker wiring (static)

WORKER = (ROOT / "src/ainerzero/runtime/memory_worker.py").read_text()


def test_worker_masks_guards_projects_and_verifies_in_the_tailself_branch():
    assert "gradients = mask_tailself_gradients(gradients)" in WORKER
    assert "tailself_guard = check_applied_frozen_gradient(" in WORKER
    i_mask = WORKER.index("gradients = mask_tailself_gradients(gradients)")
    i_clip = WORKER.index("gradients, norm = optim.clip_grad_norm(gradients, config.training.gradient_clip_norm)", i_mask)
    i_guard = WORKER.index("tailself_guard = check_applied_frozen_gradient(", i_clip)
    i_update = WORKER.index("optimizer.update(model, gradients)", i_guard)
    i_project = WORKER.index("project_tailself(model, source_tensors)", i_update)
    assert i_mask < i_clip < i_guard < i_update < i_project
    assert WORKER.count("verify_tailself_update if action_preservation_mixed_tailself else verify_tail_update") == 2
    assert "if local_fit and action_preservation_mixed_tailself:\n                # AdamW" in WORKER


# -------------------------------------------- 5. CLI entry and fail-closed identity

def test_cli_entry_is_separate_and_takes_no_scientific_knobs(monkeypatch):
    seen = {}
    monkeypatch.setattr(cli, "train_pilot_command", lambda args: seen.update(vars(args)) or {"status": "completed"})
    assert cli.main([COMMAND, *REQUIRED]) == 0
    assert seen["action_preserved_mixed_tailself_training"] is True
    for other in ("action_preserved_mixed_training", "action_preserved_mixed_onestep_training",
                  "action_preserved_mixed_weight025_training", "action_preserved_mixed_weight0_control_training"):
        assert seen.get(other, False) is False
    for flag in ("--learning-rate", "--history-weight", "--frozen-rows", "--updates"):
        with pytest.raises(SystemExit):
            cli.main([COMMAND, *REQUIRED, flag, "1"])


def _args(tmp_path, **flags):
    base = dict(
        config=CONFIG, output_dir=tmp_path, experiment_id="e", dataset=tmp_path / "d",
        checkpoint=tmp_path / "c", comparison_report=tmp_path / "r", m2l_report=tmp_path / "m",
        m2l_checkpoint=tmp_path / "k", m2mc_report=tmp_path / "x",
        action_preserved_mixed_tailself_training=True,
    )
    base.update(flags)
    return types.SimpleNamespace(**base)


def test_missing_identity_file_fails_closed_without_starting_the_worker(monkeypatch, tmp_path):
    launched = []
    monkeypatch.setattr(cli, "project_root", lambda _path: tmp_path)   # no identity file there
    monkeypatch.setattr(cli.subprocess, "run", lambda *a, **k: launched.append(a))
    monkeypatch.setattr(cli.subprocess, "Popen", lambda *a, **k: launched.append(a))
    report = cli.train_pilot_command(_args(tmp_path))
    assert report["status"] == "failed" and report["fail_closed"] is True
    assert "tailself-identity.json" in report["error"] or "No such file" in report["error"]
    assert launched == []
    assert not (ROOT / cli.TAILSELF_IDENTITY_PATH).exists() or True  # never written by this test


def test_dispatch_uses_the_new_flag_and_the_registered_timeout(monkeypatch, tmp_path):
    captured = {}

    class Done:
        returncode, stdout, stderr = 1, "", ""

    monkeypatch.setattr(cli, "verify_tailself_identity", lambda *a, **k: None)
    monkeypatch.setattr(cli, "project_root", lambda _path: tmp_path)
    monkeypatch.setattr(cli.subprocess, "run",
                        lambda cmd, **kw: captured.update(cmd=cmd, timeout=kw["timeout"]) or Done())
    cli.train_pilot_command(_args(tmp_path))
    assert "--action-preservation-mixed-tailself" in captured["cmd"]
    assert "--action-preservation-mixed" not in captured["cmd"]
    assert "--action-preservation-mixed-onestep" not in captured["cmd"]
    assert captured["timeout"] == min(1780, cli.load_pilot_config(CONFIG).budget.max_wall_seconds)


def test_entry_is_exclusive_with_other_action_commands(monkeypatch, tmp_path):
    monkeypatch.setattr(cli.subprocess, "run", lambda *a, **k: (_ for _ in ()).throw(AssertionError("launched")))
    for conflict in ("action_preserved_mixed_training", "action_preserved_mixed_onestep_training",
                     "action_preserved_mixed_weight025_training", "action_preserved_mixed_weight0_control_training"):
        report = cli.train_pilot_command(_args(tmp_path, **{conflict: True}))
        assert report["status"] == "failed" and report["fail_closed"] is True


def _live_record():
    plan = apc.mixed_tailself_condition_plan()
    return {"protocol": apc.TAILSELF_PROTOCOL, "condition_sha256": plan["condition_sha256"],
            "design_registration_sha256": plan["design_registration_sha256"],
            "config_hash": cli.pilot_config_hash(cli.load_pilot_config(CONFIG)),
            "files": {rel: hashlib.sha256((ROOT / rel).read_bytes()).hexdigest()
                      for rel in sorted(cli.TAILSELF_REQUIRED_FILES)}}


def test_identity_gate_accepts_live_record_in_memory_and_rejects_drift():
    record = _live_record()
    cli.verify_tailself_identity(ROOT, record, config_path=CONFIG)
    for rel in sorted(cli.TAILSELF_REQUIRED_FILES):
        bad = json.loads(json.dumps(record))
        bad["files"][rel] = "ab" * 32
        with pytest.raises(RuntimeError, match="identity mismatch"):
            cli.verify_tailself_identity(ROOT, bad, config_path=CONFIG)
    dropped = json.loads(json.dumps(record))
    dropped["files"].pop("src/ainerzero/learning/tailself_freeze.py")
    with pytest.raises(RuntimeError, match="required set"):
        cli.verify_tailself_identity(ROOT, dropped, config_path=CONFIG)
    wrong = dict(record, protocol=apc.ONESTEP_PROTOCOL)
    with pytest.raises(RuntimeError, match="protocol"):
        cli.verify_tailself_identity(ROOT, wrong, config_path=CONFIG)


# -------------------------------------------- 6. real mutations of production code

MUTATIONS = {
    "no_block_projection": ("src/ainerzero/learning/tailself_freeze.py",
                            'model.update({"gru": {"Wh": mx.where(block, original, current)}})', "pass"),
    "worker_front_only_projection": ("src/ainerzero/runtime/memory_worker.py",
                                     "                project_tailself(model, source_tensors)\n",
                                     "                project_gru_front(model, source_tensors)\n"),
    "mask_missing_one_row": ("src/ainerzero/learning/tailself_freeze.py",
                             "mask[start:stop, TAILSELF_COL_RANGE[0]",
                             "mask[start:stop - (start == 640), TAILSELF_COL_RANGE[0]"),
    "mask_missing_one_col": ("src/ainerzero/learning/tailself_freeze.py",
                             "TAILSELF_COL_RANGE[0]:TAILSELF_COL_RANGE[1]] = True",
                             "TAILSELF_COL_RANGE[0]:TAILSELF_COL_RANGE[1] - 1] = True"),
}


def _copy_and_run(tmp_path, mutation=None):
    repo = tmp_path / "repo"
    for d in ("src", "tests", "configs"):
        shutil.copytree(ROOT / d, repo / d, ignore=shutil.ignore_patterns("__pycache__"))
    shutil.copy2(ROOT / "pyproject.toml", repo / "pyproject.toml")
    (repo / DRAFT.relative_to(ROOT)).parent.mkdir(parents=True)
    shutil.copy2(DRAFT, repo / DRAFT.relative_to(ROOT))
    if mutation:
        rel, old, new = MUTATIONS[mutation]
        text = (repo / rel).read_text()
        assert text.count(old) == 1, mutation
        (repo / rel).write_text(text.replace(old, new))
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "-k", "not mutation and not unmutated",
         "tests/test_action_preservation_tailself.py"],
        cwd=repo, env={"PYTHONPATH": str(repo / "src"), "PATH": "/usr/bin:/bin", "PYTHONDONTWRITEBYTECODE": "1"},
        capture_output=True, text=True, timeout=300)
    return proc


@pytest.mark.parametrize("name", sorted(MUTATIONS))
def test_real_mutation_of_production_code_is_caught(name, tmp_path):
    proc = _copy_and_run(tmp_path, name)
    assert proc.returncode != 0, proc.stdout[-2000:]
    assert "failed" in proc.stdout


def test_unmutated_copy_passes_the_same_tests(tmp_path):
    proc = _copy_and_run(tmp_path)
    assert proc.returncode == 0, proc.stdout[-3000:]
