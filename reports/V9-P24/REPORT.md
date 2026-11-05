# P24 独立非作者复核：S1 r8（完成事务、合法状态、D 预算、单次守卫、字段契约、信任根、CPU 惰性隔离）

自证：本报告执行者为 `deepseek-flash-0hyx`，**不在**排除名单（claude、codex、deepseek-r7xq、deepseek-v41f-w3q7、ds-s1r8-1200、gemini-b7m9、glm-p23b-1200、minimax-p21-1022am、step5-9f2k）内，也不是上述任一身份/会话的换名或同会话代理；与 P15/r8 作者无共享会话、未领取过该卡。全部结论来自本次独立脚本输出。

## 结论

**不建议通过。** F1、F2、F4、F5、F6、F7、F8 与全部身份/冻结约束通过；**F3 的“先 D 后 train”注册顺序在真实公开路径上失败，属于阻断项**：

```
d_then_train: LifecycleError: experiment_id already exists: s1-phase1-20261021
train_then_d: 通过
```

S1-R8-DECISION F3 明文要求“共享 TRAIN 实验 manifest 应稳定…测试先 D 后 train 与先 train 后 D 都不冲突”。当前实现只在“先 train”方向成立，故 r8 不满足该条。r8 不适合以 `completed` 状态提交验收；其余各项证据充分，可供作者只修该点后重交。

## 复核范围与方法

- 只写 `reports/V9-P24/`；未改源码、未写真实中央台账/批准行、未动 r4–r7/P21 原件、未改 updates=3510/seeds/450/2/48/14400、未下载/安装、未启动 P1、未做真实 MLX 前向/训练/评测/final、未生成新数据。
- 72 个钉扎文件与 21 个绑定文件 SHA 由本会话脚本独立复算并直接粘贴输出，不引用作者数字。
- 每项 F1–F8 的反例由本会话按决策原文另写（不同注入点、不同数值、不调用作者测试断言）；每项再在**隔离源码副本**里只改一处守卫条件做坏控，要求同一探针由绿转红。
- 环境：`.venv/bin/python` 3.12.2，git HEAD `2de6cae`（工作区在复核前后均为 dirty；身份判定以 r8 清单的字节哈希为准，不作 clean-git 声明）。复核前与交报告前各复算一次 72 钉扎，两次全匹配。

## 1. 冻结来源与身份

原文命令与输出（`reports/V9-P24/logs/pinned-sha-recompute.txt` 末尾）：

```
$ .venv/bin/python reports/V9-P24/harness/verify_pinned.py
file_sha256 declared : e8cfa2390624fdf6e82829a658942e11bc012043ae8fba5602d76d9189c8114a
doc_sha256  declared : 2082e2a3c36cd648fb1608727a7f8ea0fc9afcc38e29af527c48d62f5d477175
doc_sha256  sidecar  : 2082e2a3c36cd648fb1608727a7f8ea0fc9afcc38e29af527c48d62f5d477175
status               : awaiting_coordinator_approval
pinned_all_match     : True
bound_all_match      : True
```

- 钉扎 **72/72** 匹配（0 不匹配）；作者 `reports/V9-P9/r8/source-identity.json`（SHA `17d70c72…5c19`）声明的绑定文件 **21/21** 匹配。
- 冻结文档 `artifacts/v9/s1/phase1/r8/pre_registration.json`：文档摘要 `2082e2a3…7175`，文件 SHA `e8cfa239…114a`，sidecar 同为 `2082e2a3…7175`，状态 `awaiting_coordinator_approval`（未改动）。
- CLI 只读 `verify`：`status=completed`、`source_binding=passed`、`approval=False`（`logs/verify-r8.json`）。
- 未发现 r7→r8 有 allowlist 外科举变化。独立逐叶差异（`harness/leaf_diff.py`，空容器计为叶）：

```
r7_leaves 391 / r8_leaves 398 / changed_leaves 15
outside_allowlist_empty: true
scientific_fields_equal: true
document/file SHA: 2082e2a3…7175 / e8cfa239…114a
bound_files 21/21 match, spec_sha_matches: true
```

15 个变化叶全部落在 `created_unix`、`source_identity.package_files.*`、`source_identity.package_map_digest`、`source_identity.spec.sha256`；无任何科学参数叶变化。作者报告的“398 叶、15 变”与本会话一致（本会话 r7 391 叶，早前 394 的说法是按含空容器口径的中间值，最终以本脚本为准，结论不变）。

