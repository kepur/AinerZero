# ainerzero.V9.G5 执行报告：G1 r2 小修（F1 半正定容差 / F2 重力参考相对判定 / F3 输入重登记）

角色：executor（二级执行层）；负责人：`deepseek-flash-a7k2`；时间：2026-10-20（+03）
任务状态：reported；实验状态：completed（纯 CPU 工程小修与回归；**不是**能力验收或 S1 科学门）
任务依据：relay 任务 `ainerzero.V9.G5`（参数 v0 `{}`，照用不改）；一级裁决 F1/F2/F3；D-021 放行（D-019 代码门已开）后执行
输入身份：r1 登记 `reports/V9-G1/r1-codex-20261016/cpu_registration.json` SHA256 `5aa8199f…34c6`（未改）；r2 重登记 `reports/V9-G1/r2/input_registration_r2.json` SHA256 `41f5acb6…e129`；逐节差异 `section_changes.json` SHA256 `3f5a6641…595c`
修改文件：`src/ainerzero/v9/geometry/belief.py`（F1 相对容差守卫）、`gravity.py`（F2 方向判定）、`pose_graph.py`（F1 特征值截断）、`geometry/README.md`；新增 `tests/v9/geometry/test_geometry_r2.py` 与 `reports/V9-G1/r2/`。未改 `lie.py`、`__init__.py`、`test_geometry.py`，未改 r1 任何证据
实际执行：`bash reports/V9-G1/r2/run_all.sh`（11 步，见 §5）；另加 r1 原件消费门复跑（预期 fail，见 §3.4）
验证结果：r1 49/49、r2 新增 43/43 全过；F1/F2 的 G2 最小复现转绿；6 处源码故意改坏 + 2 处登记门故意改坏全部真实变红（8/8，控制 3/3 绿）；r2 重放 references 与 r1 登记 0 字段差异；r1 证据 28/28 条哈希不变
产物：`reports/V9-G1/r2/`（report、metrics、input_registration_r2、section_changes、section_diff、reference-results-r2、脚本、evidence/、SHA256SUMS）
失败与限制：G2 的 F4（超大角 `OverflowError` 泄漏）**不在本卡范围、未修、行为未变**；一般非线性 EKF 全路径确定性界与 NEES 校准仍未验证；测试通过不代表能力通过
交回统筹：是否按 F1/F2/F3 关闭 G2 的 F1/F2/F3 并接受 r2；F4 是否另立小卡；是否将 r2 反例纳入常驻回归（已新增在 `tests/v9/geometry/test_geometry_r2.py`）

## 0. 摘要（30 行内）

