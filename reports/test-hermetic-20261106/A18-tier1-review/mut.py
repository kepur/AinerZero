import hashlib, os, shutil, signal, subprocess, sys, tempfile, json
from pathlib import Path
REPO = Path("/Users/mac/AinerWorkFlow/AinerZero")
iso = Path(tempfile.mkdtemp(prefix="a18iso-", dir=os.environ["S"]))
for n in ("src", "tests"):
    shutil.copytree(REPO / n, iso / n, symlinks=True)
shutil.copy2(REPO / "pyproject.toml", iso / "pyproject.toml")
conf = iso / "tests" / "conftest.py"
orig = conf.read_bytes(); orig_sha = hashlib.sha256(orig).hexdigest()
assert orig_sha == hashlib.sha256((REPO/"tests/conftest.py").read_bytes()).hexdigest()
MUTS = {
 "X1_fd_unresolved": ("    if isinstance(target, int):\n        try:", "    if isinstance(target, int):\n        return None\n        try:"),
 "X2_file_uri_unparsed": ('    if target_str.startswith("file:"):\n        target_str = urlparse(target_str).path\n', ""),
 "X3_patterns_drop_v9_sqlite": ('    "artifacts/v9/**/control.sqlite3*",\n    "artifacts/v9/s1/**/*.sqlite3*",\n', ""),
 "X4_session_enforcement_off": ("    assert not diff, (", "    assert True or not diff, ("),
 "X5_guards_inactive": ("_hermetic_guards_active = True\n", "_hermetic_guards_active = False\n"),
}
env = dict(os.environ, PYTHONPATH=str(iso / "src"), PYTHONDONTWRITEBYTECODE="1")
def run():
    code = ("import signal,os,sys; signal.signal(signal.SIGINT, signal.SIG_DFL); "
            "os.execv(sys.executable,[sys.executable,'-m','pytest','-q','-p','no:cacheprovider','tests/test_hermetic_guards.py'])")
    p = subprocess.run([str(REPO/".venv/bin/python"), "-c", code], cwd=iso, env=env, capture_output=True, text=True, timeout=600)
    return p.returncode, p.stdout.strip().splitlines()[-1] if p.stdout.strip() else p.stderr[-300:]
# import resolution check
chk = subprocess.run([str(REPO/".venv/bin/python"), "-c", "import sys; sys.path.insert(0,'tests'); import ainerzero, conftest; print(ainerzero.__file__); print(conftest.__file__)"], cwd=iso, env=env, capture_output=True, text=True)
print("import:", chk.stdout.strip().replace("\n"," | "), chk.stderr[-200:])
res = {"iso": str(iso), "baseline": run()}
for name, (a, b) in MUTS.items():
    src = orig.decode()
    assert src.count(a) == 1, (name, src.count(a))
    conf.write_text(src.replace(a, b, 1))
    res[name] = run()
    conf.write_bytes(orig)
    assert hashlib.sha256(conf.read_bytes()).hexdigest() == orig_sha
res["restored"] = run()
print(json.dumps(res, ensure_ascii=False, indent=1))
