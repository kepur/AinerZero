# P266：【L2·非作者复核】S6 冻结入口 P264（b40d97e0）非作者独立复核报告

复核者：gemini-w9x4（tier2 / gemini / code, math）。2026-11-16。
审查对象：S6 冻结入口 P264 交付（基于 commit `b40d97e0eebb6d87c3e1938f331e83d4ca8f676b` 与最新 HEAD `4f50808618aa13933683ad120a63f6046f4003ea`）。
设计依据：`reports/V9-S6-DESIGN/DESIGN-r3.md` §5、§7 第 5 条。

结论：**建议通过（recommend_accept）**。P264 对 S6 冻结入口的返工与 DESIGN-r3 集成方案完整合格，9 项核心检查全部通过，合规守卫与锚点机制坚固有效，未改变数值科学代码。本复核不构成真实 final 阶段启动授权。

---

## 摘要（少于 30 行）

- **审查对象**：P264 交付的冻结入口组件（`prereg_identity.py`、`make_prereg.py`、`prereg_evidence.py`、`run_s6p1.py`、单测套件）。
- **探针身份**：用 `git archive a33d34b` 重算 42 个数值源文件清单，SHA256 确为 `839063099cd798e73fa3e26cdaba3b859b2d63360f4ed8d3cc2ec54e25d610d3`；探针报告、账本与 cell 记录全部精准指向该清单。
- **当前身份**：当前冻结代码已提交；与探针清单文件集合完全相同，仅 `run_s6p1.py` 存在常数差异，其余 41 个文件逐字节相同。
- **AST 语法树占位比对**：运行器仅允许三处登记常数差异（两项预算上限与第三方元组）；新值强制要求纯数字字面量，5 种自拟绕过尝试全部被拒绝。
- **预算重分段**：新上限取自当前运行器（训练 19800s + 评测 5400s = 7h 不变）；旧探针外推计算（训练 18072.25s、评测 4212.69s）完全在新上限安全余量内。
- **第三方与环境**：通过 `importlib.metadata` 严格锁定 mlx、mlx-metal、numpy 安装版本与 RECORD SHA；拒绝 `unknown`；拒绝任何 `MLX_*` 环境变量。
- **报告锚点与自冻结**：构建器前置核验报告固定 SHA（4a79000a…）；预登记 manifest 完整纳入构建器与验证器（共 46 文件）。
- **真实干跑与变异测试**：真实探针干跑成功；`artifacts/` 目录全量 stat 比对零差异（无任何写改）；150 项 CPU 单测全过；原生经锁测试通过；8 处沙箱变异（5 项作者自测 + 3 项自拟对抗）全部被测试杀死（100%）。

---

## 1. 范围、独立性与代码身份

本复核者（`gemini-w9x4`）未参与 P264 开发，独立执行本次纯 CPU 审查。
- 目标提交：`b40d97e0eebb6d87c3e1938f331e83d4ca8f676b`（工作树当前检出 HEAD `4f50808618aa13933683ad120a63f6046f4003ea`，二者在所有 42 个数值源文件、构建器、验证器与测试上逐字节完全一致，唯一差异为研究记录与日志）。
- 工作树状态：无任何数值源文件修改，`git status --porcelain` 显示受审代码完全干净。

---

## 2. 逐项核验结论与证据

### 1. 探针身份（§7.5 第 1 条）——【通过】
- **核验方式**：直接从 git 历史执行 `git archive a33d34b5cb8d06800f584a0abcfd788d16f80fcb` 导出 42 个数值源码文件，使用 `GD.build_manifest` 独立构建清单并计算 SHA256。
- **结果**：
  - 清单文件数：42 个；
  - `manifest_sha256`: `839063099cd798e73fa3e26cdaba3b859b2d63360f4ed8d3cc2ec54e25d610d3`；
  - 探针报告 `reports/V9-S6-PHASE1/probe/EVAL-probe.json` 中 `code_manifest_sha256` 严格等于该值，`git_head` 严格等于 `a33d34b5cb8d06800f584a0abcfd788d16f80fcb`；
  - 训练账本 `artifacts/v9/s6/phase1/probe/train-ledger.json` 中各闭合记录的 `code_manifest_sha256` 均严格等于该值；
  - 6 个探针 cell 记录命名空间严格为 `s6p1-pcand`，与探针规格一致。

