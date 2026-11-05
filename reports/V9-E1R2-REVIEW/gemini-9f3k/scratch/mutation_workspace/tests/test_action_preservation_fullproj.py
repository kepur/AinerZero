"""M2n-M7 (m2m_n_mixed_history_tailself_fullproj_v1) CPU tests.

Pure CPU: no MLX import, no model, no worker launch, no RunStore write, no training.
The projection is a pure NumPy function exercised on synthetic gradient trees;
worker wiring is checked statically; real mutations edit production code in a
temporary copy of the repository.
"""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
import shutil
import subprocess
import sys
import types

import numpy as np
import pytest

from ainerzero import cli
from ainerzero.learning import action_preservation_closure as apc
from ainerzero.learning import fullproj as fp
from ainerzero.learning import halfproj as hp
from ainerzero.learning.gru_intervention import GRU_SHAPES
from ainerzero.learning.tail_update import _tail_rows
from ainerzero.learning.tailself_freeze import trainable_element_mask
from ainerzero.runtime import memory_worker as mw

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "configs" / "pilot.yaml"
REGISTRATION = ROOT / "artifacts/reports/relay-claude-20261014/M2NM7-fullproj-registration.json"
M6_DRAFT = ROOT / "artifacts/reports/relay-claude-20261014/M2NM6-halfproj-registration-draft.json"
M5_DRAFT = ROOT / "artifacts/reports/relay-claude-20261014/M2NM5-tailself-freeze-registration-draft.json"
COMMAND = "train-action-preserved-mixed-fullproj-memory"
REQUIRED = [
    "--dataset", "d", "--checkpoint", "c", "--comparison-report", "r",
    "--m2l-report", "m", "--m2l-checkpoint", "k", "--m2mc-report", "x",
    "--experiment-id", "e",
]
OLD_DIGESTS = {
    "mixed_condition_plan": "dd02c4fe58059d5c505705e35afa97042bbde2af3923239ca7b7caa6f470a4f2",
    "mixed_weight025_condition_plan": "6e98299668221d0ba970198b1af662ba5c2a1b4c9dd0f29ccb56ce0ed06041d0",
    "mixed_weight0_control_condition_plan": "e7666014e8e2fe0299491f7c8611a20018d306866d9294c6aa2bd18c2cedae6d",
    "mixed_onestep_condition_plan": "f6e71ddcc8d0f686414875c3619b8b34e31e347a8aab8f5c2cc5ce4990b22df0",
    "mixed_tailself_condition_plan": "8ce2752e6d698c3d6e91daf906901855ceac40de2a955470f27f96ab67edb6d5",
    "mixed_halfproj_condition_plan": "f5a1e45febb65ca28f2c3b1772e24173cb04aab87d5d6f7868ec2f759dbad519",
}
OLD_PROTOCOLS = {
    "MIXED_PROTOCOL": "m2m_n_mixed_single_edge_history_v1",
    "WEIGHT025_PROTOCOL": "m2m_n_mixed_history_weight025_v1",
    "WEIGHT0_CONTROL_PROTOCOL": "m2m_n_mixed_history_weight0_control_v1",
    "ONESTEP_PROTOCOL": "m2m_n_mixed_history_onestep_v1",
    "TAILSELF_PROTOCOL": "m2m_n_mixed_history_tailself_frozen_v1",
    "HALFPROJ_PROTOCOL": "m2m_n_mixed_history_tailself_halfproj_v1",
}
LEAVES = ("Wx", "Wh", "b", "bhn")


def _masks():
    return {n: trainable_element_mask(f"model.gru.{n}", GRU_SHAPES[f"model.gru.{n}"]) for n in LEAVES}


def _tree(seed, scale=1.0):
    """Masked-like half tree: trainable elements random, front rows zero, block random."""
    rng = np.random.default_rng(seed)
    out = {}
    for n in LEAVES:
        shape = GRU_SHAPES[f"model.gru.{n}"]
        out[n] = (rng.standard_normal(shape) * scale).astype(np.float32)
    return {"gru": out}


def _flat(tree):
    m = _masks()
    return np.concatenate([np.asarray(tree["gru"][n])[m[n]].astype(np.float64) for n in LEAVES])


