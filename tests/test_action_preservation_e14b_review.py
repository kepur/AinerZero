"""E14b independent static/CPU review tests for the E13b action-preservation entry.

Reviewer scope: this file only *checks* the delivered revision (E13b, source
``memory_worker.py d3c2a2e7…a255`` / ``cli.py c0a88f99…c2c1`` /
``action_preservation_closure.py e26e58d2…a06c``). It never edits the
implementation, never creates a run, never loads MLX and never writes inside a
run directory.

The heavy real-data checks (production closure on the 16 registered train
episodes, reuse-closure ledger gates, read-only control-database accounting)
live in ``artifacts/reports/E14b-independent-review/probe.py``; this file stays
light and deterministic. Findings F-01/F-02 of the review are reproduced here as
fixtures so E13b-R1 has ready-made regression material.
"""

import ast
import copy
import hashlib
import json
import sys
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from ainerzero import cli
from ainerzero.learning import action_preservation as ap
from ainerzero.learning import action_preservation_closure as apc
from ainerzero.runtime import memory_worker as mw

ROOT = Path(__file__).resolve().parents[1]
LEARNING = ROOT / "src" / "ainerzero" / "learning"
WORKER = ROOT / "src" / "ainerzero" / "runtime" / "memory_worker.py"
M2L_REPORT = ROOT / "artifacts" / "reports" / "m2l-diverse-memory.json"

# Plan digests derived by the reviewer from the pre-E13b source itself
# (``git show 02f4e3255d433a148c79a9f217dddab2e4fe56d6:src/ainerzero/runtime/memory_worker.py``,
# file SHA 1236103976ef9459037c58e25e7cdadbb67698f45e30f179d784db1ce037263e),
# not copied from the E13b report or its tests.
PRE_E13B_PLAN_SHA256 = {
    "memory_plan": "ec73cfdab0ffe3dec4992aba80dcc86dc8a526a1fd9c1ee4ce817ce991d7d51d",
    "micro_memory_plan": "2407e358866f79877da7abb4e15325bb6eff92e0c25dfe48f49dc4250396ab5d",
    "diverse_memory_plan": "535a726d00496bb9fb1572337a49cad8ba86c6bd1ec70fd54e111d2254dec797",
    "relabel_0.001": "45d4c0a39baaad61aff55120387f143eb9491e8e870fe126f1f604015d4658c4",
    "relabel_0.003": "249adc8596041098093cab8a124e27c11df0edd6b8e44ddc16cca71ecb4374a7",
}
FROZEN_ACTION_PLAN_SHA256 = "cb1437efa7980e7e15dffc736ed9ec170a0be4dabdb4b5ebdd7989d1286af489"


def digest(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


def worker_tree():
    return ast.parse(WORKER.read_text())


def test_review_process_never_imports_mlx():
    """The review modules must import without MLX (fresh-process check)."""
    code = ("import sys, ainerzero.runtime.memory_worker, "
            "ainerzero.learning.action_preservation_closure; "
            "assert not any(k == 'mlx' or k.startswith('mlx.') for k in sys.modules)")
    import subprocess
    subprocess.run([sys.executable, "-c", code], check=True)


# ------------------------------------------------------------ old entry (F-01)


def test_old_plans_match_pre_e13b_source():
    got = {
        "memory_plan": digest(mw.memory_plan()),
        "micro_memory_plan": digest(mw.micro_memory_plan()),
        "diverse_memory_plan": digest(mw.diverse_memory_plan()),
        "relabel_0.001": digest(mw.relabel_memory_plan(0.001)),
        "relabel_0.003": digest(mw.relabel_memory_plan(0.003)),
    }
    assert got == PRE_E13B_PLAN_SHA256


def test_old_entry_files_and_rates_unchanged():
    assert mw.RELABEL_LEARNING_RATES == {
        0.001: "m2m_consistent_relabel_single_edge_tail_fit_v1",
        0.003: "m2m_c_consistent_relabel_lr0003_single_edge_tail_fit_v1",
    }
    # the M2m-c entry keeps its own learning-rate argument and supervision window
    assert mw.relabel_memory_plan(0.001)["learning_rate"] == 0.001
    assert mw.relabel_memory_plan(0.003)["learning_rate"] == 0.003
    assert mw.relabel_memory_plan(0.001)["supervised_deadline_seconds"] == 1720


# ------------------------------------------------------------- plan arithmetic


def test_action_plan_arithmetic_and_registration():
    plan = mw.action_preservation_memory_plan()
    seconds = plan["resource_seconds"]
    assert ap.RETAINED_UNITS + ap.TEACHER_UNITS + ap.STUDENT_UNITS == 208_546
    assert plan["expected_total_model_units"] == 208_546
    counts = {"training_update": plan["updates"], "local_check": 2 * len(plan["local_checks"])}
    assert counts == {"training_update": 200, "local_check": 10}
    assert sum(v * counts.get(k, 1) for k, v in seconds.items()) == 1610
    assert plan["total_reserved_seconds_if_complete"] == 1610
    assert (plan["supervised_deadline_seconds"], plan["supervisor_deadline_seconds"]) == (1660, 1710)
    assert plan["supervisor_deadline_seconds"] <= ap.SINGLE_RUN_LIMIT_SECONDS
    assert plan["learning_rate"] == 0.003 and plan["updates"] == 200
    assert ap.verify_frozen_plan(plan["action_preservation"]) == FROZEN_ACTION_PLAN_SHA256
    assert "m2l_pair" not in json.dumps(seconds)


def test_action_plan_seconds_cover_exactly_the_action_path_stages():
    """Training path only: the probe branch has its own plan (checked separately)."""
    run_memory_node = next(
        n for n in worker_tree().body if isinstance(n, ast.FunctionDef) and n.name == "run_memory"
    )
    static, dynamic = set(), set()
    for node in ast.walk(run_memory_node):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "stage"
            and node.args
        ):
            (static if isinstance(node.args[0], ast.Constant) else dynamic).add(
                node.args[0].value if isinstance(node.args[0], ast.Constant) else ast.unparse(node.args[0])
            )
    expanded = {
        f"{phase}_memory_{part}" for phase in ("before", "after") for part in ("train", "development")
    } | {f"{phase}_{suffix}" for phase in ("before", "after") for suffix in ("action", "reconstruction")}
    missing = (static | expanded) - set(mw.action_preservation_memory_plan()["resource_seconds"])
    # the only stages the action branch does not execute are the two reused M2l model stages
    assert sorted(missing) == ["m2l_paired_cells", "m2l_relabel_pool"]
    assert set(expanded) <= set(mw.action_preservation_memory_plan()["resource_seconds"])