1. F1：`belief.covariance(..., semidefinite=True)` 改为**先对称化、再按相对容差**判定 `min(eig) >= -1e-12 * max(1, ||M||_2)`（`PSD_RELATIVE_TOL`，写入 README）；严格正定路径保持原 `> 0` 要求，不受容差放行。
2. F1 正例：G2 的 200/200 拒绝输入——整数 `outer([1,2,2])`（float64 eigmin −5.55e-16）、整数 `JᵀJ`（−1.14e-16）——现在被接受；相对容差在 1e-6…1e12 缩放下结论一致（绝对 1e-12 容差会误拒 1e6/1e12 缩放输入）。
3. F1 反例：`min(eig) = -1e-6*||M||_2` 的真负定、负半正定、非对称、NaN/Inf、错形状仍全部拒绝；严格路径仍拒 `diag(1,1,0)`。
4. F1 位姿图：秩亏 PSD `information` 现在可表达部分约束；`eigh` 后落入 `[-tol*max(1,||M||_2), 0)` 的舍入负特征值**先截为 0 再开方**，不产生 NaN；可观测组合正常求解（SE2 rank4/4、SE3 rank3/3），G2 下游 2 位姿单因子仍 fail-closed 为 `ObservabilityError`；缺锚/断图不可观检查不变。
5. F2：`GravityFrame` 水平参考先拒非有限值与精确零向量，再按归一化后 `|sin θ| < 1e-9` 拒绝（`HORIZONTAL_SIN_TOL`）；错误信息写明同一判据。
6. F2 正例：恰好垂直的 `[scale,0,0]` 在 scale ∈ {1e-20,1e-13,1e-12,1e-9,1e-6,1,1e8} 全部接受，基向量与尺度无关；`|sin θ|=2e-9` 在 1e-20/1/1e8 尺度都接受。
7. F2 反例：平行参考在 1e-20/1/1e8 尺度全部拒绝，`|sin θ|=5e-10` 全部拒绝，零向量报 `nonzero`、NaN/Inf 报 `finite`；原先合法的 up 方向/roll-pitch 拒绝行为不变。
8. F3：r1 登记的两个文档输入旧哈希→当前 published r5 哈希重登记，中间 r4 与 r5 预发布候选只作身份链记录；**文档哈希在 r2 消费门不豁免**，代码输入仍按 r1 哈希强制核对。
9. F3 逐节：`ARCHITECTURE_V9.md` r3→r5 共 26 个小节逐节标注（新增 11、改名 4 含文档标题、其余 15 节均有改动；S0 影响标注：`no_change` 10 / `g1_reference_added` 2 / `outside_g1_scope` 14），`V9_RESEARCH_SURVEY.md` 旧文为新文前缀（§1–§8 未改），仅追加 §9 r4 勘误 13 行；逐节结论：**S0 数学没有变化**。
10. F3 事实链：`ARCHITECTURE_V9` 旧 `ebaf1c4b…`（r3，git `995db72`）→ r4 归档 `e69a0e1c…` → r5 预发布候选 `ea786389…` → 当前 published r5 `0f54a96a…`（git `2de6caef`，`V9-r5-20261016`）；`SURVEY` 旧 `51f6a984…` → 新 `1dc744ea…`。
11. F3 重放：用 r2 消费门（文档按新哈希、代码按 r1 哈希）重放 G1 参考脚本，输出 `references` 与 r1 `reference-results-r1.json` **JSON 0 差异**——数值行为未变，同时证明“重登记后重放链恢复”。
12. r1 原件的消费门仍按原登记核对，复跑真实 `AssertionError: registered source changed: ARCHITECTURE_V9.md`（exit 1）；r1 文件与失败证据原样保留，没有在原地豁免文档哈希。
13. r1 证据冻结：r1 `SHA256SUMS.txt` 的 28 条 evidence 全部 OK；7 条源码快照中只有 r2 声明的 4 个文件（README/belief/gravity/pose_graph）变化，`lie.py`/`__init__.py`/`test_geometry.py` 未变；r1 登记文件哈希不变。
14. 回归：r1 登记的 49 项测试全过（`tests/v9/geometry/test_geometry.py`，49 passed/0 failed）；新增 43 项 r2 测试全过。
15. 故意改坏对照：6 个源码 mutation（F1 零容差/绝对容差/过宽容差、F1 去截断、F2 绝对范数/未归一化）+ 2 个登记门 mutation（文档哈希、代码哈希）全部真实 exit≠0；未改坏 control 3/3 绿（沙盒 import 解析正确 + 测试绿 + 真实登记门绿）。
16. 全部判定用断言与真实非零退出；`run_all.sh` 端到端 exit 0；证据哈希清单在 `reports/V9-G1/r2/SHA256SUMS.txt`。
17. 未做/不声明：G2 F4 未修；一般非线性 SE(2)/SE(3) EKF 全路径确定性界、NEES 统计校准未验证；本卡不构成 S1 科学门或能力晋升。
18. 预算与副作用：纯 CPU；模型调用/训练/下载/安装/付费/提交推送/删除均为 0；mutation 沙盒在 `/tmp/ainerzero-v9g5-r2-<时间戳>/`（每次重跑新建；本次路径见 `evidence/mutation-results-r2.json` 的 `sandbox` 字段，未删）。

## 1. F1：半正定守卫相对容差 + 位姿图特征值截断

### 1.1 实现
- `src/ainerzero/v9/geometry/belief.py`
  - 新增 `PSD_RELATIVE_TOL = 1e-12` 与 `psd_tolerance(matrix) = 1e-12 * max(1, ||matrix||_2)`。
  - `covariance()`：仍先检查形状/有限性/对称性（对称性检查不变，`atol=1e-12`），再对称化；`semidefinite=True` 时 `min(eig) < -psd_tolerance(p)` 才拒绝；严格路径保持 `min(eig) <= 0` 拒绝。
- `src/ainerzero/v9/geometry/pose_graph.py`
  - `information` 经同一守卫后 `eigh`；若存在负特征值，断言其 `>= -psd_tolerance(info)` 后 `np.where(eigenvalue < 0, 0.0, eigenvalue)`，再 `sqrt`。截断只针对容差内的舍入负值，不掩盖真错误（真错误已在守卫拒绝）。
