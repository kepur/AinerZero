# ainerzero.V9.T46 差异复核报告：T28 r2 删除 half_parity（E15）

**结论：`accept_with_changes`。E15 这一处改动本身干净、可机器验证、没有夹带；必须改的只有 `PROTOCOL.md` 的 3 处措辞（不触及 `proposal.json`，因此一级要登记的机器文件 SHA 仍是 `86f5ece6…`，改完即可登记）。**

- 复核人：`deepseek-q7m2`
- 与被复核方的关系：我不是 `claude-az`，也不是它的同会话别名；不是 r2 作者、不是 T37/T40 作者、不是 T35 r2 执行者；也不是 T39 的复核人（`deepseek-v41f-t3k9`）。与 r2 作者无任何共同会话。本会话此前做过 `V9.B12`/`V9.T44`（`v9/interfaces` 与 `da3_controlled`/`da3_worker`），与 T28 无关。
- 对象：`reports/V9-T28/r2/proposal.json` SHA `86f5ece6d5127fedbce79015a4fbc0b7f83fa9001b61058b6566141e7ed8608a`（上一版 `76f4c9fbbf8b0889736904c8408dec11f62c2b9c7a3d60a2210c969ef2a922b4`）
- 性质：只读复核。零模型、零权重、零账本、零锁；未改 r1 / r2 / 两个封存目录 / `da3_calibration_runner.py` / `pipeline.py` 的任何一个字节。
- 产出位置：`reports/V9-T28-r2-delta-review/`（本报告 + `metrics.json` + 7 个自写脚本 + 14 份证据）

---

## 0. 我做了什么（脚本与证据一一对应）

全部脚本我自己写，**没有 import 也没有照抄**作者的 `build_proposal_r2.py` / `build_docs_r2.py` / `check_r2.py`。

| 脚本 | 作用 | 证据 |
|---|---|---|
| `own_diff.py` | 把 JSON 摊平成叶子路径，重算两套差异 | `evidence/01-diff-vs-prev.txt`、`02-diff-vs-r1.txt` |
| `compare_author_diff.py` | 作者 `diff_r1_r2.json` 的 32 条 × 覆盖/不虚列/值一致 三项交叉 | `evidence/03-author-diff-crosscheck.txt` |
| `subtree_equality.py` | 卡面点名"逐字节相等"的 35 个子树 + 顶层白名单 | `evidence/04-…-vs-prev.txt`、`05-…-vs-r1.txt` |
| `repro_fp16_dtype.py` | 只用 CPU、不加载权重，复现 dtype 冲突（6 个子用例） | `evidence/06-fp16-dtype-repro.txt` |
| `budget_audit.py` | 预算自算 + 阶段结构检查 + 与 `load_plan` 第三方对照 | `evidence/07-budget-audit.txt` |
| `stale_scan.py` | 15 组旧数字/旧措辞模式扫描 | `evidence/08-stale-scan.txt` |
| `run_fake_e2e.py` | `load_plan(r2)` + 假 teacher，仓外整条跑通 | `evidence/09-fake-e2e.txt` |
| `verify_retired_evidence.py` | 退役证据的文件/行号/SHA + 我自己从源码读出的 marker | `evidence/10-retired-evidence.txt` |
| `adversarial.py` | 5 个自建对抗用例，用**同一批检查脚本**去抓 | `evidence/11-adversarial.txt` |
| `q2_numerical.py` | 问题 2 的数值依据（量纲、元素数、历史实测） | `evidence/13-q2-numerical.txt` |
| —（一次性） | 真实 teacher 的零模型预检 | `evidence/12-real-preflight.txt` |
| —（一次性） | 删 `mps_float16` 键的后果 | `evidence/14-mps_float16-key.txt` |

运行环境：`.venv`（torch 2.3.1）。卡面写的 `.venv-t6` 在本机不存在；实际可跑 DA3 测试与 torch 的是 `.venv`，故用它。所有 torch 相关运行一律 `device=cpu`，未触碰 MPS。

---

## 1. 差异重算（第 1 项）

### 1.1 新版 vs 上一版 `76f4c9fb`

我摊平后：上一版 300 个叶子、新版 306 个、**59 个叶子变化**，变化只落在 **4 个顶层键**：

```
/amendment: 15 个叶子    /budget: 26    /numerical_parity: 14    /open_items: 4
```

与卡面预期**完全一致**。再往里看：

