"""从 F1 权重重做前向，核对 npz 的 pred 与事件来自声称的模型和 s3p2-probe 数据。只读权重，持真实锁（非阻塞），MLX CPU，无训练。"""
import fcntl, json, marshal, os, sys, types
from pathlib import Path
import numpy as np
import ainerzero
root = Path(os.environ["REVIEW_ROOT"]).resolve(); assert Path(ainerzero.__file__).resolve().is_relative_to(root), ainerzero.__file__
import mlx.core as mx, mlx.nn as nn
from mlx.utils import tree_flatten
mx.set_default_device(mx.cpu)
from ainerzero.v9.experiments.s3 import arms_mlx as A, arms_p2_mlx as P, batching as B, data as D, replay as RP, spec
RR = Path("/Users/mac/AinerWorkFlow/AinerZero"); ART = RR / "artifacts/v9/s3/phase2/probe-p1"; J = json.loads((RR / "reports/V9-S3-PHASE2/probe-p1.json").read_text())
lock = (RR / "artifacts/locks/m0-worker.lock").open("a+"); fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
NS = "s3p2-probe"; SEEDS = (1, 2, 3); OUT = {}
def build(tag, fam, base):
    out, raw = [], []
    for w in range(100):
        for e in range(2):
            ep = D.generate_episode(D.derive_seed(NS, tag + "world", w), D.derive_seed(NS, tag + "ep", w, e), family=fam)
            seed = base + w * 100 + e
            p = B.prepare_episode(ep, 1.0, perm_seed=seed)
            if not len(p.query_t): continue
            rng = np.random.default_rng(7_200_000 + seed)
            drawn = np.array([int(rng.integers(0, int(t) - 5 + 1)) for t in p.query_t], dtype=np.int32)
            assert np.array_equal(drawn, RP.past_only_shuffle(p, 7_200_000 + seed).shuffled)
            import dataclasses
            out.append(dataclasses.replace(p, shuffled=drawn)); raw.append(ep)
    return out, raw
ev1, raw1 = build("", "F1", 20_000_000); ev2, raw2 = build("f2-", "F2", 30_000_000)
OUT["episodes"] = {"F1": len(ev1), "F2": len(ev2)}
def meta(eps):
    return {"ep": np.concatenate([np.full(len(p.query_t), i) for i, p in enumerate(eps)]), "query_t": np.concatenate([p.query_t for p in eps]), "answer": np.concatenate([p.answer for p in eps]), "swapped": np.concatenate([p.swapped for p in eps]), "bucket": np.concatenate([p.bucket for p in eps])}
def load(c, s, ph):
    with np.load(ART / f"{c}-s{s}-{ph}.npz") as d: return {k: d[k] for k in d.files}
m1, m2 = meta(ev1), meta(ev2)
OUT["event_identity_F1"] = {k: bool(np.array_equal(m1[k], load("A0", 1, "F1")[k])) for k in m1}
OUT["event_identity_F2"] = {k: bool(np.array_equal(m2[k], load("A2-C0", 1, "F2")[k])) for k in m2}
ARMS = {"A0": "A0", "O": "O", "N": "N", "A3S": "A3", "A2-C0": "A2", "A2-R16": "A2", "A2-R64": "A2", "A2-R256": "A2", "A2-CN": "A2", "A3H-C0": "A3", "A3H-R16": "A3", "A3H-R64": "A3", "A3H-R256": "A3"}
keep = np.zeros(spec.NUM_TOKEN_CLASSES, bool); keep[list(spec.F1_TOKENS)] = True
mism = {}; total = 0
for c, arm in ARMS.items():
    for s in SEEDS:
        m = A.ReadoutArm(arm); m.load_weights(str(ART / f"{c}-s{s}-F1.npz.weights.npz")); mx.eval(m.parameters())
        P_, P8 = [], []
        for i in range(0, len(ev1), 32):
            b = B.collate(ev1[i:i + 32]); lg, _ = A.forward(m, {k: mx.array(v) for k, v in b.items()}, hard=True); mx.eval(lg); L = np.asarray(lg)
            P_.append(L.argmax(-1)); P8.append(np.where(keep, L, -np.inf).argmax(-1))
        pred, pred8 = np.concatenate(P_), np.concatenate(P8); r = load(c, s, "F1"); total += 1
        if not np.array_equal(pred, r["pred"]) or not np.array_equal(pred8, r["pred_8"]): mism[f"{c}/{s}"] = int((pred != r["pred"]).sum())