# --------------------------------------------------- MLX import / model shortcut


def test_mlx_modules_are_imported_only_after_initialization():
    tree = worker_tree()
    run_memory = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "run_memory")
    lines = {"mlx": [], "apm": [], "stage_init": [], "closure": None}
    source = WORKER.read_text()
    lines["closure"] = source[: source.index("keep = None")].count("\n") + 1
    for node in ast.walk(run_memory):
        if isinstance(node, ast.Import) and any(a.name.startswith("mlx") for a in node.names):
            lines["mlx"].append(node.lineno)
        if isinstance(node, ast.ImportFrom):
            if (node.module or "").startswith("mlx"):
                lines["mlx"].append(node.lineno)
            if node.module == "ainerzero.learning.action_preservation_mlx" or any(
                a.name == "action_preservation_mlx" for a in node.names
            ):
                lines["apm"].append(node.lineno)
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "stage"
            and node.args
            and isinstance(node.args[0], ast.Constant)
            and node.args[0].value == "initialization"
        ):
            lines["stage_init"].append(node.lineno)
    assert lines["mlx"] and lines["apm"] and lines["stage_init"]
    assert min(lines["mlx"]) > max(lines["stage_init"]) > lines["closure"]
    assert min(lines["apm"]) > max(lines["stage_init"])
    # closure module must stay pure CPU
    closure_imports = {
        n.module or "" for n in ast.walk(ast.parse((LEARNING / "action_preservation_closure.py").read_text()))
        if isinstance(n, ast.ImportFrom)
    } | {
        a.name for n in ast.walk(ast.parse((LEARNING / "action_preservation_closure.py").read_text()))
        if isinstance(n, ast.Import) for a in n.names
    }
    assert not any(m == "mlx" or m.startswith("mlx.") for m in closure_imports)


def test_mlx_module_cannot_be_imported_by_a_test_process():
    """The review must not be able to reach the MLX path by accident."""
    assert "action_preservation_mlx" not in sys.modules


# ------------------------------------------------------------ fail-closed checks


FAIL_CLOSED_MESSAGES = [
    "first-update keep-loss guard failed",
    "clipped gradient has nonzero frozen rows",
    "frozen M2d teacher did not load exactly",
    "teacher cache files must be new",
    "teacher cache file identity changed",
    "memory measured work differs from reserved model units",
    "micro memory model units differ from fixed plan",
    "diverse source checkpoint or comparison report changed",
    "memory training batch has no supervised visible targets",
]


@pytest.mark.parametrize("message", FAIL_CLOSED_MESSAGES)
def test_fail_closed_message_is_raised_not_logged(message):
    hits = [
        ast.unparse(node)
        for node in ast.walk(worker_tree())
        if isinstance(node, ast.Raise) and message in ast.unparse(node)
    ]
    assert hits, f"{message!r} is not raised on the action path"


def test_action_flag_requires_its_m2l_artifacts(tmp_path):
    """The new flag alone cannot run: it still needs the completed M2l evidence."""
    with pytest.raises(ValueError, match="M2l report and checkpoint"):
        mw.run_memory(None, None, None, tmp_path, tmp_path / "db", "e",
                      action_preservation_fit=True, m2mc_report_path=tmp_path / "x")
    with pytest.raises(ValueError, match="exactly its M2m-c report"):
        mw.run_memory(None, None, None, tmp_path, tmp_path / "db", "e",
                      action_preservation_fit=False, m2mc_report_path=tmp_path / "x")


# ------------------------------------------------------- CLI -> worker wiring


