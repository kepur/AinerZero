# E1-E1 入口第一半交付报告：spec 冻结常量 + prereg 冻结/校验/批准行查找（零训练）

- **任务 ID**：`ainerzero.V9.P71`
- **执行 Agent**：`gemini-t8m4`（Tier 2，kind: gemini）
- **交付日期**：2026-10-29
- **工作性质**：规范冻结常量、预登记冻结/校验/批准行检索扫描器、严格单测与对抗变异坏对照
- **权限与环境约束**：纯 CPU / NumPy / Python 标准库；零训练、零 GPU、零数据生成；不改写 `RESEARCH_LOG.md`（统筹写作用域）；不越过文件范围。

---

## 1. 交付文件清单

1. `src/ainerzero/v9/experiments/e1/spec.py`:
   - 引用定稿候选 r3 `reports/V9-P48/PREREG_DRAFT.md`（SHA256: `372e724bd6b028da9dde76d7f1fb52aa6e1497926b5a081a64032950662f2872`）各章节。
   - 臂表规范：定义 7 组臂，②③⑥ 训练参数量严格登记为 `6150`（直接对齐 `arms_net.REGISTERED_PARAMETER_COUNT`），④ 标为诊断组（tag `"diagnostic"`，训练参数 0），①⑤⑦ 训练参数 0。
   - 族与分区：P 族与 S 族；每族 train 1000、dev 200、final 200（共 2800 段）；固定数据种子 1001；3 个固定训练种子 `(42, 43, 44)`。
   - 指标常量直接从 `metrics.py` 导入（`DEFAULT_K_STEPS`, `PRIMARY_K=10`, `CONTACT_TOLERANCE_M=0.004`, `COLLISION_VELOCITY_THRESHOLD_MPS=0.05`, `COLLISION_DEBOUNCE_FRAMES=3`, `COLLISION_MATCH_TOLERANCE_FRAMES=1`, `BALLISTIC_MIN_FRAMES=5`, `BOOTSTRAP_RESAMPLES=10000`, `BOOTSTRAP_CONFIDENCE=0.95`）。
   - 判定门：主门槛 H-E1（③ 位置误差相比 min(①, ②) 改善 ≥ 10%，碰撞 F1 不下降）；探索性比较 H-P 与 H-S 仅报配对 bootstrap 区间，不设门。
   - 预算上限：总墙钟上限 32.0 h（115200 s），计算占空比 0.25；细分数据生成 7200 s、18 个训练格共 86400 s 墙钟、dev 评测 14400 s、final 评测 1800 s（各部件和 109800 s ≤ 115200 s）。
   - 主机锚定（fail closed）：`host_anchor_state()` 与 `host_anchor()`。
2. `src/ainerzero/v9/experiments/e1/prereg.py`:
   - `build_draft()`: 依据 spec 组装完整预登记草案字典及源码实现文件哈希。
   - `freeze(document, output_path=...)`: 在密封前执行 `validate()`，将状态更新为 `awaiting_coordinator_approval`，产出确定性规范 JSON 并计算其 SHA256。
   - `validate(document)`: 严格校验模式版本、试验 ID、臂结构与参数量（②③⑥ == 6150）、主门槛数值（0.10、k=10）、分区数量、训练种子、预算分项与总上限算术（分项和 ≤ 32 h）。
   - `approval_line(digest)`: 格式化唯一合规批准行 `APPROVED e1-phase2 prereg document_sha256=<64hex>`。
   - `find_approval(log_path, expected_sha256)`: 扫描 `RESEARCH_LOG.md` 专区 `## R20261029-E1-approval`；过滤代码块（``` / ~~~）、引用行（`>`）、缩进代码块；严格要求专区内恰有 1 行批准行且摘要匹配；遇到 0 行、多行、专区标题重名或摘要不匹配均抛出 `ApprovalRefused`。
3. `src/ainerzero/v9/experiments/e1/__init__.py`:
   - 导出 `spec` 与 `prereg`。
4. `tests/test_e1_prereg.py`:
   - 14 项完整覆盖规范常量、锚定失效安全、冻结确定性与键序独立性、文件输出、校验器防御（篡改架构、篡改参数量、篡改门槛、篡改预算）、批准行解析与全部异常场景。

---

## 2. 单元测试与回归证据

- **本模块测试**：
  `python3 -m pytest tests/test_e1_prereg.py -v`
  **14 passed in 0.15s**
- **E1 全量测试**：
  `python3 -m pytest tests/test_e1*.py -v`
  **71 passed in 2.96s**（包含 test_e1_arms_net 9 项、test_e1_arms_nonnet 11 项、test_e1_export 8 项、test_e1_metrics 16 项、test_e1_prereg 14 项、test_e1_prior 13 项）。

---

## 3. 四项对抗变异坏对照（Adversarial Mutants）

所有变异体均在 `/tmp/e1_e1_mutants/` 隔离目录中运行，并通过 `PYTHONPATH` 载入变异源码后执行目标单测，全部严格变红（FAILED as expected）：

| 变异体编号 | 变异部位与内容 | 载入源码路径验证 | 目标测试 | 结果与错误类型 |
|---|---|---|---|---|
| **Mutant 1** | `prereg.validate()` 绕过参数量校验（`params != 6150` 旁路） | `/tmp/e1_e1_mutants/mutant_1/src/.../prereg.py` | `tests/test_e1_prereg.py::test_validate_rejects_arm_parameter_mismatches` | **RED** (`DID NOT RAISE SpecValidationError`) |
| **Mutant 2** | `prereg.find_approval()` 允许专区内出现多行批准行（旁路 `len(rows) > 1` 检查） | `/tmp/e1_e1_mutants/mutant_2/src/.../prereg.py` | `tests/test_e1_prereg.py::test_find_approval_rejects_multiple_lines_in_section` | **RED** (`DID NOT RAISE ApprovalRefused`) |
| **Mutant 3** | `spec.canonical_json()` 禁用字典键排序（`sort_keys=False`） | `/tmp/e1_e1_mutants/mutant_3/src/.../spec.py` | `tests/test_e1_prereg.py::test_freeze_determinism_and_key_independence` | **RED** (`AssertionError: digest mismatch across key orders`) |
| **Mutant 4** | `prereg.validate()` 预算分项总和校验重言式化（旁路 `component_sum > total_ceiling`） | `/tmp/e1_e1_mutants/mutant_4/src/.../prereg.py` | `tests/test_e1_prereg.py::test_validate_rejects_budget_math_violations` | **RED** (`DID NOT RAISE SpecValidationError`) |

---

## 4. 零训练与合规承诺

- **零训练 / 零 GPU / 零生成**：本任务仅实现规范定义、JSON 序列化/反序列化校验及日志检索逻辑，不触碰任何真实模型参数更新或数据生成。
- **只读约束**：绝不在 `RESEARCH_LOG.md` 写入批准行，批准权完全留给统筹者。
- **文件与边界隔离**：修改范围仅限 `src/ainerzero/v9/experiments/e1/`、`tests/test_e1_prereg.py` 与 `reports/V9-E1E1/`。