- `numerical_parity` 内只有 `known_risks`（`[0]` 改写、`[1]` 删除）与新增的 `retired_stages`；`cpu_float32`、`mps_float16`、`fields`、`rule`、`require_same_shapes_and_finite`、`reference` 全部逐字节相等。
- `budget` 内只有 `models[*]`（`forward_calls` 10→9、`forward_views` 28→25、`stages[4]` 整块消失）、两个总数、`unallocated_views` 8→14、`view_accounting.note`。
- `negative_controls`（含 `required_red` 常数）、`split`、`alignment`、`estimation`、`failure_policy`、`residual_vector`、墙钟/RSS/单模型常驻/重试、全部输入 SHA：**一个叶子都没动**。

`subtree_equality.py` 对 35 个点名子树逐个做规范 JSON 全等，全部 `EQUAL`，`FAILS=0`；白名单检查（除 4 个允许的顶层键外不许有变化叶子）也 `[]`。

### 1.2 新版 vs r1，与作者 32 条逐条对照

作者声明 32 条。我自己算出的"最大整块变化节点"是 **41** 个——这不是矛盾，是**粒度差异**：作者报 `/claims_forbidden`、`/execution_prerequisites`、`/budget/models[0]/stages` 这种整键，我按 list 索引拆到 `/claims_forbidden[6]`、`/execution_prerequisites[1]/[3]/[6]/[7]`、`/budget/models[0]/stages[3]/stage`。所以要做三项交叉：

| 检查 | 结果 |
|---|---|
| C1 覆盖：我的每个变化叶子都落在作者某条路径下 | **未覆盖 0 个** |
| C2 不虚列：作者每条路径下至少有一个叶子真的变了 | **虚列 0 条** |
| C3 值一致：作者记录的 `r1`/`r2` 值与该路径在真实文件里的值规范 JSON 全等 | **不一致 0 条** |
| 作者声明的 `r1_sha256`/`r2_sha256` | 与实测**相等** |

即：作者那 32 条**既不漏也不虚、值也没抄错**。`unlisted_differences = []`。

### 1.3 r1 与封存目录未被改写

- r1：`proposal.json` = `af3131a5…`、`PROTOCOL.md` = `b8d903c0…`，与卡面给的期望值一致；`shasum -c reports/V9-T28/proposal.sha256` → `proposal.json: OK`。
- `pre-half-parity-removal-76f4c9fb/`：自带 `SHA256SUMS.txt` 9 个文件，`shasum -c` **9/9 OK**（含 `proposal.json` = `76f4c9fb…`）。
- `reviewed-0e15033a/`：清单 9 条，目录里只有 6 个文件，**其余 6 个 SHA 全对**；缺 `build_proposal_r2.py`、`build_docs_r2.py`、`check_r2.py` 三个。

> 关于这 3 个缺失文件：不是篡改，是**快照不完整**。而且这三个文件在 T39 复核时的版本（`cbbff93f…`/`9875dd88…`/`bb65610d…`）与封存目录里的版本（`aa0c90a7…`/`a3276464…`/`c897aaf3…`）不同，所以**那三个被复核过的脚本版本在本仓已经不存在了**。不影响 `proposal.json` 的可验证性（我的检查全部从 proposal 本身出发），但作为可复现性记录是缺口，建议一级登记时顺手补一份。

---

## 2. half_parity 是否"按构造无法完成"（第 2 项）

### 2.1 代码事实（我逐行核过，行号精确到卡面声明）

| 事实 | 位置 | 我的核验 |
|---|---|---|
| 关 autocast + 整网转 fp16 | `envs/teachers/t6/pipeline.py:268`（类定义）内 `274` 行 `torch.autocast(..., enabled=False)`、`291` 行 `model.to(device=..., dtype=precision)` | 行号 268 处确为 `class ExplicitPrecisionDA3(DepthAnything3):` |
| 上游写死 fp32 | `cam_dec.py:37` `out_t = self.fc_t(feat.float())`，`39`/`40` 同样 | 行号 37 内容逐字一致 |
| 另两处 fp32 写死（作者未列，我补的） | `model/utils/head_utils.py:146` `return emb.float()`（DualDPT 位置编码）、`model/dinov2/vision_transformer.py:226` `pos_embed = self.pos_embed.float()` | 已读原文 |

两个文件的 SHA 与 `retired_stages.evidence` 声明**完全一致**（`f7bc81d8…`、`67357ea4…`），`pipeline.py` 自 T40 起未被改动。

### 2.2 CPU 上独立复现：`cpu_dtype_error_reproduced = true`

`repro_fp16_dtype.py` 6/6 通过（全程 `device=cpu`，零权重）：