def test_cli_action_command_round_trips_into_the_worker_parser(monkeypatch, tmp_path):
    captured = {}

    class Done:
        returncode, stdout, stderr = 1, "", ""

    def fake_run(cmd, **kw):
        captured["cmd"], captured["timeout"] = cmd, kw["timeout"]
        return Done()

    monkeypatch.setattr(cli.subprocess, "run", fake_run)
    monkeypatch.setattr(cli, "project_root", lambda _: tmp_path)
    args = SimpleNamespace(
        config=ROOT / "configs" / "pilot.yaml", output_dir=tmp_path, experiment_id="e",
        dataset=tmp_path / "d", checkpoint=tmp_path / "c", comparison_report=tmp_path / "r",
        m2l_report=tmp_path / "m", m2l_checkpoint=tmp_path / "k", m2mc_report=tmp_path / "x",
        action_preserved_memory_training=True,
    )
    cli.train_pilot_command(args)
    cmd = captured["cmd"]
    assert cmd[2] == "ainerzero.runtime.memory_worker"
    assert captured["timeout"] == min(1710, cli.load_pilot_config(args.config).budget.max_wall_seconds)

    parsed = {}
    monkeypatch.setattr(mw, "run_memory", lambda *a, **k: parsed.update(k) or {"status": "failed"})
    monkeypatch.setattr(sys, "argv", ["worker", *cmd[3:]])
    monkeypatch.setattr("builtins.print", lambda *a, **k: None)
    assert mw.main() == 1
    assert parsed["action_preservation_fit"] is True
    assert parsed["m2mc_report_path"] == (tmp_path / "x").resolve()
    assert parsed["relabel_fit"] is False and parsed["relabel_learning_rate"] is None
    assert parsed["diverse_fit"] is False and parsed["local_fit"] is False


def test_action_command_uses_the_shared_worker_lock(monkeypatch, tmp_path):
    seen = []

    @contextmanager
    def fake_lock(path):
        seen.append(Path(path))
        yield

    class Done:
        returncode, stdout, stderr = 1, "", ""

    monkeypatch.setattr(cli, "worker_lock", fake_lock)
    monkeypatch.setattr(cli.subprocess, "run", lambda cmd, **kw: Done())
    monkeypatch.setattr(cli, "project_root", lambda _: tmp_path)
    args = SimpleNamespace(
        config=ROOT / "configs" / "pilot.yaml", output_dir=tmp_path, experiment_id="e",
        dataset=tmp_path / "d", checkpoint=tmp_path / "c", comparison_report=tmp_path / "r",
        m2l_report=tmp_path / "m", m2l_checkpoint=tmp_path / "k", m2mc_report=tmp_path / "x",
        action_preserved_memory_training=True,
    )
    cli.train_pilot_command(args)
    assert seen == [tmp_path / "artifacts" / "locks" / "m0-worker.lock"]
    assert (tmp_path / "artifacts" / "control.sqlite3").exists()


# ------------------------------------------- methods-only blind spot (F-02 / R1)


def _cells(history_argmax, history_nll, zero_argmax, zero_nll):
    """Cells in the JSON shape ``action_preservation_closure._cell_arrays`` accepts."""
    return {
        "history_tail": {"argmax": list(history_argmax), "nll": list(history_nll)},
        "zero_context_tail": {"argmax": list(zero_argmax), "nll": list(zero_nll)},
    }


def _swap_fixture():
    """Two variants of one query that differ only by a within-query re-pairing.

    Cell 0 is history-only-correct, cell 1 is zero-only-correct in variant A.
    Variant B swaps the two history results (argmax and NLL together), so both
    branches keep identical accuracy/NLL/counts while the paired counts flip
    from (both 6, history_only 1, zero_only 1, neither 0) to
    (both 7, history_only 0, zero_only 0, neither 1).
    """
    cells = 8
    targets = [7] * cells
    current = [7] * cells
    tmask = [True] * cells
    cmask = [True] * cells
    variant_a = _cells([7] * cells, [0.10] * cells, [7] * cells, [0.10] * cells)
    variant_a["history_tail"]["argmax"][1] = 3
    variant_a["history_tail"]["nll"][1] = 1.10
    variant_a["zero_context_tail"]["argmax"][0] = 3
    variant_a["zero_context_tail"]["nll"][0] = 1.10
    variant_b = copy.deepcopy(variant_a)
    variant_b["history_tail"]["argmax"][0] = variant_a["history_tail"]["argmax"][1]
    variant_b["history_tail"]["argmax"][1] = variant_a["history_tail"]["argmax"][0]
    variant_b["history_tail"]["nll"][0] = variant_a["history_tail"]["nll"][1]
    variant_b["history_tail"]["nll"][1] = variant_a["history_tail"]["nll"][0]
    frames = {
        "previous_symbols": np.asarray([targets]), "previous_visible": np.asarray([tmask]),
        "current_symbols": np.asarray([current]), "current_visible": np.asarray([cmask]),
    }
    queries = [{"episode_id": "e", "query_tick": 1, "group": "development"}]
    return dict(cells=cells, variant_a=variant_a, variant_b=variant_b, frames=frames,
                queries=queries, targets=targets, tmask=tmask, current=current, cmask=cmask)


def _methods(cells, fixture):
    return {
        branch: apc._metrics(
            np.asarray(cell["argmax"]), np.asarray(cell["nll"]), np.asarray(fixture["targets"]),
            np.asarray(fixture["tmask"]), np.asarray(fixture["current"]),
            np.asarray(fixture["cmask"]), branch,
        )
        for branch, cell in cells.items()
    }


def _paired_counts(cells, fixture):
    targets = np.asarray(fixture["targets"])
    history = np.asarray(cells["history_tail"]["argmax"]) == targets
    zero = np.asarray(cells["zero_context_tail"]["argmax"]) == targets
    return {
        "both_correct": int((history & zero).sum()),
        "history_only_correct": int((history & ~zero).sum()),
        "zero_only_correct": int((~history & zero).sum()),
        "neither_correct": int((~history & ~zero).sum()),
        "prediction_disagreements": int((history != zero).sum()),
    }


