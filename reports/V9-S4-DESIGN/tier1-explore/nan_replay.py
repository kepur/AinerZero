# 存档：第五轮 L-int-c 发散的复现脚本，按运行时原样保存。输出路径写死在当时会话的临时目录，复跑前先改路径。
import sys; sys.path.insert(0, "src")
import numpy as np, mlx.core as mx, mlx.nn as nn, mlx.optimizers as optim
from mlx.utils import tree_flatten
from ainerzero.v9.experiments.s3.run_guard import RunLock
from ainerzero.v9.experiments.s4 import learned_mlx as L, world as W
with RunLock("artifacts/locks/m0-worker.lock"):
    mx.set_default_device(mx.gpu)
    rng = np.random.default_rng(20261110)
    eps = [W.generate_episode("s4x-explore", 5000 + w, int(rng.integers(4, 9))) for w in range(200)]
    pool = L.make_pool(eps, 120_000, np.random.default_rng(1), W.physics)   # as explore5
    mx.random.seed(1)
    m = L.Dynamics("L-int-c"); mx.eval(m.parameters())
    opt = optim.Adam(learning_rate=1e-3); vg = nn.value_and_grad(m, L.rollout_loss)
    br = np.random.default_rng(1)
    prev = None
    for t, (n, idx) in enumerate(L.batches(pool, 20000, 256, br), 1):
        b = {k: mx.array(v[idx]) for k, v in pool.by_n[n].items()}
        loss, g = vg(m, b)
        gn = float(mx.sqrt(sum((x ** 2).sum() for _, x in tree_flatten(g))))
        lv = float(loss)
        pfin = all(np.isfinite(np.array(v)).all() for _, v in tree_flatten(m.parameters()))
        if t % 2000 == 0 or not (np.isfinite(lv) and np.isfinite(gn) and pfin):
            P = np.array(b["p"])
            dmin = float(np.min(np.linalg.norm(P[:, :, None] - P[:, None], axis=-1) + np.eye(n) * 99))
            # where does the forward go non-finite: roll out and report the first bad step
            p, v = b["p"], b["v"]; first = None; pmax = []
            for k in range(1, 11):
                p, v, lg, _ = m(p, v, b["pil"])
                pa = np.array(p); pmax.append(float(np.nanmax(np.abs(pa))) if np.isfinite(pa).any() else float("nan"))
                if first is None and not np.isfinite(pa).all():
                    first = k
            print(t, "n", n, "loss", lv, "gradnorm", gn, "params finite", pfin, "min dist", dmin, "first bad step", first, "max|p| per step", [round(x, 1) for x in pmax], "prev", prev, flush=True)
            if not (np.isfinite(lv) and np.isfinite(gn) and pfin):
                np.savez("/private/tmp/claude-501/-Users-mac-AinerWorkFlow-AinerZero/96fa9b3d-415c-4ce8-9e61-a2e1d5dc87ed/scratchpad/nan_batch.npz", **{k: np.array(v) for k, v in b.items()})
                m.save_weights("/private/tmp/claude-501/-Users-mac-AinerWorkFlow-AinerZero/96fa9b3d-415c-4ce8-9e61-a2e1d5dc87ed/scratchpad/nan_model.safetensors")
                break
        prev = (round(lv, 3), round(gn, 2))
        opt.update(m, g); mx.eval(m.parameters(), opt.state)
