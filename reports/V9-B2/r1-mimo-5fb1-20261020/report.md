# ainerzero.V9.B2 执行报告

```markdown
# ainerzero.V9.B2 执行报告
角色：executor；负责人：mimo-5fb1（tier 2, kind=mimo）；时间：2026-10-20
任务状态：reported；实验状态：未执行（纯 CPU 契约卡，无训练/无模型运行）
任务依据：接力台任务 ainerzero.V9.B2（参数 v0，冻结，未改动）；ARCHITECTURE_V9 r5 §3 接口表与 §4 数学约定；D-021 放行本卡的代码闸门；文件范围仅 src/ainerzero/v9/{__init__.py,interfaces/,fakes/}、tests/v9/contracts/、reports/V9-B2/
输入身份：见下方「输入身份」与 source-sha256.json（AWZ 源 SHA + 本卡自有文件 SHA）
修改文件：仅新增本卡范围内文件；未触碰 geometry/（G1）、teachers/（T2）、tokenization/（T8）及其测试
实际执行：见「实际执行」命令清单；无训练、无下载、无安装、无 git commit/push、未触碰生产 relay 服务
验证结果：契约测试 160 passed / 0 failed / 0 skipped；ruff 干净；控制组绿；10/10 故意改坏全部变红；导入面探针无 MLX/ORT/torch
产物：reports/V9-B2/r1-mimo-5fb1-20261020/（report.md、metrics.json、checks.json、mutation-results.json、source-sha256.json、run_checks.py、run_mutations.py）
失败与限制：见「失败与限制」（心跳退回重领、接口决策待统筹确认、未验证项清单）；测试通过不等于能力通过
交回统筹：见「交回统筹」5 个问题；未擅自追加运行或改参数
```

## 摘要（≤30 行）

1. 交付 r5 §3 的**七个可替换接口**（`WorldBrainAdapter`、`GeometryCore`、`TimeScaleAdapter`、
   `SpatialMemory`、`PerceptionEncoder`、`HierarchicalPlanner`、`UpdateScheduler`）＋共享类型
   （`interfaces/types.py`）、带稳定 `code` 的拒绝型错误层（`interfaces/errors.py`）、
   ObservationPacket/v1.1 载荷闸门（`interfaces/validation.py`，内嵌 AWZ L1–L10 冻结副本）。
2. 交付七个 **CPU 假实现**（`src/ainerzero/v9/fakes/`，仅依赖 interfaces + numpy）：
   SE(2) 解析几何（含重力对齐抬升、Joseph 更新、`F=Ad(U⁻¹)`）、120 Hz 时间层、
   分区封印＋版本围栏的空间记忆、来源声明＋RLT 留存记账的编码器、逐级预算的规划器、
   `f_max`/`u_max` 冻结阈值的学习侧调度器、组合式 WorldBrain。
3. 交付契约测试 `tests/v9/contracts/`：**9 个文件 160 个测试**，每个契约同时有正例与反例
   （反例必须抛出带稳定 `code` 的拒绝）。
4. 验证：`pytest tests/v9/contracts` **160 passed / 0 failed / 0 skipped**；`ruff check` 对本卡
   文件 **0 错误**；子进程探针确认 `import ainerzero.v9` / `ainzero.v9.fakes` 不引入
   MLX/ONNX Runtime/torch/tensorflow/jax。
5. 故意改坏控制（`run_mutations.py`）：控制副本（未改）**绿**，**10/10 个功能变异全部变红**，
   且每个变异都能指认到预期失败的测试；变异只施加在临时目录的整包副本上（PYTHONPATH 遮蔽），
   生产源码零改动。
6. 与 G1（`ainzero.v9.geometry`，只读交叉核对）数值一致：exp/log/compose/adjoint/predict/
   update/with_side 在登记容差内完全吻合（1e-10 ~ 1e-12）。
7. `tests/v9` 全量：348 passed / 12 failed——12 个失败**全部**在 `tests/v9/teachers/test_cache.py`，
   原因是环境缺 `jsonschema`（`jsonschema_available=false`），属既有环境缺口、在本卡文件范围外。
