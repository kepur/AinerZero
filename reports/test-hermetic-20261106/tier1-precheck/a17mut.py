import os, sys, subprocess, hashlib, shutil, signal
ISO=sys.argv[1]; conf=os.path.join(ISO,"tests","conftest.py")
orig=open(conf).read(); sha=hashlib.sha256(orig.encode()).hexdigest()
muts={
 "Ma_connect_unguarded": ("        check_hermetic_access(database, \"sqlite3.connect\", root=root, whitelist=whitelist)\n", "        pass\n"),
 "Mb_snapshot_skips_shm": ("def guard_snapshot(root: Path = REAL_REPO_ROOT) -> dict[str, tuple[int, int, int]]:\n", "def guard_snapshot(root: Path = REAL_REPO_ROOT) -> dict[str, tuple[int, int, int]]:\n    return {k:v for k,v in _guard_snapshot_orig(root).items() if not k.endswith('-shm')}\ndef _guard_snapshot_orig(root: Path = REAL_REPO_ROOT) -> dict[str, tuple[int, int, int]]:\n"),
 "Mc_not_installed": ("    sqlite3.connect = guarded_connect\n    if \"sqlite3\" in sys.modules:\n        sys.modules[\"sqlite3\"].connect = guarded_connect\n", "    pass\n"),
}
env=dict(os.environ, PYTHONPATH=os.path.join(ISO,"src"), PYTHONDONTWRITEBYTECODE="1")
def run():
    signal.signal(signal.SIGINT, signal.SIG_DFL)
    r=subprocess.run([ "/Users/mac/AinerWorkFlow/AinerZero/.venv/bin/python","-m","pytest","-q","-p","no:cacheprovider","tests/test_hermetic_guards.py"],cwd=ISO,env=env,capture_output=True,text=True)
    return r.returncode, (r.stdout.strip().splitlines() or [""])[-1]
print("baseline", run())
for name,(a,b) in muts.items():
    assert orig.count(a)==1, (name, orig.count(a))
    open(conf,"w").write(orig.replace(a,b))
    print(name, run())
    open(conf,"w").write(orig)
    assert hashlib.sha256(open(conf).read().encode()).hexdigest()==sha
print("restored ok")
