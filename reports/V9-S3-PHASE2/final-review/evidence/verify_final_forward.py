"""从 F1、F2 结束的权重重做前向，核对 final npz。持真实锁（非阻塞），MLX CPU，无训练，只读权重。"""
import dataclasses, fcntl, json, os, sys, time
from pathlib import Path
import numpy as np
import ainerzero
root = Path(os.environ["REVIEW_ROOT"]).resolve(); assert Path(ainerzero.__file__).resolve().is_relative_to(root), ainerzero.__file__
import mlx.core as mx
mx.set_default_device(mx.cpu)
from ainerzero.v9.experiments.s3 import arms_mlx as A, arms_p2_mlx as P, batching as B, data as D, spec
RR = Path("/Users/mac/AinerWorkFlow/AinerZero"); ART = RR / "artifacts/v9/s3/phase2/final-final"; J = json.loads((RR / "reports/V9-S3-PHASE2/final.json").read_text())
lock = (RR / "artifacts/locks/m0-worker.lock").open("a+"); fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB); t0 = time.time()
NS = "s3p2b-final"; SEEDS = (1, 2, 3); O = {}
def build(tag, fam, base):
    out, raw = [], []
    for w in range(100):
        for e in range(2):
            ep = D.generate_episode(D.derive_seed(NS, tag + "world", w), D.derive_seed(NS, tag + "ep", w, e), family=fam)
            seed = base + w * 100 + e
            p = B.prepare_episode(ep, 1.0, perm_seed=seed)
            if not len(p.query_t): continue
            rng = np.random.default_rng(7_200_000 + seed)
            out.append(dataclasses.replace(p, shuffled=np.array([int(rng.integers(0, int(t) - 5 + 1)) for t in p.query_t], dtype=np.int32))); raw.append(ep)
    return out, raw
ev1, raw1 = build("", "F1", 20_000_000); ev2, raw2 = build("f2-", "F2", 30_000_000)
O["episodes"] = {"F1": len(ev1), "F2": len(ev2)}
def meta(eps):
    return {"ep": np.concatenate([np.full(len(p.query_t), i) for i, p in enumerate(eps)]), "query_t": np.concatenate([p.query_t for p in eps]), "answer": np.concatenate([p.answer for p in eps]), "swapped": np.concatenate([p.swapped for p in eps]), "bucket": np.concatenate([p.bucket for p in eps])}
def load(c, s, ph):
    with np.load(ART / f"{c}-s{s}-{ph}.npz") as d: return {k: d[k] for k in d.files}
m1, m2 = meta(ev1), meta(ev2)
O["event_identity_F1"] = {k: bool(np.array_equal(m1[k], load("A0", 1, "F1")[k])) for k in m1}; O["event_identity_F2"] = {k: bool(np.array_equal(m2[k], load("A2-C0", 1, "F2")[k])) for k in m2}
def forward(m, eps, tokens):
    keep = np.zeros(spec.NUM_TOKEN_CLASSES, bool); keep[list(tokens)] = True; P1, P8 = [], []
    for i in range(0, len(eps), 32):
        b = B.collate(eps[i:i + 32]); lg, _ = A.forward(m, {k: mx.array(v) for k, v in b.items()}, hard=True); mx.eval(lg); L = np.asarray(lg)
        P1.append(L.argmax(-1)); P8.append(np.where(keep, L, -np.inf).argmax(-1))
    return np.concatenate(P1), np.concatenate(P8)
def model(arm, c, s, suf):
    m = A.ReadoutArm(arm); m.load_weights(str(ART / f"{c}-s{s}-{suf}.weights.npz")); mx.eval(m.parameters()); return m
F1_ARMS = {"A0": "A0", "O": "O", "N": "N", "A1": "A1", "A3S": "A3", "A2-C0": "A2", "A2-R16": "A2", "A2-R64": "A2", "A2-R256": "A2", "A2-CN": "A2", "A3H-C0": "A3", "A3H-R16": "A3", "A3H-R64": "A3", "A3H-R256": "A3"}
END_ARMS = {"A2-C0": "A2", "A2-R16": "A2", "A2-R64": "A2", "A2-R256": "A2", "A2-CN": "A2", "A2-J": "A2", "A3H-C0": "A3", "A3H-R16": "A3", "A3H-R64": "A3", "A3H-R256": "A3", "A3H-J": "A3"}
miss = {}; cnt = {"F1": 0, "F1_after": 0, "F2": 0}
def check(tag, p, p8, r):
    if not (np.array_equal(p, r["pred"]) and np.array_equal(p8, r["pred_8"])): miss[tag] = int((p != r["pred"]).sum())
for c, arm in F1_ARMS.items():
    for s in SEEDS:
        p, p8 = forward(model(arm, c, s, "F1"), ev1, spec.F1_TOKENS); check(f"{c}/{s}/F1", p, p8, load(c, s, "F1")); cnt["F1"] += 1
