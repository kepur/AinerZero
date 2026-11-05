# ainerzero.V9.P9 执行报告：S1 第一阶段运行入口与预登记（纯 CPU，不训练）

角色：executor；负责人：deepseek-flash-a7k2（二级）；时间：2026-10-21（+03:00）
任务状态：reported；实验状态：未执行真实训练（本卡只做数据/预登记/冒烟测量）
任务依据：接力台 ainerzero.V9.P9 任务卡；AinerZero/RESEARCH_LOG.md `R20261021-P1-stageA-budget`（第 731–748 行）；ARCHITECTURE_V9.md §5「S1 的共同口径」；awz.V9.B3 r2（含 awz.V9.B19 修复）、awz.V9.B1 r3 受限出口约定、ainerzero.V9.B2 ObservationPacket/v1.1 消费 gate、ainerzero.V9.A2 冻结清单。参数 v0 `{}` 照用未改。

## 摘要（≤30 行）

1. 新增 CLI 子命令 `ainerzero s1-phase1`（模式 data/smoke/preregister/freeze/verify/train）；所有计算模式先过资源门，再取共享锁 `artifacts/locks/m0-worker.lock`，在 RunStore 登记运行（卡内独立账本 `reports/V9-P9/control.sqlite3`）并预扣预算；`train` 在冻结预登记未获一级批准前拒绝执行（本卡未训练、未更新参数）。
2. 数据：用 AWZ B3 r2 的四个程序化世界工厂（与 `ExamGenerator.build` 同源同种子规则）+ `emit_stream`（B1 r3 HandleAllocator/CounterNoise 约定、A3 校验、B2 消费者 gate）生成 train **2000 世界/9500 packet**、development **200 世界/950 packet**，rounds=1（登记上限 4 之内）；final 未生成、未读取。`dataset_digest = 8234f2f3…ad26`，生成 47.6 s，17 MB。
3. 四臂结构与参数量冻结：arm1 D 候选 **393,232** 参数（A2 冻结清单 9 项逐字节复核，只加载评测）；arm2 等变度量地图 **207,519**；arm3 情景拓扑图 **159,455**；arm4 组合 **274,031**。训练协议统一 AdamW lr=3e-4、batch 16、seq 2、seeds 0/1/2、**updates=3510**（②③④ 完全相同）。
4. 冒烟（每臂只做前向+损失，无梯度/无更新）：单步 2.10–6.96 ms（arm1 1.30 ms），MLX 峰值 3.2 MiB、进程峰值 0.187 GiB；四臂参数 SHA256 前后一致，`gradients_computed=false`、`updated_parameters=false`。
5. 预算：实测估计 **359.93 s** → 截止 `ceil(1.25×)=450 s`，监督 `450+50=500 s`；arm1 截止 2 s/监督 52 s；第一阶段总墙钟 **4099.6 s = 68.3 min ≤ 4 h**（余 2.86 h）。
6. 冻结预登记：`reports/V9-P9/pre_registration.json`，规范 JSON document SHA256 = `32c30f5005a438f759e14641f5ea77b635eb4020af7fa9ba823b7ad05bb74de6`，文件字节 SHA256 = `2602e42c…`；状态 `awaiting_coordinator_approval`（待 V9.P10 非作者对抗复核 + 一级核定）。
7. 真实反例：资源门拒绝（exit 2，进程内存线）、放宽资源线拒绝（exit 2）、共享锁忙拒绝、预算守卫拒绝（RunStore run stopped）、`--mode train` 未批准拒绝（exit 3）；证据在 `reports/V9-P9/evidence/`。
8. 测试：`tests/v9/experiments` **67 passed / 0 failed / 0 skipped**（含指标已知答案与改坏对照、数据集篡改对照、预算/锁/资源门负例），XML 在 `reports/V9-P9/tests-s1.xml`。
9. 未做/限制：真实训练与评测未执行（按卡）；final 未读；AWZ 考场代码未 git 提交，按 24 文件 SHA-256 图钉；relay exec 的 `ps` 组枚举在本机沙箱被拒（`Operation not permitted`），其 supervisor 报 `exit_unconfirmed`，各 exec 由持有者按“进程组已退出”事实手动补归档并写明原因；数据落 `reports/V9-P9/`（任务文件范围），未写 A2 钉选的 `artifacts/control.sqlite3`/旧数据集根。
10. 交回：请一级安排 V9.P10 对抗复核 → 批准预登记 → 发布 V9.P1；并请确认“世界枚举用 r2 工厂 API、rounds=1”与数据落盘位置两处口径。

## 输入身份

