#!/usr/bin/env python3
"""Author-side CPU evidence check. Never imports exploration scripts or repository modules.

Usage: .venv/bin/python -B reports/V9-S6P2-DESIGN/r1-author-check/evidence/author_check.py prepare|test|analyze
All writes stay below the fixed delivery directory. Existing evidence is never overwritten.
"""
import ast
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import subprocess
import sys
import time

OUT = Path(__file__).resolve().parents[1]
ROOT = OUT.parents[2]
EVIDENCE = OUT / "evidence"
PREREG = "reports/V9-S6-PHASE1/PREREG-r1.json"
EXPLORE = "reports/V9-S6P2-DESIGN/tier1-explore/"
DESIGN = "reports/V9-S6P2-DESIGN/DESIGN-r1.md"
RESULTS = EXPLORE + "results-p2i.json"
LOG = EXPLORE + "run-p2i.log"
SCRIPT = EXPLORE + "explore_p2f.py"
TEST = "tests/v9/experiments/test_s6_world_b.py"
WORLD = "src/ainerzero/v9/experiments/s6/world_b.py"


def digest(data):
    return hashlib.sha256(data).hexdigest()


def save_json(path, data):
    with path.open("x", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False, allow_nan=False)
        f.write("\n")


def frozen_check(pre):
    rows = []
    for rel, expected in sorted(pre["manifest"].items()):
        p = ROOT / rel
        actual = digest(p.read_bytes()) if p.is_file() else None
        rows.append({"path": rel, "absolute_path": str(p), "expected_sha256": expected,
                     "actual_sha256": actual, "match": actual == expected})
    canonical = json.dumps(pre["manifest"], sort_keys=True, separators=(",", ":")).encode()
    # make_prereg.py: full freeze additionally binds the design and three builder/helper files.
    # code_manifest_sha256 belongs to current_identity's numerical 42-file manifest.
    excluded = {pre["design"], "reports/V9-S6-PHASE1/make_prereg.py",
                "reports/V9-S6-PHASE1/prereg_evidence.py", "reports/V9-S6-PHASE1/prereg_identity.py"}
    numerical = {k: v for k, v in pre["manifest"].items() if k not in excluded}
    numerical_sha = digest(json.dumps(numerical, sort_keys=True, separators=(",", ":")).encode())
    return {"prereg_path": str(ROOT / PREREG), "manifest_key": "manifest", "file_count": len(rows),
            "matches": sum(r["match"] for r in rows), "files": rows,
            "registered_manifest_sha256": pre["code_manifest_sha256"],
            "computed_manifest_sha256": digest(canonical),
            "numerical_manifest_count": len(numerical), "numerical_manifest_sha256": numerical_sha,
            "excluded_from_numerical_manifest": sorted(excluded),
            "manifest_digest_match": numerical_sha == pre["code_manifest_sha256"]}


def snapshot_read(rel):
    return (EVIDENCE / "inputs" / rel).read_text(encoding="utf-8")


def prepare():
    pre = json.loads((ROOT / PREREG).read_text())
    paths = set(pre["manifest"]) | {PREREG, DESIGN, RESULTS, LOG, SCRIPT, TEST, WORLD,
        EXPLORE + "explore_p2a.py", "AGENTS.md", "README.md", "COORDINATION.md", "AGENT_TASKS.md", "RESEARCH_LOG.md",
        "pyproject.toml", "tests/conftest.py", "tests/v9/experiments/conftest.py", "tests/v9/experiments/s1_testkit.py",
        "src/ainerzero/__init__.py", "src/ainerzero/v9/__init__.py", "src/ainerzero/v9/experiments/__init__.py"}
    records = []
    for rel in sorted(paths):
        data = (ROOT / rel).read_bytes()
        target = EVIDENCE / "inputs" / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("xb") as f:
            f.write(data)
        records.append({"path": rel, "absolute_path": str(ROOT / rel), "sha256": digest(data), "bytes": len(data)})
    save_json(EVIDENCE / "inputs-before.json", {"utc": datetime.now(timezone.utc).isoformat(), "files": records})
    save_json(EVIDENCE / "frozen-before.json", frozen_check(pre))
    git = subprocess.run(["git", "status", "--porcelain=v1", "--untracked-files=all"], cwd=ROOT, capture_output=True, env={**os.environ, "GIT_OPTIONAL_LOCKS": "0"})
    (EVIDENCE / "git-status-before.txt").write_bytes(git.stdout)
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True)
    save_json(EVIDENCE / "workspace-before.json", {"git_head": head.stdout.strip(), "git_head_rc": head.returncode,
        "status_rc": git.returncode, "scope": "P269 auxiliary author-side check; no task claim or independent acceptance"})
    print("Prepared input snapshots and 46-file freeze check.")


