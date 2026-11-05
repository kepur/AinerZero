## 共同规则（E1 运行卡，一级 claude 2026-11-02）
- **授权**：RESEARCH_LOG `R20261029-E1-approval` 的唯一批准行，对应冻结文档 `artifacts/v9/e1/phase2/prereg.json`（document_sha256 `db75d096a048b505718690c6aec4d4f8a4d2cede4d0b32658fd395eb7c5beafd`）；预算见 `R20261102-E1-go-ahead`：总 5 h、只在本机、不租云 GPU、不付费。
- **绝对禁止 `--mode final-eval`**：final 分区是只读一次的封存数据，不在本次放行内。不得以任何方式读取 `artifacts/v9/e1/phase2/datasets/sealed_final/` 下的内容（列目录、做 SHA 清单除外）。违反即判该卡失败。
- **入口唯一**：只用 `cd /Users/mac/AinerWorkFlow/AinerZero && .venv/bin/python -m ainerzero.cli e1-phase2 …`，所有参数用默认值（不传 --output-root、--ledger、--lock-file、--prereg、--research-log、--wall-budget-seconds）。不得绕过 CLI 直接调用模块函数，不得另起锁外进程。
- **每条运行都用 `relay exec <本卡ID> --agent <你> --wall-timeout <秒> -- <命令>` 拉起**，进程组与本卡绑定；不要用 nohup 或 & 放到后台。
- **开跑前**先跑 `e1-phase2 --mode verify`，结果必须是 `status=verified`、`approval.status=approved`、`identity.status=passed`；不是就停下，在卡上提问，不得改任何源码或冻结文件。
- **不改任何文件**：src、tests、冻结的 prereg.json、RESEARCH_LOG 都不动，只在本卡的报告目录里新增文件。
- **每次运行前后**记录：中央账本 `artifacts/v9/e1/phase2/control.sqlite3` 中本实验的运行行（只读查询）、`artifacts/locks/m0-worker.lock` 状态、运行的退出码与 stdout JSON 原文。
- 任何一格失败、被拒或超时：**不重试、不调参**，保留原样，在卡上说明后交回（只交已完成部分）。重跑须由一级登记。
- 报告写清你**没有**做的事。

## 更正（一级 claude 2026-11-03 02:3x，取代上文「不传 --wall-budget-seconds」）
账本按格预留、不退还，见 RESEARCH_LOG `R20261103-E1-reservation-budget`。**训练和 dev 每格必须显式传 `--wall-budget-seconds`**：
- 训练：⑥ 1100，②③ 450；
- dev：⑥ 150，②③ 40，①④⑤⑦ 45。

训练每族先跑 ⑥。⑥ 任一格实际墙钟超过 1000 s，或 ②③ 任一格超过 400 s，就停下上报，不跑后续格。

## 更正二（一级 claude 2026-11-03 17:5x，方案 A，取代上文的授权行与 S 族预留）
- **授权改为 r1**：
  - 批准节 `R20261029-E1-approval` 的唯一合格行在第 2108 行，document_sha256 是 `84f23f2ce3a6071f622613cfa4f43a8abb468b02e456da994917bc1db68fe9f6`；
  - r0 的 `db75d096…` 已作废，冻结文档归档为 `prereg.r0.json`；
  - 依据是 RESEARCH_LOG `R20261103-E1-A-ruling`。
- **verify 的期望结果**：`document_sha256` 为 `84f23f2c…`，`approval` 为 approved，`identity` 为 passed（16 个源文件、8 个生成器）。
- **账本**：实验 id 是 `e1-phase2-20261029-r1`，在 r1 第一格准入时登记，日历窗口 72 h。5 h 总上限跨 r0 与 r1 合并累计；r0 已记 9600 s，所以第一格准入前的累计值是 9600。
- **S 族预留**：⑥ 1200，②③ 450。停止线：⑥ 超过 1100 s，或 ②③ 超过 400 s。dev 的预留不变。
- **派发**：P101 交回后立即派 P102，S 族训练与 dev 须在 72 h 内跑完。

## 更正三（一级 claude 2026-11-05）
- **`--wall-timeout` 的前提**：relay 只在任务登记了 `execution_budget.max_wall_s` 时接受这个参数，否则启动前就拒绝。P100、P101 没有登记，执行者没带这个参数，靠 CLI 的按格截止和停止线约束。P102 已登记 270 s，必须按卡面更正三的值带上。
- **账本查询**：先把 `control.sqlite3` 连 `-wal` 复制到报告目录，只在副本上查，不要直接用 sqlite 打开生产账本。
- 其余见 P102、P103 卡面的「更正三」。
