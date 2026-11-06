# S2 数据 runner 守卫与封存 final 零读回修正交付报告（ainerzero.V9.P138 r2）

- **执行代理**：`gemini-w4x2`（二级执行 Agent）· 纯 CPU（零 MLX 导入、零实盘正式生成）
- **修改范围与实现内容**：
  - `src/ainerzero/v9/experiments/s2/data_runner.py`：
    1. **守卫修正**：`assert_output_root_is_permitted` 严格调用 `resolve()`，仅放行精确匹配 `REGISTERED_HOST_ROOT / "artifacts/v9/s2/phase1"` 的生产登记路径，以及任意非 artifacts 目录；拒绝其他 artifacts 路径与符号链接绕路；清除子串猜测；未动 `spec.py`；
    2. **封存 final 零读回机制**：生成 final 时用内存 `manifest_data` 另写 `sealed_final/LAYOUT_DIGESTS.json`（仅含 partition、seed_namespace、layout_digests 3 字段）；生成 train/dev 校验不重叠时，对 sealed_final 仅读 `LAYOUT_DIGESTS.json`，绝不打开 `manifest.json` 或任何其他 final 文件。
  - `tests/v9/experiments/test_s2_data_runner.py`：新增 5 项测试（包含打补丁断言 sealed_final 下除 `LAYOUT_DIGESTS.json` 外零读取），总计 12 项单测全过。
- **坏对照对抗变异（全隔离沙盒执行，3 处均变红 KILLED，已按字节还原并校验 SHA256）**：
  - **P138-M1**（守卫对 artifacts 下所有路径均放行）：`test_p138_other_artifacts_path_e1_rejected` 变红拦截（KILLED, exit 1）；
  - **P138-M2**（比较前不 resolve 导致符号链接逃逸）：`test_p138_symlink_into_e1_artifacts_rejected` 变红拦截（KILLED, exit 1）；
  - **P138-M3**（改回读取 sealed_final/manifest.json）：`test_p138_dev_generation_reads_only_layout_digests_from_sealed_final` 变红拦截（KILLED, exit 1）。
- **全量纯 CPU 回归与实盘零写入审计**：
  - 前台纯 CPU pytest（`SIG_DFL` 信号还原）：**3536 passed, 6 deselected, 0 failed**（总计 3542 项）；
  - 实盘 `artifacts/` 全量 80,929 项在测试前后执行 stat 对比：**0 新增、0 删除、0 修改（零差异）**。
- **产物清单**：详见 `reports/V9-S2-P138/r2/sha256.json`。