def _paired_reference(cells, fixture):
    """Independent 16-field paired reference (no closure code involved)."""
    targets = np.asarray(fixture["targets"])
    tmask = np.asarray(fixture["tmask"])
    current = np.asarray(fixture["current"])
    cmask = np.asarray(fixture["cmask"])
    changed = tmask & cmask & (targets != current)
    history = np.asarray(cells["history_tail"]["argmax"]) == targets
    zero = np.asarray(cells["zero_context_tail"]["argmax"]) == targets
    disagreement = np.asarray(cells["history_tail"]["argmax"]) != np.asarray(
        cells["zero_context_tail"]["argmax"]
    )
    out = {}
    for prefix, mask in (("", tmask), ("changed_", changed)):
        out.update({
            f"{prefix}count": int(mask.sum()),
            f"{prefix}history_only_correct": int((mask & history & ~zero).sum()),
            f"{prefix}zero_only_correct": int((mask & zero & ~history).sum()),
            f"{prefix}both_correct": int((mask & history & zero).sum()),
            f"{prefix}neither_correct": int((mask & ~history & ~zero).sum()),
            f"{prefix}prediction_disagreements": int((mask & disagreement).sum()),
        })
    methods = _methods(cells, fixture)
    for field in ("accuracy", "nll", "changed_accuracy", "changed_nll"):
        a = methods["history_tail"][field]
        b = methods["zero_context_tail"][field]
        out[f"history_minus_zero_{field}"] = None if a is None or b is None else a - b
    return out


def test_paired_swap_fixture_is_valid_and_methods_invisible():
    f = _swap_fixture()
    assert _methods(f["variant_a"], f) == _methods(f["variant_b"], f)
    assert _paired_counts(f["variant_a"], f) != _paired_counts(f["variant_b"], f)
    paired_a, paired_b = _paired_reference(f["variant_a"], f), _paired_reference(f["variant_b"], f)
    assert set(paired_a) == set(paired_b) and len(paired_a) == 16
    assert paired_a != paired_b
    assert paired_a["both_correct"] == 6 and paired_b["both_correct"] == 7
    assert paired_a["history_only_correct"] == 1 and paired_b["history_only_correct"] == 0
    assert paired_a["neither_correct"] == 0 and paired_b["neither_correct"] == 1
    assert paired_a["prediction_disagreements"] == 2 and paired_b["prediction_disagreements"] == 0
    for field in ("accuracy", "nll", "changed_accuracy", "changed_nll"):
        assert paired_a[f"history_minus_zero_{field}"] == paired_b[f"history_minus_zero_{field}"]
    assert _paired_counts(f["variant_a"], f) == {
        "both_correct": 6, "history_only_correct": 1, "zero_only_correct": 1,
        "neither_correct": 0, "prediction_disagreements": 2,
    }
    assert _paired_counts(f["variant_b"], f) == {
        "both_correct": 7, "history_only_correct": 0, "zero_only_correct": 0,
        "neither_correct": 1, "prediction_disagreements": 0,
    }


def test_closure_methods_fields_exclude_the_paired_counts():
    """Boundary of the current comparison: it checks per-branch marginals only."""
    f = _swap_fixture()
    checked = set(_methods(f["variant_a"], f)["history_tail"])
    assert checked == {
        "count", "accuracy", "nll", "changed_count", "changed_accuracy", "changed_nll",
        "unchanged_count", "unchanged_accuracy", "unchanged_nll",
    }
    assert "both_correct" not in checked and "history_only_correct" not in checked
    assert M2L_REPORT.exists(), "E14b must be run on the archived M2l report"
    paired = json.loads(M2L_REPORT.read_text())["paired"]["groups"]["development"]["paired"]
    paired_specific = {"both_correct", "history_only_correct", "zero_only_correct", "neither_correct",
                       "prediction_disagreements", "changed_both_correct",
                       "changed_history_only_correct", "changed_zero_only_correct",
                       "changed_neither_correct", "changed_prediction_disagreements",
                       "history_minus_zero_accuracy", "history_minus_zero_nll",
                       "history_minus_zero_changed_accuracy", "history_minus_zero_changed_nll"}
    assert paired_specific <= set(paired)
    assert not (paired_specific & checked)


def test_paired_aware_counter_reference_rejects_the_swap():
    """Feasibility reference for E13b-R1: a paired counter detects the swap."""
    f = _swap_fixture()
    expected = _paired_counts(f["variant_a"], f)
    assert _paired_counts(f["variant_b"], f) != expected

    def paired_aware(cells, fixture):
        counts = _paired_counts(cells, fixture)
        targets = np.asarray(fixture["targets"])
        history = np.asarray(cells["history_tail"]["argmax"]) == targets
        zero = np.asarray(cells["zero_context_tail"]["argmax"]) == targets
        counts["changed_history_only_correct"] = int((history & ~zero).sum())
        counts["changed_zero_only_correct"] = int((~history & zero).sum())
        return counts

    with pytest.raises(AssertionError):
        assert paired_aware(f["variant_b"], f) == paired_aware(f["variant_a"], f)


def test_r1_recompute_paired_rejects_the_swap_when_scaled_to_one_query(monkeypatch):
    """E13b-R1: the paired-field comparison must catch the within-query re-pairing."""
    f = _swap_fixture()
    expected = {
        "per_query": [{"episode_id": "e", "query_tick": 1, "world_index": 0,
                       "methods": _methods(f["variant_a"], f),
                       "paired": _paired_reference(f["variant_a"], f)}],
        "per_world": [{"world_index": 0, "methods": _methods(f["variant_a"], f),
                       "paired": _paired_reference(f["variant_a"], f)}],
        "groups": {"development": {"methods": _methods(f["variant_a"], f),
                                   "paired": _paired_reference(f["variant_a"], f)}},
    }
    monkeypatch.setattr(apc, "PAIRED_QUERIES", 1)
    out = apc.recompute_paired([copy.deepcopy(f["variant_a"])], f["frames"], f["queries"], expected)
    assert out["max_float_diff"] == 0.0 and out["compared"] == 102
    with pytest.raises(ValueError, match="paired"):
        apc.recompute_paired([copy.deepcopy(f["variant_b"])], f["frames"], f["queries"], expected)


