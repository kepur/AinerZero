自证：本复核由 `composer-m8k4` 执行；被验卡 ainerzero.V9.P128 作者为 `gemini-h8c2`，本会话未实现或改写过 P128，不存在自审冲突。全程未运行任何 MLX。

# ainerzero.V9.P129 非作者复核报告（验 P128）

角色：executor（L2 verify）；负责人：composer-m8k4；时间：2026-11-06
任务状态：reported；实验状态：未执行（纯 CPU 静态复核，无 MLX）
任务依据：ainerzero.V9.P129 v0；`no_mlx`；只改 `reports/V9-S2-P128/review/`
结论：**RECOMMEND_ACCEPT_SCOPED**

## 范围

- 卡面新文件：`s2/arms_mlx.py`、`test_s2_arms_static.py`、`test_s2_arms_mlx_native.py`、`reports/V9-S2-P128/` 均为未跟踪新增；与卡面一致。
- `tests/conftest.py`：作者交付的 `conftest.patch` **仅**向 `NATIVE_MODULES` 追加 1 条登记（外加 1 行注释）。工作树另有他卡 hermetic 大 diff，**不计入 P128**。
- 已跟踪 `src/` 除他卡脏的 `cli.py` 外与 HEAD 逐字节一致；未改 e1 / runtime。

## 结构静态对照（附录 A × `ARM_DIMS` × `arms_mlx.py`）

| 组件 | 附录 A / spec | 代码（行号） | 一致？ |
|---|---|---|---|
| E₁ | 205→256→128，GELU | `SharedE1Encoder` L86–98：`Linear(e1_in,e1_h)`→GELU→`Linear(e1_h,e1_out)`，宽自 cfg | **是** |
| 臂 A GRU | 入 [z32,a4,dt1]=37；h 收窄 | `GRUCell(gru_in,gru_h)` L128；`gru_hidden=160` | **是**（相对初稿收窄，登记值） |
| 先验/后验 | p(z\|h)、q(z\|h,E₁)；z=32 | L130–136；GELU；出 `2*z_dim` | **是** |
| 解码器 | [h,z]→205 | L138–140, `decode` L160–163 | **是**（地形 soft-CE / 其余 MSE 在损失侧） |
| 臂 B P₁ | 初稿 256→256→128；登记加宽 | L223–226：`p1_hidden_*=320` 自 `ARM_DIMS` | **是**（附录允许只改隐藏宽） |
| 臂 B IDM | [z,z']→128→4 | L228–230, L245–249 | **是** |
| 臂 C L1 | 同 B、宽 256 | L278–292 | **是** |
| E₂ / P₂ / IDM₂ | 128→128→64；P₂ 入 72；IDM₂→7 | L305–312, L319–346 | **是** |

**手算臂 A 参数量（`param_count` 公式，对照代码层结构）**：E1 85632 + GRU 95200 + prior 28864 + post 45248 + dec 51149 = **306093** = `count_arm_a_closed_form()` = 作者登记；B=305732、C=303115，均在 300k±10%。

## 损失式子对照（MLX ↔ P111 `core_math`）

| 项 | core_math | arms_mlx | 判定 |
|---|---|---|---|
| SIGReg | L79–178：17 结点 [0.2,4]，梯形×高斯权，Epps-Pulley | `sigreg_mlx` L389–426：同结点/权/聚合；方向由调用方传入 | **同式** |
| 连续高斯 NLL | L186–221：`0.5*(sq/var+log(2πvar))`，目标作 sg 约定 | L429–437：同公式 | **同式**；MLX 未显式 `stop_gradient` |
| 软交叉熵 | L224+：`−∑ t log p`，logits | L440–447：`log_softmax` 后加权 | **同式** |
| IDM₂ 复合 | `inverse_dynamics_loss` 连续3+类别4 | `idm2_loss_mlx` L450–459 | **同式**；sg(宏动作) 依赖调用方 |
| 多步滚动 | `multistep_rollout_loss` 逐步 MSE | `multistep_latent_rollout_loss_mlx` L462–483 | **同构** |
| KL free bits | 附录 A = 1.0 nat | `arm_a_loss_mlx` L539–541：`maximum(mean_kl, ARM_A_FREE_BITS)` | **有地板** |
| 臂 A 规划代价 | 解码观察对目标交叉熵 | `planning_cost` L189–202：地形 soft-CE + 其余 MSE | **合理落地** |
| 臂 B 规划代价 | ‖ẑ_T−E₁(o_goal)‖² | **无** `planning_cost` 方法 | **缺口**（scoped） |
| 臂 A overshooting | 先验 H 步想象逐步重建 | `arm_a_loss_mlx` 仅逐步后验/先验+一步重建 | **未接线**（scoped） |

原生容差 `1e-5`（float32）对 NLL/CE/固定方向 SIGReg **合理**；`test_native_sigreg_mlx_matches_numpy` 内计算了 `core_math.sigreg(...)` 但未参与断言（死代码），真正比对的是同方向手算参考——不影响默认套件。

## 测试真伪

- 静态测试：AST 扫 `arms_mlx.py`、读 `__init__`/`conftest`、子进程 `-I` 导入 s2；**调用真实路径**，非常数比常数。
- 原生测试（未跑）：调用 `arms_mlx.*` / `param_count.*` / `core_math.*`；一步 Adam 断言损失下降——真伪可接受，留待 smoke。

## 自做变异（作者 M1–M3 以外；隔离副本；还原 SHA）

| ID | 变异 | 结果 |
|---|---|---|
| R129-X1 | `GRUCell(37,160)` 字面宽（非 M1 的 Linear） | **KILLED** |
| R129-X2 | E₁ GELU→ReLU | **存活** → 静态套件**未覆盖激活**（测试漏洞） |
| R129-X3 | 去掉 KL free-bits 地板 | **存活** → 静态套件**未覆盖 free bits**（测试漏洞） |

## 纯 CPU / 未跑 MLX

- `-I` 导入 `ainerzero.v9.experiments.s2` 后 `mlx` ∉ `sys.modules`。
- 未加 `--native-mlx`；SIG_DFL+`execv` 全量：**3542 passed, 6 deselected in 270.95s**，0 failed。
- 作者报告写「487 passed」与本机默认全量不符——以本复核计数为准；不因此否定结构交付，但记入 scoped。

## RECOMMEND_ACCEPT_SCOPED（范围）

接受 P128 作为：**三臂结构按 `ARM_DIMS`/附录 A（含登记加宽）、MLX 损失与 P111 主公式对齐、原生测试已登记未执行、静态隔离与作者三变异、conftest 仅追加 NATIVE 一行** 的交付。

不接受写成已完成：臂 A latent overshooting、臂 B 规划代价 ‖·‖²、训练图内显式 `stop_gradient(宏动作)`、静态套件对 GELU/free-bits 的防护、以及作者「487」全量计数。

修改文件：仅 `reports/V9-S2-P128/review/`。
交回统筹：可按 scoped 接受；smoke/训练接线前补 overshooting、B 规划代价与 stopgrad，并考虑静态断言激活/free-bits。
