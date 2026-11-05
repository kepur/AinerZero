# T39 · T28 r2 独立数学复核

复核人：`deepseek-v41f-t3k9`（DeepSeek-V4.1-Flash，二级执行层）
与 r1 的关系：**与 r1 无任何关系**。不是 r1 作者（codex），不是 r1 复核人（gemini-kzer），不是 r2 作者（claude-az），不是 T37/T38/T35 的任何执行者。
结论：**accept-with-required-changes**（可以成为下一次真跑的预登记依据，但登记 SHA 之前必须改掉下面 4 处；改动全部是文本/元数据，不触碰任何残差、阈值、预算算术或输入）。

零模型、零前向、零下载、零付费。只读 r1/r2/T37/T6 与 DA3 源码，未改任何既有文件，未触碰 `m0-worker.lock` 与 `runs.db`，未改 `da3_calibration_runner.py`。本目录是本任务唯一写入点。

---

## 0. 一句话结论

r2 的核心修订（`known_intrinsics=false` + 移除内参逆向控制 + 预算 20/56）**前提成立、算术正确、数学上自洽**，我独立复核通过。
但我找到 **4 处必须改**：2 处 r1 残留表述（`execution_prerequisites[1]` 仍写 T29；`review_task` 被置成 `null`）、
1 处**机器字段层面的预算不可满足**（`cumulative_wall_seconds_max=1200`，而按 T37 自己记录已预留 1170 s）、
1 处描述性 K 块的**口径陷阱**（预测 K 的主点根本不是模型估计出来的，而是写死的 `W/2,H/2`，与真值恒差 0.5 px）。
另外我给出一条**高概率过不了的门**：`cpu_parity` / `half_parity` 是"全元素逐点最大值"门，而 DA3 在 `cam_token=None` 下走**离散 argmin 选参考视角 + 重排**，这个分支一旦在 CPU/MPS 或 fp32/fp16 间翻转，容差多少都救不回来。

---

## 1. r1→r2 差异：自算并逐条对照

自写脚本 `own_diff`（不导入 `build_proposal_r2.py` / `check_r2.py`），按解析后的结构递归比对。

- r1 `proposal.json` = `af3131a51bf93ff12b43c08b4ca564124c1b1542cf9f9e196316cfa6e391cb4a` ✅
- r1 `PROTOCOL.md` = `b8d903c03e414dfb9e88bdbc6ff23aa492eca8466534cfeb9b7415cd3b2102ad` ✅（**r1 未被改写**）
- r2 `proposal.json` = `0e15033a8b55c978f3f97318e5d1978e54b406afe8d28120aebd40a8e0db9db1` ✅ 与 `proposal.sha256` / `SHA256SUMS.txt` / AMENDMENT 一致

我按叶子路径得到 **38 条**差异；作者 `diff_r1_r2.json` 声明 **27 条**路径。差别不是分歧，是**粒度**：作者把 `budget.models[i].stages` 整个列表、`claims_forbidden`、`execution_prerequisites` 各算一条，我把列表内部的元素位移展开成了多条（移除 `intrinsics_adverse` 后 `stages[3..5]` 整体前移一位）。

**逐条对照结果：我的 38 条叶子差异全部可归入作者的 27 条路径之下；作者声明的 27 条路径也全部对应真实变化（无幽灵条目）。`unlisted_differences = []`。**

一处值得记录的**清除**（不是缺陷）：`generator_sha256` 与 r1 相同（`f97d723f…`），初看像残留。核对后确认它指的是 **fixture 生成器**（同一个 sha 出现在 `reports/V9-T6/r2-calib-fixtures/manifest.json` 与 `statistical_plan`/`fixture-generation.log` 里），不是 proposal 构建脚本；输入未变，所以该字段**应当**不变。r1 的 `build_proposal.py` 是 `7f2e72fc…`，r2 的 `build_proposal_r2.py` 是 `cbbff93f…`，两者都与该字段无关。

`PROTOCOL.md` 的 r1→r2 diff 只落在预期段落：标题/头部 SHA、§固定输入、§pipeline 段、§精度一致性的 reference、§负对照段（移除错K）、S 判据里的"错K→帧序"、预算表（删一行、合计 11/31→10/28、22/62→20/56）、卸载段（四阶段→三阶段）、末节整体改写。§依据与缺口、§位姿残差与深度残差、§统计量三段**逐字节未变**。

---

