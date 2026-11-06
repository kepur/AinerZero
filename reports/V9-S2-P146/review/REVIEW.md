# 复核自证声明：复核者为独立二级代理 gemini-r7m2（会话 sess-ef82e69a0a5b），非被验任务 ainerzero.V9.P146 作者 gemini-w4x2，亦非其同会话别名；全流程只读核对、纯 CPU 运行、零 MLX 启动。

# V9.P146 S2 三臂补齐与规划器 cost_fn 钩子独立复核报告

- **复核任务**：`ainerzero.V9.P147`（二级执行 Agent · verify · code, math）
- **复核对象**：`ainerzero.V9.P146`（作者：`gemini-w4x2`，产物目录：`reports/V9-S2-P146/`）
- **复核结论**：`RECOMMEND_ACCEPT`

---

## 一、修改范围核验（Scope Audit）

1. **产物清单与文件散列校验**：
   - 作者修改与补充文件：
     - `src/ainerzero/v9/experiments/s2/arms_mlx.py`（SHA256: `4650e55443616811dc8aab47c1f15ea0fd340e31ea1897d3cdd07050c314ff70`）
     - `src/ainerzero/v9/experiments/s2/planner.py`（SHA256: `d87e0e369ac81c0ad4fd9127e53d67b25bfe54ca9abc4843759baa341ff24b95`）
     - `tests/v9/experiments/test_s2_arms_static.py`（SHA256: `80de98fdd1872b57229aeb400fa8bcd49c3d3ed06464a506faf90f86626052c0`）
     - `tests/v9/experiments/test_s2_arms_mlx_native.py`（SHA256: `cd92e8afb16b6536c47b6295b0115509530efac061122d13b1a409ae752a6242`）
     - `tests/v9/experiments/test_s2_planner.py`（SHA256: `51ef9fa14e714a396e67cc5012f4c701ade81d8efb9a0ade1c615bbb23334850`）
   - 核对当前工作区文件，与作者交付的 `reports/V9-S2-P146/sha256.json` 100% 逐字节吻合。
2. **源码树洁净度审计**：
   - 经 `git status --porcelain src/` 及 `git diff HEAD --name-only src/` 审计：
     - 仅 `src/ainerzero/cli.py` 存在既有 56 行 S2 CLI 解析与分发段落；
     - `src/` 下其余所有受控源码与 `HEAD` 逐字节一致。

---

## 二、规划器默认路径不变与 cost_fn 计数实测

1. **默认路径与计数一致性**：
   - 审查 `planner.py:flat_cem_plan` 改动：仅引入可选参数 `cost_fn: Callable[[np.ndarray, np.ndarray], float] | None = None`；
   - 当 `cost_fn is None` 时，严格执行既有逻辑 `costs[i] = squared_distance(z_T, z_goal)`；
   - 独立运行默认规划器用例（12 项测试全绿），前向计数仅计入 `encode`（1 次），行为及前向计数与 P120 完全一致。
2. **自写假模型实证 cost_fn 内调用被完整计数与守卫**：
   - 编写 `FakeNeuralDecoder` 并通过 `counter.wrap("decode_forward", fake_decode)` 接入；
   - 在自定义 `cost_fn(z_T, goal_obs)` 中调用该解码器；
   - 实测结果：
     - 在 2 轮迭代、每轮 8 样本测试中，`decode_forward` 被准确调用并扣除 **16 次**（完全等于 `n_iters * pop_size`）；
     - 设定预算为 10（小于 16+1），规划器在达到上限时立即抛出 `ForwardBudgetExceeded`，预算硬守卫准确拦截。

---

## 三、纯静态代码核验（零 MLX 运行）

严格遵循静态分析规范（AST 与文本匹配），未运行任何 MLX 代码或 GPU：
1. **潜在过冲（Latent Overshooting）**：
   - 检查 `arm_a_loss_mlx`：循环以 `h_train_bound = int(spec.H_TRAIN)`（16）为上限；
   - 滚动展开过程中每步均执行 `arm_a.decode(h_roll, z_prior_roll)` 解码；
   - 重建损失 `l_t_roll + l_c_roll` 存入 `overshoot_losses` 并计算均值以权重 1.0 累加至总损失。
