# 存档：第五轮 L-int-c 发散的复现脚本，按运行时原样保存。输出路径写死在当时会话的临时目录，复跑前先改路径。
import sys, time; sys.path.insert(0, "src")
import numpy as np, mlx.core as mx, mlx.nn as nn, mlx.optimizers as optim
from mlx.utils import tree_flatten
from ainerzero.v9.experiments.s3.run_guard import RunLock
from ainerzero.v9.experiments.s4 import learned_mlx as L, world as W
with RunLock("artifacts/locks/m0-worker.lock"):
    mx.set_default_device(mx.gpu)
    rng = np.random.default_rng(20261110)
    eps = [W.generate_episode("s4x-explore", 5000 + w, int(rng.integers(4, 9))) for w in range(200)]
    pool = L.make_pool(eps, 30000, np.random.default_rng(1), W.physics)
    mx.random.seed(1)
    m = L.Dynamics("L-int-c"); mx.eval(m.parameters())
    opt = optim.Adam(learning_rate=1e-3); vg = nn.value_and_grad(m, L.rollout_loss)
    br = np.random.default_rng(1)
    for t, (n, idx) in enumerate(L.batches(pool, 20000, 256, br), 1):
        b = {k: mx.array(v[idx]) for k, v in pool.by_n[n].items()}
        loss, g = vg(m, b)
        gn = float(mx.sqrt(sum((x ** 2).sum() for _, x in tree_flatten(g))))
        lv = float(loss)
        if not np.isfinite(lv) or not np.isfinite(gn) or t % 1000 == 0:
            P = b["p"]
            dmin = float(np.min(np.linalg.norm(np.array(P)[:, :, None] - np.array(P)[:, None], axis=-1) + np.eye(n) * 99))
            print(t, "n", n, "loss", round(lv, 3), "gradnorm", round(gn, 2), "min pair dist", dmin, flush=True)
            if not np.isfinite(lv) or not np.isfinite(gn):
                break
        opt.update(m, g); mx.eval(m.parameters(), opt.state)
