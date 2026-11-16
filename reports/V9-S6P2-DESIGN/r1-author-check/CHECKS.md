# S6P2 r1 作者侧 CPU 交付检查

限定作者侧辅助；P269 由 codex 持有，本次未占新卡，不构成独立设计验收或运行授权。只写本目录；没有模型加载、MLX 导入、摸底复跑、源码/测试/设计修复或 git add/commit/push。

## 结果与 rc

- 指定命令 `.venv/bin/python -m pytest tests/v9/experiments/test_s6_world_b.py -q`：**12 passed in 1.96s，rc=0**。完整 stdout、stderr、rc、argv 和环境调整见 `evidence/pytest.*` / `evidence/pytest-command.json`。
- NumPy 测试：检查了测试、world_b、world-A、sandbox 的实际 import；运行时 guard 记录 MLX 导入及尝试均为 0，越界写入为 0。额外第三方 pytest 插件未加载；cache、临时文件和 logging 全部定向本目录。
- 五臂 × 四轮：**180/180** 日志数值按原 `.3f`（picks）/`.4f`（指标）精度一致，含每轮 H、D_A、all_A 和三种 picks 比例；额外核对全部 **200/200** 网络指标均值及 **60/60** 整数 picks 计数。首轮所有公共指标、picks、per_net 精确相同，O 专有布局诊断除外；不据此证明选样 ID 或权重逐位相同。
- 数值分析、补充 quantile、生产 manifest 修正检查：**rc 均为 0**。不追加其他测试。

## 末轮点值

O+ 为日志代号，正式主臂名 N+。

| 臂 | 最终 H | O+ 相对该臂的 H 差 |
|---|---:|---:|
| O+ | 0.360720375898 | +0.000000000000 |
| U+ | 0.330557694930 | +0.030162680969 |
| Q+ | 0.288207068436 | +0.072513307463 |
| R+ | -0.057719284052 | +0.418439659950 |
| W+ | 0.479949368173 | -0.119228992275 |

GO = `(H(O+)−H(R+)) − 0.5×(H(W+)−H(R+))` = **0.149605333838**。只有一个探索重复，没有正式区间，不能称门通过。

O 第 2–4 轮诱饵比例为 **0.049333333333、0.024000000000、0.021333333333**；计数 74、36、32，每轮分母 1500，因此三轮合计 **142/4500 = 0.031555555556**。`tiny_world` 同时含小诱饵与大诱饵；末轮 0.021333333333 不等于三轮均值。

## t 与重复层半宽

以一期 `s6/analysis.py` 的 t_cdf/_invert/t_ppf 纯 math 函数 AST 计算，并用独立 Student 密度 Simpson 积分交叉核对（CDF 残差 <1e-12）；r0 另用 70 位 Decimal、df4 闭式核对。

| 版本 | K / m / df | t 临界值 | 重复层半宽系数 t/√K |
|---|---|---:|---:|
| r1 | 10 / 10 / 9 | 3.68966239230421 | 1.1667736956747021 |
| r0 | 5 / 9 / 4 | 5.436591556004132 | 2.4313176570253185 |

r1 写 **3.689662、1.166774** 正确；r0 写 **2.4313** 按四位小数舍入正确，无需修正。r0 数学概率的高精度半宽为 2.43131765702533477098…；与 float 输入的尾位差异不影响上述舍入。重复层半宽约缩小 52.0106%，世界层仍须另合并。详见 `evidence/quantiles.json`。

按用户本轮明确的正式规模记录：N+,R+,E+,Q+,U+,W+,N− 共 7 臂 × 10 = **70 格、210 网络、840 权重**，m10、df9，旧门不降。本次不验收整体设计，也不新增实现或运行。

## 一期冻结与分析工具修正

实际 PREREG 路径：`/Users/mac/AinerWorkFlow/AinerZero/reports/V9-S6-PHASE1/PREREG-r1.json`，字段 `manifest`。实际 46 个路径及逐项 expected/actual SHA 完整列于 `evidence/frozen-before.json` 和 `evidence/frozen-after.json`：**46/46 一致**。

原分析错误地把完整 46 文件集合摘要与 42 文件数值闭包摘要比较，属于**分析工具失败，非真实冻结失败**。原失败输出与脚本保留于 `evidence/analysis1/`。已在 `corrected-check/` 从生产 build_manifest/current_identity/make_prereg 的源码 AST 独立重建两个集合；46 文件完全匹配，42 文件 SHA 正好为注册值 **dce517dfa554ad57bb60e9fec855c8954eeefd7ee75781f64ac22665dc2b29d1**。差集四条具体路径见 `corrected-check/CORRECTION.md`；未修改原证据。

## 来源、配置与边界

results 配置为 per=1500、rounds=4、steps=1000、lr=0.001。补充读取作者提供的 `r1-handoff/I-ROUND-PROVENANCE.txt`（2026-11-16T20:40:08.428Z 工具调用）：600 世界，60 big、30 tiny、30 large，namespace `s6x-p2i-cand`，启动省略上述四参数而沿用默认值。此来源是**作者工具日志，不是密封运行 manifest**；只读保存为 `evidence/I-ROUND-PROVENANCE.author-log.txt`，未执行其中命令。起点/测试分区、源码默认值和 SHA 身份见 `evidence/detailed-results.json`、`evidence/provenance-summary.json`、`evidence/inputs-before.json`。

当前源码 SHA 不能冒充历史执行源码身份；没有重跑推理或读取检查点验证。共享工作区期间协调文件、研究记录与设计稿被他人更新，均未撤销或覆盖；数值核对使用保存的输入快照，具体变化见 `evidence/delivery-input-drift.json`。初读时设计里的 I 轮占位符在快照保存前已由作者补齐，不记作当前缺陷。

首次 pytest 因本检查自加的严格写保护拒绝默认 `/dev/null` logging 而 rc=3，尚未执行测试；原 stdout/stderr/rc 保留在 `evidence/attempt1/`。将 logging 明确指到交付目录后通过，没有修源码或测试。所有既有失败证据保留。

输入 SHA 集中记录在 `evidence/inputs-before.json`；结果摘要在 `metrics.json`；完整数字比较在 `evidence/numeric-comparison.json`。`SHA256SUMS.txt` 覆盖本目录所有文件（自身除外），含原始输出、脚本、输入快照与修正证据。