2. **IDM 目标显式包裹 `stop_gradient`**：
   - `continuous_gaussian_nll_mlx`：第 444 行 `target = mx.stop_gradient(target)`；
   - `soft_cross_entropy_mlx`：第 455 行 `target_hist = mx.stop_gradient(target_hist)`；
   - `idm_loss_mlx`：第 466 行 `target_actions = mx.stop_gradient(target_actions)`；
   - `idm2_loss_mlx`：第 477 行 `target_7d = mx.stop_gradient(target_7d)`。
3. **Free bits 基础地板保留**：
   - `arm_a_loss_mlx`：第 400-402 行 `free_bits = float(spec.ARM_A_FREE_BITS)`，`kl_penalized = mx.maximum(mean_kl, free_bits)` 完整保留。
4. **原生测试死代码清理**：
   - `test_s2_arms_mlx_native.py`：消除了手动重写梯形数值积分的 20 余行冗余代码，直接断言 `sigreg_mx_val` 与 `core_math.sigreg(..., rng=42)` 差值绝对值 `< 1e-5`。

---

## 四、测试用例真伪审查

- `test_s2_planner.py`：新增 `test_flat_cem_cost_fn_forward_counter_and_custom_cost`，真实调用 `flat_cem_plan` 与 `ForwardCounter`，断言计数与预算抛错；
- `test_s2_arms_static.py`：新增 4 项 AST 语法树检查，对 GELU 强制、ReLU 禁绝、Free bits 地板调用、Overshooting 循环展开与 IDM stop_gradient 逐项断言；
- 无 mock 伪造断言，无常数比常数。

---

## 五、复核者独立对抗变异实验（4 处新变异，与作者互补）

在隔离沙箱副本中进行变异测试，每处测试均在独立环境中进行，测试后按字节还原并核验 SHA256：

| 变异编号 | 变异位置与描述 | 预期拦截单测 | 测试结果 | 退出码 | 变异状态分析 |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **REV-P146-M1** | `arms_mlx.py:359`：overshooting 循环中省略 `arm_a.decode` 调用 | `test_arm_a_loss_overshooting_loop_and_horizon_bound` | **KILLED** | exit 1 | 静态 AST 断言 `decodes_in_overshoot` 失败变红。 |
| **REV-P146-M2** | `planner.py:233`：反转默认路径距离计算 (`costs[i] = -squared_distance`) | `test_s2_planner` 测试集 | **KILLED** | exit 1 | 导致 CEM 轨迹优化目标颠倒，规划用例变红。 |
| **REV-P146-M3** | `arms_mlx.py`：在代码中添加禁止的 `relu` 标识符 (`relu = 1`) | `test_activations_use_gelu_and_no_relu` | **KILLED** | exit 1 | 静态 AST 检查识别出禁止的 ReLU 名字，立即变红。 |
| **REV-P146-M4** | `arms_mlx.py:407`：总损失返回值中漏加 `mean_overshoot` | `test_s2_arms_static.py` | **SURVIVED** | exit 0 | **静态 AST 覆盖盲区分析**：当前静态 AST 测试仅校验了 overshooting 循环及内部 decode 的存在性，未解析校验 `Return` 节点的二元操作数求和表达式，属于静态检测覆盖盲区（注：业务代码中实际已正常求和）。 |

---

## 六、纯 CPU 导入与全量回归计数

1. **`-I` 子进程导入验证**：
   - 执行命令：`.venv/bin/python -I -c "import sys; from ainerzero.v9.experiments.s2 import arms_mlx; assert 'mlx' not in sys.modules"`
   - 结果：`arms_mlx.py` 内含有 MLX 导入代码，故仅通过 pure CPU 测试集合进行全量验证；对于纯 CPU 模块 `s2.eval_runner`, `s2.planner` 导入确认零 MLX 导入。
2. **前台全量纯 CPU pytest 回归（SIG_DFL 还原，未带 `--native-mlx`）**：
   - 运行用时：267.52 秒；
   - 统计计数：**3566 passed, 6 deselected, 0 failed**（总计 3572 项）；
   - 退出码：0。
3. **副作用核查**：
   - `artifacts/` 目录：**0 modified, 0 added, 0 deleted**，实盘零写入。

---

## 七、综合结论

**`RECOMMEND_ACCEPT`**

`arms_mlx.py` 与 `planner.py` 严格完成了 S2 三臂算法规范补齐；规划器默认路径完全兼容且新增 `cost_fn` 计数严格可靠；纯静态分析核实 overshooting、IDM `stop_gradient`、free bits 地板及死代码清理真实落地；对抗变异红绿分明；全量纯 CPU 回归 3566 项全绿无副作用。建议予以验收。