## 2. 推翻前提的机会：DA3 在没有外参时是否忽略内参

**结论：前提成立（`premise_confirmed = true`）。在 `extrinsics=None, infer_gs=False, use_ray_pose=False` 下，不存在任何让输入内参影响 depth / extrinsics / intrinsics / confidence 的路径。**

我读了全部相关文件，自己列出的 `intrinsics` 消费点（不是抄作者的 2 条）：

| # | 位置 | 输入内参的用途 | 在 r2 的实际调用下是否可达 |
|---|---|---|---|
| 1 | `model/da3.py:126-130` | `if extrinsics is not None: cam_token = self.cam_enc(extrinsics, intrinsics, ...)` else `cam_token=None` | **唯一真实入口**，`extrinsics=None` ⇒ 不可达 |
| 2 | `model/cam_enc.py:69-76` → `model/utils/transform.py:19-38` | `extri_intri_to_pose_encoding` 用 `intrinsics[...,1,1]`/`[...,0,0]` 算 `fov_h`/`fov_w` | 只被 #1 调用，不可达 |
| 3 | `model/da3.py:146` → `_process_gs_head(..., extrinsics, intrinsics)` | **该函数的 `intrinsics` 形参从未被读取**（函数体只用 `output.intrinsics`，即预测 K） | 双重不可达：`infer_gs=False`，且即便为 True 也不用 |
| 4 | `api.py:196-198 / 285-291` → `InputProcessor` | `ixts_list=None`；`_resize_ixt/_crop_ixt(None)` 原样返回 None | 不可达（`intrinsics=None`） |
| 5 | `api.py:319-323` | `in_t = None` | 不可达 |
| 6 | `api.py:341-351` `_align_to_input_extrinsics_intrinsics` | `if extrinsics is None: return prediction` — 连"把输入 K 写回预测"都不做 | **不可达，且这正是预测 K 得以保留的原因** |
| 7 | `model/da3.py:211-228` `_process_camera_estimation` | 只用 `cam_dec(feats)` → `pose_encoding_to_extri_intri`，纯预测 | 走这条（`use_ray_pose=False`） |
| 8 | `model/da3.py:181-203` `_process_ray_pose_estimation` | 只用 `output.ray/ray_conf` | 不适用（`use_ray_pose=False`） |
| 9 | `model/da3.py:374-383` `_apply_metric_scaling` | 用 `output.intrinsics`（**预测** K） | 属于 `NestedDepthAnything3Net`；`da3-small.yaml` 的 `__object__` 是 `DepthAnything3Net`，不走这里 |
| 10 | `model/dinov2/vision_transformer.py:314-331` | `cam_token=None` 时走参考视角选择，`x[:,:,0]=cam_token` 用学习到的 `camera_token` | 不使用输入 K |
| 11 | `utils/io/output_processor.py:120-133` | 读 `model_output["intrinsics"]`（预测） | 不使用输入 K |

调用链确认：`pipeline.py:335` 是 `self.model.inference(frames, process_res=process_res, export_format='mini_npz')`——**没有** `extrinsics`/`intrinsics`/`infer_gs`/`use_ray_pose` 任何参数，全部取默认值。`pipeline.py:264-280` 的 `ExplicitPrecisionDA3.forward` 只是把 `None` 原样透传。`da3-small.yaml`/`da3-base.yaml` 的 `__object__.name` 都是 `DepthAnything3Net`（`da3.py:40`，`forward` 在 100 行），不是嵌套版。

**所以 r2 的前提不是"作者说了两处"，而是"全仓只有一处真实入口，而那一处被 `extrinsics is not None` 挡住，其余六处要么读预测 K、要么形参未被使用"。r1 的内参逆向控制在构造上不可能变红，这个判断成立。**

附带发现（对第 5 节有用）：`pose_encoding_to_extri_intri` 里 `cx = W/2`、`cy = H/2` 是**写死的**（`transform.py:61-62`），只有 `fx, fy` 从 pose encoding 的 fov 通道解出。也就是说"模型自估内参"实际上是**两个自由度的焦距**，主点完全没被估计。

---

## 3. 修订的数学后果

### 3a. 三项残差是否仍良定、量纲与口径是否不变 —— 是，且**比作者说的更强**

关键在于：**三项残差的定义里没有 K**。

