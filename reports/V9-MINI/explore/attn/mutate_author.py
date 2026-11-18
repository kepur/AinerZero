# 作者自测的变异（一级 claude，11-18）。用法：git archive HEAD src tests pyproject.toml 解到 <工作目录>/base，再在 <工作目录> 里运行本脚本。非作者复核 A32 要另做自己的变异。
import pathlib, shutil, subprocess, sys
BASE = pathlib.Path("base")
PY = "/Users/mac/AinerWorkFlow/AinerZero/.venv/bin/python"
MUTS = [
 ("查询头按 [目标, 头] 排列", "src/ainerzero/v9/mini/attn.py",
  "q = q.reshape(B, G, Lq, H, dh).transpose(0, 3, 1, 2, 4).reshape(B, H * G, Lq, dh)",
  "q = q.reshape(B, G, Lq, H, dh).transpose(0, 1, 3, 2, 4).reshape(B, H * G, Lq, dh)"),
 ("读出去掉因果掩码", "src/ainerzero/v9/mini/attn.py",
  'r = mx.fast.scaled_dot_product_attention(q, k, v, scale=dh ** -0.5, mask="causal")',
  "r = mx.fast.scaled_dot_product_attention(q, k, v, scale=dh ** -0.5)"),
 ("上界差一", "src/ainerzero/v9/mini/attn.py",
  "nxt_after - t, np.inf)", "nxt_after - t - 1, np.inf)"),
 ("valid 不排除已到达的帧", "src/ainerzero/v9/mini/attn.py",
  "return ub, eq[..., 1:], ~eq[..., :-1]", "return ub, eq[..., 1:], np.ones_like(eq[..., :-1])"),
 ("目标不取上界", "src/ainerzero/v9/mini/attn.py",
  "return np.minimum(np.minimum(y, ub), cap)", "return np.minimum(y, cap)"),
 ("智能体第一步重复追加", "src/ainerzero/v9/mini/attn.py",
  "        if not self.first:          # 前缀最后一帧就是任务第一帧，已经在历史里\n",
  "        if True:\n"),
 ("last_only 的 RoPE 不加 offset", "src/ainerzero/v9/mini/attn.py",
  "q = self.rope(q, offset=L - 1)", "q = self.rope(q)"),
]
for name, f, old, new in MUTS:
    d = pathlib.Path("m"); shutil.rmtree(d, ignore_errors=True); shutil.copytree(BASE, d)
    p = d / f; s = p.read_text(); assert s.count(old) == 1, name; p.write_text(s.replace(old, new))
    r = subprocess.run([PY, "-m", "pytest", "-q", "-p", "no:cacheprovider", "tests/v9/mini/test_attn.py"], cwd=d,
                       env={"PYTHONPATH": str((d / "src").resolve()), "PATH": "/usr/bin:/bin"}, capture_output=True, text=True)
    fails = [l for l in r.stdout.splitlines() if l.startswith("FAILED")]
    print(f"== {name}: {'抓到' if r.returncode else '没抓到'}  ({r.stdout.strip().splitlines()[-1]})")
    for l in fails: print("   ", l[:150])
r = subprocess.run([PY, "-m", "pytest", "-q", "-p", "no:cacheprovider", "tests/v9/mini/test_attn.py"], cwd=BASE,
                   env={"PYTHONPATH": str((BASE / "src").resolve()), "PATH": "/usr/bin:/bin"}, capture_output=True, text=True)
print("== 未变异基线:", r.stdout.strip().splitlines()[-1])
