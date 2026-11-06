# V9.P130 S2 扰动补测试非作者独立复核报告（ainerzero.V9.P131）

- **非作者身份自证**：本复核执行代理为 `gemini-7a4c`（会话指纹 `sess-29466b545b5f`），独立二级执行 Agent；被验证任务 `ainerzero.V9.P130` 的作者为 `gemini-w4x2`。两者非同一代理，非同会话别名，无自审冲突。
- **复核结论**：**`RECOMMEND_ACCEPT`**（建议全量合并验收，无需降级或限缩范围）。

---

## 1. 变更范围与源码一致性审计

- **变更文件核验**：
  - P130 提交仅修改了测试文件：`tests/v9/experiments/test_s2_eval.py`（SHA256: `5e1d5f1d44a81c9cdd881365316eacb83273917c838f788c7e4747541f8008fb`）；
  - `src/` 核心算法实现零篡改：`src/ainerzero/v9/experiments/s2/eval.py` 的 SHA256 为 `9a98ef7e3042241f662bf66cc520f8f00c8b1e4d3c0de3b584cec954c9a4614c`，与此前验收版本逐字节一致；
  - 纯 CPU 运行，零 MLX 导入，零实盘写穿。

---

## 2. 新断言真伪与契约严密性核查

在 `tests/v9/experiments/test_s2_eval.py::test_perturb_inserts_at_step_20_and_is_reproducible` 中：
1. **扰动前轨迹（步骤 0..19）**：通过 `TrackingPlanner` 在决策 0..4（每决策 4 步）稳定输出 `ACTION_WAIT`，精确断言 `res1.actions_taken[0:20] == [ACTION_WAIT] * 20`，无任何提前扰动或偏移；
2. **扰动动作精确定位（步骤 20..24）**：扰动在 steps_used 达到 20 时触发，从 `Random(54321 + 99991)` 精确抽取 5 个动作，断言 `res1.actions_taken[20:25] == expected_perturb_actions`，断言真实有效且具有强区分度；
3. **规划器恢复控制（步骤 25 起）**：决策 5 被准时执行并呈现在 `actions_taken[25:29] == [ACTION_TURN_LEFT, ACTION_TURN_RIGHT, ACTION_WAIT, ACTION_WAIT]`，证明第 25 步准时交还控制权；
4. **原有断言未放宽**：保留并严格复核了 `perturb_applied is True`、`steps_used >= 25` 以及同种子跨回合的逐位 bit-for-bit 复现性（`actions_taken`、`trajectory`、`steps_used` 严格相等）；
5. **互斥对照组（non-perturb）**：在 `perturb=False` 回合下验证 `perturb_applied is False`，且决策 5 准时在步骤 20 执行（`actions_taken[20:24]`），与扰动行为严格互斥。

---

## 3. 独立变异测试矩阵（全部变红 KILLED）

复核者在完全隔离的临时沙盒环境中，针对 `src/ainerzero/v9/experiments/s2/eval.py` 执行了 4 处恶意破坏变异，原测试文件均灵敏变红（KILLED，退出码 1），未发生任何存活：

| 变异 ID | 变异描述与破坏点 | 预期破坏点 | 实测状态 | 捕获断言 / 退出码 |
| :--- | :--- | :--- | :--- | :--- |
| **REV-M1** | 扰动动作数量篡改为 4（`n_perturb_actions = 4`） | 扰动少于 5 步 | **KILLED** | `AssertionError: Expected perturb actions ...` (exit 1) |
| **REV-M2** | 扰动触发起点偏移至第 21 步（`perturb_at_step = 21`） | 扰动起点偏移 | **KILLED** | `AssertionError: Expected perturb actions ...` (exit 1) |
| **REV-M3** | 扰动动作数量篡改为 6（`n_perturb_actions = 6`） | 扰动超过 5 步 | **KILLED** | `AssertionError: Expected perturb actions ...` (exit 1) |
| **REV-M4** | 扰动动作被固定篡改为常量 `ACTION_FORWARD` | 扰动动作来源篡改 | **KILLED** | `AssertionError: Expected perturb actions ...` (exit 1) |

沙盒测试后均逐字节恢复原始代码并完成 SHA256 校验。

---

## 4. 全量回归与实盘零写入审计

- **前台信号与运行环境**：使用 `signal.signal(..., SIG_DFL)` 恢复默认信号处理器，前台拉起纯 CPU pytest 回归；
- **测试通过计数**：
  ```
  collected 3522 items / 6 deselected / 3516 selected
  ================ 3516 passed, 6 deselected in 257.87s ================
  ```
- **实盘零写入审计**：
  - 测试前扫描 `artifacts/` 条目数：80,929
  - 测试后扫描 `artifacts/` 条目数：80,929
  - 增删改差异统计：**0 差异（0 added, 0 deleted, 0 modified）**。

---

## 5. 验收建议与后续交接

- 建议主责统筹予以合并：`RECOMMEND_ACCEPT`。
- P123 提出的 REV-M4 存活问题已彻底闭环解决，S2 评测断言具备严密防篡改能力。
