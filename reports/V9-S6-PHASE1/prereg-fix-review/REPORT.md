# P262：【L2·非作者复核】S6 预登记证据与预算守卫修复（P261，纯CPU）

复核者：gemini-w9x4（tier2 / gemini / code, math）。2026-11-16。承接上一棒 codex-s6freeze-rv-1115 之半成品并完成全量独立亲测与核验。

结论：**建议通过（recommend_accept）**。P261 针对 P259 阻断项 F1、F2、F3 之边界修复完整合格，合规守卫生效且原 42 文件数值代码未受破坏。本结论不构成任何真实模型训练/评测或 final 阶段启动授权。

摘要（少于 30 行）：
- 审查对象：P261 交付源码 `make_prereg.py`、`prereg_evidence.py`、`test_s6_prereg.py`。
- 源码精确 SHA 经复核逐字节一致；原 42 文件数值 manifest 仍为 `839063099cd798e73fa3e26cdaba3b859b2d63360f4ed8d3cc2ec54e25d610d3`。
- F1 / 证据闭包：入口核验 84 个原始产物闭包文件 SHA256，严格校验结构与数值合法性，重算 AN 统计；排他 `"x"` 写入保证失败零残留。
- F2 / 身份绑定：核对训练 ledger、eval、工作树与提交树一致性；明确保留原 probe run_eval 自检缺失事实，未修改运行器源码。
- F3 / 预算守卫：耗时严格正有限，禁止虚增分母；真实探针核算评测外推 4212.69s 严格超出 3600s 上限，入口按原线明确拒绝，守卫完全生效。
- 独立复核测试：109 项隔离 CPU 测试全部通过（102 项原测试 + 7 项独立边缘反例测试）；7 处生产验证器对抗变异全部被测试杀死（100%）。
- 纯 CPU 验证：全程禁止 MLX 导入（sys.modules 确认无 MLX），无世界生成，无训练/微调，无 git 提交推送，仅写报告目录。

---

## 1. 范围、独立性与输入身份

本复核者（`gemini-w9x4`）未参与 P261（`codex-s6preregfix-1115`）的开发与测试实现，与被审作者完全独立。承接上一棒留存的 `reports/V9-S6-PHASE1/prereg-fix-review/` 现场，所有数据均由独立脚本复测与重算。

工作仓库状态：
- 当前 Git HEAD：`a33d34b5cb8d06800f584a0abcfd788d16f80fcb`
- 42 个数值源文件在工作树中无任何未提交修改（`git status --porcelain -- <42文件>` 输出为空）。
- 42 个数值源文件 manifest SHA256 为：`839063099cd798e73fa3e26cdaba3b859b2d63360f4ed8d3cc2ec54e25d610d3`。
- 构建器与验证器纳入正式冻结 manifest（共 45 文件），未污染数值 42 文件 manifest。

被审文件精确 SHA256 清单：

| 文件路径 | SHA256 |
|---|---|
| `reports/V9-S6-PHASE1/make_prereg.py` | `0dd9d3be32fd49032b54df73fef3e895d9f3fff28349f3a41a21fb5087438731` |
| `reports/V9-S6-PHASE1/prereg_evidence.py` | `208f6c4b5361f420b7c69c166319f2ab26d266239b709439f3471cee249f88b6` |
| `tests/v9/experiments/test_s6_prereg.py` | `795dc4c50bdf0406b0074119d068830fa2ff31ea9cc1fc528067468e667e1692` |

---

## 2. 阻断项修复逐项核验

### F1：探针真实性与完整性证据闭包（P1）
- **闭包核验范围**：`prereg_evidence.py` 在 `validate_probe`（L254-358）中从固定 probe 根目录解析，完整覆盖 84 个产物文件（1 个 eval 报告、1 个 candidate pools、1 个 train ledger、6 个 cell.json、72 个权重 safetensors、1 个 verify.json、1 个 errors.npz、1 个 worlds.json），且核验每个文件的 SHA256。
- **结构与类型检查**：对 JSON 键使用带去重校验的 hook（L168-174），任何重复 key 直接拒绝；对所有配置、候选、权重、世界数严格检查结构与类型。
- **统计重算**：使用 NumPy 加载 `errors.npz`（`allow_pickle=False`），调用 `AN.decide` 和 `AN.describe` 重新计算所有能力门与描述统计量，并与 probe 报告核对；支持科学门正常未达成，但不允许与底层数据不符。
- **失败零写入保障**：`make_prereg.py` 在通过所有校验与序列化之后，最后才使用 `with out.open("x", encoding="utf-8")`（L70-71）写入输出文件；任何前置断言或序列化异常均不会在磁盘留下任何半成品或正式预登记文件。

