# ainerzero.V9.G1 S0 数学核心交付 r1

执行者：`codex-exec-r2-20261016`（真实 Codex 子代理，沿用R2的同一Relay身份）；日期2026-10-16（+03）。只在 G1 三个授权目录写入；报告后不accept、不next，交独立 G2 复核。此交付没有修改旧模型、RunStore、架构、科学参数或任何既有门槛。

## 结果与边界

- 实现成立（作者CPU证据）：SE2/SE3 compose/inverse/exp/log/adjoint、已知点/向量群作用、左右切空间高斯及Adjoint协方差转换、body运动预测、局部不变误差EKF观测更新与Jacobian重置、重力对齐SE2×高度、锚定的小规模SE2/SE3 Gauss-Newton图。
- 49项CPU性质测试通过，12种故意改坏均由真实子进程 AssertionError / exit1 捕获。不是独立验收；G2另做非作者复核。
- 已登记线性/有界前提下，两条24步参考的条件化平移滤波和锚定平移图达解析界。**一般非线性EKF的全路径确定性界未验证，也没有承诺。** 两条轨迹服从相同平移误差代数，不能把它们当成跨世界泛化实验。
- 真实失败保留：完整SE2-EKF有非零yaw方差，不能套用固定已知朝向的平移界。step9误差0.013251042569235738 > 界0.013068675096975537，更新后yaw=-0.0032242350176040708。`reference-first-failure.log`、`run_reference-failed-r1.py`及原登记全部保留；其失败输入可由不变登记的seed/固定动作/偏置与冻结GridLab源码逐字重建。成功分支使用显式 `KnownRotationGaussian`（只有随机平移，旋转不随机），**未改界、偏置、种子或fixture**，未将成功冒充完整EKF解析验收。

## 实现前固定身份

`cpu_registration.json` 在任何数学库实现前写入，SHA256=`5aa8199fbc6bbf525b678860d155526053002a78cb975e608d96f53cda5334c6`。登记性质seed20261016、128组、往返1e-9、小角/近pi边界、Jacobian有限差分容差2e-6；GridLab seed16固定动作24步；AWZ四边形小房间25个等弧长点；所有界和偏置先固定。该登记只是CPU验证条件，**不构成S1科学门或训练授权**。

四个原始输入：当前ARCHITECTURE_V9 r3、研究调研、GridLab2D实现、AWZ motion实现。登记内列SHA，参考脚本消费前重算全部匹配；交付时再次核对匹配。源码/测试/脚本最终身份见 `source-sha256.json` 与总 `SHA256SUMS.txt`。

## 每项性质的实际适用范围

| 性质 | 实现/验证 | 前提或限制 |
|---|---|---|
| 群公理/逆元/结合律 | 128组×2群；独立矩阵指数级数对照 | float64、有界登记输入，不承诺任意尺度浮点1e-9 |
| exp(log(T)) | 小角0/1e-12/1e-8/1e-4；pi及pi附近多轴 | SO2主值(-pi,pi]；SO3角范数[0,pi]；pi轴符号分支不唯一；不要求全局log(exp(xi))=xi |
| 群作用/Adjoint | 点/向量作用组合；共轭恒等；左右boxplus一致 | 明确有群作用的坐标，不含RGB warp；G3规范化operator未实现 |
| 左右切空间高斯 | xi_left=Ad(mu)xi_right，P相应变换；左右预测对照 | 高斯协方差是一阶矩；噪声输入声明为预测后右切空间率 |
| 预测/局部观测更新 | body twist+显式dt；Joseph更新；dexp reset与独立有限差分对照 | 局部IEKF形式，不是所有非线性模型的稳定性证明；位置传感需契约允许 |
| 协方差 | 信念/观测严格SPD，过程允许PSD；对称/特征值检查 | 非SPD、非对称、NaN不静默修补；精确已知旋转另用条件类 |
| dt | 0、1e-12、1/120、10及1e12×极小速度 | 负数/NaN/Inf拒绝；不声称浮点可容纳无限尺度乘积 |
| 重力状态 | Z-up、Y-up、斜up，lift/project往返与子群组合 | gravity与up反向，水平参考不共线；拒绝roll/pitch；非完整SO3不变 |
| 位姿图 | SE2/SE3闭环局部求解，rank/自由度/奇异值输出 | 强制显式anchor选择gauge；断图/缺锚/部分未观测抛不可观；不填真值 |
| 错误回环 | 不一致约束产生非零残差 | converged不等于约束正确；不承诺自动知道哪条测量错 |

详细公式、API及限制在 `src/ainerzero/v9/geometry/README.md`。特别纠正式9的泛化说法：只有输入和估计都按同一已知群作用变化时才能讨论规范化等变；估计误差不是浮点/离散化/传感/模型失配的唯一来源，本任务没有提前实现G3。

## 解析界推导与实测

