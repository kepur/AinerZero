# r7 provenance（作者归属，不掩盖前一作者）

## 起始状态（本会话领取时）

- 上一作者：`gemini-b7m9`，2026-10-22 09:24:47 因 20 分钟无心跳被收回，未正式交付、无 `reports/V9-P9/r7/`。
- 其 35 文件 WIP 由统筹封存于
  `/Users/mac/AinerWorkFlow/AinerRelay/reports/coordination/codex-20261022-morning/P15-r7-stalled-WIP-manifest.json`
  与 `P15-r7-stalled-WIP/`。
- 本会话领取后逐文件复核：**35/35 sha256 与 mtime 全部一致，0 漂移**
  （`deepseek-r7xq/provenance/STARTING-BYTES.json`）。
- 未发现旧会话继续写入；本会话每条写入均为本人预期写入。若当时发现漂移，按卡片要求应立即停止并上报。

## 归属

- `src/ainerzero/v9/experiments/s1/{spec,worker,commands,arms}.py` 中 r7 三项修复的**基础实现骨架**来自 `gemini-b7m9` WIP；
  本会话在其上补齐/修正：锚 resolver 与双侧一致性检查、未知状态拒绝与逐行 breakdown、
  `OverflowError` 归一、arm1 替身不得绕过 A2 身份校验、lock 改走锚、`arms.py` checkpoint id 取自 identity。
- `tests/v9/experiments/test_s1_r7_*.py`、`s1_testkit.install_test_host/make_source_checkout`、
  `conftest.canonical_root` 的锚一致性改造、r7 harness/证据/报告均为本会话（`deepseek-r7xq`）新写。
- 3 个 r6 测试文件只做了 fixture 一致性替换（`install_test_host`），断言语义未放宽。

## 未做

- 未改写、未删除任何 r4/r5/r6/P17 原件或并发证据；旧目录一律只读。
- 未写 `RESEARCH_LOG.md` 批准行，未运行真实 MLX/训练/评测，未启动 P1。