- 旋转残差 `Log(Rrel_gt_1^T Rrel_pred_1)` 只依赖 `(R_gt, R_pred)`；
- 平移残差 `(s·u_pred_1 − u_gt_1)/b_gt` 只依赖 `(R_gt, c_gt, c_pred)`；
- 深度残差 `mean log(s_depth·D_pred_1/D_gt_1)` 只依赖 `(D_gt, D_pred)`。

r2 改的是**喂给模型什么**，不是**怎么算残差**。因此映射 `(预测, 真值) → 残差` 逐字未变，量纲（rad / 无量纲 / 无量纲对数比）与口径（锚帧 0 定原点、view2 定尺度、view1 唯一评分）也不变。`alignment`、`residual_vector.order`、`estimation` 三个块在我的检查里与 r1 严格相等。

### 3b. 自估 K 与真值 K 不一致如何进入这三项 —— 分两种情形，结论差别很大

设 `α = fx_pred/fx_gt`，模型预测的三维点为 `P_pred(p) = D_pred(p)·K_pred^{-1}p̃`。

**情形一：模型内部自洽（预测的 K、位姿、深度描述同一个三维重建，差一个相似变换 σR）。**
则 `σR·P_gt = P_pred` 逐像素成立。取 z 分量即得 `D_pred = σ·Z_gt`，**与 α 无关**（因为 K 只影响 x/z、y/z 的比值，不影响 z）。于是深度残差恒为 `log σ`，被 `s_depth`（锚帧中位比）精确吸收；旋转残差与平移残差同理只差一个相似规范，被锚帧原点 + view2 尺度精确吸收。
**在这种情况下，K 误差对 7 维残差的影响严格为零。** 这不是"吸收一部分"，而是**精确的规范不变性**：错误的内参在自洽模型里**就是一个规范重参数化**。
这是 r2 的数学比它自己写的更强的地方：AMENDMENT 说"相对量能吸收一部分，但不能吸收全部"——在自洽极限下是**全部**。

**情形二：模型内部不自洽（K 变了但深度/位姿不跟着变）。**
此时 `P_pred = σ·diag(1/α, 1/α, 1)·P_gt`，是一个**各向异性（横向）拉伸**，不是相似变换。逐项后果：

| 分量 | 是否受影响 | 机制 |
|---|---|---|
| 深度残差（z 型，`depth_units: metres_camera_z`） | **不受影响** | z 分量没被拉伸；`s_depth` 只吸收整体尺度 |
| 旋转残差 | **不受影响** | K 不进入旋转 |
| 平移残差 | **受影响** | `u_pred` 的横向分量被乘 `1/α`，方向随之改变；共线但带横向分量的基线上表现为 `~|u|·(1/α−1)·横向占比` |

所以**唯一可能的系统性偏差通道是平移残差的横向尺度**，且它是**共模**的（同一个模型、同一分辨率 ⇒ 同一个 α，对 6 个世界同号同量级）。

**这会不会让"fit 均值 + 协方差"失去意义？不会，但会改变均值与协方差的含义：**
- 共模偏移只进均值，不进（去均值的）协方差 ⇒ 协方差会**低估**总离散度。而 r2 已经禁止把该协方差当噪声模型（`sensor_noise_registration_allowed=false`、`full_covariance_rank_ceiling=2`、`regularization=none`、`nees=null`），所以**没有新的损失**。
- 真正被这条改变的是**均值能不能被读成"纯几何误差"**：不能。它可能含一个由"K 与深度不自洽"产生的共模量。r2 目前没写这一句，建议补一行（见 required change #4）。

### 3c. 秩上限 2 / 不求逆 / 不正则 —— 仍然成立，且**没必要改**

`n_fit_worlds = 3`、`dimension = 7` ⇒ 去中心矩阵是 3×7，`rank ≤ min(3−1, 7) = 2`。6×6 位姿子块是它的子矩阵，秩 ≤ 2。**这个上界只依赖 (n, d)，与数据怎么生成、模型喂不喂 K 完全无关。** r2 没有改 `n_fit_worlds`、没有改 `dimension`、没有改 `sample_covariance` 的分母 `(3−1)`（我已逐项断言与 r1 相等），所以结论原样成立。同理"不求逆"仍然**必要**：rank 2 < 7 ⇒ 矩阵必然奇异，任何求逆/伪逆都会给出任意解。

---

## 4. 剩下的唯一真实前向控制（帧序逆序）在原理上是否可满足

### 4.1 我自建的模型（不是 DA3）