def _from_flat(base, flat):
    m, out, off = _masks(), {}, 0
    for n in LEAVES:
        v = np.array(base["gru"][n], copy=True)
        c = int(m[n].sum())
        v[m[n]] = flat[off:off + c].astype(np.float32)
        out[n] = v
        off += c
    return {"gru": out}


def _copy(tree):
    return {"gru": {n: np.array(v, copy=True) for n, v in tree["gru"].items()}}


def _np_tree_map(fn, *trees):
    return {"gru": {n: fn(*(t["gru"][n] for t in trees)) for n in LEAVES}}


def _merge(halves):
    weights, total = apc.mixed_half_weights(12, 4, 1.0)
    return apc.combine_mixed_halves(halves, weights, total, _np_tree_map)


# ---------------------------------------------------------------- 1. identities unchanged

def test_old_protocols_condition_digests_and_entries_are_unchanged():
    for name, digest in OLD_DIGESTS.items():
        assert getattr(apc, name)()["condition_sha256"] == digest
    for name, value in OLD_PROTOCOLS.items():
        assert getattr(apc, name) == value
    assert cli.HALFPROJ_PROTOCOL == OLD_PROTOCOLS["HALFPROJ_PROTOCOL"]
    assert cli.TAILSELF_PROTOCOL == OLD_PROTOCOLS["TAILSELF_PROTOCOL"]
    assert cli.ONESTEP_PROTOCOL == OLD_PROTOCOLS["ONESTEP_PROTOCOL"]
    assert cli.HALFPROJ_IDENTITY_PATH == "artifacts/reports/E29-halfproj/halfproj-identity.json"
    assert "src/ainerzero/learning/fullproj.py" not in cli.HALFPROJ_REQUIRED_FILES
    assert "src/ainerzero/learning/fullproj.py" not in cli.TAILSELF_REQUIRED_FILES
    for cmd in (
        "train-action-preserved-mixed-memory",
        "train-action-preserved-mixed-onestep-memory",
        "train-action-preserved-mixed-weight025-memory",
        "train-action-preserved-mixed-tailself-memory",
        "train-action-preserved-mixed-weight0-control-memory",
        "train-action-preserved-mixed-tailself-halfproj-memory",
        COMMAND,
        "train-action-preserved-mixed-tailself-fullproj-memory",
    ):
        with pytest.raises(SystemExit) as exc:
            cli.main([cmd, "--help"])
        assert exc.value.code == 0


def test_condition_differs_from_m2n_m6_only_by_the_projection_and_units():
    base, new = apc.mixed_halfproj_condition_plan(), apc.mixed_fullproj_condition_plan()
    assert new["protocol"] == apc.FULLPROJ_PROTOCOL == cli.FULLPROJ_PROTOCOL == "m2m_n_mixed_history_tailself_fullproj_v1"
    assert new["halfproj_condition_sha256"] == base["condition_sha256"] == OLD_DIGESTS["mixed_halfproj_condition_plan"]
    assert new["units"]["total"] == 212_704
    assert new["windows"]["units_per_update"] == 204
    assert new["units"]["total"] - base["units"]["total"] == 10_400
    assert new["windows"]["units_per_update"] - base["windows"]["units_per_update"] == 52
    assert new["condition_sha256"] not in OLD_DIGESTS.values()


def test_design_digest_is_bound_to_the_registration_file_bytes():
    assert hashlib.sha256(REGISTRATION.read_bytes()).hexdigest() == apc.FULLPROJ_DESIGN_REGISTRATION_SHA256
    reg = json.loads(REGISTRATION.read_text())
    assert reg["protocol"] == apc.FULLPROJ_PROTOCOL
    assert reg["budget"]["units"] == 212_704
    assert reg["budget"]["seconds"] == 1_740
    assert reg["budget"]["work_deadline"] == 1_760
    assert reg["budget"]["supervisor_deadline"] == 1_780
    assert reg["baseline"]["condition_sha256_prefix"] == OLD_DIGESTS["mixed_halfproj_condition_plan"][:16]


