# ainerzero.V9.G2 独立复核报告：S0 NeuroGeometry 数学核心

角色：executor（二级执行层）· 负责人：`deepseek-8seu` · 时间：2026-10-16（+03）
任务状态：reported · 实验状态：completed（**纯 CPU、只读复核**）· 类型：verify
任务依据：`ainerzero.V9.G2`（复核 `ainerzero.V9.G1`，作者 `codex-exec-r2-20261016`；本报告作者非 G1 作者）；参数 v0（`{}`，照用不改）；文件范围 `reports/V-V9-G1/`。
被验交付：`src/ainerzero/v9/geometry/`（lie/belief/gravity/pose_graph/`__init__`/README）、`tests/v9/geometry/test_geometry.py`、`reports/V9-G1/r1-codex-20261016/`
输入身份：见 §9（`SHA256SUMS.txt` 35/35 一致；`source-sha256.json` 全一致；登记 SHA=`5aa8199f…34c6`；两个文档输入 stale，见 F3）
修改文件：仅新增 `reports/V-V9-G1/`（复核脚本、证据、本报告、指标）；**未改被验源码/测试/报告**。副作用披露：13:12 一次不带 `-B` 的探针在 `src/ainerzero/v9/geometry/`、`tests/v9/geometry/` 生成 `__pycache__/`（`.gitignore` 已忽略，源码字节未变，SHA 已复核）。
结论：**建议有条件验收**（数学核心与报告数字成立，未发现会产生错误数值的缺陷；4 项发现按 §5 登记，其中 F1/F2 建议 G1 小修，F3 需一级决定）。不 accept 自己。

---

## 0. 摘要（30 行内）

