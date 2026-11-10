"""S3 第三阶段 final 的独立复算（复核者自写）。只用 NumPy 和标准库，不导入运行器和任何项目代码。
登记内容（比较项、bootstrap、Bonferroni m、K5 带宽、偏移档）一律从预登记读。只读，不写 artifacts/。

用法：recompute_final.py <仓库根> <输出 json>
"""
import hashlib, json, sys
from pathlib import Path
import numpy as np

REPO, OUT = Path(sys.argv[1]), Path(sys.argv[2])
A = REPO / "artifacts/v9/s3/phase3/final-final"
P = json.loads((REPO / "reports/V9-S3-PHASE3/PREREG-r1.json").read_text())
F = json.loads((REPO / "reports/V9-S3-PHASE3/final.json").read_text())
R = F["result"]
D = P["descriptive"]
B = D["bootstrap"]
M = D["bonferroni_m"]
OFFS = D["offsets"]
NW = P["sizes"]["final"]

ev = {k: v for k, v in np.load(A / "events.npz").items()}
off = {k: {c: v for c, v in np.load(A / f"events_k{k}.npz").items()} for k in OFFS}
logs = [json.loads(l) for l in (A / "worlds.jsonl").read_text(encoding="utf-8").splitlines()]
O = {"sha_ok": {f: hashlib.sha256((A / f).read_bytes()).hexdigest() == h for f, h in F["files_sha256"].items()}}

# 种类：查询事件的数目应等于日志里的查询数
n_log_q = sum(len(lg["queries"]) for lg in logs)
kinds = {int(k): int((ev["kind"] == k).sum()) for k in np.unique(ev["kind"])}
KQ = next(k for k, n in kinds.items() if n == n_log_q)
KF = next(k for k in kinds if k != KQ)
O["kinds"] = {"query": KQ, "fast": KF, "counts": kinds}


def sets(e):
    q, f = e["kind"] == KQ, e["kind"] == KF
    return {"fast": f, "fast_e1": f & (e["episode"] >= 1), "query": q, "decoy": q & (e["decoy"] == 1),
            "decoy_stable": q & (e["decoy"] == 1) & (e["relocated"] == 0), "relocated": q & (e["relocated"] == 1), "clean": q & (e["decoy"] == 0)}


def corr(e, p):
    return (e[f"pred_{p}"] == e["answer"]).astype(np.float64)


def paired(e, mask, a, b):
    w = e["world"][mask]
    d = corr(e, a)[mask] - corr(e, b)[mask]
    ws, idx = np.unique(w, return_inverse=True)
    n_w = np.bincount(idx, minlength=len(ws)).astype(np.float64)
    d_w = np.bincount(idx, weights=d, minlength=len(ws))
    draws = np.random.default_rng(B["seed"]).integers(0, len(ws), size=(B["n"], len(ws)))
    boot = d_w[draws].sum(1) / n_w[draws].sum(1)
    tail = (1 - B["level"]) / 2
    lo, hi = np.quantile(boot, [tail, 1 - tail]); blo, bhi = np.quantile(boot, [tail / M, 1 - tail / M])
    return {"delta": float(d.mean()), "ci_low": float(lo), "ci_high": float(hi), "bonf_low": float(blo), "bonf_high": float(bhi),
            "n_events": int(len(d)), "n_worlds": int(len(ws)), "acc_a": float(corr(e, a)[mask].mean()), "acc_b": float(corr(e, b)[mask].mean())}


S = sets(ev)
mine_desc = {n: paired(ev, S[s], a, b) for n, s, a, b in D["comparisons"]}
O["descriptive_bit_identical"] = {n: mine_desc[n] == R["descriptive"][n] for n in mine_desc}
O["descriptive_count"] = len(mine_desc)
mine_off = {str(k): {n: paired(off[k], sets(off[k])[s], a, b) for n, s, a, b in D["offset_comparisons"]} for k in OFFS}
O["offsets_bit_identical"] = {k: {n: mine_off[k][n] == R["offsets"][k][n] for n in mine_off[k]} for k in mine_off}
O["n_comparisons"] = {"prereg_m": M, "final": R["n_comparisons"], "counted": len(D["comparisons"]) + len(D["offset_comparisons"]) * len(OFFS)}

# 准确率表与比率
POL = [c[5:] for c in ev if c.startswith("pred_")]
acc = {n: {p: float(corr(ev, p)[m].mean()) for p in POL if (ev[f"pred_{p}"][m] >= 0).all()} | {"n": int(m.sum())} for n, m in S.items() if m.any()}
G = R["diagnostics"]
O["accuracy_identical"] = acc == G["accuracy"]
rate = lambda m, c: float(ev[c][m].mean())
mine_rates = {"D2_U0_won_by_past": rate(S["fast_e1"], "u0_past"), "D5_SR_fast_rate_queries": rate(S["query"], "sr_fast"),
              "D5_SR_fast_rate_fast": rate(S["fast"], "sr_fast"), "D8_query_tie_rate": rate(S["query"] & (ev["g_slow"] == 1), "query_tie"),
              "D8_slow_hit_rate": rate(S["query"], "g_slow"), "D8_slow_hit_on_cell": rate(S["query"] & (ev["g_slow"] == 1), "g_item_on_cell")}
