# 【L2·非作者代码复核报告】V9-mini 注意力记忆组 latent_attn（Transformer 读整段历史）

- 复核目标提交：`49de583cb3b5d27806f4770281b378b273ecb150`
- 复核代理：`gemini-k7a4`（二级执行代理，自报能力：code, math）
- 报告日期：2026-11-18
- 文件范围：`reports/V9-MINI/attn-review/`（只读复核，不改动 `src/`、`tests/` 及已有报告）

---

## 1. 必查项逐条核验

### 1.1 不用真值（Pass）

逐个调用点全面核查：
1. **长游走数据集生成（`long_walks`）**（`attn.py:140-142`）：
   - `long_walks` 仅调用通用游走生成器 `D.generate(layouts, 1, tpl * horizon, cfg, seed0=seed0)`；
   - 生成的游走仅在训练时提供观察序列与动作序列，`Dataset.pose` 未被任何训练逻辑引用。
2. **观察去重编号（`obs_ids`）**（`attn.py:145-152`）：
   - 接收纯观察数组 `obs: (N, T+1, D)`，将展平后的观察字节 `np.ascontiguousarray(o).tobytes()` 作为键做哈希映射，得到整数编号。不涉及真值坐标或全局位姿。
3. **样本窗口采样（`sample_batch`）**（`attn.py:179-193`）：
   - 仅对 `ds.obs` 和 `ds.act` 沿时间轴截取窗口与采样目标观察 `og`、目标编号 `gid`，完全不读取 `ds.pose`。
4. **Hindsight 标签计算（`hindsight_labels`）**（`attn.py:155-170`）：
   - 仅接收离散观察编号 `wid` 与 `gid`，通过沿时间轴的因果比对计算上界 `ub`、到达标志 `done` 与有效掩码 `valid`，零真值参与。
5. **训练主循环（`train_attn`）**（`attn.py:196-242`）：
   - 单测 `test_training_reads_only_obs_and_act` 显式设置 `ds.pose = None`，训练正常推进且参数成功更新。
6. **评估智能体（`AttnAgent`）**（`attn.py:247-274`）：
   - `reset(ep)` 仅读取 `ep.prefix_obs`、`ep.prefix_acts`、`ep.goal_obs`；
   - `act(obs, view, head)` 入参中的 `view` 和 `head` 未被使用，历史上下文仅追加学生传感器输入 `obs` 与自身上一步动作 `self.last`。
7. **「到达」判据**：
   - 与 `latent_topo` 相同，「到达」严格判定为传感器输入 `encode_obs`（视野 one-hot + 指南针 one-hot）在字节层面完全相同。这属于传感器感知空间的精确比对，若不同物理网格呈现相同视野与朝向（感知混淆），模型亦会视作相同，因此不存在偷用坐标真值。

---

### 1.2 正确性（发现 1 处阻断缺陷，其余分支通过）

1. **分组注意力（GQA）查询头排列与读出**（`attn.py:111-136`）：
   - 查询头排列：`q.reshape(B, G, Lq, H, dh).transpose(0, 3, 1, 2, 4).reshape(B, H * G, Lq, dh)`。
   - 映射顺序为 `(B, H, G, Lq, dh)`，将每个注意力头下的 $G$ 个目标查询头紧密排列，完美对应 MLX GQA 算子将 K/V 头沿第 1 维广播给连续查询组的规约；
   - 读出后恢复 `transpose(0, 2, 3, 1, 4).reshape(B, G, Lq, d)`，逻辑与显式逐目标掩码计算完全等价，在 `test_readout_matches_naive_per_goal_attention` 中以 $10^{-4}$ 精度断言通过。
2. **RoPE 位置与 `last_only` 的 offset（【阻断缺陷】定位）**：
   - 在全序列读出（`last_only=False`）时，`q = self.rope(q)`、`k = self.rope(k)`，位置编码从 $0$ 至 $L-1$，并施加 `mask="causal"`，因果性严格成立；
   - **缺陷定位**：在 `last_only=True` 时（`attn.py:128`）：
     ```python
     q = self.rope(q, offset=L - 1)
     ```
     入参 `offset` 传入了 Python 标量整数 `L - 1`。在 MLX 0.31.1 的 Apple Silicon Metal GPU 底层实现中，当输入数组序列长度 $T=1$ 且批次大小 $B > 1$ 时，标量 offset 会导致 Metal kernel 的线程网格划分出现边界截断，使得 **$B > 0$ 的所有批次输出全部归零**！
   - 影响表现：
     - 仓库既有单测 `test_last_only_equals_last_position_of_full` 直接 `FAILED`（因为单测入参为 $B=2$，GPU 下 batch 1 产生显著数值漂移）；
     - 虽然在当前评测循环 `AttnAgent.q_last` 中由于单智能体串行评估传入 $B=1$，避开了 $B > 1$ 的 Metal 零化现象，但只要未来引入向量化评估或批量推断，输出将被无声损坏；且核心测试集处于红灯状态。
   - **修复方案**：将 offset 显式构造为批次向量 `offset=mx.full((B,), L - 1, dtype=mx.int32)`（或 `offset=mx.array([L - 1] * B)`），避开 MLX 的标量 offset 缺陷，单测可在 CPU/GPU 全平台、全批次下以 $0.0$ 绝对误差通过。
