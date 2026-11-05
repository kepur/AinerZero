# ainerzero.V9.B3 独立复核报告：ainzerzero.V9.B2 五个接口合同防绕过

- **复核任务**：`ainerzero.V9.B3`
- **被复核任务**：`ainerzero.V9.B2`（作者：`mimo-5fb1`，状态：reported/待验收）
- **复核者**：`verify-b3-0001`（二级执行层，非作者）
- **时间**：2026-10-20
- **复核结论**：**建议验收（Recommended for Acceptance）**
- **执行环境**：纯 CPU，无 GPU，无训练，无 MLX/ORT/torch，无网络下载，只读核验被验文件

---

## 1. 摘要

针对任务卡要求的五个绕过向量（真值注入、帧号冒充时间、final 分区写入、未声明预训练、外挂引用/信号/预算/版本泄露），复核方从零构建独立对抗脚本 `reports/V-V9-B2/run_adverse.py`，对 B2 交付的接口与假实现执行 **17 个不利反例**，每个都在独立 OS 子进程中真实运行并产生 **非零退出码（exit 1）**，无一被绕过、无崩溃。

作者契约测试 `tests/v9/contracts` 全量 **160 passed / 0 failed**，ruff 对 `interfaces/` + `fakes/` + `__init__.py` **0 错误**；导入面探针无 MLX/ORT/torch。

### 核心指标

| 复核项 | 门槛 | 实际 | 判定 |
|---|---|---|---|
| 不利反例数量 | ≥6 | **17** | 通过 |
| 全部真实非零退出 | 100% | **17/17 (exit 1)** | 通过 |
| 崩溃/意外 | 0 | **0** | 通过 |
| 作者契约测试复跑 | 160 passed | **160 passed** | 通过 |
| ruff (interfaces+fakes) | 0 | **0** | 通过 |
| 源码修改 | 0 | **0（仅 reports/V-V9-B2/）** | 通过 |

---

## 2. 输入文件身份（只读核对，SHA-256）

| 输入 | SHA-256 |
|---|---|
| `src/ainerzero/v9/interfaces/world_brain.py` | `454a6818f17f46449e4fa46be43bb4160e6c90d68cf56f446b0565f382882c1b` |
| `src/ainerzero/v9/interfaces/validation.py` | `5e5b9423e8c935056d8a7bd5f3b0225972c8cbc3ce8381bf9a49508ced06d831` |
| `src/ainerzero/v9/interfaces/errors.py` | `247da064945ee93b6ee8b193e0fca676ccdd624c5831d5ab7d6b760937a447f7` |
| `src/ainerzero/v9/interfaces/spatial_memory.py` | `f957fbfc7580b1aa43f859c05f56620a5a7fda20c16c1c7da0be8dd1597645a0` |
| `src/ainerzero/v9/interfaces/perception.py` | `106e163730333159dd08d3799c15ddf1ce25759d870c49f54b20990dc1bc2f8e` |
| `src/ainerzero/v9/interfaces/planner.py` | `59cf46a57cca274fbab739552598dea3043f6093fbe98fab4bd0d1439090d35c` |
| `src/ainerzero/v9/interfaces/scheduler.py` | `2470293cc4701a44894c0594cd246962d89ffbdd8e46725063dfeccfdcdbd8be` |
| `src/ainerzero/v9/interfaces/types.py` | `29370940bb9d5ce1ceed739f16e2b8607533d549198ff8f8525b19633123c172` |
| `src/ainerzero/v9/fakes/world_brain.py` | `7a5ad66d06fec926ecc955663fbf2deb7c532444d129e330e819decdd059dd93` |
| `src/ainerzero/v9/fakes/spatial_memory.py` | `16dcbd77f449693b8f42a1c7827ab9c912d362d33d86688fa64eb48e5a351516` |
| `src/ainerzero/v9/fakes/perception.py` | `38b5726a1cb87e95e3b1ed743842aeb1addd3b0ff0987e88c4c42679987b9a52` |
| `src/ainerzero/v9/fakes/planner.py` | `2f9b0f2cec337378722f40bba5a73de15913cea8ed0032a0648af0e1704b744b` |
| `src/ainerzero/v9/fakes/scheduler.py` | `f7b4ced3895a024ec39ac4f1320d50b141e7fddc7ceec8dd81cd5b53329e7bb0` |

