# ainerzero.V9.P47 执行报告
角色：executor；负责人：composer-a7k2；时间：2026-10-28
任务状态：reported；实验状态：未执行（零运行审计）
任务依据：ainerzero.V9.P47 L2 零运行审计；参数 v0；不授权训练/MLX/下载/改冻结值
输入身份：只读核查 `src/ainerzero/v9/experiments/s1/{prereg,arms,data,awz_export}.py`、`src/ainerzero/v9/geometry/canonical.py`、`artifacts/v9/s1/phase1/r13/pre_registration.json`、`reports/V9-S1-r14-budget-proposal.md`、`reports/frontier-integration-20261027/{REPORT,DESIGN_CORE}.md`；AWZ `sensing/{noise,config,exit}.py` 只读
修改文件：仅 `reports/V9-P47/`（本报告与 `metrics.json`）
实际执行：静态对照；未跑 MLX / train / eval / verify
验证结果：六项均有 file:line 证据；**建议在 r14 冻结前修正表述**
产物：`reports/V9-P47/REPORT.md`、`reports/V9-P47/metrics.json`
失败与限制：未改 `prereg.py`（超出文件范围）；未接入 G3；未复跑任何实验
交回统筹：抄送 S1 主责 claude-az；G1 主责见 COORDINATION 10-26 节（codex）。r14 预算数字可不变，但 `effective_metadata.equivariant_source` 应在冻结前改表述。

## 摘要（≤30 行）

预登记写「G3 估计位姿＋协方差注入误差」，实现是自写 yaw 积分＋日志 ego_motion（含 AWZ 传感器高斯噪声），**不是** `canonical.canonicalize` / `inject_pose_error`。建议 r14 冻结前**改表述**，不要为对齐描述去接 G3（会改 source identity，超出本卡）。

---

## 1. 规范化用的位姿估计来自哪里？是否 G3 canonicalize？

**结论：否。不是 G3 canonicalize。**

| 证据 | 内容 |
|---|---|
| `prereg.py:393-394` | `equivariant_source` 写 “analytic normalisation (G3 estimated pose + covariance-injected error)…” |
| `arms.py:30` | 只 `from . import data, spec`；**无** `ainerzero.v9.geometry` / `canonical` |
| `arms.py:15-16` | 模块说明自称 “G3-style estimated pose”，但是固定自写代码 |
| `arms.py:320-338` | `motion_from_residual`：logged action + 有界 residual；`integrate_pose`：yaw 积分 |
| `arms.py:126-163`、`496-497` | `MetricMapMemory.warp` 用估计 motion 重采样网格（臂 2/4） |
| `canonical.py:460-481`、`537-540` | G3 真正的 `canonicalize` / `inject_pose_error` 在 geometry 包；S1 包内 **零引用** |

位姿信念从零起积：`arms.py:353` / `:421-424` `pose = np.zeros(...)`，每步用 `actions`（数据里的 ego_motion）加 `0.05 * tanh(residual)`，再 warp 记忆。这是解析积分，**不是** `CanonicalBelief` + `g(mu_hat)^-1 · x`。

---

## 2. “协方差注入误差”是否在 S1 数据/运行路径实现？来源与量级

**结论：G3 意义下的协方差注入（`inject_pose_error` 从 Σ 采样）未实现。**  
存在的是 **AWZ 出口对观测通道的高斯传感器噪声**，在数据生成时写入 packet，不是训练时对估计位姿的协方差注入。

| 证据 | 内容 |
|---|---|
| `canonical.py:537-540` | `inject_pose_error(belief, rng)`：从 belief Σ 采样并扰动均值 —— S1 **未调用** |
| `awz_export.py:47-49` | 源绑定含 `sensing/noise.py`；经 `emit_stream` 生成 |
| `AnimeWorldZero/.../sensing/noise.py:19-76` | `CounterNoise` + `add_gaussian` |
| `AnimeWorldZero/.../sensing/config.py:76-80` | `NOISE_SPEC`：`ego_motion` σ_m=0.005、σ_deg=0.25；`relative_objects` 0.02 m / 0.5°；`pose_sensor` 0.03 m / 0.5° |
| `AnimeWorldZero/.../sensing/exit.py:642-655` | ego_motion 通道加噪 |
| 实装 packet（datasets 样例） | channels = `relative_objects` + `ego_motion`；`sensor_noise` 与上表一致；**无** `pose_sensor` 通道进学生流 |
| `arms.py:320-325` | 运行路径另有 **有界学习残差**（0.05 / 2° 量级），不是 Σ 采样 |