| 对象 | 身份 |
|---|---|
| AinerZero 工作树 | 未提交；prereg 绑定 s1 包 11 个源文件 SHA256 + `spec.py` SHA256（见下），不绑定整棵脏树 |
| s1 包源文件 | 见 `metrics.json.source_identity.package_files`；`spec.py` sha256 `ac8dae54…c3aa` |
| AWZ 数据源 | git HEAD `2b0d4f2834298c18b237f7611451d1ec7625bf36`；exams/sensing/protocols 共 24 文件 SHA-256 图，source_map_digest `35c529b9d77d2b84…` |
| 数据集 | `dataset_digest 8234f2f382281f355b662f05f0bb576d5efac4853f732ddf2e1cdfeee083ad26`；manifest 文件 sha256 `ffd2fdf8…` |
| A2 冻结清单 | `reports/V9-baseline/r3/baseline_manifest.json`（hint digest `3481b6ad…45e9`）；D 候选 pilot `pilot-b4e75e9b…` / checkpoint `96b72328…`；tensors sha256 `cbb14d878dfd…`，本次逐字节复核 9 项 pinned 文件 |
| 冻结预登记 | document SHA256 `32c30f50…4de6`；file SHA256 `2602e42c…` |
| 冒烟指标 | `smoke_metrics.json` sha256 `b4e7d121…` |

## 修改文件

- 新增 `src/ainerzero/v9/experiments/__init__.py`、`src/ainerzero/v9/experiments/s1/`：`__init__.py`、`spec.py`（冻结常量）、`resource_gate.py`（资源门+运行期守卫）、`data.py`（数据身份/分区守卫/特征视图）、`awz_export.py`（AWZ 只读生产者）、`arms.py`（四臂模型+A2 身份加载）、`metrics.py`（指标计算）、`prereg.py`（草稿/冻结/校验/SHA256）、`smoke.py`（无更新冒烟）、`worker.py`（RunStore/预算/守卫运行体）、`commands.py`（CLI 实现）。
- 修改 `src/ainerzero/cli.py`：新增 `s1-phase1` 子命令解析与分发（约 +36 行）。
- 新增 `tests/v9/experiments/`：`conftest.py`、`s1_testkit.py`、`test_s1_data.py`、`test_s1_resource_gate.py`、`test_s1_metrics.py`、`test_s1_prereg.py`、`test_s1_ledger_budget_guard.py`。
- 新增 `reports/V9-P9/`（数据集、预登记、冒烟/校验报告、证据、测试 XML、metrics.json）。
- 未改其它源文件、未提交/推送、未下载/安装/付费、未停任何服务。

## 实际执行（命令与结果）

```sh
cd /Users/mac/AinerWorkFlow/AinerZero

# 1) 单元测试（纯 CPU）
PYTHONPATH=src .venv-ainerzero/bin/python -m pytest tests/v9/experiments -q -p no:cacheprovider \
  --junitxml=reports/V9-P9/tests-s1.xml
# -> 67 passed, 0 failed/error/skipped（XML: tests="67" failures="0" errors="0" skipped="0"）

# 2) 数据集（经 relay exec 登记运行；命令内部持锁、RunStore、预算守卫）
python3 /Users/mac/AinerWorkFlow/AinerRelay/bin/relay exec ainerzero.V9.P9 --agent deepseek-flash-a7k2 -- \
  .venv-ainerzero/bin/python -m ainerzero.cli s1-phase1 --mode data --output-root reports/V9-P9
# -> CLI status=completed；worker_exit=0；run_id 070ad2da…，role=auxiliary，reserved 351.7 s；
#    2000 train / 200 dev 世界，9500/950 packet，生成 47.6 s，dataset_digest 8234f2f3…ad26
#    （AWZ 侧实际命令：cwd=AnimeWorldZero，PYTHONPATH=AWZ/python:AinerForge:AinerZero/src，
#     .venv/bin/python -m ainerzero.v9.experiments.s1.awz_export --out-dir <staging>
#     --train-worlds 2000 --development-worlds 200 --rounds-per-world 1 --generator-seed awz-v9-b3-v0）

# 3) 草稿预登记（参数计数 + 数据身份）
.venv-ainerzero/bin/python -m ainerzero.cli s1-phase1 --mode preregister --output-root reports/V9-P9
# -> status=completed；arm1/2/3/4 = 393232/207519/159455/274031；draft_sha256 f0c270c5…

# 4) 无更新冒烟（经 relay exec；四臂仅前向+损失）
python3 /Users/mac/AinerWorkFlow/AinerRelay/bin/relay exec ainerzero.V9.P9 --agent deepseek-flash-a7k2 -- \
  .venv-ainerzero/bin/python -m ainerzero.cli s1-phase1 --mode smoke --output-root reports/V9-P9
# -> CLI status=completed；worker_exit=0；run_id 184.5 s 预留；参数 SHA256 前后一致，无梯度/无更新

# 5) 冻结 + 复验
.venv-ainerzero/bin/python -m ainerzero.cli s1-phase1 --mode freeze --output-root reports/V9-P9
# -> status=completed；updates=3510；deadline=450 s；supervision=500 s；phase_wall=4099.6 s；
#    pre_registration.json（document sha 32c30f50…4de6，file sha 2602e42c…）
.venv-ainerzero/bin/python -m ainerzero.cli s1-phase1 --mode verify --output-root reports/V9-P9
# -> status=completed；prereg_sha256=32c30f50…；dataset digest/文件复核通过；资源门通过；
#    smoke_parameters_unchanged=true

# 6) 真实反例（全部留证 reports/V9-P9/evidence/）
--mode data --limits-file 收紧进程内存到 0.001 GiB   -> exit 2，resource_gate 拒绝
--mode data --limits-file 把 MLX 线从 4 提到 8 GiB     -> exit 2，loosening refused
（另一进程持有 m0-worker.lock 时）--mode data          -> 失败：A worker is already running in this project
--mode smoke --wall-budget-seconds 2（只允许收紧）      -> 预算守卫在模型工作前拒绝，RunStore run=stopped
--mode train（冻结状态 awaiting_coordinator_approval）  -> exit 3，preregistration_not_approved

# 7) 冻结源码一致性检查（无脚本侧副作用）
#    见 evidence/integrity_check.json：prereg 绑定的 11 个包文件 + spec.py 与磁盘一致；ok=true
```