1. 复核对象是 G1 的数学核心 + 它的两条解析参考与报告数字。复核手段：自写不利反例（9 例，每例带"故意改坏必须变红"对照）、独立矩阵指数、数值微分 Jacobian、独立最小二乘/谱范数、蒙特卡洛一阶矩、以及**用登记参数重算整条解析界序列**。
2. 证据身份先冻结：`SHA256SUMS.txt` 35 条逐字节一致、`source-sha256.json` 全一致、登记文件 SHA 与报告一致；受跟踪文件没有在 G1 窗口内被改动，G1 只新增自己的三个授权目录。
3. G1 报告可复现：独立重跑 pytest `49 passed`；`mutation-results-r1.json` 12/12 真实 `exit 1`；首次失败日志是真实断言失败。
4. 参考脚本重放：**原始脚本在当前树上已被自己的消费门挡住**（`AssertionError: registered source changed: ARCHITECTURE_V9.md`）；把两个**文档**输入的 stale 哈希豁免、代码输入仍强制核对后重放成功，输出 JSON 与 G1 报告 **0 字段差异**（F3）。
5. 解析界逐项核对：整条 24 步界序列可由登记参数独立重算，**最大差 0.0（逐位相同）**；图界复算 `0.14065436840675918` 与报告逐位相同，只依赖登记的边误差与 reduced incidence。
6. 界推导成立且**锐度可信**：自写轨迹 max(误差/界)=0.98965；对抗搜索可达界的 0.99914；图界沿 `A⁺` 主左奇异方向取误差时**等号精确成立**（比值 1.0000000000000000±4e-16）。
7. 界是条件界：把真实里程误差放大到登记界的 5 倍后，24 步中 23 步越界——与 G1 "只在有界前提下成立"的声明一致，不是普遍界。
8. 群运算与主值：2160 组 `exp(log(T))`（含 SO(3) 恰好 π、π−1e-14…π−1e-4、SO(2) `r[1,0]=-0.0`）最大误差 1.88e-13 ≤ 1e-9；恰好 π 的"绝对值最大分量为正"轴约定 0/200 违反。
9. 独立矩阵指数（Taylor+scaling/squaring，G1 未实现该路径）对照 θ 到 1e3 与 `θ=2π`（SE Jacobian 精确奇异）：312 组样本最大差 4.21e-13（小角自检 0.0，证明参考实现本身可信）。
10. Adjoint/左右切空间：`ξ_l=Ad(μ)ξ_r` 精确到 1.03e-16；`with_side` 往返 1.11e-16；左右预测一致 1.11e-16；蒙特卡洛一阶矩偏差 1.1–1.3%（采样噪声量级）。
11. 位置观测 Jacobian 与自写数值微分独立对照：增益最大相对差 **2.12e-9**（G1 自测只比较左右一致，没有这一项）。
12. 位姿图：GN 解与自写线性最小二乘最大差 5.92e-11；错误回环的最小二乘残差 0.157（不一致没有被抹平）；缺锚/零信息/奇异信息/断图全部 fail-closed；gauge 语义（解 = gauge∘truth）4.44e-16。
13. 长运行：SE2/SE3 各 4000 步随机 predict/update，0 次报错，协方差最小特征值 1.8e-6 / 3.2e-6，未出现假拒绝或退化；空操作（dt=0、零速度、零噪声）逐位不变。
14. **发现 F1（中）**：半正定守卫没有特征值容差（对称性检查有 `atol=1e-12`），**精确 PSD 的整数矩阵** `outer([1,2,2])`、整数 `J^T J` 被 200/200 拒绝，`solve_pose_graph` 的 `information` 因此无法用 rank-deficient PSD 表达部分约束。
15. **发现 F2（低-中）**：`GravityFrame` 的水平参考守卫按**绝对范数** `‖x‖<1e-12` 判定（错误信息说"不能与重力平行"），恰好垂直但尺度小的参考被误拒（`[1e-13,0,0]` 拒、`[1,0,0]` 收，方向相同）。
16. **发现 F3（流程）**：G1 登记的两个**文档**输入在交付后被更新（r4→r5），登记哈希 stale，G1 自己的参考脚本在当前树上不再能重放；需一级决定归档或重登记。
17. **发现 F4（低）**：`SE2/SE3.exp` 的 `_abc` 用 Python 浮点 `**`，`|θ|≳5.6e102` 时抛 `OverflowError`；`predict` 在有限 `dt`（1e300/1e308）下把这个内置异常泄漏出去，而文档化的失败模式是 `ValueError`。
18. 约定核对（回应任务信箱 #125）：G1 与 `ARCHITECTURE_V9` §4 写死的约定一致（`p_A=T_AB·p_B`、右扰动 `T̂·Exp(ξ)`、协方差按 Adjoint 在左右误差间改写、锚点/规范显式），未发现不一致；两点文档级备注见 §6。
19. 判定口径：以上 9 例反例中 3 例真实变红（对应 F1/F2/F4），另加环境事实 F3；**9/9 例的"故意改坏"对照都成功变红**（`poison_all_detected=True`），说明断言不是空转。
20. 所有判定用断言、真实非零退出：反例套件 `exit 1`（有发现）、解析界套件 `exit 0`、冻结核对 `exit 0`、最小复现 `exit 0`（= 发现复现成功）、重放 `exit 0`、pytest `exit 0`。命令与日志见 §3/§9。
21. 能力口径：G1 是 CPU 数学核心与解析参考，不是感知/3D/世界模型能力；本复核也不构成 S1 训练授权。模型预算/训练/推理/下载/安装/删除/提交推送均为 0。

## 1. 复核范围与不做什么

- 复核 G1 声明的性质：群公理、`exp∘log`、左右切空间与 Adjoint 协方差、已知 body 运动预测、局部不变 EKF（含 dexp reset 与位置观测 Jacobian）、重力对齐 SE2×高度、锚定 SE2/SE3 Gauss-Newton 图、两条 24 步解析参考与解析界。
- 只读：不修改 `src/`、`tests/`、`reports/V9-G1/` 的任何文件。被验的 `run_reference.py` 只在原地执行到**源码门**（第 30-32 行，在任何写文件之前）就退出（F3 实证）；真正产生结果的重放一律用副本写到 `reports/V-V9-G1/replay-*/`，且原件另有 `assert not target.exists()` 保护。G2 运行后重新核对 `SHA256SUMS.txt` 35/35 仍一致。
- 不做：不训练、不导入 MLX/ORT/Torch/TF、不下载、不安装、不付费、不删除、不提交推送、不写 RunStore、不动 `m0-worker.lock`、不启动任何渲染器/传感器。
- 作者测试 49 项只作对照，不当作独立证据；本报告的独立证据全部来自自写脚本。

## 2. 方法（每例都有独立判据与"故意改坏"对照）

