# V9.T38 对抗复核报告：非作者复核 V9.T37（DA3 标定 runner 重写，零运行）

## 0. 顶部摘要（≤30 行）
- **复核结论**：**`accept`（通过 V9.T37）**；但**当前直接申请新配额真跑的风险等级为 `high`**（补齐下方两项跨文件前置修复后降至 `low`）。
- **独立性与红线**：复核者 `gemini-9e5a` ≠ T37 作者 `claude-az`（r2）/ `deepseek-v41f-w3q7`（r1）；全程零模型加载、零真跑；`runs.db` SHA256 `64b668050dfbab7ae1e5b9fe5280f44cecb12643fb820b6a752a6a693723107f`（累计 81 视图 / 1170.0s）与 `m0-worker.lock`（`mtime=1790110663`）分毫不改。
- **核心必答题——下一次真跑还会死在已知的同类问题上吗？**
  1. **不会死在 T35 r2 原崩点或 T37 范围内的数学/协议错误上**：`process_res=280` 在 `InputProcessor` 中对 `280×210`（恰为 `20×14`、`15×14`）零缩放零裁剪，必出 `(N, 210, 280)`；`w2c→c2w` 求逆、锚定残差、样本协方差秩上限、负控必红、非空目录拒写、`--preflight-only`（`rc=6`）全部核验属实且无硬编码假结论。
  2. **但若只修订 T28（Option A）就直接真跑，必死在 T37 文件范围外的同类「未真跑分支」Bug 上**：
     - **[阻断级 #1 · 必崩] `envs/teachers/t6/pipeline.py` 的 `dtype="float16"`（`half_parity` 第 10 次调用）必抛 `RuntimeError`**：`ExplicitPrecisionDA3`（`pipeline.py:268-291`）关闭 `autocast` 并把整网权重 `.to(torch.float16)`，而上游 DA3 的 `DualDPT._add_pos_embed` → `make_sincos_pos_embed`（`head_utils.py:135,140,146` 硬编码 `omega` 为 `float32` 做 `einsum` 并返回 `emb.float()` 喂给 `fp16` `ConvTranspose2d`）以及 `CameraDec.forward`（`cam_dec.py:37-40` 调 `self.fc_t(feat.float())` 乘 `fp16` `Linear` 权重）均要求 `fp32` 权重/算子。此前 `test_r2.py:172` 靠 mock 模型、T33 跳过 `half_parity`、T35 r2 死在 `fp32` 第 1 关、T37 用纯 NumPy `FakeTeacher`，导致该必崩路径从未被真跑触达。
     - **[阻断级 #2 · 空跑烧配额] `da3_worker.py:204` 硬门控 `if views == 18:` 与修订提案 `--views 56` 冲突**：若用户按 `AMENDMENT_PROPOSAL.md` 批准前向视图口径 `--views 56` 而未同步改 `da3_worker.py:204`，`teacher-da3 --mode run --views 56` 会在 `RunStore` 预扣 56 视图后跳过标定、做 0 次前向并以 `rc=0, status="completed"` 退出。
  3. **剩余经验风险（非崩溃类）**：修复上述两项后，CPU/MPS/fp16 数值一致性门槛（`1e-3/1e-3`、`1e-2/1e-2`，尤其焦距 `~245 px` 与 `expp1` 置信度 `[1.0, 7.0]`）在真实 ViT+DualDPT 上尚无实测样本；即使超差，T37 runner 也会保留全部 `safetensors` 与 `ev.json` 并以 `EXIT_STAGE_FAILED=2` 诚实报 `failed`，不会静默放宽或半途丢证据。
- **测试与变异核验**：全套 DA3 CPU 测试 `48 passed`；回退 r1 立即失败（无 math 模块 `rc=2`；保留 math 回退 runner 为 `4 failed, 13 errors`）；T37 原 10 项变异 **10/10 拦截**；本卡新增 8 项对抗变异 **5/8 拦截、3/8 存活**（暴露测试断言盲区：`parity` 退化为仅测 `depth`、`holdout` 漏入 `fit` 协方差、协方差分母 `N` 替代 `N-1`，详见 §4）。

---

## 1. 复核身份、文件与账本 SHA256 核对

- **任务 ID**：`ainerzero.V9.T38`（复核 `ainerzero.V9.T37`）
- **复核 Agent**：`gemini-9e5a`（Tier 2，独立于 `claude-az` 与 `deepseek-v41f-w3q7`）
- **电源与环境**：AC Power（100%），macOS CPU-only 只读核验，未导入/实例化任何 PyTorch/DA3/MLX 模型。

### 1.1 被复核源码、协议与证据身份（全部与 `reports/V9-T37/evidence/SHA.txt` 一致）

| 文件 | SHA256 | 核验状态 |
|---|---|---|
| `src/ainerzero/v9/teachers/da3_calibration_math.py` | `4c99e60a33b60dc6f7a98d4ddfa0078b15f5ed0ab831e976a97954f160d66996` | 一致 |
| `src/ainerzero/v9/teachers/da3_calibration_runner.py` | `9efdf59f5c2d17853b3103394b532f37d2b403284f01b42a1b435107cf569b86` | 一致 |
| `src/ainerzero/v9/teachers/da3_worker.py` | `20201f34487e52e4f05c02a080bb355748902ad962a421a21b2decc468ba8bb7` | 一致 |
| `tests/test_da3_calibration_runner.py` | `f66c8e0f80964446537b2cd968737328290cc166865e0b8b06c4e29a0870bd19` | 一致 |
| `tests/test_teacher_da3_controlled.py` | `781f0b23805be1b8d379050047a7335e18357620b27fa798332f7d411c568db0` | 一致 |
| `tests/test_da3_supervision.py` | `79be9a1e3e6abbc9e0670de8595f204e664b5f275c6ed04474e55fb1a9a803ef` | 一致 |
| `reports/V9-T28/proposal.json`（冻结预登记） | `7b775b49b6c76d508190be54de3c69473f29a8f5e6e07f1ec73056262a9cf284` | 未改 |
| `data/v9/t6_calibration/manifest.json`（冻结真值） | `0a40213d96c36630428430b27c7138b21496cf37558062a5b6fc993a845d05a7` | 未改 |
| `envs/teachers/t6/statistical_protocol.json` | `5910b94a017b09d1249b94083a2417b24015326458aa685c879dd20b4c14e9f5` | 未改 |
| `artifacts/v9/teachers/benchmark/runs.db`（前/后） | `64b668050dfbab7ae1e5b9fe5280f44cecb12643fb820b6a752a6a693723107f` | 未改（`mtime_ns=1793088879453767951`） |
| `artifacts/locks/m0-worker.lock`（前/后） | `mtime_ns=1790110663379635830`（`1790110663`） | 未触碰 |

本地权重纯 CPU 文件哈希核验（调用 `envs/teachers/t6/pipeline.py::inspect_weights`，`models_loaded=0`）：
- `DA3-SMALL`：`config.json` `a486e29e...`（1202 B）、`model.safetensors` `364492e3...`（137,248,940 B）—— 通过。
- `DA3-BASE`：`config.json` `5e34115e...`（1205 B）、`model.safetensors` `e01067dc...`（541,518,028 B）—— 通过。

---

## 2. 独立复算 World-0 真实 DA3 输出（`t6-analytic-room-00`）

脱离 `da3_calibration_math.py`，直接读取 `reports/V9-T35/predictions/da3_small/t6-analytic-room-00/seq.safetensors` 与 `data/v9/t6_calibration/t6-analytic-room-00_view_{00,01,02}.npz` 独立编写几何与深度核验脚本复算：

### 2.1 原始张量属性与参考系发现
- `depth`: `shape=(3, 378, 504), dtype=float32, min=0.305331, max=1.496570, median=0.974339`（无量纲相对深度，相对真值米制深度约差 `6.85×`）。
- `confidence`: `shape=(3, 378, 504), dtype=float32, min=1.000685, max=6.977242, median=2.241409`（对应 `DualDPT` 的 `conf_activation="expp1"`，即 $1 + e^x > 1$）。
- `camera_pose`: `shape=(3, 3, 4), dtype=float32`（`candidate.json` 明载 `"extrinsics": "world_to_camera"`）。各视图外参距 `[I | 0]` 的 Frobenius 距离分别为：
  - `view 0`: `0.066430`，**`view 1`: `0.000539`**，`view 2`: `0.063885`。
  - **关键观察**：上游 DA3 的 `select_reference_view(..., strategy="saddle_balanced")` 在 world 0 上实际把**中间帧 `view 1`**（而非 `view 0`）选为了内部近似原点参考系！T37 的 `anchored_residual` 以 `view 0` 锚定后仍消除了这一参考系偏移。
- `intrinsics`: `view 0` 在 `504×378` 下预测 `fx=438.015, fy=439.124, cx=252.0, cy=189.0`；真值 `K` 按 `504/280=1.8` 折算为 `fx=396.0, fy=396.0, cx=251.1, cy=188.1`（无内参条件化时 DA3 FOV 头高估焦距约 `+10.6%`）。

### 2.2 逐视图深度指标与 T28 7 维锚定残差独立复算结果

- **不缩放直接送入 `anchored_residual`**：立即抛出 `ValueError: paired depth shapes must agree (view 0: pred (378, 504) vs gt (210, 280)); resampling is not allowed`（确认禁止静默重采样生效）。
- **离线仅诊断缩放至 `210×280` 后的逐视图自拟合（`s_i = median(gt_i) / median(pred_i)`）**：

| 视图 | Bilinear `abs_rel` | Bilinear `delta1` | Bicubic `abs_rel` | Bicubic `delta1` | 与统筹抽查参考值对比 |
|---|---:|---:|---:|---:|---|
| `view 0` | **`0.092604`** | **`0.999252`** | `0.092726` | `0.999286` | 精确吻合 `0.0926` / `0.9993` |
| `view 1` | **`0.090442`** | **`0.996871`** | `0.090602` | `0.996939` | 精确吻合 `0.0904` / `0.9969` |
| `view 2` | **`0.090454`** | **`0.994932`** | `0.090575` | `0.994779` | 精确吻合 `0.0905` / `0.9949` |

- **T28 跨视图锚定 7 维残差（`view 0` 定旋转/原点与深度尺度 `s_depth=6.849622`，`view 2` 定平移基线尺度，`view 1` 计分）**：

| 外参约定 | `rotation_deg` | `translation_residual_norm` | `residual_7d` (`[rx, ry, rz, tx, ty, tz, log_d]`) | `depth_abs_rel` (anchor-scaled) |
|---|---:|---:|---|---:|
| **正确：`invert_w2c(camera_pose)` → `c2w`** | **`0.9812°`** (`0.0171 rad`) | **`0.083037`** | `[+0.005587, -0.016141, -0.001245, -0.036323, +0.033076, +0.066946, -0.018013]` | `0.092350` (`δ1=0.997347`) |
| **错误（r1）：把 `w2c` 直接当 `c2w`** | **`5.4407°`** (`0.0950 rad`) | **`1.046644`** | `[-0.005320, -0.094436, -0.008402, +1.041287, -0.030755, -0.101188, -0.018013]` | `0.092350` (`δ1=0.997347`) |

独立复算与 `da3_calibration_math.py::anchored_residual` 逐分量误差 `< 1e-6`，完全证实 D2（r1 未求逆 `w2c` 导致 `tx ≈ +1.041`、平移残差范数 `1.047`）及 T37 修复的数学正确性。

---

## 3. 上游 DA3 内参条件化死锁（D8）与 `da3_worker.py`（D9/D10）核查

### 3.1 D8 全路径源码核查（确认不存在任何绕过 `extrinsics` 单独传 `intrinsics` 的旁路）
逐文件核查 `envs/teachers/t6/Depth-Anything-3/src/depth_anything_3/` 与 `envs/teachers/t6/pipeline.py`：
1. **`model/da3.py:126`**：`cam_token = self.cam_enc(extrinsics, intrinsics, image.shape[-2:]) if extrinsics is not None else None` —— 当 `extrinsics=None`（T28 `known_poses: false`）时，`cam_enc` 根本不调用，`intrinsics` 在前向中被完全丢弃。
2. **`model/cam_enc.py:33,58,70`**：`CameraEnc` 的输入层是 `nn.Linear(9, dim_out // 2)`，其 9 维向量由 `[T(3), quat(4), fov_h, fov_w]` 拼接而成且第 58 行先算 `c2w = affine_inverse(ext)`；预训练权重在架构层面就不存在「只喂内参不喂位姿」的 token 编码器（若传单位阵伪造外参则直接违反 `known_poses: false` 并污染多视图相对位姿）。
3. **`model/da3.py:141,181`（`use_ray_pose` / `_process_ray_pose_estimation`）**：从 `ray` 头输出反解预测位姿与预测内参，不接收输入 `intrinsics`。
4. **`model/da3.py:145,238`（`_process_gs_head`）**：函数签名虽有 `intrinsics`，函数体内完全未引用（实际读 `output.get("intrinsics")`），且 `da3-small`/`da3-base` 的 `gs_head` 未启用。
5. **`api.py:350`（`_align_to_input_extrinsics_intrinsics`）**：首行 `if extrinsics is None: return extrinsics, intrinsics, ...` 直接返回。
6. **`envs/teachers/t6/pipeline.py:306`（`DA3GeometryTeacher.process_keyframes`）**：签名 `(self, frames, *, timestamps=None, world_id="unknown", process_res=504)` 甚至不接收 `intrinsics` 参数。

**D8 结论**：T28 冻结条款 `known_poses: false + known_intrinsics: true + intrinsics_adverse(must turn red)` 对真实 DA3 在架构上确系死锁；T37 用 `RealTeacherFactory.supports_intrinsics_conditioning = False` 在 `preflight()`（零模型加载、零账本消耗）抛出 `ProtocolUnsatisfiable`（`EXIT_UNSATISFIABLE = 6`）并提交 `AMENDMENT_PROPOSAL.md`（推荐 Option A），处置完全诚实、合规。

### 3.2 `da3_worker.py` D9 / D10 核查
- **D9**：`da3_worker.py:209` 默认运行目录已改为时间戳隔离目录 `reports/V9-T6/calibration-runs/<UTC_stamp>-<pid>/`（`calibration-evidence.json` + `predictions/`），彻底脱离已交付的 `reports/V9-T35/`。
- **D10**：
  - `views == 18 and allow_model_execution` 时调用 `da3_calibration_runner.py`，若 `returncode != 0` 原样向上传递非零退出码并设 `status="failed"`。
  - `views != 18`（如 `views == 2` 受控 CPU 测试）时返回 `returncode=0`，但报告显式写入 `model_runs=0, real_forward_executed=False, calibration_executed=False`（不再写 r1 的假通过字段）。
  - **发现的跨文件交互陷阱**：见 §5.2（若修订后改用 `--views 56`，`views == 18` 硬判断会导致空跑返回 `0` 并白扣 56 视图配额！）。

---

## 4. 回退验证与对抗变异测试（T37 原 10 项 + T38 新增 8 项）

所有回退与变异均在仓库外临时目录 `/var/folders/.../T/v9_t38_sbx_*` 中执行并即时清理，仓库零改动。

### 4.1 现行测试套件与 `--preflight-only` 实测
- 执行：`PYTHONPATH=src pytest -q tests/test_da3_calibration_runner.py tests/test_da3_supervision.py tests/test_teacher_da3_controlled.py tests/test_da3_views_82.py`
  - 结果：**`48 passed in 73.65s`**。
- 执行：`python3 src/ainerzero/v9/teachers/da3_calibration_runner.py --preflight-only --output /tmp/t38_pf_nonexistent/ev.json --predictions-dir /tmp/t38_pf_nonexistent/preds`
  - 结果：`rc=6`，stderr 输出 `PROTOCOL UNSATISFIABLE (no model work done): RealTeacherFactory cannot condition predictions on intrinsics...`，且未创建 `/tmp/t38_pf_nonexistent`。

### 4.2 回退 r1 验证（`tests_fail_when_fix_reverted = true`）
1. **完整回退至 r1**（用 `reports/V9-T37/evidence/da3_calibration_runner.r1-original.py` 替换 runner 并移除新增的 `da3_calibration_math.py`）：`pytest` 收集阶段直接失败（`rc=2`，`FileNotFoundError: da3_calibration_math.py`）。
2. **保留 `da3_calibration_math.py` + `da3_worker.py`，仅将 `da3_calibration_runner.py` 回退为 `r1-original.py`**：`pytest` 返回 `rc=1`（**`4 failed, 13 errors, 6 passed`**；仅 6 个纯数学/上游静态测试通过，涉及 runner 的 17 个用例全部失败或因缺 `load_plan`/`preflight` 报错；且 `r1-original.py` 顶层直接 `import torch`，T37 已消除顶层重依赖）。

### 4.3 变异测试矩阵（10/10 原变异拦截 + 5/8 新增对抗变异拦截 + 3 处测试盲区定位）

- **复跑 T37 原 10 项变异（`T37-A`..`T37-J`）**：**10 / 10 全部被拦截**（与 `reports/V9-T37/evidence/mutation-results.txt` 完全一致）。
- **T38 独立设计的 8 项新增对抗变异（`NEW-1`..`NEW-8`）**：

| 变异编号 | 目标文件与注入故障 | 结果 | 失败测试数 / 说明 |
|---|---|---|---|
| `NEW-1` | `da3_calibration_math.py`: `log_so3(rg.T @ rp)` 漏转置改为 `log_so3(rg @ rp)` | **拦截** | 4 failed (`test_w2c_must_be_inverted_before_use`, `test_residual_invariant_to_pose_frame_and_scale` 等) |
| `NEW-2` | `da3_calibration_runner.py`: 切换 device/dtype 时漏调 `self.factory.release(t.teacher)`（违反驻留模型上限=1） | **拦截** | 1 failed (`test_full_run_with_capable_teacher_follows_t28...` 捕获 `f.max_live > 1`) |
| `NEW-3` | `da3_calibration_runner.py`: `frame_order_adverse` 把真值视图也跟着按 `(2,1,0)` 倒序（负控伪装失效） | **拦截** | 3 failed (`test_adverse_control_that_does_not_turn_red_is_a_failure_not_a_pass` 等) |
| `NEW-4` | `da3_worker.py`: 默认输出目录回退为 `reports/V9-T35/predictions`（覆盖旧证据） | **拦截** | 1 failed (`test_default_output_dirs_must_not_be_the_delivered_t35_folder`) |
| `NEW-7` | `da3_calibration_math.py`: `parity_compare` 漏乘参考值幅值 `atol + rtol` 替代 `atol + rtol * np.abs(a)` | **拦截** | 3 failed (`test_parity_rule_is_elementwise_with_reference_scaled_rtol` 等) |
| **`NEW-5`** | `da3_calibration_runner.py`: `_Run.run_variant` 把 `plan.parity_fields` 改回 `('depth',)`（重现 r1 D5 只比 depth 漏掉 `confidence`/`extrinsics`/`intrinsics`） | **存活（盲区）** | 0 failed —— `FakeFactory(..., cpu_eps=0.05)` 只扰动了 `depth`，没有用例在 runner 层扰动另外 3 个张量 |
| **`NEW-6`** | `da3_calibration_runner.py`: 把 `holdout_worlds` 也 append 进 `fit` 协方差（违反 T28 `data_leakage_prohibition`） | **存活（盲区）** | 0 failed —— `test_da3_calibration_runner.py:281` 写成 `cal["fit"]["rank"] == cal["fit"]["rank_ceiling"] == 2 or cal["fit"]["rank"] <= 2`（4 个 fit world 的 `rank_ceiling` 实为 3，因 `FakeTeacher` 残差秩 ≤ 2 被 `or` 短路，且未断言 `cal["fit"]["n_samples"] == 4`） |
| **`NEW-8`** | `da3_calibration_math.py`: `fit_statistics` 样本协方差除以 `N` 而非无偏 `N - 1` | **存活（盲区）** | 0 failed —— 单测只断言了矩阵秩与 `[7, 7]` 形状，未核对 `np.cov(..., ddof=1)` 数值 |

> 注：`NEW-5`、`NEW-6`、`NEW-8` 对应的 T37 **生产代码实现本身均正确**（分别是 `plan.parity_fields`、`fit if w in plan.fit_worlds else hold`、`/ (x.shape[0] - 1)`），不会导致真跑出错，但建议统筹后续顺手补强这 3 条测试断言。

---

## 5. `FakeTeacher` 拟真度审计与下一次真跑生死研判

### 5.1 `FakeTeacher` vs 真实 `DA3GeometryTeacher` 对比（`fake_teacher_realistic = false`）

| 维度 | 真实 `DA3GeometryTeacher`（`envs/teachers/t6/pipeline.py` + 上游 DA3） | T37 `FakeTeacher`（`tests/test_da3_calibration_runner.py`） | 影响评估 |
|---|---|---|---|
| `process_keyframes` 参数签名 | **不接收 `intrinsics` 参数**（传入即 `TypeError`） | 接收 `intrinsics=None` | Option A（`known_intrinsics=False`）下 `RealTeacherFactory` 不传 `intrinsics` 故安全；但若未来打开 `known_intrinsics=True` 而不改 `pipeline.py` 会直接 `TypeError` |
| `dtype="float16"` 行为 | **`ExplicitPrecisionDA3` 关 `autocast` + 整网 `.to(fp16)` → 在 `DualDPT`/`CameraDec` 必抛 `RuntimeError`** | 纯 NumPy 加高斯/常数扰动，从不触发 PyTorch dtype 校验 | **致命盲区**：直接掩盖了真跑第 10 次调用 `half_parity` 的必崩异常 |
| `confidence` 值域分布 | `expp1` 激活，实测 `[1.0007, 6.9772]`（中位数 `2.24`） | 常数 `0.9` | 真实置信度幅值高 `2.5–7.7×`，影响绝对/相对容差敏感度 |
| 世界参考系选择 | `saddle_balanced` 按内容动态选帧作近似原点（world 0 选了 `view 1`） | 固定全局变换 `(Q, t0, s)` | `anchored_residual` 对全局 `Sim(3)` 不变，数学结论不受影响 |
| 预测内参 `K` 与返回字典键 | FOV 解码（`cx=W/2, cy=H/2`，world 0 焦距偏大 `+10.6%`），且含 `cache_key`/`key_material` | 直接回填缩放后真值 `K`，不含 `cache_key` 等缓存元数据 | T37 runner 自存 `prediction.safetensors`，不依赖 `cache_key` |

### 5.2 下一次真跑还会死在已知的同类问题上吗？（逐项依据与剩余风险）

**结论：在修掉下方 #1 和 #2 之前，下一次真跑【一定会死】在已知的同类「未真跑验证路径」问题上（风险 `high`）；修掉 #1 和 #2 并落地 T28 Option A 修订后，不再存在已知工程必死点（风险降至 `low`，仅剩诚实科学实测风险）。**

1. **【必死点 #1 · 必须修】`envs/teachers/t6/pipeline.py` 的 `dtype="float16"` 精度包装缺陷**
   - **依据**：`pipeline.py:268-291` 中 `ExplicitPrecisionDA3.forward` 使用 `with torch.autocast(device_type=image.device.type, enabled=False): return self.model(...)`，并在 `pipeline.py:291` 执行 `model.to(device=self.device_choice, dtype=torch.float16)`。而上游 DA3 源码存在两处硬编码 `float32` 算子：
     - **崩点 1A**：`da3-small` 与 `da3-base` 均配置 `DualDPT`（默认 `pos_embed=True`，`dualdpt.py:54,225`）。`_add_pos_embed` 传入 `dtype=x.dtype`（`float16`）生成网格，随后 `model/utils/head_utils.py:135,140` 用硬编码 `dtype=torch.float32` 构造 `omega` 并执行 `torch.einsum("m,d->md", pos, omega)`（`Half` 与 `Float` 在 `autocast(enabled=False)` 下直接 `RuntimeError`）；且第 146 行 `return emb.float()` 会把 `x + pe` 升成 `float32`，紧接着送入权重为 `float16` 的 `ConvTranspose2d`（`dualdpt.py:173`）再次触发 dtype 冲突。
     - **崩点 1B**：`model/cam_dec.py:37,39,40` 显式调用 `self.fc_t(feat.float())`、`self.fc_qvec(feat.float())`、`self.fc_fov(feat.float())`；当 `fc_*` 的 `nn.Linear` 权重被 `pipeline.py:291` 转成 `float16` 且 `autocast` 被禁用时，必抛 `RuntimeError: mat1 and mat2 must have the same dtype, but got Float and Half`。
   - **后果**：若直接真跑，前 9 次 `float32` 调用（MPS + CPU）跑完后，第 10 次调用 `DA3-SMALL/half_parity` 必抛 `RuntimeError`，runner 以 `EXIT_ERROR=1, status="failed"` 终止，白白烧掉新申请的 RunStore 配额。
   - **修复方向（供统筹在下一张实现卡决策）**：遵循上游 DA3 的原生半精度语义（保持模型权重为 `float32`，在 `half_parity` 下启用 `torch.autocast(device_type=..., dtype=torch.float16, enabled=True)`，让上游 `da3.py:139` 的内部 `autocast(enabled=False)` 正常保护 `DualDPT` 与 `CameraDec` 的 `fp32` 头），并在 `envs/teachers/t6/tests/` 用未 mock 的真实最小网络结构或真实算子契约测试验证（注意变更 `pipeline.py` 会改变 `pipeline_code_sha256` 缓存键，需在申请真跑前一次性改完冻住）。

2. **【必死/空跑点 #2 · 必须对齐】`da3_worker.py:204` 的 `views == 18` 硬门控 vs 配额视图口径**
   - **依据**：`da3_worker.py:204` 写有 `if views == 18 and args.allow_model_execution:`；而 `AMENDMENT_PROPOSAL.md:48-49` 提请用户二选一批准「数据集视图 18」或「前向视图 56」。若用户选 `--views 56` 而未同步更新 `da3_worker.py:204`（及 `da3_controlled.py` 默认权重检查 `--model da3-all`），CLI 会先在 `runs.db` 扣掉 56 视图，随后跳过真跑直接报 `rc=0`（`real_forward_executed=False`）。同时必须在 `teacher-da3 --mode run` 之前先跑 `da3_calibration_runner.py --preflight-only`（因 `execute_guarded_da3_benchmark` 在启动 worker 前即扣减 `RunStore` 预算）。

3. **【已彻底排除的旧崩点】输入输出分辨率与几何约定**
   - 核查 `utils/io/input_processor.py:233-242,324-334,365-383`：`280×210` 图像在 `process_res=280` 下满足 `max(280,210)==280` 且 `280=20×14, 210=15×14`（`PATCH_SIZE=14` 整数倍），`InputProcessor` 零缩放零裁剪，`DualDPT` 必输出精确 `(N, 210, 280)` 深度与置信度，绝不会再发生 `(378, 504)` vs `(210, 280)` 崩溃。

4. **【剩余诚实经验风险（非崩溃）】数值一致性容差（`cpu_parity` `1e-3/1e-3`、`half_parity` `1e-2/1e-2`）与 Option A 预测内参偏差记录**
   - 真实 DA3 的 `exp` 深度头、`expp1` 置信度头与 RoPE 注意力在 MPS vs CPU / fp16 vs fp32 下是否存在个别像素超出 `atol + rtol * |ref|`，在零运行约束下无法先验打包票；但 T37 已确保即便超差也会完整跑完所有阶段、落盘全部 `safetensors` 与 `ev.json` 并以 `EXIT_STAGE_FAILED=2` 诚实退出（属于有效实验结论，而非程序崩溃）。
   - 另外，`AMENDMENT_PROPOSAL.md` Option A 第 3 条提出将预测 `K` 与真值 `K` 的偏差作为描述性字段记录；当前 `da3_calibration_runner.py:313` 已将预测 `intrinsics` 存入 `prediction.safetensors` 并纳入 `parity` 对比，若修订版 `proposal.json` 要求在 `calibration-evidence.json` 的 `per_world` 中显式输出 `K` 偏差摘要，需在落地 Option A 时一并补入。

---

## 6. 给一级统筹的验收与排期建议

1. **验收 `ainerzero.V9.T37`（`accept`）**：T37 在其授权文件范围内完整、诚实地修复了 D1–D11，消除了所有未测先报的硬编码字段，补齐了 `rc=6` 零模型预检与 23 项快速 CPU 单测，且严守零运行红线。
2. **在向用户申请新真跑配额前，先派一张轻量前置修复卡（零真跑）一次性收口**：
   - 修复 `envs/teachers/t6/pipeline.py` 的 `float16` `autocast`/权重 dtype 冲突；
   - 对齐用户选定的 T28 修订版 `proposal.json`（Option A）与 `da3_worker.py:204` 的 `views` 门控（`18` vs `56`）及 `--model da3-all` 预检；
   - 顺手补上 §4.3 检出的 3 条测试断言盲区（`NEW-5` 四字段 parity、`NEW-6` `fit.n_samples == 4` 防泄漏、`NEW-8` `ddof=1` 协方差数值）。
3. 完成上述收口并通过 `--preflight-only`（`rc=0`）后，再执行唯一一次真跑。