### F2：代码身份与训练账本一致性核验（P1）
- **四方一致性绑定**：核对工作树代码、提交树代码（通过 `git archive` 提取 tar 包逐文件计算 SHA256，L127-147）、训练账本 `train-ledger.json` 中记录的 `code_manifest_sha256`（L306）以及评测报告中的 `code_manifest_sha256`（L273），确保四者完全一致。
- **如实保留运行器状态**：保留了原 probe 中 `git_head=None` 的事实，未伪造或补造 commit 字段；明确指出原 `run_eval` 的 probe 分支未实现对训练 ledger 源码的自检，将此检查收紧在预登记入口入口处，保全了既有 42 文件数值代码无需重跑或重训。

### F3：预算外推与耗时有效性守卫（P2）
- **耗时严格校验**：`prereg_evidence.py:number`（L39-42）强制耗时必须为正有限浮点数（特定选择耗时允许非负）；单 cell 内轮次耗时总和与 cell 总时间对照（容差 0.15s）；逐 cell 耗时与 ledger 耗时对照；严格限制必须恰好 6 格，不可伪造或虚增分母。
- **真实探针预算拒绝验证**：
  - 训练外推计算：`1.15 * (Σ train_seconds * reps + 450) = 18072.25s <= 21600s`。
  - 评测外推计算：`1.30 * (616.0 * 28 / 6 + 19.6 * 28 / 6 * 4) = 4212.693333s > 3600s`。
  - 真实运行测试中，`make_prereg.py` 准确抛出 `EvidenceError: 预计超出上限：训练 18072.250000 秒（上限 21600.0），评测 4212.693333 秒（上限 3600）`，且没有落盘任何正式预登记文件（见 `evidence/live-result.json`）。守卫真实生效。

---

## 3. 测试与变异验证

### 独立回归测试
在沙箱快照内运行包含 102 项原基线测试与 7 项独立补充测试（覆盖未关闭账本、旧训练代码、缺失复训记录、打乱世界顺序、非整数 counts、权重哈希不符、负耗时等边界）的完整测试套件：
```
109 passed in 70.71s (0:01:10)
MLX_IN_SYS_MODULES False
```
日志保存在 `evidence/tests-independent.out` 与最新重测记录中。

### 生产验证器对抗变异
在 `mutations/` 隔离副本中对生产验证器 `prereg_evidence.py` 进行 7 处核心断言变异（I1 至 I7），全部变异均被对应单测杀死（returncode 1，`DID NOT RAISE` 断言失败）：
1. `I1-open-ledger`: 变异 `closed` 检查 -> **KILLED**
2. `I2-old-train-code`: 变异 `code_manifest_sha256` 检查 -> **KILLED**
3. `I3-no-retraining-records`: 变异 `retrain` 存在性检查 -> **KILLED**
4. `I4-world-order`: 变异世界顺序与集合检查 -> **KILLED**
5. `I5-counts-dtype`: 变异 `counts` 整数类型检查 -> **KILLED**
6. `I6-weight-hash`: 变异权重哈希检查 -> **KILLED**
7. `I7-negative-number`: 变异非负/正有限数检查 -> **KILLED**

变异杀死率：**7 / 7 (100%)**。

---

## 4. 资源守卫与合规声明

- 本任务执行全程为纯 CPU 操作，未导入 MLX（sys.modules 显式断言检查），未调用 GPU，未加载模型权重，未生成任何环境世界。
- 未修改任何源码或测试代码，未修改已交付的 P261 报告，未执行 git commit 或 git push。
- 唯一写入目录限定为 `/Users/mac/AinerWorkFlow/AinerZero/reports/V9-S6-PHASE1/prereg-fix-review/`。
- 本报告建议通过 P261。真实探针已由入口正确触发评测超限拒绝，后续是否调整 final 预算分配或启动下一阶段，由一级统筹依据相关规则裁决。
