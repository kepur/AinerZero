# ainerzero.V9.G3 执行报告

角色：executor；负责人：`deepseek-flash-9m2x`；时间：2026-10-20（+03）
任务状态：reported；实验状态：未执行训练/无模型工作（纯 CPU 工程性质测试）
任务依据：AinerRelay 任务卡 `ainerzero.V9.G3`（D-021 放行，代码门 awz.V9.A10 已开）；
`ARCHITECTURE_V9.md` r5 §2、§3 GeometryCore 行、§4 式 9、§4 约定段；
`AnimeWorldZero/docs/design/V9_LANDING_PLAN.md` §11.1（r4 改写：输入只限点/对象向量/地图坐标、
等变误差按来源分列、约定与 G1 一致）。

## 摘要（结果与边界）

- 新增 `src/ainerzero/v9/geometry/canonical.py`：解析规范化算子 `canonicalize`/`decanonicalize`，
  支持点集（2D/3D，含地图坐标）、位姿（SE(3) 世界位姿）、速度/方向向量、平面度量栅格；
  另含按信念协方差 Σ 的位姿误差注入工具与右扰动一阶误差传播预测函数。
- 只用估计位姿 μ̂ 的重力对齐部分 `g(μ̂) ∈ SE(2)`；高度与重力方向原样保留，不做完整 SE(3) 规范化；
  估计位姿含 roll/pitch 时**拒绝**而不是静默投影。RGB/图像输入显式拒绝（r4 范围外）。
- 新增 `tests/v9/geometry/test_canonical.py`：57 项性质测试；`tests/v9/geometry` 全量 **106 passed**
  （含 G1 原有 49 项，0 失败/跳过），CPU 墙钟 8.7 s。
- `decanonicalize∘canonicalize` 恒等：全部类型最大误差 ≤ 8.9e-16（登记容差 1e-9）；
  对随机 `g ∈ SE(2)`（含 θ≈±π、平移 0/±1e-12）等变误差 ≤ 8.9e-16（登记 1e-9）；
  任意随机非等变 numpy 映射包进规范化后严格等变，误差 ≤ 1.8e-15（且证明该映射本身非等变）。
- 位姿误差传播：Σ 注入经验协方差相对误差 3.1%（N=6000，登记 5%）；SE(2) 点/向量规范化误差经验协方差
  与 `JΣJᵀ` 一阶预测相对误差 3.1%/0.8%，SE(3) 为 1.1%（滚动/俯仰扰动恒为 0，见限制）。
- 栅格：双线性重采样、索引域外填 `fill` 并返回有效性掩码；插值误差满足解析界
  `B1 = h²/4·sup‖Hessian f‖₂`（登记测试场），往返误差 ≤ `2·B1`，h 减半误差比 3.85（O(h²)）。
- 故意改坏对照：3 个变异（`g` 反向、漏重力对齐改用完整 SO(3)、栅格旋转方向取反）在真实子进程
  pytest 中全部变红（分别 27/2/3 项失败）；只做导入改写的对照变异全绿（57 passed），证明测试装置本身不红。
- G1 已验收源码 6 个文件 SHA256 与 `reports/V9-G1/r1-codex-20261016/source-sha256.json` 逐字节一致；
  仅新增上述 2 个文件与 `reports/V9-G3/`，未改 G1 文件、`__init__.py` 或其他目录。
- 这是作者证据，不是独立验收（G4 复核待做）；测试通过不代表视觉/空间/学习能力。

## 实现要点与约定

- 约定直接沿用 G1（不重新定义）：`T_AB` 把 B 系坐标变到 A 系，`p_A = T_AB p_B`，`T_AC = T_AB T_BC`；
  右扰动 `X = μ Exp(ξ_r)`；左/右误差转换 `ξ_l = Ad(μ) ξ_r`。G3 与 r4 §4 约定核对一致，故未停车、未改 G1。
- 规范提升：`L(μ̂) = frame.lift(g(μ̂), 0) ∈ SE(3)`（偏航 + 水平平移、竖直平移为 0），
  `canonicalize: x̃ = L⁻¹x`，`decanonicalize: x = L x`。等价于式 9 的 `x̃ = g(μ̂)⁻¹·x`、`y = g(μ̂)·f(x̃)`。
- 类型分派：`WorldPoints`/`WorldVectors` 标签区分“平移作用”的点与“仅旋转作用”的向量，标签随
  规范化/反规范化保持，使 `decanonicalize∘canonicalize` 在泛型 API 上也有定义；位姿按尾部 `(4,4)` 识别；
  `(H,W,3)` 类图像数组抛 `ValueError`，不会当成 3D 点集。
- 位姿误差注入：SE(2) 按完整 3 维 Σ 采样；SE(3) 只在保持重力对齐的切空间子空间采样
  （任意平移 + 偏航，无 roll/pitch），否则扰动后的位姿违反 G3 合同。`sample_pose_errors`/
  `apply_pose_error`/`inject_pose_error` 供训练侧使用；本卡只实现与测试，未训练。
