"""S3 第三阶段 final：复核者自己的整套重算（K2、K2b 一类核对加全部逐事件预测）。

只导入世界生成器与第一阶段冻结模块（persist、store.parse_student_step、data.derive_seed、spec），
不导入 promotion、analysis_p3、cues、run_phase3、verify_*。按 DESIGN-r2 §3 自己实现：驻留切分、认地方、
每回合一票、R2、版本与哈希、各策略（C、L、G、G-NR、MODE、G-perm、G-SR、U(α)、GT、LT）和各标记。
按种子重新生成 s3p3-final（这次允许），与 worlds.jsonl 和 5 个 events*.npz 逐项比对。只读，不写 artifacts/。

用法：independent_rerun.py <仓库根> <输出 json> [世界数]
"""
import collections, hashlib, json, random, sys, time
from pathlib import Path
import numpy as np

REPO, OUT = Path(sys.argv[1]), Path(sys.argv[2])
sys.path.insert(0, str(REPO / "src"))
from ainerzero.v9.experiments.s3 import persist as PS, spec  # noqa: E402
from ainerzero.v9.experiments.s3.data import derive_seed  # noqa: E402
from ainerzero.v9.experiments.s3.store import parse_student_step  # noqa: E402

NS = "s3p3-final"
A = REPO / "artifacts/v9/s3/phase3/final-final"
NW = int(sys.argv[3]) if len(sys.argv) > 3 else 200
T, TIE, GAP, DMAX, SCALE = spec.T, 1e-6, 5, 5.0, 49.0
ALPHAS = {"U0": 0.0, "U05": 0.5, "U1": 1.0, "U2": 2.0}
OFFS = (1, 2, 3, 5)
F1 = list(spec.F1_TOKENS)
assert not any(m.endswith(("s3.promotion", "s3.analysis_p3", "s3.cues")) for m in sys.modules)