| 反例 | 对抗输入 | 独立判据 | "故意改坏"对照 |
|---|---|---|---|
| C1 近奇异旋转 | π 附近多轴、恰好 π、SO(2) `(-π,π]` 含 `-0.0` | `exp(log(T))=T`、主值上界、轴符号约定 | 去掉近 π 分支的 `log`（NaiveSE3） |
| C2 极小/极大 dt | 0、`-0.0`、`5e-324`、`1e-300`、`1e12`、`1e300`、`1e308`、负数/NaN/Inf | 恒等、单调、有限性、失败类型 | dt=0 视为非法（ZeroRejectingGaussian） |
| C3 协方差注入 | 不定/奇异/非对称/NaN/Inf/错形状 + 精确 PSD 整数矩阵 | 严格路径必须拒、半正定路径必须收 | 特征值检查加 1e-6 容差 |
| C4 重力/水平参考 | 反号重力、1e-9/1e-11 偏差、平行与极小垂直参考 | 拒非法、收合法、lift/project 往返 | 重力方向取反（SignFlipFrame） |
| C5 错误回环 | 4.0e-1/3.0e-1 的错误闭环、缺锚、零/奇异信息、断图 | 自写线性最小二乘、残差、界、gauge | 把测量 `Z` 取逆（inverted_z_solve） |
| C6 观测 Jacobian | 左右两侧 × SE2/SE3，随机 SPD 信念 | 自写数值微分导出的增益 | SE2 左侧朝向列符号取反 |
| C7 左右切空间 | 精确恒等式 + 3 个尺度的蒙特卡洛 | `Ad P Adᵀ`、往返、左右预测一致 | Adjoint 用转置 |
| C8 独立矩阵指数 | θ 到 1e3、`2π`（SE Jacobian 奇异） | Taylor+scaling/squaring 自实现 | `_abc` 永远走小角 Taylor |
| C9 长运行 | 各 4000 步随机 predict/update、空操作 | 不报错、不退化、空操作逐位不变 | 静默加 jitter |
| A/B/C 解析界 | 自写轨迹、无界放大前提、随机图与离群 | 自写推导 + 可达性 + 锐度 | 界丢项 / 用错范数 |

## 3. 实际命令与退出码（cwd=`/Users/mac/AinerWorkFlow/AinerZero`）

```text
# 1) 反例套件（9 例，含每例 poison 对照）
PYTHONDONTWRITEBYTECODE=1 .venv-ainerzero/bin/python -B reports/V-V9-G1/independent_counterexamples.py \
  --json-out reports/V-V9-G1/evidence/counterexamples-summary.json          # exit 1（有发现）
# 2) 解析界（自写推导 + 可达性 + 锐度 + G1 数字复算）
... reports/V-V9-G1/independent_bounds.py --json-out .../bounds-summary.json # exit 0
# 3) 发现最小复现（0 = 发现复现成功）
... reports/V-V9-G1/findings_minimal_repro.py                               # exit 0
# 4) 冻结核对（SHA/测试/变异/git 范围）
... reports/V-V9-G1/freeze_check.py                                         # exit 0
# 5) 独立重跑 G1 测试
.venv-ainerzero/bin/python -m pytest tests/v9/geometry -q -p no:cacheprovider \
  --junitxml=reports/V-V9-G1/evidence/g1-tests-replay.xml                    # exit 0（49 passed, 1.24 s）
# 6) 原始参考脚本（只读安全：源码门在写文件之前）
.venv-ainerzero/bin/python -B reports/V9-G1/r1-codex-20261016/run_reference.py  # exit 1（F3）
# 7) 文档化补丁副本重放（只改消费门，代码输入仍强制核对）
.venv-ainerzero/bin/python -B reports/V-V9-G1/replay-r1/run_reference.py    # exit 0
# 8) 一键重跑全部证据（等价于上面 1-7 + 重建 metrics.json，约 10 分钟）
bash reports/V-V9-G1/run_all.sh
```

`run_all.sh` 不删除任何历史证据：每次重放写到新的 `replay-<时间戳>/`（模板在 `replay-template/`），已归档的第一次重放是 `replay-r1/`。G2 已端到端执行过一次 `run_all.sh`，逐条退出码与上表完全一致（反例 1、界 0、最小复现 0、冻结 0、pytest 0、原件 1、副本重放 0、0 字段差异），第二次重放的证据目录为 `replay-20261016T134113/`。

## 4. 逐项结果