按 r2 的精确残差定义实现（`S = ‖rotvec‖ + ‖(s·u_pred−u_gt)/b_gt‖ + AbsRel`，`s_depth` 用锚帧中位比，`b_gt=‖u_gt_2‖`），在 6 个真实 fixture 世界（真 GT 位姿 + 真 GT 深度）上跑 4 类合成 teacher：

| teacher | 定义 | S_clean | S_bad（逆序） | 判据 `S_bad ≥ S_clean+max(1e-4,0.1S_clean)` | 变红世界数 |
|---|---|---|---|---|---|
| T1 oracle 位姿感知（无噪声） | 槽位 i 的输出 = 该槽位图像所属真实相机的位姿/深度 | 0.000000 | **1.1095** | 需 ≥ 0.0001 | **6/6** |
| T1b oracle 位姿感知（有界噪声） | 同上 + 每视角刚体扰动 + 深度尺度扰动 | 0.1521 | **1.1815** | 需 ≥ 0.1674 | **6/6** |
| T2 先验主导 / 置换不变 | 无论槽位里是哪张图，永远输出同一组规范位姿与同一深度场 | 0.0642 | 0.0642 | 需 ≥ 0.0706 | **0/6** |
| T3 位姿固定 + 槽位内深度 | 位姿不随图像变；深度只取决于本槽位那张图（**完全不做跨视角/时序推理**） | 0.0555 | 0.0555–0.0562 | 需 ≥ 0.0610 | **0/6** |

**回答"是否必然"：不是。**
- 对**位姿感知**的 teacher：**满足，而且余量极大**。S_bad ≈ 1.11 vs 门槛 1e-4，余量约 1.1×10⁴ 倍；带噪声时余量仍约 7 倍。构造上不需要模型"理解时序"，只需要它**每个槽位的输出跟着该槽位的图像内容走**。
- 对**顺序不敏感**的 teacher：**不必然不增加，也不必然增加**。T1 本身就是"顺序不敏感"的（每个槽位的输出只取决于本槽位图像，没有任何跨视角推理），它照样变红。原因是判据的变红**不来自时序推理，而来自协议自身的槽位对齐**：逆序把锚槽（slot 0）和尺度槽（slot 2）换成了别的物理相机，而 GT 标签仍是 [0,1,2]。
  T3 只增加 0.0002–0.0009（不足 10% 门槛），说明"顺序不敏感"只在**位姿也不随图像变**时才会不红。

### 4.2 共线几何下有没有逆序后 S 不变的退化情形

有精确的充要条件，而且**被协议自己的守卫排除**：

- 旋转项在逆序后为 0 ⟺ `R0 = R2`；
- 平移项在逆序后为 0 ⟺ `c0 = c2`；
- 两者同时成立 ⇒ `b_gt = ‖c2 − c0‖ = 0` ⇒ 命中 `alignment.gt_baseline_min_metres = 1e-6` 的拒绝分支，**不会进入统计**。

数值验证（合成刚体）：

| 构造 | 结果 |
|---|---|
| A：`R0=R2` 且 `c0=c2` | `gt-baseline-reject`（协议拒绝，不产生 S） |
| B：`R0=R2=I`、共线等距 `c0=0, c1=.35x, c2=.7x` | 旋转项 **0.000°**，平移项 **1.0000** ⇒ S=1.0，**仍然变红** |
| D：`R0≠R2` 但 `c0=c2` | `gt-baseline-reject` |

**所以：只有旋转项可能退化，而旋转项单独退化时平移项仍给出 S≈1.0。不存在通过基线守卫的精确退化构型。** 真实 fixture 也不接近退化：6 个世界全部**严格共线**（`sin(angle) ~ 1e-15`）、**严格等距**（0.35 / 0.70 m）、`R0` 与 `R2` 相差 **6.35–6.36°**，`R0 ≠ R2`。

### 4.3 但有一个必须写进报告的限制：**深度通道对这条控制几乎不起作用**

T1 无噪声时，逆序的 `absrel = 0.0000`。原因：`s_depth = median(D_gt_0 / D_pred_0)`，而逆序后 `D_pred_0` 恰好是 view2 的深度，中位比 ≈ 1，于是 `mean log(s_depth·D_gt_1/D_gt_1) ≈ 0`。**整体尺度被 `s_depth` 精确吸收，深度通道只对"形状"变化有反应，对"关联被换掉"这件事没有反应。** 变红完全由旋转项（6.36°）和平移项（1.0）贡献。

