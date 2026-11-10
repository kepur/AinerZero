"""第 10 项：研究日志 R20261110-S4-start 第五至第十轮的数字，与 tier1-explore 的 results*/diag*/run*.log 逐个比对（四舍五入到日志的位数）。"""
import ast, json, re, sys
from pathlib import Path
X = Path(sys.argv[1]); OUT = sys.argv[2]
J = lambda f: json.loads((X / f).read_text())
def logrow(f, key):
    for line in (X / f).read_text().splitlines():
        if line.startswith(key + " {"):
            return ast.literal_eval(line[len(key) + 1: line.rindex("}") + 1])
r6, r7, r8, r9, r10 = J("results6-train-fix-20000.json"), J("results7-batchmix-20000.json"), J("results8-lrwidth.json"), J("results9-ablation.json"), J("results9-w1-confirm.json")
d8, d8w = J("diag8-decay.json"), J("diag8-wide-decay.json")
r5i, r5l = logrow("run5-20000-crashed.log", "L-ind"), logrow("run5-20000-crashed.log", "L-int")
r9l, r10l = {k: logrow("run9-ablation.log", k) for k in ("recipe6", "clip-only", "share-noclip", "share-w1x10")}, {k: logrow("run10-w1-confirm.log", k) for k in ("c-w1x10", "noclip-w1x10", "ind-w1x10")}
C = [  # (日志里的说法, 日志值, 文件值)
 ("第五轮 L-int D(6 盘)", 0.444, r5l["six"]["D"]), ("第五轮 L-int D 下界", 0.397, r5l["six"]["D_low"]), ("第五轮 L-int HF", 0.027, r5l["six"]["HF"]),
 ("第五轮 L-ind HF 上界", 0.069, r5i["six"]["HF_high"]),
 ("第六轮 L-int D", 0.823, r6["L-int"]["six"]["D"]), ("第六轮 L-int HF 上界", 0.135, r6["L-int"]["six"]["HF_high"]), ("第六轮 L-int-c D 下界", 0.845, r6["L-int-c"]["six"]["D_low"]),
 ("第六轮 宽 128 HF", 0.097, r6["L-int-wide"]["six"]["HF"]), ("第六轮 重识别参照 E-B/E-P", [22, 33], [r6["reid"]["E-B"][0], r6["reid"]["E-P"][0]]),
 ("第七轮 0.25、0.25 HF(6 盘)", 0.102, r7["c25n25"]["six"]["HF"]), ("第七轮 0.25、0.25 HF(10 盘)", 0.099, r7["c25n25"]["ten"]["HF"]),
 ("第八轮 衰减、宽 128 D", 0.862, r8["wide-decay"]["six"]["D"]), ("第八轮 衰减 HF 上界", 0.139, r8["decay"]["six"]["HF_high"]),
 ("第九轮 0.5、10、10 D", 0.837, r9["share-w1x10"]["six"]["D"]), ("第九轮 0.5、10、10 HF", 0.078, r9["share-w1x10"]["six"]["HF"]),
 ("第九轮 0.5、10、10 自由步误差", 0.061, r9l["share-w1x10"]["free_error6"]), ("第九轮 0.5、10、10 重识别", 36, r9["share-w1x10"]["reid"][0]),
 ("第九轮 不裁剪 自由步误差", 0.113, r9l["share-noclip"]["free_error6"]),
 ("第十轮 L-int-c HF 上界", 0.078, r10["c-w1x10"]["six"]["HF_high"]), ("第十轮 不裁剪 HF", 0.094, r10["noclip-w1x10"]["six"]["HF"]), ("第十轮 L-ind D 下界", 0.002, r10["ind-w1x10"]["six"]["D_low"]),
 ("擦边分解 自由步(无墙柱接触) 衰减", 0.118, d8["free_by_hard_contact"]["none"]["mean_error"]), ("擦边分解 自由步 宽 128", 0.099, d8w["free_by_hard_contact"]["none"]["mean_error"]),
 ("擦边分解 E-B 碰撞步误差", 1.269, d8["eb_collision_error"]),
]
def same(a, b):
    if isinstance(a, list): return a == b
    nd = len(str(a).split(".")[1]) if "." in str(a) else 0
    return round(b + 1e-12, nd) == a or abs(round(b, nd) - a) < 1e-9
rows = [{"claim": c, "log": a, "file": b, "match": same(a, b)} for c, a, b in C]
same4 = all(r9["recipe6"][p][k] == r6["L-int"][p][k] for p in ("six", "ten") for k in ("D", "D_low", "HF", "HF_high"))
rows.append({"claim": "第九轮：第六轮写法重训与第六轮在四位小数上相同", "log": True, "file": same4, "match": same4})
json.dump(rows, open(OUT, "w"), ensure_ascii=False, indent=1)
print(sum(r["match"] for r in rows), "of", len(rows), "match"); [print(r) for r in rows if not r["match"]]
