# 非作者复核报告：S2 数学核心（ainerzero.V9.P111）

自证：复核者为 `gemini-m7k4`，与被验任务 ainerzero.V9.P111 作者 `gemini-8m4d` 为不同会话的独立 Agent，未参与 P111 的设计、编写与提交；本次复核为纯 CPU 只读核对，未修改任何源码与测试。

---

## 一、文件范围与完整性核实

1. **工作树状态**：
   - `src/` 目录下除已登记的 `s2/` 之外的所有已追踪文件，与 `HEAD` 逐字节完全一致（`git diff HEAD src/` 输出为空）。
   - 被验卡 ainerzero.V9.P111 交付的 7 个核心文件 SHA256 校验与作者报告 **100% 吻合**：
     - `src/ainerzero/v9/experiments/s2/__init__.py`: `d083f457255e140af89dc81afe06bc16a3663955f64b8e830bcb750d019d105d`
     - `src/ainerzero/v9/experiments/s2/core_math.py`: `3d0311e7edbc7f421bea662ab30e023f25a8c6eac7aa0756bcf6cd7f1ed7f972`
     - `tests/v9/experiments/test_s2_core_math.py`: `45381c98dd9bdda40379611ee6529ed8d4373c081e6c4d160b06365b936f3efb`
     - `tests/v9/experiments/test_s2_package_pure_cpu.py`: `75bcdd36913e1db4b84206359f8b22f082d0185a0c769454e3ae29f6f0da8398`
     - `reports/V9-S2-K1/run_mutations.py`: `86cfbe93e7e07a0e780029512a3a878fb494ddfbff9ba7370c81db1e3a9905bc`
     - `reports/V9-S2-K1/REPORT.md`: `83019c82fda3c3d0bd12a6fc15d19df94ec912fcece34566e5e61edb03498db1`
     - `reports/V9-S2-K1/metrics.json`: `9453fb591dcb7ed0dea117e947a469360077d2407bc91a2288efcf8d6e42dd9b`

---

## 二、SIGReg 对照论文核对（arXiv 2511.08544 §3.2）

对照 LeJEPA 论文（arXiv 2511.08544 §3.2）及 Epps & Pulley (1983) 原始形式：

| 核对项 | 论文定义与式号 | 代码实现与行号 (`core_math.py`) | 结论 |
|---|---|---|---|
| **投影方向分布** | 基于 Cramér-Wold 定理，在超球面 $S^{D-1}$ 上均匀各向同性采样单位向量 $a \sim \text{Unif}(S^{D-1})$ (§3.2 式 1) | 行 139–146：通过标准多元正态采样 `raw_dirs` 后逐行除以欧氏范数 `norms`，按球面对称性严格服从 $S^{D-1}$ 均匀分布 | **一致** |
| **Epps–Pulley 统计量** | $T = \int_{\mathbb{R}} \|\phi_N(t) - \phi_0(t)\|^2 w(t) dt$，其中 $\phi_N(t) = \frac{1}{N}\sum_j e^{i t X_j}$，$\phi_0(t) = e^{-t^2/2}$ (§3.2 式 2) | 行 166–175：`diff_cos = mean_cos - phi_0`，`sq_diff = diff_cos**2 + mean_sin**2`，严格分离实虚部计算模长平方 | **一致** |
| **权重函数** | 高斯窗口 $w(t) = e^{-t^2/2}$（Epps & Pulley 1983, §3.2 式 2）保证全实数轴可积与数值收敛 | 行 160–162：`w_t = np.exp(-0.5 * (knots**2))`，并融合进积分权重 | **一致** |
| **积分节点与法则** | 离散频域区间截断与离散求积（§3.2 建议 17 节点） | 行 152–156：`np.linspace(t_min, t_max, n_knots)`（默认 `n_knots=17, t_min=0.2, t_max=4.0`），采用闭式复化梯形公式（端点权重减半） | **一致** |
| **归一化** | 投影单位范数 $\|a\|=1$；特征函数除以样本量 $N$；最终对 $M$ 个随机方向取期望平均 | 行 146（范数归一）、行 167–168（`np.mean` 沿样本维归一）、行 178（`np.mean` 沿方向维取期望） | **一致** |

**代码独立性与许可证合规**：
代码风格为纯粹严谨的 NumPy 向量化算子，变量命名（`Z_arr`, `raw_dirs`, `knots`, `trapz_weights`, `phi_0`, `w_t`, `t_X`, `sq_diff`, `t_stat`）直接对应数学公式推导，没有任何第三方专有结构或 CC BY-NC 4.0 仓库代码痕迹，未侵犯原作者版权。

---

## 三、宏动作聚合 SE(2) 数学手算独立核验（2 个作者未测案例）

