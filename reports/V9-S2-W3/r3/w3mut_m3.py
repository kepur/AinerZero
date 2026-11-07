import hashlib, os, shutil, subprocess, tempfile, json
from pathlib import Path
REPO = Path("/Users/mac/AinerWorkFlow/AinerZero")
iso = Path(tempfile.mkdtemp(prefix="w3iso-", dir=os.environ["S"]))
for n in ("src", "tests"): shutil.copytree(REPO / n, iso / n, symlinks=True)
shutil.copy2(REPO / "pyproject.toml", iso / "pyproject.toml")
LP = "src/ainerzero/v9/experiments/s2/learned_planning.py"; AD = "src/ainerzero/v9/experiments/s2/adapters_mlx.py"
exec(open('/private/tmp/claude-501/-Users-mac-AinerWorkFlow-AinerZero/9ceafe9f-ae1e-4da6-a85d-2438a4c80c0b/scratchpad/w3muts_m3.py').read())
env = dict(os.environ, PYTHONPATH=str(iso / "src"), PYTHONDONTWRITEBYTECODE="1")
def run():
    code = "import signal,os,sys; signal.signal(signal.SIGINT, signal.SIG_DFL); os.execv(sys.executable,[sys.executable,'-m','pytest','-q','-p','no:cacheprovider']+"+repr(TESTS)+")"
    p = subprocess.run([str(REPO/".venv/bin/python"), "-c", code], cwd=iso, env=env, capture_output=True, text=True, timeout=600)
    return p.returncode, (p.stdout.strip().splitlines() or ["?"])[-1]
chk = subprocess.run([str(REPO/".venv/bin/python"), "-c", "import ainerzero.v9.experiments.s2.learned_planning as m; print(m.__file__)"], cwd=iso, env=env, capture_output=True, text=True)
res = {"import": chk.stdout.strip(), "baseline": run()}
for name, (f, a, b) in MUTS.items():
    path = iso / f; orig = path.read_bytes(); sha = hashlib.sha256(orig).hexdigest(); src = orig.decode()
    assert src.count(a) == 1, (name, src.count(a))
    path.write_text(src.replace(a, b, 1)); res[name] = run(); path.write_bytes(orig)
    assert hashlib.sha256(path.read_bytes()).hexdigest() == sha
res["restored"] = run()
print(json.dumps(res, ensure_ascii=False, indent=1))
