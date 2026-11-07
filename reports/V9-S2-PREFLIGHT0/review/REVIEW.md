自证声明：复核者为独立二级执行 agent gemini-8f4b（会话 sess-4bc4b7ff4dc0），非本改动作者（作者为一级统筹者 claude）；本次复核为纯只读独立核对，未修改任何仓库源码与测试，未导入或执行 MLX，未占用 GPU，未创建 git 提交或推送。

# 非作者复核报告：S2 运行前预检 Preflight 0（ainerzero.V9.P162）

- **结论**：**RECOMMEND_ACCEPT**
- **复核者**：`gemini-8f4b`（二级执行层）
- **改动作者**：`claude`（一级统筹层直接改动）
- **复核时间**：2026-11-07
- **评测与测试环境**：macOS (Darwin arm64), Python 3.12.2, pytest 9.1.1 (纯 CPU 模式，Zero MLX / Zero GPU)

---

## 1. 改动背景与代码审查 (Code Review)

### 1.1 审查目标与背景
在原 `s2/commands.py` 中，非 `verify` 模式调用 `_check_approval_preflight(research_log)` 时未传入 `expected_sha256` 参数，导致任何符合语法格式的批准行均可放行，未能与当前冻结的预登记文档形成强绑定；此外，代码源文件的哈希一致性仅在 `verify` 模式下核验，而在实际运行模式（`train`、`generate-data`、`plan-select`、`dev-eval`、`final-eval` 等）未在起跑时核实源码是否脱离冻结版本。

### 1.2 源码改动范围
对比 P148 r3 交付基线（`commands.py` SHA: `dae571426f9fd44d539318860267b2350c9dc4ab157fca7bdabad5ec4ebe4e30`），本次一级改动仅对 `src/ainerzero/v9/experiments/s2/commands.py` 增加了 Preflight 0 门禁逻辑（L450-L490）：
- 检查 `prereg.json` 是否存在，若不存在则拒入：`status='refused', stage='unfrozen', exit_code=3`；
- 执行 `identity.verify_frozen_identity(prereg_file, repo_root=...)`：若代码摘要不匹配捕获 `FrozenIdentityMismatchError`，拒绝并返回 `stage='identity_mismatch', exit_code=1`；若校验过程异常则关闭放行返回 `stage='identity_verification', exit_code=1`；
- 核验 `document_sha256` 格式为合法 64 位十六进制；
- 调用 `_check_approval_preflight(paths["research_log"], expected_sha256=frozen_sha)`，强制将批准行中的哈希与预登记文档哈希强绑定。

差异已完整记录于 `reports/V9-S2-PREFLIGHT0/review/commands_preflight0.diff`。

### 1.3 测试套件改动核查
- `tests/v9/experiments/test_s2_lifecycle.py`：
  - 新增 `_freeze_and_approve` 辅助函数，在临时目录真实冻结预登记并写入精确匹配的批准行；
  - 调整用例 (a) 为「已冻结、缺少批准行」（保持拒绝与零写入断言不变）；
  - 更新用例 (b)(c)(d)(f) 改用 `_freeze_and_approve` 获取真实哈希；
  - 新增用例 (g) 未冻结时拒入、(h) 批准行文档哈希不匹配时拒入、(i) 源码身份不符时拒入、(j) 真实冻结且哈希一致时准入；
  - 原有账本隔离、只读核验、零写入等断言未做任何削弱。
- `tests/v9/experiments/test_s2_train_runner.py` 与 `test_s2_wiring.py`：
  - 将此前使用的任意伪哈希改为了真实调用 `freeze.freeze(prereg.build_draft())` 生成的真实文档哈希，保持测试严谨性，未削弱任何既有断言。

文件 SHA256 核验：
- `src/ainerzero/v9/experiments/s2/commands.py`: `7334402af1a592795f710fd06266892727280ce5cd85a0d802f888e829a39fef`
- `tests/v9/experiments/test_s2_lifecycle.py`: `640bfac9bff90f389783226728b0e7c0968025f00a97ed1fee922cbdfa4b1337`
- `tests/v9/experiments/test_s2_train_runner.py`: `58ef5871ad4f9e9e8ef6c490a467f6a37b65851d436f6d6a9415e0e653eb6147`
- `tests/v9/experiments/test_s2_wiring.py`: `5d7631c803b602e3bbceaef2c35b650daef7a697597c281e87ca332f89f6cb9d`
所有文件与作者提交的 `sha256.txt` 100% 逐字节一致。

---

## 2. 4 门禁独立实测 (Four-Gate Verification)

在临时沙箱环境中，复核者独立执行了对 4 个门禁状态的严格黑盒测试（真实改动磁盘文件字节，不依赖全局 mock），结果如下：

