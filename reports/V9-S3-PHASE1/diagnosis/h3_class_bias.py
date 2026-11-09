"""一级诊断（dev1 之后，不用 dev 分区）：H3 的崩塌是记忆受损，还是读出头类别偏置。
用 dev1 的终态权重（F2 阶段之后），在 s3p1-probe 的 F1 回合上比较：
  普通读出（16 类全开） vs 只在 F1 的 8 类里选（等价于告诉模型当前属于哪一族）。
另外统计 A3 的打分头选中记录的命中率，并与手工线索比较。
"""
import fcntl, json, sys
from pathlib import Path
import numpy as np
REPO = Path("/Users/mac/AinerWorkFlow/AinerZero"); sys.path.insert(0, str(REPO / "src"))
import mlx.core as mx, mlx.nn as nn
from ainerzero.v9.experiments.s3 import arms_mlx as A, batching as B, data as D, spec
mx.set_default_device(mx.cpu)
lock = (REPO / "artifacts/locks/m0-worker.lock").open("a+"); fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
NS = spec.NAMESPACE_PROBE; LAM = 1.0; LONG = B.BUCKET_CODE[spec.BUCKET_LONG]
ev = []
for w in range(100):
    ep = D.generate_episode(D.derive_seed(NS, "diag-world", w), D.derive_seed(NS, "diag-ep", w, 0), family="F1")
    p = B.prepare_episode(ep, LAM, perm_seed=70_000_000 + w)
    if len(p.query_t): ev.append(p)
f1 = np.array(sorted(spec.F1_TOKENS)); out = {}
for arm in ("A0", "A1", "A2", "A3"):
    rows = []
    for s in (1, 2, 3):
        m = A.ReadoutArm(arm); m.load_weights(str(REPO / f"artifacts/v9/s3/phase1/dev-dev1-{arm}-s{s}.npz")); mx.eval(m.parameters())
        C0, C1, Sw, Bk = [], [], [], []
        for i in range(0, len(ev), 32):
            b = B.collate(ev[i:i + 32]); lg, _ = A.forward(m, {k: mx.array(v) for k, v in b.items()}, hard=True); lg = np.asarray(lg)
            C0.append(lg.argmax(-1) == b["answer"])
            C1.append(f1[lg[:, f1].argmax(-1)] == b["answer"]); Sw.append(b["swapped"]); Bk.append(b["bucket"])
        c0, c1, sw, bk = map(np.concatenate, (C0, C1, Sw, Bk)); l = bk == LONG
        rows.append({"open_primary": float(c0[l & sw].mean()), "f1_only_primary": float(c1[l & sw].mean()), "open_unswapped": float(c0[l & ~sw].mean()), "f1_only_unswapped": float(c1[l & ~sw].mean())})
    out[arm] = {k: round(float(np.mean([r[k] for r in rows])), 4) for k in rows[0]}; print(arm, out[arm], flush=True)
Path(sys.argv[1]).write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
