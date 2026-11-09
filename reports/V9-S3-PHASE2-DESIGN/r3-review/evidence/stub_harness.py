"""真实 run_phase2.py 文本 + 桩 mlx：拒绝路径、清理路径、字符校验。全部在假根目录，不生成数据，不碰真实 artifacts。"""
import json, os, shutil, subprocess, sys, time
from pathlib import Path
W = Path(sys.argv[1]).resolve(); FZ = W / "frozen"; PY = "/Users/mac/AinerWorkFlow/AinerZero/.venv/bin/python"; RUN = "reports/V9-S3-PHASE2/run_phase2.py"
sys.path.insert(0, str(FZ / "src"))
from ainerzero.v9.experiments.s3 import run_guard as GD
real = Path("/Users/mac/AinerWorkFlow/AinerZero/artifacts/v9/s3/phase2/dev_uses.json"); real_before = real.read_bytes()
import numpy
def git(r, *a): subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", *a], cwd=r, check=True, capture_output=True)
def fake(name):
    r = W / "fake" / name
    if r.exists(): shutil.rmtree(r)
    (r / "reports/V9-S3-PHASE2").mkdir(parents=True); shutil.copytree(FZ / "src", r / "src", ignore=shutil.ignore_patterns("__pycache__")); shutil.copy2(FZ / RUN, r / RUN)
    d = r / "reports/DESIGN.md"; d.write_text("design"); (r / "artifacts/locks").mkdir(parents=True); (r / "artifacts/v9/s3/phase2").mkdir(parents=True)
    pre = {"manifest": GD.build_manifest(r, [r / RUN], src_root=r / "src", extra=[d]), "third_party": {"numpy": numpy.__version__, "mlx.core": "0.32.2"}, "dev_max_uses": 2, "final_approval_line": "LINE", "h3_capacity": 64}
    (r / "reports/V9-S3-PHASE2/PREREG-r1.json").write_text(json.dumps(pre)); (r / ".gitignore").write_text("artifacts/\n__pycache__/\n"); git(r, "init", "-q"); git(r, "add", "."); git(r, "commit", "-qm", "frozen"); return r
N = [0]
def run(r, *a, report="reports/out.json"):
    N[0] += 1; env = {k: v for k, v in os.environ.items() if not k.startswith("PYTHON")}
    return subprocess.run([PY, "-I", "-X", f"pycache_prefix={r.parent / (r.name + f'-pyc{N[0]}')}", str(W / "launch.py"), str(W / "stubs"), str(r / RUN), "--report", str(r / report), *a], cwd=r, env=env, capture_output=True, text=True, timeout=60)
def state(r):
    a = r / "artifacts/v9/s3/phase2"; L = a / "dev_uses.json"
    try: led = [u["id"] if isinstance(u, dict) else u for u in json.loads(L.read_text())] if L.exists() else []
    except Exception: led = "unparsable"
    return {"ledger": led, "marker": (a / "FINAL_READ_ONCE.json").exists(), "report": (r / "reports/out.json").exists(), "dirs": sorted(p.name for p in a.iterdir() if p.is_dir())}
OUT = {}
def rec(k, p, r, **extra):
    OUT[k] = {"exit": p.returncode, "err": (p.stderr.strip().splitlines() or [""])[-1].replace(str(r), "<root>")[:110], **state(r), **extra}; print(k, json.dumps(OUT[k], ensure_ascii=False), flush=True)
DEV = ("--stage", "dev", "--use-id", "dev1", "--purpose", "x"); FINAL = ("--stage", "final", "--approval", "LINE")
A = lambda r: r / "artifacts/v9/s3/phase2"
r = fake("u1"); rec("U1_dev_valid_reaches_mlx_and_spends", run(r, *DEV), r)
r = fake("u2"); rec("U2_final_valid_reaches_mlx_and_marks", run(r, *FINAL), r)
r = fake("u3"); rec("U3_smoke_valid_id", run(r, "--stage", "smoke", "--use-id", "t1"), r)
r = fake("u4"); rec("U4_probe_valid_id", run(r, "--stage", "probe", "--use-id", "p1"), r)
for sid, bad in enumerate((" dev1", "dev1 ", "a/b", "../x", "dev.1", "", "dev1\n", "é")):
    for stage, extra in (("dev", ("--purpose", "x")), ("smoke", ()), ("probe", ()), ("final", ("--approval", "LINE"))):
        r = fake(f"bad{sid}{stage}"); p = run(r, "--stage", stage, "--use-id", bad, *extra)
        k = f"I_{stage}_{json.dumps(bad, ensure_ascii=False)}"; rec(k, p, r); assert "invalid use id" in OUT[k]["err"], k; assert not OUT[k]["report"] and not OUT[k]["dirs"] and OUT[k]["ledger"] == [] and not OUT[k]["marker"], k