def test_r1_closure_paired_counts_match_the_original_m2k_rule():
    rng = np.random.default_rng(11)
    for _ in range(200):
        targets = rng.integers(0, 5, 8)
        current = np.where(rng.random(8) < 0.5, targets, rng.integers(0, 5, 8))
        tmask, cmask = rng.random(8) < 0.7, rng.random(8) < 0.7
        tmask[0] = True
        history = rng.integers(0, 5, 8)
        zero = rng.integers(0, 5, 8)
        changed = tmask & cmask & (targets != current)
        h, z = history == targets, zero == targets
        disagreements = history != zero
        expected = {}
        for prefix, mask in (("", tmask), ("changed_", changed)):
            expected.update({
                f"{prefix}count": int(mask.sum()),
                f"{prefix}history_only_correct": int((mask & h & ~z).sum()),
                f"{prefix}zero_only_correct": int((mask & z & ~h).sum()),
                f"{prefix}both_correct": int((mask & h & z).sum()),
                f"{prefix}neither_correct": int((mask & ~h & ~z).sum()),
                f"{prefix}prediction_disagreements": int((mask & disagreements).sum()),
            })
        assert apc.paired_counts(history, zero, targets, tmask, current, cmask) == expected


# --------------------------------------------------------------- unit table


def test_student_unit_table_rejects_out_of_range_update():
    fixture = json.loads((ROOT / "tests/fixtures/m2md_pool_manifest.json").read_text())
    windows = ap.preservation_windows(fixture["samples"], fixture["schedule"])
    table = apc.student_units_per_update(windows)
    assert (len(table), sum(table)) == (200, 27_988)
    schedule = copy.deepcopy(windows["schedule"])
    batch = schedule[0]
    rows = {windows["rows"][r]["row"]: windows["rows"][r]["feedback"] for r in batch}
    low = min(rows, key=rows.get)
    high = max(rows, key=rows.get)
    assert rows[high] > rows[low], "fixture needs a batch with differing feedback"
    schedule[0] = [low if r == high else r for r in batch]
    with pytest.raises(ValueError, match="137..144"):
        apc.student_units_per_update(dict(windows, schedule=schedule))
    with pytest.raises(ValueError, match="200 entries"):
        apc.student_units_per_update(dict(windows, schedule=schedule[:-1]))


# --------------------------------------------------------- records rejection


def test_public_records_from_episodes_rejects_non_train_and_duplicates(monkeypatch):
    import ainerzero.core.experience as experience

    monkeypatch.setattr(experience, "admit_training", lambda item, policy: item)

    class Dumpable(SimpleNamespace):
        def model_dump(self, mode):
            return {"id": self.tag}

    def episode(tag, partition, episode_id, world):
        return Dumpable(
            tag=tag,
            initial=SimpleNamespace(context=SimpleNamespace(
                partition=SimpleNamespace(value=partition), episode_id=episode_id,
                environment_instance_id=world)),
            transitions=[],
        )

    with pytest.raises(ValueError, match="train episodes only"):
        apc.public_records_from_episodes([episode("e", "development", "e", "w")])
    dup = [episode("e", "train", "e", "w"), episode("e2", "train", "e", "w")]
    with pytest.raises(ValueError, match="duplicate train episode"):
        apc.public_records_from_episodes(dup)


def test_strict_records_reject_foreign_fields_and_int_like_keys():
    base = {
        "e": {"partition": "train", "environment_instance_id": "w",
              "public_episode_sha256": "a" * 64,
              "transitions": {0: {"target_observation_id": "t", "current_observation_id": "c",
                                  "action_request_id": "a", "public_transition_sha256": "b" * 64,
                                  "target_tick": 1}}},
    }
    assert apc._strict_records(base)["e"]["transitions"][0]["target_tick"] == 1
    for mutate in (
        lambda r: r["e"].update(verified=True),
        lambda r: r["e"].update(transitions={np.int64(0): r["e"]["transitions"][0]}),
        lambda r: r["e"]["transitions"][0].update(target_tick=np.int64(1)),
        lambda r: r["e"]["transitions"][0].update(extra_field=1),
    ):
        bad = copy.deepcopy(base)
        mutate(bad)
        with pytest.raises(ValueError):
            apc._strict_records(bad)


# ------------------------------------------------------------ screen semantics


def _screen_inputs(after_nll=(0.05, 0.15), before_nll=(0.0, 0.0)):
    def action(correct, nll):
        return {"horizons": {"1": {"model": {"count": 384, "accuracy": correct[0] / 384, "nll": nll[0]}},
                             "4": {"model": {"count": 384, "accuracy": correct[1] / 384, "nll": nll[1]}}}}
    paired = {"groups": {"development": {"methods": {"zero_context_tail": {
        "count": 4096, "accuracy": 3892 / 4096, "changed_count": 127,
        "changed_accuracy": 115 / 127}}}}}
    return (
        {"action": action((384, 384), before_nll)},
        {"action": action((377, 359), after_nll),
         "reconstruction": {"gate": {"status": "passed"}, "model": {"count": 544, "accuracy": 1.0}}},
        paired,
        {"count": 2048, "correct": 1946, "changed_count": 140, "changed_correct": 126},
    )


