"""Render a final report ONLY after an explicitly released, complete eval comparison."""
import datetime
import hashlib
import json
from pathlib import Path
import sys

here=Path(__file__).resolve().parent
root=here.parents[2]
out=Path(sys.argv[1]).resolve()
if not out.is_relative_to(here):
    raise SystemExit('Comparison must be within assigned directory')
def load(name):
    return json.loads((out/name).read_text())
s=load('summary.json')
if s['status'] not in ('recommend_pass','recommend_return'):
    raise SystemExit('Final comparison is not complete')
b=load('budget.json')
r=load('recomputed.json')
audit=load('integrity.json')
inp=load('inputs-sha256.json')
manifest=load('source-manifest.json')
release=json.loads((here/'eval-release.json').read_text())
decision='建议通过（仅探针工程与计时复核）' if s['status']=='recommend_pass' else '建议打回'
lines=[
 '# P260 S6 probe 纯 CPU 独立复算报告', '',
 f'结论：**{decision}**。',
 f"逐字段比较 {s['compared_fields']} 项，不一致 {len(s['mismatches'])} 项；产物完整性问题 {len(audit['problems'])} 项；final 预算外推符合上限：{s['budget_fits']}。",
 '本报告不是 K=1 的科学能力结论，不自动放行 final、不晋升模型。', '',
 '## 身份与边界', '',
 '- 执行者：codex-s6probe-rv-1115，tier2 / kind codex / skills code,math；仅领取 P260，未参与被审实现或模型运行。',
 '- 指定版本：a33d34b5cb8d06800f584a0abcfd788d16f80fcb；源码闭包以 source-manifest.json 的逐文件哈希绑定。',
 f"- 源码闭包 SHA256：`{manifest['sha256']}`（{len(manifest['files'])} 个文件）。", 
 f"- 一级可读通知：消息 #{release['id']}，{release['created_at']}；原文保存在 eval-release.json，收到后才读取 eval 报告。",
 '- 所有写入仅 reports/V9-S6-PHASE1/probe-review-codex/；未改 src、tests、设计、旧产物；未回退他人改动、未提交、未推送。',
 '- 仅标准库 + NumPy。审计钩子拒绝导入 mlx / ainerzero；environment.json 记录两者均未加载。没有生成世界、模拟标签、训练、推理或重新评测。',
 '- 没有预留或消耗新的模型运行预算。下面的时间是已交付训练账本的实际量及未来规模的计算外推，不是运行授权或 RunStore 预留。', '',
 '## 完整性与可复算证据', '',
 '- 六臂 R/E/Z/T/P/G，各一个重复；每格三个网络 × 四轮，共 72 份 safetensors。逐文件 SHA、文件集合和 safetensors 头部数据区覆盖均检查。',
 '- 每轮 3000 个编号、每条选择轨迹累计 12000 个不重复编号；P 的三个学习者各自一条轨迹。每轮 picks 与 reveal_log.ids 完全一致，call 顺序 0..3，revealed 顺序等于所有 picks 串联。',
 '- 独立派生首轮、候选池和挑选种子；各臂首轮一致；R/T 四轮随机编号独立复算一致。E/Z/P 分数只核对摘要格式及已有重放记录，没有运行模型重新计算分数。',
 '- main6 50 世界、extrap10 25 世界，分别为世界 0..49 的 6 盘和 1000..1024 的 10 盘。每世界 300 状态、299 个相邻转移；所有误差数组覆盖 1×3×4×世界数×4 类。',
 '- 核对报告、cell.json、errors.npz、worlds.json、verify.json 与训练账本的身份及 SHA 链；输入完整哈希在 inputs-sha256.json。',
 '- 既有 verify.json：六格全部重放记录为真，E-r0-n0、P-r0-n0 各四轮复训逐位一致记录为真，种子 1；与报告嵌入记录逐字段相同。这里只独立核对落盘证据与其绑定，不声称 CPU 重新执行了训练或重放。',
 '- 候选状态与实际标签张量没有单独落盘，本次不能独立重算候选内容池 SHA 或物理标签内容。核对的是各格 pool_sha256 与 pools.json 一致、揭示链完整，并核对已保存跨进程复算记录；不将 SHA 当来源认证。', '',
 '## 八门算术（K=1，仅流程检查）', '',
 '| 门 | 独立点值 | Bonferroni 下界 | 上界 | 报告判定复现 |',
 '|---|---:|---:|---:|---|',
]
for g,v in r['result']['gates'].items():
    lines.append(f"| {g} | {v['point']:.10f} | {v['bonferroni'][0]:.10f} | {v['bonferroni'][1]:.10f} | {v['passed']} |")