- `src/ainerzero/v9/geometry/README.md` 写明 tol 数值、判据、正例与截断规则。
- 未改其他 G1 接口：`covariance()` 签名不变，`__init__` 导出不变，`lie.py` 未改。

### 1.2 证据
| 项 | 输入 | 结果 |
|---|---|---|
| 正例（G2 输入） | 整数 `outer([1,2,2])`、整数 `JᵀJ` | 接受；`eigmin(float64)` 原型 −5.551e-16 / −1.139e-16 |
| 正例（尺度） | `outer([1,2,2])*{1e6,1e12}` | 接受；绝对 1e-12 容差会拒绝（−3.28e-10 / −4.51e-4） |
| 正例（边界） | `diag(scale, scale, -0.5*tol)`，scale∈{1e-3,1,1e6} | 接受 |
| 反例（边界） | `diag(scale, scale, -2*tol)` | 拒绝（`positive semidefinite`） |
| 反例（真负定） | `diag(1,1,-1e-6)` 等 4 种 | 全部拒绝 |
| 反例（坏输入） | 非对称/NaN/Inf/错形状 | 全部拒绝 |
| 严格路径不变 | `diag(1,1,0)`、`TangentGaussian` | 仍拒绝 |
| 下游正例 | 秩亏 PSD 过程噪声（predict） | 接受且输出协方差仍 SPD |
| 位姿图正例 | SE2 三条整数秩亏 PSD information | 收敛、rank=free=3、残差 3.7e-17 |
| 位姿图正例 | SE3 三条轴秩亏 information（fixed_rotations） | 收敛、rank=free=3 |
| 位姿图正例 | 容差内负特征值 `diag(-5e-13,1,0)` | 无 NaN、收敛、rank=free=4（未截断会 NaN） |
| 位姿图 fail-closed | G2 的 2 位姿单因子；缺锚；断图 | 均 `ObservabilityError`，可解性检查未被绕过 |

对应测试：`tests/v9/geometry/test_geometry_r2.py` 的 `test_f1_*` 与 `test_g2_minimal_reproduction_f1_f2_is_green`。

## 2. F2：重力水平参考改方向判定

### 2.1 实现
`gravity.py`：`GravityFrame.__post_init__` 中
1. 形状/有限性由 `vector()` 先拒（NaN/Inf/错形状 → `ValueError`）；
2. gravity/up 精确零向量 → `ValueError("gravity and up must be nonzero")`；
3. 水平参考精确零向量 → `ValueError("horizontal reference must be nonzero")`；
4. 计算 `sin_θ = ||h − u(u·h)|| / ||h||`，`sin_θ < HORIZONTAL_SIN_TOL (=1e-9)` 才拒绝，错误信息 `horizontal reference must not be parallel to gravity (|sin theta| < 1e-9)`；
5. 归一化、basis 构造与原先一致；合法输入数值逐位不变（basis 与 lift/project 结果不变）。

### 2.2 证据
| 项 | 输入 | 结果 |
|---|---|---|
| 正例（G2 尺度表） | 恰好垂直 `[scale,0,0]`，scale∈{1e-20…1e8} | 全部接受，basis 相同 |
| 正例（小角度） | `|sin θ|=2e-9`，scale∈{1e-20,1,1e8} | 全部接受，归一化方向一致 |
| 反例（平行） | `[0,0,scale]`，scale∈{1e-20,1,1e8} | 全部拒绝（`parallel`） |
| 反例（近平行） | `|sin θ|=5e-10`，scale∈{1e-20,1,1e8} | 全部拒绝（`parallel`） |
| 反例（零/非有限） | `[0,0,0]`、NaN、±Inf、错形状 | 分别 `nonzero` / `finite` 拒绝 |
| 反例（gravity/up） | 零、同向、NaN/Inf | 分别 `nonzero` / `opposite` / `finite` 拒绝 |
| 兼容性 | r1 的 Z-up/Y-up/斜 up 往返、roll/pitch 拒绝 | 仍通过（r1 49 项含这些断言） |

对应测试：`tests/v9/geometry/test_geometry_r2.py` 的 `test_f2_*`。

## 3. F3：输入重登记（旧→新哈希 + 逐节 S0 影响）