for c, arm in END_ARMS.items():
    for s in SEEDS:
        m = model(arm, c, s, "end")
        p, p8 = forward(m, ev1, spec.F1_TOKENS); check(f"{c}/{s}/F1_after", p, p8, load(c, s, "F1_after")); cnt["F1_after"] += 1
        p, p8 = forward(m, ev2, spec.F2_TOKENS); check(f"{c}/{s}/F2", p, p8, load(c, s, "F2")); cnt["F2"] += 1
O["forward_reproduced"] = cnt; O["forward_mismatches"] = miss
# 零状态
m = model("A2", "A2-C0", 1, "F1"); Z = []
for i in range(0, len(ev1), 32):
    b = B.collate(ev1[i:i + 32]); lg = P.zero_memory_logits(m, {k: mx.array(v) for k, v in b.items()}); mx.eval(lg); Z.append(np.asarray(lg).argmax(-1) == b["answer"])
Z = np.concatenate(Z); r = load("A2-C0", 1, "F1"); ref = J["cells"]["A2-C0/1"]["zero_state"]; zs = {}
for code, name in {1: "short", 2: "mid", 3: "long"}.items():
    s = r["bucket"] == code; zs[name] = abs(float(r["correct"][s].mean()) - ref[name]["memory"]) < 1e-12 and abs(float(Z[s].mean()) - ref[name]["zero"]) < 1e-12
O["zero_state_match"] = zs
# 检索诊断（独立实现严格命中）
vis = lambda o: o[:spec.VIEW_FEAT_DIM].reshape(9, spec.CELL_FEAT_DIM)[:, spec.NUM_TERRAIN_CLASSES:].argmax(1)
def strict(ep, e, cand):
    c = tuple(e["cell"]); pos = lambda t: (int(ep["steps"][t]["truth"]["x"]), int(ep["steps"][t]["truth"]["y"])); a = e["prev_visit_t"]
    while a > 0 and pos(a - 1) == c: a -= 1
    return a <= cand <= e["prev_visit_t"]
def retr(eps, raws):
    rows = []
    for p, ep in zip(eps, raws):
        by = {int(e["t"]): e for e in ep["events"]}
        for i, t in enumerate(p.query_t.tolist()):
            if not (p.bucket[i] == 3 and p.swapped[i]): continue
            e, a, top = by[t], int(p.answer[i]), int(p.top1[i]); cs = [int(c) for c, ma in zip(p.candidates[i], p.cand_mask[i]) if ma]
            rows.append((strict(ep, e, top), any(strict(ep, e, c) for c in cs), a in vis(p.obs[top]), any(a in vis(p.obs[c]) for c in cs)))
    return len(rows), [float(x) for x in np.array(rows, dtype=float).mean(0)]
KEYS = ("top1_strict", "pool_strict", "top1_visible", "pool_visible"); O["retrieval"] = {}
for fam, (eps, raws) in {"F1": (ev1, raw1), "F2": (ev2, raw2)}.items():
    n, v = retr(eps, raws); rt = J["retrieval"][fam]; O["retrieval"][fam] = {"n": n, "mine": [round(x, 4) for x in v], "exact_match": n == rt["n"] and all(abs(x - rt[k]) < 1e-12 for x, k in zip(v, KEYS))}
# A3H 与 A3S 的打分头实际选到的记录（报告结论 2 的依据）
def scorer_pick(arm_cond, s):
    m = model("A3", arm_cond, s, "F1"); strictn = visn = n = 0
    for i in range(0, len(ev1), 32):
        eps = ev1[i:i + 32]; b0 = B.collate(eps); b = {k: mx.array(v) for k, v in b0.items()}; ep, t = b["ep"], b["query_t"]
        z_q = m.encode(b["obs"][ep, t]); cand, mask = b["candidates"], b["cand_mask"]; safe = mx.where(cand < 0, mx.zeros_like(cand), cand); nn_, k = cand.shape
        z_c = m.encode(b["obs"][mx.broadcast_to(ep[:, None], (nn_, k)), safe]); sc = m.score(b["cand_feats"], z_q, z_c); top = np.asarray(mx.argmax(mx.where(mask, sc, mx.array(-1e9)), axis=-1)); mx.eval(sc)
        for j in range(nn_):
            if not (b0["bucket"][j] == 3 and b0["swapped"][j]): continue
            e_idx = int(b0["ep"][j]); p = eps[e_idx]; ep_raw = raw1[i + e_idx]; qt = int(b0["query_t"][j]); ev = {int(x["t"]): x for x in ep_raw["events"]}[qt]; c = int(b0["candidates"][j, top[j]]); a = int(b0["answer"][j])
            n += 1; visn += a in vis(p.obs[c]); strictn += strict(ep_raw, ev, c)
    return n, strictn / n, visn / n
O["scorer_picks_F1"] = {c: [dict(zip(("n", "strict", "visible"), (lambda t: (t[0], round(t[1], 4), round(t[2], 4)))(scorer_pick(c, s)))) for s in SEEDS] for c in ("A3H-C0", "A3S")}
O["seconds"] = round(time.time() - t0, 1)
print(json.dumps(O, ensure_ascii=False, indent=1, default=str)); Path(sys.argv[1]).write_text(json.dumps(O, ensure_ascii=False, indent=1, default=str)); fcntl.flock(lock, fcntl.LOCK_UN)