8. 需统筹确认的接口决策 6 条见下文；测试通过不等于能力通过，真实实现与能力验收仍在各自卡片。

## 输入身份

| 输入 | SHA-256 |
| --- | --- |
| `AnimeWorldZero/contracts/v9/observation_leak_rules.v1_1.json` | `5a53affd4ee437ba130d9ebddc066f71d50a30598caa6b2d1ffedf392fbe931d`（与 `LEAK_RULE_SOURCE_SHA256` 常量一致，漂移测试钉死） |
| `AnimeWorldZero/contracts/v9/observation_packet.v1_1.schema.json` | `01be45e0adfdac74d00d3f4affd2dce52ce5596f23c3def974b14998bd0830eb` |
| `AnimeWorldZero/.../valid/packet_student.json`、`packet_c0_start_baseline.json` | 见 `source-sha256.json` → `awz_inputs` |
| 只读参考：G1 `src/ainerzero/v9/geometry/{README.md,lie.py,belief.py}` | 见 `source-sha256.json`（G1 文件本卡未修改） |
| 本卡新增/修改的全部文件 | 见 `source-sha256.json` → `owned_files`（报告生成后重跑 `run_checks.py` 刷新） |

任务参数：`v0 {}` 冻结，未修改；如觉参数不妥在本报告提出，不自行改（无此意见）。

## 修改文件

| 路径 | 目的 |
| --- | --- |
| `src/ainerzero/v9/__init__.py` | 包入口：`INTERFACES`（7 元组）、`LAYERING` 导入预算声明；不自动导入 fakes |
| `src/ainerzero/v9/interfaces/`（11 文件） | 7 个 ABC ＋ `types.py`（25 个共享类型）＋ `errors.py`（17 类稳定 code 拒绝）＋ `validation.py`（载荷闸门/泄漏规则/引用裁决） |
| `src/ainerzero/v9/fakes/`（8 文件） | 7 个 CPU 假实现 ＋ `FAKES` 映射 |
| `tests/v9/contracts/`（10 文件） | conftest ＋ 9 个契约测试文件，160 个测试 |
| `reports/V9-B2/r1-mimo-5fb1-20261020/` | `run_checks.py`、`run_mutations.py`、`report.md`、`metrics.json`、`checks.json`、`mutation-results.json`、`source-sha256.json` |

**未修改**（D-021 范围禁令遵守情况）：`src/ainerzero/v9/geometry/`、`teachers/`、`tokenization/`
及其测试目录一次未写；AWZ 仓库只读打开；无删除、无 git 提交/推送。

合计新增代码约 5,608 行（含测试与报告脚本）。

## 实际执行

```bash
# 环境（项目自带 venv，未安装任何新包）
.venv-ainerzero/bin/python -V            # 3.12.x, numpy 2.5.3, pytest 9.1.1

# 静态与契约验证（本卡报告脚本，写 checks.json + source-sha256.json）
.venv-ainerzero/bin/python reports/V9-B2/r1-mimo-5fb1-20261020/run_checks.py      # exit 0

# 分项命令（run_checks.py 内部执行的等价命令）
.venv-ainerzero/bin/python -m ruff check src/ainerzero/v9/__init__.py \
    src/ainerzero/v9/interfaces src/ainerzero/v9/fakes tests/v9/contracts reports/V9-B2  # 0
.venv-ainerzero/bin/python -m pytest tests/v9/contracts -q                              # 160 passed
.venv-ainerzero/bin/python -m pytest tests/v9 -q          # 348 passed, 12 failed（既有 jsonschema 缺口）

# 故意改坏必须变红（控制组 + 10 个变异，临时目录整包遮蔽）
.venv-ainerzero/bin/python reports/V9-B2/r1-mimo-5fb1-20261020/run_mutations.py    # exit 0, 10/10 caught
```

接力台：`relay heartbeat ainerzero.V9.B2 --agent mimo-5fb1`（前台命令 + 每 300 秒后台循环）；
本卡无 `relay ask` 事项（无参数问题）、无 `relay exec`、无训练/预算调用。

## 验证结果

### 契约测试（正例 + 反例）

`pytest tests/v9/contracts` → **160 passed / 0 failed / 0 skipped / 0 error**，分布：