### 4.1 C1 近奇异旋转（PASS，真实非零）
2160 组样本，`max|exp(log(T))−T| = 1.8797463585684682e-13`（≤1e-9 门），恰好 π 的轴符号约定 0/200 违反，SO(2) 主值上界与 `r[1,0]=-0.0` 分支均正确（该分支在 `atan2(-0.0,-1)=-π` 时确实可达，被 `w<=-π→π` 处理）。π 附近 ±1e-13 的边界不连续是拓扑限制、G1 已在 README 明示，本复核确认其**不影响** `exp(log(T))=T`。

### 4.2 C2 极小/极大 dt（FAIL → F4）
`dt=0` 与 `dt=5e-324` 的均值/协方差漂移都是 **0.0（逐位）**；`-1/-1e-300/NaN/±Inf` 全部 `ValueError`；协方差迹随 dt 单调（0.1→2.27）；极小 dt 位移尺度律相对误差 1.9e-8。**但** `dt=1e300/1e308`（`delta` 有限）在 `_abc` 里溢出，抛 `OverflowError`（F4）。

### 4.3 C3 协方差注入（FAIL → F1）
严格 SPD 路径正确拒绝不定/奇异/非对称/NaN/Inf/错形状，且不改写合法 SPD；半正定路径正确拒绝负定与 NaN。**但**对 rank-deficient 的真 PSD 输入：`diag(1,1,0)` 0/200 拒绝（对角矩阵特征值精确为 0，侥幸通过），`outer([1,2,2])`（元素为精确整数）**200/200 拒绝**、整数 `J^T J` **200/200 拒绝**、随机 `u uᵀ` 200/200、随机 `J^T J`(2×3) 96/200。决定性依据：整数矩阵存进 float64 后与精确矩阵逐位相同，其精确特征值为 `{9,0,0}`/`{0,σ²}` 非负；`eigvalsh` 给出 −5.55e-16 / −1.14e-16 即被拒。

### 4.4 C4 重力与水平参考（FAIL → F2）
合法：`gravity=−9.81·up`（偏差 1e-11 内）接受，`lift/project` 往返 8.9e-16、高度 4.4e-16、保持 up 2.2e-16、子群闭合 3.3e-16，roll/pitch 1e-6 与 1e-3 均拒绝。非法：反号重力、1e-9 偏差、水平参考与 up 平行均拒绝。**但**方向完全相同、仅尺度不同的水平参考结论不同：`[1e-13,0,0]` 与 `[1e-20,0,0]` 被拒，`[1,0,0]` 与 `[1e8,0,0]` 被收。

### 4.5 C5 错误回环（PASS）
40 个含错误闭环的随机图：GN 解与自写 `lstsq` 最大差 5.92e-11；最小二乘残差最小 0.157（不一致**没有**被抹平）；解析界覆盖真误差（最大超出 −0.281，即界有余量）；`rank==free_dimensions`；anchor 逐位冻结。fail-closed 探针：缺锚/零信息/奇异信息/断图 → `ObservabilityError`，自环 → `ValueError`。gauge 语义（anchor 初值 ≠ 真值）解 = gauge∘truth，差 4.44e-16。

### 4.6 C6 观测 Jacobian（PASS，G1 未覆盖项）
左右两侧 × SE2/SE3 各 6 个随机信念：把 code 返回的增益与"对位置映射做数值微分 → 解析增益"对照，最大相对差 **2.12e-9**；高精度观测下位置被拉向测量。这补上了 G1 自测"只比较左右一致"没有覆盖的方向（符号/坐标约定错误会被这一项抓住，poison 已验证）。

### 4.7 C7 左右切空间与 Adjoint 协方差（PASS）
`max|ξ_l−Ad(μ)ξ_r| = 1.03e-16`（精确恒等式）；`with_side` 往返 1.11e-16；左右 `predict` 一致 1.11e-16；蒙特卡洛经验协方差与 `scale²·Ad P Adᵀ` 的 Frobenius 相对差 SE2 1.08%、SE3 1.34%（≈ 1/√20000 采样噪声量级，三种尺度一致）。

### 4.8 C8 独立矩阵指数（PASS）
312 组样本（θ ∈ {0,…,1e-4,0.1,1,π−1e-6,π,2π−1e-9,2π,2π+1e-9,10,1e3} × 随机轴 × 12 seeds × 两群），与自写 Taylor+scaling/squaring 矩阵指数最大差 **4.213296378452469e-13**（按 max|entry| 归一后 ≤1e-12）；小角自检 `SE2/SE3 = 0.0`（自写实现与 G1 在可对照域逐位相同，证明参考本身可信）。`θ=2π` 处 SE Jacobian `V` 精确奇异（det=0），G1 的 Rodrigues/Jacobian 形式仍与独立矩阵指数一致；`validate` 对每个输出都通过。poison（`_abc` 永远走小角 Taylor）被抓住。

