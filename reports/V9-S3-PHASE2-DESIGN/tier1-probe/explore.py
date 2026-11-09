"""S3 第二阶段设计前的一级探索。未登记，只用来定设计，不作任何结论。

只用 s3p1-train 训练、s3p1-probe 评测，不碰 dev、final。不改任何冻结文件。
问三件事：
  1. 候选池的天花板：完美打分头最多能拿到多少（纯数据，不训练）。
  2. 学习检索：训练时硬采样单条（与评测一致）是否好于软混合；多少步收敛。
  3. 换世界族后的保护：有界回放、参数锚定、联合训练各能挡住多少遗忘。
持 m0-worker.lock（MLX CPU）。
"""
import fcntl, json, pickle, sys, time
from pathlib import Path
import numpy as np

REPO = Path("/Users/mac/AinerWorkFlow/AinerZero"); sys.path.insert(0, str(REPO / "src"))
import mlx.core as mx, mlx.nn as nn, mlx.optimizers as optim
from mlx.utils import tree_flatten
from ainerzero.v9.experiments.s3 import arms_mlx as A, batching as B, data as D, spec

OUT = Path(__file__).resolve().parent
CACHE = Path(sys.argv[1]) if len(sys.argv) > 1 else None
LONG = B.BUCKET_CODE[spec.BUCKET_LONG]
SEEDS = (1, 2)
BATCH, LR, LAM = 16, 1e-3, 1.0
T0 = time.monotonic()
R = {"note": "一级探索，未登记，只用 train/probe", "ceiling": {}, "curves": {}, "protection": {}}


def say(*x): print(f"[{time.monotonic() - T0:8.1f}s]", *x, flush=True)
def save(): (OUT / "results.json").write_text(json.dumps(R, ensure_ascii=False, indent=1), encoding="utf-8")


def build(ns, tag, n_w, n_e, family, base):
    out = []
    for w in range(n_w):
        for e in range(n_e):
            ep = D.generate_episode(D.derive_seed(ns, tag + "world", w), D.derive_seed(ns, tag + "ep", w, e), family=family)
            p = B.prepare_episode(ep, LAM, perm_seed=base + w * 100 + e)
            if len(p.query_t): out.append(p)
    return out


def load():
    if CACHE and CACHE.is_file():
        return pickle.loads(CACHE.read_bytes())
    d = {
        "tr1": build(spec.NAMESPACE_TRAIN, "", 400, 4, "F1", 0),
        "tr2": build(spec.NAMESPACE_TRAIN, "f2-", 400, 4, "F2", 10_000_000),
        "ev1": build(spec.NAMESPACE_PROBE, "explore-", 200, 2, "F1", 40_000_000),
        "ev2": build(spec.NAMESPACE_PROBE, "explore-f2-", 200, 2, "F2", 50_000_000),
    }
    if CACHE: CACHE.write_bytes(pickle.dumps(d))
    return d


def visible(o):
    return o[:spec.VIEW_FEAT_DIM].reshape(9, spec.CELL_FEAT_DIM)[:, spec.NUM_TERRAIN_CLASSES:].argmax(1)


def ceiling(eps):
    rows = []
    for p in eps:
        for i in range(len(p.query_t)):
            a = int(p.answer[i])
            top, ora = visible(p.obs[p.top1[i]]), visible(p.obs[p.oracle[i]])
            cs = [visible(p.obs[c]) for c, m in zip(p.candidates[i], p.cand_mask[i]) if m]
            rows.append({
                "long": p.bucket[i] == LONG, "swapped": bool(p.swapped[i]),
                "oracle_any": a in ora, "oracle_center": ora[4] == a,
                "top1_any": a in top, "top1_center": top[4] == a,
                "pool_any": any(a in c for c in cs), "pool_center": any(c[4] == a for c in cs),
                "pool_size": len(cs),
            })
    out = {}
    for name, f in (("long_swapped", lambda r: r["long"] and r["swapped"]), ("long_unswapped", lambda r: r["long"] and not r["swapped"])):
        s = [r for r in rows if f(r)]
        out[name] = {k: float(np.mean([r[k] for r in s])) for k in ("oracle_any", "oracle_center", "top1_any", "top1_center", "pool_any", "pool_center", "pool_size")} | {"n": len(s)}
    return out


