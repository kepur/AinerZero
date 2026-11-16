"""P262-sub reviewer mutations: real edits of the production validator in ISOLATED copies only.

usage: python -B mutate_sub.py <base_copy> <work_dir> <out_dir>

<base_copy> is `git archive HEAD src tests pyproject.toml reports/V9-S6-PHASE1 reports/V9-S6-DESIGN` plus the
three reviewed files (exact SHA). For each mutant: APFS clone of the base, exact single-occurrence string
replacement(s) in prereg_evidence.py / make_prereg.py, then the AUTHOR's unchanged test file is run through
run_tests_sub.py (MLX import blocker, PYTHONPATH=<copy>/src, module-origin check). Killed = pytest exit 1 with
at least one FAILED test id, all modules from the copy, no MLX. The mutant source, unified diff and full
pytest log are saved per mutant.
"""
import concurrent.futures as cf
import difflib
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

base, work, out = (Path(a).resolve() for a in sys.argv[1:4])
LIVE = Path("/Users/mac/AinerWorkFlow/AinerZero")
assert not base.is_relative_to(LIVE) and not work.is_relative_to(LIVE)
PY = str(LIVE / ".venv-ainerzero/bin/python")
DRIVER = str(Path(__file__).resolve().parent / "run_tests_sub.py")
H = "reports/V9-S6-PHASE1/prereg_evidence.py"
M = "reports/V9-S6-PHASE1/make_prereg.py"
MUTANTS = [
    ("X1-zero-duration-allowed", H, [("and (value >= 0 if zero else value > 0)", "and (value >= 0 if zero else value >= 0)")]),
    ("X2-report-commit-unchecked", H, [("    for commit in {head, report_head}:", "    for commit in {head}:")]),
    ("X3-cell-pool-link-dropped", H, [("    same(rec['pool_sha256'], pools['0'], 'cell pool SHA')", "    pass  # MUTANT X3")]),
    ("X4-T-R-shared-picks-dropped", H, [("    same(recs['T-r0']['tracks'][0]['picks'], recs['R-r0']['tracks'][0]['picks'], 'T/R selections')", "    pass  # MUTANT X4")]),
    ("X5-final-6h-1h-pins-dropped", H, [("    same(sets['final']['train_cap_s'], 21600.0, 'final training cap')", "    pass  # MUTANT X5a"),
                                        ("    same(sets['final']['eval_limit_s'], 3600, 'final eval cap')", "    pass  # MUTANT X5b")]),
    ("X6-probe-ledger-cap-dropped", H, [("    require(ledger_seconds <= cfg['train_cap_s'], 'actual probe training exceeded cap')", "    pass  # MUTANT X6")]),
    ("X7-pick-range-dropped", H, [("all(type(i) is int and 0 <= i < pool for i in ids)", "all(type(i) is int for i in ids)")]),
    ("X8-prewrite-evidence-recheck-dropped", M, [('    PE.require(not GD.check_manifest(REPO, evidence["files_sha256"]), "evidence changed before output")', "    pass  # MUTANT X8")]),
    ("X9-eval-budget-equality-refused", H, [("est_eval <= final['eval_limit_s']", "est_eval < final['eval_limit_s']")]),
    ("X10-int-accepts-float", H, [('require(type(actual) is int if type(expected) is int else type(actual) in (float, int), f"{label}: numeric type")',
                                   'require(type(actual) in (float, int), f"{label}: numeric type")')]),
    ("X11-first-picks-replay-dropped", H, [("        same(row['first_ok'], True, 'first picks replay')", "        pass  # MUTANT X11")]),
    ("X12-helper-not-frozen", M, [("extra=[design, VERIFY, Path(__file__).resolve(), Path(PE.__file__).resolve()]", "extra=[design, VERIFY, Path(__file__).resolve()]")]),
    ("X13-verify-plus-eval-vs-elapsed-dropped", H, [("require(verify_s + eval_s <= elapsed + .15 and elapsed <= cfg['eval_limit_s']", "require(elapsed <= cfg['eval_limit_s']")]),
    ("X14-ledger-closed-truthy", H, [("        same(row['closed'], True, 'training ledger must be closed')", "        require(row['closed'], 'training ledger must be closed')")]),
    ("X15-git-status-clean-dropped", H, [("    require(not git('status', '--porcelain', '--', *code), 'numerical source files are not committed')", "    pass  # MUTANT X15")]),
]


def run(m):
    name, rel, reps = m
    copy = work / name
    subprocess.run(["rm", "-rf", str(copy)], check=True)
    subprocess.run(["cp", "-Rc", str(base), str(copy)], check=True)
    target = copy / rel
    src = target.read_text()
    new = src
    for old, rep in reps:
        assert new.count(old) == 1, (name, old, new.count(old))
        new = new.replace(old, rep)
    target.write_text(new)
    d = out / name
    d.mkdir(parents=True, exist_ok=False)
    (d / Path(rel).name).write_text(new)
    (d / "diff.txt").write_text("".join(difflib.unified_diff(src.splitlines(True), new.splitlines(True), "a/" + rel, "b/" + rel)))
    cmd = [PY, "-B", DRIVER, str(copy), str(work / (name + "-bt"))]
    env = {**os.environ, "PYTHONPATH": str(copy / "src"), "PYTHONDONTWRITEBYTECODE": "1"}
    r = subprocess.run(cmd, cwd=copy, env=env, capture_output=True, text=True)
    log = r.stdout + r.stderr
    (d / "pytest.log").write_text(log)
    failed = sorted(set(re.findall(r"^FAILED (\S+)", log, re.M)))
    summary = [ln for ln in log.splitlines() if re.search(r"\d+ (passed|failed)", ln)]
    return {"mutant": name, "file": rel, "replacements": reps, "argv": cmd, "returncode": r.returncode,
            "summary": summary[-1] if summary else None, "failed_tests": failed,
            "all_from_copy": "ALL_FROM_COPY True" in log, "mlx_imported": "MLX_IN_SYS_MODULES False" not in log,
            "killed": r.returncode == 1 and bool(failed) and "ALL_FROM_COPY True" in log and "MLX_IN_SYS_MODULES False" in log,
            "mutant_sha256": hashlib.sha256(new.encode()).hexdigest()}


out.mkdir(parents=True, exist_ok=False)
with cf.ThreadPoolExecutor(4) as ex:
    results = list(ex.map(run, MUTANTS))
for row in results:
    print(json.dumps({k: row[k] for k in ("mutant", "returncode", "summary", "killed", "all_from_copy", "mlx_imported")}), flush=True)
    for t in row["failed_tests"]:
        print("   FAILED", t, flush=True)
(out / "results.json").write_text(json.dumps(results, indent=1, ensure_ascii=False))