⇒ 这条控制实质上是**"帧-标签关联逆序（含锚/尺度槽互换）"**控制，不是"时序敏感性"控制。见第 7 节的过头声称。

---

## 5. 描述性"预测 K vs 真值 K"块

**隔离性：成立。** `profile.intrinsics_policy` 明确 `conditioning: none`，且写明该对比"descriptive only, not part of the 7-vector, the score, the fit statistics or any threshold"。我在检查器里逐项断言：`residual_vector.dimension == 7`、`order` 与 r1 相等、`negative_controls.score` 里没有 K、`estimation` 块与 r1 严格相等。**该块确实没有进入 7 维向量、评分、fit 统计或任何阈值。**

**"同一分辨率下比较"是否良定：良定，但有一个口径陷阱。**

用 `envs/teachers/.venv-t6/bin/python`（CPU、**不加载任何模型**、只 import `utils.io.input_processor`）自测：

- `t6-analytic-room-00` 的 view-0/1/2，源图 210×280，`process_res=280` ⇒ 处理后张量 `(1, 3, 210, 280)`，**逐帧 `(3, 210, 280)`，无任何缩放/裁剪**；
- 顺带把 GT K 一起传进去，输出 K 与输入 K **逐位相同**（`allclose(atol=0)`）⇒ 预处理不改 K。

**陷阱：** 真值 K 是 `fx=fy=220.0, cx=139.5, cy=104.5`（像素中心约定 `(W−1)/2, (H−1)/2`），而 DA3 的预测 K 里 `cx = W/2 = 140.0`、`cy = H/2 = 105.0` 是**写死的**（`transform.py:61-62`），并且**不参与任何学习**。所以：
- 描述性对比里的 `cx, cy` 偏移**恒为 +0.5 px**，这是**约定差，不是模型误差**；
- 预测 K 实际只有 **2 个自由度**（fx, fy），"模型自估内参"这个说法在数学上应理解为"模型自估焦距"。

如果不把这层写清，将来把 `+0.5 px` 读成"DA3 主点估计偏差 0.5 像素"就是一次干净的误读。

---

## 6. 预算算术

从 `budget.models[*].stages` 自算（两种口径都算，互相校验）：

| variant | 声明 calls/views | Σcalls | Σ(calls×frames_per_call) | Σ(calls×len(views)) | 阶段数 |
|---|---:|---:|---:|---:|---:|
| DA3-SMALL | 10 / 28 | 10 | 28 | 28 | 5 |
| DA3-BASE | 10 / 28 | 10 | 28 | 28 | 5 |
| 合计 | 20 / 56 | 20 | 56 | 56 | — |

`reserve_before_model_import_views = 64`，`unallocated_views = 64 − 56 = 8` ✅ 与声明一致。

**与 T37 runner 一致：** `da3_calibration_runner.py:142` 取 `calls_per_variant = models[0]["forward_calls"]`、`views_per_variant = models[0]["forward_views"]`（即 10 / 28），`runner:353` 断言 `(acc.calls, acc.views) == (10, 28)`。按 runner 的阶段派发（first_frame 1/1、calibration 6×3、frame_order 1×3、cpu_parity 1×3、half_parity 1×3）累计正好 10 次 / 28 视图。**一致。**
（旁注，属 T38 范围：runner 只读 `models[0]` 就套用到两个型号，隐含假设两型号预算相同。r2 恰好相同，所以不触发；但这是个静默假设。）

**`budget.view_accounting` 是 OPEN：确认。** `status = "OPEN_pending_user_decision"`，note 明确"账本按数据集视图 18 还是前向视图 56 记账是用户尚未做的决定，登记前必须重述"。`open_items[0]` 覆盖它。按任务要求，我**不因此 reject**，只确认它被明确标为未决且 `open_items` 覆盖完整。

**但 `open_items` 不完整的一处：** `budget.cumulative_wall_seconds_max` 仍是 **1200**，而 `reports/V9-T37/AMENDMENT_PROPOSAL.md` 明写"累计墙钟上限 1200 s 已预留 1170 s …新一次真跑至少需要上限 ≥ 1230 s"。`open_items[1]` 只在**散文里**提到"cumulative reserved wall already 1170/1200"，**机器字段本身仍是那个装不下这次运行的数字**。见 required change #3。

---

## 7. 找遗漏：残留的 r1 表述与过头声称

### 7.1 残留（确认 2 处）

