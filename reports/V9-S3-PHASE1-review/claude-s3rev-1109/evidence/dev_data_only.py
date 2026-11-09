"""只算数据、不碰模型：核对 dev1 的事件数、分区不重叠、静默丢弃。P208 第二路。

不评估任何模型，不产生准确率。final 只算 derive_seed（不生成世界）。
"""
import collections, json, os, sys
from pathlib import Path
import ainerzero
root = Path(os.environ["REVIEW_ROOT"]).resolve()
assert Path(ainerzero.__file__).resolve().is_relative_to(root), ainerzero.__file__
from ainerzero.v9.experiments.s3 import batching as B, data as D, spec
from ainerzero.v9.experiments.s2.world import make_layout
LONG = spec.BUCKET_LONG
def build(ns, tag, nw, ne, fam, base):
    n_prim = n_uns = n_ev = n_kept = n_ep = n_ep_prim = 0; dropped_buckets = collections.Counter()
    for w in range(nw):
        for e in range(ne):
            ep = D.generate_episode(D.derive_seed(ns, tag + "world", w), D.derive_seed(ns, tag + "ep", w, e), family=fam)
            p = B.prepare_episode(ep, 1.0, perm_seed=base + w * 100 + e)
            n_ev += len(ep["events"]); n_kept += len(p.query_t); n_ep += 1 if len(p.query_t) else 0
            kept = set(p.query_t.tolist())
            for v in ep["events"]:
                if v["t"] not in kept: dropped_buckets[str(v["bucket"])] += 1
            l = p.bucket == B.BUCKET_CODE[LONG]
            k = int((l & p.swapped).sum()); n_prim += k; n_uns += int((l & ~p.swapped).sum()); n_ep_prim += 1 if k else 0
    return dict(episodes_kept=n_ep, events_total=n_ev, events_kept=n_kept, dropped_by_bucket=dict(dropped_buckets), n_primary=n_prim, n_unswapped=n_uns, episodes_with_primary=n_ep_prim)
out = {"dev_F1": build(spec.NAMESPACE_DEV, "", 50, 2, "F1", 20_000_000), "dev_F2": build(spec.NAMESPACE_DEV, "f2-", 50, 2, "F2", 30_000_000)}
print(json.dumps(out, ensure_ascii=False, indent=1), flush=True)
def seeds(ns, tag, nw, ne):
    return {"world": {D.derive_seed(ns, tag + "world", w) for w in range(nw)}, "ep": {D.derive_seed(ns, tag + "ep", w, e) for w in range(nw) for e in range(ne)}}
parts = {"train_F1": seeds(spec.NAMESPACE_TRAIN, "", 400, 4), "train_F2": seeds(spec.NAMESPACE_TRAIN, "f2-", 400, 4), "dev_F1": seeds(spec.NAMESPACE_DEV, "", 50, 2), "dev_F2": seeds(spec.NAMESPACE_DEV, "f2-", 50, 2), "final_F1": seeds(spec.NAMESPACE_FINAL, "", 100, 2), "final_F2": seeds(spec.NAMESPACE_FINAL, "f2-", 100, 2), "probe": seeds(spec.NAMESPACE_PROBE, "", 100, 1), "probe_diag": seeds(spec.NAMESPACE_PROBE, "diag-", 100, 1)}
coll = {}
names = sorted(parts)
for i, a in enumerate(names):
    for b in names[i + 1:]:
        for k in ("world", "ep"):
            n = len(parts[a][k] & parts[b][k])
            if n: coll[f"{a}&{b}:{k}"] = n
print("seed_collisions", coll, flush=True)
lay = {}
for name, ns, tag, nw in (("train_F1", spec.NAMESPACE_TRAIN, "", 400), ("train_F2", spec.NAMESPACE_TRAIN, "f2-", 400), ("dev_F1", spec.NAMESPACE_DEV, "", 50), ("dev_F2", spec.NAMESPACE_DEV, "f2-", 50), ("probe", spec.NAMESPACE_PROBE, "", 100)):
    lay[name] = {make_layout(D.derive_seed(ns, tag + "world", w)).layout_sha256 for w in range(nw)}
print("distinct_layouts", {k: len(v) for k, v in lay.items()}, flush=True)
over = {}
ln = sorted(lay)
for i, a in enumerate(ln):
    for b in ln[i + 1:]:
        over[f"{a}&{b}"] = len(lay[a] & lay[b])
print("layout_overlap", over, flush=True)