| 文件 | 数量 | 覆盖契约 |
| --- | --- | --- |
| `test_payload_gate.py` | 23 | 载荷白名单、时间白名单、L1–L10、引用命名空间/时间裁决、AWZ 漂移钉死与 20 个 AWZ 示例分类 |
| `test_world_brain.py` | 11 | step/reset/propose；信封、快照、真值键、时间倒流、提案 TTL/证据摘要反例 |
| `test_geometry_contract.py` | 36 | 群代数、群作用、规范形、predict/update/with_side、显式重力、构造守卫；G1 数值交叉核对 |
| `test_timescale_contract.py` | 14 | 120 Hz 显式 dt 对齐、两条冻结宏规则、空动作/未知类/非法 tick 反例 |
| `test_spatial_memory.py` | 20 | 分区封印、平移等变查询、编码器版本围栏、预算不超、晋级证据与 teacher/LLM 拒绝 |
| `test_perception_contract.py` | 12 | 来源/许可声明、RLT 留存跨调用记账、私有/远程/未来引用反例 |
| `test_planner_contract.py` | 12 | 逐级预算、耗尽回退、子目标无真值键扫描、缺预算/真值目标反例 |
| `test_scheduler_contract.py` | 23 | 三种信号源、`bn-` 前缀、信念图闭包、超 `f_max` 全量回退、阈值冻结、世界侧载荷反例 |
| `test_interface_surface.py` | 9 | 7 接口 ABC 面、一一对应假实现、子进程无框架导入、静态导入扫描 |

**每个契约都有反例**：所有拒绝型断言都断言到稳定 `code`（如 `envelope_rejected`、
`truth_field_rejected`、`singular_measurement_noise`、`partition_write_rejected`、
`signal_rejected`、`reference_rejected`），不靠错误文案匹配。

### 故意改坏必须变红（`mutation-results.json`）

| 变异 | 目标测试 | 结果 |
| --- | --- | --- |
| M1 拆掉 WorldBrain 载荷闸门 | `test_step_rejects_whole_envelope` | RED caught |
| M2 放行倒流时间 | `test_step_rejects_backwards_time` | RED caught |
| M3 逆元返回转置 | `test_compose_inverse_is_identity` | RED caught |
| M4 规范化退化为恒等 | `test_canonicalize_actually_changes_coordinates` | RED caught |
| M5 delta_s 改用帧号 | `test_align_reports_real_dt_not_the_stride` | RED caught |
| M6 拆掉 final 分区封印 | `test_write_refuses_non_allowlisted_partitions` | RED caught |
| M7 拆掉编码器版本围栏 | `test_query_excludes_foreign_encoder_version` | RED caught |
| M8 拆掉引用命名空间/时间裁决 | `test_encode_resolves_only_registered_namespaces` | RED caught |
| M9 子目标注入真值键 | `test_emitted_subgoals_have_no_truth_keys` | RED caught |
| M10 拆掉世界侧信号扫描 | `test_world_side_signal_payloads_are_refused` | RED caught |
| 控制（整包副本未改动） | 全部 | GREEN（遮蔽生效的证据） |

锚点唯一性校验：每个变异的 `old` 文本必须恰出现 1 次，否则脚本直接非零退出（防源码漂移后变异空转）。

### 无框架导入（子进程探针）

`import ainerzero.v9` 后 `sys.modules` 不含 `mlx`/`onnxruntime`/`torch`/`tensorflow`/`jax`，
且 `ainzero.v9.fakes` **不在** `sys.modules`（分层声明：契约层不自动拉假实现）；
`from ainerzero.v9 import fakes` 同样零框架。另有静态正则扫描（`^\s*(import|from)\s+(框架)`）
覆盖 `interfaces/` 与 `fakes/` 全部 `.py`。

## 交回统筹的接口决策（需确认，未自行扩范围）

1. `GeometryCore` 抽象面 = `compose/inverse/exp/log/adjoint/act/predict/update/with_side/
   canonicalize/decanonicalize` + `gravity` 属性 + `supported()`；比 §3「示意」多出
   `act`、`with_side`、`supported`；`predict(belief, motion, dt)`、`update(belief, obs, model{H,R})`
   签名取 G1 已接受语义（body twist + 显式 H/R）。
