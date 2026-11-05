# ainerzero.V9.T9 独立复核报告：ainerzero.V9.T8 RLT 参考实现

角色：verifier（二级，独立复核者）；负责人：deepseek-flash-3tgx；时间：2026-10-20；任务状态：reported；
被验任务：`ainerzero.V9.T8`（RLT 停帧去重 numpy 参考实现，执行者/作者 `opencode-de3b`，reported 第 1/3 次）；
依据：`ainerzero.V9.T9` 任务卡、`ARCHITECTURE_V9.md` §4 第 10 项（Eq.10：`‖p_t − p_{t−1}‖_∞ < τ` 合并、游程长度编码）、
`docs/research/V9_FRONTIER_COST_SURVEY.md`、作者报告（`relay show ainerzero.V9.T8 --full` / `reports/V9-T8/REPORT.md`）、
`AnimeWorldZero/docs/adr/ADR-0012-v9-neurogeometry-hjepa.md`；参数 v0 照用未改（`{}`）。
**本复核者不是 T8 作者**；只读被验文件，只写 `reports/V-V9-T8/`。纯 CPU，无 MLX/torch/GPU/下载/训练/提交推送。

## 摘要（≤30 行）

1. 独立重写纯 Python 循环 oracle（不使用作者测试/实现内部），对 `rlt_frame_dropping` 的语义、保留率、可逆性逐项核对。
2. **11 个自写对抗用例真实执行、无失败**（要求 ≥6）：周期闪烁（阈值上/下）、单像素变化、τ 恰在边界（等于/略小于）、
   超长静止段（T=1000）、首帧/末帧变化、T=1 边界、τ=0 不去重、混合长度批次 fail-closed、负 τ 拒绝。
3. **保留率独立重算全部一致**：9 个数值用例 impl `K`/`retention_rate` 与 oracle 精确相等（差 0，≤1e-15），
   并从返回的 `retained/run_lengths/positions` 再独立重算 K、rate、每位置游程和 = T。
4. **还原可逆**：解码 `(positions, run_lengths, retained)` 可逐位置重建保留帧索引与 token 值；kept 帧 restoration
   与原文逐位相等；merged 帧 restoration 等于该 run 的保留 token，且相对上一原始帧 diff < τ。
5. 确定性：同一输入两次调用输出逐位相同；实现不修改输入张量。
6. **纯 CPU 检查**：AST 导入根仅 `{"numpy"}`；隔离子进程导入后 `sys.modules` 无 torch/mlx/tensorflow/jax/coremltools。
7. **故意改坏对照 4/4 变红**：`<`↔`<=` 边界、保留率分母、去掉 restoration 传播、去掉首帧保留——各 mutation 副本
   被同一组检查真实捕获（失败检查数 42/18/16/153，指定用例/检查全部命中），`--mutate` exit 0 表示控制成立。
8. 作者套件独立复跑：`tests/v9/tokenization/test_rlt.py` → **18 passed, exit 0**；实现/测试 SHA 与作者报告声明一致
   （`6514aa80…6167` / `58957951…9314`）。
9. **建议验收（限范围）**：纯 CPU numpy 参考实现 + 合成片段语义/保留率/可逆性/纯度；**不**外推 V-JEPA 特征上的
   精度-吞吐实测、真实数据或 runtime 接入。不 accept 自己。
10. 观察（非阻塞）：`positions` 只有 (h,w) 无帧索引（需由 run_lengths 解码）；长游程 restoration 误差可 >τ（符合登记语义，
    但消费者不能假设全局 ≤τ）；tau 校验用 `assert`（`python -O` 会失效）；非 4D 输入抛 ValueError 而非断言；
    混合长度批次不支持但 fail-closed。详见 §7。

## 输入身份与环境

| 输入 | SHA256 |
|---|---|
| 被验实现 `src/ainerzero/v9/tokenization/rlt.py` | `6514aa80a66ab1ff3f92bcc8dce3a59c3ea0da9c2d49bbadea675afa63526167`（与作者声明一致） |
| 被验测试 `tests/v9/tokenization/test_rlt.py` | `58957951c50e008b453059da5da2c4e505fc555140f879f87a2c416593c69314`（与作者声明一致） |
| 作者报告 `reports/V9-T8/REPORT.md` | `b66a82407c017e8d39a3b70e7db93ee4cebe9531a1b27a0137e3d6309166c9bf` |
| 作者指标 `reports/V9-T8/metrics.json` | `5d89c0dc852fcc49924e8e86031777a732259ec4a39c89480bfba83c23065df9` |
| git HEAD（AinerZero） | `2de6caef0820894520271a8943761cc0b3cf8c22` |

