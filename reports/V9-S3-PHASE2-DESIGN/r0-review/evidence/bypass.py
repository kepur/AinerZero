"""run_guard 对抗实验。全部在临时目录，真实 artifacts 不碰。"""
import fcntl, importlib, json, multiprocessing as mp, os, shutil, subprocess, sys, tempfile, time, types
from pathlib import Path
from ainerzero.v9.experiments.s3 import run_guard as G
PY = sys.executable
RG = Path(G.__file__).resolve()
T = Path(tempfile.mkdtemp(dir=sys.argv[1]))
OUT = {}
def rec(k, v):
    OUT[k] = v; print(k, "::", json.dumps(v, ensure_ascii=False, default=str), flush=True)
ctx = mp.get_context("fork")
def race_worker(i, ledger, lockpath, barrier, q):
    barrier.wait()
    try:
        with G.RunLock(lockpath) as l:
            G.consume_dev_use(l, ledger, f"dev{i}", "race")
        q.put("ok")
    except G.GuardError as e:
        q.put("refused")
def race(same_lock, rounds=40, n=6):
    over = 0; maxok = 0; lens = []
    for r in range(rounds):
        d = T / f"race{same_lock}{r}"; d.mkdir(); ledger = d / "uses.json"
        b = ctx.Barrier(n); q = ctx.Queue()
        ps = [ctx.Process(target=race_worker, args=(i, ledger, d / ("shared.lock" if same_lock else f"own{i}.lock"), b, q)) for i in range(n)]
        [p.start() for p in ps]; res = [q.get(timeout=30) for _ in ps]; [p.join() for p in ps]
        ok = res.count("ok"); maxok = max(maxok, ok); over += ok > 2; lens.append(len(json.loads(ledger.read_text())))
    return {"rounds": rounds, "procs": n, "rounds_with_more_than_2_successes": over, "max_successes_in_a_round": maxok, "ledger_len_seen": sorted(set(lens))}
rec("B1a_shared_lock_control", race(True))
rec("B1b_each_process_own_lock_file", race(False))
# 持锁判断
d = T / "b2"; d.mkdir(); p = d / "shared.lock"; other = d / "other.lock"
holder = p.open("a+"); fcntl.flock(holder, fcntl.LOCK_EX | fcntl.LOCK_NB)
try:
    with G.RunLock(other) as l:
        G.consume_dev_use(l, d / "a.json", "dev1", "shared lock busy, other file held")
    rec("B2a_other_lock_file_passes_while_shared_is_busy", json.loads((d / "a.json").read_text())[0]["id"])
finally:
    holder.close()
l = G.RunLock(p); l._fh = object()
G.consume_dev_use(l, d / "b.json", "dev1", "forged")
rec("B2b_forged_attribute_passes", l.held)
with G.RunLock(p) as l:
    fcntl.flock(l._fh, fcntl.LOCK_UN)
    probe = p.open("a+"); fcntl.flock(probe, fcntl.LOCK_EX | fcntl.LOCK_NB); probe.close()
    rec("B2c_held_stays_true_after_os_unlock", l.held)
# 删锁文件后两人同时持有
d = T / "b3"; d.mkdir(); p = d / "lk"
a = G.RunLock(p).__enter__(); os.unlink(p); b = G.RunLock(p).__enter__()
rec("B3_unlink_then_two_holders", {"a_held": a.held, "b_held": b.held, "same_inode": os.fstat(a._fh.fileno()).st_ino == os.fstat(b._fh.fileno()).st_ino})
b.__exit__(); a.__exit__()
# .pyc 绕过
def tiny(root):
    src = root / "src"; pkg = src / "ainerzero" / "sub"; pkg.mkdir(parents=True)
    (src / "ainerzero/__init__.py").write_text(""); (pkg / "__init__.py").write_text("")
    return src, pkg