- **A** `nn.Linear(64,3).half()` 在 `autocast(enabled=False)` 下收 `.float()` 输入 → `RuntimeError: mat1 and mat2 must have the same dtype, but got Float and Half`。**与作者所述错误串逐字相同。**
- **B** 同一 fp16 Linear 收 `.half()` 输入 → 正常，`out.dtype=float16`。说明错因就是 `.float()` 那一句，不是 fp16 本身。
- **C** 同一段算术在 autocast 打开时不抛错 → 说明失败来自"禁用 autocast 的整网 fp16"，不是"fp16 不可行"。
- **D** `cam_dec.py` 的 `fc_t`/`fc_qvec`/`fc_fov` 三处 `.float()` **各自都能独立触发**同一错误（所以不是单点偶然）。
- **E** 位置编码写死 fp32 是**另一类**问题：逐元素 add 会静默提升到 fp32（不抛错），再喂给下游 fp16 Linear 才炸。我第一版断言"相加即抛错"是错的，按实测改写了断言——这条弯路留在脚本注释里。
- **F** fp32 阶段同一段算术：`.float()` 是 no-op，`out.dtype=float32`，正常。

结论：**"这个阶段按构造无法产出结果"这一判断成立**，且在 CPU 上可被任何人用 20 行代码复现，不需要 DA3 权重。

### 2.3 作者 MPS 主张的证据强度：中等偏弱（但不影响结论）

作者的 MPS 主张是："没有 Python 异常，Metal 断言直接中止进程（SIGABRT，退出码 134）"。我没有复现（卡面也不要求、不允许），只评价证据：

- **强度偏弱的理由**：单源自述；`reports/V9-T40/DECISIONS_FOR_USER.md` 第 1 节只有文字，没有留 stderr、没有留 `$?`、没有留崩溃现场。按本仓自己的证据标准（别处都在留 SHA 与日志），这一条是**未落档的口头断言**。
- **但它是"承重"还是"装饰"？** 承重部分是"该阶段无法完成"，这一点我在 CPU 上独立复现了；SIGABRT vs `RuntimeError` 的差别只影响两件事：(a) T40 为什么要逐阶段原子落盘（设计选择，已实现且被测试覆盖）；(b) 措辞。**删除决定不依赖 SIGABRT 这个细节。**
- **建议（非必须）**：`PROTOCOL.md:82` 与 `retired_stages.reason` 把 MPS 结果当既成事实陈述。加一个"作者报告"的限定词即可，成本近乎零。

顺带一条**独立旁证**（作者没提，我发现的）：本仓 pinned torch 是 **2.3.1**，其 `torch/amp/autocast_mode.py` 里 `"mps"` 出现 **0 次**，`torch.autocast(device_type="mps", ...)` 在 2.3.1 上是**空操作**；而 T6 归档里那次 `f32_vs_f16` 正是用 `torch.autocast("mps", float16)` 跑的，实测 `max_abs_diff = 0.0`（阈值 0.15）。**fp16 matmul 不可能给出 0.0**（fp16 相对精度约 1e-3），所以那次所谓"fp16 前向"实际仍是 fp32。这独立支持"本仓从未真正跑过 fp16 前向"，也就支持"half_parity 从来没产出过任何结果"。

### 2.4 fp32 阶段会不会撞同类问题？`fp32_stages_risk`

**不会，理由是逐条可查的**：

1. `precision=float32` 时 `image.to(float32)` 与上游 `.float()` 是同一个 dtype，`autocast(enabled=False)` 也不改变 fp32 运算 → 复现用例 F 直接验证。
2. 我在整个 `Depth-Anything-3/src` 里搜 `float64` / `.double()`：**0 命中** → 不存在"MPS 不支持 float64"这类设备不兼容。
3. 搜 `torch.linalg` / `torch.svd` / `.inverse()` / `torch.solve`：**0 命中** → 不存在 MPS 算子缺口。
4. `infer_gs=False`、`use_ray_pose=False`，GS 与 ray 分支不进前向；`sky` 键在本构型下根本不会被 head 产出（`model/` 目录里没有任何 `sky` 写入点），所以 `_process_mono_sky_estimation` 里的 `torch.quantile` 是死路径。
5. 剩下四个阶段全是 fp32，历史上有过真实 MPS/F32 前向（T33 的 10 视图 7.5 s）。

**剩下的风险不是 dtype，是数值与离散选择**——见问题 2。

---

## 3. 预算算术（第 3 项）

我自己从 `budget.models[*].stages` 重算（`calls × frames_per_call`），再与文件声明、与 `load_plan` 三方对照：

| | DA3-SMALL | DA3-BASE | 合计 |
|---|---:|---:|---:|
| calls | 9 | 9 | 18 |
| views | 25 | 25 | 50 |
| loads（(device,precision) 变化次数） | 2 | 2 | 4 |