def to_mx(b): return {k: mx.array(v) for k, v in b.items()}


def forward_a3_sampled(model, b):
    """A3 训练：读出头看按打分采样的单条记录，与评测看单条一致。打分头目标不变。"""
    ep, t = b["ep"], b["query_t"]
    z_q = model.encode(b["obs"][ep, t])
    cand, mask = b["candidates"], b["cand_mask"]
    safe = mx.where(cand < 0, mx.zeros_like(cand), cand)
    n, k = cand.shape
    ep_k = mx.broadcast_to(ep[:, None], (n, k))
    z_c = model.encode(b["obs"][ep_k, safe])
    m_c = model.project(z_c)
    z_q_k = mx.broadcast_to(z_q[:, None, :], (n, k, z_q.shape[-1]))
    s = model.score(b["cand_feats"], mx.stop_gradient(z_q), mx.stop_gradient(z_c))
    y_k = mx.broadcast_to(b["answer"][:, None], (n, k))
    ce_c = nn.losses.cross_entropy(model.readout(z_q_k, m_c), y_k, reduction="none")
    util = mx.stop_gradient(-ce_c)
    target = mx.exp(A._masked_log_softmax(util / A.UTILITY_TEMPERATURE, mask))
    aux = -(target * A._masked_log_softmax(s, mask)).sum(-1).mean()
    idx = mx.random.categorical(A._masked_log_softmax(mx.stop_gradient(s), mask))
    w = (mx.arange(k)[None, :] == idx[:, None]).astype(mx.float32)
    m = (w[..., None] * m_c).sum(1)
    return model.readout(z_q, m), aux


def loss_for(variant):
    if variant == "soft":
        return A.loss_fn
    def f(model, b):
        lg, aux = forward_a3_sampled(model, b)
        return nn.losses.cross_entropy(lg, b["answer"], reduction="mean") + aux
    return f


def train(m, opt, sample, steps, seed, loss=A.loss_fn):
    rng = np.random.default_rng(seed); vg = nn.value_and_grad(m, loss)
    for _ in range(steps):
        l, g = vg(m, to_mx(B.collate(sample(rng))))
        g, _ = optim.clip_grad_norm(g, 1.0); opt.update(m, g); mx.eval(m.parameters(), opt.state, l)
        if not np.isfinite(float(l)): raise FloatingPointError("loss not finite")


def pick(data, n): return lambda rng: [data[j] for j in rng.choice(len(data), size=n, replace=False)]


def mixed(a, b, na, nb):
    return lambda rng: [a[j] for j in rng.choice(len(a), size=na, replace=False)] + [b[j] for j in rng.choice(len(b), size=nb, replace=False)]


def evaluate(m, eps, tokens):
    C, Cm, Sw, Bk = [], [], [], []
    mask = np.zeros(spec.NUM_TOKEN_CLASSES, bool); mask[list(tokens)] = True
    for i in range(0, len(eps), 32):
        b = B.collate(eps[i:i + 32]); lg, _ = A.forward(m, to_mx(b), hard=True); mx.eval(lg); L = np.asarray(lg)
        C.append(L.argmax(-1) == b["answer"]); Cm.append(np.where(mask, L, -np.inf).argmax(-1) == b["answer"]); Sw.append(b["swapped"]); Bk.append(b["bucket"])
    C, Cm, Sw, Bk = map(np.concatenate, (C, Cm, Sw, Bk)); l = Bk == LONG
    return {"primary": float(C[l & Sw].mean()), "primary_masked": float(Cm[l & Sw].mean()), "unswapped": float(C[l & ~Sw].mean()), "unswapped_masked": float(Cm[l & ~Sw].mean()), "n": int((l & Sw).sum())}