## 2. F1 完成事务（通过）

`--case f1` 三个慢动作切点各自独立建库、独立注入，并在切点后再调用一次终态事务模拟“重跑”：

| 切点 | 报告 | 台账行 | 重跑后行数 | 重跑后同 run 行 | marker |
|---|---|---|---|---|---|
| before_commit | failed / completion_deadline_exceeded | failed | 1 | 1 | completion_invalid.json |
| inside_commit_sql_lock（外部 BEGIN IMMEDIATE 持锁 0.65s，协议 0.30s） | failed，`expired_in_flight=true` | completed，reason 未改写，`rolled_back=false` | 1 | 1 | completion_invalid.json |
| after_commit_write_returned（提交落地后时钟跳 2s） | failed，`expired_in_flight=true` | completed，`rolled_back=false` | 1 | 1 | completion_invalid.json |

- 三切点重跑均**没有**第二条登记行，marker 保留，已提交行不被改写。
- 坏控：禁用 `completion.py` 的 deadline 拒绝后同一探针转红。
- **诚实边界**：`before_commit` 切点后重跑内部 `_complete_run` 会返回 `status=completed`，而该 run 行仍是 `failed` 且 marker 在。公开 `run_worker` 在到达该内部缝之前就被 `already_attempted` 拒绝（F8 已证），消费者也因 marker 拒绝；故不构成“接受未完成 run”，但这是内部缝的一处不一致，建议作者一并收紧，不单独作为阻断。

## 3. F2 合法状态表（通过）

8 个活动态（created/initializing/collecting/training/validating/pausing/paused/stopping）各按 1000s 计入；3 个终态 completed/failed/stopped 各 125s；`None` 与伪造 `quarantined` 均抛 `LedgerStateInvalid`。未复用作者的 200s/边界表。坏控：把 `ACTIVE_STATES` 还原成 r7 缺 collecting/validating/stopping 的集合 → 探针转红。

## 4. F3 D 预算（通过）与注册顺序（阻断）

预算部分（`--case f3`）：2.0s 工作截止下，D 实际预留 `reserved_active_seconds=1.0`、`reserved_optimizer_steps=0`、真实快照 `max_wall_seconds=2.0`、`arm_id=arm1`、只调用 1 次 D 前向，无 5s 保底、无 eval 默认 300s。坏控：恢复 `max(5.0, min(0.5*budget, …))` 保底 → 探针转红。

注册顺序（`--case order`，独立临时库，不碰中央台账）：

```
train_then_d: {"passed": true,  "train_run": "a10784ab…", "d_run": "ea4c37bc…"}
d_then_train: {"passed": false, "error": "LifecycleError: experiment_id already exists: s1-phase1-20261021"}
```

复现路径（公开方法，非手工造行）：先 `ledger.open_aux_run(mode="eval", experiment_id=TRAIN_EXPERIMENT_ID, request_id=f"{TRAIN_EXPERIMENT_ID}:eval:arm1", snapshot_extra={"arm_id":"arm1",…})` 并完成 D，再 `worker._open_train_run(document, ledger, approval, arm_id="arm2", seed=0)`。

根因（只读定位）：

- `src/ainerzero/v9/experiments/s1/worker.py:567-573`：`open_aux_run` 发现 experiment 不存在时**自动创建** `s1-phase1-20261021`；
- 同文件 `:1391-1397`：`_open_train_run` **无条件** `store.create_experiment(...TRAIN_EXPERIMENT_ID)`，同一 ID 已存在即抛 `LifecycleError`。

影响：任何先于 train 打开、且挂在 TRAIN 实验下的子 run（D 预检，或其它 aux 角色）都会把后续 train 卡死；这正是 F3 要求消除的“按新实验 ID 重置尝试/总账”的反面。**判定：不通过，阻断。**

## 5. F4 单次 D 守卫（通过）

由产品自身 `open_aux_run(snapshot_extra=arm_id/seed/purpose)` 生成含 `arm_id=arm1` 的真实行：第一次 `completed`；第二次 `refused / already_attempted`；arm1 行数 1→1，全表 1 行。旧行无 `arm_id` 但 experiment/purpose 疑似 D 时状态 `unidentifiable`（fail closed、保留历史、不自动修表）；其它 arm 状态 `ok`。坏控：让守卫忽略产品写入的 `arm_id` 行 → 探针转红。

## 6. F5 字段契约（通过）