## 验证结果（与验收标准逐条对应）

| 验收项 | 结果 | 证据 |
|---|---|---|
| CLI 子命令经共享锁/RunStore/预算守卫，可由 relay-runner exec 登记 | 通过：data/smoke 均经 `relay exec` 登记（relay exec 记录 7 条，含开始/结束归档）；计算模式持共享锁、RunStore 记 run（completed/failed/stopped 全终态，0 optimizer steps 预留）、预算守卫真实拒绝 | `data_report.json`、`smoke_report.json`、`evidence/relay-execs.json`、`control.sqlite3` |
| 资源门任一不满足真实拒绝启动（给反例） | 通过：进程内存线活体拒绝 exit 2；MLX 线放宽被拒 exit 2；另有锁忙/预算/未批准三个负例 | `evidence/refusal-*.json`、`tests/v9/experiments/test_s1_resource_gate.py` |
| 四臂结构、参数量、超参、种子、步数冻结；训练臂预算相同 | 通过：arm1 393,232（frozen_candidate、0 更新、只评测）；arm2/3/4 = 207,519/159,455/274,031，全部 0.1M–2M；②③④ updates 均为 3510、seeds 0/1/2、AdamW lr 3e-4、batch 16、seq 2；validate() 强制校验 | `pre_registration.json`、`tests/v9/experiments/test_s1_prereg.py` |
| 指标脚本单测含已知答案与改坏对照 | 通过：定位误差、未见地图聚合、拓扑边 precision/recall、少样本转移、样本效率曲线、M2 记忆干扰全部有精确已知答案与“改坏必须变差/变化”的对照；数据/预登记/资源门也各有改坏对照 | `test_s1_metrics.py`（67 项中 12 项指标断言）、`tests-s1.xml` |
| 冒烟实测单步耗时与峰值内存；截止/监督超时按规则冻结且总墙钟 ≤4 h | 通过：四臂前向+损失 step 2.10–6.96 ms（arm1 1.30 ms）；进程峰值 0.187 GiB、MLX 峰值 3.2 MiB；估计 359.93 s→deadline 450 s（×1.25）、supervision 500 s（+50 s）；phase_total 4099.6 s ≤ 14400 s，余 10300.4 s | `smoke_metrics.json`、`pre_registration.json.timing` |
| 未读 final、未更新参数 | 通过：数据集只有 train/development；final 无文件、无加载器（`FinalPartitionSealed`）；冒烟 `gradients_computed=false`、`updated_parameters=false`、四臂参数 SHA256 前后一致；RunStore 全部 auxiliary 运行 optimizer_steps=0 | `smoke_metrics.json`、`data.py` 单测、`control.sqlite3` |
| 预登记文件 SHA256 与完整命令写入报告 | 通过：document/file SHA256 与完整命令见上；`integrity_check.json` 复核冻结源码身份 ok=true | 本报告、`evidence/integrity_check.json` |