def test_screen_uses_after_minus_before_and_never_promotes():
    out = apc.preservation_screen(*_screen_inputs(after_nll=(0.05, 0.15), before_nll=(0.0, 0.0)))
    assert out["status"] == "passed" and out["promotion"] is False
    assert out["checks"]["action_1"]["nll_increase"] == 0.05
    out = apc.preservation_screen(*_screen_inputs(after_nll=(0.05, 0.15), before_nll=(1.0, 1.0)))
    assert out["checks"]["action_1"]["nll_increase"] == pytest.approx(-0.95)
    assert out["status"] == "passed" and out["promotion"] is False and out["automatic_next_run"] is False
    worse = apc.preservation_screen(*_screen_inputs(after_nll=(0.0500001, 0.15), before_nll=(0.0, 0.0)))
    assert worse["status"] == "failed" and worse["checks"]["action_1"]["passed"] is False


def test_screen_rejects_wrong_denominator_or_tampered_counts():
    before, after, paired, relabel = _screen_inputs()
    bad = copy.deepcopy(relabel)
    bad["count"] = 2047
    with pytest.raises(ValueError):
        apc.preservation_screen(before, after, paired, bad)
    bad = copy.deepcopy(paired)
    bad["groups"]["development"]["methods"]["zero_context_tail"]["changed_count"] = 126
    with pytest.raises(ValueError):
        apc.preservation_screen(before, after, bad, relabel)


# ------------------------------------------------------------ cache trust root


def test_expected_cache_binding_uses_its_own_run_id(tmp_path):
    fixture = json.loads((ROOT / "tests/fixtures/m2md_pool_manifest.json").read_text())

    def records(samples):
        out = {}
        for s in samples:
            rec = out.setdefault(s["episode_id"], {
                "partition": "train", "environment_instance_id": s["environment_instance_id"],
                "public_episode_sha256": s["public_episode_sha256"], "transitions": {}})
            rec["transitions"][s["transition_index"]] = {
                k: s[k] for k in ("target_observation_id", "current_observation_id", "action_request_id",
                                  "public_transition_sha256", "target_tick")}
        return out

    windows = apc.production_windows(fixture["samples"], fixture["schedule"], records(fixture["samples"]))
    (tmp_path / "manifest.json").write_bytes(b'{"schema_version": 1}')
    run_id = "11111111-1111-4111-8111-111111111111"
    binding = apc.expected_cache_binding(checkpoint_path=tmp_path, windows=windows["windows"],
                                         keys=windows["keys"], run_id=run_id)
    assert binding["run_id"] == run_id and len(binding) == 14
    arrays = {
        "incoming_h": np.zeros((256, 256), np.float32),
        "teacher_logits": np.zeros((256, 2, 8, 256), np.float32),
        "visible_mask": np.ones((256, 8), bool),
    }
    ap.teacher_cache_manifest(binding, arrays)
    # a cache written under a different run_id can never satisfy the production binding
    other = dict(binding, run_id="22222222-2222-4222-8222-222222222222")
    with pytest.raises(ValueError, match="binding mismatch"):
        ap.verify_teacher_cache(ap.teacher_cache_manifest(other, arrays), arrays, binding)
    # and the trusted source digest really covers the three teacher source files
    assert apc.teacher_source_sha256(LEARNING) == binding["teacher_source_sha256"]


# ------------------------------------------------- E13b-R1 probe entry review


def test_r1_probe_plan_registered_arithmetic():
    plan = mw.action_preservation_probe_plan()
    assert plan["protocol"] == mw.PROBE_PROTOCOL
    assert plan["production_protocol"] == ap.PROTOCOL
    assert plan["updates"] == mw.PROBE_UPDATES == 3 and plan["local_checks"] == []
    assert plan["student_model_units_per_update"] == list(mw.PROBE_STUDENT_UNITS) == [139, 138, 144]
    assert plan["expected_total_model_units"] == (
        2 * ap.TEACHER_UNITS + 3 * plan["training_model_units_per_update"] + sum(mw.PROBE_STUDENT_UNITS)
    ) == 5_025
    seconds = plan["resource_seconds"]
    assert set(seconds) == {"compatibility", "initialization", "teacher_cache", "cache_protocol_checks",
                            "teacher_repeat", "training_update", "verification"}
    assert sum(v * (3 if k == "training_update" else 1) for k, v in seconds.items()) == 179
    assert plan["total_reserved_seconds_if_complete"] == 179
    assert (plan["supervised_deadline_seconds"], plan["supervisor_deadline_seconds"]) == (229, 279)
    assert plan["supervisor_deadline_seconds"] <= ap.SINGLE_RUN_LIMIT_SECONDS
    assert plan["checkpoint"].startswith("not_saved") and plan["promotion"] is False
    assert plan["evaluations"].startswith("none") and plan["first_update_invariant"] == "recorded_not_stopping"
    assert "m2l_baselines" not in plan
    # the probe never reuses the training entry's M2l stages or evaluation windows
    assert "after_paired" not in seconds and "m2l_paired_cells" not in seconds


