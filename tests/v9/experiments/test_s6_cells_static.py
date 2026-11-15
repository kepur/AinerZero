"""S6 cells, static (no MLX import): the selection path names nothing that could produce an outcome. DESIGN-r2 §6."""
from __future__ import annotations

import ast
from pathlib import Path

CELLS = Path(__file__).resolve().parents[3] / "src/ainerzero/v9/experiments/s6/cells.py"
SELECTION = ("select", "disagreement", "epinet_spread", "closest_pair", "_per_id", "score_digest")
FORBIDDEN = {"physics", "generate_episode", "make_pool", "make_sigma_pool", "train_worlds", "true_physics", "bounce",
             "sim_labels", "reveal", "revealed_pool", "_simulate", "_outcomes", "_labeller", "candidate_source",
             "candidate_worlds", "make_candidate_pool", "Episode", "steps", "contacts"}


def _functions():
    tree = ast.parse(CELLS.read_text(encoding="utf-8"))
    return {n.name: n for n in tree.body if isinstance(n, ast.FunctionDef)}


def _names(fn):
    out = set()
    for node in ast.walk(fn):
        if isinstance(node, ast.Name):
            out.add(node.id)
        elif isinstance(node, ast.Attribute):
            out.add(node.attr)
    return out


def test_selection_functions_exist():
    assert set(SELECTION) <= set(_functions())


def test_selection_path_names_no_outcome_source():
    fns = _functions()
    for name in SELECTION:
        bad = _names(fns[name]) & FORBIDDEN
        assert not bad, f"{name} references {sorted(bad)}"


def test_select_reads_only_states_and_remaining_from_the_pool_and_runs_sealed():
    fn = _functions()["select"]
    pool_calls = {n.func.attr for n in ast.walk(fn) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                  and isinstance(n.func.value, ast.Attribute) and n.func.value.attr == "cp"}
    assert pool_calls == {"states", "remaining"}
    withs = [n for n in ast.walk(fn) if isinstance(n, ast.With)]
    assert any(isinstance(i.context_expr, ast.Call) and getattr(i.context_expr.func, "id", "") == "sealed"
               for w in withs for i in w.items)


def test_the_seal_covers_the_outcome_sources():
    tree = ast.parse(CELLS.read_text(encoding="utf-8"))
    sealed = next(n for n in tree.body if isinstance(n, ast.Assign) and getattr(n.targets[0], "id", "") == "_SEALED")
    pairs = {(e.elts[0].id if isinstance(e.elts[0], ast.Name) else ast.unparse(e.elts[0]), e.elts[1].value)
             for e in sealed.value.elts}
    want = {("W", "physics"), ("W", "generate_episode"), ("L", "make_pool"), ("L", "make_sigma_pool"),
            ("A", "train_worlds"), ("Mo", "true_physics"), ("Mo", "bounce"), ("S", "sim_labels"),
            ("S.CandidatePool", "_simulate"), ("S.CandidatePool", "reveal")}
    assert pairs == want