def canon(o):
    return json.dumps(o, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def vhash(parent, e, items):
    return hashlib.sha256(canon({"parent": parent, "episode": e, "items": items}).encode()).hexdigest()


def pick(cands, cnt, votes):
    last = {k: max(i for i, x in enumerate(votes) if x == k) for k in cands}
    return max(cands, key=lambda k: (cnt[k], last[k]))


def r2(votes, slow, rollback):
    if slow is None:
        c = collections.Counter(votes); ok = [k for k, n in c.items() if n >= 2]
        return pick(ok, c, votes) if ok else None
    if not rollback:
        return slow
    last = max([i for i, x in enumerate(votes) if x == slow] or [-1])
    c = collections.Counter(votes[last + 1:]); ok = [k for k, n in c.items() if n >= 2 and k != slow]
    return pick(ok, c, votes) if ok else slow


def place(axy, ater, xy, ter):
    d = np.abs(axy - xy).sum(-1)
    sim = (ater == ter).mean(-1)
    return sim * SCALE * 1.0 - d, (d <= DMAX) & (sim >= 1.0)


class Store:
    def __init__(self, rollback):
        self.rb = rollback; self.xy = np.zeros((0, 2)); self.ter = np.zeros((0, 9), dtype=np.int8)
        self.votes, self.slow, self.cell, self.members = [], [], [], []
        self.versions = [{"parent": None, "episode": -1, "items": [], "hash": vhash(None, -1, [])}]
        self.c = collections.Counter()

    def best(self, xy, ter, slow_only):
        ids = np.array([i for i in range(len(self.slow)) if (self.slow[i] is not None or not slow_only)], dtype=np.int64)
        if len(ids) == 0:
            return None, False
        s, ok = place(self.xy[ids], self.ter[ids], xy, ter)
        if not ok.any():
            return None, False
        s = np.where(ok, s, -np.inf); j = int(np.argmax(s))
        return int(ids[j]), bool((s == s[j]).sum() > 1)

    def absorb(self, e, xy, ter, tok, cells):
        per = {}
        for i in range(len(tok)):
            j, tied = self.best(xy[i], ter[i], False)
            if j is None:
                j = len(self.slow)
                self.xy = np.vstack([self.xy, xy[i][None]]); self.ter = np.vstack([self.ter, ter[i][None]])
                self.votes.append([]); self.slow.append(None); self.cell.append(tuple(cells[i])); self.members.append([])
            else:
                self.c["writes_matched"] += 1; self.c["write_ties"] += int(tied)
            self.members[j].append(tuple(cells[i]))
            per.setdefault(j, collections.Counter())[int(tok[i])] += 1
        changed = False
        for j in sorted(per):
            top = per[j].most_common(2)
            self.c["votes"] += 1; self.c["vote_ties"] += int(len(top) > 1 and top[0][1] == top[1][1])
            self.votes[j].append((e, top[0][0]))
            new = r2([k for _, k in self.votes[j]], self.slow[j], self.rb)
            if new != self.slow[j]:
                self.slow[j] = new; changed = True
        if changed:
            items = [[j, self.slow[j], [float(self.xy[j][0]), float(self.xy[j][1])], [int(v) for v in self.ter[j]], [list(v) for v in self.votes[j]]]
                     for j in range(len(self.slow)) if self.slow[j] is not None]
            p = self.versions[-1]["hash"]
            self.versions.append({"parent": p, "episode": e, "items": items, "hash": vhash(p, e, items)})


def records(seq):
    ep, t, xy, ter, tok, cell, start = [], [], [], [], [], [], []
    for E in seq.episodes:
        start.append(len(ep))
        for s in E.raw["steps"]:
            r = parse_student_step(s)
            ep.append(E.index); t.append(r.t); xy.append((r.est_pose[0], r.est_pose[1])); ter.append(r.world_terrain.reshape(-1))
            tok.append(r.observed_token); cell.append((int(s["truth"]["x"]), int(s["truth"]["y"])))
    return {"ep": np.array(ep, np.int32), "t": np.array(t, np.int32), "xy": np.array(xy, np.float64), "ter": np.stack(ter).astype(np.int8),
            "tok": np.array(tok, np.int32), "cell": np.array(cell, np.int32), "start": start}


def gtime(R, idx):
    return R["ep"][idx].astype(np.int64) * T + R["t"][idx]


def top1(R, idx, qi, alpha=0.0, eligible=False):
    if len(idx) == 0:
        return None
    s, ok = place(R["xy"][idx], R["ter"][idx], R["xy"][qi], R["ter"][qi])
    if eligible:
        if not ok.any():
            return None
        idx, s = idx[ok], s[ok]
    s = s - alpha * (R["ep"][qi] - R["ep"][idx]) + TIE * gtime(R, idx)
    return int(idx[int(np.argmax(s))])


def latest(R, past, qi):
    if len(past) == 0:
        return None
    _, ok = place(R["xy"][past], R["ter"][past], R["xy"][qi], R["ter"][qi])
    m = past[ok]
    return None if len(m) == 0 else int(R["tok"][m[int(np.argmax(gtime(R, m)))]])


def dwells(R, s0, s1):
    out, prev = [], None
    for i in range(s0, s1):
        if R["tok"][i] > 0:
            key = (float(R["xy"][i][0]), float(R["xy"][i][1]), int(R["tok"][i]))
            if key != prev:
                out.append(i)
            prev = key
        else:
            prev = None
    return np.array(out, dtype=np.int64)


COLS = ("kind", "world", "episode", "t", "answer", "shown", "decoy", "relocated", "tok_before", "tok_after", "first_ok", "g_slow",
        "g_item_on_cell", "query_tie", "sr_fast", "u0_past") + tuple("pred_" + p for p in ("C", "L", "G", "GNR", "MODE", "GP", "SR", "U0", "U05", "U1", "U2", "GT", "LT"))


def analyse(seq, R, w, k):
    if k:
        R = dict(R); xy = R["xy"].copy()
        for e in range(len(seq.episodes)):
            rng = random.Random(derive_seed(NS, "offset", w, e, k)); dx, dy = rng.randint(-k, k), rng.randint(-k, k)
            xy[R["ep"] == e] += (dx, dy)
        R["xy"] = xy
    perm = dict(zip(F1, random.Random(derive_seed(NS, "perm", w)).sample(F1, len(F1))))
    G, GN = Store(True), Store(False)
    tv, tslow = {}, {}
    rows, obs_log, queries, fast_log = [], [], [], []
    past = []
    st = R["start"] + [len(R["ep"])]
    for e, E in enumerate(seq.episodes):
        s0, s1 = st[e], st[e + 1]
        op = np.array(past, dtype=np.int64)
        if e >= 1:
            for c in seq.persistent:
                hit = [i for i in range(s0, s1) if tuple(R["cell"][i]) == c]
                if not hit:
                    continue  # 这一回合没走到这个固定格：没有查询
                qi = hit[0]; t = int(R["t"][qi])
                shown = int(R["tok"][qi]); ans = E.regime[c]
                L = latest(R, op, qi); L = shown if L is None else L
                j, tie = G.best(R["xy"][qi], R["ter"][qi], True)
                g = L if j is None else G.slow[j]
                jn, _ = GN.best(R["xy"][qi], R["ter"][qi], True)
                gnr = L if jn is None else GN.slow[jn]
                ja, _ = G.best(R["xy"][qi], R["ter"][qi], False)
                if ja is None:
                    mode = L
                else:
                    v = [x for _, x in G.votes[ja]]; cnt = collections.Counter(v); mode = pick(list(cnt), cnt, v)
                f = top1(R, np.arange(s0, s0 + max(t - GAP + 1, 0)), qi, eligible=True)
                at = op[(R["cell"][op] == np.array(c)).all(1)] if len(op) else op
                lt = int(R["tok"][at[int(np.argmax(gtime(R, at)))]]) if len(at) else shown
                gt = tslow.get(c); gt = lt if gt is None else gt
                rel = int(e >= PS.RELOCATION_EPISODE and c in seq.relocated)
                rows.append({"kind": 1, "world": w, "episode": e, "t": t, "answer": ans, "shown": shown, "decoy": int(E.decoy[c]), "relocated": rel,
                             "tok_before": seq.before[c], "tok_after": seq.after[c], "first_ok": 1, "g_slow": int(j is not None),
                             "g_item_on_cell": int(j is not None and G.cell[j] == c), "query_tie": int(tie), "sr_fast": int(f is not None), "u0_past": -1,
                             "pred_C": shown, "pred_L": L, "pred_G": g, "pred_GNR": gnr, "pred_MODE": mode, "pred_GP": perm.get(g, g),
                             "pred_SR": g if f is None else int(R["tok"][f]), "pred_U0": -1, "pred_U05": -1, "pred_U1": -1, "pred_U2": -1, "pred_GT": gt, "pred_LT": lt})
                queries.append({"episode": e, "t": t, "version": G.versions[-1]["hash"], "xy": R["xy"][qi].tolist(), "terrain": R["ter"][qi].tolist(),
                                "shown": shown, "answer": ans, "decoy": int(E.decoy[c]), "relocated": rel, "pred_G": g, "pred_L": L})
        for ev_ in E.raw["events"]:
            if ev_["bucket"] != spec.BUCKET_LONG or not ev_["swapped"]:
                continue
            t = int(ev_["t"]); qi = s0 + t
            fp = np.arange(s0, s0 + max(t - GAP + 1, 0))
            uni = np.concatenate([np.arange(0, s0), fp])
            c_ = top1(R, fp, qi)
            u = {n: top1(R, uni, qi, alpha=a) for n, a in ALPHAS.items()}
            f = top1(R, fp, qi, eligible=True)
            if f is not None:
                sr = int(R["tok"][f])
            else:
                j, _ = G.best(R["xy"][qi], R["ter"][qi], True)
                lm = latest(R, op, qi)
                sr = G.slow[j] if j is not None else (lm if lm is not None else int(R["tok"][qi]))
            pc = 0 if c_ is None else int(R["tok"][c_])
            rows.append({"kind": 0, "world": w, "episode": e, "t": t, "answer": int(ev_["answer"]), "shown": int(R["tok"][qi]), "decoy": 0, "relocated": 0,
                         "tok_before": -1, "tok_after": -1, "first_ok": 1, "g_slow": 0, "g_item_on_cell": 0, "query_tie": 0, "sr_fast": int(f is not None),
                         "u0_past": int(u["U0"] is not None and R["ep"][u["U0"]] < e),
                         "pred_C": pc, "pred_L": -1, "pred_G": pc, "pred_GNR": -1, "pred_MODE": -1, "pred_GP": -1, "pred_SR": sr,
                         **{f"pred_{n}": (0 if r is None else int(R["tok"][r])) for n, r in u.items()}, "pred_GT": -1, "pred_LT": -1})
            fast_log.append([e, t, int(ev_["answer"])])
        o = dwells(R, s0, s1)
        G.absorb(e, R["xy"][o], R["ter"][o], R["tok"][o], R["cell"][o])
        GN.absorb(e, R["xy"][o], R["ter"][o], R["tok"][o], R["cell"][o])
        per = {}
        for i in o:
            per.setdefault(tuple(R["cell"][i]), collections.Counter())[int(R["tok"][i])] += 1
        for c in sorted(per):
            tv.setdefault(c, []).append(per[c].most_common(1)[0][0]); tslow[c] = r2(tv[c], tslow.get(c), True)
        obs_log += [[int(R["ep"][i]), int(R["t"][i]), float(R["xy"][i][0]), float(R["xy"][i][1]), R["ter"][i].tolist(), int(R["tok"][i])] for i in o]
        past += o.tolist()
    pers = set(seq.persistent)
    slow_cells = [G.cell[j] for j in range(len(G.slow)) if G.slow[j] is not None]
    d8 = {"items": len(G.slow), "slow": len(slow_cells), "slow_off_persistent": sum(c not in pers for c in slow_cells),
          "persistent_with_several_slow": sum(slow_cells.count(c) > 1 for c in pers), "mixed_items": sum(len(set(m)) > 1 for m in G.members),
          "versions": len(G.versions) - 1, **{k: int(G.c[k]) for k in ("writes_matched", "write_ties", "votes", "vote_ties")}}
    return rows, {"versions": G.versions, "observations": obs_log, "queries": queries, "fast_events": fast_log, "d8": d8}


T0 = time.monotonic()
logs = [json.loads(l) for l in (A / "worlds.jsonl").read_text(encoding="utf-8").splitlines()]
EV = {k: v for k, v in np.load(A / "events.npz").items()}
EVK = {k: {c: v for c, v in np.load(A / f"events_k{k}.npz").items()} for k in OFFS}
rows = {0: [], **{k: []for k in OFFS}}
res = {"worlds": NW, "mismatch": collections.Counter(), "first_mismatch": {}}
d8sum = collections.Counter()
for w in range(NW):
    seq = PS.generate_sequence(NS, w, allow_registered=True)
    R = records(seq)
    lg = logs[w]
    if lg["world"] != w or lg["world_seed"] != seq.world_seed or lg["layout_sha256"] != seq.layout_sha256:
        res["mismatch"]["world_identity"] += 1
    r0, mine = analyse(seq, R, w, 0)
    rows[0] += r0
    d8sum.update(mine["d8"])
    for key in ("observations", "fast_events"):
        if mine[key] != lg[key]:
            res["mismatch"][key] += 1; res["first_mismatch"].setdefault(key, w)
    if [v["hash"] for v in mine["versions"]] != [v["hash"] for v in lg["versions"]] or mine["versions"] != [{k: v[k] for k in ("parent", "episode", "items", "hash")} for v in lg["versions"]]:
        res["mismatch"]["versions"] += 1; res["first_mismatch"].setdefault("versions", w)
    keys = ("episode", "t", "version", "xy", "terrain", "shown", "answer", "decoy", "relocated", "pred_G", "pred_L")
    if mine["queries"] != [{k: q[k] for k in keys} for q in lg["queries"]]:
        res["mismatch"]["queries"] += 1; res["first_mismatch"].setdefault("queries", w)
    for k in OFFS:
        rows[k] += analyse(seq, R, w, k)[0]
    if (w + 1) % 25 == 0:
        print(f"[{time.monotonic() - T0:6.1f}s] world {w + 1}", flush=True)


def compare(rows_, ev):
    n = len(rows_)
    out = {}
    for c in COLS:
        mine = np.array([r[c] for r in rows_], dtype=np.int64)
        theirs = ev[c][:n] if c in ev else None
        out[c] = None if theirs is None else int((mine != theirs).sum())
    return {"rows_mine": n, "rows_theirs_total": int(len(ev["kind"])), "column_mismatches": {c: v for c, v in out.items() if v}, "columns_checked": len(out)}


res["mismatch"] = dict(res["mismatch"])
res["events_main"] = compare(rows[0], EV)
res["events_offsets"] = {str(k): compare(rows[k], EVK[k]) for k in OFFS}
res["d8_mine"] = dict(d8sum)
F = json.loads((REPO / "reports/V9-S3-PHASE3/final.json").read_text())
res["d8_identical_to_final"] = dict(d8sum) == F["result"]["diagnostics"]["D8_items"] if NW == 200 else None
res["seconds"] = round(time.monotonic() - T0, 1)
res["forbidden_loaded"] = sorted(m for m in sys.modules if m.endswith(("s3.promotion", "s3.analysis_p3", "s3.cues")))
OUT.write_text(json.dumps(res, ensure_ascii=False, indent=1))
print(json.dumps(res, ensure_ascii=False))