条件平移滤波：固定已知旋转、加性真实位移d；里程计误差范数<=b_u、观测误差<=b_z；`e_minus=e_prev+e_odom`、`e_plus=(I-K)e_minus+K e_obs`。三角不等式给 `B_minus=B_prev+b_u`、`B_plus=||I-K||2 B_minus+||K||2 b_z`。登记偏置为固定有界数，协方差是滤波权重，不声称无界高斯噪声每条样本也满足同界。每一步实际误差都与该步界断言，另加1e-9浮点slack。

固定旋转平移图：anchor0移除，reduced incidence A满列秩；单位权重、已登记每边误差e。`delta_x=A^+e`，故 `||delta_x||2<=||A^+||2||e||2`。理论界只用已登记输入与A计算，不读取求解输出调界；GN解还与独立线性lstsq结果逐坐标比较<=1e-9。

| 参考 | 滤波最大实际误差 | 该组最大解析界 | 图纠错前L2 | 图纠错后L2 | 图解析界L2 |
|---|---:|---:|---:|---:|---:|
| GridLab2D | 0.009611299116605 | 0.009624564302927 | 0.252388589282479 | 0.010095543571584 | 0.140654368406759 |
| AWZ解析小房间 | 0.009611299116605 | 0.009624564302927 | 0.252388589282480 | 0.010095543572310 | 0.140654368406759 |

每条图rank=48/48，2次迭代；噪声后最优残差约0.01730665，并非把不一致约束抹成零。两路滤波每一步分别满足其该步界，表中仅汇总最大值。无噪声已知运动学主均值另有1e-9门，全部满足。

来源边界：GridLab来自现有 `GridWorld.apply`，单位是格，不当米；AWZ来自现有 `Trajectory2D.eval_pos_and_tangent`，小房间四边形边长2m，Y-up显式映射，单位米。AWZ参考**未启动WorldKernel/Blender/Godot、未渲染房间、未测真实视觉传感**。这里的已知位移与允许位置观测是解析诊断，不是给未来学生开放隐藏真值。原始点、每步界、source SHA与图结果在 `reference-results-r1.json`（成功分支的文件名；r1原失败另存）。

## 实际命令、失败与证据

cwd=`/Users/mac/AinerWorkFlow/AinerZero`，使用既有`.venv-ainerzero`（NumPy2.5.3 / pytest9.1.1），未安装依赖。

```text
python3 /Users/mac/AinerWorkFlow/AinerRelay/bin/relay claim ainerzero.V9.G1 --agent codex-exec-r2-20261016
PYTHONDONTWRITEBYTECODE=1 .venv-ainerzero/bin/python -m pytest tests/v9/geometry -q -p no:cacheprovider --junitxml=reports/V9-G1/r1-codex-20261016/cpu-tests-r1.xml
PYTHONDONTWRITEBYTECODE=1 .venv-ainerzero/bin/python -B reports/V9-G1/r1-codex-20261016/run_reference.py
PYTHONDONTWRITEBYTECODE=1 .venv-ainerzero/bin/python -B reports/V9-G1/r1-codex-20261016/run_reference.py > reports/V9-G1/r1-codex-20261016/reference-first-failure.log 2>&1
PYTHONDONTWRITEBYTECODE=1 .venv-ainerzero/bin/python -B reports/V9-G1/r1-codex-20261016/run_reference.py > reports/V9-G1/r1-codex-20261016/reference-success-r2.log 2>&1
PYTHONDONTWRITEBYTECODE=1 .venv-ainerzero/bin/python -m pytest tests/v9/geometry -q -p no:cacheprovider --junitxml=reports/V9-G1/r1-codex-20261016/cpu-tests-r2.xml
PYTHONDONTWRITEBYTECODE=1 .venv-ainerzero/bin/python -B reports/V9-G1/r1-codex-20261016/run_mutations.py
.venv-ainerzero/bin/ruff check --no-cache src/ainerzero/v9/geometry tests/v9/geometry
```

首次性质46过，加入条件参考与子群组合性质后49过。完整EKF套界第一次失败后仅加诊断信息重复CPU复现，exit1日志如上；随后修正前提匹配实现成功exit0。Ruff首次有一个未用测试import（F401），删去后通过，不涉及公式/参数。所有原XML/失败保留。

`run_mutations.py` 对SE2/SE3五种运算逐个内存改坏（10个），另故意移除重力方向与无锚可观性拒绝（2个），12个子进程均真实exit1且日志含性质AssertionError；不是手写失败状态。argv与退出码在 `mutation-results-r1.json`。两个报告脚本均安装导入拦截器拒绝MLX/ORT/Torch/TF，pytest最后检查这些模块未导入。

模型预算预留=0，模型工作=0，训练=0，优化更新=0。临时变异在隔离子进程内存中，不改持久源码，不创建生产库；报告目录就是证据目录，没有外部临时数据目录。没有下载/安装/付费/删除/提交/推送。源码候选与作者测试通过不代表已通过G2或S1。

理论背景的官方摘要已在本轮只读打开：[micro Lie theory v9](https://arxiv.org/abs/1812.01537)、[IEKF stable observer v4](https://arxiv.org/abs/1410.1465)。这里只借数学定义和有条件稳定性的边界，不宣称复现其全部定理或代码；实现公式由矩阵级数/共轭/有限差分等具体性质核对。