- `unallocated_views` 自算 `64 − 50 = 14`，声明 14 ✓
- `reserve_before_model_import_views` 仍为 64 ✓
- 阶段名 `['first_frame','calibration','frame_order_adverse','cpu_parity']` ✓，全部 `precision` 集合 = `{'float32'}` ✓
- `load_plan(r2)` 给出 `calls_per_variant=9`、`views_per_variant=25`、`known_intrinsics=False`、`focal_scale=(1.0,1.0)`、`parity_cpu=(0.001,0.001)`、`parity_half=(0.01,0.01)`、`red_floor=0.0001`、`red_rel=0.1` —— 与我的算术一致。

**阶段结构**（这类改动不会破坏 calls/views 算术，所以必须单独断言）：

- `first_frame`：`worlds=[room-00]`、`views=[0]`、1 call、mps ✓
- `calibration`：6 个世界各 1 call、`views=[0,1,2]`、世界集合 == `fit_worlds ∪ holdout_worlds` ✓
- `frame_order_adverse`：`views=[2,1,0]`（正是锚点/评分/尺度三个槽位的逆序）✓
- `cpu_parity`：`device=cpu`、`views=[0,1,2]` ✓

`view_accounting.status = OPEN_pending_user_decision`、`wall_accounting.status = OPEN_pending_user_decision`、`cumulative_wall_seconds_max = null`、`open_items` 4 条。**按卡面要求，这些未决项不构成 reject**；我确认它们被明确标为未决、且与现状一致（1170/1200 s、`next_run_minimum_cap_s=1230`）。

> 一处**遗漏**（建议补，不阻塞）：`open_items[0]` 覆盖了"账本按数据集视图 18 还是前向视图 50 记"，但**没有记录它的下游后果**——`da3_worker.py:28` 的 `REGISTERED_CALIBRATION_VIEWS = 18` 是拿 `spec.views`（CLI `--views`）去比 18 的。若用户选前向视图口径、下次真跑记 50，worker 会**直接拒绝执行**（`refused_no_calibration`），而这不是协议层面能看出来的。建议在 `open_items` 里加一句。

---

## 4. 残留旧数字与旧措辞（第 4 项）

15 组模式共 43 处命中，**逐条判定后：没有一处是"当前值被写错"，全部是"改前→改后"的历史说明**。

| 命中 | 判定 |
|---|---|
| `PROTOCOL.md:85`「每型号 10 次/28 视图 → 9 次/25 视图，合计 20 次/56 视图 → 18 次/50 视图；每型号加载 3 次 → 2 次，合计 6 → 4」 | **应保留**。箭头左是改前值，且 3→2、6→4 与"删掉 mps/f16 这一次加载"吻合（r1/r2-prev 的 (device,precision) 序列是 mps/f32 → cpu/f32 → mps/f16） |
| `PROTOCOL.md:92`「每型号 11 次/31 视图 → 9 次/25 视图，合计 62 → 50」 | **应保留**。这是 r1→r2 的累计差（先删 `intrinsics_adverse` 得 10/28，再删 `half_parity` 得 9/25） |
| `PROTOCOL.md:43`「r1 另有 MPS/F16 一致性阶段…其容差键在机器文件中原值保留但无任何阶段使用」 | **应保留**，且是准确的 |
| `PROTOCOL.md:56`「MPS/F32六个世界 6 3 18」、`:60`「两型号合计 18 — 50」、`:100`「18 视图输入」 | **不是旧数字**：分别是校准阶段 6×3=18 视图、两型号 18 calls/50 views、数据集 18 视图 |
| `proposal.json` 里 6 处 `half_parity` | 全在 `amendment`（逐字批准、E15 变更记录）与 `retired_stages`（退役记录）里，**必须存在** |
| `unallocated_views=8` | **新版已无命中**（只存在于封存目录）✓ |
| `31`/`62`/`56`/`28`/`20 次`/`10 次` | **只出现在上述两行箭头式说明里**，机读文件里 0 命中 ✓ |

`mps_float16` 容差键保留是否误导消费者 —— `mps_float16_key_assessment`：