### RunStore 运行账本（reports/V9-P9/control.sqlite3）

| run | 状态 | 说明 |
|---|---|---|
| c9fc8e04… | failed | 首次 data 运行（worker 缺 `__main__` 入口，修复后重跑；原始失败原因保留在 relay exec detail） |
| 070ad2da… | completed | data：2000+200 世界数据集，reserved 351.7 s |
| 91edad30… / b175c443… / 3e4cea44… | completed | smoke 三次（前两次为修复前中间版本；最终冻结版本 run `3e4cea44…`，见 smoke_report.json） |
| 91035323… | failed | 预算负例修复前的中间运行（validating→stopped 非法迁移），修复后重跑 |
| 83e9e859… | stopped | 预算守卫负例（`--wall-budget-seconds 2`），模型工作前拒绝 |

所有运行 role=auxiliary、environment_steps=0、optimizer_steps=0、model_transitions=0；本卡**没有更新任何模型参数**。为避免改动 A2 钉选的 `artifacts/control.sqlite3`（其行级摘要属 accepted 基线），账本与数据都放在任务文件范围内。

### relay exec 说明（如实记录）

本机沙箱禁止执行 `ps`（`/bin/ps: Operation not permitted`），relay exec 的进程组确认依赖 `ps` 枚举，因此 supervisor 对每条 exec 报 `exit_unconfirmed`、返回码 1 且不写终态。实际命令本身均正常完成（数据/冒烟 CLI 返回 0，报告为 completed）。按 AGENTS 的收尾要求，持有者用本机事实（`killpg(pgid,0)=ProcessLookupError`，组已退出）逐条补归档终态，`detail` 写明原因；7 条 exec 记录见 `evidence/relay-execs.json`。这是接力台与本机沙箱的交互限制，不是任务状态失败。

## 产物与 SHA256

| 产物 | SHA256 |
|---|---|
| `reports/V9-P9/pre_registration.json`（document canonical） | `32c30f5005a438f759e14641f5ea77b635eb4020af7fa9ba823b7ad05bb74de6` |
| `reports/V9-P9/pre_registration.json`（文件字节） | `2602e42cad7bf39e5b6ac788d19e393dc22f9d0b07cca6c4ef525e0fcb0d76a0` |
| `reports/V9-P9/pre_registration.json.sha256` | `39648a958c1d5a2dfde4fef7827c36e2188526f37d8bb7090d2728e4daf8cf71` |
| `reports/V9-P9/draft_preregistration.json` | `67c297e51dbb6e76848fb7203004df5d8f03d0f3c608813f2635112741972ebf` |
| `reports/V9-P9/smoke_metrics.json` | `b4e7d1218b29652c188425ec6d1def2fe49d8fd1a22e7192d01b705ae4b11ce8` |
| `reports/V9-P9/dataset/dataset_manifest.json` | `ffd2fdf861323f6db13e1336e73e1dd292ecc7874b05af787f1f9945131fa4a9` |
| `reports/V9-P9/dataset/packets/train.jsonl` | `28bedf0e592488ae9d5d533fd519b031491319c61914da7cc9e5ca14f8592178` |
| `reports/V9-P9/dataset/packets/development.jsonl` | `b9420ef5e26a00a29f022f75390cf39ffd36fac1be8b723767fa71250d7a4aa7` |
| `reports/V9-P9/dataset/truth/train.jsonl` | `8fa91cfe4b7366bd9cab3e921b0a307d98426af3ca44934edbf0449c9d1e52e5` |
| `reports/V9-P9/dataset/truth/development.jsonl` | `76b986495229de893fb50e0740296f6414225a06b1b444fa4f20eb43911e26e6` |
| `reports/V9-P9/tests-s1.xml` | `1177a0adc850e83725534e383e06c806e0a163fe8505464d03dbcd6565ea775a` |
| `reports/V9-P9/verify_report.json` | `0df3fa1b14ade61cfc6a32af667387141d363157c76da08373240d558a032213` |
| `reports/V9-P9/metrics.json` | 见 `SHA256SUMS.txt` |
| `reports/V9-P9/evidence/`（12 个文件：资源门/放宽/锁/预算/未批准反例、relay exec 记录、源码一致性、草稿与冻结命令报告、2 个 stderr 日志） | 见 `SHA256SUMS.txt` |

