"""f2_sampler 与探针版内联逻辑的行为对比；HEAD 的 evaluate 对探针逐事件数据回归。"""
import importlib.util, json, os, sys
from pathlib import Path
import numpy as np
root = Path(os.environ["REVIEW_ROOT"]).resolve()
spec_ = importlib.util.spec_from_file_location("runner_copy", root / "reports/V9-S3-PHASE2/run_phase2.py"); M = importlib.util.module_from_spec(spec_); spec_.loader.exec_module(M)
from ainerzero.v9.experiments.s3 import analysis_p2 as G, batching as B, replay as RP, spec
assert Path(G.__file__).resolve().is_relative_to(root)
def tagged(n, tag):
    return [B.PreparedEpisode(obs=np.zeros((10, spec.OBS_DIM), dtype=np.float32), query_t=np.array([6, 7, 8], dtype=np.int32), top1=np.array([1, 2, 3], dtype=np.int32), oracle=np.array([1, 2, 3], dtype=np.int32), shuffled=np.array([0, 1, 2], dtype=np.int32), candidates=np.zeros((3, 12), dtype=np.int32), cand_feats=np.zeros((3, 12, 3), dtype=np.float32), cand_mask=np.ones((3, 12), dtype=bool), answer=np.array([tag * 100000 + i, tag * 100000 + i + 50000, tag * 100000 + i + 90000], dtype=np.int32), swapped=np.ones(3, dtype=bool), bucket=np.full(3, 3, dtype=np.int32)) for i in range(n)]
tr1, tr2 = tagged(1600, 1), tagged(1600, 2)
def old_inline(how, seed, stage):
    """59ed20d run_phase2.py 主循环里的原文逻辑。"""
    order_cap = len(tr1) if stage == "smoke" else None
    if how == "none":
        return M.pick(tr2, M.BATCH), None
    cap = 64 if how == "CN" else int(how[1:])
    cap = min(cap, order_cap) if order_cap else cap
    buf = [tr1[j] for j in RP.buffer_indices(len(tr1), cap, M.BUFFER_SEED + seed)]
    if how == "CN":
        buf = RP.permute_answers(buf, M.CN_SEED + seed)
    return M.mixed(tr2, buf, M.MIX, M.MIX), len(buf)
ident = lambda b: [tuple(e.answer.tolist()) for e in b]
checked = bad = 0
for how in ("none", "R16", "R64", "R256", "CN"):
    for seed in (1, 2, 3):
        for stage in ("probe", "dev", "final"):
            o, no = old_inline(how, seed, stage); n, nn = M.f2_sampler(how, tr1, tr2, seed, clamp=stage == "smoke")
            if how != "none" and no != nn: bad += 1
            for s in range(25):
                checked += 1; bad += ident(o(np.random.default_rng(s))) != ident(n(np.random.default_rng(s)))
print(json.dumps({"sampler_batches_compared": checked, "differences": bad}))
A = Path("/Users/mac/AinerWorkFlow/AinerZero/artifacts/v9/s3/phase2/probe-p1"); J = json.loads((root / "reports/V9-S3-PHASE2/probe-p1.json").read_text()); old = J["result"]; S = (1, 2, 3)
per = {}
for c in sorted({k.rsplit("/", 1)[0] for k in J["cells"]}):
    for s in S:
        for ph in ("F1", "F1_after", "F2"):
            p = A / f"{c}-s{s}-{ph}.npz"
            if p.exists():
                with np.load(p) as d: per[c, s, ph] = {k: d[k] for k in d.files}
new = G.evaluate(per, S, capacity=64, has_a1=False)
def cmp(a, b, path=""):
    if isinstance(a, dict):
        out = []
        for k in a:
            if k not in b: out.append(path + "/" + k + " missing_in_new"); continue
            out += cmp(a[k], b[k], path + "/" + k)
        return out
    return [] if (a == b or (isinstance(a, float) and abs(a - b) < 1e-12)) else [f"{path}: {a} != {b}"]
print(json.dumps({"regression_diffs_vs_probe_json": cmp(old, new), "added_keys": sorted(set(new) - set(old)), "h3_added": sorted(set(new["h3_prime"]) - set(old["h3_prime"])), "claims": new["claims"], "replay_minus_cn_8class": {k: round(new["h3_prime"]["replay_minus_cn_8class"][k], 4) for k in ("delta", "ci_low", "ci_high")}}, ensure_ascii=False))
inv = G.invalidated(new, "x"); print(json.dumps({"invalidated_claims": inv["claims"], "valid": inv["valid"], "reason": inv["invalid_reason"], "h2_pass_kept": inv["h2"]["pass"]}))
