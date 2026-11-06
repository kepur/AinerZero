"""final-eval entry (r2): all registered arms, one read per family, and its own approval line."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).parent))
from test_e1_eval_runner import PerfectArm, synthesize_bounce_sequence  # noqa: E402

from ainerzero.v9.experiments.e1 import analysis, commands, export, prereg, spec, worker  # noqa: E402
from ainerzero.v9.experiments.e1.export import seal_final_dataset  # noqa: E402

pytestmark = pytest.mark.native_mlx(reason="real MLX import at collection via the e1 package (arms_net) (A39)")


def _seal_family(data_dir: Path, family: str, tmp_path: Path) -> tuple[Path, str]:
    """Seal a two-episode final dataset for one family, laid out as generate-data does."""
    s1, t1, tr1 = synthesize_bounce_sequence(1, init_z=0.5, init_vz=-1.0)
    s2, t2, tr2 = synthesize_bounce_sequence(2, init_z=0.6, init_vz=-1.0)
    staging = tmp_path / f"staging_{family}"
    staging.mkdir()
    with open(staging / "student_final.jsonl", "w", encoding="utf-8") as f:
        f.write(json.dumps(s1) + "\n" + json.dumps(s2) + "\n")
    with open(staging / "truth_final.jsonl", "w", encoding="utf-8") as f:
        f.write(json.dumps(t1) + "\n" + json.dumps(t2) + "\n")
    (staging / "export_meta.json").write_text(json.dumps({"version": "v1", "episodes": 2}), encoding="utf-8")
    sealed = seal_final_dataset(staging, sealed_root=data_dir / "sealed_final" / family, sealed_by="test")
    digest = sealed["dataset_digest"]
    return data_dir / "sealed_final" / family / digest, digest


class _TrajectoryArm:
    """Prediction that holds position: runs the whole evaluation path without a model file."""

    name = "hold"

    def predict(self, prefix, env, n_future, *, geometry_by_body=None, **kwargs):
        return {
            name: np.tile(np.asarray(rows, dtype=np.float64)[-1], (n_future, 1)) for name, rows in prefix.items()
        }


class _BrokenArm:
    name = "broken"

    def predict(self, *args, **kwargs):
        raise RuntimeError("model blew up")


def _env(tmp_path: Path, *, final_line: bool = True) -> dict[str, Path]:
    output_root = tmp_path / "phase2"
    output_root.mkdir()
    data_dir = tmp_path / "datasets"
    data_dir.mkdir()
    draft = prereg.build_draft()
    (data_dir / "generator_identity.json").write_text(
        json.dumps(
            {
                "generator_digests": draft["generator_digests"],
                "velocity_injection": draft["required_velocity_injection"],
            }
        ),
        encoding="utf-8",
    )
    prereg_file = output_root / "prereg.json"
    _, digest = prereg.freeze(draft, output_path=prereg_file)
    log = tmp_path / "RESEARCH_LOG.md"
    lines = [f"## {prereg.APPROVAL_SECTION}", prereg.approval_line(digest)]
    if final_line:
        lines.append(f"{prereg.FINAL_APPROVAL_PREFIX}{digest}")
    log.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {
        "output_root": output_root,
        "data_dir": data_dir,
        "prereg": prereg_file,
        "research_log": log,
        "ledger": output_root / "control.sqlite3",
        "lock_file": tmp_path / "worker.lock",
    }


def _args(env: dict[str, Path], mode: str, **kwargs) -> argparse.Namespace:
    base = {"command": "e1-phase2", "mode": mode, "arm": None, "family": None, "seed": None, "wall_budget_seconds": None}
    base.update(env)
    base.update(kwargs)
    return argparse.Namespace(**base)


def _use_trajectory_arms(monkeypatch, *, broken: tuple[int, int | None] | None = None) -> list:
    built: list = []

    def fake_build(arm, family, seed, output_root, evaluator_dir):
        built.append((arm, family, seed))
        if broken == (arm, seed):
            return _BrokenArm()
        return _TrajectoryArm()

    monkeypatch.setattr(worker, "build_arm_for_eval", fake_build)
    return built


def _make_checkpoints(env: dict[str, Path], family: str) -> None:
    for arm in spec.TRAINABLE_ARM_IDS:
        for seed in spec.TRAINING_SEEDS:
            cell = env["output_root"] / "checkpoints" / f"arm{arm}_{family}_seed{seed}"
            cell.mkdir(parents=True)
            (cell / "model_weights.npz").write_bytes(b"x")


# --- Approval ------------------------------------------------------------------------------


def test_prereg_approval_alone_does_not_open_final_eval(tmp_path):
    env = _env(tmp_path, final_line=False)
    sealed_dir, _ = _seal_family(env["data_dir"], "P", tmp_path)
    rep, code = commands.e1_phase2_command(_args(env, "final-eval", family="P"))
    assert code == commands.EXIT_REFUSED_APPROVAL
    assert rep["stage"] == "final_eval_approval"
    assert not export.final_marker_path(sealed_dir).exists()
    assert not env["ledger"].exists()


def test_final_approval_for_another_document_is_refused(tmp_path):
    env = _env(tmp_path)
    text = env["research_log"].read_text(encoding="utf-8")
    other = hashlib.sha256(b"other").hexdigest()
    lines = [ln for ln in text.splitlines() if not ln.startswith(prereg.FINAL_APPROVAL_PREFIX)]
    env["research_log"].write_text("\n".join(lines + [prereg.FINAL_APPROVAL_PREFIX + other]) + "\n", encoding="utf-8")
    rep, code = commands.e1_phase2_command(_args(env, "final-eval", family="P"))
    assert code == commands.EXIT_REFUSED_APPROVAL
    assert rep["stage"] == "final_eval_approval"


def test_final_approval_line_does_not_open_train_or_dev(tmp_path):
    """The two lines are not interchangeable in either direction."""
    env = _env(tmp_path)
    text = env["research_log"].read_text(encoding="utf-8")
    lines = [ln for ln in text.splitlines() if not ln.startswith(prereg.APPROVAL_PREFIX)]
    env["research_log"].write_text("\n".join(lines) + "\n", encoding="utf-8")
    rep, code = commands.e1_phase2_command(_args(env, "train", arm=3, family="P", seed=42))
    assert code == commands.EXIT_REFUSED_APPROVAL


def test_final_eval_needs_an_explicit_family(tmp_path):
    env = _env(tmp_path)
    rep, code = commands.e1_phase2_command(_args(env, "final-eval"))
    assert code == commands.EXIT_FAILED
    assert rep["stage"] == "invalid_family"


# --- The read is not spent early -----------------------------------------------------------


def test_missing_checkpoint_leaves_the_read_unspent(tmp_path):
    env = _env(tmp_path)
    sealed_dir, _ = _seal_family(env["data_dir"], "P", tmp_path)
    rep, code = commands.e1_phase2_command(_args(env, "final-eval", family="P"))
    assert code == commands.EXIT_FAILED
    assert rep["stage"] == "missing_checkpoint"
    assert not export.final_marker_path(sealed_dir).exists()
    assert not env["ledger"].exists()


def test_arm_that_fails_to_load_leaves_the_read_unspent(tmp_path, monkeypatch):
    env = _env(tmp_path)
    sealed_dir, _ = _seal_family(env["data_dir"], "P", tmp_path)
    _make_checkpoints(env, "P")

    def bad_build(arm, family, seed, output_root, evaluator_dir):
        raise OSError("corrupt checkpoint")

    monkeypatch.setattr(worker, "build_arm_for_eval", bad_build)
    rep, code = commands.e1_phase2_command(_args(env, "final-eval", family="P"))
    assert code == commands.EXIT_FAILED
    assert not export.final_marker_path(sealed_dir).exists()
    assert not (env["data_dir"] / "final").exists()


# --- All arms, each family -----------------------------------------------------------------


def test_final_eval_runs_every_registered_arm_in_both_family_orders(tmp_path, monkeypatch):
    env = _env(tmp_path)
    built = _use_trajectory_arms(monkeypatch)
    for family in ("S", "P"):  # S first was refused for P by the old global marker
        _seal_family(env["data_dir"], family, tmp_path)
        _make_checkpoints(env, family)
        rep, code = commands.e1_phase2_command(_args(env, "final-eval", family=family))
        assert code == commands.EXIT_COMPLETED, rep

    assert len(built) == 26
    final_dir = env["output_root"] / "eval_final"
    for family in ("P", "S"):
        for arm, seed in worker.registered_final_cells(family):
            report = json.loads((final_dir / f"eval_{worker.final_eval_cell_name(arm, family, seed)}.json").read_text(encoding="utf-8"))
            assert (report["arm"], report["family"], report["seed"]) == (arm, family, seed)
            assert report["partition"] == "final"
            assert report["episodes_evaluated"] == 2

    # analysis sees all 26 cells, and no others.
    cells = analysis.load_cells(final_dir, partition="final")
    assert len(cells) == 26
    assert (json.loads((final_dir / "final_eval_P.json").read_text(encoding="utf-8")))["failed_arms"] == {}


def test_second_read_of_a_family_is_refused(tmp_path, monkeypatch):
    env = _env(tmp_path)
    _use_trajectory_arms(monkeypatch)
    _seal_family(env["data_dir"], "P", tmp_path)
    _make_checkpoints(env, "P")
    _, code = commands.e1_phase2_command(_args(env, "final-eval", family="P"))
    assert code == commands.EXIT_COMPLETED
    rep, code = commands.e1_phase2_command(_args(env, "final-eval", family="P"))
    assert code == commands.EXIT_FAILED
    assert rep["stage"] == "final_eval_already_read_once"


def test_one_failing_arm_does_not_cost_the_others(tmp_path, monkeypatch):
    env = _env(tmp_path)
    _use_trajectory_arms(monkeypatch, broken=(6, 43))
    sealed_dir, _ = _seal_family(env["data_dir"], "P", tmp_path)
    _make_checkpoints(env, "P")
    rep, code = commands.e1_phase2_command(_args(env, "final-eval", family="P"))
    assert code == commands.EXIT_FAILED
    assert rep["status"] == "failed"

    final_dir = env["output_root"] / "eval_final"
    assert export.final_marker_path(sealed_dir).exists()
    assert not (final_dir / "eval_arm6_P_43.json").exists()
    assert len(list(final_dir.glob("eval_arm*.json"))) == 12
    assert "arm6_P_43" in json.loads((final_dir / "final_eval_P.json").read_text(encoding="utf-8"))["failed_arms"]


def test_each_cell_is_saved_as_soon_as_it_finishes(tmp_path, monkeypatch):
    """A crash later on must not lose what was already computed from the one read."""
    env = _env(tmp_path)
    _seal_family(env["data_dir"], "P", tmp_path)
    final_dir = env["output_root"] / "eval_final"
    seen: list[int] = []

    class Spy(_TrajectoryArm):
        def predict(self, *args, **kwargs):
            seen.append(len(list(final_dir.glob("eval_arm*.json"))))
            return super().predict(*args, **kwargs)

    monkeypatch.setattr(worker, "build_arm_for_eval", lambda **kw: Spy())
    _make_checkpoints(env, "P")
    _, code = commands.e1_phase2_command(_args(env, "final-eval", family="P"))
    assert code == commands.EXIT_COMPLETED
    assert seen[-1] == 12  # the 13th arm starts after 12 files exist


# --- analysis ------------------------------------------------------------------------------


def test_load_cells_ignores_files_from_another_partition(tmp_path):
    report = {"arm": 1, "family": "P", "seed": None, "summary": {}, "episodes": []}
    (tmp_path / "dev.json").write_text(json.dumps({**report, "partition": "development"}), encoding="utf-8")
    assert analysis.load_cells(tmp_path, partition="final", allow_partial=True) == {}
    assert ("P", 1, None) in analysis.load_cells(tmp_path, partition="development", allow_partial=True)


# --- r2 scope ------------------------------------------------------------------------------


def test_arm2_cannot_be_retrained_and_data_cannot_be_regenerated(tmp_path):
    env = _env(tmp_path)
    rep, code = commands.e1_phase2_command(_args(env, "train", arm=2, family="P", seed=42))
    assert code == commands.EXIT_FAILED
    assert rep["stage"] == "invalid_arm"
    rep, code = commands.e1_phase2_command(_args(env, "generate-data"))
    assert code == commands.EXIT_FAILED
    assert rep["stage"] == "data_generation_not_allowed"
    assert not env["ledger"].exists()


def test_reservations_follow_the_arm_and_add_up_to_what_was_approved():
    caps = spec.BUDGET_CAPS
    assert commands._get_cell_budget("train", 3) == 500.0
    assert commands._get_cell_budget("train", 6) == 1150.0
    with pytest.raises(ValueError):
        commands._get_cell_budget("train", 2)
    assert commands._get_cell_budget("eval", 2) == 20.0
    assert commands._get_cell_budget("eval", 6) == 130.0
    assert commands._get_cell_budget("final-eval", None) == 900.0
    with pytest.raises(ValueError):
        commands._get_cell_budget("train", 3, 501.0)

    # The user approved 3.2 h for training plus dev; final is separate.
    assert caps["train_total_wall_max_seconds"] + caps["dev_eval_total_max_seconds"] <= 3.2 * 3600.0
    prereg.validate(prereg.build_draft())


def test_budget_validation_rejects_reservations_that_do_not_add_up():
    draft = prereg.build_draft()
    draft["budget_caps"]["train_cell_wall_by_arm"] = {"3": 600.0, "6": 1150.0}
    with pytest.raises(prereg.SpecValidationError, match="train reservations"):
        prereg.validate(draft)
    draft = prereg.build_draft()
    draft["budget_caps"]["dev_eval_cell_by_arm"]["6"] = 131.0
    with pytest.raises(prereg.SpecValidationError, match="dev reservations"):
        prereg.validate(draft)


def _fake_r1_root(tmp_path: Path, monkeypatch) -> Path:
    """An r1-shaped checkpoint tree, with the digest pins pointed at it."""
    root = tmp_path / "r1"
    weights, norms = {}, {}
    for family in spec.FAMILIES:
        for seed in spec.TRAINING_SEEDS:
            cell = f"arm2_{family}_seed{seed}"
            d = root / "checkpoints" / cell
            d.mkdir(parents=True)
            (d / "model_weights.npz").write_bytes(f"w{cell}".encode())
            (d / "normalization.npz").write_bytes(f"n{cell}".encode())
            (d / "checkpoint_meta.json").write_text("{}", encoding="utf-8")
            weights[cell] = hashlib.sha256(f"w{cell}".encode()).hexdigest()
            norms[cell] = hashlib.sha256(f"n{cell}".encode()).hexdigest()
    monkeypatch.setattr(spec, "INHERITED_ARM2_WEIGHTS_SHA256", weights)
    monkeypatch.setattr(spec, "INHERITED_ARM2_NORMALIZATION_SHA256", norms)
    return root


def test_inherit_arm2_copies_and_leaves_the_source_alone(tmp_path, monkeypatch):
    src = _fake_r1_root(tmp_path, monkeypatch)
    before = {p: p.read_bytes() for p in src.rglob("*") if p.is_file()}
    dst = tmp_path / "r2"
    worker.ensure_inherited_arm2(src, dst)
    assert worker.verify_inherited_arm2(dst) == []
    assert {p: p.read_bytes() for p in src.rglob("*") if p.is_file()} == before
    assert sorted(p.name for p in (dst / "checkpoints" / "arm2_P_seed42").iterdir()) == [
        "checkpoint_meta.json",
        "model_weights.npz",
        "normalization.npz",
    ]
    worker.ensure_inherited_arm2(src, dst)  # idempotent


def test_inherit_arm2_refuses_a_changed_file(tmp_path, monkeypatch):
    src = _fake_r1_root(tmp_path, monkeypatch)
    dst = tmp_path / "r2"
    (src / "checkpoints" / "arm2_S_seed44" / "normalization.npz").write_bytes(b"tampered")
    with pytest.raises(RuntimeError, match="arm2_S_seed44/normalization.npz"):
        worker.ensure_inherited_arm2(src, dst)


def test_inherit_arm2_does_not_overwrite_an_existing_checkpoint(tmp_path, monkeypatch):
    src = _fake_r1_root(tmp_path, monkeypatch)
    dst = tmp_path / "r2"
    worker.ensure_inherited_arm2(src, dst)
    target = dst / "checkpoints" / "arm2_P_seed42" / "model_weights.npz"
    target.write_bytes(b"changed afterwards")
    with pytest.raises(RuntimeError, match="arm2_P_seed42/model_weights.npz"):
        worker.ensure_inherited_arm2(src, dst)
    assert target.read_bytes() == b"changed afterwards"