lines += ['',
 '复算使用池化误差和/计数的比值；10000 次按世界配对抽样，种子 20261114，逐次先 main6 再 extrap10。比值门在 log 尺度构建区间；K=1 时重复层方差为 0、使用标准正态分位数。点值、逐重复值、95% 区间、Bonferroni 区间、方差分量、分位数、df、布尔判据及汇总字段逐一比较；另核对四轮描述量、臂间差和比值以及选样重合比例。',
 '浮点容限：相对 2e-11、绝对 2e-12；键集合、长度、布尔类型和值均精确比较。comparison.json 保存全部比较项，recomputed.json 保存独立重算值。',
 '工具自身验证：八门手算点值及常量样本的零方差区间；非零方差的解析标准误对照；自由运动代价负对照；点值/区间/判定三处篡改均被检出。见 tool-validation-r2.json。', '',
 '## final 预算独立外推', '',
 f"- 探针训练账本累计计费 {audit['ledger_charged_s']:.3f} 秒，所有 invocation closed；六格秒数与账本、评测报告一致。",
 '| 臂 | 探针实际秒数 | final 重复数 | 外推格训练秒数 |',
 '|---|---:|---:|---:|',
]
for a,sec in b['per_arm_probe_s'].items():
    k=3 if a=='G' else 5
    lines.append(f'| {a} | {sec:.1f} | {k} | {sec*k:.1f} |')
lines += ['',
 f"28 格、84 网络、336 权重文件。加权训练 {b['weighted_training_s']:.1f} 秒，加 5×90=450 秒候选池余量后乘 1.15，得到 **{b['estimated_train_s']:.2f} 秒**；上限 21600 秒，符合：{b['train_fits']}。",
 f"训练账本相对六格秒数的实际额外耗时 {b['probe_ledger_overhead_s']:.3f} 秒，按五组外推为 {b['observed_overhead_x5_s']:.3f} 秒；与保守候选池额度分开报告。",
 f"评测按格数 28/6、测试世界数 300/75 外推：校验 {b['projected_verify_s']:.2f} 秒，纯评测 {b['projected_scoring_s']:.2f} 秒，合计乘 1.30 为 **{b['estimated_eval_s']:.2f} 秒**；上限 3600 秒，符合：{b['eval_fits']}。",
    '外推公式对应 a33d34b 的原 make_prereg.py，原文快照在 baseline-source/；P261 对 builder/helper/tests 的修订不改变本次原公式/6h+1h基准。数值输入由 train-ledger.json / cell.json 独立获取并对评测报告交叉检查。假设同规模格性能不变；只是一点计时外推，不能保证后续运行耗时。没有更改门槛或预算。', '',
 '## 原文 citations', '',
 '以下为实际源码逐字引文，完整带行号输出及文件 SHA 在 citations.txt。', '',
]
quotes=[
 ('reports/V9-S6-DESIGN/DESIGN-r2.md','- K = 1（只用于探针）'),
 ('reports/V9-S6-DESIGN/DESIGN-r2.md','   - 本稿的臂、配方、门槛、预算在探针前冻结。'),
 ('reports/V9-S6-PHASE1/make_prereg.py','    est_train = '),
 ('reports/V9-S6-PHASE1/make_prereg.py','    est_eval = '),
 ('src/ainerzero/v9/experiments/s6/cells.py','        if [e["ids"]'),
 ('src/ainerzero/v9/experiments/s6/cells.py','    T = len(ep.steps) - 1'),
 ('reports/V9-S6-PHASE1/verify_s6p1.py','RETRAIN = '),
]
for rel,prefix in quotes:
    source=(here/'baseline-source'/rel).read_text().splitlines()
    matches=[(i,line) for i,line in enumerate(source,1) if line.startswith(prefix)]
    if len(matches)!=1:
        raise RuntimeError(f'Citation missing/ambiguous: {rel} {prefix}')
    n,line=matches[0]
    lines += [f'`{rel}:{n}`（a33d34b 原文，baseline-source/ 同路径快照）',f'> {line}', '']
