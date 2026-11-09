"""重算 h3_class_bias（probe 分区，只读权重，不拿锁、不写 artifacts）。P208 第二路。"""
import json, os, sys
from pathlib import Path
import numpy as np
import ainerzero
root = Path(os.environ["REVIEW_ROOT"]).resolve(); assert Path(ainerzero.__file__).resolve().is_relative_to(root)
import mlx.core as mx
mx.set_default_device(mx.cpu)
from ainerzero.v9.experiments.s3 import arms_mlx as A, batching as B, data as D, spec
W = Path("/Users/mac/AinerWorkFlow/AinerZero/artifacts/v9/s3/phase1")
NS = spec.NAMESPACE_PROBE; LONG = B.BUCKET_CODE[spec.BUCKET_LONG]
ev = []
for w in range(100):
    ep = D.generate_episode(D.derive_seed(NS, "diag-world", w), D.derive_seed(NS, "diag-ep", w, 0), family="F1")
    p = B.prepare_episode(ep, 1.0, perm_seed=70_000_000 + w)
    if len(p.query_t): ev.append(p)
f1 = np.array(sorted(spec.F1_TOKENS)); out = {}
for arm in ("A0", "A1", "A2", "A3"):
    rows = []
    for s in (1, 2, 3):
        m = A.ReadoutArm(arm); m.load_weights(str(W / f"dev-dev1-{arm}-s{s}.npz")); mx.eval(m.parameters())
        C0, C1, Sw, Bk = [], [], [], []
        for i in range(0, len(ev), 32):
            b = B.collate(ev[i:i + 32]); lg, _ = A.forward(m, {k: mx.array(v) for k, v in b.items()}, hard=True); lg = np.asarray(lg)
            C0.append(lg.argmax(-1) == b["answer"]); C1.append(f1[lg[:, f1].argmax(-1)] == b["answer"]); Sw.append(b["swapped"]); Bk.append(b["bucket"])
        c0, c1, sw, bk = map(np.concatenate, (C0, C1, Sw, Bk)); l = bk == LONG
        rows.append({"open_primary": float(c0[l & sw].mean()), "f1_only_primary": float(c1[l & sw].mean())})
    out[arm] = {k: round(float(np.mean([r[k] for r in rows])), 4) for k in rows[0]}
print(json.dumps(out, ensure_ascii=False))
ref = json.loads(Path("/Users/mac/AinerWorkFlow/AinerZero/reports/V9-S3-PHASE1/diagnosis/h3_class_bias.json").read_text())
print("ref", json.dumps(ref, ensure_ascii=False))
