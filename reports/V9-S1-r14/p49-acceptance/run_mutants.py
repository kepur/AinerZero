import shutil, subprocess, sys, os
from pathlib import Path
REPO = Path("/Users/mac/AinerWorkFlow/AinerZero")
S = Path(sys.argv[1])
W = "src/ainerzero/v9/experiments/s1/worker.py"
P = "src/ainerzero/v9/experiments/s1/prereg.py"
MUTANTS = {
 "M1_train_guard_removed": (W, "            if inherited is not None:\n                report.update(", "            if False:\n                report.update("),
 "M2_run_id_check_removed": (W, '    if run.run_id != cell["source_run_id"]:', "    if False:"),
 "M3_sha_check_removed": (W, '    if binding["final"]["sha256"] != cell["params_sha256"]:', "    if False:"),
 "M4_trust_any_section": (W, "    if expected is None or json.loads(json.dumps(section)) != json.loads(json.dumps(expected)):\n        return None", "    if False:\n        return None"),
 "M5_validate_skips_inheritance": (P, "    reasons.extend(_inheritance_reasons(document))\n", ""),
}
rows = {}
for name, (rel, old, new) in MUTANTS.items():
    root = S / name
    shutil.copytree(REPO / "src", root / "src", ignore=shutil.ignore_patterns("__pycache__"))
    f = root / rel
    t = f.read_text()
    assert t.count(old) == 1, (name, t.count(old))
    f.write_text(t.replace(old, new))
    env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    env["PYTHONPATH"] = os.pathsep.join([str(root / "src"), str(REPO / "tests/v9/experiments")])
    probe = subprocess.run([str(REPO / ".venv/bin/python"), "-c", "import ainerzero,sys; print(ainerzero.__file__)"], env=env, capture_output=True, text=True, cwd=str(S))
    p = subprocess.run([str(REPO / ".venv/bin/python"), "-m", "pytest", "-q", "-p", "no:cacheprovider",
                        str(REPO / "tests/v9/experiments/test_s1_r14_registration.py")], env=env, capture_output=True, text=True, cwd=str(S))
    tail = (p.stdout.strip().splitlines() or [""])[-1]
    rows[name] = {"imported_from": probe.stdout.strip(), "rc": p.returncode, "tail": tail}
    print(name, "| from mutant:", str(root) in probe.stdout, "| rc", p.returncode, "|", tail)
before = {p.name: p.read_bytes() for p in (REPO / "src/ainerzero/v9/experiments/s1").glob("*.py")}
print("repo untouched check computed over", len(before), "files")