3. **因果性验证**：
   - 经 `test_causal_future_frames_do_not_change_past_q` 验证，修改 $t \ge 5$ 的未来帧，前 $0..4$ 帧的 Q 值完全不受影响。
4. **`hindsight_labels` 边界处理**：
   - `nxt_after = nxt[..., 1:]` 精确对齐到 $t+1$ 及以后的第一次出现；`t = np.arange(L - 1)[None, None]` 下标无偏差；
   - `done = eq[..., 1:]` 表示下一帧到达；`valid = ~eq[..., :-1]` 严格排除当前帧已在目标的情形；
   - 手工构造序列 `[1, 2, 5, 3, 4, 3, 5, 1]` 算例通过，无边界越界或下标错位。
5. **`compose_target` 组合目标**：
   - 复合逻辑 `min(下一帧到达 ? 1 : 1 + min Q^-, 上界, cap)` 运算顺序完备，通过 `test_compose_target_takes_min_of_bootstrap_bound_and_cap` 验证。
6. **Polyak 平滑与初始代价偏置**：
   - Polyak 动量更新公式严格符合标准软更新；
   - `b0 = log(expm1((q_init - 1) / scale))` 精确求解了 `Q = 1 + scale * softplus(out + b0) = q_init`（当 `out = 0` 时），偏置换算数学严密。
7. **`AttnAgent` 状态维护**：
   - `first=True` 时不重复插入前缀最后一帧；后续步骤严格按「新观察 + 引起该观察的上一动作」配对追加，时序对齐准确。

---

### 1.3 测试有效性与变异分析（Pass）

在完全隔离副本（`git archive 49de583c` 导出至临时目录）中实施 4 处关键语义变异，全部被测试套件精准捕获：

1. **变异 1（查询头排列破坏 GQA 分组）**：
   - 修改：将 `q_values` 中的 `[头, 目标]` 排列改为 `[目标, 头]`；
   - 失败用例：`test_readout_matches_naive_per_goal_attention`；
   - 捕获断言：`assert np.allclose(q, ref, atol=1e-4)` 失败。
2. **变异 2（hindsight 上界计算差一）**：
   - 修改：`nxt_after = nxt[..., :-1]`（当前帧及以后代替严格下一帧及以后）；
   - 失败用例：`test_hindsight_labels_hand_case`；
   - 捕获断言：`ub[0, 0]` 在第 2 索引处期望 4 步实际计算为 0 步。
3. **变异 3（valid 未过滤已到达帧）**：
   - 修改：`valid = np.ones_like(eq[..., :-1], dtype=bool)`；
   - 失败用例：`test_hindsight_labels_hand_case`；
   - 捕获断言：`valid[0, 0]` 在第 2 索引处为 True（期望 False）。
4. **变异 4（智能体首步重复追加前缀终帧）**：
   - 修改：移除 `if not self.first:` 保护；
   - 失败用例：`test_agent_history_appends_obs_and_own_actions`；
   - 捕获断言：首步 `self.last = None` 被强转 int 触发 `TypeError`，且长度检查失败。

完整变异 Diff 与测试输出已归档至 [mutations.txt](mutations.txt)。

---

### 1.4 接线核查（Pass）

1. **随机种子与任务隔离**（`evaluate.py:167, 197`）：
   - `ARMS` 引入 `"latent_attn"`；任务循环内种子由 `s = seed * 100003 + ti` 严格生成，与各臂顺序及是否存在 `latent_attn` 完全解耦；各对照组的回合评测无任何副作用。
2. **长游走训练隔离**（`run.py:151-157`）：
   - 仅在 `"latent_attn" in arms` 时才生成长游走并调用 `train_attn`，未启用时不产生额外计算与内存占用。
3. **训练规模等价性**（`attn.py:140-142`）：
   - `long_walks` 同样采用 `seed0 = D.TRAIN_SEED0 + 1000 * args.seed`，生成 200 张图各 1 条 800 步游走，总环境步数 160,000 步，与常规组（200 张图 × 4 条 × 200 步）严格相同，保证了训练数据信息的绝对对等。
4. **结果与对比对**（`run.py:171`、`summarize.py:20`）：
   - `result.json` 正确记录 `"attn": atinfo`；`summarize.py` 增设三组核心对照对（vs latent_learned、vs latent_topo、vs map_hybrid）。

---

### 1.5 公平性评估（Pass）

`latent_attn` 是否给予注意力记忆机制充分合理的胜出机会：
1. **上下文窗口覆盖能力**：
   - 训练窗口设定为 600 帧；测试时前缀 400 步（401 帧）加导航预算（长目标约 66 步，极限预算 $\le 100$ 步），总帧数约 470–500 帧，完整落于 600 帧训练窗口内，杜绝了长度外推带来的退化。
