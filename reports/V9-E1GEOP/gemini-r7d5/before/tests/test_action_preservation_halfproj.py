"""M2n-M6 (m2m_n_mixed_history_tailself_halfproj_v1) CPU tests.

Pure CPU: no MLX import, no model, no worker launch, no RunStore write, no training.
The projection is a pure NumPy function exercised on synthetic gradient trees;
worker wiring is checked statically; real mutations edit production code in a
temporary copy of the repository.
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
from ainerzero.learning import halfproj as hp
from ainerzero.learning.gru_intervention import GRU_SHAPES
from ainerzero.learning.tailself_freeze import trainable_element_mask
from ainerzero.runtime import memory_worker as mw

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "configs" / "pilot.yaml"
DRAFT = ROOT / "artifacts/reports/relay-claude-20261014/M2NM6-halfproj-registration-draft.json"
M5_DRAFT = ROOT / "artifacts/reports/relay-claude-20261014/M2NM5-tailself-freeze-registration-draft.json"
COMMAND = "train-action-preserved-mixed-tailself-halfproj-memory"
REQUIRED = ["--dataset", "d", "--checkpoint", "c", "--comparison-report", "r", "--m2l-report", "m",
            "--m2l-checkpoint", "k", "--m2mc-report", "x", "--experiment-id", "e"]
OLD_DIGESTS = {
    "mixed_condition_plan": "dd02c4fe58059d5c505705e35afa97042bbde2af3923239ca7b7caa6f470a4f2",
    "mixed_weight025_condition_plan": "6e98299668221d0ba970198b1af662ba5c2a1b4c9dd0f29ccb56ce0ed06041d0",
    "mixed_weight0_control_condition_plan": "e7666014e8e2fe0299491f7c8611a20018d306866d9294c6aa2bd18c2cedae6d",
    "mixed_onestep_condition_plan": "f6e71ddcc8d0f686414875c3619b8b34e31e347a8aab8f5c2cc5ce4990b22df0",
    "mixed_tailself_condition_plan": "8ce2752e6d698c3d6e91daf906901855ceac40de2a955470f27f96ab67edb6d5",
}
OLD_PROTOCOLS = {
    "MIXED_PROTOCOL": "m2m_n_mixed_single_edge_history_v1",
    "WEIGHT025_PROTOCOL": "m2m_n_mixed_history_weight025_v1",
    "WEIGHT0_CONTROL_PROTOCOL": "m2m_n_mixed_history_weight0_control_v1",
    "ONESTEP_PROTOCOL": "m2m_n_mixed_history_onestep_v1",
    "TAILSELF_PROTOCOL": "m2m_n_mixed_history_tailself_frozen_v1",
}
OLD_TAILSELF_FILES = {
    "src/ainerzero/cli.py", "src/ainerzero/runtime/memory_worker.py",
    "src/ainerzero/learning/action_preservation_closure.py", "src/ainerzero/learning/action_preservation.py",
    "src/ainerzero/learning/one_step_memory.py", "src/ainerzero/learning/tail_update.py",
    "src/ainerzero/learning/tailself_freeze.py", "configs/pilot.yaml",
    "artifacts/reports/relay-claude-20261014/M2NM5-tailself-freeze-registration-draft.json",
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


def _conflicting(seed=3, alpha=0.7):
    single = _tree(seed)
    noise = _tree(seed + 100)
    g_s = _flat(single)
    history = _from_flat(noise, -alpha * g_s + 0.3 * _flat(noise))
    assert float(_flat(history) @ g_s) < 0
    return history, single


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
    assert cli.TAILSELF_PROTOCOL == OLD_PROTOCOLS["TAILSELF_PROTOCOL"]
    assert cli.ONESTEP_PROTOCOL == OLD_PROTOCOLS["ONESTEP_PROTOCOL"]
    assert set(cli.TAILSELF_REQUIRED_FILES) == OLD_TAILSELF_FILES
    assert cli.TAILSELF_IDENTITY_PATH == "artifacts/reports/E28-tailself/tailself-identity.json"
    assert "src/ainerzero/learning/halfproj.py" not in cli.TAILSELF_REQUIRED_FILES
    assert "src/ainerzero/learning/halfproj.py" not in cli.ONESTEP_REQUIRED_FILES
    assert apc.TAILSELF_DESIGN_REGISTRATION_SHA256 == hashlib.sha256(M5_DRAFT.read_bytes()).hexdigest()
    for old in ("train-action-preserved-mixed-memory", "train-action-preserved-mixed-onestep-memory",
                "train-action-preserved-mixed-weight025-memory", "train-action-preserved-mixed-tailself-memory",
                "train-action-preserved-mixed-weight0-control-memory", COMMAND):
        with pytest.raises(SystemExit) as exc:
            cli.main([old, "--help"])
        assert exc.value.code == 0


def test_condition_differs_from_m2n_m5_only_by_the_projection_field_and_bookkeeping():
    base, new = apc.mixed_tailself_condition_plan(), apc.mixed_halfproj_condition_plan()
    assert new["protocol"] == apc.HALFPROJ_PROTOCOL == cli.HALFPROJ_PROTOCOL == "m2m_n_mixed_history_tailself_halfproj_v1"
    assert new["tailself_condition_sha256"] == base["condition_sha256"] == OLD_DIGESTS["mixed_tailself_condition_plan"]
    assert set(new) - set(base) == {"tailself_condition_sha256", "tailself_protocol",
                                    "tailself_design_registration_sha256", "half_projection"}
    changed = {k for k in set(base) & set(new) if base[k] != new[k]}
    assert changed == {"protocol", "single_factor", "condition_sha256", "design_registration_sha256"}
    proj = new["half_projection"]
    assert proj["skip_if_norm_sq_below"] == 1e-12 and proj["extra_model_calls"] == 0
    assert new["condition_sha256"] not in OLD_DIGESTS.values()


def test_design_digest_is_bound_to_the_registration_draft_bytes():
    assert hashlib.sha256(DRAFT.read_bytes()).hexdigest() == apc.HALFPROJ_DESIGN_REGISTRATION_SHA256
    draft = json.loads(DRAFT.read_text())
    assert draft["protocol_proposed"] == apc.HALFPROJ_PROTOCOL
    assert draft["projection"]["skip_if_norm_sq_below"] == apc.HALFPROJ_PROJECTION["skip_if_norm_sq_below"]
    assert draft["budget"] == {"units": 202304, "seconds": 1740, "work_deadline": 1760,
                               "supervisor_deadline": 1780, "extra_model_calls": 0}
    assert draft["parameters"] == apc.mixed_halfproj_condition_plan()["frozen_block"]["parameters"]


def test_worker_plan_is_m2n_m5_plus_projection():
    m5, new = mw.action_preservation_mixed_tailself_memory_plan(), mw.action_preservation_mixed_tailself_halfproj_memory_plan()
    differing = {k for k in set(m5) | set(new) if m5.get(k) != new.get(k)}
    assert differing == {"protocol", "half_projection", "action_preservation_condition"}
    assert (new["training_model_units_per_update"], new["expected_total_model_units"]) == (152, 202_304)
    assert (new["total_reserved_seconds_if_complete"], new["supervised_deadline_seconds"],
            new["supervisor_deadline_seconds"]) == (1_740, 1_760, 1_780)
    assert (new["trainable_parameter_count"], new["frozen_parameter_count"]) == (61_952, 331_280)
    assert (new["single_edge_rows"], new["history_rows"]) == (12, 4)


# ---------------------------------------------------------------- 2. pure projection

def test_non_conflict_returns_the_same_tree_and_merged_gradient_is_bitwise_m2n_m5():
    single = _tree(1)
    history = _from_flat(_tree(2), 0.5 * _flat(single) + 0.1 * _flat(_tree(2)))
    assert float(_flat(history) @ _flat(single)) > 0
    before = _copy(history)
    new, tel = hp.project_history_half(history, single)
    assert new is history and tel["projected"] is False and tel["removed_fraction"] == 0.0
    m5 = _merge({"single_edge": single, "history": before})
    m6 = _merge({"single_edge": single, "history": new})
    for n in LEAVES:
        assert m6["gru"][n].tobytes() == m5["gru"][n].tobytes()
    assert tel["cos_gh_gs"] > 0 and tel["history_l2"] > 0 and tel["single_l2"] > 0


def test_exactly_orthogonal_is_not_projected():
    single = {"gru": {n: np.zeros(GRU_SHAPES[f"model.gru.{n}"], np.float32) for n in LEAVES}}
    history = _copy(single)
    single["gru"]["Wx"][128, 0] = 1.0
    history["gru"]["Wx"][128, 1] = 1.0
    new, tel = hp.project_history_half(history, single)
    assert new is history and tel["projected"] is False and tel["inner_product"] == 0.0


def test_conflict_projects_inner_product_to_zero_and_never_touches_single():
    history, single = _conflicting()
    single_bytes = {n: v.tobytes() for n, v in single["gru"].items()}
    history_bytes = {n: v.tobytes() for n, v in history["gru"].items()}
    new, tel = hp.project_history_half(history, single)
    assert tel["projected"] is True and tel["inner_product"] < 0 and tel["cos_gh_gs"] < 0
    assert {n: v.tobytes() for n, v in single["gru"].items()} == single_bytes
    assert {n: v.tobytes() for n, v in history["gru"].items()} == history_bytes   # input untouched
    g_s, g_h, g_new = _flat(single), _flat(history), _flat(new)
    post = float(g_new @ g_s)
    assert abs(post) <= 1e-6 * np.linalg.norm(g_h) * np.linalg.norm(g_s)
    assert post >= -1e-6 * np.linalg.norm(g_h) * np.linalg.norm(g_s)
    reference = (g_h - (g_h @ g_s) / (g_s @ g_s) * g_s).astype(np.float32).astype(np.float64)
    np.testing.assert_array_equal(g_new, reference)
    removed = np.linalg.norm(g_h - g_new) / np.linalg.norm(g_h)
    assert tel["removed_fraction"] == pytest.approx(removed, rel=1e-12)
    assert 0 < tel["removed_fraction"] < 1
    assert tel["history_l2"] == pytest.approx(np.linalg.norm(g_h), rel=1e-12)
    assert tel["single_l2"] == pytest.approx(np.linalg.norm(g_s), rel=1e-12)
    assert tel["cos_gh_gs"] == pytest.approx((g_h @ g_s) / np.linalg.norm(g_h) / np.linalg.norm(g_s), rel=1e-12)
    m = _masks()
    for n in LEAVES:   # frozen elements of the history tree keep their bits
        assert new["gru"][n][~m[n]].tobytes() == history["gru"][n][~m[n]].tobytes()
        assert new["gru"][n].dtype == np.float32
    # merged gradient: single half contribution identical, history replaced
    merged = _merge({"single_edge": single, "history": new})
    expected = _merge({"single_edge": single, "history": _copy(new)})
    for n in LEAVES:
        assert merged["gru"][n].tobytes() == expected["gru"][n].tobytes()


def test_small_single_norm_skips_and_records():
    history, _ = _conflicting()
    single = {"gru": {n: np.zeros(GRU_SHAPES[f"model.gru.{n}"], np.float32) for n in LEAVES}}
    single["gru"]["Wx"][128, 0] = 1e-7      # ||g_s||^2 = 1e-14 < 1e-12
    history["gru"]["Wx"][128, 0] = -1.0
    new, tel = hp.project_history_half(history, single)
    assert new is history and tel["skipped_small_single_norm"] is True and tel["projected"] is False


def test_non_finite_and_bad_trees_fail_closed():
    history, single = _conflicting()
    history["gru"]["Wh"][128, 0] = np.nan
    with pytest.raises(ValueError, match="finite"):
        hp.project_history_half(history, single)
    with pytest.raises(ValueError, match="tree"):
        hp.project_history_half({"gru": {"Wx": single["gru"]["Wx"]}}, single)


def test_projection_ignores_frozen_elements():
    history, single = _conflicting()
    m = _masks()
    # put a huge conflicting value only in a frozen element (tail-self block / front row)
    single["gru"]["Wh"][200, 150] = 1e6
    history["gru"]["Wh"][200, 150] = -1e6
    assert not m["Wh"][200, 150] and not m["Wx"][0, 0]
    _, tel_a = hp.project_history_half(history, single)
    history2, single2 = _conflicting()
    _, tel_b = hp.project_history_half(history2, single2)
    assert tel_a["inner_product"] == tel_b["inner_product"]
    assert tel_a["elements"] == 61_952


# ---------------------------------------------------------------- 3. worker wiring (static)

def test_worker_calls_projection_before_merge_only_in_the_new_branch():
    src = (ROOT / "src/ainerzero/runtime/memory_worker.py").read_text()
    block = src[src.index("if action_preservation_mixed_tailself_halfproj:\n                    # M2n-M6"):
                src.index("gradients = apc.combine_mixed_halves(half_grads")]
    assert "project_history_half(" in block
    assert 'tree_flatten(half_grads["history"])' in block and 'tree_flatten(half_grads["single_edge"])' in block
    assert '                    if projection["projected"]:\n                        half_grads["history"] = {' in block
    assert 'half_grads["single_edge"] =' not in block
    assert 'mixed_details["half_projection"] = projection' in block
    assert "action_preservation_mixed_tailself = True  # M2n-M5 branch + half projection" in src
    assert '"--action-preservation-mixed-tailself-halfproj"' in src
    assert src.count("project_history_half(") == 1
    halfproj_src = (ROOT / "src/ainerzero/learning/halfproj.py").read_text()
    assert "import mlx" not in halfproj_src


# ---------------------------------------------------------------- 4. CLI entry / identity gate

def test_subcommand_sets_only_the_new_flag_and_has_no_scientific_knobs(monkeypatch):
    seen = {}
    monkeypatch.setattr(cli, "train_pilot_command", lambda args: seen.update(vars(args)) or {"status": "completed"})
    assert cli.main([COMMAND, *REQUIRED]) == 0
    assert seen["action_preserved_mixed_halfproj_training"] is True
    for other in ("action_preserved_mixed_training", "action_preserved_mixed_onestep_training",
                  "action_preserved_mixed_tailself_training", "action_preserved_mixed_weight025_training",
                  "action_preserved_mixed_weight0_control_training"):
        assert seen.get(other, False) is False
    for flag in ("--learning-rate", "--history-weight", "--projection-threshold", "--updates"):
        with pytest.raises(SystemExit):
            cli.main([COMMAND, *REQUIRED, flag, "1"])


def _args(tmp_path, **flags):
    base = dict(
        config=CONFIG, output_dir=tmp_path, experiment_id="e", dataset=tmp_path / "d",
        checkpoint=tmp_path / "c", comparison_report=tmp_path / "r", m2l_report=tmp_path / "m",
        m2l_checkpoint=tmp_path / "k", m2mc_report=tmp_path / "x",
        action_preserved_mixed_halfproj_training=True,
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
    assert "halfproj-identity.json" in report["error"] or "No such file" in report["error"]
    assert launched == []
    assert not (tmp_path / cli.HALFPROJ_IDENTITY_PATH).exists()


def test_dispatch_uses_the_new_flag_and_the_registered_timeout(monkeypatch, tmp_path):
    captured = {}

    class Done:
        returncode, stdout, stderr = 1, "", ""

    monkeypatch.setattr(cli, "verify_halfproj_identity", lambda *a, **k: None)
    monkeypatch.setattr(cli, "verify_tailself_identity",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("M2n-M5 gate used")))
    monkeypatch.setattr(cli, "project_root", lambda _path: tmp_path)
    monkeypatch.setattr(cli.subprocess, "run",
                        lambda cmd, **kw: captured.update(cmd=cmd, timeout=kw["timeout"]) or Done())
    cli.train_pilot_command(_args(tmp_path))
    assert "--action-preservation-mixed-tailself-halfproj" in captured["cmd"]
    for old in ("--action-preservation-mixed", "--action-preservation-mixed-tailself",
                "--action-preservation-mixed-onestep"):
        assert old not in captured["cmd"]
    assert captured["timeout"] == min(1780, cli.load_pilot_config(CONFIG).budget.max_wall_seconds)


def test_entry_is_exclusive_with_other_action_commands(monkeypatch, tmp_path):
    monkeypatch.setattr(cli.subprocess, "run", lambda *a, **k: (_ for _ in ()).throw(AssertionError("launched")))
    for conflict in ("action_preserved_mixed_training", "action_preserved_mixed_onestep_training",
                     "action_preserved_mixed_tailself_training", "action_preserved_mixed_weight025_training",
                     "action_preserved_mixed_weight0_control_training"):
        report = cli.train_pilot_command(_args(tmp_path, **{conflict: True}))
        assert report["status"] == "failed" and report["fail_closed"] is True


def _live_record():
    plan = apc.mixed_halfproj_condition_plan()
    return {"protocol": apc.HALFPROJ_PROTOCOL, "condition_sha256": plan["condition_sha256"],
            "design_registration_sha256": plan["design_registration_sha256"],
            "config_hash": cli.pilot_config_hash(cli.load_pilot_config(CONFIG)),
            "files": {rel: hashlib.sha256((ROOT / rel).read_bytes()).hexdigest()
                      for rel in sorted(cli.HALFPROJ_REQUIRED_FILES)}}


def test_identity_gate_accepts_live_record_in_memory_and_rejects_drift():
    assert set(cli.HALFPROJ_REQUIRED_FILES) == (OLD_TAILSELF_FILES - {
        "artifacts/reports/relay-claude-20261014/M2NM5-tailself-freeze-registration-draft.json"}) | {
        "src/ainerzero/learning/halfproj.py",
        "artifacts/reports/relay-claude-20261014/M2NM6-halfproj-registration-draft.json"}
    assert cli.HALFPROJ_IDENTITY_PATH != cli.TAILSELF_IDENTITY_PATH
    record = _live_record()
    cli.verify_halfproj_identity(ROOT, record, config_path=CONFIG)
    for rel in sorted(cli.HALFPROJ_REQUIRED_FILES):
        bad = json.loads(json.dumps(record))
        bad["files"][rel] = "ab" * 32
        with pytest.raises(RuntimeError, match="identity mismatch"):
            cli.verify_halfproj_identity(ROOT, bad, config_path=CONFIG)
    dropped = json.loads(json.dumps(record))
    dropped["files"].pop("src/ainerzero/learning/halfproj.py")
    with pytest.raises(RuntimeError, match="required set"):
        cli.verify_halfproj_identity(ROOT, dropped, config_path=CONFIG)
    with pytest.raises(RuntimeError, match="protocol"):
        cli.verify_halfproj_identity(ROOT, dict(record, protocol=apc.TAILSELF_PROTOCOL), config_path=CONFIG)
    with pytest.raises(RuntimeError, match="condition_sha256"):
        cli.verify_halfproj_identity(ROOT, dict(record, condition_sha256=OLD_DIGESTS["mixed_tailself_condition_plan"]),
                                     config_path=CONFIG)


# ---------------------------------------------------------------- 5. real mutations

MUTATIONS = {
    "two_sided_projection": ("src/ainerzero/learning/halfproj.py",
                             '    new_tree = {"gru": new_leaves}\n',
                             '    new_tree = {"gru": new_leaves}\n'
                             '    for name in LEAVES:\n'
                             '        s_leaf = single["gru"][name]\n'
                             '        s_leaf[masks[name]] = s_leaf[masks[name]] - np.float32(hs / hh) * leaves[name][masks[name]]\n'),
    "drop_negative_check": ("src/ainerzero/learning/halfproj.py",
                            "    if not hs < 0:\n        return history, telemetry\n", ""),
    "flipped_sign": ("src/ainerzero/learning/halfproj.py",
                     "projected = g_h - (hs / ss) * g_s", "projected = g_h + (hs / ss) * g_s"),
    "worker_skips_projection": ("src/ainerzero/runtime/memory_worker.py",
                                '                    if projection["projected"]:\n',
                                '                    if False and projection["projected"]:\n'),
}


def _copy_and_run(tmp_path, mutation=None):
    repo = tmp_path / "repo"
    for d in ("src", "tests", "configs"):
        shutil.copytree(ROOT / d, repo / d, ignore=shutil.ignore_patterns("__pycache__"))
    shutil.copy2(ROOT / "pyproject.toml", repo / "pyproject.toml")
    for draft in (DRAFT, M5_DRAFT):
        target = repo / draft.relative_to(ROOT)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(draft, target)
    if mutation:
        rel, old, new = MUTATIONS[mutation]
        text = (repo / rel).read_text()
        assert text.count(old) == 1, mutation
        (repo / rel).write_text(text.replace(old, new))
    return subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "-k", "not mutation and not unmutated",
         "tests/test_action_preservation_halfproj.py"],
        cwd=repo, env={"PYTHONPATH": str(repo / "src"), "PATH": "/usr/bin:/bin", "PYTHONDONTWRITEBYTECODE": "1"},
        capture_output=True, text=True, timeout=300)


@pytest.mark.parametrize("name", sorted(MUTATIONS))
def test_real_mutation_of_production_code_is_caught(name, tmp_path):
    proc = _copy_and_run(tmp_path, name)
    assert proc.returncode != 0, proc.stdout[-2000:]
    assert "failed" in proc.stdout


def test_unmutated_copy_passes_the_same_tests(tmp_path):
    proc = _copy_and_run(tmp_path)
    assert proc.returncode == 0, proc.stdout[-3000:]
