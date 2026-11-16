"""Read-only AST reproduction of production build_manifest calls and manifest_sha. No repository imports."""
import ast
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Iterable

OUT = Path(__file__).resolve().parents[1]
ROOT = OUT.parents[2]
DEST = OUT / "corrected-check"
DEST.mkdir(exist_ok=True)
SNAP = OUT / "evidence" / "inputs"


def source(rel):
    return (SNAP / rel).read_text()


guard_rel = "src/ainerzero/v9/experiments/s3/run_guard.py"
identity_rel = "reports/V9-S6-PHASE1/prereg_identity.py"
maker_rel = "reports/V9-S6-PHASE1/make_prereg.py"
runner_rel = "reports/V9-S6-PHASE1/run_s6p1.py"
verify_rel = "reports/V9-S6-PHASE1/verify_s6p1.py"
names = {"sha256_file", "_dotted", "_module_file", "_imported_names", "import_closure", "build_manifest"}
tree = ast.parse(source(guard_rel))
functions = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in names]
assert {n.name for n in functions} == names
ns = {"ast": ast, "hashlib": hashlib, "Path": Path, "Iterable": Iterable}
exec(compile(ast.Module(body=functions, type_ignores=[]), guard_rel, "exec"), ns)
gd = SimpleNamespace(build_manifest=ns["build_manifest"])
identity_tree = ast.parse(source(identity_rel))
current = next(n for n in identity_tree.body if isinstance(n, ast.FunctionDef) and n.name == "current_identity")
numerical_call = next(n.value for n in current.body if isinstance(n, ast.Assign) and
                      any(isinstance(t, ast.Name) and t.id == "current" for t in n.targets))
assert ast.unparse(numerical_call.func) == "GD.build_manifest"
numerical = eval(compile(ast.Expression(numerical_call), identity_rel, "eval"),
                 {"GD": gd, "repo": ROOT, "RUNNER_REL": runner_rel, "VERIFY_REL": verify_rel})
pre = json.loads((SNAP / "reports/V9-S6-PHASE1/PREREG-r1.json").read_text())
maker_tree = ast.parse(source(maker_rel))
doc = next(n.value for n in ast.walk(maker_tree) if isinstance(n, ast.Assign) and
           any(isinstance(t, ast.Name) and t.id == "doc" for t in n.targets))
formal_call = next(v for k, v in zip(doc.keys, doc.values) if isinstance(k, ast.Constant) and k.value == "manifest")
assert ast.unparse(formal_call.func) == "GD.build_manifest"
formal = eval(compile(ast.Expression(formal_call), maker_rel, "eval"),
              {"GD": gd, "REPO": ROOT, "RUNNER": ROOT / runner_rel, "VERIFY": ROOT / verify_rel,
               "design": ROOT / pre["design"], "Path": Path, "__file__": str(ROOT / maker_rel),
               "PE": SimpleNamespace(__file__=str(ROOT / "reports/V9-S6-PHASE1/prereg_evidence.py")),
               "PI": SimpleNamespace(__file__=str(ROOT / identity_rel))})
hash_fn = next(n for n in identity_tree.body if isinstance(n, ast.FunctionDef) and n.name == "manifest_sha")
hash_ns = {"hashlib": hashlib, "json": json}
exec(compile(ast.Module(body=[hash_fn], type_ignores=[]), identity_rel, "exec"), hash_ns)
formal_sha = hash_ns["manifest_sha"](formal)
numerical_sha = hash_ns["manifest_sha"](numerical)
removed = sorted(set(formal) - set(numerical))
result = {"status": "PASS", "role": "author-side correction of analysis tool; NOT a frozen-file repair",
          "production_calls": {"formal": {"path": maker_rel, "line": formal_call.lineno, "expression": ast.unparse(formal_call)},
                               "numerical": {"path": identity_rel, "line": numerical_call.lineno, "expression": ast.unparse(numerical_call)},
                               "hash": {"path": identity_rel, "line": hash_fn.lineno, "expression": ast.get_source_segment(source(identity_rel), hash_fn)}},
          "formal_frozen_files": len(formal), "numerical_closure_files": len(numerical),
          "formal_rebuilt_equals_registered_manifest": formal == pre["manifest"],
          "numerical_is_exact_subset": all(formal[k] == v for k, v in numerical.items()),
          "formal_minus_numerical": removed, "formal_46_sha256": formal_sha,
          "numerical_42_sha256": numerical_sha, "registered_code_manifest_sha256": pre["code_manifest_sha256"],
          "code_digest_match": numerical_sha == pre["code_manifest_sha256"],
          "source_sha256": {p: hashlib.sha256((SNAP / p).read_bytes()).hexdigest() for p in [guard_rel, identity_rel, maker_rel]},
          "explanation": "The same original compact JSON encoding applies. The original failure compared the wrong file sets: 46-file formal freeze vs 42-file numerical closure. All frozen files and the production numerical digest match.",
          "preserved_initial_failure": "evidence/analysis1/analysis.stdout.log",
          "execution": "AST-selected pure Python import-closure/hash functions and two build_manifest call expressions; reads source bytes only, no MLX imports, no model work, no git or writes outside delivery"}
assert len(formal) == 46 and len(numerical) == 42
assert formal == pre['manifest'] and result['numerical_is_exact_subset'] and result['code_digest_match']
with (DEST / "RESULTS.json").open('x') as f:
    json.dump(result, f, indent=2, ensure_ascii=False)
    f.write('\n')
print(json.dumps(result, indent=2, ensure_ascii=False))