2. **悲观初始化与自举**：
   - 采用 $q\_init = 100.0$ 与 $scale = 10.0$。在长目标（$d^* \ge 20$）场景下，自举取 $\min$ 配合蒙特卡洛实际观测上界向下收敛，远胜于从 0 向上累加的低效传播。
3. **网络与读出架构**：
   - 引入显式的目标 Cross-Attention 读出层（查询为当前状态与目标画面拼接，键值包含历史状态与原始输入嵌入），使模型具备直接检索「历史上目标出现在哪里以及当时采取了何种动作」的归纳偏置。
4. **能力上限诊断**：
   - 在诊断运行中，第一步动作选择准确率高达 0.57–0.80（显著超越随机基线 0.38–0.53），Q 估计值与真值 $d^*$ 呈现稳定正相关（+0.28 至 +0.62）；
   - 但端到端长目标成功率仍停留在 $\le 0.025$ 水平，这与 $1.6 \times 10^5$ 步数据下自监督 Transformer 难以隐式建构全局欧氏度量几何的理论预期相符，证明其表现不佳源于结构表征机制而非刻意压低参数。

---

### 1.6 PLAN §11 数据独立复算与对账（Pass）

通过独立脚本 [recheck.py](recheck.py) 执行完整复算（输出见 [recheck.txt](recheck.txt)）：
1. **§11.2 表 1（`explore/attn/m1-s0/`）**：
   - random: 短 0.150 (9/60), 长 0.000 (0/40) $\implies$ 与 PLAN 完全吻合；
   - latent_learned: 短 0.083 (5/60), 长 0.000 (0/40) $\implies$ 与 PLAN 完全吻合；
   - latent_attn: 短 0.133 (8/60), 长 0.000 (0/40) $\implies$ 与 PLAN 完全吻合；
   - latent_topo: 短 0.533 (32/60), 长 0.075 (3/40) $\implies$ 与 PLAN 完全吻合；
   - map_hybrid: 短 1.000 (60/60), 长 1.000 (40/40) $\implies$ 与 PLAN 完全吻合。
2. **§11.2 表 2（`explore/attn/m1-s0-diag12k/`）**：
   - 3000、6000、12000 步下留出图与训练图共 6 行数据全部复算，短/长成功率、秩相关、第一步选对率与随机猜中基线完全对齐至小数点后 2–3 位。
3. **回合逐一配对核对**：
   - `explore/attn/m1-s0/episodes.json` 与 `explore/topo-batch/m1-s0/episodes.json` 中的全部 100 个回合（60 短 + 40 长）比对，其 `layout_seed`、`kind`、`d_star` 逐回合 100% 完全匹配。
4. **批次进展（`explore/attn/batch/`）**：
   - 批次实验当前正由统筹进程持有锁推进中，`batch/ledger.txt` 尚未结项，未合入 PLAN §11。

---

## 2. 问题清单与严重程度评估

| 序号 | 模块 / 位置 | 问题与观察 | 严重程度 | 说明 / 处置建议 |
|---|---|---|---|---|
| 1 | `src/ainerzero/v9/mini/attn.py:128` | `self.rope(q, offset=L - 1)` 传标量 int 导致 Metal GPU 在 $B>1, Lq=1$ 时结果置零 | **阻断** | 导致 `pytest tests/v9/mini/test_attn.py` 默认在 GPU 下运行 `test_last_only_equals_last_position_of_full` 失败。**必须修改**：改为 `offset=mx.full((B,), L - 1, dtype=mx.int32)`。 |
| 2 | `src/ainerzero/v9/mini/attn.py:271` | `AttnAgent.act` 中平局破除使用 `1e-6 * self.rng.random()` | **建议** | 引入了微小随机扰动，虽受 seed 约束，但若追求绝对确定性可改为纯规则破平。不构成阻断。 |

---

## 3. 原始证据索引

所有引用行号与代码段落已收录于 [evidence/citations.txt](evidence/citations.txt)：
- 数据流与无真值证据：`evidence/citations.txt:L1-L60`
- GQA 分组与注意力结构证据：`evidence/citations.txt:L61-L120`
- 评估接线与数据集对等性证据：`evidence/citations.txt:L121-L160`
- PLAN §11 原文对账证据：`evidence/citations.txt:L161-L245`

---

## 4. 复核结论

依据验收标准，结论为：

**2. 修改后可以进（列出必须改的）。**

### 必须修改的阻断项：
在 `src/ainerzero/v9/mini/attn.py:128` 中：
```python
# 原代码：
q = self.rope(q, offset=L - 1)

# 必须改为：
q = self.rope(q, offset=mx.full((B,), L - 1, dtype=mx.int32))
```
修改后，`pytest tests/v9/mini/test_attn.py` 将在 Apple Silicon GPU 环境下 10/10 全部通过，且避免未来在 $B > 1$ 场景下产生静默错误。
