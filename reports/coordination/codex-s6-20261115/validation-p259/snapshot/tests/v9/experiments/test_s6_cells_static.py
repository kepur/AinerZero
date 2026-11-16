"""S6 cells, static (no MLX import): the selection path names nothing that could produce an outcome. DESIGN-r2 §6."""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

CELLS = Path(__file__).resolve().parents[3] / "src/ainerzero/v9/experiments/s6/cells.py"
SELECTION = ("select", "disagreement", "epinet_spread", "closest_pair", "_per_id", "score_digest")
FORBIDDEN = {"physics", "generate_episode", "make_pool", "make_sigma_pool", "train_worlds", "true_physics", "bounce",
             "sim_labels", "reveal", "revealed_pool", "_simulate", "_outcomes", "_labeller", "candidate_source",
             "candidate_worlds", "make_candidate_pool", "Episode", "steps", "contacts", "_assemble"}


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


def _closure(fns, roots):
    """The selection functions plus every module-level function they reach by name, transitively."""
    seen, todo = set(), list(roots)
    while todo:
        name = todo.pop()
        if name in seen or name not in fns:
            continue
        seen.add(name)
        todo += [n.id for n in ast.walk(fns[name]) if isinstance(n, ast.Name) and n.id in fns]
    return seen


def test_selection_path_names_no_outcome_source():
    fns = _functions()
    reach = _closure(fns, SELECTION)
    assert set(SELECTION) <= reach and "sealed" in reach
    for name in reach:
        bad = _names(fns[name]) & FORBIDDEN
        assert not bad, f"{name} references {sorted(bad)}"


S6 = CELLS.parent
MODULE_LEVEL_CHECKED = ("cells.py", "sandbox.py", "epinet_mlx.py")


def _module_level_names(tree):
    """Every name and attribute in code that runs at import time: module statements (also nested in if/try/with/for
    blocks), class bodies, decorators, base classes and the default values of function and lambda arguments; not
    function or lambda bodies. Assignment targets in class bodies (dataclass field names) are not counted, their
    values are. The ``_SEALED`` table is skipped."""
    out, stack = set(), list(tree.body)
    while stack:
        node = stack.pop()
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            args = node.args
            stack.extend(list(args.defaults) + [d for d in args.kw_defaults if d is not None])
            stack.extend(getattr(node, "decorator_list", []))
            continue
        if isinstance(node, ast.ClassDef):
            stack.extend(node.decorator_list + node.bases + [k.value for k in node.keywords])
            for stmt in node.body:
                if isinstance(stmt, (ast.Assign, ast.AnnAssign)) and stmt.value is not None:
                    stack.append(stmt.value)
                elif not isinstance(stmt, (ast.Assign, ast.AnnAssign)):
                    stack.append(stmt)
            continue
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "_SEALED" for t in node.targets):
            continue
        if isinstance(node, ast.Name):
            out.add(node.id)
        elif isinstance(node, ast.Attribute):
            out.add(node.attr)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            out |= {a.asname or a.name.split(".")[-1] for a in node.names} | {a.name.split(".")[-1] for a in node.names}
        stack.extend(ast.iter_child_nodes(node))
    return out


@pytest.mark.parametrize("module", MODULE_LEVEL_CHECKED)
def test_no_module_level_alias_of_an_outcome_source(module):
    """A module-level binding such as ``_step = W.physics`` (also inside try/if blocks, also in the sandbox or the
    epinet module) would survive the seal, which patches module attributes."""
    tree = ast.parse((S6 / module).read_text(encoding="utf-8"))
    bad = _module_level_names(tree) & FORBIDDEN
    assert not bad, f"{module}: import-time code references {sorted(bad)}"


def test_module_level_scan_reaches_nested_blocks():
    tree = ast.parse("try:\n    _phys = W.physics\nexcept Exception:\n    pass\ndef f():\n    return W.physics\n")
    assert "physics" in _module_level_names(tree)
    assert "physics" not in _module_level_names(ast.parse("def f():\n    return W.physics\n"))
    assert "physics" in _module_level_names(ast.parse("class C:\n    def __init__(self, _p=W.physics):\n        pass\n"))
    assert "physics" in _module_level_names(ast.parse("class C:\n    step = W.physics\n"))
    assert "physics" in _module_level_names(ast.parse("@deco(W.physics)\ndef f():\n    pass\n"))
    assert "physics" in _module_level_names(ast.parse("f = lambda p=W.physics: p\n"))
    assert "steps" not in _module_level_names(ast.parse("class Sizes:\n    steps: int = 2500\n"))


def test_select_never_aliases_the_pool():
    """Every use of ``.cp`` in select is ``<track>.cp.states()`` or ``<track>.cp.remaining()``; no ``pool = track.cp``."""
    fn = _functions()["select"]
    parents = {child: node for node in ast.walk(fn) for child in ast.iter_child_nodes(node)}
    uses = [n for n in ast.walk(fn) if isinstance(n, ast.Attribute) and n.attr == "cp"]
    assert uses
    for u in uses:
        meth = parents.get(u)
        call = parents.get(meth)
        assert isinstance(meth, ast.Attribute) and meth.attr in ("states", "remaining"), ast.unparse(meth or u)
        assert isinstance(call, ast.Call) and call.func is meth


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
            ("S.CandidatePool", "_simulate"), ("S.CandidatePool", "reveal"), ("S.CandidatePool", "revealed_pool"),
            ("S.CandidatePool", "_assemble")}
    assert pairs == want