- **保留是对的**，而且不是"图省事"：`load_plan` 在 `da3_calibration_runner.py:152` **无条件**读 `par["mps_float16"]`。我在 `/tmp` 副本上删掉该键实测 → `load_plan` 抛 `KeyError: 'mps_float16'`。要删键就必须同时改 runner，而那需要另一张卡 + 一次非作者复核，对一张"小卡"是过度扩张；而且 T41 刚刚复核过 runner，此时动它风险更大。
- 已有的防误读措施足够：`PROTOCOL.md:43` 明说"原值保留但无任何阶段使用"，`retired_stages[0]` 带 `tolerance_key: "mps_float16"` 与 `tolerance_kept_unchanged_and_unused: true`。
- **残留隐患（只报告，不改）**：`da3_calibration_runner.py:356` 仍有 `elif name in ("cpu_parity", "half_parity")` 分支，`parity_half` 也仍被解析。若将来有人把 `half_parity` 阶段加回 budget，runner 会**静默用 0.01 容差**跑起来，不需要任何代码改动。建议后续卡做一处硬化：让 `load_plan` 断言"每个容差键都至少被一个阶段使用"，把死键变成预检错误。

---

## 5. runner 与新版一致吗（第 5 项）

### 5.1 假 teacher 整条跑通：`runner_fake_run_ok = true`

`run_fake_e2e.py`：`load_plan(r2)` + `load_fixtures` + 显式 `preflight` + `run_full_calibration`，产出写在 `/tmp`（仓外，跑完已清理）。

```
preflight checks = ['t28_hashes_bound','fixtures_match_split','outputs_are_fresh','protocol_satisfiable_by_teacher']
run_full_calibration: exit=0  status=limited_aligned_diagnostic_candidate_unregistered  failures=[]
[DA3-SMALL] stages=['first_frame','calibration','frame_order_adverse','cpu_parity']
[DA3-BASE ] stages=['first_frame','calibration','frame_order_adverse','cpu_parity']
forward_accounting: calls_actual=9 views_actual=25 complete=True  (两个型号都是)
make() 序列: [('DA3-SMALL','mps','float32'),('DA3-SMALL','cpu','float32'),
              ('DA3-BASE','mps','float32'),('DA3-BASE','cpu','float32')]
证据 JSON 里出现 'half_parity' 字样: False
```

即：阶段恰好 4 个、前向账目 9/25、每型号 2 次 `make()` 且全 `float32`、合计 4 次、退出码 0 —— 与卡面逐项一致。

顺带确认"红了也如实报"：对拍明细是**逐字段**的 `max_abs` / `failed_elements` / `total_elements`（`da3_calibration_math.py:144-169`，判据 `diff > atol + rtol*|a|` 记失败、`failed == 0` 才 pass），`_Run` 只 append failure 不 raise，`run_full_calibration` 最后把 `EXIT_STAGE_FAILED = 5` 返回并**照样写完整证据**（`da3_calibration_runner.py:60`、`356-365`、`440-451`）。

### 5.2 真实 teacher 的预检：零模型，通过

`R.preflight(plan, R.RealTeacherFactory(), ...)` → 4 项 checks 全过，且预检前后 `sys.modules` 里 `torch` / `pipeline` / `depth_anything_3` **全部为 False** —— 确认没有触发任何权重加载（`RealTeacherFactory.make()` 只在 `run_variant` 里被调用）。

### 5.3 硬编码数字：`hardcoded_numbers_in_runner_or_worker`

| 位置 | 内容 | 判定 |
|---|---|---|
| `da3_calibration_runner.py` | **无任何数值魔数**（18/28/31/56/62/50/25/9/64 全部 0 命中），阶段/容差/阈值/划分全从 proposal 读 | 干净 |
| `da3_calibration_runner.py:356` | `elif name in ("cpu_parity", "half_parity")` | **死分支**，见 §4 隐患 |
| `da3_calibration_runner.py:152` | `parity_half=(par["mps_float16"]...)` | 仍解析，见 §4 |
| `da3_worker.py:28` | `REGISTERED_CALIBRATION_VIEWS: int = 18`，在 `:209` 与 `spec.views` 比较 | 与 r2 的**数据集视图 18** 一致；但口径若改前向视图（50）会拒绝真跑，见 §3 遗漏 |

worker 里 `half_parity` 0 命中。

### 5.4 我实际跑的是哪个 runner 版本（必须交代的前提）

卡面的语境是"T40 已修、T41 已复核"，但磁盘上的 runner **不是** T40 交卷时那一版：

| | SHA | 说明 |
|---|---|---|
| T40 报告声明 | `d6d2416e…` | 我用 `reports/V9-T40/evidence/t37-to-t40.diff` 的 runner 段 patch 到 `t37-accepted/` 基线上**重建出了这个 SHA**，逐字节吻合 → **T40 的 SHA 表没错** |
| 磁盘当前 | `5c12b934…` | mtime `2026-10-28 00:53:54`，晚于 T40 交卷（约 00:14） |

