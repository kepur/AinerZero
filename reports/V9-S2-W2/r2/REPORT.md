# W2 r2（P164）：学习模型规划回合与检查点存取（一级 claude 实现，2026-11-07）

- **执行者：** 一级 claude（用户 11-07「你直接一级二级全做」）。r1 作者 gemini-b7x4；r2 原领取者 gemini-7k2q 停滞 76 分钟、盘上零改动，由一级收回。
- **复核：** 须由非作者 gemini 复核（P166）。claude、gemini-b7x4、gemini-7k2q 都不得领。

## 改了什么
| 项 | 位置 | 说明 |
|---|---|---|
| G1 真值隔离 | `learned_planning.make_plan_fn` | plan_fn 的签名只有 `obs, goal_obs, k, counter, rng`。由于 `run_episode` 按签名传参，state、layout、goal_state、spec 都到不了模型。不给模型设置任何属性；模型自带计数器时直接报错。eval.py 中 r1 新增的 goal_state/spec 传参已撤回 |
| G2 D3.1 | `cem_config_for_budget`，spec 末尾追加 | 种群、迭代数由 N_fwd 按公式推出；plan_choice 必填并严格校验；s₂、m、动作数都取自 spec；种群小于 2 时报错。宏动作在 [-1,1]^7 上搜索，再经 `denormalize_macro` 还原（r1 把宏动作当成 4 类离散值，真实 C 臂的维度对不上） |
| 观察特征 | `featurize_obs` / `featurize_goal` | obs 中的 dt 填本步宣告的 k，与训练数据口径一致（评测里原来填的是上一步的 k）；目标观察取 last_action=WAIT、dt=1，与回合起点的约定相同 |
| G3 检查点 | `adapters_mlx.checkpoint_path`、`ledger_checkpoint_sha`、`load_trained_model` | 路径唯一；期望 sha 只从 sqlite 账本读，且必须恰好有一条已完成的 train run，经 `ledger_read_snapshot` 读取；meta.json 不作依据；删除了多形态回退和 `except: pass` |
| G4 | `load_trained_models_for_planning` | seed 改为必填关键字参数 |
| **新发现 1：检查点保存崩溃** | `_save_params` / `_load_params` | 原实现 `np.savez(Path("best.ckpt"))` 实际写出 `best.ckpt.npz`，紧接着对 `best.ckpt` 算 sha 就抛 FileNotFoundError：三个臂的每一格训练都会在第一次存检查点时失败 |
| **新发现 2：E1 未保存** | 同上 | 原实现只展平两层参数，每臂约 85,632 个参数（E1 编码器全部）被丢弃。现改用 `tree_flatten`/`tree_unflatten`，键与形状严格比对。MLX 实测存取往返的最大差为 0.0（三臂各约 30.3–30.6 万参数） |
| **新发现 3：臂 A 无法规划** | `MLXArmAAdapter.encode` | 原实现返回 128 维的 E1 特征，而 `predict_l1` 需要 32 维的 z。现改为返回零 GRU 状态下的后验均值 |
| G5 | — | 不再改写 `model.counter`；改为要求模型不带计数器 |

## 规划协议问题（未在本卡修，见设计稿附录 E）
用完美假臂实测：§4 的协议（m=4、终点代价、后续步 dt 取 E[k]）连 oracle 都无法在长目标上成功。改为 m=1、轨迹求和代价、后续步 dt=1 后，12/12 成功。所以「完美臂成功率 > 0.5」这条用例移交 W5。

## 计算量（native 实测）
三个臂各规划 1 个决策（N_fwd=4096，未批量化）共 7.2 s，约 2.4 s/决策。按 m=1、每回合约 70 个决策估算，dev 评测远超预算，必须由 W5 做批量化。

## 测试与坏对照
- `test_s2_learned_planning.py`：39 条通过。覆盖 D3.1 公式（全部候选 × 3 档 N_fwd）、签名、TruthGuard 代理、编码计数（第 1 个决策 2 次、之后每个决策 1 次）、超预算报错、分层臂 L2 计数，以及检查点的 4 种拒绝情形。
- native（`--native-mlx`）：1 条通过，三臂各做一个决策。已登记进 NATIVE_MODULES，带标记，模块级导入 MLX。
- 默认全量：3660 passed, 6 deselected。前后对实盘 artifacts 做 lstat 比对（mtime、ctime、size、ino），差异为 0。
- 隔离副本坏对照（`run_mutations.py`）的 4 项均变红：真值参数、固定种群 32、跳过 sha 核对、plan_choice 默认值。
