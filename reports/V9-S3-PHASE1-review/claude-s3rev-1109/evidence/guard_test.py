"""run_phase1.py 守卫测试：在假根目录里跑改写了 REPO 的副本，真实 artifacts 不受影响。P208 第二路。

GE 变体把 mx.set_default_device(mx.cpu) 换成 raise SystemExit("GUARDS_PASSED")，守卫之后立刻退出，不产生任何数据或训练。
LK 变体只改 REPO，用于验证「先记账后拿锁」。fake 根内的 PREREG 副本登记的是改写后的 runner 的 SHA，别的文件 SHA 不变。
"""
import fcntl, hashlib, json, os, shutil, subprocess, sys
from pathlib import Path
W = Path(sys.argv[1]); R = Path("/Users/mac/AinerWorkFlow/AinerZero"); PY = str(R / ".venv/bin/python")
sha = lambda p: hashlib.sha256(Path(p).read_bytes()).hexdigest()
src_runner = (R / "reports/V9-S3-PHASE1/run_phase1.py").read_text(encoding="utf-8")
real_stat = {p: (os.stat(p).st_mtime_ns, os.stat(p).st_size) for p in [R / "artifacts/locks/m0-worker.lock", R / "artifacts/v9/s3/phase1/dev_uses.json"]}
LOG = []
def build(variant):
    F = W / f"fake_{variant}"
    if F.exists(): shutil.rmtree(F)
    (F / "reports/V9-S3-PHASE1").mkdir(parents=True); (F / "reports/V9-S3-DESIGN").mkdir(parents=True); (F / "artifacts/locks").mkdir(parents=True)
    shutil.copytree(W / "base/src", F / "src")
    old = 'REPO = Path("/Users/mac/AinerWorkFlow/AinerZero")'; assert src_runner.count(old) == 1
    s = src_runner.replace(old, f'REPO = Path("{F}")')
    if variant == "GE":
        o2 = "    mx.set_default_device(mx.cpu)\n"; assert s.count(o2) == 1
        s = s.replace(o2, '    raise SystemExit("GUARDS_PASSED")\n')
    assert "/Users/mac/AinerWorkFlow/AinerZero" not in s
    (F / "reports/V9-S3-PHASE1/run_phase1.py").write_text(s, encoding="utf-8")
    pre = json.loads((R / "reports/V9-S3-DESIGN/PREREG-r1.json").read_text(encoding="utf-8"))
    pre["code_sha256"]["reports/V9-S3-PHASE1/run_phase1.py"] = sha(F / "reports/V9-S3-PHASE1/run_phase1.py")
    (F / "reports/V9-S3-DESIGN/PREREG-r1.json").write_text(json.dumps(pre, ensure_ascii=False), encoding="utf-8")
    return F, pre
def go(F, label, *args):
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1", "PYTHONPATH": str(F / "src")}
    p = subprocess.run([PY, str(F / "reports/V9-S3-PHASE1/run_phase1.py"), "--report", str(F / "r.json"), *args], capture_output=True, text=True, timeout=120, env=env)
    tail = (p.stderr.strip().splitlines() or [""])[-1]
    u = F / "artifacts/v9/s3/phase1/dev_uses.json"; m = F / "artifacts/v9/s3/phase1/FINAL_READ_ONCE.json"
    rec = {"case": label, "args": list(args), "exit": p.returncode, "msg": tail, "dev_ledger": [x["id"] for x in json.loads(u.read_text())] if u.exists() else None, "final_marker": m.exists()}
    LOG.append(rec); print(json.dumps(rec, ensure_ascii=False), flush=True)
    return rec
F, pre = build("GE")
line = pre["final_approval_line"]
go(F, "dev 无 use-id 被拒", "--stage", "dev")
go(F, "dev1 通过守卫", "--stage", "dev", "--use-id", "dev1")
go(F, "dev1 重复被拒", "--stage", "dev", "--use-id", "dev1")
go(F, "dev2 通过守卫", "--stage", "dev", "--use-id", "dev2")
go(F, "dev3 超限被拒", "--stage", "dev", "--use-id", "dev3")
go(F, "final 无批准行被拒", "--stage", "final")
go(F, "final 错批准行被拒", "--stage", "final", "--approval", "S3-P1-FINAL-READ-APPROVED-TIER1-20261110")
go(F, "final 正确批准行", "--stage", "final", "--approval", line)
go(F, "final 第二次被拒", "--stage", "final", "--approval", line)
go(F, "smoke：不记账、不校验 SHA", "--stage", "smoke")
victim = F / "src/ainerzero/v9/experiments/s3/analysis.py"
orig = victim.read_text(encoding="utf-8")
victim.write_text(orig + "\n# tamper\n", encoding="utf-8")
go(F, "SHA：被篡改的 analysis.py 被拒（dev）", "--stage", "dev", "--use-id", "dev9")
go(F, "SHA：smoke 不查，篡改照过", "--stage", "smoke")
victim.write_text(orig, encoding="utf-8")
s2 = F / "src/ainerzero/v9/experiments/s2/world.py"
s2o = s2.read_text(encoding="utf-8")
s2.write_text(s2o + "\n# tamper s2 world, unfrozen dependency\n", encoding="utf-8")
(F / "artifacts/v9/s3/phase1/dev_uses.json").unlink()
go(F, "绕过演示：删账本后 dev 复用 + S2 world.py 改动无人发现", "--stage", "dev", "--use-id", "dev1")
s2.write_text(s2o, encoding="utf-8")
(F / "artifacts/v9/s3/phase1/FINAL_READ_ONCE.json").unlink()
go(F, "绕过演示：删标记后 final 可再读", "--stage", "final", "--approval", line)
F2, pre2 = build("LK")
holder = (F2 / "artifacts/locks/m0-worker.lock").open("a+"); fcntl.flock(holder, fcntl.LOCK_EX | fcntl.LOCK_NB)
go(F2, "先记账后拿锁：锁被占，dev 仍被扣一次", "--stage", "dev", "--use-id", "dev1")
go(F2, "先记账后拿锁：锁被占，final 标记已写，一次机会作废", "--stage", "final", "--approval", pre2["final_approval_line"])
fcntl.flock(holder, fcntl.LOCK_UN); holder.close()
assert real_stat == {p: (os.stat(p).st_mtime_ns, os.stat(p).st_size) for p in real_stat}, "真实 artifacts 被碰了"
print("REAL_ARTIFACTS_UNTOUCHED True", flush=True)
(W / "out/guard_test.json").write_text(json.dumps(LOG, ensure_ascii=False, indent=1), encoding="utf-8")