lines += ['## 实际命令与复跑', '',
 '注册、claim、prompt、心跳、消息 received/applied 均通过现有 Relay CLI 完成；完整卡面在 task-prompt.txt，消息和心跳在 heartbeat-inbox.jsonl。', '',
 '```sh',
 'cd /Users/mac/AinerWorkFlow/AinerZero',
 '.venv/bin/python -I -B reports/V9-S6-PHASE1/probe-review-codex/validate_tool.py',
 '.venv/bin/python -I -B reports/V9-S6-PHASE1/probe-review-codex/recompute.py --out reports/V9-S6-PHASE1/probe-review-codex/replay-NEW --report reports/V9-S6-PHASE1/probe/EVAL-probe.json',
 '```', '',
 '复跑必须给新的输出目录，不覆盖本次复核。实际最终命令、退出码、标准输出和标准错误在 final-command.json / final-run.stdout / final-run.stderr。原有 preliminary-01/02 留存训练中的快照，READY.md 的“未完成”仅描述当时状态。', '',
 '## 失败、发现和未验证项', '',
 f"逐字段不一致：{json.dumps(s['mismatches'],ensure_ascii=False)}。",
 f"完整性问题：{json.dumps(audit['problems'],ensure_ascii=False)}。",
 '实际模型重放、复训和标签物理真值未由本执行者重跑；没有再次读 final；K=5 重复层统计不在本次 K=1 探针复算中验证。',
 f"记录的第三方版本：{json.dumps(s['recorded_third_party'],ensure_ascii=False)}。MLX 若记为 unknown，则该报告未提供确切发行版本，复核者没有通过导入 MLX 补查。",
 '共享仓库中他人的 COORDINATION.md / RESEARCH_LOG.md 等改动保持原状。工具准备时错误尝试了不存在的 src/ainerzero/s6 路径，立即更正为 src/ainerzero/v9/experiments/s6；没有执行或更改目标代码。',
 '最终建议只涵盖本次探针产物、算术和预算可行性。具体启动/冻结/接受由一级负责。交回 P260 后不领取下一卡。', '',
 f"生成时间：{datetime.datetime.now(datetime.timezone.utc).isoformat()}",
]
if not b['eval_fits']:
    lines.insert(5, f"**预算必修项：原式预计评测 {b['estimated_eval_s']:.2f} 秒，超出冻结上限 3600 秒达 {b['estimated_eval_s']-3600:.2f} 秒；仅含 30% 余量的校验部分已为 {1.3*b['projected_verify_s']:.2f} 秒。当前预算可行性不成立，建议不得据此冻结或启动 final。算术复现与预算可行性分别判定；本执行者不修改公式、参数或上限。**")
with (here/'REPORT.md').open('x') as f:
    f.write('\n'.join(lines)+'\n')
metrics={**s,'budget':b,'code_manifest_sha256':manifest['sha256'],'input_count':len(inp),'report':'reports/V9-S6-PHASE1/probe-review-codex/REPORT.md'}
with (here/'metrics.json').open('x') as f:
    json.dump(metrics,f,ensure_ascii=False,indent=2)
    f.write('\n')
print(decision)
