"""探针 p1 失败的复现：多个进程同时首次编译同一个 MLX CPU 融合内核（nn.relu 是 mx.compile 的函数），
在共用的缓存目录 $TMPDIR/mlx/<版本>/cpu/ 里写同名 .so 而冲突（ld: open() failed, errno=17）。

用法：python -I race_repro.py <shared|private> <进程数> <轮数> <根目录>
- shared：所有进程共用同一个新的空 TMPDIR（等于探针重启后缓存被清空的情形）；
- private：每个进程各用自己的空 TMPDIR（修法）。
每一轮用一个新的空目录和一个新的输入形状组合，逼出新内核。打印每轮出错的进程数。只用 CPU，不写仓库。
"""
import multiprocessing as mp
import os
import sys
import tempfile
from pathlib import Path


def child(tmp: str, k: int, q):
    os.environ["TMPDIR"] = tmp
    import mlx.core as mx
    import mlx.nn as nn
    mx.set_default_device(mx.cpu)
    try:
        # a broadcast pattern specific to this round, so the kernel is not in any cache yet
        a = mx.ones((3 + k, 1, 5)) * float(k)
        b = mx.ones((1, 4, 5))
        mx.eval(nn.relu(a - b))
        q.put("ok")
    except Exception as exc:  # noqa: BLE001
        q.put("error: " + str(exc).splitlines()[0][:160])


def main():
    mode, n, rounds, root = sys.argv[1], int(sys.argv[2]), int(sys.argv[3]), Path(sys.argv[4])
    ctx = mp.get_context("spawn")
    total_err = 0
    for k in range(rounds):
        base = Path(tempfile.mkdtemp(prefix=f"r{k}-", dir=root))
        dirs = [str(base)] * n if mode == "shared" else [str(base / f"w{i}") for i in range(n)]
        for d in dirs:
            Path(d).mkdir(parents=True, exist_ok=True)
        q = ctx.Queue()
        ps = [ctx.Process(target=child, args=(d, k, q)) for d in dirs]
        for p in ps:
            p.start()
        for p in ps:
            p.join()
        res = [q.get() for _ in ps]
        errs = [r for r in res if r != "ok"]
        total_err += len(errs)
        print(f"{mode} round {k}: {len(errs)} of {n} failed" + (f"  e.g. {errs[0]}" if errs else ""), flush=True)
    print(f"{mode}: {total_err} failures in {rounds} rounds x {n} processes")


if __name__ == "__main__":
    main()