- 一阶传播：右扰动下规范化点误差 `δ = -[ρx, ρy, 0] - θ·J·p`，向量误差 `δ = -θ·J·v`，预测为 `JΣJᵀ`；
  明确为一阶/小噪声结果，不是无界高斯的全路径确定性界（左扰动仅支持注入，不提供传播预测）。
- 栅格语义：`PlanarGrid` 的 `frame` 是格点坐标系在重力平面坐标中的 SE(2) 位姿，单元 (i,j) 中心为
  `((j+0.5)r, (i+0.5)r)`；规范化输出轴对齐于规范帧（智能体中心），双线性插值、边界索引截断、
  源索引域外填 `fill`、`valid` 掩码标记不可用单元，并记录来源帧以便 `decanonicalize_grid` 渲染回原格点。

## r4 改写要求逐条对应

| r4 要求 | 实现/证据 |
|---|---|
| 输入只限点、对象向量、地图坐标；原始 RGB 不在范围 | 点为 2D/3D 世界点（含地图坐标），向量为旋转作用量，栅格为平面地图坐标；`(H,W,3)` 图像输入测试断言 `ValueError`；文档写明无图像 warp |
| 等变误差按来源分列报告 | metrics.json `error_sources`：栅格插值（解析界+实测）、边界（clamp+fill+掩码，边界/内部误差分开）、数值误差（≤1e-15）、数据关联（本算子不做关联，恒 0，不对外部管线声称） |
| 约定与 G1 一致（T_AB 方向、右扰动）；不一致就停下报告 | G1 README/§4 核对一致：`p_world=R p_body+t` 即 `T_WB`；右误差 `X=μExp(ξ)`；未发现冲突，G1 文件未改 |
| 不自行改 G1 | 6 个 G1 文件哈希与 G1 登记逐一相同（run_checks.py 断言） |

## 实际命令（cwd=`/Users/mac/AinerWorkFlow/AinerZero`）

```text
# 依赖环境：既有 .venv-ainerzero（Python 3.12 / NumPy 2.5.3 / pytest 9.1.1），未安装任何依赖
.venv-ainerzero/bin/ruff check --no-cache src/ainerzero/v9/geometry/canonical.py tests/v9/geometry/test_canonical.py
.venv-ainerzero/bin/python -m pytest tests/v9/geometry -q -p no:cacheprovider \
    --junitxml=reports/V9-G3/r1-deepseek-flash-20261020/cpu-tests.xml
.venv-ainerzero/bin/python -B reports/V9-G3/r1-deepseek-flash-20261020/run_mutations.py
.venv-ainerzero/bin/python -B reports/V9-G3/r1-deepseek-flash-20261020/run_checks.py
```

`run_mutations.py` 在 `$TMPDIR/ainerzero-g3-mutants-*/` 隔离目录生成变异副本（运行后自动删除），
每个变异用真实子进程 pytest + 环境变量 `AINERZERO_CANONICAL_OVERRIDE` 指向变异副本；
源码与测试文件本身不被改写。`run_checks.py` 断言 G1 哈希、重测全部性质并写 `metrics.json`，
任一门不满足即非零退出（本次 exit 0）。

## 身份（源码/测试 SHA256）

| 文件 | SHA256 |
|---|---|
| `src/ainerzero/v9/geometry/canonical.py` | `ea446f76043f8aeac33d1665dbf18252a4678700b849d54e17f5fa9cc3282a50` |
| `tests/v9/geometry/test_canonical.py` | `38ced822b96d9815b6d1a7a2f40d3e0c48475054466311699dfd7dff02ab9606` |
| `reports/V9-G3/r1-deepseek-flash-20261020/run_mutations.py` | `4be767fc2605483021c913cafccd14997fc5406e8b395009d0bad8d98ab15113` |
| `reports/V9-G3/r1-deepseek-flash-20261020/run_checks.py` | `bb30792f933c16b38079c218c193f44b5e97d639b4c08cb3ed43d52d7775ad9c` |

完整登记制文件：`source-sha256.json`。G1 6 文件的期望/实测哈希见 `metrics.json.g1_source_checks`（全部 unchanged）。
输入身份：`ARCHITECTURE_V9.md` r5、G1 实现（`lie.py`/`belief.py`/`gravity.py`/`pose_graph.py`）、
G1 报告与 `cpu_registration.json` 均只读消费；本卡未改架构、参数、数据或既有报告。

## 验证结果（作者 CPU 证据）

