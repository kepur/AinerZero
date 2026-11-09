"""59ed20d 与 HEAD 的函数级字节码差异（只读 git 对象）。"""
import subprocess, sys, types
from pathlib import Path
R = "/Users/mac/AinerWorkFlow/AinerZero"
def src(rev, rel): return subprocess.run(["git", "show", f"{rev}:{rel}"], cwd=R, capture_output=True, text=True, check=True).stdout
def walk(c, p=""):
    yield p + c.co_name, c
    for k in c.co_consts:
        if isinstance(k, types.CodeType): yield from walk(k, p + c.co_name + ".")
def sig(c):
    cs = tuple(("<code>" if isinstance(k, types.CodeType) else (None if isinstance(k, str) and len(k) > 30 else k)) for k in c.co_consts)
    return (c.co_code, c.co_names, c.co_varnames, cs)
for rel in ("reports/V9-S3-PHASE2/run_phase2.py", "src/ainerzero/v9/experiments/s3/analysis_p2.py", "src/ainerzero/v9/experiments/s3/arms_p2_mlx.py", "src/ainerzero/v9/experiments/s3/replay.py", "src/ainerzero/v9/experiments/s3/run_guard.py"):
    a = dict(walk(compile(src("59ed20d", rel), rel, "exec"))); b = dict(walk(compile(src("HEAD", rel), rel, "exec")))
    same = sorted(n for n in set(a) & set(b) if sig(a[n]) == sig(b[n])); diff = sorted(n for n in set(a) & set(b) if sig(a[n]) != sig(b[n]))
    print(f"== {rel.split('/')[-1]}: identical {len(same)}; changed {diff}; added {sorted(set(b) - set(a))}; removed {sorted(set(a) - set(b))}")