1. **`execution_prerequisites[1]` = `"T29 independent math review and lead immutable SHA registration"`** —— T29 是 **r1 的**复核卡，r2 的复核卡是 T39。这是"活字段"里的 r1 残留，`amendment.changes` 里的 `E1 identity/supersedes/author/review_task` 声称改过这一族字段，实际漏了这一条。
2. **`review_task` = `null`** —— r1 里是 `"ainerzero.V9.T29"`，r2 把它置空而不是指向 T39。这与 `E1` 自称的"改了 review_task"**自相矛盾**，并且切断了"这个 SHA 由哪张卡把关"的追溯链。

### 7.2 已核对并**排除**的疑似残留（避免误报）

- `generator_sha256` 与 r1 相同 → 是 fixture 生成器，**应当**不变（见 §1）。
- `PROTOCOL.md:3` "r1 当时是 T29" → 刻意的历史说明，不是残留。
- `PROTOCOL.md:13` "不称已知 K 条件化"、`:45` "r1 的错K负对照已移除"、`:68` "11 次/31 视图 → 10 次/28 视图，合计 62 → 56" → 全是否定句或历史对照，正确。
- `claims_forbidden` 仍含 `"blind intrinsic recovery"` → 仍然该禁，正确。
- `negative_controls.score` / `required_red` / `frames` / `boundary_rejection` / `unrelated_error` → 与 r1 严格相等，未偷改。

### 7.3 过头声称（3 处）

1. **"帧序负对照"这个名字过头。** 如 §4.3，变红由锚/尺度槽互换驱动，深度通道被 `s_depth` 吸收，`T1`（完全不做时序推理）也能变红，`T3`（同样不做时序推理但位姿固定）不红。**一个红结果证明的是"每槽输出跟着本槽图像走"，不是"模型对时间顺序敏感"。** 建议改称"帧-标签关联逆序对照（含锚/尺度槽互换）"，并在 PROTOCOL 里写明"该对照不检验时序敏感性"。
2. **"模型自估内参条件下"这句话过头。** 预测 K 是 pose-encoding 里 fov 通道的**读回值**，不是前向的**条件输入**；深度头是独立分支，从不用 K。而且主点是写死的。更准确的说法是"**未提供任何内参或外参条件下；模型自行输出一组焦距，该输出仅作描述性读回**"。现写法容易被读成"模型用自己估的 K 去算深度"，那不是这版 DA3 的行为。
3. **描述性 K 块里的 "ratios/offsets to the ground-truth K" 过头。** `cx, cy` 的 offset 恒为 `+0.5 px`，是像素中心约定差（GT 用 `(W−1)/2`，DA3 用 `W/2`），不是模型能力。报告里必须标注这一点，否则将来一定会被读成模型误差。

---

## 8. 自建对抗用例（6 个，全部实跑）

检查器 `own_check_r2.py` 的判据**全部来自 r1 与用户批准的选项 A**，**不把 `diff_r1_r2.json` 当真值来源**（这是关键：作者的自证脚本一旦被改，用它的输出做真值就失效）。

| # | 构造 | 期望 | 实测 | 抓到它的检查 |
|---|---|---|---|---|
| A1 | 放宽 `numerical_parity` 容差（1e-3→1e-1，两处）+ `required_red` 的 0.1→0.01 + `known_intrinsics` 改回 `true` | 抓到 | ✅ rc=1 | C3（5 条未列出差异）、C5（required_red / 4 个容差）、C7（known_intrinsics 非 false）、C4（幽灵条目） |
| A2 | 偷改 `negative_controls.frames` 的 GT 标签关联，**并把它从 `diff_r1_r2.json` 里删掉**，让 diff 看起来只改了批准范围 | 抓到 | ✅ rc=1 | C3（未列出差异 `negative_controls.frames`）+ C5（frames 变了） |
| A3 | 在 `amendment.unchanged_by_construction` 声称未改的 `alignment.pose_translation` 里去掉 `s·`，**并从 diff 删掉 `/alignment`** | 抓到 | ✅ rc=1 | C3 + C5（alignment 声称未改但变了） |
| A4 | 预算算术篡改：某阶段 `calls` +1，合计不动 | 抓到 | ✅ rc=1 | C6（声明 10/28 ≠ 自算 11/31；合计 21/59；unallocated 算术不符） |
| A5 | 语义等价的"假变更"：顶层键顺序反转 + `0.001` 写成 `0.0010` | **不误报** | ✅ 零 C3/C5/C6 告警（rc=1 仅因继承了 §7.1 的两处真实缺陷） | — |
| A6 | 只修 §7.1 两处（`review_task→T39`、去掉活字段里的 T29） | **通过** | ✅ rc=0 PASS | — |