2. `PoseBelief.side ∈ {right,left}`：除 `with_side` 外一切入口拒绝左手信念（`require_belief(..., side="right")`），
   换边满足 `P_l = Ad(μ) P_r Ad(μ)ᵀ`。
3. 噪声奇异/为零的量测必须拒绝 → 新增类型 `SingularMeasurementNoise(code=singular_measurement_noise)`
   （§4.7 C1 的可断言载体）。
4. `SpatialMemory` 新增接口方法 `parameter_fingerprint()`；查询**恒定**按编码器版本过滤，
   异版本条目进 `QueryResult.excluded`（拒绝解释且不静默丢弃），无任何「跳过过滤」开关。
5. 写分区 fail-closed 白名单 `WRITABLE_PARTITIONS=("train","development")`；
   调度器种子必须 `bn-` 前缀（信念节点），其余 `SignalRejected`。
6. 载荷闸门按 schema `additionalProperties=false` 收紧为「恰好 8 个白名单字段」；
   时间白名单恰为 `{sim_hz,t_ticks,dt_ticks,dt_s}` 且 `dt_s == dt_ticks/120`。

## 失败与限制

- **心跳退回**：执行记录 #1 因 20 分钟无心跳 stalled 退回（`relay show` 可见）。同一 agent
  （mimo-5fb1）以原令牌重新领取，已写文件未丢失；此后改为每 300 秒后台心跳循环（日志
  `/private/var/folders/.../T/opencode/hb-B2.log`）。如实留档，不掩饰。
- **AWZ invalid 示例的消费者侧分类**：18 个 invalid 示例中，整份文档 18/18 被本闸门拒绝
  （信封层）；其中 10 个连 `payload` 单独也拒绝。其余 8 个
  （`actor_missing`、`actor_unknown_kind`、`channel_not_allowed`、`episode_id_uuid5`、
  `old_native_origin`、`origin_observed`、`payload_time_mismatch`、`seq0_payload_dt_nonzero`）
  的违规信息**只在信封/生产者侧**（actor/origin/seq/信道允许表/信封 dt 交叉核对/首包 dt），
  消费者拿不到信封，按 A2/A7 与 L7 属生产者契约，不在本卡范围；已在
  `test_awz_example_packets_are_classified_the_same` 中显式断言并注释，不冒充全覆盖。
- **未验证 / 不在本卡**：真实 RLT 分词（T8）、真实资产解析器（awz.V9.A3/B1 必须在真实加载路径测）、
  `skill_proposal.v1` 全 schema 符合性（B1）、SE(3)/任意重力方向的几何（G1）、
  任何模型能力（`测试通过不等于能力通过`）、独立复核（应由不同 agent 出验证任务）。
- 假实现是**测试替身**：SE(2) 单群、重力固定 (0,0,-1)、零运动传播；不能当研究实现引用。
- `tests/v9` 全量 12 个既有失败全部来自 `tests/v9/teachers/test_cache.py`（缺 `jsonschema`），
  在本卡文件范围外，未修（不越权），留作统筹决定是否补环境。
- 环境记录：numpy 2.5.3 / pytest 9.1.1 / ruff（dev 组）；未下载、未安装、未支付、未开网络。

## 交回统筹

1. 确认上面 6 条接口决策（尤其 1/3/4：`act`/`with_side` 入面、`SingularMeasurementNoise` 新类型、
   `parameter_fingerprint` 入面与「excluded 而非抛异常」的版本围栏）。
2. AWZ invalid 示例的 8 个「信封侧」违规是否需要本卡消费者侧也补（若要，需参数变更走统筹）。
3. `tests/v9/teachers/test_cache.py` 的 `jsonschema` 环境缺口由谁补（非本卡范围）。
4. 建议后续验证任务（不同 agent）：独立复核本卡报告 + 对同一套变异做黑盒重跑。
5. 本卡未做任何训练/下载/提交；如需扩展到 SE(3) 或真实分词接入，另开卡片。

（任务参数 v0 未改动；未擅自追加运行或换参数。）