- 原始 `reserved_active_seconds`：缺失/None/NaN/±inf/负数/布尔/字符串（`"9.5"`）全部 `LedgerStateInvalid`，不存在 `or 0`/`max` 静默吞值。
- 时间戳：None/NaN/±inf/±1e308/非时间字符串全部 `LedgerTimestampInvalid`；反向时钟拒绝。
- 合法未来高水位 7.0s 正常计入，未误拒（与 RunStore 语义一致）。
- 坏控：把校验换成 `max(0.0, float(value) or 0.0)` → 探针转红。

## 7. F6 冻结信任根（通过）

按原 A2 算法（`identity` 内原正式实现）重算，**先算后比**：清单自摘要 `3481b6ad…45e9` 与登记值相等；原件文件 SHA `2c991f05…be5b` 与钉扎值相等；校验 9 个条目字段（manifest/metadata/tensors 登记），不只看 tensors。负例：篡改摘要 → `DIdentityError`；翻转 1 字节 → `DIdentityError: A2-pinned file changed`。坏控：删掉“重算摘要 vs 登记摘要”的比较 → 探针转红。

## 8. F7 MLX 惰性隔离（通过）

在独立子进程里对身份/记账入口做导入观测：`identity/worker/completion/prereg/data/evaluation/metrics` 共 9 个入口可加载，`mlx_imported=false`、`arms=false`、返回码 0。`smoke` 是真实前向+loss 测量，属于被禁止的真实模型工作，不在本次只读身份入口范围（已在 `scope_note` 披露）。坏控：在 `identity.py` 顶层加 `from . import arms` → 探针转红。

## 9. F8 诚实 CPU 全链（通过）

公开 `run_worker` train 分支 + CPU test double（不真实训练）：

- 3510 次梯度调用，保存点 `[0, 439, 878, 1755, 3510]`，run `completed`，预留优化步 3510，优化器预留 3510 次，final 之后 0 次。
- 第二次提交 `refused / already_attempted`，行数 1→1，arm2/seed0 行数 1。
- 无 MLX 子进程（shim 令 `import mlx` 抛 ImportError）同样完成 3510 步、保存点一致、二次拒绝、行数 1；`mlx_imported_in_process=false`、`mlx_usable=false`。
- 单独运行 `--case f8_nomlx`（**不带** shim）时 `mlx_usable=true`，其 `require_mlx_absent` 断言正确转红（`logs/probe-f8_nomlx.json`），可作为该断言未被写死的反证。
- 真实环境里 `mlx.core` 由 `resource_gate.mlx_memory_probe` 局部队导入（分配器探针），`arms` 未被导入；不宣称“进程从未 import mlx”。
- 坏控：train 分支不再转发 CPU double（`backend=None`）→ 探针转红。

## 10. 守卫坏控汇总

`harness/run_mutations.py` 为每项建临时源码副本，只改一处条件；8/8 全部由绿转红（`evidence/guard-broken-controls.json`，`all_controls_red=true`）。8 项基线在同一探针下均为绿，排除“探针本身永远红”。

作者基线测试只读复跑：`tests/v9/experiments` **291 passed**；`tests/v9/{geometry,contracts,teachers,tokenization}` **378 passed**（`logs/author-tests-experiments.txt`）。测试通过不等同能力通过，本报告结论以上述独立探针为准。

## 11. 未验证 / 边界

- 未运行真实 MLX 前向、训练、评测、final，未测真实 D 的实际成本与时长；F3 只验证 2s 截止下的记账与快照，不证明 2s 足够（决策允许“不够只报告不扩”）。
- 未在真实中央台账上重放 D→train；该缺陷由同一公开方法在独立库复现，真实台账写入被明令禁止。
- F1 的 `before_commit` 内部重跑状态不一致（见 §2）未列为阻断，但建议修复。
- 工作区 dirty 为复核前既有状态；本报告不声称代码树等于 git HEAD，只声称 72 个钉扎文件与 r8 清单逐字节相等。

## 12. 复现命令

```bash
.venv/bin/python reports/V9-P24/harness/verify_pinned.py
.venv/bin/python reports/V9-P24/harness/leaf_diff.py
.venv/bin/python reports/V9-P24/harness/probe_core.py --case f1   # f2…f8、order 同理
.venv/bin/python reports/V9-P24/harness/run_mutations.py
.venv/bin/python -m pytest tests/v9/experiments -q -p no:cacheprovider
```

证据：`reports/V9-P24/evidence/*.json`、`reports/V9-P24/logs/*`、指标 `reports/V9-P24/METRICS.json`。
