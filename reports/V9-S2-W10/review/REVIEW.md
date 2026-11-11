# P185 非作者复核 · S2 集成 W10（P184）

- **结论：`RECOMMEND_ACCEPT`**
- **复核者：** `gemini-k8d4`（二级执行层；非 P184 作者；P184 作者为一级 `claude`）
- **被复核任务：** `ainerzero.V9.P184`（reported）
- **复核日期：** 2026-11-08
- **任务目标：** 非作者只读审查 S2 集成 W10（规划推理改走 MLX CPU 流、随机种子决定初始权重、过时 native 测试对齐当前契约）。亲手在独立进程验证跨进程种子确定性与熵隔离；在隔离副本中亲手复现 M1–M6 坏对照及自选变异；运行全部 7 个 S2 原生测试并在无并行干扰下复跑临时目录 smoke 预演；前台运行全量回归并核验实盘 artifacts 零改动。

---

## 1. 范围（Scope）

- **W10 声明修改文件**（共 5 个模块）：
  - `src/ainerzero/v9/experiments/s2/adapters_mlx.py`
  - `src/ainerzero/v9/experiments/s2/spec.py`
  - `tests/conftest.py`
  - `tests/v9/experiments/test_s2_plan_device_native.py`（新增）
  - `tests/v9/experiments/test_s2_adapters_mlx_native.py`（对齐 W8/W9 契约）
- **SHA256 逐一校验**：
  实盘盘上 5 个文件与 `reports/V9-S2-W10/sha256.txt` 逐字 100% 完全匹配：
  - `adapters_mlx.py`: `7c89a728a0ea5cd153a518bfb240eb1688165f39b86b41fb2985bcdf024a3434`
  - `spec.py`: `b5b92c9aa83550e212259cfce65bb1fe01f0ff905ce9fe667729da068c94ed94`
  - `tests/conftest.py`: `ba840651b0ac400cec663ee5f815341d605455666f7682057b5ad689e1a04690`
  - `test_s2_plan_device_native.py`: `b38b9e8d9c4d00584731208788963279693c9387958c029a4c88d4d700ce2214`
  - `test_s2_adapters_mlx_native.py`: `e8fefdd179c7849e4ef8a78c8c3ae0bf631d6f7e287afd034d83f9fee68653de`
- **补丁核对**：
  `git diff c478e0a~1 c478e0a -- src/ tests/` 与作者报告提交的补丁 `reports/V9-S2-W10/git_diff.patch` 逐文件比对，差异严格为 0。
- **工作树其他文件说明**：
  工作树中未跟踪文件均为历史任务残留输出（如 `reports/V9-B3-mlx-unitcost/`, `reports/V9-E1...`, `reports/V9-P44/`, 以及刚刚完成并验收的 `reports/V9-S2-W9/review/` 等），未触碰任何受保护文件（`commands.py`, `eval_runner.py`, `learned_planning.py`, `planner.py`, `probe_eval.py`, `artifacts/` 等）。

---

## 2. 回退清零（Zero Fallback Check）

对 `src/ainerzero/v9/experiments/s2/adapters_mlx.py` 全面 grep 目标模式：

| 检查模式 | 命中位置 | 缺数据时的流向与处理 | 判定 |
|---|---|---|:---:|
| `or []` | 无命中 | — | **通过** |
| `or {}` | 无命中 | — | **通过** |
| `getattr(..., default)` | `line 785, 797` | 用于账本路径解析（缺账本则抛出 `ValueError`）及 Counter 属性检查，无数据兜底。 | **通过** |
| `if ... is None else` | 无命中 | — | **通过** |
| `default_` | 无命中 | — | **通过** |
| `seed=42` | **零命中** | 原在 `train_step` 中的静默 `init(seed=42)` 已被彻底清除。 | **通过** |
| **未调用 init 报错** | `line 173, 305, 462` | 若 `self.optimizer is None`（未显式调用 `init(seed)`），直接抛出 `RuntimeError("train_step called before init(seed)...")`，严格 fail-closed。 | **通过** |
| **未知设备报错** | `line 37-39` | 若 `spec.PLAN_INFERENCE_DEVICE` 非 `"cpu"` 或 `"gpu"`，直接抛出 `ValueError`，绝无回退。 | **通过** |

---

## 3. 训练与推理的边界（Training vs Inference Boundaries）

