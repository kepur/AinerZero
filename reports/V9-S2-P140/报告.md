# S2 预登记冻结补测与 approval_line 校验交付报告（ainerzero.V9.P140）

- **执行代理**：`gemini-w4x2`（二级执行 Agent）· 纯 CPU（零 MLX 导入、零实盘写入）
- **修改范围（严格限定）**：
  - `src/ainerzero/v9/experiments/s2/freeze.py`：仅改动 `approval_line` 这一个函数。先对传入 sha 执行 `.strip().lower()`，严格断言长度必须为 64 位且完全匹配 `[0-9a-f]{64}` 正则，否则即刻抛出 `ValueError`；除该函数外，`freeze.py` 其余代码逐字节不变（详见 `reports/V9-S2-P140/freeze.diff`）。
  - `tests/v9/experiments/test_s2_freeze_identity.py`：补齐两条关键单测，测试集总计 8 项全部通过。
- **补齐单测覆盖**：
  - `test_p140_cli_snippet_tamper_detected_and_names_cli_py`：在隔离 staged repo 冻结后篡改 `cli.py` 中 s2-phase1 段落的单字节，运行时核验即刻抛出 `FrozenIdentityMismatchError` 并明确点名 `src/ainerzero/cli.py:s2-phase1`；
  - `test_p140_approval_line_validation`：核验 63 位、65 位、含非法字符 'g'、空字符串均严格抛出 `ValueError`；大写 64 位十六进制合法转换为小写并成功生成规范批准行。
- **坏对照对抗变异（隔离沙盒副本，均精准变红 KILLED，已按字节还原并校验 SHA256）**：
  - **P140-M1**（去除 `cli.py` s2 段落摘要抽取）：`test_p140_cli_snippet_tamper_detected_and_names_cli_py` 变红拦截（KILLED, exit 1）；
  - **P140-M2**（去除 `approval_line` 64 位十六进制格式校验）：`test_p140_approval_line_validation` 变红拦截（KILLED, exit 1）。
- **全量纯 CPU 回归与实盘零写入审计**：
  - 前台纯 CPU pytest（`SIG_DFL` 信号还原）：**3538 passed, 6 deselected, 0 failed**（总计 3544 项）；
  - 实盘 `artifacts/` 全量 80,929 项在测试前后执行 stat 对比：**0 新增、0 删除、0 修改（零差异）**。
- **产物清单**：详见 `reports/V9-S2-P140/sha256.json`。