def run_test():
    argv = [".venv/bin/python", "-m", "pytest", TEST, "-q"]
    env = os.environ.copy()
    override = {"PYTHONDONTWRITEBYTECODE": "1", "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
        "PYTEST_ADDOPTS": "-o cache_dir=" + str(OUT / "pytest-cache") + " --basetemp=" + str(OUT / "pytest-tmp") + " -o log_file=" + str(OUT / "pytest.log"),
        "PYTHONPATH": str(EVIDENCE / "guard") + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else ""),
        "TMPDIR": str(OUT / "tmp")}
    (OUT / "tmp").mkdir(exist_ok=True)
    env.update(override)
    started = datetime.now(timezone.utc).isoformat()
    t = time.monotonic()
    with (EVIDENCE / "pytest.stdout.log").open("xb") as stdout, (EVIDENCE / "pytest.stderr.log").open("xb") as stderr:
        p = subprocess.run(argv, cwd=ROOT, env=env, stdout=stdout, stderr=stderr)
    with (EVIDENCE / "pytest.rc.txt").open("x") as f:
        f.write(str(p.returncode) + "\n")
    save_json(EVIDENCE / "pytest-command.json", {"argv": argv, "cwd": str(ROOT), "started_utc": started,
        "finished_utc": datetime.now(timezone.utc).isoformat(), "elapsed_s": time.monotonic() - t,
        "returncode": p.returncode, "environment_overrides": override,
        "reason": "Keep caches, temporary files, and every Python-audited write inside delivery; block MLX before tests; disable external pytest plugin autoload."})
    print((EVIDENCE / "pytest.stdout.log").read_text(), end="")
    print((EVIDENCE / "pytest.stderr.log").read_text(), end="", file=sys.stderr)
    print("pytest rc:", p.returncode)


