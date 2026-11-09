"""r0 的绕过实验在新 run_guard 上重跑。全部在临时目录。"""
import fcntl, json, multiprocessing as mp, os, shutil, subprocess, sys, tempfile, time, types
from pathlib import Path
from ainerzero.v9.experiments.s3 import run_guard as G
T = Path(tempfile.mkdtemp(dir=sys.argv[1])); OUT = {}; ctx = mp.get_context("fork")
def rec(k, v): OUT[k] = v; print(k, "::", json.dumps(v, ensure_ascii=False, default=str)[:300], flush=True)
def race_worker(i, ledger, lockpath, barrier, q):
    barrier.wait()
    try:
        with G.RunLock(lockpath) as l:
            G.consume_dev_use(l, ledger, f"dev{i}", "race", max_uses=2, expected_lock=lockpath)
        q.put("ok")
    except G.GuardError: q.put("refused")
over, mx_, lens = 0, 0, []
for r in range(40):
    d = T / f"race{r}"; d.mkdir(); ledger = d / "uses.json"; b = ctx.Barrier(6); q = ctx.Queue()
    ps = [ctx.Process(target=race_worker, args=(i, ledger, d / f"own{i}.lock", b, q)) for i in range(6)]
    [p.start() for p in ps]; res = [q.get(timeout=30) for _ in ps]; [p.join() for p in ps]
    ok = res.count("ok"); over += ok != 2; mx_ = max(mx_, ok); lens.append(len(json.loads(ledger.read_text())))
rec("B1_six_processes_own_locks", {"rounds": 40, "rounds_not_exactly_2": over, "max_successes": mx_, "ledger_lengths": sorted(set(lens))})
d = T / "b2"; d.mkdir(); shared, other = d / "shared.lock", d / "other.lock"
with G.RunLock(other) as l:
    try: G.consume_dev_use(l, d / "a.json", "dev1", "x", max_uses=2, expected_lock=shared); rec("B2_other_lock_refused", False)
    except G.GuardError as e: rec("B2_other_lock_refused", str(e)[:60])
d = T / "b3"; d.mkdir(); p = d / "lk"
a = G.RunLock(p).__enter__(); os.unlink(p); b = G.RunLock(p).__enter__()
rec("B3_unlink_then_two_holders_still_possible", {"a_held": a.held, "b_held": b.held, "same_inode": os.fstat(a._fh.fileno()).st_ino == os.fstat(b._fh.fileno()).st_ino})
b.__exit__(); a.__exit__()
d = T / "b5"; d.mkdir(); src = d / "src"; pkg = src / "ainerzero"; pkg.mkdir(parents=True); (pkg / "__init__.py").write_text(""); rep = d / "reports"; rep.mkdir(); (rep / "helper.py").write_text("X=1\n"); e = rep / "run.py"; e.write_text("import helper\n")
closure = [str(x.relative_to(d.resolve())) for x in G.import_closure(src, [e])]
mani = G.build_manifest(d, [e], src_root=src)
bad_frozen = G.check_loaded_modules(d, mani, modules={"helper": type("M", (), {"__file__": str(rep / "helper.py")}), "__main__": type("M", (), {"__file__": str(e)})}, ignore_roots=[])
bad_unfrozen = G.check_loaded_modules(d, {"src/ainerzero/__init__.py": "x"}, modules={"helper": type("M", (), {"__file__": str(rep / "helper.py")}), "__main__": type("M", (), {"__file__": str(e)})}, ignore_roots=[])
rec("B5_sibling", {"closure": closure, "frozen_flagged": bad_frozen, "unfrozen_flagged_n": len(bad_unfrozen)})
fp = T / "out_of_repo"; fp.mkdir(); (fp / "fakelib.py").write_text("__version__ = '9.9'\n"); sys.path.insert(0, str(fp))
rec("B6_third_party_outside_repo_not_refused", G.third_party_versions(d, ["fakelib"]))
evil = types.ModuleType("evil"); rec("B9_module_without_file_ignored", G.check_loaded_modules(d, {"x": "y"}, modules={"ainerzero.evil": evil}))
led = d / "w.json"; lk = d / "k"
with G.RunLock(lk) as l:
    for u in ("dev1", "dev1 ", " "): G.consume_dev_use(l, led, u, "x", max_uses=9, expected_lock=lk)
rec("B8_whitespace_ids", [x["id"] for x in json.loads(led.read_text())])
errs = {}
led = d / "ints.json"; led.write_text("[1]")
with G.RunLock(lk) as l:
    try: G.consume_dev_use(l, led, "a", "x", max_uses=2, expected_lock=lk)
    except Exception as ex: errs["list_of_ints_ledger"] = type(ex).__name__
try:
    with G.RunLock(d / "no/such/dir/lk"): pass
except Exception as ex: errs["missing_lock_dir"] = type(ex).__name__
rec("B10_non_guard_exceptions", errs)
(Path(sys.argv[1]) / "out/bypass3.json").write_text(json.dumps(OUT, ensure_ascii=False, indent=1, default=str)); shutil.rmtree(T)