print("INVALID_IDS_ALL_REFUSED_NOTHING_CREATED", sum(k.startswith("I_") for k in OUT), flush=True)
r = fake("c1"); A(r).joinpath("dev_uses.json").write_text(json.dumps([{"id": "a"}, {"id": "b"}])); rec("C1_exhausted_cleans_shell", run(r, *DEV), r)
r = fake("c2"); A(r).joinpath("dev_uses.json").write_text(json.dumps([{"id": "dev1"}])); rec("C2_duplicate_id_cleans_shell", run(r, *DEV), r)
r = fake("c3"); L = A(r) / "dev_uses.json"; L.write_text("not json"); rec("C3_malformed_ledger_cleans_shell", run(r, *DEV), r); L.write_text("[]"); rec("C3b_retry_after_repair_works", run(r, *DEV), r)
r = fake("c4"); A(r).joinpath("FINAL_READ_ONCE.json").write_text('{"keep":1}'); rec("C4_marker_exists_cleans_shell", run(r, *FINAL), r, marker_content=A(r).joinpath("FINAL_READ_ONCE.json").read_text())
# 不该删的东西
r = fake("d1"); (r / "reports/out.json").write_text("earlier evidence"); A(r).joinpath("dev_uses.json").write_text(json.dumps([{"id": "a"}, {"id": "b"}])); p = run(r, *DEV); rec("D1_existing_report_kept", p, r, report_content=(r / "reports/out.json").read_text())
r = fake("d2"); (A(r) / "dev-dev1").mkdir(); (A(r) / "dev-dev1/precious.npz").write_text("data"); A(r).joinpath("dev_uses.json").write_text(json.dumps([{"id": "a"}, {"id": "b"}])); p = run(r, *DEV); rec("D2_existing_run_dir_kept", p, r, precious=(A(r) / "dev-dev1/precious.npz").read_text())
r = fake("d3"); t = r / "reports/precious.json"; t.write_text("precious"); (r / "reports/out.json").symlink_to(t); A(r).joinpath("dev_uses.json").write_text(json.dumps([{"id": "a"}, {"id": "b"}])); p = run(r, *DEV); rec("D3_report_is_symlink_target_kept", p, r, target=t.read_text(), link_kept=(r / "reports/out.json").is_symlink())
r = fake("d4"); (r / "reports/out.json").symlink_to(r / "reports/nothing.json"); A(r).joinpath("dev_uses.json").write_text(json.dumps([{"id": "a"}, {"id": "b"}])); p = run(r, *DEV); rec("D4_dangling_symlink_refused", p, r, link_kept=(r / "reports/out.json").is_symlink())
r = fake("d5"); A(r).joinpath("dev_uses.json").write_text(json.dumps([{"id": "a"}, {"id": "b"}])); p = run(r, *DEV, report="reports/new/sub/out.json"); rec("D5_refused_nested_report_removed_parents_stay", p, r, nested_report=(r / "reports/new/sub/out.json").exists(), parent_dir=(r / "reports/new/sub").is_dir())
r = fake("d6"); A(r).joinpath("dev_uses.json").write_text("[1]"); rec("D6_non_guard_error_not_cleaned", run(r, *DEV), r)
r = fake("d7"); A(r).joinpath("dev_uses.json").write_text(json.dumps([{"id": "a"}])); rec("D7_second_dev_ok_ledger_kept", run(r, "--stage", "dev", "--use-id", "b2", "--purpose", "x"), r)
OUT["real_ledger_untouched"] = real_before == real.read_bytes(); print("REAL_LEDGER_UNTOUCHED", OUT["real_ledger_untouched"], flush=True)
(W / "out/stub_harness.json").write_text(json.dumps(OUT, ensure_ascii=False, indent=1))
