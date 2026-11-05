import shutil, subprocess, sys, os
from pathlib import Path
REPO = Path("/Users/mac/AinerWorkFlow/AinerZero"); S = Path(sys.argv[1])
D = "src/ainerzero/v9/experiments/s1/data.py"; F = "src/ainerzero/v9/experiments/s1/final_eval.py"
MUT = {
 "M1_marker_not_exclusive": (D, "os.O_CREAT | os.O_EXCL | os.O_WRONLY", "os.O_CREAT | os.O_TRUNC | os.O_WRONLY"),
 "M2_token_not_checked": (D, "        if final_token is not None and _final_token_valid(final_token):\n            return partition", "        if final_token is not None:\n            return partition"),
 "M3_already_read_not_refused": (F, '    if seal.get("already_read"):\n        return _refused(', '    if False:\n        return _refused('),
}
for name, (rel, old, new) in MUT.items():
    root = S / name
    shutil.copytree(REPO / "src", root / "src", ignore=shutil.ignore_patterns("__pycache__"))
    f = root / rel; t = f.read_text(); assert t.count(old) == 1, name; f.write_text(t.replace(old, new))
    env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    env["PYTHONPATH"] = os.pathsep.join([str(root / "src"), str(REPO / "tests/v9/experiments")])
    probe = subprocess.run([str(REPO / ".venv/bin/python"), "-c", "import ainerzero; print(ainerzero.__file__)"], env=env, capture_output=True, text=True, cwd=str(S))
    p = subprocess.run([str(REPO / ".venv/bin/python"), "-m", "pytest", "-q", "-p", "no:cacheprovider", str(REPO / "tests/v9/experiments/test_s1_final_eval.py")], env=env, capture_output=True, text=True, cwd=str(S))
    print(name, "| from mutant:", str(root) in probe.stdout, "| rc", p.returncode, "|", (p.stdout.strip().splitlines() or [""])[-1])