环境：Python 3.12.4 / numpy 2.4.2 / CPU only；未安装包、未联网、未跑模型。
工作树说明：`src/ainerzero/v9/tokenization/`、`tests/v9/tokenization/` 是作者 T8 的**未提交**产物（`git status` 为 `??`）；
开工前仓库已有他人未提交改动（CLAUDE.md/COORDINATION.md/RESEARCH_LOG.md/docs/research/* 等），本卡未碰。
本卡只新增 `reports/V-V9-T8/`。

## 复核方式

- **独立 oracle**：`reports/V-V9-T8/verify_t9.py` 内按规格用纯 Python 循环重写（逐位置保留帧 = `{0} ∪ {t≥1 : diff≥τ}`，
  游程 = 相邻保留帧差/末段 T−last，保留 token = 原帧特征，restoration 按 run 填保留 token）；不复用实现内部函数。
- **11 个对抗用例**（全部自写、真实执行，非作者夹具）：见 §2 表。
- **独立重算保留率**：① oracle K/rate 对比；② 只从返回产物重算 K、rate、每位置游程和；③ 从产物解码帧索引与 token 值。
- **可逆性**：kept 帧逐位；merged 帧 token 填充与 diff<τ；解码重建与 oracle 保留帧/值一致。
- **纯度**：AST 导入根 + 隔离子进程 `sys.modules` 扫描。
- **故意改坏对照**：复制实现到临时目录做 4 个变异（不改被验文件），同一检查组必须非零红；见 §6。
- **作者套件**：只复跑，不作为唯一证据。

## 2) 对抗用例与独立保留率重算（全部 MATCH）

| 用例（对应卡内类别） | 形状 T×H×W×D | τ | K impl | 总 token | 保留率 impl | oracle | 一致 |
|---|---|---|---|---|---|---|---|
| periodic_flicker_above_tau（周期闪烁，帧间 +0.6） | 6×2×2×3 | 0.5 | 24 | 24 | 1.000000 | 1.000000 | ✓ |
| periodic_flicker_below_tau（周期闪烁，帧间 +0.49 < τ） | 6×2×2×3 | 0.5 | 4 | 24 | 0.166667 | 0.166667 | ✓ |
| single_pixel_change（单像素/单 patch 变化） | 5×3×3×2 | 0.5 | 11 | 45 | 0.244444 | 0.244444 | ✓ |
| tau_boundary_equal（diff 恰 == τ 必须保留） | 3×1×2×1 | 0.5 | 4 | 6 | 0.666667 | 0.666667 | ✓ |
| tau_boundary_below（diff = τ−1e−9 必须合并） | 3×1×2×1 | 0.5 | 2 | 6 | 0.333333 | 0.333333 | ✓ |
| long_static_1000（超长静止段 1000 帧） | 1000×2×3×4 | 0.1 | 6 | 6000 | 0.001000 | 0.001000 | ✓ |
| first_last_frame_change（首帧唯一 + 末帧变化） | 4×2×2×1 | 0.5 | 6 | 16 | 0.375000 | 0.375000 | ✓ |
| single_frame_T1（T=1 边界） | 1×2×2×1 | 0.5 | 4 | 4 | 1.000000 | 1.000000 | ✓ |
| tau_zero_no_dropping（τ=0 不去重） | 4×2×2×1 | 0.0 | 16 | 16 | 1.000000 | 1.000000 | ✓ |
| mixed_length_batch_fail_closed（混合长度批次） | [T=3, T=5] | 0.5 | — | — | 期望异常 | AttributeError | ✓（fail-closed） |
| negative_tau_rejected（负 τ） | 3×1×1×1 | −0.1 | — | — | 期望异常 | AssertionError | ✓ |

- 独立产物重算：每个数值用例 `len(retained)=len(run_lengths)=len(positions)=K`，每位置跑长和 = T，
  `rate = K/(T·H·W)` 与返回值一致（差 0）。
- 可逆性/确定性/输入不变：全部用例通过；`restoration` kept 帧逐位相等、merged 帧 = run token 且相对上一帧 diff < τ。
- 原始输出与逐项检查：`case-results.json`（11 用例、11 项检查、0 失败）、`verify-t9.log`（exit 0）。

## 3) 作者套件与声明核对

- 命令：`PYTHONDONTWRITEBYTECODE=1 python3 -m pytest tests/v9/tokenization/test_rlt.py -q -p no:cacheprovider`
  → **18 passed in 0.12s，exit 0**（日志 `pytest-author.log`）。
- 实现/测试 SHA 与作者报告 §5 声明的 `6514aa80…` / `58957951…` 逐字节一致（本报告 §输入身份）。
- 作者报告中的保留率表（one_beat 0.375、still_image 1/T 等）本复核未逐夹具照抄；本复核用自建用例独立重算，
  不把作者测试当唯一证据。

## 4) 纯度检查（无 MLX/torch/模型）

- AST：`rlt.py` 导入根 = `["numpy"]`（无 torch/mlx/tensorflow/jax）。
- 隔离子进程（cwd=临时目录、PYTHONPATH 清空）导入实现后扫描 `sys.modules`：`loaded_forbidden_modules = ""`，exit 0。
- 证据：`case-results.json → import_purity`；命令含在 `verify-t9.log`。

## 5) 判定与建议

- **建议验收 ainerzero.V9.T8，限范围**：纯 CPU numpy 参考实现 + 合成/对抗片段上的语义、保留率、可逆性、确定性、纯度。
  该建议不覆盖：V-JEPA 2.1 特征上的精度损失/吞吐实测、真实视频数据、任何执行/渲染能力。
- 未发现足以打回的问题；§7 的观察项建议作为后续卡/文档澄清，不阻塞本卡验收。
- 本复核者不 accept 自己，不宣称能力通过；验收由一级/非作者决定。

## 6) 故意改坏对照（同一检查组必须变红；`--mutate` exit 0 = 控制成立）

| 变异（临时副本，不改被验文件） | 期望命中用例/检查 | 实测失败检查数 | 结果 |
|---|---|---|---|
| M1 `<`→`<=`（边界合并规则改错） | tau_boundary_equal / retained_values | 42 | 红 ✓ |
| M2 保留率分母 +1 | long_static_1000 / retention_rate | 18 | 红 ✓ |
| M3 去掉 restoration 传播（merged 帧用原帧） | periodic_flicker_below_tau / restoration_merged_token | 16 | 红 ✓ |
| M4 去掉首帧保留（keep_mask[0]=False） | single_frame_T1 / retained_count | 153 | 红 ✓ |

命令：`python3 reports/V-V9-T8/verify_t9.py --mutate` → exit 0，`all_controls_turned_red=true`；
每变异副本 SHA 与样本失败见 `mutation-results.json`、`mutate-t9.log`。临时目录在 `/var/folders/.../v9t9-mutations-*` 下，运行后删除。

## 7) 观察与限制（非阻塞）

1. `positions` 只含 `(h,w)`，**不含帧索引**；帧索引必须由 `run_lengths` 逐位置累加解码（本复核已按该法验证可逆）。
   若下游需要直接帧索引，建议后续卡在输出中显式给出或在文档写明解码规则。
2. 长游程 restoration 误差可超过 τ（作者报告已说明；语义上 merged 帧相对上一帧 diff<τ、restoration 取 run 的保留 token 值，
   本复核确认行为符合登记；消费者不得假设全局 `max|video−restoration| ≤ τ`）。
3. `tau >= 0` 用 `assert` 校验：`python -O` 下会关闭断言（参考实现可接受，生产接口建议显式异常）。
4. shape 解包在 `ndim` 断言之前发生：非 4D 输入抛 `ValueError` 而非 AssertionError（错误类型不一致，非安全漏洞）。
5. 仅支持单个 4D 张量；混合长度批次以 AttributeError fail-closed（无静默错误结果）。如需批量 API 需另开卡。
6. 本卡未验证：真实 V-JEPA 特征上的精度/吞吐（GPU 实测不在授权范围）、真实视频/数据集、整数/半精度 dtype、
   runtime 端到端接入、消费者兼容。

## 8) 产物与命令

- 报告：`reports/V-V9-T8/REPORT.md`（本文件）、`报告.md`（字节相同副本）、`SHA256SUMS`
- 脚本：`reports/V-V9-T8/verify_t9.py`（`--verify` 独立复核；`--mutate` 故意改坏对照）
- 证据：`case-results.json`（11 用例逐项检查 + import purity + case_metrics）、`mutation-results.json`、
  `verify-t9.log`、`mutate-t9.log`、`pytest-author.log`、`input-identities.json`、`metrics.json`/`指标.json`、
  `baseline-worktree.txt`
- 实际命令：
  - `PYTHONDONTWRITEBYTECODE=1 python3 reports/V-V9-T8/verify_t9.py --verify` → exit 0（11 用例 / 0 失败）
  - `PYTHONDONTWRITEBYTECODE=1 python3 reports/V-V9-T8/verify_t9.py --mutate` → exit 0（4/4 变异变红）
  - `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest tests/v9/tokenization/test_rlt.py -q -p no:cacheprovider` → 18 passed, exit 0
- 未提交、未推送、未安装、未下载、未跑模型/GPU、未写生产库/RunStore、未改被验文件。

## 9) 交回统筹

1. 是否按「限纯 CPU numpy 参考实现 + 合成片段」范围验收 T8；§7 观察项是否登记为后续卡（positions 帧索引、assert 校验、
   批量 API）。
2. T8 声明中的 V-JEPA 2.1 精度/吞吐实测与真实数据验证仍为未验证，本复核不外推。
3. 本复核未 accept 自己；建议由一级或另一非作者按本报告与证据复核后决定。