def test_worker_plan_is_m2n_m6_plus_intra_projection_and_budget():
    m6 = mw.action_preservation_mixed_tailself_halfproj_memory_plan()
    new = mw.action_preservation_mixed_tailself_fullproj_memory_plan()
    assert new["protocol"] == apc.FULLPROJ_PROTOCOL
    assert (new["training_model_units_per_update"], new["expected_total_model_units"]) == (204, 212_704)
    assert (m6["training_model_units_per_update"], m6["expected_total_model_units"]) == (152, 202_304)
    assert (new["total_reserved_seconds_if_complete"], new["supervised_deadline_seconds"],
            new["supervisor_deadline_seconds"]) == (1_740, 1_760, 1_780)
    assert (new["trainable_parameter_count"], new["frozen_parameter_count"]) == (61_952, 331_280)
    assert (new["single_edge_rows"], new["history_rows"]) == (12, 4)


# ---------------------------------------------------------------- 2. pure projection

def test_non_conflict_combined_gradient_equals_m6_within_1e6():
    """When neither intra nor inter projection triggers, combined gradient relative error <= 1e-6 vs M6."""
    single = _tree(10)
    g_s = _flat(single)
    # create CE and KL aligned with single so no inter-projection, and aligned with each other so no intra-projection
    ce = _from_flat(_tree(20), 0.4 * g_s + 0.1 * _flat(_tree(21)))
    kl = _from_flat(_tree(30), 0.3 * g_s + 0.1 * _flat(_tree(31)))
    assert float(_flat(ce) @ _flat(kl)) > 0
    h_m6 = fp.add_gradient_trees(ce, kl)
    assert float(_flat(h_m6) @ g_s) > 0

    new_h_m7, tel_m7 = fp.project_full(ce, kl, single)
    assert tel_m7["intra_projected"] is False
    assert tel_m7["projected"] is False
    assert tel_m7["intra_removed_fraction"] == 0.0
    assert tel_m7["removed_fraction"] == 0.0

    new_h_m6, tel_m6 = hp.project_history_half(h_m6, single)
    assert tel_m6["projected"] is False

    g_m7 = _merge({"single_edge": single, "history": new_h_m7})
    g_m6 = _merge({"single_edge": single, "history": new_h_m6})

    diff_norm = np.linalg.norm(_flat(g_m7) - _flat(g_m6))
    ref_norm = np.linalg.norm(_flat(g_m6))
    assert diff_norm / ref_norm <= 1e-6
    for k in (
        "cos_gCEh_gKLh", "intra_projected", "intra_removed_fraction",
        "cos_gh_gs", "projected", "removed_fraction",
        "history_l2", "single_l2", "kl_h_l2", "ce_h_l2",
    ):
        assert k in tel_m7


def test_intra_conflict_projects_ce_off_kl_and_preserves_kl_and_single():
    """When <g_CEh, g_KLh> < 0, projects g_CEh off g_KLh: dot(g_CEh', g_KLh) >= 0; kl and single untouched."""
    kl = _tree(40)
    g_kl = _flat(kl)
    # ce opposite to kl
    ce = _from_flat(_tree(41), -0.8 * g_kl + 0.2 * _flat(_tree(42)))
    assert float(_flat(ce) @ g_kl) < 0
    single = _tree(43)

    kl_bytes = {n: v.tobytes() for n, v in kl["gru"].items()}
    single_bytes = {n: v.tobytes() for n, v in single["gru"].items()}
    ce_bytes = {n: v.tobytes() for n, v in ce["gru"].items()}

    new_ce, intra_tel = fp.project_intra_history(ce, kl)
    assert intra_tel["intra_projected"] is True
    assert intra_tel["inner_product"] < 0
    assert intra_tel["cos_gCEh_gKLh"] < 0

    # inputs kl and single never modified
    assert {n: v.tobytes() for n, v in kl["gru"].items()} == kl_bytes
    assert {n: v.tobytes() for n, v in single["gru"].items()} == single_bytes
    assert {n: v.tobytes() for n, v in ce["gru"].items()} == ce_bytes

    g_new_ce = _flat(new_ce)
    post = float(g_new_ce @ g_kl)
    assert post >= -1e-6 * np.linalg.norm(_flat(ce)) * np.linalg.norm(g_kl)
    reference = (_flat(ce) - (_flat(ce) @ g_kl) / (g_kl @ g_kl) * g_kl).astype(np.float32).astype(np.float64)
    np.testing.assert_array_equal(g_new_ce, reference)
    assert 0 < intra_tel["intra_removed_fraction"] < 1

    # Now full project
    new_h, full_tel = fp.project_full(ce, kl, single)
    assert full_tel["intra_projected"] is True
    assert {n: v.tobytes() for n, v in kl["gru"].items()} == kl_bytes
    assert {n: v.tobytes() for n, v in single["gru"].items()} == single_bytes


