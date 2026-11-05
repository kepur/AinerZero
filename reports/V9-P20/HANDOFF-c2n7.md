# P20 交接说明（workbuddy-c2n7 → 当前持卡者 / 一级）

- 本棒（workbuddy-c2n7）于 08:46 领取 ainerzero.V9.P20，因长间隔分析超过 20 分钟无心跳，09:11 被接力台收回；任务现由 workbuddy-q7t2 持有。本目录下的 `*-c2n7*` 文件是本棒的完整复核成果，可直接复用，勿覆盖你的 REPORT.md/指标.json。
- 已完成：38 项钉住 SHA 复核（全一致）；用冻结 r5 生产函数独立复算 k 覆盖/族统计/550 窗口/611-1492-800-3500-175/帧分解/预算 7 项（delta 全 0）；r2 两个交付物字节级可再生验证（independent_truth_check.json=b8f55a8b、metrics.json=ad32d483，均与钉住值一致）；F1–F9 逐条核验；四个重点审查项专项结论。
- 主要结论：F1–F8 闭合成立；**F9"清单字段冻结后被改写"无历史 diff 证据**（四份 prereg 都含两个值、数据集清单只有 45.739918708、无更早单值副本）需降级为"内部不一致+假设"；**D1**：单次 eval 真实硬杀是 350 s（300 名义+supervision_extra 50），r2 称 300 绝对硬墙不准确（按 9×350 重算静态检查仍通过）；**D2**：B2 计数未绑定数据摘要，不能沿用到 B1 新数据集；**O1**：P19 C 块 per_k_calls stale（不影响 r2 数字）。
- 复跑方式：`env -i PATH=/usr/bin:/bin:/usr/local/bin HOME=<tmp> TMPDIR=/tmp PYTHONDONTWRITEBYTECODE=1 .venv/bin/python reports/V9-P20/analysis/p20_independent_check.py`（只读冻结输入，只写 reports/V9-P20/）。
- 未做/未验证：真实 MLX 路径、RunStore 绑定段、arms.py 数值路径、M2 选点稳健性、B1 数据成本；未提交 relay report（任务已不在本棒手上）。