改动来源是 **T42（gemini-f8a2，`reports/V9-T42/REPORT.md` 第 4 项）**：`_write_atomic` 的临时文件名从 `.tmp` 改成同目录 `.tmp.<pid>.<uuid>` 并加异常清理。T40 版与当前版的**全部差异只有 2 个 hunk / 18 行**（一个 `import uuid` + `_write_atomic` 函数体），`load_plan`、`preflight`、阶段执行、对拍、退出码**一行未动**（`evidence/15-runner-version.txt`）。

所以：**我的 §5.1–5.3 结论是对 `5c12b934…` 成立的，而它相对 T40/T41 认证的 `d6d2416e…` 只差一个原子写的健壮性修补。** 这一点写在这里，是因为"复核用的代码版本与被复核报告声明的版本不一致"必须显式交代，不能默认读者知道中间还夹了一张 T42。

（顺带：`da3_worker.py`、`da3_controlled.py` 现在的 mtime 是 `01:26`/`01:44`，那是我本会话 `V9.T44` 的改动，已在 `reports/V9-T44/` 交代；`benchmark_commands.py` 同理。它们不影响本卡结论，但 T42 报告里的这四个 SHA 现在都已过期。）

---

## 6. 自建对抗用例（第 6 项）：5/5 全被抓

每个用例都复制新版到 `/tmp`、注入一处篡改，然后用**上面同一批检查脚本**去跑（不是另写一套）：

| # | 篡改 | 抓住它的是 | 结果 |
|---|---|---|---|
| A | `cpu_float32` 容差 0.001 → 0.01 | `subtree_equality`：`DIFF /numerical_parity/cpu_float32` + 白名单 | 抓到 |
| B | 逆序控制常数 `max(0.0001, 0.1·S_clean)` → `0.00001` | `subtree_equality`：`DIFF /negative_controls/required_red` + `OFFENDER` | 抓到 |
| C | 把 `half_parity` **加回** budget，并把总数改成看起来对的 10/28、20/56、`unallocated=8` | `budget_audit`：阶段名白名单（`未登记的阶段名`）+ `retired_stages` 交叉（`重新出现在 budget.stages 里=['half_parity']`） | 抓到 |
| D | 制造"只删了 half_parity"的假象：实则把 `calibration` 里 room-03 的 `views` 从 `[0,1,2]` 改成 `[0,1,1]`（`frames_per_call` 仍 3，总数不变） | `budget_audit` 的阶段结构检查：`views=[0,1,1] 期望 [0,1,2] -> False` | 抓到 |
| E | `retired_stages.evidence.cam_dec` 的行号 37→38、SHA 改成全 0 | `verify_retired_evidence`：SHA 不一致 + 行号处 marker 不符 | 抓到 |

**C 和 D 值得单独说**：这两个用例的 calls/views 算术**完全自洽**（C 自算 10 次/28 视图、合计 20/56、`64−56=8` 全对；D 仍是 9/25）。也就是说，**只做预算算术是抓不到它们的**，必须靠"阶段名白名单 + 退役表交叉"和"阶段内容结构断言"。这正是我额外加这两类检查的原因。

### 6.1 对作者 `check_r2.py` 的评价（只静态评价，未用作自证）

**真有鉴别力的**：
- `:99/:101` 退役证据的行号+文件 SHA 与磁盘比对（读的是磁盘，不是声明）。
- `:115/:117/:119` 与**上一版**做 top-level / 一层下钻的规范 JSON 比对 —— 这条覆盖是完整的，能抓到 A。
- `:121` `[s for s in old_stages if s["stage"]!="half_parity"] == new_stages` —— **逐字典比较**，能抓到 D。
- `:66` 阶段名列表恒等、`:70` 算术三元组、`:154-158` 用真实 runner + 假 teacher 端到端并断言"没有 float16 的 make()、只有 4 次加载"。
- `:105-108` 封存/复核目录 SHA。

**同义反复或覆盖不到的地方**：
- `:29-35` 的"差异只落在枚举范围内"是拿**作者自己写的 `diff_r1_r2.json`** 当输入去比白名单 —— 如果 diff 文件本身漏了一条路径，这条检查看不见。**这是唯一一处真正的循环**；我用自己摊平的叶子差异补上了（C1 覆盖检查）。
- `:42-58` 的"未改动"断言只枚举了固定的键名；枚举之外的键若在 r1→r2 之间被改动，只能靠 `:115` 的顶层比较兜住（能兜住，但一层下钻只对 `budget`/`numerical_parity` 做了）。
- `:124` 用海象运算符嵌在条件表达式里（`p2[...] == p1_sha if (p1_sha := ...) else False`），可读性差、且 `p1_sha` 恒为真所以 `else False` 是死分支。
- 完全没有检查"阶段内容是否与 `split` 一致"（我的结构检查才抓得到 D 之外的变体，例如把 `first_frame` 的 `views` 从 `[0]` 改成 `[1]`——那也不会破坏算术，作者 `:121` 能抓到、但 `:66/:70` 抓不到）。