| 性质 | 登记容差 | 实测最大误差/相对误差 |
|---|---|---|
| `decanonicalize∘canonicalize`（点2D/3D、向量2D/3D、位姿；SE2/SE3 信念；Z-up/Y-up；含 θ=±π、±(π−1e-12)、平移 0/±1e-12） | ≤ 1e-9 | 8.88e-16 |
| `canonicalize(g·x, g·belief) = canonicalize(x, belief)`（全部类型，随机 g 含近 ±π） | ≤ 1e-9 | 8.88e-16 |
| 任意随机非等变映射包进规范化后的整体等变（SE(2)） | ≤ 1e-9 | 1.78e-15 |
| 位姿误差注入经验协方差 vs Σ（N=6000） | ≤ 5% | 3.09% |
| SE(2) 点规范化误差经验协方差 vs `JΣJᵀ` | ≤ 5% | 3.07% |
| SE(2) 向量规范化误差经验协方差 vs `JΣJᵀ` | ≤ 5% | 0.80% |
| SE(3) 点（重力对齐子空间注入） | ≤ 5% | 1.06%（SE(3) 子空间注入经验协方差 2.60%） |
| 栅格插值 vs 解析场，h=0.1/0.05 | 解析界 h²/4·sup‖H‖₂ | 1.52e-3 / 4.13e-4；界 2.06e-3 / 5.16e-4 |
| 栅格往返，h=0.1/0.05 | ≤ 2·B1 | 2.59e-3 / 6.73e-4，均 ≤ 界；h 减半误差比 3.85（登记 [3,5]） |
| 栅格等变（规范化数据与掩码） | ≤ 1e-9 | 数据 2.2e-16；掩码全等 |
| 标记点旋转方向判别 | 峰值距期望 ≤1.5 格 | 0.035 m（0.7 格）；反向预测位置分离 >2 格 |
| 空点集/空位姿集 | 形状保持 | (0,2)/(0,3)/(0,4,4) 全部保持 |

位姿/高度约定专项：SE(3) 信念（高度 0.37）下，位于智能体水平位置、世界高度 1.25 的点规范化为
`[0,0,1.25]`；智能体位姿规范化为单位旋转 + `[0,0,0.37]` 平移；随机点沿 up 的分量逐点保持；
roll/pitch 位姿被拒绝（`ValueError`）。这些断言同时是“漏掉重力对齐”变异的检出点之一。

## 故意改坏对照（真实子进程、非手写状态）

| 变异 | 结果 | 证据 |
|---|---|---|
| 对照：仅把相对导入改写为绝对导入，无功能变异 | 全绿 57 passed，exit 0 | `mutation-control-import-shim-only.log` |
| 把 `g` 换成 `g⁻¹`（规范化方向反） | 变红：27 failed，exit 1 | `mutation-inverse-direction-g-instead-of-g-inverse.log` |
| 漏掉重力对齐、改用完整 SE(3) 位姿 | 变红：2 failed，exit 1 | `mutation-full-se3-missing-gravity-alignment.log` |
| 栅格旋转方向取反（去掉源帧逆变换） | 变红：3 failed，exit 1 | `mutation-grid-rotation-direction-reversed.log` |

汇总：`mutation-results.json`（含每个变异 SHA、失败测试名、返回码）；任一变异存活则脚本非零退出。

## 失败与限制（如实）

- 本交付是**作者证据**，不是独立验收；`ainerzero.V9.G4` 独立复核未做，`accepted` 由统筹决定。
- 栅格往返上界只对登记的 C² 测试场与分辨率成立并有 O(h²) 收敛验证；中间栅格只有 C⁰，
  因此**不声明任意函数/任意精度的通用解析界**。
- 一阶协方差传播只在小噪声、右扰动约定下成立；左扰动支持注入但不提供传播预测。
  SE(3) 注入只覆盖保持重力对齐的切空间子空间（任意平移+偏航）；完整 6 自由度噪声会破坏
  G3 合同（roll/pitch 被拒绝），这是合同决定的限制，不是遗漏。
- 未接真实位姿估计器、传感/地图/学生管线；**数据关联误差**在本算子中恒为 0（不做关联），
  不对外部感知管线声称任何关联精度。
- 未修改 `src/ainerzero/v9/geometry/__init__.py`（文件范围外），因此公开导入需写
  `from ainerzero.v9.geometry.canonical import ...`；是否加入包导出留待后续卡/统筹决定。
- CPU 工程性质测试通过不代表空间能力、视觉能力或 S1 科学门通过；未训练、未下载、未安装、未付费、
  未提交/推送、未删除任何既有材料；模型/训练预算 0。

## 产物

目录 `reports/V9-G3/r1-deepseek-flash-20261020/`：
`report.md`（本文件）、`metrics.json`（指标与门）、`cpu-tests.xml`（106 项 JUnit）、
`mutation-*.log`（4 份真实子进程日志）、`mutation-results.json`（变异汇总）、
`source-sha256.json`、`run_mutations.py`、`run_checks.py`。
源码与测试：`src/ainerzero/v9/geometry/canonical.py`、`tests/v9/geometry/test_canonical.py`。

## 交回统筹

1. 请 G4 独立复核重点：规范化方向与 `T_AB` 约定、SE(3) 信念的高度/重力保留、栅格重采样掩码、
   一阶传播公式与容差、3 个变异的检出是否由断言而非环境错误产生。
2. 待决定：`canonical` 模块是否加入 `geometry/__init__.py` 公开导出（涉及 G1 文件范围，需另卡）。
3. 本卡未提出的扩展（数据关联误差、真实估计器端到端、图像/点云规范化）不在文件范围，未做。