def test_both_intra_and_inter_conflict_projects_both():
    """Both projections trigger in sequence; single and kl are never modified."""
    single = _tree(50)
    g_s = _flat(single)
    kl = _from_flat(_tree(51), -0.5 * g_s + 0.1 * _flat(_tree(52)))
    g_kl = _flat(kl)
    ce = _from_flat(_tree(53), -0.6 * g_kl + 0.1 * _flat(_tree(54)))

    assert float(_flat(ce) @ g_kl) < 0
    kl_bytes = {n: v.tobytes() for n, v in kl["gru"].items()}
    single_bytes = {n: v.tobytes() for n, v in single["gru"].items()}

    new_h, tel = fp.project_full(ce, kl, single)
    assert tel["intra_projected"] is True
    assert {n: v.tobytes() for n, v in kl["gru"].items()} == kl_bytes
    assert {n: v.tobytes() for n, v in single["gru"].items()} == single_bytes
    post_inter = float(_flat(new_h) @ g_s)
    assert post_inter >= -1e-6 * np.linalg.norm(_flat(new_h)) * np.linalg.norm(g_s)


def test_small_kl_norm_skips_intra_projection():
    kl = {"gru": {n: np.zeros(GRU_SHAPES[f"model.gru.{n}"], np.float32) for n in LEAVES}}
    kl["gru"]["Wx"][128, 0] = 1e-7  # norm sq < 1e-12
    ce = _tree(60)
    ce["gru"]["Wx"][128, 0] = -1.0
    new_ce, tel = fp.project_intra_history(ce, kl)
    assert new_ce is ce
    assert tel["skipped_small_kl_norm"] is True
    assert tel["intra_projected"] is False


def test_non_finite_and_bad_trees_fail_closed():
    ce, kl = _tree(70), _tree(71)
    ce["gru"]["Wh"][128, 0] = np.nan
    with pytest.raises(ValueError, match="finite"):
        fp.project_intra_history(ce, kl)
    with pytest.raises(ValueError, match="tree"):
        fp.project_intra_history({"gru": {"Wx": ce["gru"]["Wx"]}}, kl)


# ---------------------------------------------------------------- 3. worker wiring (static)

def test_worker_calls_fullproj_correctly():
    src = (ROOT / "src/ainerzero/runtime/memory_worker.py").read_text()
    assert "action_preservation_mixed_tailself_fullproj" in src
    assert "from ainerzero.learning.fullproj import project_full" in src
    assert "project_full(" in src
    assert 'mixed_details["full_projection"] = projection' in src
    assert "fullproj_source_schedule_compat" in src
    assert '"--action-preservation-mixed-tailself-fullproj"' in src
    fullproj_src = (ROOT / "src/ainerzero/learning/fullproj.py").read_text()
    assert "import mlx" not in fullproj_src


# ---------------------------------------------------------------- 4. CLI entry / identity gate

def test_subcommand_sets_only_the_new_flag_and_has_no_scientific_knobs(monkeypatch):
    seen = {}
    monkeypatch.setattr(cli, "train_pilot_command", lambda args: seen.update(vars(args)) or {"status": "completed"})
    assert cli.main([COMMAND, *REQUIRED]) == 0
    assert seen["action_preserved_mixed_fullproj_training"] is True
    for other in (
        "action_preserved_mixed_training",
        "action_preserved_mixed_onestep_training",
        "action_preserved_mixed_tailself_training",
        "action_preserved_mixed_halfproj_training",
        "action_preserved_mixed_weight025_training",
        "action_preserved_mixed_weight0_control_training",
    ):
        assert seen.get(other, False) is False
    for flag in ("--learning-rate", "--history-weight", "--projection-threshold", "--updates"):
        with pytest.raises(SystemExit):
            cli.main([COMMAND, *REQUIRED, flag, "1"])