def test_amendment_first_update_bound_is_registered_and_fail_closed():
    """C06a amendment: exact 0.0 replaced by the registered absolute bound."""
    import math

    assert apc.FIRST_UPDATE_KEEP_LOSS_MAX == 1e-5
    plan = mw.action_preservation_memory_plan()
    assert plan["first_update_keep_loss_max"] == apc.FIRST_UPDATE_KEEP_LOSS_MAX
    assert mw.action_preservation_probe_plan()["first_update_bound"] == 1e-5
    # measured C06a values pass, are recorded, and are not exact zero
    measured = [1.7572e-08, -1.512e-09, 1.2131165760820295e-07, -2.5553e-08, 5.7843e-08]
    out = apc.check_first_update_keep_loss(measured)
    assert out["within_registered_bound"] is True and out["all_exact_zero"] is False
    assert out["count"] == 5 and out["max_abs"] == pytest.approx(1.2131165760820295e-07)
    # boundary is inclusive; anything above, non-finite, or empty stops the run
    assert apc.check_first_update_keep_loss([1e-5, -1e-5])["within_registered_bound"] is True
    for bad in ([1.000001e-5], [-1.000001e-5], [float("nan")], [float("inf")], [], [0.0, -math.inf]):
        with pytest.raises(ValueError):
            apc.check_first_update_keep_loss(bad)


def test_amendment_training_branch_uses_the_bound_and_probe_only_records():
    tree = worker_tree()
    run_memory_node = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "run_memory")
    probe_node = next(n for n in tree.body if isinstance(n, ast.FunctionDef)
                      and n.name == "run_action_preservation_probe")
    training_src = ast.unparse(run_memory_node)
    probe_src = ast.unparse(probe_node)
    assert "check_first_update_keep_loss" in training_src
    assert "first-update keep-loss guard failed" in training_src
    assert "check_first_update_keep_loss" not in probe_src
    assert "within_registered_bound" in probe_src and "stopping" in probe_src
    assert 'all_exact_zero' in probe_src


def test_e15_regression_candidate_evaluation_names_are_bound_for_action_path():
    """E15 failure 2026-10-13: evaluate_zero_context_inputs/summarize_relabel_pool
    were imported only under ``not action_preservation_fit`` while the candidate
    relabel-pool evaluation runs for every relabel variant (UnboundLocalError)."""
    run_memory_node = next(n for n in worker_tree().body
                           if isinstance(n, ast.FunctionDef) and n.name == "run_memory")

    def guarded(node, stack, out):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.If):
                guarded(child, stack + [ast.unparse(child.test)], out)
            else:
                if isinstance(child, ast.ImportFrom):
                    out.append((child.module or "", [a.name for a in child.names], tuple(stack)))
                guarded(child, stack, out)

    imports = []
    guarded(run_memory_node, [], imports)
    for name, module in (("evaluate_zero_context_inputs", "ainerzero.learning.paired_memory"),
                         ("summarize_relabel_pool", "ainerzero.learning.relabel_memory")):
        guards = [g for mod, names, g in imports if mod == module and name in names]
        assert guards, f"{name} is never imported in run_memory"
        assert any(not any("action_preservation_fit" in g for g in chain) for chain in guards), (
            f"{name} is only bound when action_preservation_fit is false: {guards}"
        )


def test_training_log_keeps_memory_and_combined_front_norms_separate():
    """E16 finding A1: `raw_front_gradient_l2` must stay the memory-branch value.

    The combined guard values are logged under explicit ``combined_*`` keys so the
    training entry can no longer be overwritten by ``keep_details``.
    """
    source = WORKER.read_text()
    assert '"combined_raw_front_gradient_l2": front["raw_front_gradient_l2"]' in source
    assert '"combined_applied_front_gradient_l2": front["applied_front_gradient_l2"]' in source
    assert '"combined_front_applied_gradient_max": front["front_applied_gradient_max"]' in source
    run_memory_node = next(n for n in worker_tree().body
                           if isinstance(n, ast.FunctionDef) and n.name == "run_memory")
    training_src = ast.unparse(run_memory_node)
    assert "raw_front_gradient_l2=raw_front_gradient_l2" in training_src
    assert "entry.update(memory_loss=total," in training_src and "**keep_details" in training_src
    # the combined keys are the ones spread into the log, never the memory-only name
    assert "combined_raw_front_gradient_l2" in source
    probe_src = ast.unparse(next(n for n in worker_tree().body if isinstance(n, ast.FunctionDef)
                                 and n.name == "run_action_preservation_probe"))
    assert "memory_raw_front_gradient_l2" in probe_src


def test_r1_probe_units_match_the_registered_windows():
    fixture = json.loads((ROOT / "tests/fixtures/m2md_pool_manifest.json").read_text())
    windows = ap.preservation_windows(fixture["samples"], fixture["schedule"])
    table = apc.student_units_per_update(windows)
    assert tuple(table[:3]) == mw.PROBE_STUDENT_UNITS
    assert tuple(table[:3]) == (139, 138, 144)


def _probe_args(tmp_path):
    return SimpleNamespace(
        config=ROOT / "configs" / "pilot.yaml", output_dir=tmp_path, experiment_id="e",
        dataset=tmp_path / "d", checkpoint=tmp_path / "c", comparison_report=tmp_path / "r",
        m2l_report=tmp_path / "m", m2l_checkpoint=tmp_path / "k", m2mc_report=tmp_path / "x",
        action_preservation_probe=True,
    )