### 3.1 旧→新身份链（`reports/V9-G1/r2/input_registration_r2.json`）
| 文档 | r1 登记（旧） | 中间修订（仅记录） | 当前（新，消费门强制） |
|---|---|---|---|
| `ARCHITECTURE_V9.md` | `ebaf1c4b…ac91`（r3 内容；git `995db72`；r1 报告称“当前 r3”） | r4 `e69a0e1c…1dda`（归档 `reports/V9-A1/r5-revision/r4-archive/`）；r5 预发布候选 `ea786389…`（`reports/architecture-finalization-20261016/pre-publication/`） | `0f54a96a…f2a4`（published r5，git `2de6caef`，基线 `V9-r5-20261016`；与 `publication-metrics.json` 一致） |
| `docs/research/V9_RESEARCH_SURVEY.md` | `51f6a984…8b29`（同 git `995db72`） | — | `1dc744ea…f636`（旧文为新文前缀：§1–§8 逐字节未改，仅追加 §9 r4 勘误 13 行） |

代码输入（**仍按 r1 登记哈希强制核对，未重登记、未豁免**）：`src/ainerzero/environments/gridlab2d.py = baea7cb6…`；AWZ `python/animeworld/kernel/motion.py = c21cd8a2…`，两者逐字节一致。

### 3.2 逐节 S0 数学影响（`section_diff_r3_r5.md`，机器可核对的 `section_changes.json`）
- `ARCHITECTURE_V9.md`：26 个小节逐节列出；每节标注 `no_change` / `g1_reference_added` / `outside_g1_scope` 并写说明。要点：
  - §4 数学定义新增“约定”块：右误差 `X=μ·Exp(ξ_r)`、`ξ_l=Ad(μ)ξ_r`、Adjoint **只用于左右误差改写**、显式规范与锚点，并写死“**B2、G3 的实现以 G1 为准**”；式 1/5/6/7 逐字保留，式 2 仅句末标点变化、四条公式片段不变；式 3/4/8/9/10/11/12/13 的改动属学习侧、世界侧、G3 规范化、RLT 与稀疏更新，**不在 G1 范围**。
  - §5 研究顺序的 S0 行新增 D-019 总门与“**G1 已登记的 CPU 容差与 fixture 不改**”、误差界前提与“CPU 工程界不能替代 S1 科学门”——流程措辞，S0 数学不变。
  - 其余改动为 r4/v10 的世界侧、教师、成本、关闭表等，逐节注明与 S0 数学无关。
  - 结论：**S0 数学（G1 已实现的李群/切空间高斯/重力框架/位姿图）公式、容差、接口均无变化**；r5 只是把既有 G1 语义写进架构并指定 G1 为实现权威。
- `V9_RESEARCH_SURVEY.md`：11 个小节，§1–§8 逐字节未改；新增 §9“r4 勘误”（THICK 官方代码、V-JEPA 2.1 论文、通用口径），与 S0 数学无关。

### 3.3 消费门（`verify_registration_r2.py`，exit 0）
- 文档：当前 sha256 必须等于 r2 `new_sha256`，**没有豁免分支**；旧哈希必须能从登记的 git 提交逐字节重建。
- 代码：必须等于 r1 登记哈希（`gridlab2d.py`、AWZ `motion.py`）。
- r1 冻结：r1 登记文件 SHA256 `5aa8199f…` 不变；r1 `SHA256SUMS.txt`（SHA256 `e8007233…`）的 28 条 evidence 全 OK；7 条源码快照中 4 条 r2 允许改动、其余 3 条（`lie.py`/`__init__.py`/`test_geometry.py`）未变。
- 逐节差异与当前文档重新推导的结构逐项一致（标题、行数、changed/renamed/new 标志、S0 标注、旧小节未匹配列表）；“以 G1 为准”等 S0 核对句存在。
- 篡改用例：把文档 `new_sha256` 或代码哈希改坏后消费门真实 exit 1（见 §4 的 m7/m8）。

### 3.4 重放与 r1 原件
- `run_reference_r2.py`（r2 消费门）：文档按新哈希、代码按 r1 哈希核对后重放 G1 参考；`references` 与 r1 `reference-results-r1.json` **JSON 0 字段差异**（`evidence/replay-vs-r1-diff.json`），说明重登记后重放链恢复且 r2 未改登记的数值行为。
- r1 原件 `run_reference.py` **未改**，其消费门仍使用 stale 文档哈希，复跑真实 `AssertionError: registered source changed: ARCHITECTURE_V9.md`（exit 1，日志 `evidence/r1-original-gate-still-fails.log`）；失败证据与 r1 报告保留，没有在原脚本里豁免文档哈希。