def _args(tmp_path, **flags):
    base = dict(
        config=CONFIG, output_dir=tmp_path, experiment_id="e", dataset=tmp_path / "d",
        checkpoint=tmp_path / "c", comparison_report=tmp_path / "r", m2l_report=tmp_path / "m",
        m2l_checkpoint=tmp_path / "k", m2mc_report=tmp_path / "x",
        action_preserved_mixed_fullproj_training=True,
    )
    base.update(flags)
    return types.SimpleNamespace(**base)


def test_missing_identity_file_fails_closed_with_zero_worker_launches(monkeypatch, tmp_path):
    launched = []
    monkeypatch.setattr(cli, "project_root", lambda _path: tmp_path)
    monkeypatch.setattr(cli.subprocess, "run", lambda *a, **k: launched.append(a))
    monkeypatch.setattr(cli.subprocess, "Popen", lambda *a, **k: launched.append(a))
    report = cli.train_pilot_command(_args(tmp_path))
    assert report["status"] == "failed" and report["fail_closed"] is True
    assert "fullproj-identity.json" in report["error"] or "No such file" in report["error"]
    assert launched == []


def test_dispatch_uses_the_new_flag_and_the_registered_timeout(monkeypatch, tmp_path):
    captured = {}

    class Done:
        returncode, stdout, stderr = 1, "", ""

    monkeypatch.setattr(cli, "verify_fullproj_identity", lambda *a, **k: None)
    monkeypatch.setattr(cli, "verify_halfproj_identity",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("halfproj gate used")))
    monkeypatch.setattr(cli, "project_root", lambda _path: tmp_path)
    monkeypatch.setattr(cli.subprocess, "run",
                        lambda cmd, **kw: captured.update(cmd=cmd, timeout=kw["timeout"]) or Done())
    cli.train_pilot_command(_args(tmp_path))
    assert "--action-preservation-mixed-tailself-fullproj" in captured["cmd"]
    for old in ("--action-preservation-mixed", "--action-preservation-mixed-tailself",
                "--action-preservation-mixed-tailself-halfproj"):
        assert old not in captured["cmd"]
    assert captured["timeout"] == min(1780, cli.load_pilot_config(CONFIG).budget.max_wall_seconds)


def test_entry_is_exclusive_with_other_action_commands(monkeypatch, tmp_path):
    monkeypatch.setattr(cli.subprocess, "run", lambda *a, **k: (_ for _ in ()).throw(AssertionError("launched")))
    for conflict in (
        "action_preserved_mixed_training",
        "action_preserved_mixed_onestep_training",
        "action_preserved_mixed_tailself_training",
        "action_preserved_mixed_halfproj_training",
        "action_preserved_mixed_weight025_training",
        "action_preserved_mixed_weight0_control_training",
    ):
        report = cli.train_pilot_command(_args(tmp_path, **{conflict: True}))
        assert report["status"] == "failed" and report["fail_closed"] is True


def _live_record():
    plan = apc.mixed_fullproj_condition_plan()
    return {
        "protocol": apc.FULLPROJ_PROTOCOL,
        "condition_sha256": plan["condition_sha256"],
        "design_registration_sha256": plan["design_registration_sha256"],
        "config_hash": cli.pilot_config_hash(cli.load_pilot_config(CONFIG)),
        "files": {rel: hashlib.sha256((ROOT / rel).read_bytes()).hexdigest()
                  for rel in sorted(cli.FULLPROJ_REQUIRED_FILES)},
    }


def test_identity_gate_accepts_live_record_in_memory_and_rejects_drift():
    record = _live_record()
    cli.verify_fullproj_identity(ROOT, record, config_path=CONFIG)
    for rel in sorted(cli.FULLPROJ_REQUIRED_FILES):
        bad = json.loads(json.dumps(record))
        bad["files"][rel] = "ab" * 32
        with pytest.raises(RuntimeError, match="identity mismatch"):
            cli.verify_fullproj_identity(ROOT, bad, config_path=CONFIG)
    dropped = json.loads(json.dumps(record))
    dropped["files"].pop("src/ainerzero/learning/fullproj.py")
    with pytest.raises(RuntimeError, match="required set"):
        cli.verify_fullproj_identity(ROOT, dropped, config_path=CONFIG)
    with pytest.raises(RuntimeError, match="protocol"):
        cli.verify_fullproj_identity(ROOT, dict(record, protocol=apc.HALFPROJ_PROTOCOL), config_path=CONFIG)
    with pytest.raises(RuntimeError, match="condition_sha256"):
        cli.verify_fullproj_identity(ROOT, dict(record, condition_sha256=OLD_DIGESTS["mixed_halfproj_condition_plan"]),
                                     config_path=CONFIG)