A5/A6 合起来证明：检查器**不误报语义等价改写**，且**唯一的阻塞项就是那两处文本缺陷**，修完即绿。

---

## 9. 回答三个问题

### Q1：r2 能否作为下一次真跑的预登记依据？

**能，条件是 accept-with-required-changes。** 下列 4 项在登记 SHA 之前必须改完（全部是文本/元数据，**不触碰残差定义、阈值、预算算术、输入 SHA**，所以不需要再走一轮数学复核，只需一级核对 diff 后再登记）：

| # | 必须改 | 理由 | 严重度 |
|---|---|---|---|
| 1 | `execution_prerequisites[1]` 的 `T29` → `T39` | r1 复核卡残留，切断追溯链 | 必须 |
| 2 | `review_task` 由 `null` → `"ainerzero.V9.T39"` | 与 `amendment.changes` 的 `E1` 自相矛盾；无卡可追 | 必须 |
| 3 | `budget.cumulative_wall_seconds_max`：或改成足够的值，或在字段旁显式标注"该上限将在用户批准配额时上调（当前已用 1170/1200）" | 现值 1200 在算术上装不下这次运行（需 ≥1230）；现在只有散文 `open_items[1]` 提到，机器字段本身仍是错的 | **必须**（这条最可能再烧一次授权） |
| 4 | `PROTOCOL.md` 补三句：(a) 该对照检验的是关联而非时序；(b) 自洽极限下残差对 K 严格不变，不自洽时只有平移残差横向共模；(c) 预测 K 的主点是写死的 `W/2,H/2`，与 GT 恒差 0.5 px 属约定差 | 消除 §7.3 的三处过头声称 | 建议（不阻塞登记，但强烈建议同批改） |

改完后重新算 `proposal.json` 的 SHA 并由一级登记。**注意：改完 SHA 会变，`proposal.sha256` / `SHA256SUMS.txt` / AMENDMENT 里的 `0e15033a…` 都要同步。**

### Q2：在 r2 下，真实 DA3 上还有哪些"按构造或高概率过不了"的门？

按风险从高到低：

**(1) `cpu_parity` / `half_parity` —— 结构性风险，最高。**
`cam_token=None` 时，backbone 在 `alt_start-1` 层调用 `select_reference_view(x, 'saddle_balanced')`（`vision_transformer.py:314-321`），这是对 3 个视角的 **`balance_score.argmin(dim=1)`**——一个**离散 argmax/argmin**，然后 `reorder_by_reference` 重排、末尾 `restore_original_order`（`:344-345`）还原。而 `THRESH_FOR_REF_SELECTION = 3`，本次正好 **S=3，恰好卡在阈值上**，所以这个分支**一定会走**。
`balance_score` 是三个"距 0.5 的距离"之和，每个分量都由 3 个值做 min-max 归一化得到 ⇒ 结构上极易接近平局。**一旦 CPU 与 MPS（或 fp32 与 fp16）在 argmin 上翻到不同视角，输出就是整段置换，逐元素门会以 O(1) 的量级失败——`atol/rtol` 给多大都救不回来。**
这不是容差问题，是**离散分支的不可约风险**。建议：在 `--preflight-only` 阶段把 `b_idx` 打进证据（3 个视角的 `balance_score`），真跑时对 `cpu_parity`/`half_parity` 额外记录 `b_idx`；若翻车，正确的修法是"记录并显式失败"，不是放宽容差。