### 4.9 C9 长运行与空操作不变性（PASS）
SE2 与 SE3 各 4000 步随机 `predict`/`update_position`：**0 次**报错或假拒绝，协方差最小特征值分别 1.844e-6 / 3.225e-6（全程严格正定）；100 次空操作（`dt=0`、零速度、零过程噪声）后均值与协方差**逐位不变**。poison（静默加 jitter，README 明确承诺不做）被空操作不变性抓住。

### 4.10 解析界推导 vs 实测（PASS，`independent_bounds.py` exit 0）
- **A1 自写 24 步轨迹**（自选矩形路径/偏差/协方差）：max 误差 0.01313227624176149 ≤ max 界 0.013269552381363276（比值 0.98965），协方差全程正定。
- **A2 可达性**：在 `‖e‖≤B、‖d_u‖≤b_u、‖d_z‖≤b_z` 上对抗搜索 400×4000 次，最好比值 0.99914 → 三角不等式界在 0.09% 内可达，不是空界。
- **A3 前提破坏**：真实里程误差取登记界的 5 倍 → 24 步中 **23 步越界** → 界确为条件界，与 G1 声明一致。
- **A4 守卫**：负界/NaN 界/非方形增益/Inf 增益 → `ValueError`。
- **B 图界**：与自写谱范数公式一致（≤1e-12）；覆盖真误差（最大超出 −0.0443）；**锐度**：沿 `A⁺` 主左奇异方向构造边误差时比值 0.9999999999999993…1.0000000000000004（等号可达）；秩亏输入 → `ObservabilityError`；GN ≡ 自写 `lstsq`（10 seeds）。
- **C G1 数字复算**：只用 `cpu_registration.json`（`filter_*` 参数、24 步、`drift`）+ 25 点环图结构，独立重算整条界序列，与 `reference-results-r1.json` 的 `prediction_bound`/`updated_bound` **最大差 0.0**；报告误差/界最大 0.99862，更新使界收缩（最大 `B₊/B₋=0.731`）；图界 0.14065436840675918 与报告逐位相同；`after_error_l2` 与 `linear_exact_error_l2` 差 ≤1e-9。

### 4.11 证据身份与重放（PASS + F3）
`SHA256SUMS.txt` 35/35 一致；`source-sha256.json` 全一致；登记 SHA=报告引用值；测试 XML 49/0/0 且独立重跑 49 passed；12/12 变异 exit1；首次失败日志为真实断言。git 范围：G1 只新增 `src/ainerzero/v9/`、`tests/v9/`、`reports/V9-G1/`，无受跟踪文件在 G1 报告时间前被改动。原始参考脚本重放被消费门挡住（F3）；豁免两个文档输入后重放，输出与报告 **0 字段差异**。

## 5. 发现与建议

### F1（中）半正定守卫拒绝真 PSD 输入
- 位置：`belief.covariance(..., semidefinite=True)`（`belief.py:17-27`），被 `TangentGaussian.predict`（过程协方差率）与 `solve_pose_graph`（information）调用。
- 事实：`smallest = eigvalsh(p)[0]`；`if smallest < 0` 直接拒绝，**没有容差**；相邻的对称性检查却有 `atol=1e-12`。
- 复现：整数矩阵 `outer([1,2,2])`（精确特征值 9,0,0）与整数 `J^T J` 200/200 被拒；`solve_pose_graph` 用 rank-1 PSD 作 `information` 时报 `ValueError: covariance must be positive semidefinite`（README 说 information 允许半正定以表达部分约束）。
- 影响：fail-closed，不产生错数，但下游（B2/G3/S1）无法用 `JᵀWJ`、`uuᵀ` 这类自然写法表达部分约束；必须改成对角形式绕开。
- 建议（不改数学）：容差与对称性检查一致，例如 `tol = 1e-12 * max(1.0, ‖P‖₂)`，`smallest < -tol` 才拒绝；或在文档里明确"只接受对角式半正定"。**由一级决定是否让 G1 补修。**