def fresh(arm, seed):
    mx.random.seed(seed); m = A.ReadoutArm(arm); mx.eval(m.parameters()); return m, optim.Adam(learning_rate=LR)


def main():
    d = load(); say("data", {k: len(v) for k, v in d.items()})
    R["ceiling"] = {"F1": ceiling(d["ev1"]), "F2": ceiling(d["ev2"])}; save(); say("ceiling", json.dumps(R["ceiling"]["F1"]["long_swapped"]))
    lock = (REPO / "artifacts/locks/m0-worker.lock").open("a+"); fcntl.flock(lock, fcntl.LOCK_EX); say("lock held")
    mx.set_default_device(mx.cpu)
    tr1, tr2, ev1, ev2 = d["tr1"], d["tr2"], d["ev1"], d["ev2"]

    # 收敛曲线：同一模型逐段加训。
    for name, arm, loss in (("A2", "A2", A.loss_fn), ("A3soft", "A3", A.loss_fn), ("A3hard", "A3", loss_for("hard"))):
        for s in SEEDS:
            m, opt = fresh(arm, s); done = 0; cur = {}
            for ck in (1000, 2000, 4000, 8000):
                train(m, opt, pick(tr1, BATCH), ck - done, s * 1000 + ck, loss); done = ck
                cur[str(ck)] = evaluate(m, ev1, spec.F1_TOKENS)
            R["curves"][f"{name}/{s}"] = cur; save(); say("curve", name, s, {k: round(v["primary"], 3) for k, v in cur.items()})

    # 保护：F1 3000 步后接 F2 1500 步。
    F1S, F2S = 3000, 1500
    def run(name, arm, f1_loss, how, seed):
        m, opt = fresh(arm, seed)
        if how == "joint":
            train(m, opt, mixed(tr1, tr2, 8, 8), F1S + F2S, seed + 10, f1_loss)
            before = None
        else:
            train(m, opt, pick(tr1, BATCH), F1S, seed + 10, f1_loss)
            before = evaluate(m, ev1, spec.F1_TOKENS)
            rng = np.random.default_rng(seed + 500)
            if how == "none":
                train(m, opt, pick(tr2, BATCH), F2S, seed + 20, f1_loss)
            elif how.startswith("R"):
                n = int(how[1:]); buf = [tr1[j] for j in rng.choice(len(tr1), size=n, replace=False)]
                train(m, opt, mixed(tr2, buf, 8, 8), F2S, seed + 20, f1_loss)
            elif how.startswith("L2-"):
                lam = float(how[3:]); anchor = [mx.array(v) for _, v in tree_flatten(m.trainable_parameters())]; mx.eval(anchor)
                def reg(model, b):
                    extra = sum(mx.sum((v - a) ** 2) for (_, v), a in zip(tree_flatten(model.trainable_parameters()), anchor))
                    return f1_loss(model, b) + lam * extra
                train(m, opt, pick(tr2, BATCH), F2S, seed + 20, reg)
            else:
                raise ValueError(how)
        r = {"before": before, "after": evaluate(m, ev1, spec.F1_TOKENS), "f2": evaluate(m, ev2, spec.F2_TOKENS)}
        R["protection"][f"{name}/{how}/{seed}"] = r; save()
        say("prot", name, how, seed, "before", None if before is None else round(before["primary"], 3), "after", round(r["after"]["primary"], 3), "masked", round(r["after"]["primary_masked"], 3), "f2", round(r["f2"]["primary"], 3))

    for how in ("none", "R16", "R64", "R256", "L2-1", "L2-10", "joint"):
        for s in SEEDS: run("A2", "A2", A.loss_fn, how, s)
    for how in ("none", "R64", "R256", "joint"):
        for s in SEEDS: run("A3hard", "A3", loss_for("hard"), how, s)
    R["elapsed_s"] = round(time.monotonic() - T0, 1); save(); say("done"); fcntl.flock(lock, fcntl.LOCK_UN)


main()