---

## 7. 三个问题

### 问题 1：E15 能否作为 r2 的最终形态进入一级登记 SHA？

**能，`accept_with_changes`**，但必须改的点只有 `PROTOCOL.md` 的 3 处措辞（见 §8）。**这三处都不在 `proposal.json` 里**，所以一级要登记的机器文件 SHA `86f5ece6…` 在改完后不变 —— 换句话说，措辞修正不会让登记对象漂移。

理由汇总：差异完全可枚举且与作者声明逐条对上（不漏、不虚、值不差）；卡面点名的所有"不许动"的子项逐字节相等；预算算术与 `load_plan` 三方一致；`load_plan`+假 teacher 整条跑通 exit 0；退役证据的文件/行号/SHA 经我独立核验为真；5 个对抗用例全被抓。

### 问题 2：删掉 half_parity 之后，剩下哪些门"按构造或高概率过不了"？

**严格"按构造不可能"的：没有了。** `half_parity` 是唯一一个。

**高概率红的是 `cpu_parity`**，而且我给得出量化的理由：

- 真值 depth 量纲：`2.59 – 9.68`（中位 6.44）。`atol=rtol=1e-3` 落到每元素上就是 **0.0037 – 0.0107** 的绝对容差。
- 对拍元素数：depth 176400 + confidence 176400 + extrinsics 36 + intrinsics 27 = **352863**（卡面说 ~3.5e5，对上了），且要求**失败元素数 = 0**。
- 本仓**唯一一次** MPS-vs-CPU fp32 实测（V9-T6 归档 `metrics.json`）：`max_abs_diff = 0.065056`，当时的绝对阈值是 0.08。**0.065 是中位深度容差的 8.7 倍、最大深度容差的 6.1 倍。**
- 所以：若该量级的设备差异在 280 分辨率下依然成立，`depth` 字段必然有非零 `failed_elements` → `cpu_parity` 判红。**"保持现状"不等于"大概率能过"，而是"大概率红、但红得诚实"。**
- 还有一条 O(1) 风险（`known_risks[0]` 已披露）：没有 `cam_token` 时参考视角由 3 视图上的离散 argmin 选出，CPU/MPS 一旦翻转，输出坐标系整体改变，任何容差都救不回来。近平时这个翻转不难发生。
- 反过来，`intrinsics` 反而是最宽松的一项：`fx=220` → rtol 项给出 **0.22** 的绝对容差（假 teacher 跑里 `intrinsics max_abs=0.11` 就是靠这个过的）。

**一旦翻转/超差，协议会如实报而不是静默通过** —— 我在代码和运行里两头确认了：逐字段记 `max_abs`/`failed_elements`/`total_elements`；失败只 append 不 raise，所以**两个型号仍会跑完、标定证据（fit/holdout 统计、全部预测）照样落盘**；最后退出码 `5`、`status="failed"`。没有任何"静默通过"的分支。

**`frame_order_adverse` 不属于"过不了"**：它是经验判据（S_bad ≥ S_clean + max(1e-4, 0.1·S_clean)），而 T6 归档里同类负对照 NEG-01（帧序打乱）是 `turned_red_as_expected` —— 历史证据支持它在真实 DA3 上能变红。当然按协议，没变红本身就是失败结果，不换指标。

### 问题 3：修订后有没有"说得过头"的话？

有 3 处，都不影响本次删除的正确性：

1. **`PROTOCOL.md:84`「这不是"结果出来后为通过而改动"：任何运行之前提出」** —— "任何运行之前"字面不成立：`T35` 那次唯一授权的真跑已经发生过（耗时 7 s、预留 60 s，因 runner 缺陷失败并耗掉配额；`open_items[1]` 自己写着累计已预留 1170/1200 s）。准确说法应是"在任何**产出标定结果的**运行之前"。这句恰恰是最需要精确的一句，建议改。
2. **`PROTOCOL.md:87`「若以后要它，需要先改管线（autocast 方案）并另立预登记」** —— 把 autocast 说成可行路线，偏乐观：本仓 pinned torch 2.3.1 上 `torch.autocast(device_type="mps")` 是**空操作**（`autocast_mode.py` 里 `"mps"` 0 命中），而且 `da3.py:127/:139` 自己就把 depth head 与 camera estimation 包在 `autocast(enabled=False)` 里 —— 外层开 autocast 也进不去。T6 那次 `f32_vs_f16 = 0.0` 正是这个机制的直接后果。所以 autocast 路线在当前环境里会产出**一个永远不可能变红的空门**。建议改成"需要换 torch 版本或改 `da3.py` 的 `enabled=False` 段，并另立预登记"。
3. **`PROTOCOL.md:82`「而且它是每个型号最后一个阶段、整次运行的最后一步之前就会把授权耗光」** —— 句子本身不通顺，且"授权耗光"的机制（按预留一次扣）没说出来。建议改成"它是 DA3-SMALL 的最后一个阶段，会崩在 DA3-BASE 开始之前；授权已按预留扣掉，不退还"。