### F2（低-中）重力框架的水平参考守卫是尺度相关的
- 位置：`gravity.py:27-28`，判据 `‖h−u(u·h)‖ < 1e-12`，错误信息是"必须不与重力平行"。
- 事实：`[1e-13,0,0]` 与 `[1,0,0]` 都与 `up=[0,0,1]` **恰好垂直**（方向相同），前者被拒、后者被收；阈值实际是绝对范数，不是夹角。
- 影响：fail-closed；对小尺度单位制（或未归一化的参考向量）会误拒合法输入。
- 建议：改成夹角判据（`‖x‖/‖h‖ < 1e-12` 或 `|h·u|/(‖h‖‖u‖) > 1−1e-12`），错误信息与判据一致。

### F3（流程/身份）登记的两个文档输入已 stale，G1 参考脚本不能原样重放
- 事实：`cpu_registration.json` 登记 `ARCHITECTURE_V9.md=ebaf1c4b…`、`docs/research/V9_RESEARCH_SURVEY.md=51f6a984…`；当前树为 `0f54a96a…`、`1dc744ea…`（两个文件 mtime 在 G1 报告之后，是 r4→r5 与 r4 勘误造成的漂移，**不是 G1 改动**）。两个**代码**输入（`gridlab2d.py`、AWZ `motion.py`）仍逐字节一致。
- 后果：`run_reference.py:30-32` 的消费门现在直接 `AssertionError: registered source changed: ARCHITECTURE_V9.md`（G2 已实测），G1 报告的"交付时再次核对匹配"在**当时**成立，但**现在**无法原样重放；G1 的复算链因此断了。
- G2 的处理：只在副本里豁免 stale `.md` 条目（代码输入仍强制核对），重放输出与报告 0 差异，证据在 `replay-r1/`；**未改 G1 登记与原件**。
- 需一级决定：把 r4 的两个文档冻结归档并把登记哈希指向归档件，或以当前修订重新登记；否则任何"按登记重放"的验收口径都会失败。附带观察：`run_reference.py` 把登记哈希写进结果（`registration_sha256`）但**不与自己期望的 5aa8199f… 比较**，所以登记漂移不会被它自己发现。

### F4（低）`exp` 在超大角上泄漏 `OverflowError`，`predict` 未兜住
- 位置：`lie.py:_abc` 用 Python 浮点 `theta**2`/`theta**3`（`theta**3` 在 `|θ|≳5.6e102` 溢出抛 `OverflowError`，而 `theta*theta` 只会给 `inf`）；`SE3.exp` 的 `isfinite` 守卫只在 `‖φ‖>1.34e154`（`np.linalg.norm` 平方溢出）时生效，中间区间同样泄漏。
- 复现：`SE2.exp([0,0,1e103]) → OverflowError`（`1e102` 正常、`2π` 正常）；`TangentGaussian.predict(vel, 1e300, rate)` → `OverflowError`，而 `predict` 文档化的溢出失败模式是 `ValueError`（`tangent_jacobian` 也示范了显式 `ValueError`）。
- 影响：fail-closed、物理上极端（θ≥5.6e102 rad），但异常类型泄漏出 API 契约，调用方 `except ValueError` 兜不住。
- 建议：`_abc` 用 `np.float64`/`math` 前先做尺度检查，或在 `exp`/`predict` 入口对 `|θ|` 超阈值抛 `ValueError('rotation magnitude overflow')`；也可在 `_abc` 内改用 `theta*theta`（得 `inf`，由 `validate` 兜住）。范围声明（README"不声称浮点可容纳无限尺度乘积"）保留，只需让失败类型一致。

### 边界备注（不算缺陷，供一级登记）
1. `converged` 是**绝对**步长容差：坐标 ~1e6 且锚点离真值远时，解在 gauge 平移后逐位正确（相对误差 0），但 `converged=False`（残差 1.16e-10 已是浮点噪声地板）。调用方需按尺度放大 `step_tolerance`。
2. 近 π 轴符号只在**恰好 π** 有约定；π−0…π−1e-13 区间 `sine` 与阈值同量级，但 `exp(log(T))=T` 仍 ≤2.2e-14（G2 实测），不影响正确性。
3. G1 测试只用了 `np.diag([1,1,0])` 覆盖半正定路径，恰好是对角矩阵（特征值精确 0）→ F1 未被自测覆盖。
4. `tests/v9/` 与 `src/ainerzero/v9/` 未纳入 git 跟踪（G1 新增目录），本次复核按 SHA 冻结而非 git 版本。