因此：把 AWZ 观测噪声说成 “covariance-injected error（G3）” 会混淆两层机制。

---

## 3. 真值位姿规范化有没有在任何计分路径上被使用？

**结论：真值从不进入模型前向/训练；计分时真值用作对齐锚点与误差对照，不是“真值规范化观测”的 upper-bound 臂。**

| 证据 | 内容 |
|---|---|
| `data.py:10-14`、`575-576` | 训练只读 packets；不读 truth |
| `arms.py:394-396` | “no truth pose is ever supplied” |
| `evaluation.py:23-29` | `align_relative_pose`：窗口起点真值作 **frame 对齐**；“truth is never an input to the model” |
| `evaluation.py:153-155`、`metrics.py:490-491` | 对齐后与真值比 localization_error |
| `spec.py:408-410` | 指标定义：estimate vs evaluator truth |

预登记后半句 “truth-pose normalisation is upper-bound diagnostic only and is never scored”：**未找到**单独的「真值规范化」诊断路径；真值用于 **计分对照/对齐**，与该句字面不完全一致。半句里 “never scored” 若指“真值不进模型输入”则成立；若指“真值不参与任何计分”则 **不成立**（localization 就是对真值计分）。

---

## 4. r13 冻结件与 r14 申请是否沿用同一表述？

**结论：r13 冻结件字面相同；r14 预算申请未改该科学表述，并显式等待本审计。**

| 证据 | 内容 |
|---|---|
| `artifacts/v9/s1/phase1/r13/pre_registration.json` → `effective_metadata.equivariant_source` | 与 `prereg.py:393-394` **同一字符串** |
| 同目录 `draft_preregistration.json` | 同句 |
| `reports/V9-S1-r14-budget-proposal.md:91-96` | 补注：P47 若判不一致，**冻结前先改表述或最小实现**；预算数字可不变 |

`build_draft()` 会把该字符串写进下一份预登记；若不改 `prereg.py`，r14 冻结会再次锁死同一错误表述。

---

## 5. 哪些第一阶段结论依赖这条表述？

| 依赖点 | 说明 |
|---|---|
| 预登记科学身份 | 任何声称“等变来源＝G3＋协方差注入”的 phase-1 文档/冻结件（r1–r13 同源句） |
| `reports/frontier-integration-20261027/REPORT.md:120` | 已标出不一致，并要求 r14 前核清 |
| 同报告 raw/ground 笔记 | 指出 arms 无 G1/G3、无协方差误差注入 |
| r14 冻结内容 | 预算申请已挂钩：表述修正会改变待冻 JSON 的 metadata（**不**必然改 updates/deadline 等数值） |
| 能力解读 | 若把 arm2/4 的 grid warp 解读成“已接 G3 等变算子”，会被该表述误导；实际是自写 SE(2)-like yaw warp |

数值门槛、updates=3510、deadline=1200 s 等 **不**依赖这句英文；依赖的是对 **机制身份** 的宣称。

---

## 6. 建议的最小修正（不得改冻结数值）

**建议：r14 冻结前改表述（优先），不要为对齐文案去接线 G3。**

推荐替换文案（草案，供一级定稿）：

> `analytic ego-motion integration (logged AWZ ego_motion with sensor Gaussian noise + bounded learned residual); metric-map warp by that estimate; not G3 CanonicalBelief/inject_pose_error; truth pose is evaluator-only (alignment/scoring), never a model input`

| 选项 | 评价 |
|---|---|
| **A. 改 `prereg.py` `effective_metadata.equivariant_source` 后重出 r14 draft/freeze** | **最小且正确**；不改 updates/deadline/资源；会改 document SHA（预期内） |
| B. 最小实现：S1 调用 G3 `canonicalize`/`inject_pose_error` | 改 `arms.py` + source_identity；科学行为变化；需另卡与批准；**非本审计最小解** |
| C. 冻结时原样照抄 | **不建议**；会把已知错误锁进 r14 |

**是否建议在 r14 冻结前修正：是（选项 A）。**

---

## 验收核对

1. 位姿来源 ≠ G3 canonicalize — 有证据  
2. 协方差注入（G3）未实现；AWZ 观测噪声有来源与量级 — 有证据  
3. 真值不进模型；计分用真值对齐/对照，无“真值规范化诊断臂” — 有证据  
4. r13 同句；r14 申请等待修正 — 有证据  
5. 依赖项列出 — 有  
6. 最小修正 = 改表述 — 有；**建议冻结前修正**

抄送：S1 主责 claude-az；COORDINATION G1 主责 codex（知悉即可）。