1. **装饰器与方法包裹核查**：
   - 三个模型臂共计 **12 个推理方法** 被 `@_planning_device` 包裹：
     - `MLXArmAAdapter`: `encode`, `predict_l1`, `cost_fn`, `latents`（4 个）；
     - `MLXArmBAdapter`: `encode`, `predict_l1`, `latents`（3 个）；
     - `MLXArmCAdapter`: `encode`, `predict_l1`, `encode_l2`, `predict_l2`, `latents`（5 个）；
   - **非推理方法严格未包裹**：
     - `init`: 负责设定随机种子并重建模型与优化器，未包裹；
     - `train_step`: 真实模型梯度更新，严格在默认 GPU 上运行，未包裹；
     - `rollout_error`: 验证评估循环，未包裹；
     - `save` / `load`: 检查点 I/O，未包裹。
2. **生产调用链路溯源**：
   - `ainerzero.cli.main` -> `commands.py` -> `train_runner.py:466`：生产训练路径在训练循环前显式调用 `arm.init(int(seed))` 初始化权重与优化器，随后调用 `arm.train_step(batch)`；
   - `load_trained_model`（`adapters_mlx.py:768-800`）：仅调用 `model = factory(...)` 与 `model.load(ckpt)`，**绝对不调用 init**，杜绝了重置或冲掉已加载检查点权重的问题。

---

## 4. 种子决定初始权重（Seed Determinism Across Processes）

复核者编写测试脚本并在两个独立子进程中执行（各进程预先用不同的随机熵 `999999` 与 `123456789` 打乱全局 MLX 随机状态），比对三臂参数的 SHA256：

```bash
# Process 1 (Entropy: 999999)
ARM=arm_a SEED=42 ENTROPY=999999 SHA=c012ed73f55db26c4dda778950083ea000460b5492bf4c4f267b6d26014deb02
ARM=arm_a SEED=43 ENTROPY=999999 SHA=c987220f5822de32dc99957c3c0231034918544ab93fc13edf00263645b9b2f8
ARM=arm_b SEED=42 ENTROPY=999999 SHA=819401655d986f04a0d1544801ad1059f6c1bbbead7db9d6bce3f05adc402887
ARM=arm_c SEED=42 ENTROPY=999999 SHA=a6d86141a6ab6b4932716233d3f0203a024da0a2c9517bcfdd29367602bcc84d

# Process 2 (Entropy: 123456789)
ARM=arm_a SEED=42 ENTROPY=123456789 SHA=c012ed73f55db26c4dda778950083ea000460b5492bf4c4f267b6d26014deb02
ARM=arm_a SEED=43 ENTROPY=123456789 SHA=c987220f5822de32dc99957c3c0231034918544ab93fc13edf00263645b9b2f8
ARM=arm_b SEED=42 ENTROPY=123456789 SHA=819401655d986f04a0d1544801ad1059f6c1bbbead7db9d6bce3f05adc402887
ARM=arm_c SEED=42 ENTROPY=123456789 SHA=a6d86141a6ab6b4932716233d3f0203a024da0a2c9517bcfdd29367602bcc84d
```

- **核实判定**：
  1. 跨进程相同种子哈希逐字节一致（`c012ed73...`）；
  2. 相同臂不同种子哈希完全不同（seed 42 `c012ed73...` != seed 43 `c987220f...`）；
  3. 彻底解决了 MLX 全局 key 导致初始权重不可控的历史缺陷。

---

## 5. 亲手变异（Manual Mutations in Isolated Environment）

在隔离目录 `/tmp/s2_w10_mutation_env` 中验证 `import ainerzero` 指向副本（`assert "/tmp/s2_w10_mutation_env/src" in ainerzero.__file__` 通过）。

亲手测试卡面 M1–M6 及自选 M7 共 7 处变异，全部精准变红失败，还原后 SHA256 100% 恢复：