# ---------------------------------------------------------------- 4b. rejection fixes (A57 r2)

def _fullproj_history_branch() -> str:
    """The fullproj history-half branch of the worker, from its flag to `continue`."""
    src = (ROOT / "src/ainerzero/runtime/memory_worker.py").read_text()
    start = src.index('if action_preservation_mixed_tailself_fullproj and name == "history":')
    return src[start:src.index("continue", start)]


def _np_mask_tree(tree):
    """NumPy equivalent of tail_update.mask_gru_tail_gradients (that one needs MLX)."""
    out = {}
    for name, value in tree["gru"].items():
        rows = _tail_rows(f"model.gru.{name}", np.shape(value)).reshape((-1,) + (1,) * (np.ndim(value) - 1))
        out[name] = np.where(rows, np.asarray(value), np.zeros_like(np.asarray(value)))
    return {"gru": out}


def _front_l2(unmasked, masked):
    return float(np.sqrt(sum(
        np.sum((np.asarray(a) - np.asarray(b)) ** 2, dtype=np.float64)
        for a, b in zip(unmasked["gru"].values(), masked["gru"].values())
    )))


def test_fullproj_front_row_l2_uses_m6_formula_and_is_nonzero():
    """Rejection fix: the fullproj history half records its front-row gradient with
    the M2n-M6 formula — ||unmasked (g_CEh+g_KLh) − masked applied sum|| — not 0.0."""
    rng = np.random.default_rng(20261014)
    ce = {"gru": {n: rng.standard_normal(GRU_SHAPES[f"model.gru.{n}"]).astype(np.float32) for n in LEAVES}}
    kl = {"gru": {n: rng.standard_normal(GRU_SHAPES[f"model.gru.{n}"]).astype(np.float32) for n in LEAVES}}
    # M6 formula on one combined gradient: ||g − mask(g)||
    g_sum = fp.add_gradient_trees(ce, kl)
    front_m6 = _front_l2(g_sum, _np_mask_tree(g_sum))
    # M7 worker formula: ||(g_CEh+g_KLh) − (mask(g_CEh)+mask(g_KLh))||
    front_m7 = _front_l2(g_sum, fp.add_gradient_trees(_np_mask_tree(ce), _np_mask_tree(kl)))
    assert front_m6 > 1e-3, "random gradients must have non-zero front rows"
    assert math.isclose(front_m6, front_m7, rel_tol=1e-6, abs_tol=1e-9)
    branch = _fullproj_history_branch()
    assert '"front_row_gradient_l2": 0.0' not in branch
    assert '"front_row_gradient_l2": half_front' in branch
    assert "tree_flatten(unmasked_sum)" in branch
    assert "np.asarray(a) - np.asarray(b)" in branch
    assert "front-output gradient is not finite" in branch


def test_fullproj_history_half_requires_parts_one_fail_closed():
    """Rejection fix: per-part CE/KL gradients are overwritten, not accumulated —
    the worker must fail closed unless the registered parts==1."""
    branch = _fullproj_history_branch()
    assert "if parts != 1:" in branch
    assert "requires parts==1 (fail-closed)" in branch
    assert "raise RuntimeError" in branch


def test_identity_file_is_not_frozen_by_the_implementation():
    """Rejection fix: the identity file belongs to the tier-1 freeze; the
    implementation must not write `registered_by` or claim a frozen status."""
    identity = ROOT / cli.FULLPROJ_IDENTITY_PATH
    if identity.exists():
        record = json.loads(identity.read_text())
        assert "registered_by" not in record, "实现者不得代一级写 registered_by"
        assert record.get("status") != "identity_frozen_run_not_authorized"


# ---------------------------------------------------------------- 5. real mutations (at least 4)

