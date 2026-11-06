# S2 数学核心（NumPy 参考实现）验收报告（ainerzero.V9.P111）

声明：依据 LeJEPA 论文（arXiv 2511.08544）及 ARCHITECTURE_V9 自主实现，**未打开或未参考其源码**（CC BY-NC 4.0）；纯 CPU 实现，未导入 MLX，无训练。

## 1. 公式与论文式号对照
| 模块 | 对应公式/节号 | 数学定义与约定 |
|---|---|---|
| SIGReg | arXiv 2511.08544 §3.2 | $S^{D-1}$ 随机单位投影 + Epps-Pulley 经验特征函数与标准正态 $\phi_0(t)$ 比较；17 节点梯形积分 |
| 逆动力学损失 | ARCHITECTURE_V9 §4 式 4 | 连续高斯固定方差 NLL + 类别直方图软目标交叉熵；目标作停止梯度 sg(a) 常量 |
| 宏动作聚合 $A_2$ | ARCHITECTURE_V9 §4 式 3 | $p = \sum_i R(\psi_i - \psi_t) d_i$，SE(2) 复合；$d\psi \in (-\pi, \pi]$ 归一；不整除默认报错 fail-closed |
| 多步滚动损失 | DESIGN-r0 §3 式 4 | 自回归链式展开 $z_h = f(z_{h-1}, a_{h-1}, dt_{h-1})$，逐项记录与真值误差 |

## 2. 测试与变异
- **测试清单**（14 项全绿，耗时 1.90s）：
  - SIGReg：各向同性样本值 (0.0017) 远低于 3 种退化 (常数 0.204/秩 1 0.094/各向异性 0.153，阈值 0.00525 由样本量推导)；正交旋转不变性；NaN/Inf 抛错。
  - 宏动作聚合：直线前进、原地旋转、正方形闭环 ($p\approx 0, d\psi\approx 0$)、先转 90° 再走、不规则 dt、不整除报错与 `drop_tail`。
  - 损失与滚动：连续 NLL 闭式解、软 CE、复合 IDM；3 步自回归滚动逐步误差吻合；纯 CPU 子进程 `-I` 隔离断言 `mlx` 零导入。
- **变异检验表**（`reports/V9-S2-K1/run_mutations.py` 隔离副本，全部变红并按字节还原）：
  - K1-M1（位移直接相加）：`test_aggregate_macro_square_loop_back_to_origin` 变红（exit 1，SHA 还原校验通过）
  - K1-M2（SIGReg 换均匀分布 CF）：`test_sigreg_isotropic_vs_degenerates...` 变红（exit 1，SHA 还原校验通过）
  - K1-M3（去掉 $d\psi$ 归一）：`test_aggregate_macro_square_loop_back_to_origin` 变红（exit 1，SHA 还原校验通过）
  - K1-M4（`__init__` 加 MLX 导入）：`test_s2_package_pure_cpu_no_mlx_imported` 变红（exit 1，SHA 还原校验通过）

## 3. 测试计数与产物 SHA256
- 全量收集计数：**前 3455 项（6 deselected） $\to$ 后 3469 项（6 deselected，净增 14 项）**。
- `src/ainerzero/v9/experiments/s2/__init__.py`: `d083f457255e140af89dc81afe06bc16a3663955f64b8e830bcb750d019d105d`
- `src/ainerzero/v9/experiments/s2/core_math.py`: `3d0311e7edbc7f421bea662ab30e023f25a8c6eac7aa0756bcf6cd7f1ed7f972`
- `tests/v9/experiments/test_s2_core_math.py`: `45381c98dd9bdda40379611ee6529ed8d4373c081e6c4d160b06365b936f3efb`
- `tests/v9/experiments/test_s2_package_pure_cpu.py`: `75bcdd36913e1db4b84206359f8b22f082d0185a0c769454e3ae29f6f0da8398`
- `reports/V9-S2-K1/run_mutations.py`: `86cfbe93e7e07a0e780029512a3a878fb494ddfbff9ba7370c81db1e3a9905bc`