| # | 变异名称与操作 | 目标文件 | 变异后测试表现 (RED) | 还原 SHA |
|---|---|---|---|:---:|
| M1 | **忽略设备**：`_planning_device` 不切流直接返回 `fn(*args, **kwargs)` | `adapters_mlx.py` | **FAILED (RED)**: 3 failed, 15 passed | **恢复 (MATCH)** |
| M2 | **训练也包进规划设备**：`MLXArmBAdapter.train_step` 套上 `_planning_device` | `adapters_mlx.py` | **FAILED (RED)**: 2 failed, 16 passed | **恢复 (MATCH)** |
| M3 | **predict_l2 漏包**：去掉 `predict_l2` 上的 `@_planning_device` | `adapters_mlx.py` | **FAILED (RED)**: 2 failed, 16 passed | **恢复 (MATCH)** |
| M4 | **未知设备静默回退**：`spec.PLAN_INFERENCE_DEVICE` 非法时 fallback 到 GPU | `adapters_mlx.py` | **FAILED (RED)**: 1 failed, 17 passed | **恢复 (MATCH)** |
| M5 | **臂 B init 不重建模型**：`init` 仅设种子不重建 `self.model` | `adapters_mlx.py` | **FAILED (RED)**: 2 failed, 16 passed | **恢复 (MATCH)** |
| M6 | **臂 C 恢复静默种子 42**：`train_step` 恢复 `self.init(seed=42)` 兜底 | `adapters_mlx.py` | **FAILED (RED)**: 1 failed, 17 passed | **恢复 (MATCH)** |
| M7 | **自选变异：spec 规划设备设为 gpu**：`PLAN_INFERENCE_DEVICE = "gpu"` | `spec.py` | **FAILED (RED)**: 3 failed, 15 passed | **恢复 (MATCH)** |

详细记录见 `reports/V9-S2-W10/review/mutations_summary.json`。

---

## 6. 原生用例与临时目录 smoke 预演（Native Tests & Rehearsal）

### 6.1 原生用例执行
以 `--native-mlx` 运行 S2 全部 7 个原生测试文件：
```bash
PYTHONPATH=src .venv/bin/pytest tests/v9/experiments/test_s2_arms_mlx_native.py tests/v9/experiments/test_s2_adapters_mlx_native.py tests/v9/experiments/test_s2_arm_a_batched_native.py tests/v9/experiments/test_s2_learned_planning_native.py tests/v9/experiments/test_s2_production_e2e_native.py tests/v9/experiments/test_s2_train_native.py tests/v9/experiments/test_s2_plan_device_native.py --native-mlx -v
```
- **测试结果**：`37 passed in 9.04s`（100% 通过）。

### 6.2 临时目录 smoke 预演复跑
- 预检 `pgrep -fl pytest`：无任何正在运行的 pytest 进程（输出为空，严格单负载）。
- **实测输出原文**（详见 `reports/V9-S2-W10/review/smoke_rehearsal_review_out.txt`）：
```
ELAPSED 174.9
REASONS []
STEP_TIMES {'arm_a': 0.117523455619812, 'arm_b': 0.19253361225128174, 'arm_c': 0.2633127450942993}
PLAN_TIMES {'arm_a': {'median_seconds': 1.9619239375024335, 'episode_times': [2.0916221250008675, 1.8322257500039996], 'n_episodes': 2}, 'arm_b': {'median_seconds': 2.2777242709998973, 'episode_times': [2.2726507499974105, 2.282797792002384], 'n_episodes': 2}, 'arm_c': {'median_seconds': 1.0988881874982326, 'episode_times': [1.137903541995911, 1.0598728330005542], 'n_episodes': 2}}
STEP3_PASSED True {'arm_a': (True, 0, 0, 5.23217, 3.076295), 'arm_b': (True, 0.21106, 0.200484, 1.554658, 0.054514), 'arm_c': (True, 0.217135, 0.190644, 5.465669, 3.580894)}
STEP4 {'passed': True, 'success_rate': 1.0, 'fuse_triggered': False, 'n_episodes': None}
BUDGET_TOTAL 33485 passed True []
BUDGET_PARTS {'smoke': 1200, 'data': 1160, 'train': 5226, 'plan_select': 966, 'post_train_gates': 110, 'dev': 20020, 'final': 4805, 'total': 33485}
```
- **核心指标核实**：
  1. **总耗时**：`174.9 s`（< 1200 s 上限，CPU 流规划延迟大幅削减，比 W9 的 208 s 进一步缩短）；
  2. **reasons**：`[]`（完全为空，零报警）；
  3. **Step 3 短训**：三臂全部通过，数值与作者报告中第 1 次、第 2 次预演（`smoke_rehearsal_out1.txt` / `smoke_rehearsal_out2.txt`）**逐位完全相同**（B 臂 initial 0.21106, final 0.200484；C 臂 initial 0.217135, final 0.190644）；
  4. **Step 4 Oracle 熔断**：`passed: True, success_rate: 1.0, fuse_triggered: False`；
  5. **规划耗时中位数**：Arm A 1.96 s，Arm B 2.28 s，Arm C 1.10 s（较 GPU 流下降超过 50%）；
  6. **推算预算**：`BUDGET_TOTAL 33,485 s`（远远低于 54,000 s 上限，余量达 38.0%）。