### 案例 1：前进 — 左转 90° — 前进 — 右转 45° — 前进（5 步，等步长）
- **输入序列**：
  - 步 0：$(dx=1.0, dy=0.0, d\psi=0.0, \text{cat}=0), dt=1.0$
  - 步 1：$(dx=0.0, dy=0.0, d\psi=\pi/2, \text{cat}=1), dt=1.0$
  - 步 2：$(dx=1.0, dy=0.0, d\psi=0.0, \text{cat}=0), dt=1.0$
  - 步 3：$(dx=0.0, dy=0.0, d\psi=-\pi/4, \text{cat}=2), dt=1.0$
  - 步 4：$(dx=1.0, dy=0.0, d\psi=0.0, \text{cat}=0), dt=1.0$
- **手算推导**：
  - 步 0 后：$\psi_1=0$，$p_0 = (1.0, 0.0)$
  - 步 1 后：$\psi_2=\pi/2$，$p_1 = (0.0, 0.0)$
  - 步 2 后：$\psi_3=\pi/2$，$p_2 = R(\pi/2)(1.0, 0.0)^T = (0.0, 1.0)$
  - 步 3 后：$\psi_4=\pi/4$，$p_3 = (0.0, 0.0)$
  - 步 4 后：$\psi_5=\pi/4$，$p_4 = R(\pi/4)(1.0, 0.0)^T = (\frac{\sqrt{2}}{2}, \frac{\sqrt{2}}{2})$
  - **总位移闭式解**：
    $p_x = 1.0 + \frac{\sqrt{2}}{2} \approx 1.7071067811865475$
    $p_y = 1.0 + \frac{\sqrt{2}}{2} \approx 1.7071067811865475$
  - **总朝向与时长**：$d\psi = \pi/4 \approx 0.7853981633974483$，$dt_{\text{sum}} = 5.0$
  - **类别直方图**：3 次类别 0，1 次类别 1，1 次类别 2 $\to [0.6, 0.2, 0.2, 0.0]$
- **代码输出对比**：
  - `dx` 误差：$0.0$
  - `dy` 误差：$0.0$
  - `dpsi` 误差：$0.0$
  - `hist` 与 `dt_sum` 逐项完全吻合。

### 案例 2：不规则 dt 且同时存在平移与大幅转动（3 步）
- **输入序列**：
  - 步 0：$(dx=2.0, dy=1.0, d\psi=\pi/3, \text{cat}=1), dt=0.5$
  - 步 1：$(dx=-1.0, dy=3.0, d\psi=5\pi/6, \text{cat}=2), dt=1.75$
  - 步 2：$(dx=0.5, dy=-2.0, d\psi=-\pi/2, \text{cat}=0), dt=2.25$
- **手算推导**：
  - 步 0 后：$\psi_1=\pi/3$，$p_0 = (2.0, 1.0)$
  - 步 1 后：$\psi_2=7\pi/6$，$p_1 = R(\pi/3)(-1.0, 3.0)^T = \begin{pmatrix} 0.5 & -\frac{\sqrt{3}}{2} \\ \frac{\sqrt{3}}{2} & 0.5 \end{pmatrix} \begin{pmatrix} -1 \\ 3 \end{pmatrix} = \begin{pmatrix} -0.5 - 1.5\sqrt{3} \\ 1.5 - 0.5\sqrt{3} \end{pmatrix}$
  - 步 2 后：$\psi_3=2\pi/3$，$p_2 = R(7\pi/6)(0.5, -2.0)^T = \begin{pmatrix} -\frac{\sqrt{3}}{2} & 0.5 \\ -0.5 & -\frac{\sqrt{3}}{2} \end{pmatrix} \begin{pmatrix} 0.5 \\ -2.0 \end{pmatrix} = \begin{pmatrix} -0.25\sqrt{3} - 1.0 \\ -0.25 + \sqrt{3} \end{pmatrix}$
  - **总位移闭式解**：
    $p_x = 0.5 - 1.75\sqrt{3} \approx -2.531088913245535$
    $p_y = 2.25 + 0.5\sqrt{3} \approx 3.1160254037844384$
  - **总朝向与时长**：$d\psi = 2\pi/3 \approx 2.0943951023931953$，$dt_{\text{sum}} = 4.5$
  - **类别直方图**：类别 0、1、2 各 1 次 $\to [1/3, 1/3, 1/3, 0.0]$
- **代码输出对比**：
  - `dx` 误差：$4.44 \times 10^{-16}$（浮点机内精度级别）
  - `dy` 误差：$8.88 \times 10^{-16}$
  - `dpsi` 误差：$4.44 \times 10^{-16}$
  - 手算真值与代码输出吻合度达机器精度上限。

---

## 四、测试真实性与 SIGReg 阈值推导核查