其它：`data_report.json`、`smoke_report.json`、`evidence/preregister_report.json`、`evidence/freeze_report.json`、`evidence/integrity_check.json`、`evidence/relay-execs.json`、`reports/V9-P9/control.sqlite3` 均在目录内，`SHA256SUMS.txt` 覆盖全部证据文件。

## 失败与限制（如实）

1. 早期失败保留于 relay exec 记录与报告备份：①第一次 data 运行 worker 模块缺 `__main__` 入口，CLI 无有效报告；②第二次 data 运行在 finalize 报“payload digest differs from producer list”（生产者与消费者对逐回合摘要的定义不同，已统一为 `sha256(canonical_json([payload,...]))` 并重跑）；③预算负例首次运行因 `validating→stopped` 迁移不存在而崩溃（已改为经 `stopping` 收敛并重跑）。这些中间版本的 `data_report.json` 已被最终成功运行覆盖；原始失败原因保留在 `evidence/relay-execs.json` 的 detail 字段中。
2. 本卡**未训练、未评测、未更新任何参数**；`--mode train` 的实际训练路径已实现但按预登记状态拒绝执行，待 V9.P10 复核与一级批准后由 V9.P1 使用。
3. AWZ 考场代码未提交 git（工作树 untracked），数据身份用 24 个源文件的 SHA-256 图钉 + AWZ HEAD `2b0d4f2…` 表达；不是 git 级不可变保证。
4. 世界数量：B3 的 `generate_suite()` 只实例化 9 个固定场景；本卡按登记上限枚举时直接调用 r2 程序化工厂（`navigation_world/time_world/relation_world/e3_identity_world(partition, scene_id, seed)`），种子命名空间与分区守卫沿用 r2 原实现，未改 AWZ 任何文件；冻结 rounds=1（上限为 4）。此口径请一级确认。
5. B1 r3 路径：使用 r2 `emit_stream`（它内部用 B1 r3 的 `HandleAllocator`/`CounterNoise` 与 A3 校验器）作为受限出口；未直接用 `sensing.SensorExit`（其登记范围是小房间切片，考场世界不是其输入）。此口径请一级确认。
6. 预算“估计”用“前向+损失 step × 3（更新成本因子）÷ 0.25 占空比 × 1.2 评估开销”，未实测反向传播（本卡被要求只做前向+损失）；×3 是保守假设，不是实测值。冒烟本身未做占空比节流（测量模式）；训练循环内按 0.25 节流。
7. 资源门语义：8/4/16/1 GiB 与 0.25 占空比为启动+运行期检查（占空比在启动时为配置上限检查、训练时为节流）；交换区增长按现有 pilot_worker 登记语义取“本次运行起点基线”，不是整次开机基线。
8. A2 全清单 497 文件未全量重算（那会触碰 A2 复核的工作量）；D 候选的 9 项 pinned 文件已逐字节复核；A2 `manifest_digest` 作为 hint 记录在预登记中。
9. 数据与账本放在 `reports/V9-P9/`（任务文件范围）；没有写入历史 `artifacts/` 数据集根，也未改 A2 钉选的 `artifacts/control.sqlite3`。若一级要求数据进 `artifacts/`，需另行登记文件范围与 A2 基线处理方式。
10. 在本机沙箱下 relay exec 无法确认进程组空（`ps` 被拒），见上；这会影响接力台对 exec 终态的自动归档，需要环境/接力台侧处理，本卡已如实留证。
11. 工作树在开工前已含其他卡未提交改动（CLAUDE.md、COORDINATION.md 等）；本卡只改上述文件，未提交、未推送。

## 交回统筹

1. 请安排 **V9.P10 非作者对抗复核**（运行监督代码 + 预登记 + 冒烟证据），重点：资源门反例、预算守卫、RunStore 账本、冒烟“未更新参数”、四臂预算相同、final 未读；复核通过后由一级核定 `pre_registration.json`（document SHA256 `32c30f50…4de6`）并发布 V9.P1。
2. 请确认两处口径：①世界枚举使用 r2 程序化工厂 API（`scene_id` 展开，2000/200，rounds=1）是否符合 B3“考场生成器”登记意图；②冻结数据落盘在 `reports/V9-P9/` 还是应改到 `artifacts/`（若改，需要 A2 基线登记方式）。
3. 预登记中 arm1 明确标注“不可比”（C0 符号观察输入，无地图/拓扑/位姿输出），只做 A2 身份复验与自带 C0 诊断；S1 指标不适用于它。
4. 若一级同意，V9.P1 的 9 次训练 + arm1 评测请使用本报告的 `--mode` 入口与冻结文件；任何扩预算/改上限/重跑需另行登记，本卡不放宽。