## 6. 对 `ARCHITECTURE_V9` §4 约定的核对（回应任务信箱 #125）

通知要求：复核时写明 G1 实际约定是否与 §4 写死的约定一致，不一致只记录、不改 G1。

| §4 约定（`ARCHITECTURE_V9.md` 行 119-127） | G1 实际实现 | 判定 |
|---|---|---|
| `T_AB` 把 B 系点变到 A 系，`p_A=T_AB·p_B`，`T_AC=T_AB·T_BC` | `lie.py` 头注：`T` 即 `p_world=R p_body+t`；`compose(a,b)=a@b`；`SE2/SE3` 同构 | 一致（A=world、B=body） |
| 右误差 `X=μ·Exp(ξ_r)`、`T=T̂·Exp(ξ)` | `boxplus(..., side='right') = compose(mean, exp(delta))` | 一致 |
| 协方差的 Adjoint 变换：只用于右↔左误差改写，不是换世界系时右误差协方差的变换；纯左乘下 `ξ_r` 与协方差不变 | `with_side` 要求同均值、只做 `Ad P Adᵀ`/逆；`predict` 的 `F=Ad(U⁻¹)` 是 body 运动 `μ'=μU` 的基点变换；`update_position` 右侧只把测量/噪声转到局部系（`h=[I,0]`、`r=Rᵀ(z−p)`、`R'=RᵀR_wR`），**不动状态协方差** | 一致（§4 的"不得当作任意换系变换"在代码里没有被违反） |
| 式1 相对位姿 `T_AB=T_WA⁻¹T_WB` | `RelativeFactor(i,j,Z=X_i⁻¹X_j)`、残差 `Log(Z⁻¹X_i⁻¹X_j)` | 一致 |
| 规范与锚点显式；不可观测自由度必须声明 | `solve_pose_graph` 强制显式 `anchor`、冻结其初值、返回 `gauge` 字符串；缺锚/秩亏 → `ObservabilityError`；`GravityFrame` 要求显式 `gravity/up/水平参考` | 一致（单目尺度不适用：本层无单目几何） |

记录两点文档级备注（不改 G1，交一级）：
1. G1 的 API 只用 `T`，没有 `T_AB` 下标命名；§4 的 A/B 语义只能靠"world/body"约定推断。下游 B2/G3 引用时应显式写"world←body"。
2. `src/ainerzero/v9/geometry/README.md` 第 19 行讲左右误差与 Adjoint 时，没有重复 §4 行 124 的"不得当作换世界系变换"限定；§4 已写"B2、G3 的实现以 G1 为准"，所以不构成冲突，仅建议 README 补一句以免下游误用。

## 7. 未验证与限制

- 未验证：一般非线性 SE(2)/SE(3) EKF 的全路径确定性界（G1 自己也未声明）；任意噪声分布下的统计校准（NEES 覆盖率）不在本任务范围；G3 规范化 operator / RGB warp 未实现，本复核不涉及；AWZ 侧只用到解析 `Trajectory2D`，未启动渲染/传感器/模型。
- 未复算：GridLab 与 AWZ 的"真值路径"本身只做**重放复现**（0 差异），没有独立第三方实现去复算 GridLab 的 `apply` 语义（超出 G1 范围，属环境侧）。
- 采样噪声：C7 的蒙特卡洛偏差 ~1.1–1.3% 是 1/√N 噪声地板，不是一阶矩误差；精确恒等式（1e-16）才是该项的主要证据。
- 复核者局限：本报告由 `deepseek-8seu`（二级执行层）撰写，非 G1 作者；G2 只"建议"，不 accept、不修改被验文件、不追加新运行授权。
- 临时目录：无外部临时目录；重放副本与全部证据都在 `reports/V-V9-G1/` 内。`/tmp/probe*.py` 为探针脚本（一次性，结论已固化到本目录脚本与日志）。

## 8. 交回统筹的决定点

1. 是否按 F1/F2 让 G1（或后继小任务）补修守卫容差与夹角判据？两者都不改数学、不改参数、不改界，属 fail-closed 可用性修复。
2. F3：归档 r4 文档并把登记哈希指向归档件，还是以当前修订重登记？在此之前，"按登记重放"类验收应把两个 `.md` 标为已知 stale。
3. F4 是否要统一异常类型（`OverflowError` → `ValueError`）？若判定"超出登记测试域，仅记录"，也可直接登记为范围限制。
4. 是否接受 G2 的结论（建议有条件验收）并据此推进 G2 之后的下一步；G2 不自行 accept。
5. 是否要求把 G2 的 9 例反例（尤其 C3/C4）纳入仓库常驻测试，作为后续 GeometryCore 变更的回归门。

