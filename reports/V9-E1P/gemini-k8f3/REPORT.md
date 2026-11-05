# E1-P 有偏物理先验积分器与中心差分 Jacobian 实现与测试报告（ainerzero.V9.P67）

- **执行者**：gemini-k8f3（二级执行 agent，纯 CPU / NumPy）
- **任务 ID**：`ainerzero.V9.P67`
- **对应阶段**：AinerZero V9 落地 · 轨道 P S1–S2 实验 · E1-P 先验积分器卡
- **依据协议**：`reports/V9-P48/E1_IMPLEMENTATION_PLAN.md`（架构裁定第 1–3 条）
- **改动范围**：
  - 积分器模块：`src/ainerzero/v9/experiments/e1/prior.py`
  - Jacobian 模块：`src/ainerzero/v9/experiments/e1/jacobian.py`
  - 包入口：`src/ainerzero/v9/experiments/e1/__init__.py`
  - 单元与解析测试：`tests/test_e1_prior.py`
  - 交付与校验产物：`reports/V9-E1P/gemini-k8f3/`

---

## 1. 物理先验积分器设计（prior.py）

按 `E1_IMPLEMENTATION_PLAN.md` 架构裁定第 1–3 条：
1. **纯 NumPy / CPU 实现**：完全脱离重型引擎（Blender / Genesis），半隐式欧拉算法（semi-implicit Euler），确定性可微。
2. **时钟对齐**：600 Hz 物理子步（`dt = 1/600 s`），每 60 fps 帧执行 10 个子步，与 E0 输出及物理参数严格同频。
3. **坐标系与重力**：右手系、Z 轴向上，重力加速度取 `(0, 0, -9.81)` m/s$^2$。
4. **结构性有偏先验（F_prior）**：
   - 登记的结构偏差：所有盒体与盒体、盒体与静态障碍物之间的接触均使用外接包围球（bounding-sphere）近似；
   - 无转动摩擦，无空气阻力（仅受线性与角速度阻尼影响）；
   - 默认有偏先验参数 $\hat{\phi}_0$ 取参数空间中点：
     `friction = 0.50`, `restitution = 0.45`, `mass = 2.60`, `linear_damping = 0.125`, `angular_damping = 0.125`。
5. **接触与碰撞冲量**：
   - 静态环境（地面平面、倾斜 Ramp、水平桌面 TableTop）的冲量响应，含恢复系数 $e$ 与库仑摩擦极限 $\Delta v_t \le \mu (1+e)|v_n|$；
   - 活动物体之间的双体弹性/非弹性碰撞冲量与贯穿位置修正。

---

## 2. 中心差分 Jacobian 与正交基截断（jacobian.py）

1. **中心差分 $\partial F_{\text{prior}} / \partial \phi$**：
   - 对 5 项物理参数（friction, restitution, mass, linear_damping, angular_damping）逐一施加正、负扰动；
   - 默认相对扰动步长 `rel_step = 1e-3`；
   - 输出形状为 `(num_frames + 1, 6)` 的状态灵敏度导数矩阵 $\partial [x, y, z, v_x, v_y, v_z] / \partial \phi_j$。
2. **SVD 正交投影基截断**：
   - 对 Jacobian 矩阵执行奇异值分解（SVD）；
   - 相对截断阈值严格设为 $10^{-6} \cdot \sigma_{\max}$；
   - 截断后的正交左奇异向量矩阵 $U_{\text{basis}}$ 满足 $U^T U = I$，直接作为 ⑥ 臂（残差学习正交投影）的基底。

---

## 3. 单元测试与解析检验（tests/test_e1_prior.py）

通过 7 项严格的解析物理和数值导数测试：
1. `test_analytical_free_fall`: 真空自由落体 $z(t) = z_0 - \frac{1}{2} g t^2$，数值解与解析解在 20 帧内偏差 $< 0.005$ m，反向重力坏对照验证成功。
2. `test_analytical_frictionless_inclined_ramp`: 30° 斜面无摩擦滑块，加速度 $a = g \sin 30^\circ = 4.905$ m/s$^2$，末速度解析相对误差 $< 5\%$。
3. `test_ground_bounce_restitution`: 恢复系数 $e=0.75$ 的地面反弹速度反转比例 $v_{\text{out}} \approx e |v_{\text{in}}|$，零恢复系数 $e=0.0$ 坏对照验证成功。
4. `test_flat_ground_coulomb_friction`: 平面滑动库仑摩擦减速 $a = -\mu g$，速度线性递减至停止。
5. `test_head_on_body_collision_momentum_conservation`: 自由空间中双球对心弹性碰撞动量严格守恒（相对误差 $< 10^{-4}$）。
6. `test_central_difference_jacobian`: 中心差分灵敏度验证，线性阻尼系数增大导致末速度单调下降（$\partial v_x / \partial d_{\text{lin}} < 0$）。
7. `test_svd_orthogonal_projection_basis`: SVD 正交投影基的正交性检验（$U^T U = I$，误差 $< 10^{-6}$）。

### 测试结果
```text
tests/test_e1_prior.py .......                                           [100%]
7 passed in 0.09s
```

结合指标模块，E1 完整测试集（23 项测试）在 0.23 秒内 100% 通过。
