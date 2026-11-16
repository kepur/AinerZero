"""P259 CPU-only review. No model imports, world generation, git mutations or live artifacts.

The archive's builder and guard are executed unchanged except third_party_versions:
that helper normally imports mlx. Here it reads distribution metadata only.
Runner/candidate pure functions are AST-extracted without executing their imports.
All reports below are explicitly SYNTHETIC counterexamples, never real probes.
"""
import ast
import contextlib
import copy
import hashlib
import importlib.abc
import importlib.metadata
import importlib.util
import io
import json
import resource
import sys
import time
from pathlib import Path
from types import SimpleNamespace as NS

OUT = Path(__file__).resolve().parents[1]
ROOT = OUT / "snapshot"
HERE = ROOT / "reports/V9-S6-PHASE1"
RUN_LABEL = sys.argv[1] if len(sys.argv) > 1 else "r2"
CASES = ROOT / ("cpu-cases-" + RUN_LABEL)
CASES.mkdir(exist_ok=True)
sys.dont_write_bytecode = True


class DenyMLX(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == "mlx" or fullname.startswith("mlx."):
            raise RuntimeError("FORBIDDEN MLX IMPORT: " + fullname)


sys.meta_path.insert(0, DenyMLX())


def audit(event, args):
    if event == "open":
        path, mode, flags = args
        if isinstance(path, (str, bytes)) and flags & (1 | 2 | 64 | 512 | 1024):
            if not Path(path).resolve().is_relative_to(OUT):
                raise RuntimeError("WRITE OUTSIDE REVIEW DIRECTORY: " + str(path))


sys.addaudithook(audit)
sys.path.insert(0, str(ROOT / "src"))
spec = importlib.util.spec_from_file_location("reviewed_make_prereg", HERE / "make_prereg.py")
MP = importlib.util.module_from_spec(spec)
spec.loader.exec_module(MP)
GD = MP.GD


def metadata_versions(repo, names):
    result = {}
    for name in names:
        try:
            result[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            result[name] = "metadata-unavailable"
    return result


GD.third_party_versions = metadata_versions  # The only builder seam; not an identity/budget check.
manifest = GD.build_manifest(ROOT, [MP.RUNNER], src_root=ROOT / "src", extra=[MP.VERIFY])
code_sha = hashlib.sha256(json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
arms = ("R", "E", "Z", "T", "P", "G")
sizes = dict(per=3000, rounds=4, steps=2500, pool=60000, cand_worlds=240)
probe = dict(cand_ns="s6p1-pcand", test_ns="s6p1-probe", sizes=sizes,
             reps={a: 1 for a in arms}, worlds=[50, 25], train_cap_s=9000, eval_limit_s=3600)
final = dict(cand_ns="s6p1-cand", test_ns="s6p1-final", sizes=sizes,
             reps={a: 3 if a == "G" else 5 for a in arms}, worlds=[200, 100],
             train_cap_s=21600, eval_limit_s=3600)
base = dict(schema="s6.phase1.eval.v1", set="probe", config=probe,
            sets=dict(probe=probe, final=final), code_manifest_sha256=code_sha, code_dirty=[],
            git_head="a33d34b5cb8d06800f584a0abcfd788d16f80fcb",
            third_party=metadata_versions(ROOT, ("numpy", "mlx")),
            verify=dict(passed=True, replay={a + "-r0": {"passed": True} for a in arms},
                        retrain={a + "-r0-n0": {"passed": True} for a in ("E", "P")}, pools_ok={"0": True}),
            result={"gates": {g: {"passed": False} for g in MP.AN.GATES}},
            train_seconds={a + "-r0": 500 for a in arms}, verify_seconds=100, eval_seconds=100,
            cells_sha256={a + "-r0": "0" * 64 for a in arms}, files_sha256={"errors.npz": "0" * 64})


def run_case(name, data, existing=False):
    ip, op = CASES / (name + "-SYNTHETIC-probe.json"), CASES / (name + "-SYNTHETIC-prereg.json")
    ip.write_text(json.dumps(data, indent=1))
    if existing:
        op.write_text("keeper\n")
    sys.argv = [str(HERE / "make_prereg.py"), "--design", str(ROOT / "reports/V9-S6-DESIGN/DESIGN-r2.md"),
                "--probe", str(ip), "--out", str(op)]
    capture = io.StringIO()
    with contextlib.redirect_stdout(capture):
        try:
            MP.main()
            result = {"accepted": True}
        except (SystemExit, Exception) as exc:
            result = {"accepted": False, "exception": type(exc).__name__, "message": str(exc)}
    result.update(stdout=capture.getvalue().strip(), output_exists=op.exists())
    if result["accepted"]:
        doc = json.loads(op.read_text())
        result["budget"] = doc["budget"]
    print(name, json.dumps(result, ensure_ascii=False))
    return result


results = {}
variants = {"baseline_synthetic_no_artifact_files": base}
d = copy.deepcopy(base); d["result"] = {"valid": False, "gates": {}}; d["verify"] = {"passed": True}
d.pop("cells_sha256"); d.pop("files_sha256"); variants["invalid_incomplete_no_proof"] = d
d = copy.deepcopy(base); d["verify"]["replay"]["E-r0"]["passed"] = False
variants["contradictory_failed_replay"] = d
d = copy.deepcopy(base); d["verify"]["passed"] = "false"; variants["non_boolean_passed"] = d
d = copy.deepcopy(base); d.pop("schema"); d.pop("git_head"); d["third_party"] = {"numpy": "other", "mlx": "other"}
variants["missing_schema_head_other_versions"] = d
d = copy.deepcopy(base); d["train_seconds"] = {a + "-r0": -500 for a in arms}; d["verify_seconds"] = -100; d["eval_seconds"] = -100
variants["negative_times"] = d
d = copy.deepcopy(base); d["train_seconds"] = {a + "-r0": 0 for a in arms}; d["verify_seconds"] = 0; d["eval_seconds"] = 0
variants["zero_times"] = d
d = copy.deepcopy(base); d["train_seconds"].update({a + "-r999": 0 for a in arms})
variants["extra_nonexistent_cells"] = d
d = copy.deepcopy(base); d["sets"]["final"]["train_cap_s"] = 999999
variants["different_final_cap"] = d
for name, field, value in [("reject_wrong_set", "set", "final"), ("reject_verify_false", "verify", {"passed": False}),
                           ("reject_code_sha", "code_manifest_sha256", "0" * 64), ("reject_dirty_flag", "code_dirty", [" M source.py"])]:
    d = copy.deepcopy(base); d[field] = value; variants[name] = d
d = copy.deepcopy(base); d["train_seconds"]["R-r0"] = 100000; variants["reject_over_budget"] = d
d = copy.deepcopy(base); d.pop("train_seconds"); variants["reject_missing_timings"] = d
if RUN_LABEL == "r3":
    d = copy.deepcopy(base); d["verify_seconds"] = float("nan"); variants["reject_nan_timing_late"] = d
    d = copy.deepcopy(base); d["train_seconds"]["R-r0"] = float("inf"); variants["reject_infinite_timing"] = d
    d = copy.deepcopy(base); d["train_seconds"].pop("G-r0"); variants["reject_missing_arm"] = d
    d = copy.deepcopy(base); d["sets"]["probe"]["worlds"] = [0, 0]; variants["reject_zero_worlds"] = d
    d = copy.deepcopy(base); d["verify_seconds"] = 0; d["eval_seconds"] = 0
    d["train_seconds"] = {a + "-r0": (21600 / 1.15 - 450) / 28 for a in arms}
    variants["at_train_cap_equality"] = d
    d = copy.deepcopy(d); d["train_seconds"]["R-r0"] += 0.01
    variants["reject_just_over_train_cap"] = d
for name, data in variants.items():
    results[name] = run_case(name, data)
results["reject_existing_output"] = run_case("reject_existing_output", base, existing=True)

# Exact AST-extracted candidate_source, using encoded inert states instead of any worlds.
import numpy as np
cells_file = ROOT / "src/ainerzero/v9/experiments/s6/cells.py"
tree = ast.parse(cells_file.read_text())
fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "candidate_source")
fake_eps = [NS(n_disks=4, pillars=np.array([[e, 0, 0.5]]),
               steps=[NS(positions=np.array([[e, t], [e+1, t+1]], float),
                         velocities=np.array([[e+2, t+2], [e+3, t+3]], float)) for t in range(100)]) for e in range(6)]
tiny = NS(pool=500)
env = {"np": np, "Sizes": object, "FULL": tiny, "candidate_worlds": lambda ns, k, sizes: fake_eps,
       "pool_seed": lambda ns, k: 8271 + k}
exec(compile(ast.Module(body=[fn], type_ignores=[]), str(cells_file), "exec"), env)
got = env["candidate_source"]("inert-fixture", 0, tiny)
order = got[4]["p"][:, 0, :].astype(int)
picks = np.random.default_rng(8271).choice(600, 500, replace=False)
expected = np.array([(i // 100, i % 100) for i in picks])
adjacent = float(np.mean((order[:-1, 0] == order[1:, 0]) & (np.abs(np.diff(order[:, 1])) == 1)))
results["candidate_cpu"] = {"draw_order_exact": bool(np.array_equal(order, expected)), "unique": len(np.unique(order, axis=0)),
                            "adjacent_share": adjacent, "synthetic_only": True}
print("candidate_cpu", json.dumps(results["candidate_cpu"]))

# Execute the unchanged run_eval prelude only, stop before verification/world generation.
runner_file = HERE / "run_s6p1.py"
rtree = ast.parse(runner_file.read_text())
names = {"run_eval", "cell_dir", "all_cells", "sha", "ledger_used"}
fns = [n for n in rtree.body if isinstance(n, ast.FunctionDef) and n.name in names]
runner_cases = OUT / ("runner-cases-" + RUN_LABEL)
runner_cases.mkdir(exist_ok=True)


class StopBeforeVerification(Exception):
    pass


def stop_verify(*args):
    raise StopBeforeVerification("No model, replay, world generation, scoring or final read executed")


for set_name in ("probe", "final"):
    root = runner_cases / set_name
    (root / "cells").mkdir(parents=True, exist_ok=True)
    cfg = {"reps": {a: 1 for a in arms}, "sizes": NS(rounds=4), "worlds": [50, 25],
           "test_ns": "unused-no-world", "eval_limit_s": 3600}
    for a in arms:
        p = root / "cells" / (a + "-r0"); p.mkdir(); (p / "cell.json").write_text("{}")
    (root / "train-ledger.json").write_text(json.dumps([dict(start=0, last_beat=1, closed=True,
        prereg_sha256="OLD-prereg", code_manifest_sha256="OLD-training-code", third_party={"mlx": "old"})]))
    env = dict(Path=Path, json=json, hashlib=hashlib, time=time, resource=resource, GD=GD,
               SETS={set_name: cfg}, ROOT=runner_cases, LOCK=runner_cases / "fixture.lock", REPO=ROOT,
               REGISTERED_SETS=("final",), DANGLING_CHARGE_S=900,
               C=NS(ARMS=arms, verify_cell_dir=lambda *args: {"seconds": 500}),
               startup_checks=lambda s: ({"final_approval_line": "fixture-approval"}, "NEW-prereg", "new-head", {"mlx": "new"}),
               code_manifest=lambda: manifest, manifest_sha=lambda m: code_sha,
               set_summary=lambda s: probe, independent_verify=stop_verify)
    exec(compile(ast.Module(body=fns, type_ignores=[]), str(runner_file), "exec"), env)
    old_clean = GD.check_git_clean
    GD.check_git_clean = lambda *a: ("new-head", [])  # archive has no git; identity branch itself is unchanged
    try:
        env["run_eval"](NS(set=set_name, approval="fixture-approval" if set_name == "final" else None,
                            report=str(root / "eval-SYNTHETIC.json")), lambda *x: None)
    except Exception as exc:
        results["runner_" + set_name] = {"exception": type(exc).__name__, "message": str(exc),
                                          "report_written": (root / "eval-SYNTHETIC.json").exists()}
        print("runner_" + set_name, json.dumps(results["runner_" + set_name]))
    finally:
        GD.check_git_clean = old_clean

assert results["candidate_cpu"]["draw_order_exact"] and results["candidate_cpu"]["unique"] == 500
assert results["runner_probe"]["exception"] == "StopBeforeVerification"
assert results["runner_final"]["exception"] == "GuardError"
assert all(not results[n]["accepted"] for n in results if n.startswith("reject_"))
assert all(results[n]["accepted"] for n in variants if not n.startswith("reject_"))
assert not any(n == "mlx" or n.startswith("mlx.") for n in sys.modules)
results["no_mlx_imported"] = True
results["metadata_seam"] = metadata_versions(ROOT, ("numpy", "mlx"))
(OUT / ("evidence/cpu-results-" + RUN_LABEL + ".json")).write_text(json.dumps(results, ensure_ascii=False, indent=2))
print("NO_MLX_IMPORTED True; all writes guarded under", OUT)