OUT["forward_reproduced_cells"] = total; OUT["forward_mismatches"] = mism
# 零状态
m = A.ReadoutArm("A2"); m.load_weights(str(ART / "A2-C0-s1-F1.npz.weights.npz")); mx.eval(m.parameters())
Z = []
for i in range(0, len(ev1), 32):
    b = B.collate(ev1[i:i + 32]); lg = P.zero_memory_logits(m, {k: mx.array(v) for k, v in b.items()}); mx.eval(lg); Z.append(np.asarray(lg).argmax(-1) == b["answer"])
Z = np.concatenate(Z); r = load("A2-C0", 1, "F1"); zs = {}
for code, name in {1: "short", 2: "mid", 3: "long"}.items():
    s = r["bucket"] == code; zs[name] = {"memory": float(r["correct"][s].mean()), "zero": float(Z[s].mean())}
ref = J["cells"]["A2-C0/1"]["zero_state"]
OUT["zero_state_match"] = {k: abs(zs[k]["memory"] - ref[k]["memory"]) < 1e-12 and abs(zs[k]["zero"] - ref[k]["zero"]) < 1e-12 for k in zs}
# 检索诊断，独立实现严格命中
vis = lambda o: o[:spec.VIEW_FEAT_DIM].reshape(9, spec.CELL_FEAT_DIM)[:, spec.NUM_TERRAIN_CLASSES:].argmax(1)
def strict(ep, e, cand):
    c = tuple(e["cell"]); pos = lambda t: (int(ep["steps"][t]["truth"]["x"]), int(ep["steps"][t]["truth"]["y"]))
    a = e["prev_visit_t"]
    while a > 0 and pos(a - 1) == c: a -= 1
    return a <= cand <= e["prev_visit_t"]
rows = []
for p, ep in zip(ev1, raw1):
    by = {int(e["t"]): e for e in ep["events"]}
    for i, t in enumerate(p.query_t.tolist()):
        if not (p.bucket[i] == 3 and p.swapped[i]): continue
        e, a, top = by[t], int(p.answer[i]), int(p.top1[i]); cs = [int(c) for c, ma in zip(p.candidates[i], p.cand_mask[i]) if ma]
        rows.append((strict(ep, e, top), any(strict(ep, e, c) for c in cs), a in vis(p.obs[top]), any(a in vis(p.obs[c]) for c in cs)))
a = np.array(rows, dtype=float).mean(0); rt = J["retrieval"]["F1"]
OUT["retrieval"] = {"n": len(rows), "mine": [round(float(x), 6) for x in a], "report": [round(rt[k], 6) for k in ("top1_strict", "pool_strict", "top1_visible", "pool_visible")]}
# 硬采样路径泄漏：未来观察、标签、真值
b = {k: mx.array(v) for k, v in B.collate(ev1[:8]).items()}
m = A.ReadoutArm("A3"); m.load_weights(str(ART / "A3H-C0-s1-F1.npz.weights.npz")); mx.eval(m.parameters())
key = mx.random.key(5)
def lg(bb):
    x, aux = P.a3_sampled_forward(m, bb, key); mx.eval(x, aux); return np.asarray(x), float(aux)
