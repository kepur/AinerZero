"""新改动的纯 CPU 变异（不导入 MLX）。"""
import json, os, re, shutil, subprocess, sys
from pathlib import Path
W = Path(sys.argv[1]); PY = "/Users/mac/AinerWorkFlow/AinerZero/.venv/bin/python"
G = "src/ainerzero/v9/experiments/s3/run_guard.py"; A = "src/ainerzero/v9/experiments/s3/analysis_p2.py"
T = ["tests/v9/experiments/test_s3_run_guard.py", "tests/v9/experiments/test_s3p2_replay_analysis.py"]
M = [
 ("n01_fullmatch_to_match", G, 're.fullmatch(r"[A-Za-z0-9_-]+", use_id or "")', 're.match(r"[A-Za-z0-9_-]+", use_id or "")'),
 ("n02_allow_slash", G, 're.fullmatch(r"[A-Za-z0-9_-]+", use_id or "")', 're.fullmatch(r"[A-Za-z0-9_/-]+", use_id or "")'),
 ("n03_allow_dot", G, 're.fullmatch(r"[A-Za-z0-9_-]+", use_id or "")', 're.fullmatch(r"[A-Za-z0-9_.-]+", use_id or "")'),
 ("n04_allow_dot_and_slash", G, 're.fullmatch(r"[A-Za-z0-9_-]+", use_id or "")', 're.fullmatch(r"[A-Za-z0-9_./-]+", use_id or "")'),
 ("n05_empty_ok", G, 're.fullmatch(r"[A-Za-z0-9_-]+", use_id or "")', 're.fullmatch(r"[A-Za-z0-9_-]*", use_id or "")'),
 ("n06_dev_old_name", A, '"dev": "s3p2b-dev"', '"dev": "s3p2-dev"'),
 ("n07_final_old_name", A, '"final": "s3p2b-final"', '"final": "s3p2-final"'),
 ("n08_train_renamed", A, '"train": "s3p2-train"', '"train": "s3p2b-train"'),
 ("n09_probe_renamed", A, '"probe": "s3p2-probe"', '"probe": "s3p2b-probe"'),
 ("n10_final_equals_dev", A, '"final": "s3p2b-final"', '"final": "s3p2b-dev"'),
]
res = []
for name, rel, old, new in M:
    d = W / "cpu_mut" / name
    if d.exists(): shutil.rmtree(d)
    d.parent.mkdir(exist_ok=True); (d / "tests/v9/experiments").mkdir(parents=True); shutil.copytree(W / "frozen/src", d / "src")
    for t in T: shutil.copy(W / "frozen" / t, d / t)
    p = d / rel; s = p.read_text(encoding="utf-8"); assert s.count(old) == 1, name; p.write_text(s.replace(old, new), encoding="utf-8")
    subprocess.run([PY, "-c", f"import ast;ast.parse(open({str(p)!r},encoding='utf-8').read())"], check=True)
    r = subprocess.run([PY, "-m", "pytest", *T, "--noconftest", "-q", "-p", "no:cacheprovider", "--tb=line"], cwd=d, env={**os.environ, "PYTHONPATH": str(d / "src"), "PYTHONDONTWRITEBYTECODE": "1"}, capture_output=True, text=True, timeout=200)
    fl = [l.split("::")[-1] for l in r.stdout.splitlines() if l.startswith("FAILED")]
    res.append({"mutant": name, "status": "KILLED" if r.returncode == 1 and fl else ("SURVIVED" if r.returncode == 0 else "ERROR"), "failed": fl[:2]}); print(json.dumps(res[-1], ensure_ascii=False), flush=True); shutil.rmtree(d)
(W / "out/mutants_cpu.json").write_text(json.dumps(res, ensure_ascii=False, indent=1))