## 4. 故意改坏必须变红（`run_mutations_r2.py`，`evidence/mutation-results-r2.json`）

| mutation | 改坏内容 | 期望 | 实际 |
|---|---|---|---|
| control_import_sandbox | 未改坏源码 + 正确 import 解析 | 绿 | exit 0，import 解析到沙盒 |
| control_unmutated_r2_tests | 未改坏副本跑 r2 测试 | 绿 | exit 0，0 failed |
| control_verify_registration | 真实 r2 登记过消费门 | 绿 | exit 0 |
| m1_psd_guard_zero_tolerance | 半正定守卫回退为 `min(eig) < 0` | 红 | exit 1，12 项失败 |
| m2_psd_guard_absolute_tolerance | 容差改成绝对 `1e-12` | 红 | exit 1，2 项失败 |
| m3_psd_guard_loose_relative_tolerance | 相对容差放大到 `1e-3` | 红 | exit 1，4 项失败 |
| m4_pose_graph_no_eigenvalue_clamp | 去掉特征值截断 | 红 | exit 1，4 项失败（NaN 路径） |
| m5_gravity_absolute_norm_guard | 水平参考回退为绝对范数 `<1e-12` | 红 | exit 1，8 项失败 |
| m6_gravity_unnormalized_guard | 去掉 `/||h||` 归一化 | 红 | exit 1，7 项失败 |
| m7_registration_document_hash_tamper | 改坏文档 `new_sha256` | 红 | exit 1（消费门 FAIL） |
| m8_registration_code_hash_tamper | 改坏代码输入哈希 | 红 | exit 1（消费门 FAIL） |

说明：首轮 harness 的 m7 取反哈希写法恰好与原值相同（首位本就是 `0`），导致“未变红”；**这是 harness 缺陷不是门漏**，改为写全 `f*64` 后 m7 真实变红。最终 `mutation-results-r2.json` 为修正后结果，上述 8/8 红、control 3/3 绿。

## 5. 实际命令与退出码（cwd=`/Users/mac/AinerWorkFlow/AinerZero`）

```bash
# 一键（11 步；本报告所有证据都由它重跑生成）
bash reports/V9-G1/r2/run_all.sh                                  # exit 0
# 分步等价命令
PYTHONDONTWRITEBYTECODE=1 .venv-ainerzero/bin/python -B reports/V9-G1/r2/build_r2_registration.py   # exit 0
PYTHONDONTWRITEBYTECODE=1 .venv-ainerzero/bin/python -B reports/V9-G1/r2/verify_registration_r2.py \
  --json-out reports/V9-G1/r2/evidence/registration-verify.json                                     # exit 0
.venv-ainerzero/bin/python -m pytest tests/v9/geometry/test_geometry.py -q -p no:cacheprovider \
  --junitxml=reports/V9-G1/r2/evidence/pytest-r1.xml                                               # exit 0（49 passed）
.venv-ainerzero/bin/python -m pytest tests/v9/geometry/test_geometry_r2.py -q -p no:cacheprovider \
  --junitxml=reports/V9-G1/r2/evidence/pytest-r2.xml                                               # exit 0（43 passed）
PYTHONDONTWRITEBYTECODE=1 .venv-ainerzero/bin/python -B reports/V9-G1/r2/g2_minimal_repro_r2.py \
  --json-out reports/V9-G1/r2/evidence/g2-minimal-repro-r2.json                                     # exit 0（F1/F2 转绿）
PYTHONDONTWRITEBYTECODE=1 .venv-ainerzero/bin/python -B reports/V9-G1/r2/run_reference_r2.py        # exit 0（references 0 差异）
PYTHONDONTWRITEBYTECODE=1 .venv-ainerzero/bin/python -B reports/V9-G1/r2/run_mutations_r2.py        # exit 0（8/8 红）
PYTHONDONTWRITEBYTECODE=1 .venv-ainerzero/bin/python -B reports/V9-G1/r2/build_metrics.py           # exit 0
.venv-ainerzero/bin/ruff check --no-cache src/ainerzero/v9/geometry tests/v9/geometry/test_geometry_r2.py  # exit 0（All checks passed）
PYTHONDONTWRITEBYTECODE=1 .venv-ainerzero/bin/python -B reports/V9-G1/r2/build_shasums.py           # exit 0
# r1 原件消费门（保留的失败证据，预期非零）
PYTHONDONTWRITEBYTECODE=1 .venv-ainerzero/bin/python -B reports/V9-G1/r1-codex-20261016/run_reference.py  # exit 1
```