| 门禁分支 | 测试场景 | 预期状态 | 预期 Exit Code | 实际返回状态与 Stage | 实测结果 |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Gate A** | `prereg.json` 不存在 | refused | 3 (REFUSED_APPROVAL) | `status='refused', stage='unfrozen'` | **PASSED** (未碰账本) |
| **Gate B** | 已冻结，批准行哈希与文档不匹配 | refused | 3 (REFUSED_APPROVAL) | `status='refused', stage='approval'` | **PASSED** (未碰账本) |
| **Gate C** | 已冻结且批准行匹配，但在磁盘上真实篡改 `spec.py` 1 字节 | refused | 1 (FAILED) | `status='refused', stage='identity_mismatch'` | **PASSED** (精准检测并报出 `spec.py` 差异) |
| **Gate D** | 已冻结、源码未动、批准行哈希完全匹配 | completed | 0 (COMPLETED) | `status='completed'` | **PASSED** (成功准入并完成 runner 调度) |

详细执行记录保存在 `reports/V9-S2-PREFLIGHT0/review/four_gates_log.json`。

---

## 3. Reviewer Bad Control 变异测试 (3 项独立变异)

在 `/tmp/ainerzero_p162_bad_control` 沙箱中执行了 3 项独立代码变异，检验对应测试是否严格变红（Turn RED）：

### 变异 1：去掉 `commands.py` 中的 `expected_sha256=frozen_sha` 绑定
- **变异操作**：将 `_check_approval_preflight(paths["research_log"], expected_sha256=frozen_sha)` 改为 `_check_approval_preflight(paths["research_log"])`。
- **靶标测试**：`tests/v9/experiments/test_s2_lifecycle.py::test_h_run_mode_refused_when_approval_names_other_document`
- **实测结果**：**变红 FAILED**（靶标用例断言 `assert code == commands.EXIT_REFUSED_APPROVAL` 失败：`E assert 0 == 3`）。
- **恢复验证**：代码恢复后 SHA 100% 还原，测试重回 PASSED。

### 变异 2：跳过 `commands.py` 中的 `identity.verify_frozen_identity` 源码身份核验
- **变异操作**：跳过 `verify_frozen_identity`，直接读取文档中的 document_sha256。
- **靶标测试**：`tests/v9/experiments/test_s2_lifecycle.py::test_i_run_mode_refused_on_source_identity_mismatch`
- **实测结果**：**变红 FAILED**（靶标用例断言 `assert report["stage"] == "identity_mismatch"` 失败：未抛出异常直接跳过，用例捕获阶段不符）。
- **恢复验证**：代码恢复后 SHA 100% 还原，测试重回 PASSED。

### 变异 3：移除 `commands.py` 中的 `prereg_file.is_file()` 存在性预检
- **变异操作**：注释掉 `if not prereg_file.is_file(): return ..., EXIT_REFUSED_APPROVAL`。
- **靶标测试**：`tests/v9/experiments/test_s2_lifecycle.py::test_g_run_mode_refused_when_unfrozen`
- **实测结果**：**变红 FAILED**（靶标用例断言 `assert code == commands.EXIT_REFUSED_APPROVAL` 失败：`E assert 1 == 3`，且 stage 变为 `identity_verification` 而非 `unfrozen`）。
- **恢复验证**：代码恢复后 SHA 100% 还原，测试重回 PASSED。

变异记录及失败堆栈已写入 `reports/V9-S2-PREFLIGHT0/review/reviewer_mutations.json`。

---

## 4. 全量 Pure-CPU 回归与实盘保护 (Full Regression & Artifact Integrity)

- **执行命令**：`reports/V9-S2-PREFLIGHT0/review/run_full_regression.py`（内部调用 `.venv/bin/python -m pytest`，并在父子进程显式还原 `SIG_DFL` 信号处理）。
- **回归耗时**：301.76 秒。
- **测试结果**：`3621 passed, 6 deselected, 0 failed`。
- **实盘保护核验**：
  - 测试运行前扫描 `artifacts/` 目录节点数：80929。
  - 测试运行后扫描 `artifacts/` 目录节点数：80929。
  - 前后比对差异数：**0 处变动 (diff_count: 0)**。
  - 详细统计保存在 `reports/V9-S2-PREFLIGHT0/review/stat_comparison.json`。

---

## 5. 验收结论

一级统筹者在 `commands.py` 中实现的 Preflight 0 门禁逻辑严密、契约清晰：
1. 彻底补齐了非 verify 运行模式下的代码身份防漂移机制与批准行预登记文档 SHA256 强绑定机制；
2. 4 门禁全场景实测表现符合预期；
3. 3 项靶向变异均能有效变红，证明对应测试用例敏感度充足，无断言弱化或虚假通过；
4. 全量 3621 条纯 CPU 回归全过，实盘 `artifacts/` 严格零改动。

**建议结论**：`RECOMMEND_ACCEPT`（建议完全验收合入）。