---

## 7. 全量默认套件与实盘 artifacts 零改动审计

- **执行方式**：前台 `SIG_DFL+execv` 执行（通过 `relay exec --every 120` 维持心跳与进程组监督）：
  ```bash
  python3 /Users/mac/AinerWorkFlow/AinerRelay/bin/relay exec ainerzero.V9.P185 --agent gemini-k8d4 --every 120 -- python3 /tmp/run_pytest_full_w10.py
  ```
- **测试结果**：
  - 用时：`1090.20 s (0:18:10)`
  - 统计：`3725 passed, 7 deselected, 0 failed`（通过率 100%）。
  - 日志存入 `reports/V9-S2-W10/review/pytest_full_tail.txt`。
- **实盘 artifacts 审计（lstat 前后比对）**：
  - 测试前扫描：84,283 项（`reports/V9-S2-W10/review/artifacts_stat_before.json`）
  - 测试后扫描：84,283 项（`reports/V9-S2-W10/review/artifacts_stat_after.json`）
  - 比对维度：`ctime`、`mtime`、`size`、`ino`、`mode`
  - 差异汇总（`reports/V9-S2-W10/review/artifacts_diff.json`）：
    - `added`: 0
    - `removed`: 0
    - `changed`: 0
    - **实盘差异严格为 0（零写入）**。

---

## 8. 逐字抽查（Spot Checks）

从作者 `reports/V9-S2-W10/REPORT.md` 中随机抽取 4 处声明与实盘代码逐字比对（详见 `reports/V9-S2-W10/review/spot_checks.json`）：

| # | 报告声明 | 盘上实际位置 | 核查结果 |
|---|---|---|:---:|
| 1 | `adapters_mlx._planning_device` 装饰器包住三臂共 12 个推理方法，在 `mx.stream(<device>)` 内计算并转换成 numpy。 | `src/ainerzero/v9/experiments/s2/adapters_mlx.py:34-45` 及 12 处装饰点 | **一致 (MATCH)** |
| 2 | `init(seed)` 先 `mx.random.seed(seed)`，再重建模型和优化器。同时去掉 `train_step` 里静默 `init(seed=42)` 的回退，改为报错。 | `src/ainerzero/v9/experiments/s2/adapters_mlx.py:161-174, 293-306, 450-463` | **一致 (MATCH)** |
| 3 | 设备由 `spec.PLAN_INFERENCE_DEVICE` 决定，只追加，值为 `"cpu"`。不认识的值直接报错，不回退。 | `src/ainerzero/v9/experiments/s2/spec.py:340-344` | **一致 (MATCH)** |
| 4 | 坏对照：M1 忽略设备 3 条失败；M2 训练也包进 2 条失败；M3 predict_l2 不包 2 条失败；M4 未知设备回退 1 条失败；M5 臂 B init 不重建 2 条失败；M6 臂 C 恢复静默种子 1 条失败。 | `reports/V9-S2-W10/w10muts.py & tests/v9/experiments/test_s2_plan_device_native.py` | **一致 (MATCH)** |

---

## 9. 结论与建议

W10 补丁针对 smoke 预算与随机性根因进行了高精度的工程改进：
1. 单步 CEM 规划推理改走 MLX CPU 流，彻底消除了 GPU 流上频繁小张量 `numpy.asarray` 同步的巨大延迟（规划回合中位数降至 A 1.96 s、B 2.28 s、C 1.10 s），全流程推算预算缩减至 33,485 s（余量 38%）；
2. 修复种子决定初始权重的缺陷，清除了 `seed=42` 隐式回退，跨进程与同一进程均严格可复现，使 smoke 第 3 步自检数值在两次预演中实现逐位稳定复现；
3. 坏对照 M1–M6 及自选 M7 全部红绿闭环；原生用例 37 条全通；smoke 独立预演 174.9 s 零报警通过；全量测试 0 failed，实盘 artifacts 零改动。

**复核结论：`RECOMMEND_ACCEPT`**。
建议统筹予以接收，并推进后续 S2 r2 冻结与 smoke 运行。