**(2) `half_parity` 的 fp16 数值 —— 高概率偏紧。**
适配器 `ExplicitPrecisionDA3` **主动关掉了 autocast**（`torch.autocast(..., enabled=False)`）并把输入 `image.to(dtype=float16)`，等于把 **LayerNorm / softmax / `torch.quantile` / `torch.linalg.inv` 全部压到 fp16**，而不是上游默认的"fp16 矩阵乘 + fp32 归约"。
- fp16 单位舍入 `u = 2^-11 ≈ 4.88e-4`；ViT-S(12 block) + DPT 的最长数值路径约 10²–10³ 次顺序浮点运算，误差按 `u·√L·放大因子` 累积，放大因子（LayerNorm/softmax 的 Jacobian）常为 1–10；
- 门的判据是**全元素逐点最大值**，元素数 ≈ `3×210×280×2 + 48 + 27 ≈ 353k`。`max` over 353k 元素 ≈ 4.5σ（若近似高斯）。要 `max < atol+rtol·|ref| ≈ 1e-2 + 1e-2·|ref|`，就要求单元素 σ ≲ 2e-3 相对。**fp16 深层 ViT 的典型单元素 σ 就在 1e-3–1e-2，`max` 落在 1e-2 上下 ⇒ 这是个五五开的门，不是稳过的门。**
- 另外两个具体隐患：`_process_mono_sky_estimation` 里的 `torch.quantile(sampled_depth, 0.99)`（若 head 输出含 `sky`）在 MPS 上对 fp16 支持有限；LayerNorm 的 `eps=1e-6` 在 fp16 下**下溢为 0**，低方差通道有除零风险。

**(3) `cpu_parity` 的 fp32 —— 中等偏紧。**
同精度、不同后端（Accelerate vs Metal），差异来自归约顺序与算子实现，典型单元素相对差 1e-5–1e-4；`max` over 353k 元素 ≈ 4.5σ ⇒ 约 1e-4–5e-4。`rtol=1e-3` 有约 2–10 倍余量，**大概率能过，但不宽裕**。真正会把它推过去的是 (1) 里的置换翻转和任何隐式 CPU fallback。

**(4) `first_frame` 单帧前向 —— 需要确认 `b_idx` 行为。**
`S=1 < THRESH_FOR_REF_SELECTION=3` ⇒ 不走参考视角选择，走 `cam_token=None` 的固定 token 路径。这一路**没有**离散分支，反而是最稳的一步。但它和 calibration（S=3，走选择）**不是同一条计算图**，所以 first_frame 的耗时/峰值不能外推到 3 帧阶段——协议里已经这么写了，正确。

**(5) 帧序逆序控制 —— 低风险，但不是零。**
见 §4：位姿感知 teacher 余量约 1.1×10⁴ 倍。风险只在于"DA3 的位姿头是否被先验主导"。若真实 DA3 在 0.35 m 基线上输出接近规范的轨迹（T2 型），S_bad ≈ S_clean 就会不红。r2 已经诚实地把它标为"经验结果、不红即失败"，这一点我认可。

**(6) 已确认的 runner 缺陷（T38 范围，不是 r2 的问题）：**
`da3_calibration_runner.py:131` 无条件解析 `p["negative_controls"]["intrinsics"]` ⇒ 读 r2 会 `KeyError`。r2 的 PROTOCOL 已披露，我复核确认。**在 runner 修好之前，`--preflight-only` 对 r2 根本跑不起来**，所以 `execution_prerequisites[6]`（preflight 必须先过）目前是不可满足的——不是 r2 的错，但它是登记后到真跑之间的硬阻塞，必须和 T38 一起排。

### Q3：噪声候选的**声称范围**还有哪句话说得过头？

一句：**"测的是模型自估内参条件下的相对位姿与相对深度"**（`PROTOCOL.md:13`、`profile.assumption`）。
它读起来像"内参是这条 profile 的一个条件维度"，但事实上：内参**不是输入**、深度头**从不读它**、主点**根本没被估计**、而且在自洽极限下残差对 K **严格不变**。所以这条 profile 真正测的是"**在不给任何相机参数的条件下，DA3 的相对位姿与相对深度的几何误差**"，自估内参只是同一前向的**附带读回值**，不是"条件"。
建议改成："未向 teacher 提供任何内参或外参；teacher 自行输出一组焦距，该输出仅作描述性读回，不构成条件化，也不进入任何统计量。"

次要一句：**"唯一真实前向控制"**这个提法本身没错（确实只剩它一个真实前向），但配合"帧序"这个名字会让人以为它覆盖了时序敏感性。见 §7.3 第 1 条。

---

## 10. 红线遵守

只读；未加载任何模型（`.venv-t6` 只用于 `InputProcessor` 的 CPU 预处理与 numpy/scipy 几何计算）；未触碰 `m0-worker.lock` 与 `artifacts/v9/teachers/benchmark/runs.db`；未改 r1/r2 任何文件（r1 两个 SHA 复核前后一致）；未改 `da3_calibration_runner.py`；未推送、未下载、未付费。写入点仅 `reports/V9-T28-r2-review/` 与临时工作目录 `.tmp/t39-review/`（脚本与中间产物）。