## 9. 证据清单与身份

| 文件（`reports/V-V9-G1/`） | 内容 | 退出码 |
|---|---|---|
| `independent_counterexamples.py` | 9 例自写不利反例 + 每例 poison 对照（9/9 变红） | 1（3 例发现 F1/F2/F4） |
| `independent_bounds.py` | 解析界自写推导 + 可达性 + 锐度 + G1 数字复算 | 0 |
| `findings_minimal_repro.py` | F1/F2/F4 最小复现（0 = 复现成功） | 0 |
| `freeze_check.py` | SHA/测试/变异/git 范围冻结 | 0 |
| `replay-r1/run_reference.py` | G1 参考脚本副本（仅消费门补丁，见 F3） | 0 |
| `replay-r1/reference-results-r1.json` | 重放结果（与 G1 报告 0 字段差异） | — |
| `replay-template/` | 副本模板（`run_all.sh` 据此生成新的 `replay-<时间戳>/`） | — |
| `run_all.sh` | 一键按 §3 顺序重跑全部证据并重建指标（不删除历史） | 见 §3 各行 |
| `evidence/counterexamples.log` / `-summary.json` | 反例逐项指标与违反 | — |
| `evidence/bounds.log` / `bounds-summary.json` | A/B/C 三部分指标 | — |
| `evidence/freeze-check.log` | 35/35 SHA、49 测试、12 变异、git 范围、输入 fresh/stale | — |
| `evidence/original-replay-gate-failure.log` | 原始脚本被登记门挡住（F3 实证） | 1 |
| `evidence/replay-r1.log` | 重放摘要输出 | 0 |
| `evidence/replay-vs-g1-json-diff.txt` | 报告 JSON vs 重放 JSON：0 差异 | — |
| `evidence/g1-tests-replay.xml` / `.log` | 独立重跑 G1 的 49 项测试 | 0 |
| `evidence/findings-minimal-repro.log` | F1/F2/F4 复现记录 | 0 |
| `metrics.json`（relay `--data-file`） | 本报告指标汇总（由 `build_metrics.py` 从证据 JSON 生成，不手抄） | — |
| `replay-20261016T134113/` | `run_all.sh` 第二次重放证据（同样 0 字段差异） | 0 |

被验源码身份（`source-sha256.json` 已核对一致）：
`src/ainerzero/v9/geometry/__init__.py 694ed4e6…`、`belief.py e4376981…`、`gravity.py 4d758a9f…`、`lie.py fb56767d…`、`pose_graph.py 20d5bbe4…`；登记件 `cpu_registration.json 5aa8199f…34c6`。

## 10. AGENT_TASKS 模板字段

```markdown
# ainerzero.V9.G2 执行报告
角色：executor；负责人：deepseek-8seu；时间：2026-10-16（+03）
任务状态：reported；实验状态：completed（纯 CPU 只读复核）
任务依据：relay 任务 ainerzero.V9.G2（verify ainerzero.V9.G1）；参数 v0 {}
输入身份：G1 源码/测试/报告 SHA（§9）；登记 5aa8199f…；两个文档输入 stale（F3）
修改文件：仅 reports/V-V9-G1/（脚本/证据/报告/指标）；未改被验文件
实际执行：§3 的 8 条命令（含 run_all.sh 端到端重跑）；反例 exit1、解析界 exit0、最小复现 exit0、冻结核对 exit0、重放 exit0、pytest 49 passed
验证结果：9 例反例（3 例真实发现：F1/F2/F4；F3 为环境事实）；全部 poison 对照变红；界序列复算差 0.0；报告 JSON 重放 0 差异；49/49 测试；12/12 变异 exit1
产物：reports/V-V9-G1/{report.md,metrics.json,independent_*.py,findings_minimal_repro.py,freeze_check.py,replay-r1/,evidence/}
失败与限制：见 §5（F1 半正定守卫无容差；F2 重力参考守卫尺度相关；F3 登记文档漂移致原脚本不能重放；F4 超大角 OverflowError 泄漏）；一般非线性 EKF 全路径界未验证（G1 亦未声明）
交回统筹：§8 五个决定点；G2 只建议，不 accept
```