def test_r1_probe_cli_has_no_scientific_params_and_dispatches(monkeypatch, tmp_path):
    captured = {}

    class Done:
        returncode, stdout, stderr = 1, "", ""

    monkeypatch.setattr(cli.subprocess, "run", lambda cmd, **kw: captured.update(
        cmd=cmd, timeout=kw["timeout"]) or Done())
    monkeypatch.setattr(cli, "project_root", lambda _: tmp_path)
    args = _probe_args(tmp_path)
    cli.train_pilot_command(args)
    assert captured["cmd"][2] == "ainerzero.runtime.memory_worker"
    assert "--action-preservation-probe" in captured["cmd"]
    assert "--action-preservation-fit" not in captured["cmd"]
    assert captured["timeout"] == min(279, cli.load_pilot_config(args.config).budget.max_wall_seconds)

    seen = {}
    monkeypatch.setattr(cli, "train_pilot_command", lambda a: seen.update(vars(a)) or {"status": "completed"})
    required = ["--dataset", "d", "--checkpoint", "c", "--comparison-report", "r", "--m2l-report", "m",
                "--m2l-checkpoint", "k", "--m2mc-report", "x", "--experiment-id", "e"]
    assert cli.main(["probe-action-preserved-memory", *required]) == 0
    assert seen["action_preservation_probe"] is True and not hasattr(seen, "learning_rate")
    for flag in ("--learning-rate", "--relabel-learning-rate", "--local-fit", "--diverse-fit"):
        with pytest.raises(SystemExit):
            cli.main(["probe-action-preserved-memory", *required, flag, "1"] if flag.endswith("rate") else
                     ["probe-action-preserved-memory", *required, flag])


def test_r1_probe_worker_flag_is_exclusive(monkeypatch):
    base = ["w", "--config", "c", "--dataset", "d", "--checkpoint", "k", "--output-dir", "o",
            "--control-db", "b", "--experiment-id", "e", "--action-preservation-probe",
            "--comparison-report", "r", "--m2l-report", "m", "--m2l-checkpoint", "mk",
            "--m2mc-report", "x"]
    for extra in (["--action-preservation-fit"], ["--local-fit"], ["--diverse-fit"], ["--relabel-fit"],
                  ["--relabel-learning-rate", "0.003"]):
        monkeypatch.setattr(sys, "argv", [*base, *extra])
        with pytest.raises(SystemExit):
            mw.main()
    called = {}
    monkeypatch.setattr(mw, "run_action_preservation_probe",
                        lambda *a, **k: called.update(k) or {"status": "failed"})
    monkeypatch.setattr(sys, "argv", base)
    monkeypatch.setattr("builtins.print", lambda *a, **k: None)
    assert mw.main() == 1
    assert called["m2mc_report_path"] == Path("x") and called["comparison_report_path"] == Path("r")
    assert called["m2l_report_path"] == Path("m") and called["m2l_checkpoint_path"] == Path("mk")


def test_r1_probe_runner_saves_no_checkpoint_and_runs_no_evaluation():
    tree = worker_tree()
    probe = next(n for n in tree.body if isinstance(n, ast.FunctionDef)
                 and n.name == "run_action_preservation_probe")
    called = {ast.unparse(n.func).split(".")[-1] for n in ast.walk(probe) if isinstance(n, ast.Call)}
    forbidden = {"save_checkpoint", "evaluate_one_step_memory", "evaluate_predictor",
                 "evaluate_paired_memory", "evaluate_zero_context_inputs", "evaluate_micro_memory",
                 "evaluate_reconstruction", "memory_screen", "local_memory_screen",
                 "compare_strata", "regression_flags", "summarize_relabel_pool"}
    assert not (called & forbidden), sorted(called & forbidden)
    assert "load_checkpoint" in called  # source re-validation only
    text = (ROOT / "src/ainerzero/runtime/memory_worker.py").read_text()
    assert 'checkpoint_saved": False' in text
    assert '"probe-teacher-cache.npz"' in text and '"probe-teacher-cache-manifest.json"' in text
    probe_src = ast.unparse(probe)
    assert 'directory + "/teacher-cache.npz"' not in probe_src
    assert "probe-teacher-cache.npz" in probe_src


def test_r1_probe_cache_binding_is_rejected_by_the_production_check(monkeypatch, tmp_path):
    fixture = json.loads((ROOT / "tests/fixtures/m2md_pool_manifest.json").read_text())

    def records(samples):
        out = {}
        for s in samples:
            rec = out.setdefault(s["episode_id"], {
                "partition": "train", "environment_instance_id": s["environment_instance_id"],
                "public_episode_sha256": s["public_episode_sha256"], "transitions": {}})
            rec["transitions"][s["transition_index"]] = {
                k: s[k] for k in ("target_observation_id", "current_observation_id", "action_request_id",
                                  "public_transition_sha256", "target_tick")}
        return out

    windows = apc.production_windows(fixture["samples"], fixture["schedule"], records(fixture["samples"]))
    (tmp_path / "manifest.json").write_bytes(b'{"schema_version": 1}')
    probe_binding = apc.expected_cache_binding(
        checkpoint_path=tmp_path, windows=windows["windows"], keys=windows["keys"],
        run_id="33333333-3333-4333-8333-333333333333")
    arrays = {"incoming_h": np.zeros((256, 256), np.float32),
              "teacher_logits": np.zeros((256, 2, 8, 256), np.float32),
              "visible_mask": np.ones((256, 8), bool)}
    probe_manifest = ap.teacher_cache_manifest(probe_binding, arrays)
    ap.verify_teacher_cache(probe_manifest, arrays, probe_binding)
    # a later production run has its own run_id, so the probe cache cannot pass as production
    production_binding = dict(probe_binding, run_id="44444444-4444-4444-8444-444444444444")
    with pytest.raises(ValueError, match="binding mismatch"):
        ap.verify_teacher_cache(probe_manifest, arrays, production_binding)
