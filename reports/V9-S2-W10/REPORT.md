# S2 集成 W10：规划推理改走 CPU 流，种子决定初始权重（一级 claude，2026-11-08）

起因：P183 复核者的临时目录 smoke 预演测得的规划耗时，推算总预算 67,385 s，超过 15 h（54,000 s）。

- 那次预演和一级的全量测试同时运行，CPU 有争用。
- 一级第三次预演（R20261108-S2-smoke-rehearsal）没有负载争用，推算为 53,844 s，余量只有 0.3%。
- 正式 smoke 的预算门一遇噪声就会失败，而 smoke 失败不重试，所以冻结 r2 之前要先解决。

## 1. 剖析（臂 A，一个长目标回合，未训练模型）

剖析脚本在临时目录，基准脚本见 `bench_device.py`。

- 一个回合有 72 个决策，每个决策调用 128 次 `predict_l1`（4 轮 CEM × H=32），合计 9216 次。
- 总耗时 4.45 s，其中 3.7 s 花在 `numpy.asarray` 上，也就是每次调用都把 MLX 结果同步回 numpy。
- 每次调用只有 15–63 行（flat pop = (N_fwd−8)//(4H)），GPU 的耗时以每次同步的延迟为主。

## 2. 改动

### 2.1 规划推理设备

- `adapters_mlx._planning_device` 装饰器包住三臂共 12 个推理方法（encode、predict_l1、cost_fn、latents、encode_l2、predict_l2），在 `mx.stream(<device>)` 内计算并转换成 numpy。
- 设备由 `spec.PLAN_INFERENCE_DEVICE` 决定，只追加，值为 `"cpu"`。不认识的值直接报错，不回退。
- train_step、rollout_error、init、save、load 不包，训练仍走默认的 GPU。
- 规划代码（planner、learned_planning、eval、eval_runner）一律未改，协议、N_fwd、回合数和门槛都不变。

### 2.2 种子决定初始权重（顺带发现的缺陷）

- MLX 的全局随机 key 每个进程都不同：两个进程 `mx.random.normal((3,))` 的结果不一样。
- 三个适配器都在 `__init__` 构造模型，`init(seed)` 只设种子、不重建模型。所以登记的种子不决定初始权重，同一个训练格每次的初始权重都不同。
- 修复：`init(seed)` 先 `mx.random.seed(seed)`，再重建模型和优化器。
- 同时去掉 `train_step` 里静默 `init(seed=42)` 的回退，改为报错。原回退在加载 checkpoint 后误调用时会重置权重，也会掩盖漏设种子的问题。
- 这个缺陷让 smoke 第 3 步不稳定。W10 第一次预演（`smoke_rehearsal_out0_before_seed_fix.txt`）中，臂 B 的 SIGReg 从 0.207 升到 0.239（1.154 倍，超过 1.1 倍的门），而单独重跑时为 0.95–0.97 倍。修复后两次预演第 3 步的数值逐位相同。

### 2.3 过时的 native 用例

`test_s2_adapters_mlx_native.py` 的 2 条用例在 HEAD b72a79e 上就已失败。一级用 `git archive HEAD` 导出隔离副本复现过：

- 一条用旧的 dts 形状 (B,T,1)，W8/W9 的契约是 (B,T)；
- 一条认为臂 A 的 encode 返回 128 维，W5/W9 之后是 32 维的 z。

此前各卡都没有跑过这个 native 文件，本卡把它改到当前契约。

## 3. 证据

### native 用例

S2 的 7 个 native 文件共 37 条，全部通过（`native_all.txt`）。新文件 `test_s2_plan_device_native.py` 有 18 条，覆盖：

- 推理在 CPU 上、训练在 GPU 上运行，用设备探针记录；
- CPU 与 GPU 推理结果一致，atol 和 rtol 都是 1e-4；
- 未知设备会报错；
- 同一进程内、跨进程（每个臂构造前随机打乱全局 key），同一种子得到相同权重，不同种子得到不同权重；
- 未调用 init 就 train_step 会报错。

### 坏对照

在隔离副本中运行（`mutations.txt`、`w10muts.py`），6 处变异全部变红，还原后 18 条通过：

| # | 变异 | 结果 |
|---|---|---|
| M1 | 忽略设备 | 3 条失败 |
| M2 | 训练也包进规划设备 | 2 条失败 |
| M3 | predict_l2 不包 | 2 条失败 |
| M4 | 未知设备回退到 gpu | 1 条失败 |
| M5 | 臂 B 的 init 不重建模型 | 2 条失败 |
| M6 | 臂 C 恢复静默种子 42 | 1 条失败 |

### 设备基准

未训练的三臂，各跑 3 个长目标回合，GPU/CPU 交替两轮。三臂的回合结果（success、steps_used）在两种设备上一致。

| 臂 | GPU 中位数（s） | CPU 中位数（s） |
|---|---|---|
| A | 4.47 / 4.50 | 1.86 / 1.85 |
| B | 4.21 / 4.01 | 2.12 / 2.13 |
| C | 1.80 / 1.77 | 1.02 / 1.02 |

### N_fwd 档位（CPU）

见 `bench_tiers.py`。dev 曲线的实际倍数是 A 3.18、B 3.19、C 3.28，`check_smoke_budget` 的公式按 1 + 2048/4096 + 8192/4096 = 3.5 计。所以公式在 CPU 上偏保守，不会低估 dev。

### 临时目录 smoke 预演

seed 修复后连跑两次（`smoke_rehearsal_out1.txt`、`smoke_rehearsal_out2.txt`），output_root 都在临时目录：

| 项 | 第 1 次 | 第 2 次 |
|---|---|---|
| 总耗时（s） | 214.3 | 213.8 |
| reasons | 空 | 空 |
| 第 3 步 | 三臂通过，数值两次逐位相同 | 同左 |
| 第 4 步 oracle 成功率 | 1.0 | 1.0 |
| 规划中位数 A / B / C（s） | 1.99 / 2.26 / 1.07 | 1.99 / 2.37 / 1.07 |
| 预算推算（s） | 35,001 | 35,553 |

预算推算低于 54,000 s，余量约 35%。

### 其他

- 默认全量（SIG_DFL+execv，不跳过任何文件）：3725 passed，7 deselected，0 failed，用时 1088 s；实盘 artifacts 的 lstat 前后差异为 0（`pytest_full_tail.txt`）。
- `git_diff.patch`、`sha256.txt` 与盘上一致。

## 4. 不在本卡范围

- 未跑生产 `s2-phase1`，未写 artifacts/。
- 冻结的 r1 prereg 未动；r1 本来就要被 r2 替换，代码身份届时一并更新。
- W9 复核时记录的 smoke 规划耗时都是 GPU 规划，现以本报告为准。