另外两条**说得过满但不是错**：`PROTOCOL.md:82` 与 `retired_stages.reason` 把 MPS 的 SIGABRT/134 当既成事实（见 §2.3，建议加"作者报告"）；`AMENDMENT.md` 未记录"复核过的那三个 build/check 脚本版本已丢失"（见 §1.3）。

---

## 8. 必须改的点（`required_changes`）

全部只动 `PROTOCOL.md`（必要时同步 `AMENDMENT.md`），**不动 `proposal.json`**，所以登记 SHA 不变：

1. `PROTOCOL.md:84` 把「任何运行之前提出」改成「在任何产出标定结果的运行之前提出」，并补一句 T35 那次运行因 runner 缺陷失败、未产出任何标定结果，E15 的证据来自不加载权重的 dtype 复现。
2. `PROTOCOL.md:87` 把「autocast 方案」改成准确说法：当前 torch 2.3.1 的 MPS autocast 是空操作，且 `da3.py` 内部已 `enabled=False`，要恢复 fp16 一致性需先换 torch 版本或改 `da3.py`，再另立预登记。
3. `PROTOCOL.md:82` 重写那句不通顺的授权说明（DA3-SMALL 最后阶段 → 崩在 DA3-BASE 之前 → 预留已扣不退）。
4. （建议同批）`PROTOCOL.md:82` 与 `retired_stages.reason` 的 MPS 结论加「作者报告」限定词。
5. （建议同批）`open_items` 补一句：若配额口径改为前向视图 50，`da3_worker.py:28` 的 `REGISTERED_CALIBRATION_VIEWS = 18` 会拒绝真跑，需同步调整。
6. （建议同批，非本卡范围）一级登记时给 `reviewed-0e15033a/` 补上缺失的 3 个 build/check 脚本，或在其 `SHA256SUMS.txt` 里注明"仅存交付物，脚本版本未留存"。

**若一级认为"小卡不该再改文档"**，备选口径：把 1–3 记为 `T47` 的文档修订项，**机器文件 SHA `86f5ece6…` 现在就登记**。我不推荐这个口径，因为第 1 条正是"预登记不能为通过而改"这句话本身，写歪了会削弱整份预登记的可信度；而它改起来只是三个句子。

---

## 9. 红线核对

| 项 | 结果 |
|---|---|
| 只读 | 是。`reports/V9-T28/**`、`da3_calibration_runner.py`、`pipeline.py` 复核前后 SHA 不变（`86f5ece6…`、`af3131a5…`） |
| 不加载 DA3 模型/权重 | 是。全部 torch 运行 `device=cpu` 且只构造 `nn.Linear`；真实预检前后 `sys.modules` 无 `torch`/`pipeline`/`depth_anything_3` |
| 不碰 `m0-worker.lock` | 是。`mtime_epoch=1790110663`、`size=0`，前后一致 |
| 不碰 `runs.db` | 是。`64b668050dfbab7ae1e5b9fe5280f44cecb12643fb820b6a752a6a693723107f`，前后一致 |
| 不改 r1 / r2 / 封存目录 | 是。r2 `SHA256SUMS.txt` 9/9 OK；封存目录 9/9 OK；r1 `proposal.sha256` OK |
| 产出只写 `reports/V9-T28-r2-delta-review/` | 是。所有跑批输出写 `/tmp`，跑完 `shutil.rmtree` 清理 |
| 不推送、不下载、不付费 | 是 |

---

## 10. 一句话给下一棒

E15 干净：删得对、删得全、没夹带；`half_parity` 在 CPU 上 20 行代码就能证明"按构造不可能完成"，MPS 的 SIGABRT 是单源自述但不承重。**真正该担心的是 `cpu_parity`——按本仓唯一一次 MPS/CPU fp32 实测，它超差 6–9 倍，第一次真跑大概率以退出码 5 结束（证据仍在、不会静默通过）。**
