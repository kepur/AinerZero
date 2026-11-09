"""r2 启动顺序对抗。假根目录，替身分区，记账后立即退出的桩，真实 artifacts 不碰。"""
import fcntl, json, os, shutil, subprocess, sys, time
from pathlib import Path
W = Path(sys.argv[1]).resolve(); PY = "/Users/mac/AinerWorkFlow/AinerZero/.venv/bin/python"; BASE = W / "base"; RUN = "reports/V9-S3-PHASE2/run_phase2.py"
sys.path.insert(0, str(BASE / "src"))
from ainerzero.v9.experiments.s3 import run_guard as GD
real = Path("/Users/mac/AinerWorkFlow/AinerZero/artifacts/v9/s3/phase2"); before = sorted(str(p) for p in real.iterdir())
ANCHOR = "        mx.set_default_device(mx.cpu)\n        capacity = "
def git(r, *a): subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", *a], cwd=r, check=True, capture_output=True)
def fake(name):
    r = W / "fake" / name
    if r.exists(): shutil.rmtree(r)
    (r / "reports/V9-S3-PHASE2").mkdir(parents=True); shutil.copytree(BASE / "src", r / "src", ignore=shutil.ignore_patterns("__pycache__"))
    t = (BASE / RUN).read_text(encoding="utf-8"); assert t.count(ANCHOR) == 1
    (r / RUN).write_text(t.replace(ANCHOR, '        raise SystemExit("REVIEW_STOP_AFTER_CONSUME")\n' + ANCHOR), encoding="utf-8")
    d = r / "reports/DESIGN.md"; d.write_text("design"); (r / "artifacts/locks").mkdir(parents=True); (r / "artifacts/v9/s3/phase2").mkdir(parents=True)
    pre = {"manifest": GD.build_manifest(r, [r / RUN], src_root=r / "src", extra=[d]), "third_party": GD.third_party_versions(BASE, ("numpy", "mlx.core")), "dev_max_uses": 2, "final_approval_line": "LINE", "h3_capacity": 64}
    (r / "reports/V9-S3-PHASE2/PREREG-r1.json").write_text(json.dumps(pre)); (r / ".gitignore").write_text("artifacts/\n__pycache__/\n"); git(r, "init", "-q"); git(r, "add", "."); git(r, "commit", "-qm", "frozen"); return r
N = [0]
def run(r, *a, prefix=None, report="reports/out.json"):
    N[0] += 1; p_ = prefix or (r.parent / f"{r.name}-pyc{N[0]}")
    env = {k: v for k, v in os.environ.items() if not k.startswith("PYTHON")}
    return subprocess.run([PY, "-I", "-X", f"pycache_prefix={p_}", str(r / RUN), "--report", str(r / report), *a], cwd=r, env=env, capture_output=True, text=True, timeout=120)
def state(r):
    a = r / "artifacts/v9/s3/phase2"; L = a / "dev_uses.json"; M = a / "FINAL_READ_ONCE.json"
    led = None
    if a.is_dir() and L.exists():
        try: led = [u["id"] for u in json.loads(L.read_text())]
        except Exception: led = "unparsable"
    return {"ledger": led or [], "final_marker": M.exists(), "report_exists": (r / "reports/out.json").exists(), "run_dirs": sorted(p.name for p in a.iterdir() if p.is_dir()) if a.is_dir() else "root_is_file"}
OUT = json.loads((W / "out/runner_order2_part1.json").read_text()) if (W / "out/runner_order2_part1.json").exists() else {}
def rec(k, p, r):
    OUT[k] = {"exit": p.returncode, "last_err": (p.stderr.strip().splitlines() or [""])[-1][:150], **state(r)}; print(k, json.dumps(OUT[k], ensure_ascii=False), flush=True)
DEV = ("--stage", "dev", "--use-id", "dev1", "--purpose", "x"); FINAL = ("--stage", "final", "--approval", "LINE")
r = fake("c10"); shutil.rmtree(r / "artifacts/v9/s3/phase2"); (r / "artifacts/v9/s3/phase2").write_text("file"); rec("C10_root_is_a_file", run(r, *DEV), r)
r = fake("c11"); (r / "artifacts/v9/s3/phase2/FINAL_READ_ONCE.json").write_text("{}"); rec("C11_marker_exists", run(r, *FINAL), r)
r = fake("c12"); rec("C12_use_id_with_slash", run(r, "--stage", "dev", "--use-id", "a/b", "--purpose", "x"), r); OUT["C12_use_id_with_slash"]["tree"] = sorted(str(p.relative_to(r / "artifacts")) for p in (r / "artifacts").rglob("*") if p.is_dir())[:8]
r = fake("c13"); p = run(r, "--stage", "dev", "--use-id", "../../../../../escaped", "--purpose", "x"); rec("C13_use_id_with_dotdot", p, r); OUT["C13_use_id_with_dotdot"]["escaped_outside_phase2"] = [str(x.relative_to(r)) for x in r.rglob("*escaped*")][:4]; print("C13 tree", OUT["C13_use_id_with_dotdot"]["escaped_outside_phase2"], flush=True)
# 陈旧字节码
def tamper(r, prefix, age):
    f = r / "src/ainerzero/v9/experiments/s3/analysis_p2.py"; orig = f.read_text(); st = int(time.time()) - 900
    assert orig.count("H2_MIN_DELTA = 0.05") == 1; f.write_text(orig.replace("H2_MIN_DELTA = 0.05", "H2_MIN_DELTA = 0.50")); os.utime(f, (st, st))
    env = {k: v for k, v in os.environ.items() if not k.startswith("PYTHON")}
    subprocess.run([PY, "-I", "-X", f"pycache_prefix={prefix}", "-c", f"import sys; sys.path.insert(0, {str(r / 'src')!r}); import ainerzero.v9.experiments.s3.analysis_p2"], env=env, check=True, capture_output=True)
    f.write_text(orig); os.utime(f, (st, st))
    if age:
        for pyc in Path(prefix).rglob("*.pyc"): os.utime(pyc, (time.time() - age, time.time() - age))
    return env
r = fake("c14"); prefix = r.parent / "c14-stale"; tamper(r, prefix, 900); rec("C14_old_stale_prefix_refused", run(r, *DEV, prefix=prefix), r)
r = fake("c15"); prefix = r.parent / "c15-stale"; env = tamper(r, prefix, 0); p = run(r, *DEV, prefix=prefix); rec("C15_tampered_bytecode_younger_than_tolerance", p, r)
seen = subprocess.run([PY, "-I", "-X", f"pycache_prefix={prefix}", "-c", f"import sys; sys.path.insert(0, {str(r / 'src')!r}); import ainerzero.v9.experiments.s3.analysis_p2 as G; print(G.H2_MIN_DELTA)"], env=env, capture_output=True, text=True).stdout.strip(); OUT["C15_value_loaded"] = seen; print("C15 value", seen, flush=True)
after = sorted(str(p) for p in real.iterdir()); OUT["real_artifacts_untouched"] = before == after; print("REAL_UNTOUCHED", before == after, flush=True)
(W / "out/runner_order2.json").write_text(json.dumps(OUT, ensure_ascii=False, indent=1))