def analyze():
    data = json.loads(snapshot_read(RESULTS))
    arms = ["O+", "U+", "Q+", "R+", "W+"]
    errors = []
    checks = []
    def check(name, ok, detail=None):
        row = {"check": name, "pass": bool(ok), "detail": detail}
        checks.append(row)
        if not ok:
            errors.append(row)
    check("five arms exactly", set(data["arms"]) == set(arms), list(data["arms"]))
    logged = {}
    for lineno, line in enumerate(snapshot_read(LOG).splitlines(), 1):
        match = re.match(r"^([OUQRW]\+) r(\d+) picks ring ([\d.]+) big ([\d.]+) tiny ([\d.]+) \| (.*)$", line)
        if not match:
            continue
        arm, rnd, ring, big, tiny, tail = match.groups()
        key = (arm, int(rnd))
        check("unique log row " + str(key), key not in logged)
        vals = {"picks.ring": ring, "picks.big_world": big, "picks.tiny_world": tiny}
        vals.update(dict(re.findall(r"\b(H|D_B|all_B|D_A|free_A|all_A)=(-?[\d.]+)", tail)))
        logged[key] = {"line": lineno, "values": vals, "raw": line}
    check("20 logged rows", len(logged) == 20, len(logged))
    comparisons = []
    mean_checks = []
    round_table = []
    for arm in arms:
        rows = data["arms"][arm]
        check(arm + " rounds 0..3", [r["round"] for r in rows] == list(range(4)))
        for row in rows:
            rnd = row["round"]
            log = logged[(arm, rnd)]
            record = {"arm": arm, "round_zero_based": rnd, "log_line": log["line"], "picks": row["picks"],
                      **{k: row[k] for k in ("H", "D_A", "all_A")}}
            round_table.append(record)
            for key, literal in log["values"].items():
                val = row["picks"][key.split(".")[1]] if key.startswith("picks.") else row[key]
                decimals = len(literal.split(".")[1])
                ok = format(val, "." + str(decimals) + "f") == literal
                comparisons.append({"arm": arm, "round_zero_based": rnd, "field": key, "json_value": val,
                    "log_literal": literal, "decimals": decimals, "absolute_difference": abs(val - float(literal)),
                    "half_log_unit": 0.5 * 10 ** (-decimals), "pass": ok})
            check(arm + " per_net count r" + str(rnd), len(row["per_net"]) == 3)
            for key in row["per_net"][0]:
                computed = math.fsum(net[key] for net in row["per_net"]) / len(row["per_net"])
                ok = math.isclose(computed, row[key], rel_tol=0, abs_tol=1e-14)
                mean_checks.append({"arm": arm, "round_zero_based": rnd, "field": key,
                    "per_net_mean": computed, "reported": row[key], "pass": ok})
    check("all log numeric fields match their printed precision", all(r["pass"] for r in comparisons), len(comparisons))
    check("all per-net means match JSON aggregate", all(r["pass"] for r in mean_checks), len(mean_checks))
    first = data["arms"]["O+"][0]
    # Layout diagnostics only exist for O; compare everything else, including all per-network metrics.
    common = {k: v for k, v in first.items() if k != "layouts"}
    first_equal = {a: {k: v for k, v in data["arms"][a][0].items() if k != "layouts"} == common for a in arms}
    check("first round exact equality (all metrics, picks, per_net; excludes O-only layouts)", all(first_equal.values()), first_equal)
    per = data["config"]["per"]
    counts = []
    for r in round_table:
        for key, value in r["picks"].items():
            scaled = value * per
            counts.append({"arm": r["arm"], "round_zero_based": r["round_zero_based"], "field": key,
                "count": round(scaled), "fraction": value, "pass": 0 <= value <= 1 and abs(scaled - round(scaled)) < 1e-9})
    check("pick fractions consistent with integer counts / per", all(c["pass"] for c in counts), len(counts))
    h = {a: data["arms"][a][-1]["H"] for a in arms}
    diffs = {a: h["O+"] - h[a] for a in arms if a != "O+"}
    go = (h["O+"] - h["R+"]) - 0.5 * (h["W+"] - h["R+"])
    decoys = {}
    for a in arms:
        vals = [r["picks"]["tiny_world"] for r in data["arms"][a][1:4]]
        decoys[a] = {"rounds_2_to_4_fractions": vals, "mean": math.fsum(vals) / 3,
            "pooled_count": sum(round(v * per) for v in vals), "pooled_denominator": 3 * per}
    pure_imports = {}
    for rel in (TEST, WORLD, "src/ainerzero/v9/experiments/s4/world.py", "src/ainerzero/v9/experiments/s6/sandbox.py"):
        tree = ast.parse(snapshot_read(rel))
        imports = []
        for n in ast.walk(tree):
            if isinstance(n, ast.Import):
                imports.extend({"line": n.lineno, "module": x.name} for x in n.names)
            elif isinstance(n, ast.ImportFrom):
                imports.append({"line": n.lineno, "module": n.module, "names": [x.name for x in n.names]})
        pure_imports[rel] = imports
    check("static test/world/sandbox/world-A imports contain no MLX", not any("mlx" in (i["module"] or "") for v in pure_imports.values() for i in v))
    script = snapshot_read(SCRIPT)
    tree = ast.parse(script)
    decoy_assignments = [ast.get_source_segment(script, n) for n in ast.walk(tree)
        if isinstance(n, ast.Assign) and any(ast.unparse(t).startswith("tiny[") for t in n.targets)]
    check("tiny_world combines tiny and large decoys", any("B.TINY_RADIUS" in x and "B.LARGE_RADIUS" in x for x in decoy_assignments), decoy_assignments)
    env_config = {}
    for n in tree.body:
        if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id in {"CAND_NS", "POOL", "CAND_WORLDS", "N_BIG", "N_TINY", "N_LARGE"} for t in n.targets):
            env_config[ast.unparse(n.targets[0])] = ast.get_source_segment(script, n.value)
    pre = json.loads(snapshot_read(PREREG))
    freeze = frozen_check(pre)
    save_json(EVIDENCE / "frozen-after.json", freeze)
    check("phase1 frozen files unchanged", freeze["file_count"] == 46 and freeze["matches"] == 46, freeze["matches"])
    check("phase1 manifest canonical digest matches", freeze["manifest_digest_match"])
    before = json.loads((EVIDENCE / "inputs-before.json").read_text())
    after = []
    for row in before["files"]:
        p = ROOT / row["path"]
        actual = digest(p.read_bytes()) if p.is_file() else None
        after.append({"path": row["path"], "before_sha256": row["sha256"], "after_sha256": actual, "unchanged": actual == row["sha256"]})
    save_json(EVIDENCE / "inputs-after.json", after)
    changes = [r for r in after if not r["unchanged"]]
    guard = json.loads((EVIDENCE / "pytest-guard.json").read_text())
    command = json.loads((EVIDENCE / "pytest-command.json").read_text())
    check("CPU pytest rc=0", command["returncode"] == 0)
    check("MLX never imported or attempted", guard["guard_active"] and not guard["loaded_mlx_modules"] and not guard["blocked_mlx_imports"])
    check("no test write outside author delivery", not guard["blocked_writes"])
    placeholders = [{"line": i, "text": s} for i, s in enumerate(snapshot_read(DESIGN).splitlines(), 1) if "I_ROUND_" in s]
    findings = []
    attempt1 = json.loads((EVIDENCE / "attempt1" / "pytest-command.json").read_text())
    findings.append({"severity": "harness_failure_preserved", "detail": "Initial test launch exited 3 before test execution: the strict write guard rejected pytest's default /dev/null logging sink. Retry explicitly routes pytest log_file into the delivery directory; no repository code or tests changed.", "evidence": "evidence/attempt1/", "returncode": attempt1["returncode"]})
    if placeholders:
        findings.append({"severity": "delivery_incomplete", "path": DESIGN, "detail": "I-round summary/detail placeholders still present in inspected design snapshot", "locations": placeholders})
    findings.append({"severity": "provenance_limit", "detail": "results config records only per/rounds/steps/lr. DESIGN-r1.md line 131 supplies historical command and env (600/60/30/30, s6x-p2i-cand), but these and historical input hashes are not embedded in results-p2i.json or run-p2i.log. Current SHA identifies this check's snapshot, not proven historical execution bytes; no pool regeneration was performed."})
    findings.append({"severity": "checker_correction_preserved", "detail": "Initial analysis incorrectly compared the full 46-file manifest digest to code_manifest_sha256. Read-only tracing of make_prereg.py:66-68 and prereg_identity.py:138-153 shows code_manifest_sha256 binds the numerical 42-file subset. Correct subset matches; all 46 individual frozen SHA values also match. Initial analysis and script retained in evidence/analysis1; no repository defect or source repair."})
    if changes:
        findings.append({"severity": "shared_workspace_drift", "detail": "Files changed externally during check; analysis uses saved before snapshots.", "files": changes})
    for err in errors:
        findings.append({"severity": "failed_check", **err})
    metrics = {"schema": "s6p2-r1-author-check-v1", "role": "auxiliary author-side CPU delivery check, NOT independent design acceptance", "task_owner": "P269 codex (no new claim)",
        "created_utc": datetime.now(timezone.utc).isoformat(), "config": {"recorded_results": data["config"],
        "source_expressions_not_historical_env": env_config, "design_declared_candidate_worlds": {"total": 600, "big": 60, "tiny": 30, "large": 30},
        "candidate_namespace_design_declared": "s6x-p2i-cand", "historical_env_source": "DESIGN-r1.md:131 (not embedded in original results/log)", "pool_size_source_and_log": 60000, "networks_per_arm": 3,
        "start_path_source": "artifacts/v9/s6/phase1/probe/cells/E-r0/r3-n{j}.safetensors", "old_namespace_source": "s6p1-pcand",
        "test_namespaces_source": ["s6x-p2a-testB", "s6x-p2a-testA"], "test_worlds_each_source": 30,
        "batch_size_source": 256, "exploration_floor_O_source": "per//5 = 300 of 1500 (20%) after first round",
        "replay_source": "all + arms use old pool on odd t, new pool on even t; 1000 steps/network/round"},
        "tests": command, "initial_test_attempt": attempt1, "checks": checks, "failed_checks": errors, "rounds": round_table,
        "log_comparisons": comparisons, "per_net_aggregate_checks": mean_checks, "pick_counts": counts,
        "first_round_exact_equal": first_equal, "final_H": h, "final_H_difference_O_minus": diffs,
        "GO": {"formula": "(H(O+)-H(R+))-0.5*(H(W+)-H(R+))", "value": go,
            "confidence_interval": None, "formal_gate_accepted": False, "reason": "one exploration repeat; point value only"},
        "decoy_rounds_2_to_4": decoys, "tiny_world_semantics": "both tiny (0.15-0.25) and large (0.85-0.95) decoy worlds, not tiny-only",
        "static_imports": pure_imports, "pytest_guard": guard, "phase1_frozen": freeze,
        "input_files": before["files"], "input_changes_during_check": changes, "findings": findings,
        "not_performed": ["MLX imports", "model load/inference/training", "exploration rerun", "checkpoint or final artifact read", "design acceptance", "source/test/design fixes", "git add/commit/push", "Relay card mutation"],
        "model_budget_reserved": 0, "model_work_completed": 0}
    save_json(OUT / "metrics.json", metrics)
    save_json(EVIDENCE / "numeric-comparison.json", {"log": comparisons, "aggregate": mean_checks, "pick_counts": counts})
    with (EVIDENCE / "citations.txt").open("x") as f:
        for rel in (DESIGN, SCRIPT, EXPLORE + "explore_p2a.py", WORLD, TEST, LOG):
            f.write("\n" + str(ROOT / rel) + "\n")
            for i, line in enumerate(snapshot_read(rel).splitlines(), 1):
                f.write(f"{i:4d} {line}\n")
    git = subprocess.run(["git", "status", "--porcelain=v1", "--untracked-files=all"], cwd=ROOT, capture_output=True, env={**os.environ, "GIT_OPTIONAL_LOCKS": "0"})
    (EVIDENCE / "git-status-after.txt").write_bytes(git.stdout)
    print(json.dumps({"failed_checks": errors, "log_fields": len(comparisons), "per_net_means": len(mean_checks),
        "final_H": h, "O_minus": diffs, "GO": go, "decoys": decoys, "frozen": [freeze["matches"], freeze["file_count"]],
        "input_changes": changes, "findings": findings}, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    {"prepare": prepare, "test": run_test, "analyze": analyze}[sys.argv[1]]()