d = T / "b4"; d.mkdir(); src, pkg = tiny(d); gate = pkg / "gate.py"; gate.write_text("THRESHOLD = 0.05\n")
entry = d / "run.py"; entry.write_text("from ainerzero.sub import gate\n")
manifest = G.build_manifest(d, [entry], src_root=src, extra=[entry])
now = int(time.time()) - 500
gate.write_text("THRESHOLD = 0.50\n"); os.utime(gate, (now, now))
env = {k: v for k, v in os.environ.items() if k not in ("PYTHONDONTWRITEBYTECODE", "PYTHONPYCACHEPREFIX")}; env["PYTHONPATH"] = str(src)
subprocess.run([PY, "-c", "import ainerzero.sub.gate"], env=env, check=True)
gate.write_text("THRESHOLD = 0.05\n"); os.utime(gate, (now, now))
chk = f'''
import importlib.util as u, json, sys
s = u.spec_from_file_location("rg", {str(RG)!r}); G = u.module_from_spec(s); sys.modules["rg"] = G; s.loader.exec_module(G)
from pathlib import Path
from ainerzero.sub import gate
m = json.loads({json.dumps(json.dumps(manifest))})
print(json.dumps({{"THRESHOLD_seen_at_run": gate.THRESHOLD, "check_manifest": G.check_manifest(Path({str(d)!r}), m), "check_loaded_modules": G.check_loaded_modules(Path({str(d)!r}), m), "source_on_disk": Path({str(gate)!r}).read_text().strip()}}))
'''
r1 = subprocess.run([PY, "-c", chk], env=env, capture_output=True, text=True); rec("B4a_stale_pyc_runs_tampered_code", json.loads(r1.stdout) if r1.returncode == 0 else r1.stderr)
env2 = {**env, "PYTHONPYCACHEPREFIX": str(d / "fresh_cache")}
r2 = subprocess.run([PY, "-c", chk], env=env2, capture_output=True, text=True); rec("B4b_fresh_pycache_prefix_control", json.loads(r2.stdout) if r2.returncode == 0 else r2.stderr)
# 报告目录旁的模块与第三方遮蔽
d = T / "b5"; d.mkdir(); src, pkg = tiny(d); rep = d / "reports"; rep.mkdir()
(rep / "helper.py").write_text("CHEAT = True\n"); (rep / "numpy.py").write_text("__version__ = 'shadow'\n")
entry = rep / "run.py"
entry.write_text("import helper\nimport numpy\n")
closure = [str(x.relative_to(d.resolve())) for x in G.import_closure(src, [entry])]
manifest = G.build_manifest(d, [entry], src_root=src)
chk5 = f'''
import importlib.util as u, json, runpy, sys
s = u.spec_from_file_location("rg", {str(RG)!r}); G = u.module_from_spec(s); sys.modules["rg"] = G; s.loader.exec_module(G)
from pathlib import Path
sys.path.insert(0, {str(rep)!r})
import helper, numpy
m = json.loads({json.dumps(json.dumps(manifest))})
print(json.dumps({{"helper_loaded": helper.__file__, "numpy_version": numpy.__version__, "check_manifest": G.check_manifest(Path({str(d)!r}), m), "check_loaded_modules": G.check_loaded_modules(Path({str(d)!r}), m)}}))
'''
r5 = subprocess.run([PY, "-c", chk5], env={**env, "PYTHONPATH": str(src)}, capture_output=True, text=True)
rec("B5_sibling_and_shadow_modules_escape", {"closure": closure, "run": json.loads(r5.stdout) if r5.returncode == 0 else r5.stderr})
# 启动后的动态导入
d = T / "b6"; d.mkdir(); src, pkg = tiny(d); (pkg / "late.py").write_text("X = 1\n"); entry = d / "run.py"; entry.write_text("import ainerzero.sub\n")
manifest = G.build_manifest(d, [entry], src_root=src)
chk6 = f'''
import importlib, importlib.util as u, json, sys
s = u.spec_from_file_location("rg", {str(RG)!r}); G = u.module_from_spec(s); sys.modules["rg"] = G; s.loader.exec_module(G)
from pathlib import Path
import ainerzero.sub
m = json.loads({json.dumps(json.dumps(manifest))})
first = G.check_loaded_modules(Path({str(d)!r}), m)
importlib.import_module("ainerzero.sub.late")
print(json.dumps({{"at_startup": first, "after_late_import": G.check_loaded_modules(Path({str(d)!r}), m)}}))
'''
r6 = subprocess.run([PY, "-c", chk6], env={**env, "PYTHONPATH": str(src)}, capture_output=True, text=True); rec("B6_startup_only_check_misses_late_import", json.loads(r6.stdout) if r6.returncode == 0 else r6.stderr)
# 其余
G.check_stage_namespace("smoke", "s3p2-dev", probe="s3p2-dev", dev="s3p2-dev", final="s3p2-final"); rec("B7_probe_equal_dev_config_passes_smoke", True)
d = T / "b8"; d.mkdir(); p = d / "lk"; led = d / "u.json"
with G.RunLock(p) as l:
    for u in ("dev1", "dev1 ", " "): G.consume_dev_use(l, led, u, "x", max_uses=99)
rec("B8_whitespace_ids_and_max_uses_override", [x["id"] for x in json.loads(led.read_text())])
evil = types.ModuleType("evil")
rec("B9_module_without_file_ignored", G.check_loaded_modules(Path("/tmp"), {"x": "y"}, modules={"ainerzero.evil": evil}))
errs = {}
led = d / "empty.json"; led.write_text("")
with G.RunLock(p) as l:
    try: G.consume_dev_use(l, led, "a", "x")
    except Exception as e: errs["empty_ledger"] = type(e).__name__
try:
    with G.RunLock(d / "no/such/dir/lk"): pass
except Exception as e: errs["missing_lock_dir"] = type(e).__name__
with G.RunLock(p) as l:
    try: G.consume_dev_use(l, d / "bad.json", "a", "x") if (d / "bad.json").write_text("[1]") else None
    except Exception as e: errs["list_of_ints_ledger"] = type(e).__name__
rec("B10_non_guard_exceptions", errs)
(Path(sys.argv[1]) / "out/bypass.json").write_text(json.dumps(OUT, ensure_ascii=False, indent=1, default=str))
shutil.rmtree(T)