### 2. 当前身份（§7.5 第 2 条）——【通过】
- **核验方式**：调用 `prereg_identity.current_identity(REPO, probe_root, probe_manifest)` 进行核验。
- **结果**：
  - 冻结代码已处于已提交干净状态（`head: 4f50808618aa13933683ad120a63f6046f4003ea`）；
  - 当前代码清单与探针清单文件集完全相同（42 个文件，`set(current) == set(probe_manifest)`）；
  - 唯一发生变更的文件仅为 `reports/V9-S6-PHASE1/run_s6p1.py`（`changed == ['reports/V9-S6-PHASE1/run_s6p1.py']`），其余 41 个数值源码文件逐字节哈希完全一致。

### 3. 运行器只差三处（§7.5 第 3 条）——【通过】
- **核验方式**：审查 `prereg_identity.py` 的语法树占位比对机制（`runner_diff` 与 `_extract`），并在独立测试脚本中构造 5 种绕过尝试：
  1. `19800 + 0`（二元运算表达式而非纯字面量） -> 抛出 `IdentityError: a registered constant is not a plain numeric literal`；
  2. `int(19800)`（函数调用） -> 抛出 `IdentityError: a registered constant is not a plain numeric literal`；
  3. 修改 smoke 集 `train_cap_s` -> 抛出 `IdentityError: the runner differs from the probe's beyond the three registered constants`；
  4. 插入无害字符串/语句 -> 抛出 `IdentityError: the runner differs from the probe's beyond the three registered constants`；
  5. 传列表 `["numpy", "mlx.core"]` 而非元组 -> 抛出 `IdentityError: THIRD_PARTY must be a tuple of string literals`。
- **结论**：占位比对完全封闭，任何超出三处登记常数的改动（包括语义等价的表达式、其他集上限、语句、函数体等）均被严格拒绝。

### 4. 预算（§7.5 第 4 条）——【通过】
- **核验方式**：核对当前运行器常数与 `prereg_evidence.py` 中的预算外推计算。
- **结果**：
  - 当前运行器 `SETS['final']`：`train_cap_s: 19800`（5.5h），`eval_limit_s: 5400`（1.5h），总和 25200s（7h）保持不变；
  - 探针报告记录严格校验旧上限：`OLD_CAPS = (21600.0, 3600)`；
  - 真实探针外推值：
    - 训练：`18072.25s <= 19800s`（留出余量 1727.75s，约 8.7%）；
    - 评测：`4212.69s <= 5400s`（留出余量 1187.31s，约 22.0%）；
  - 外推完全落入新上限之内，不再发生误拒绝。

### 5. 第三方库（§7.5 第 5、6 条）——【通过】
- **核验方式**：调用 `prereg_identity.final_versions()`、`distributions()` 与 `mlx_environment()`。
- **结果**：
  - `final_versions`: `{'numpy': '2.5.3', 'mlx.core': '0.32.2'}`，与运行器启动检查一致；
  - `distributions`:
    - `mlx`: version `0.32.2`, RECORD SHA256 `288147063d5c...`, mtime `1791963309.988`；
    - `mlx-metal`: version `0.32.2`, RECORD SHA256 `cd13296d3f6f...`；
    - `numpy`: version `2.5.3`, RECORD SHA256 `a8c81c62b056...`；
    - 无任何 `unknown`；`mtime` 严格早于探针训练开始时间；
  - `mlx_environment`: 注入环境变量 `MLX_DUMMY=1` 时被立即拒绝，抛出 `IdentityError: MLX_* environment variables are set: ['MLX_DUMMY']`。

### 6. 报告锚点——【通过】
- **核验方式**：审查 `make_prereg.py:34, 49`。
- **结果**：`PROBE_REPORT_SHA256 = "4a79000a646e8a817bd2916dd0471fb9ca221b2dac9d30fd67d00bc01ac16e9e"`。在读取报告内容前首先校验 `hashlib.sha256(data).hexdigest() == PROBE_REPORT_SHA256`。篡改探针报告中任何计时或字段均会立即拒绝，彻底关闭了利用未锚定报告绕过预算的漏洞。