base, aux = lg(b); rng = np.random.default_rng(1); n = b["query_t"].shape[0]
other = dict(b); other["answer"] = mx.array(rng.integers(1, 17, size=n), dtype=mx.int32); other["oracle"] = mx.array(rng.integers(0, 360, size=n), dtype=mx.int32); other["swapped"] = mx.array(rng.random(n) < .5); other["bucket"] = mx.array(rng.integers(0, 4, size=n), dtype=mx.int32); other["top1"] = mx.array(rng.integers(0, 360, size=n), dtype=mx.int32); other["shuffled"] = mx.array(rng.integers(0, 360, size=n), dtype=mx.int32)
x2, aux2 = lg(other)
OUT["sampled_logits_ignore_labels_truth"] = bool(np.array_equal(base, x2)); OUT["sampled_aux_depends_on_answer"] = aux != aux2
obs0, ep_, q = np.array(b["obs"]), np.array(b["ep"]), np.array(b["query_t"]); bad = 0
for i in range(0, n, max(1, n // 25)):
    o = obs0.copy(); o[ep_[i], int(q[i]) + 1:] = 1 - o[ep_[i], int(q[i]) + 1:]; bb = dict(b); bb["obs"] = mx.array(o)
    x3, _ = lg(bb)
    bad += not np.array_equal(base[i], x3[i])
OUT["sampled_future_obs_changed_event"] = bad
# 探针后的代码：真实旧字节码 vs 当前代码
S3 = RR / "src/ainerzero/v9/experiments/s3/__pycache__"
def old(name):
    bc = (S3 / f"{name}.cpython-312.pyc").read_bytes(); mod = types.ModuleType("old_" + name); exec(marshal.loads(bc[16:]), mod.__dict__); return mod
OP, OR = old("arms_p2_mlx"), old("replay")
batch = {k: mx.array(v) for k, v in B.collate(ev1[:16]).items()}
ident = {"sample": 0, "forward": 0, "loss_grad": 0, "keys": 40, "params_compared": 0}
for wname in ("A3H-C0-s1-F1", None):
    mm = A.ReadoutArm("A3")
    if wname: mm.load_weights(str(ART / f"{wname}.npz.weights.npz"))
    else: mx.random.seed(11); mm = A.ReadoutArm("A3")
    mx.eval(mm.parameters())
    for s in range(20):
        k = mx.random.key(s)
        scores = mx.array(np.random.default_rng(s).normal(size=(64, 12)), dtype=mx.float32); mask = mx.array(np.random.default_rng(s).random((64, 12)) < .7)
        ident["sample"] += not np.array_equal(np.asarray(OP.sample_candidate(scores, mask, k)), np.asarray(P.sample_candidate(scores, mask, k)))
        a1 = OP.a3_sampled_forward(mm, batch, k); a2 = P.a3_sampled_forward(mm, batch, k); mx.eval(a1, a2)
        ident["forward"] += not (np.array_equal(np.asarray(a1[0]), np.asarray(a2[0])) and float(a1[1]) == float(a2[1]))
        l1, g1 = nn.value_and_grad(mm, OP.a3_sampled_loss)(mm, batch, k); l2, g2 = nn.value_and_grad(mm, P.a3_sampled_loss)(mm, batch, k); mx.eval(l1, l2, g1, g2)
        f1, f2 = dict(tree_flatten(g1)), dict(tree_flatten(g2)); ident["params_compared"] = len(f1)
        ident["loss_grad"] += not (float(l1) == float(l2) and all(np.array_equal(np.asarray(f1[x]), np.asarray(f2[x])) for x in f1))
OUT["old_pyc_vs_current_arms_p2_differences"] = ident
diffs = 0; cases = 0; boundary = {}
for p in ev1 + ev2:
    for sd in (0, 1, 2):
        cases += 1; diffs += not np.array_equal(OR.past_only_shuffle(p, sd).shuffled, RP.past_only_shuffle(p, sd).shuffled)
import dataclasses
for t0 in (0, 1, 3, 4, 5, 6):
    q = dataclasses.replace(ev1[0], query_t=np.array([t0], dtype=np.int32), top1=ev1[0].top1[:1], oracle=ev1[0].oracle[:1], shuffled=ev1[0].shuffled[:1])
    res = []
    for f in (OR.past_only_shuffle, RP.past_only_shuffle):
        try: res.append(("ok", int(f(q, 1).shuffled[0])))
        except Exception as e: res.append((type(e).__name__, ""))
    boundary[t0] = res
OUT["old_pyc_vs_current_replay"] = {"cases": cases, "differences": diffs, "boundary": boundary}
for fn in ("buffer_indices", "permute_answers"):
    pass
print(json.dumps(OUT, ensure_ascii=False, indent=1, default=str)); Path(sys.argv[1]).write_text(json.dumps(OUT, ensure_ascii=False, indent=1, default=str))
fcntl.flock(lock, fcntl.LOCK_UN)
