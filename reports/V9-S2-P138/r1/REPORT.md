# S2 数据 runner 守卫修复交付报告（ainerzero.V9.P138）

- **执行代理**：`gemini-w4x2`（二级执行 Agent）· 纯 CPU（零 MLX 导入、零实盘正式生成）
- **修改范围**：
  - `src/ainerzero/v9/experiments/s2/data_runner.py`：仅改动守卫函数 `assert_output_root_is_permitted`（保留 `assert_output_root_is_temporary` 兼容别名）及其调用处；定义 `REGISTERED_HOST_ROOT` 与 `REGISTERED_OUTPUT_ROOT` 模块级常量（未动 `spec.py`，待 P125 验收后追加）；除守卫外其余代码逐字节未变（详见 `data_runner.diff`）。
  - `tests/v9/experiments/test_s2_data_runner.py`：新增 4 项测试覆盖放行与拦截契约，总计 11 项单测全部通过。
- **守卫新规则核验**：
  - **允许**：`output_root` resolve 后恰好等于 `REGISTERED_HOST_ROOT / "artifacts/v9/s2/phase1"`；
  - **允许**：任意不在 `REGISTERED_HOST_ROOT / "artifacts"` 之下的路径（如测试 tmp_path）；
  - **拒绝**：`artifacts/` 下的其他任意目录（如 `artifacts/v9/e1/phase2`、`artifacts/v9/s1/` 等）；
  - **拒绝**：符号链接绕路（比较前严格调用 `resolve()`，检测目标指向）；
  - **清除猜名**：彻底移除了按 `tmp/temp/pytest` 字符串子串猜测的旧逻辑。
- **坏对照对抗变异（隔离沙盒副本，均变红 KILLED，已按字节还原并校验 SHA256）**：
  - **P138-M1**（守卫对 artifacts 下所有路径均放行）：`test_p138_other_artifacts_path_e1_rejected` 变红拦截（KILLED, exit 1）；
  - **P138-M2**（比较前不调用 resolve 导致符号链接逃逸）：`test_p138_symlink_into_e1_artifacts_rejected` 变红拦截（KILLED, exit 1）。
- **全量纯 CPU 回归与实盘零写入审计**：
  - 前台纯 CPU pytest（`SIG_DFL` 信号还原）：**3535 passed, 6 deselected, 0 failed**（总计 3541 项）；
  - 实盘 `artifacts/` 全量 80,929 项在测试前后执行 stat 对比：**0 新增、0 删除、0 修改（零差异）**。
- **产物清单**：详见 `reports/V9-S2-P138/sha256.json`。