MUTATIONS = {
    "skip_intra_history_projection": (
        "src/ainerzero/learning/fullproj.py",
        "    new_ce_h, intra_tel = project_intra_history(ce_history, kl_history)\n",
        "    new_ce_h, intra_tel = ce_history, {'cos_gCEh_gKLh': 0.0, 'intra_projected': False, 'intra_removed_fraction': 0.0, 'ce_h_l2': 1.0, 'kl_h_l2': 1.0, 'inner_product': 0.0, 'post_inner_product': 0.0, 'elements': 61952, 'skipped_small_kl_norm': False}\n",
    ),
    "project_kl_off_ce_reversed": (
        "src/ainerzero/learning/fullproj.py",
        "    projected = g_ce - (c / kl_sq) * g_kl\n",
        "    projected = g_kl - (c / ce_sq) * g_ce\n",
    ),
    "modify_g_s": (
        "src/ainerzero/learning/fullproj.py",
        "    new_g_h, inter_tel = project_history_half(g_h_tree, single)\n",
        "    new_g_h, inter_tel = project_history_half(g_h_tree, single)\n    single['gru']['Wx'][128, 0] = 999.0\n",
    ),
    "teacher_logits_recomputed_units_223104": (
        "src/ainerzero/runtime/memory_worker.py",
        "    if condition[\"units\"][\"total\"] != 212_704 or condition[\"full_projection\"][\"extra_model_calls\"] != 52:\n",
        "    if False:\n",
    ),
    # Rejection fix (A57 r2): hard-coding the history half's front-row telemetry
    # back to 0.0 must be caught.
    "fullproj_front_row_hardcoded_zero": (
        "src/ainerzero/runtime/memory_worker.py",
        "                            \"ce\": float(ce_loss.item()),\n"
        "                            \"kl\": float(np.mean(h_kls)),\n"
        "                            \"front_row_gradient_l2\": half_front,\n",
        "                            \"ce\": float(ce_loss.item()),\n"
        "                            \"kl\": float(np.mean(h_kls)),\n"
        "                            \"front_row_gradient_l2\": 0.0,\n",
    ),
    # Rejection fix (A57 r2): dropping the parts==1 fail-closed guard must be caught.
    "fullproj_parts_guard_removed": (
        "src/ainerzero/runtime/memory_worker.py",
        "                        if parts != 1:\n",
        "                        if False:\n",
    ),
}


def _copy_and_run(tmp_path, mutation=None):
    repo = tmp_path / "repo"
    for d in ("src", "tests", "configs"):
        shutil.copytree(ROOT / d, repo / d, ignore=shutil.ignore_patterns("__pycache__"))
    shutil.copy2(ROOT / "pyproject.toml", repo / "pyproject.toml")
    for doc in (REGISTRATION, M6_DRAFT, M5_DRAFT):
        target = repo / doc.relative_to(ROOT)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(doc, target)
    if mutation:
        rel, old, new = MUTATIONS[mutation]
        text = (repo / rel).read_text()
        assert text.count(old) == 1, f"mutation {mutation}: old text not found uniquely"
        (repo / rel).write_text(text.replace(old, new))
        if mutation == "teacher_logits_recomputed_units_223104":
            # also modify action_preservation_closure units to 223104 to simulate recomputing teacher logits
            cl_path = repo / "src/ainerzero/learning/action_preservation_closure.py"
            cl_text = cl_path.read_text()
            cl_text = cl_text.replace('"total": 171_904 + student_single + student_history + student_history_recompute + teacher,',
                                      '"total": 223_104,')
            cl_path.write_text(cl_text)
    return subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "-k", "not mutation and not unmutated",
         "tests/test_action_preservation_fullproj.py"],
        cwd=repo, env={"PYTHONPATH": str(repo / "src"), "PATH": "/usr/bin:/bin", "PYTHONDONTWRITEBYTECODE": "1"},
        capture_output=True, text=True, timeout=300)


@pytest.mark.parametrize("name", sorted(MUTATIONS))
def test_real_mutation_of_production_code_is_caught(name, tmp_path):
    proc = _copy_and_run(tmp_path, name)
    assert proc.returncode != 0, f"Mutation {name} was not caught! Output: {proc.stdout}\n{proc.stderr}"
    assert "failed" in proc.stdout


def test_unmutated_copy_passes_the_same_tests(tmp_path):
    proc = _copy_and_run(tmp_path)
    assert proc.returncode == 0, f"Unmutated copy failed! Output: {proc.stdout}\n{proc.stderr}"