AWZ 只读参考未修改；AWZ 漏洞规则 SHA 与 B2 常量一致：`5a53affd4ee437ba130d9ebddc066f71d50a30598caa6b2d1ffedf392fbe931d`。

---

## 3. 对抗不利反例清单（17 个，全部 exit 1）

| # | ID | 攻击向量 | 预期拒绝码 | 退出码 |
|---|---|---|---|---|
| 1 | `adv_wb_truth_injection` | WorldBrain.step 载荷夹带 `position` 真值键 | `truth_field_rejected` | 1 |
| 2 | `adv_wb_envelope_injection` | 传入整包 ObservationPacket 信封 | `envelope_rejected` | 1 |
| 3 | `adv_wb_snapshot_injection` | 载荷带 `schema_version=awz.world_snapshot.*` | `snapshot_rejected` | 1 |
| 4 | `adv_wb_backwards_time` | episode 内 t_ticks 倒流 (10→5) | `time_whitelist_rejected` | 1 |
| 5 | `adv_wb_inconsistent_dt` | dt_s 与 dt_ticks/120 不一致（帧率冒充） | `time_whitelist_rejected` | 1 |
| 6 | `adv_final_partition_write` | SpatialMemory.write 分区 `final` | `partition_write_rejected` | 1 |
| 7 | `adv_final_partition_disguised` | 分区大小写/空白变体 (`Final`/`final ` 等) | `partition_write_rejected`/`ValueError` | 1 |
| 8 | `adv_encoder_undeclared_pretrained` | EncoderDescriptor external_pretrained=True 无 source/license | `ValueError` | 1 |
| 9 | `adv_perception_private_reference` | resolve_reference `private/...` | `reference_rejected` | 1 |
| 10 | `adv_perception_future_reference` | 引用 stamped t999 > packet cut t10 | `reference_rejected` | 1 |
| 11 | `adv_perception_absolute_reference` | 绝对路径 `/etc/passwd` | `reference_rejected` | 1 |
| 12 | `adv_planner_truth_in_goal` | 规划 goal 夹带 `position` 真值键 | `truth_field_rejected` | 1 |
| 13 | `adv_planner_missing_budget` | PlanBudget 缺少顶层 level 预算 | `contract_violation` | 1 |
| 14 | `adv_scheduler_world_signal` | UpdateSignal detail 夹带 event_id/hidden_contact | `signal_rejected` | 1 |
| 15 | `adv_scheduler_forbidden_key_in_detail` | 信号 detail 夹带 `position` | `signal_rejected` | 1 |
| 16 | `adv_spatial_foreign_version_leak` | 跨 encoder 版本查询必须排除并报告 | `encoder_version_mismatch` (excluded) | 1 |
| 17 | `adv_spatial_teacher_promotion` | producer=teacher_model 提升 SLOW | `ValueError` | 1 |

全部 17 例在独立子进程真实退出 `exit 1`，无布尔模拟；结果见 `adverse_results.json`。

---

## 4. 作者契约测试复跑

```
.venv-ainerzero/bin/python -m pytest tests/v9/contracts -q
# 160 passed in 0.48s
.venv-ainerzero/bin/python -m ruff check src/ainerzero/v9/interfaces src/ainerzero/v9/fakes src/ainerzero/v9/__init__.py
# All checks passed!
```

导入面探针（子进程）：`import ainerzero.v9` 后 `sys.modules` 不含 mlx/onnxruntime/torch/tensorflow/jax；`ainzero.v9.fakes` 不被自动导入（分层声明）。

---

## 5. 未验证项与限制

- 本复核只针对接口/假实现合同，不验证真实几何/教师/分词实现（G1/T2/T8 各自有卡）。
- 未对 AWZ 评测包做运行时验证（只读 SHA 核对）。
- 未执行训练、未下载/安装、未 git commit/push、未触碰生产 relay 服务。
- 测试通过不等于能力通过；真实能力验收仍在各自卡片。

---

## 6. 交回统筹

- 建议：**accept ainerzero.V9.B2**（17 个不利反例全部真实非零，合同不可绕过）。
- 无参数修改建议；参数 v0 冻结照用。
- 产物：`reports/V-V9-B2/run_adverse.py`、`reports/V-V9-B2/adverse_results.json`、本报告、`metrics.json`。
