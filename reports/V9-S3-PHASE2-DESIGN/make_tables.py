"""从结果文件生成 DESIGN-r1 的表格，避免手抄舍入。写入同目录 TABLES.md。"""
import json
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
EX = json.loads((HERE / "tier1-probe/results.json").read_text(encoding="utf-8"))
PR = json.loads((HERE.parent / "V9-S3-PHASE2/probe-p1.json").read_text(encoding="utf-8"))
r, cells = PR["result"], PR["cells"]
SEEDS = (1, 2, 3)
out = []


def p(line=""):
    out.append(line)


def boot(b):
    return f"{b['delta']:+.3f}（{b['ci_low']:+.3f}, {b['ci_high']:+.3f}）"


def mean(cond, phase, key="primary"):
    return float(np.mean([cells[f"{cond}/{s}"][phase][key] for s in SEEDS]))


p("## 探针（`s3p2-probe`，F1 2000 步，F2 1000 步，3 个种子，正式运行器）")
p()
p(f"主指标事件 {r['h3_prime']['retention']['n_events']} 个（3 个种子合计），{r['h3_prime']['retention']['n_episodes']} 个回合。用时 {PR['elapsed_s']:.0f} 秒（不含 A1），峰值内存 {PR['peak_rss_bytes'] / 1e9:.2f} GB。")
p()
p("| 臂 | F1 结束 | 备注 |")
p("|---|---|---|")
for c, note in (("A0", "地板"), ("O", "上界"), ("N", "负对照，只读 t−5 之前"), ("A2-C0", "手工线索"), ("A3S", "软混合"), ("A3H-C0", "硬采样")):
    p(f"| {c} | {r['accuracy_F1'][c]:.3f} | {note} |")
p()
p("| 门 | 实测 Δ（95% 区间） | 判据 | 结果 |")
p("|---|---|---|---|")
p(f"| H2：A3H − A2 | {boot(r['h2'])} | ≥ 0.05 且下界 > 0 | {'过' if r['h2']['pass'] else '不过'} |")
p(f"| H2b：A3H − A3S | {boot(r['h2b'])} | ≥ 0.03 且下界 > 0 | {'过' if r['h2b']['pass'] else '不过'} |")
h = r["h3_prime"]
p(f"| H3′ 保留：A2-R{h['capacity']} 的 F1 下降 | {boot(h['retention'])} | 上界 ≤ 0.05 | {'过' if h['gates']['retention'] else '不过'} |")
p(f"| H3′ 可塑性：A2-C0 的 F2 − A2-R{h['capacity']} 的 F2 | {boot(h['plasticity'])} | 上界 ≤ 0.05 | {'过' if h['gates']['plasticity'] else '不过'} |")
p(f"| 干扰存在：A2-C0 下降，8 类读出 | {boot(h['interference_8class'])} | ≥ 0.10 | {'过' if h['interference_8class']['delta'] >= 0.10 else '不过'} |")
p(f"| 回放内容起作用：A2-CN 下降，8 类读出 | {boot(h['content_8class'])} | ≥ 0.10 | {'过' if h['content_8class']['delta'] >= 0.10 else '不过'} |")
p()
p("**容量曲线（只描述）**")
p()
p("| 条件 | F1 下降（16 类） | F1 下降（8 类） | F2 代价 |")
p("|---|---|---|---|")
for mem in ("A2", "A3H"):
    for k, v in r[f"capacity_{mem}"].items():
        p(f"| {k} | {boot(v['drop'])} | {v['drop_8class']['delta']:+.3f} | {boot(v['plasticity_cost'])} |")
p()
p(f"按 §3 的规则选出的容量：**{PR['selected_capacity']}**。")
p()
p("**不保护与对照的 F1 准确率（16 类 / 8 类）**")
p()
p("| 条件 | F1 结束 | F2 后的 F1 | F2 |")
p("|---|---|---|---|")
for c in ("A2-C0", "A2-CN", "A3H-C0"):
    p(f"| {c} | {mean(c, 'F1'):.3f} | {mean(c, 'F1_after'):.3f} / {mean(c, 'F1_after', 'primary_8'):.3f} | {mean(c, 'F2'):.3f} |")
for c in ("A2-J", "A3H-J"):
    p(f"| {c}（联合） | — | {mean(c, 'F1_after'):.3f} / {mean(c, 'F1_after', 'primary_8'):.3f} | {mean(c, 'F2'):.3f} |")
p()
rt = PR["retrieval"]["F1"]
p("**检索诊断（F1，长间隔已换事件）**")
p()
p(f"手工线索第一名：严格命中 {rt['top1_strict']:.3f}，能看到答案 {rt['top1_visible']:.3f}。候选池：严格命中任一 {rt['pool_strict']:.3f}，能看到答案任一 {rt['pool_visible']:.3f}。")
p()
z = cells["A2-C0/1"]["zero_state"]
p("**零状态诊断（A2-C0 种子 1，F1 结束）**：" + "；".join(f"{k} 间隔 {v['memory']:.3f} − {v['zero']:.3f} = {v['penalty']:+.3f}" for k, v in z.items()) + "。")
p()
p("## 探索（`s3p1-train` / `s3p1-probe`，2 个种子，F1 3000 步，F2 1500 步，未登记）")
p()
c = EX["ceiling"]["F1"]["long_swapped"]
p(f"候选天花板（{c['n']} 个事件）：第一名能看到答案 {c['top1_any']:.3f}，候选池能看到答案 {c['pool_any']:.3f}，真值 {c['oracle_any']:.3f}。")
p()
p("| 臂 | 1000 步 | 2000 | 4000 | 8000 |")
p("|---|---|---|---|---|")
for n in ("A2", "A3soft", "A3hard"):
    vals = [np.mean([EX["curves"][f"{n}/{s}"][ck]["primary"] for s in (1, 2)]) for ck in ("1000", "2000", "4000", "8000")]
    p(f"| {n} | " + " | ".join(f"{v:.3f}" for v in vals) + " |")
(HERE / "TABLES.md").write_text("\n".join(out) + "\n", encoding="utf-8")
print("\n".join(out))