1. **真实调用**：测试套件直接导入 `ainerzero.v9.experiments.s2.core_math` 中的实际函数，无测试内重写，无常数比常数。
2. **SIGReg 阈值推导**：
   - 阈值非经验硬编码常数，而是依据大数定律与正态经验特征函数方差理论解析推导：
     若 $Z \sim \mathcal{N}(0, I_D)$，则任意单位方向投影 $X = Z a \sim \mathcal{N}(0, 1)$。
     各节点处 $\mathbb{E}[|\phi_N(t) - \phi_0(t)|^2] = \frac{1 - e^{-t^2}}{N}$。
     加权积分理论期望为 $C_{\text{theory}} / N$。
     在 $N=300$ 时，$C_{\text{theory}} \approx 0.525$，期望值约为 $0.00175$。
     测试将判断阈值设为 $3 \times \mathbb{E}[\text{SIGReg}] \approx 0.00525$。
   - 实测各向同性正态样本为 $0.0017 < 0.00525$；退化分布（常数崩塌 $0.204$、秩一 $0.094$、各向异性 $0.153$）均超出阈值 $10$ 倍以上，统计边界坚实。

---

## 五、复核者独立变异实验（4 处作者表外变异）

所有变异均在隔离临时目录中执行（复制 `src`、`tests`、`pyproject.toml`，断言 import 解析到副本），测试前先验证原代码通过，变异后验证测试转红，并在测试后按字节还原校验 SHA256。

| 变异编号 | 变异部位与内容 | 目标测试 | 变异前状态 | 变异后退出码 | 拦截断言特征 | 还原 SHA 吻合 |
|---|---|---|---|---|---|---|
| **REV-M1** | Continuous Gaussian NLL 漏掉对数归一化项（仅保留误差平方除以方差） | `test_inverse_dynamics_loss_continuous_gaussian_nll` | PASS | 1 (变红) | `assert math.isclose(nll_min, expected_min, abs_tol=1e-12)` | 是 |
| **REV-M2** | 多步自回归滚动：状态不向前传递（`z_curr` 锁定为 `z0`，退化为开环单步） | `test_multistep_rollout_loss_autoregressive_chaining` | PASS | 1 (变红) | `assert math.isclose(res.total_loss, 0.0, abs_tol=1e-12)` | 是 |
| **REV-M3** | 软目标交叉熵：丢失负号（导致损失为非物理负值） | `test_inverse_dynamics_loss_soft_cross_entropy` | PASS | 1 (变红) | `assert math.isclose(loss, math.log(2.0), abs_tol=1e-4)` | 是 |
| **REV-M4** | SIGReg 随机投影方向不做单位范数归一化（投影方差扩大 $D$ 倍导致分布失配） | `test_sigreg_isotropic_vs_degenerates_sample_size_derived_threshold` | PASS | 1 (变红) | `assert val_iso < threshold` | 是 |

4 处变异全部在第一时间精准变红，无任何漏网存活，充分证明测试套件的高灵敏度。

---

## 六、纯 CPU 隔离与测试套件计数

1. **MLX 隔离核实**：
   - 子进程启动测试中，确认 `sys.modules` 中完全不含任何 `mlx` 或 `mlx.*` 模块。
2. **全量测试套件运行**：
   - 使用仓库标准虚拟环境 `.venv/bin/pytest` 运行 P111 交付的全部 14 项测试，**14 passed in 1.78s**，全部通过。
   - 全量收集计数：基线 3455 项（6 deselected） $\to$ P111 净增 14 项（13 项 `test_s2_core_math.py` + 1 项 `test_s2_package_pure_cpu.py`）至 3469 项。在包含其他当前未提交 WIP 模块时全量收集为 3476 项（6 deselected）。
3. **环境防御细节说明**：
   - `test_s2_package_pure_cpu.py` 使用了 `subprocess.run([sys.executable, "-I", "-c", code])`。
   - 当在非 virtualenv 的原生系统 Python（如 Homebrew Python，且 numpy 安装在 user site-packages）下运行时，参数 `-I` 会因禁用 user site-packages 导致子进程无法找到 numpy。
   - 在仓库标准的 `.venv` 虚拟环境中（库安装于虚拟环境自带 site-packages），该用例测试完美通过。建议后续测试用例参考 `test_s2_world.py`，加入 `site.addsitedir(site.getusersitepackages())`，以彻底防御不同解释器启动环境的差异。

---

## 七、复核结论

**`RECOMMEND_ACCEPT_SCOPED`（推荐按环境限定通过）**

- **通过范围**：P111 所实现的 S2 数学核心（SIGReg 正则、连续/类别逆动力学损失、SE(2) 宏动作空间聚合与多步自回归滚动损失）数学逻辑严密、公式对照精确、独立手算完全闭环、测试具有高度变异敏感性，且严守纯 CPU 与零模型导入纪律。
- **限定建议**：执行与后续评测统一在 `.venv` 环境下运行，以确保子进程 `-I` 隔离测试的稳健执行。
