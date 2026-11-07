# S2 接线收尾 r3 交付报告（ainerzero.V9.P148）

- **执行代理**：`gemini-m8d2`（二级执行 Agent）· 纯 CPU（零 MLX 运行，零 smoke 运行）
- **r3 依据**：DESIGN-r2.md 附录 B（r2.3）与一级 Claude 预检意见
- **核心交付**：
  1. **移除全量常数指标**：`smoke.py` 中 `measure_real_smoke` 彻底移除常数；第 3 步（短训健全性）与第 4 步（oracle 可行性熔断）在 P148 不实现，标记 `status='not_implemented'`，smoke 严格判为 `failed`，原因明确记录「短训健全性与可行性熔断待 P152 实现」。
  2. **计时改用登记批次形状**：批次形状采用 `(32, 17, 205)`（`observations: (32, H_train+1, 205)`，`actions: (32, H_train+1, 4)`，`dts: (32, H_train+1, 1)`），K=20 步，前置 1 步预热；三臂训练步数取最小值共用；预算按实测核算。
  3. **适配层支持批次张量**：`adapters_mlx.py` 增强支持 3D 批次输入，兼顾单序列与批次序列。
  4. **单测与对抗变异闭环**：`tests/v9/experiments/test_s2_wiring.py` 扩充至 16 项纯 CPU 单测，断言批次形状为 (32, 17, …)，断言未实现时必定 failed；P148-M1 至 P148-M5 共 5 处变异在沙盒中全部精准变红（KILLED，退出码非零），逐字节还原且 SHA256 一致。
  5. **conftest 与环境回归**：`tests/conftest.py` 严格仅增加 1 行 native 登记；80,929 项真实 artifact stat 审计结果 0 差异；全量回归 3556 passed / 40 failed（40 项失败皆因宿主机磁盘剩余 24.90 GiB < 50.0 GiB 门禁，为环境资源项，S2 全部 0 失败）。
- **产物清单**：详见 `reports/V9-S2-P148/r3/`（`sha256.json`, `commands.diff`, `conftest.diff`, `mutation_summary.json`, `stat_comparison.json`, `tests_list.txt`）。