### 7. 冻结入口本身也被冻结——【通过】
- **核验方式**：检查 `make_prereg.py:66-67` 写入的 `doc["manifest"]`。
- **结果**：正式预登记 manifest 共冻结 46 个文件：42 个数值源文件 + `DESIGN-r3.md` + `verify_s6p1.py` + `make_prereg.py` + `prereg_evidence.py` + `prereg_identity.py`。构建器与所有验证器均受清单保护。

### 8. 真实干跑——【通过】
- **核验方式**：执行 `make_prereg.py --design reports/V9-S6-DESIGN/DESIGN-r3.md --probe reports/V9-S6-PHASE1/probe/EVAL-probe.json --out reports/V9-S6-PHASE1/p264-review/PREREG-r1.dryrun.json`，干跑前后比对 `artifacts/` 目录中所有文件的 stat 快照。
- **结果**：
  - 构建成功输出：`written .../PREREG-r1.dryrun.json files frozen: 46 est train 18072 est eval 4213`；
  - `stat-before.json` 与 `stat-after.json` 经比较完全一致（哈希与 mtime 零变动）；
  - 无任何训练账本写入，无 `s6p1-final` 生成，无 `FINAL_READ_ONCE` 标记创建；干跑产物命名为 `.dryrun.json` 以免混淆。

### 9. 改坏源码复验——【通过】
- **核验方式**：使用 `git archive b40d97e0` 在独立临时目录（`/private/var/folders/.../p266-mutation-sandbox-*`，断言与主仓库不同且在仓库外）建立沙箱，设置 `PYTHONPATH=<sandbox>/src`，执行变异验证脚本 `run_mutations.py`。
- **基线测试**：150 passed in 73.72s (0:01:13)，0 失败。
- **作者变异复验（5 处）**：
  1. `P1`（跳过报告锚点检查）：**KILLED**（1 failed, 107 passed）；
  2. `P4`（预算外推取 probe 旧上限）：**KILLED**（1 failed, 75 passed）；
  3. `P7`（跳过 MLX_* 环境变量检查）：**KILLED**（1 failed, 120 passed）；
  4. `P10`（接受非 DESIGN-r3.md 设计稿）：**KILLED**（1 failed, 121 passed）；
  5. `P14`（允许新值使用表达式折叠）：**KILLED**（1 failed, 116 passed）。
- **自拟独立变异（3 处）**：
  6. `M1`（NEW 登记错误第三方元组 `("numpy", "mlx")`）：**KILLED**（1 failed in 4.55s）；
  7. `M2`（NEW 登记错误旧预算上限 `21600/3600`）：**KILLED**（1 failed in 4.53s）；
  8. `M3`（跳过占位符 syntax-tree dump 比较）：**KILLED**（1 failed, 114 passed）。
- **变异杀伤率**：8 / 8（100% 全部被测试杀死）。

---

## 3. 测试套件运行证据

1. **CPU 单元测试**：
   - 命令：`.venv/bin/python -m pytest -q -p no:cacheprovider tests/v9/experiments/test_s6_prereg.py tests/v9/experiments/test_s6_prereg_identity.py`
   - 结果：`150 passed in 76.73s (0:01:16)`。
2. **原生 MLX 经锁测试**：
   - 命令：`.venv/bin/python reports/V9-S4-PHASE1/impl-review-r2-recheck/evidence/harness/hold_lock.py artifacts/locks/m0-worker.lock .venv/bin/python -m pytest -q -p no:cacheprovider --native-mlx tests/v9/experiments/test_s6p1_runner_native.py tests/v9/experiments/test_s6_cells_native.py`
   - 结果：`lock held by 32119; 24 passed in 64.14s (0:01:04)`。
3. **真实干跑前后 stat 校验**：
   - `artifacts/` 目录全量文件快照对比：`before == after` 完全一致（见 `stat-before.json` 与 `stat-after.json`）。

---

## 4. 资源守卫与合规声明

- 本次复核全程只读核查，除原生锁内回归外未调用模型运行，未执行任何训练/微调/世界生成，未触碰中央 RunStore。
- 未修改工作仓库内任何受控文件，未执行 git stash、checkout、reset、commit 或 push。
- 所有产物均限定保存在本复核目录 `reports/V9-S6-PHASE1/p264-review/`。
- 本报告建议通过 P264。冻结入口已具备正式冻结资格，后续正式预登记生成与 final 运行由一级统筹与用户授权推进。
