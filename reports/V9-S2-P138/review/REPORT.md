自证声明：复核者为独立二级代理 gemini-a5b8（会话 sess-7b3b52555339），绝非 V9.P138 作者 gemini-w4x2，亦非 V9.P133 作者 gemini-7a4c，亦非其同会话别名。本次为全新独立会话纯 CPU 只读复核。

# 非作者复核报告：V9.P138 S2 数据 runner 守卫修正（ainerzero.V9.P139）

- **复核结论**：`RECOMMEND_ACCEPT`（强烈建议接受 P138，并建议统筹一级同时终审接受 P133）
- **复核代理**：`gemini-a5b8`（二级执行 Agent）· 纯 CPU 独立复核（零 GPU/MLX 导入、只读核对、零源码污染）
- **被复核任务**：`ainerzero.V9.P138`（作者：`gemini-w4x2`）及关联前置 `ainerzero.V9.P133`（作者：`gemini-7a4c`）

---

## 1. 改动范围核查（契约完整性）

1. **`src/ainerzero/v9/experiments/s2/data_runner.py`**：
   - 守卫修正：`assert_output_root_is_permitted`（及向前兼容别名 `assert_output_root_is_temporary`）重写，仅放行精确匹配 `REGISTERED_HOST_ROOT / "artifacts/v9/s2/phase1"` 的生产登记路径，以及任意非 artifacts 目录；
   - 彻底清除子串猜测逻辑（已移除 `tmp`、`temp`、`pytest` 等弱名称推测）；
   - 参数 v2 追加项：生成 final 时同步在内存产出并写入 `sealed_final/LAYOUT_DIGESTS.json`；生成 dev/train 执行 `assert_partitions_disjoint` 时，对 `sealed_final` 严格只读 `LAYOUT_DIGESTS.json`。
2. **`src/ainerzero/v9/experiments/s2/spec.py`**：
   - 确认完全未改动（零修改、零脏代码）；
   - `REGISTERED_HOST_ROOT` 与 `REGISTERED_OUTPUT_ROOT` 通过 `getattr(spec, ..., fallback)` 安全读取，符合 P125 验收后的规范。
3. **`tests/v9/experiments/test_s2_data_runner.py`**：
   - 12 项单元测试全部通过（耗时 5.31s）。

---

## 2. 守卫规则独立验证（伪造根目录五种路径测试）

在独立的验证测试脚本 `reports/V9-S2-P138/review/verify_all.py` 中，使用隔离伪造的主机根目录验证了五种核心路径场景：
1. **登记路径**（`artifacts/v9/s2/phase1`）：**放行**（返回解析后的绝对路径）；
2. **e1 路径**（`artifacts/v9/e1/phase2`）：**拒绝**（抛出 `ValueError: output_root cannot point to non-registered artifacts directory`）；
3. **`artifacts/v9/s2/other`**：**拒绝**（严格抛出 `ValueError`）；
4. **符号链接绕道 e1**（外部目录建立 symlink 指向 e1）：**拒绝**（`Path.resolve()` 在判断前求值，成功拦截）；
5. **tmp 下的普通目录**（包括无 temp 关键字的自定义工作目录）：**放行**。
- **路径名猜测消除**：静态 AST 分析与动态测试均确认，代码完全基于 `out_path.is_relative_to(artifacts_root)` 拓扑比较，不再检查路径字符串名称。

---

## 3. sealed_final 零读回与字段核验（参数 v2 追加要求）

1. **`LAYOUT_DIGESTS.json` 字段核验**：
   - 生成 final 后，检查 `sealed_final/LAYOUT_DIGESTS.json`；
   - 字段严格限定为：`{"partition", "seed_namespace", "layout_digests"}`，无任何多余字段；
   - 确认绝不包含 `goal_episode_specs` 或任何回合具体轨迹规格。
2. **运行时读盘补丁拦截验证**：
   - 在随后生成 dev/train 分区时，对 `builtins.open`、`Path.read_text`、`Path.read_bytes` 全部挂载拦截钩子；
   - 捕获到对 `sealed_final/LAYOUT_DIGESTS.json` 的合法只读，且断言对 `sealed_final` 下除 `LAYOUT_DIGESTS.json` 外的任何文件（如 `manifest.json`、数据文件等）读取为零！

---

## 4. 复核者自做变异（3 处坏对照，全部变红 KILLED）

复核者在 `reports/V9-S2-P138/review/run_mutations.py` 中独立实现了 3 处变异测试，变异前后源码 SHA256 逐字节比对，100% 干净还原：

| 变异编号 | 变异位置与内容 | 拦截测试用例 | 运行结果 | 源码还原校验 |
|---|---|---|---|---|
| **REV-M1** | 守卫弱化为仅比对 artifacts 根目录（`out_path == artifacts_root`），允许子路径 | `test_five_guard_paths`（`s2/other` 与 `e1` 拦截用例） | **变红 KILLED** (exit 1) | SHA256 一致通过 |
| **REV-M2** | 在 `sealed_final/LAYOUT_DIGESTS.json` 中恶意注入 `goal_episode_specs` 字段 | `test_sealed_final_zero_readback_and_fields`（严格三字段断言） | **变红 KILLED** (exit 1) | SHA256 一致通过 |
| **REV-M3** | 不重叠检查中将 `sealed_final` 读取目标改回 `manifest.json` | `test_sealed_final_zero_readback_and_fields`（动态 I/O 补丁拦截） | **变红 KILLED** (exit 1) | SHA256 一致通过 |

---

## 5. 全量纯 CPU 回归与实盘零写入审计

- **执行方式**：通过 `relay exec` 前台纯 CPU 还原默认信号（`SIG_DFL`）执行；
- **测试结果**：**3536 passed, 6 deselected, 0 failed**（总计 3542 项，用时 268.73s）；
- **实盘 `artifacts/` stat 审计**：
  - 测试前扫描：80,929 项；
  - 测试后扫描：80,929 项；
  - **差异统计：0 新增、0 删除、0 修改（零差异）**。

---

## 6. P133 原有交付复核与终审建议

受统筹委托，本卡在修正后的 `data_runner` 上一并复核了 P133 的原有契约：
1. **重复执行拦截**：在 RunStore 账本已有 completed 记录时，重新请求同分区生成立即返回 `{"status": "duplicate_execution"}`，且原 manifest 的 `st_mtime_ns` 未受篡改；
2. **分区规模校验**：train 分区必须显式传入 `n_worlds` 与 `episodes_per_world`，未传时严格抛出 `ValueError`；dev 与 final 分区正常采用预设默认规模；
3. **账本生命周期与指标记录**：正确推进 `collecting -> completed` 状态，消耗 `active_seconds`，`SHA256SUMS.txt` 哈希准确记录。
- **终审评价**：P133 实现架构优良，P138 的安全修正彻底消除了实盘写入与密封数据泄露隐患，两张卡契约完备、测试充分。建议统筹 **同时接受 P133 与 P138**！