O["rates_identical"] = {k: v == G[k] for k, v in mine_rates.items()}
O["rates"] = mine_rates
# 恢复曲线
rel = S["relocated"]; curve = {}; first = None
for e in sorted(set(ev["episode"][rel].tolist())):
    m = rel & (ev["episode"] == e)
    row = {p: float(corr(ev, p)[m].mean()) for p in ("C", "L", "G", "GNR", "MODE")} | {"n": int(m.sum())}
    curve[str(e)] = row
    if first is None and row["G"] > row["C"]:
        first = e
O["recovery_identical"] = {"by_episode": curve == G["D4_recovery"]["by_episode"], "first": first == G["D4_recovery"]["first_episode_G_beats_C"], "first_episode": first}
O["recovery"] = curve
# D8：日志里每个世界的条目诊断求和
items = {k: int(sum(lg["items"][k] for lg in logs)) for k in logs[0]["items"]}
O["D8_items_identical"] = items == G["D8_items"]; O["D8_items"] = items

# 契约门 K4–K7
q = S["query"]; stable = q & (ev["relocated"] == 0)
k4 = {"decoy_iff_shown_differs": bool(((ev["shown"][q] != ev["answer"][q]) == (ev["decoy"][q] == 1)).all()),
      "stable_answer_is_episode0_value": bool((ev["answer"][stable] == ev["tok_before"][stable]).all()),
      "relocated_answer_is_new_value": bool((ev["answer"][rel] == ev["tok_after"][rel]).all() and (ev["tok_after"][rel] != ev["tok_before"][rel]).all()),
      "query_is_first_arrival": bool((ev["first_ok"][q] == 1).all()),
      "all_sets_present": bool(S["decoy"].any() and S["clean"].any() and S["fast"].any())}
exp, band = P["contract"]["expected_per_100_worlds"], P["contract"]["sample_band"]
have = {k: int(S[k].sum()) for k in exp}
k5 = {k: [exp[k] * NW / 100 * (1 - band[k]), have[k], exp[k] * NW / 100 * (1 + band[k])] for k in exp}
k5_ok = all(lo <= h <= hi for lo, h, hi in k5.values())
lq = [(lg["world"], x["episode"], x["t"], x["answer"], x["shown"], x["decoy"], x["relocated"], x["pred_G"], x["pred_L"]) for lg in logs for x in lg["queries"]]
eq = list(zip(*(ev[c][q].tolist() for c in ("world", "episode", "t", "answer", "shown", "decoy", "relocated", "pred_G", "pred_L"))))
lf = [(lg["world"], e, t, a) for lg in logs for e, t, a in lg["fast_events"]]
ef = list(zip(*(ev[c][S["fast"]].tolist() for c in ("world", "episode", "t", "answer"))))
k6 = {"queries_match": lq == eq, "fast_match": lf == ef, "worlds": [lg["world"] for lg in logs] == list(range(NW)) == sorted(set(ev["world"].tolist()))}
ident = ("kind", "world", "episode", "t", "answer", "shown", "decoy", "relocated", "tok_before", "tok_after", "first_ok")
k7 = {str(k): all(np.array_equal(off[k][c], ev[c]) for c in ident) for k in OFFS}
L = R["legality"]
O["K4"] = {"mine": k4, "same_as_final": all(L["K4_labels"][k] == v for k, v in k4.items())}
O["K5"] = {"mine": k5, "passed": k5_ok, "same_as_final": have == L["K5_samples"]["have"] and k5_ok == L["K5_samples"]["passed"]}
O["K6"] = {"mine": k6, "same_as_final": all(k6.values()) == L["K6_events_match_log"]["passed"]}
O["K7"] = {"mine": k7, "same_as_final": all(k7.values()) == L["K7_offsets_same_events"]["passed"]}
O["summary"] = {"descriptive_all_identical": all(O["descriptive_bit_identical"].values()),
                "offsets_all_identical": all(all(v.values()) for v in O["offsets_bit_identical"].values()),
                "accuracy": O["accuracy_identical"], "rates": all(O["rates_identical"].values()),
                "recovery": all(O["recovery_identical"][k] for k in ("by_episode", "first")), "D8_items": O["D8_items_identical"],
                "K4": all(k4.values()) and O["K4"]["same_as_final"], "K5": k5_ok and O["K5"]["same_as_final"],
                "K6": all(k6.values()) and O["K6"]["same_as_final"], "K7": all(k7.values()) and O["K7"]["same_as_final"], "sha": all(O["sha_ok"].values())}
O["mine_descriptive"] = mine_desc; O["mine_offsets"] = mine_off
OUT.write_text(json.dumps(O, ensure_ascii=False, indent=1))
print(json.dumps(O["summary"], ensure_ascii=False)); print(O["kinds"], O["n_comparisons"], "first G>C", first)
