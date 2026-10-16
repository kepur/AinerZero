# S0 GeometryCore 数学实现

纯 NumPy/float64；无模型、优化参数、训练、RunStore 或下载。公开入口在 `__init__.py`。

## 坐标、主值与群作用

`T=[R,t;0,1]` 将 body 点变到 world：`p_world=R p_body+t`。切向量按平移在前排列：SE2 为 `[rho_x,rho_y,theta]`，SE3 为 `[rho_x,rho_y,rho_z,phi_x,phi_y,phi_z]`。

- `SE2/SE3.compose(a,b)` 为 `a @ b`，`inverse` 为群逆。
- `exp` 使用 Rodrigues / SE Jacobian，小角度展开；`log` 用主值旋转，求解平移 Jacobian。
- SO2 主值 `(-pi,pi]`；SO3 旋转向量范数 `[0,pi]`。恰在 pi，轴符号不唯一，本实现选绝对值最大分量为正。该分支不连续是拓扑限制，不能要求任意切向量满足 `log(exp(xi))=xi`；测试的是 `exp(log(T))=T`。
- `act(T, points)` 是已知点坐标的群作用；`vectors=True` 不加平移。没有实现 G3 的规范化 operator；没有 RGB warp 或任意视角精确等变声明。
- 重力框架要求显式 `gravity`、`up` 与水平参考方向。gravity 必须与 up 反向；basis 为 `[horizontal_x, up cross horizontal_x, up]`。`GravityFrame.lift/project` 在 SE2×高度与保持 up 的SE3子群间往返，拒绝 roll/pitch。AWZ 的 Y-up 经此显式映射，不能默认为 Z-up。

SE2 的 Adjoint 是 `[[R,-Jt],[0,1]]`，`J=[[0,-1],[1,0]]`；SE3 为 `[[R,[t]x R],[0,R]]`。它们满足 `T Exp(xi) T^-1=Exp(Ad(T)xi)`。群作用只对显式坐标、对象向量等有意义，原始 RGB 若无深度/平面等前提不能由位姿推出精确 warp。估计误差也不是浮点误差、离散化误差、模型失配或采样误差的唯一来源。

## 左右误差、局部不变滤波与条件化参考

右误差：`X=mu Exp(xi_r)`；左误差：`X=Exp(xi_l) mu`。`boxplus/boxminus` 必须给出匹配的 side（默认 right）。同均值下，`xi_l=Ad(mu)xi_r`，故一阶协方差 `P_l=Ad(mu)P_r Ad(mu)^T`。

`TangentGaussian.predict` 的已知运动是 body twist：`U=Exp(u dt)`、`mu'=mu U`。右误差 `F=Ad(U^-1)`，左误差 `F=I`。输入过程协方差率定义在预测结果的右切空间，乘 dt 后加入；左形式再按新均值 Adjoint 转换。dt=0 为恒等；负数/非有限数拒绝。输入信念协方差严格正定，过程协方差允许半正定；不通过静默加 jitter 修复坏输入。

`update_tangent` 接收明确 side 的局部观测残差、H、R，先做 Joseph 更新，再用 dexp 的左右 Jacobian 重置均值处的协方差。`update_position` 提供显式 world 位置传感模型；这不代表学生获准读取绝对真值，也不是视觉位姿估计器。一般SE2/SE3上的高斯矩与重置是一阶局部近似，**不承诺任意噪声/任意轨迹的确定性误差上界**。非线性位姿图也不承诺全局收敛。

`KnownRotationGaussian` 是另外一个**固定已知旋转条件下**的平移高斯参考。它只有 n维随机平移，不给旋转加一个“很小但非零”的方差，因此确实落在可交换的平移子空间。已知运动与观测：

```text
x_k = x_(k-1) + d_k
xhat_minus = xhat_previous + d_k + e_odom
z_k = x_k + e_obs
xhat_plus = xhat_minus + K (z_k - xhat_minus)
```

若 `||e_odom||<=b_u`、`||e_obs||<=b_z`、之前误差界为B，则

```text
B_minus = B + b_u
B_plus = ||I-K||_2 B_minus + ||K||_2 b_z
```

由三角不等式直接得到，与真实噪声是否服从高斯无关。只有实际误差满足有界前提时才是逐路径保证。无界高斯噪声不能给出相同确定性全路径界。完整SE2-EKF的非零旋转协方差破坏该条件，本任务保留了一次错误套用平移界的真实失败（报告目录），没有用条件化参考成功覆盖它。

## 位姿图、gauge 与解析界

`RelativeFactor(i,j,Z,information)` 的 `Z=X_i^-1 X_j`。残差 `Log(Z^-1 X_i^-1 X_j)`；小规模密集Gauss-Newton、中心数值差分、有限回溯。information允许半正定以表达部分约束，但锚定后的数值Jacobian必须满列秩，否则抛 `ObservabilityError`，不以任意真值坐标填补。

调用方必须给 `anchor`，固定为其提供的初始位姿。这只选定全局平移/旋转gauge，不构成绝对坐标观测。缺锚、断图、剩余自由度未观测都报告不可观。返回 rank、自由维数、奇异值、残差与converged。converged仅表示局部步长达到容差，不能当成约束正确；错误回环可形成非零最优残差，不能普遍自动识别其来源。

`fixed_rotations=True` 固定所有输入旋转，只优化平移。解析参考进一步限定所有旋转为恒等、已知相对平移，加锚后 reduced incidence 为满列秩A。若相对平移误差为e，最小二乘解误差满足

```text
xhat-xtrue = (sqrt(W) A)^+ sqrt(W) e
||xhat-xtrue||_2 <= ||(sqrt(W) A)^+||_2 ||sqrt(W)e||_2
```

`linear_translation_error_bound` 仅实现此条件下的谱范数界；不将它用于任意非线性SE3图。已登记参考为单位权重、里程计固定有界偏置、闭环相对位移精确；均属于诊断设定，不是从真实传感中免费得到的世界信息。

## 当前证据范围

固定CPU登记在 `reports/V9-G1/r1-codex-20261016/cpu_registration.json`。1e-9往返只在登记的有界坐标、主值旋转与float64测试域内断言；有限差分Jacobian容差2e-6。测试包含近pi、小角、左右误差、协方差、dt、重力及图的gauge/秩问题。来自现有GridLab2D和AWZ Trajectory2D的小房间路径只作已知运动学解析参考，没有渲染、感知、神经学习、三维理解或S1能力验收。

理论背景：[Solà 等 micro Lie theory，v9](https://arxiv.org/abs/1812.01537)、[Barrau 与 Bonnabel IEKF，v4](https://arxiv.org/abs/1410.1465)。后者的稳定性结论有系统类别和线性情形标准条件；这里不将其当成任意观测模型均稳定的证明。代码为本任务独立实现，未下载第三方代码。