## 6. 证据清单与身份

| 文件（`reports/V9-G1/r2/`） | 内容 |
|---|---|
| `report.md` | 本报告 |
| `metrics.json` | 指标汇总（由 `build_metrics.py` 从证据 JSON 生成，不手抄） |
| `input_registration_r2.json` | r2 输入重登记（旧→新哈希、代码输入、消费门规则、身份链） |
| `section_changes.json` / `section_diff_r3_r5.md` | 逐节结构差异与 S0 数学影响（机器可核对 + 人类可读） |
| `verify_registration_r2.py` | r2 消费门（文档不豁免、代码强制、r1 冻结、逐节一致） |
| `reference-results-r2.json` | r2 消费门重放的 G1 参考结果（与 r1 references 0 差异） |
| `g2_minimal_repro_r2.py` | G2 最小复现（F1/F2）转绿核对；F4 只报告状态 |
| `run_mutations_r2.py` / `evidence/mutation-*.log` / `evidence/mutation-results-r2.json` | 故意改坏必须变红对照 |
| `evidence/pytest-r1.xml` / `.log`、`pytest-r2.xml` / `.log` | 两套测试的 junit 与日志 |
| `evidence/registration-verify.json`、`replay-r2.log`、`replay-vs-r1-diff.json`、`r1-original-gate-still-fails.log` | 消费门/重放/r1 原件失败复跑证据 |
| `SHA256SUMS.txt` | 本目录全部产物（除自身）的 SHA256 清单，路径相对仓库根 |

源码身份（SHA256）：
`belief.py = 1d1f12d1d379…`、`gravity.py = 150e169a4fe5…`、`pose_graph.py = 6676d3975d52…`、`README.md = e68811950926…`、`test_geometry_r2.py = 624884044454…`；
完整值见 `metrics.json` 的 `source_sha256` 与 `SHA256SUMS.txt`（以文件为准，不在此手抄）。

## 7. 未验证与限制

- **F4 未修**：G2 的 `exp` 超大角 `OverflowError` 泄漏不在本卡范围；本卡未改 `lie.py`，r2 脚本只报告其状态（`SE2.exp(1e103)` 仍 `OverflowError`、`predict(dt=1e300)` 仍 `OverflowError`）。
- 一般非线性 SE(2)/SE(3) EKF 的全路径确定性界、任意噪声分布的统计校准（NEES 覆盖率）未验证，G1 亦未声明。
- 位姿图的 `converged` 仍是绝对步长容差，大尺度坐标需调用方放大 `step_tolerance`（G2 边界备注 1，本卡未改）。
- r1 的 49 项是作者回归测试的重跑，不是新的独立复核；G2 仍需一级验收。
- F3 的“S0 数学无变化”是对 r3→r5 文档的逐节人工判定 + 机器核对句（以 G1 为准、G1 容差/fixture 不改、公式片段保留），不是对 r5 全文的数学证明；r5 其余新增内容属其他阶段，不在本卡复核范围。
- 本卡不构成 S1 科学门、训练授权、能力晋升；不声明 G2 可被自动 close。

## 8. 临时目录与副作用披露

- mutation 沙盒：`/tmp/ainerzero-v9g5-r2-<时间戳>/`（源码副本，未删除；真实源码未被修改；实际路径见 `evidence/mutation-results-r2.json`）。
- 未产生外部模型/数据；`reports/V9-G1/r1-codex-20261016/`、`reports/V-V9-G1/` 未改（r1 28/28 证据哈希已复核）。
- 生成 `src/ainerzero/v9/geometry/__pycache__/` 与 `tests/v9/geometry/__pycache__/`（`.gitignore` 已忽略，源码字节未变）；所有测试/脚本用 `PYTHONDONTWRITEBYTECODE=1` 运行。
- 模型预算预留 = 0、实际 = 0；无训练、无下载、无安装、无付费、无提交/推送、无删除。
