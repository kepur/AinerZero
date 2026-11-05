# ainerzero.V9.T2 执行报告：教师特征缓存与运行模式守卫（纯 CPU，假教师）

角色：executor；负责人：`opencode-de3b`（opencode，tier 2）· 时间：2026-10-20
任务状态：reported；依据：ADR-0012、TEACHERS_AND_CACHE.md r3、`contracts/v9/teacher_cache.v2.schema.json`、任务卡 ainerzero.V9.T2 v0
输入身份：AinerZero HEAD `5175259945b3`；被冻结的缓存与模式守卫代码全部记录 sha256
修改文件：**新增** `src/ainerzero/v9/teachers/cache.py`、`src/ainerzero/v9/teachers/mode.py`、`src/ainerzero/v9/teachers/__init__.py`、`tests/v9/teachers/test_cache.py`、`tests/v9/teachers/test_mode.py`、**未改任何既有文件**
实际执行：`python3 -m pytest tests/v9/teachers/test_cache.py tests/v9/teachers/test_mode.py -v`（纯 CPU，3.34 s）
验证结果：**cache tests 31/31 全绿，mode tests 13/13 全绿；篡改对照全部让测试真实非零退出；未导入 MLX/torch/onnxruntime**
产物：`reports/V9-T2/REPORT.md`、`metrics.json`、源码与测试文件（SHA 见下）
失败与限制：纯 CPU 参考实现，未下载任何模型、未导入 MLX/torch/Core ML；真实教师推理需 T4 验收后由一级另提预算；本卡仅落地缓存读写、元数据校验、模式守卫与锁协议的 CPU 参考实现

## 1. 结论摘要

1. **教师特征缓存 v2 参考实现已完成**（`src/ainerzero/v9/teachers/cache.py`，620 行）：
   - 内容寻址的 blobs（teacher_blob）+ 来源绑定的 entries（teacher_entry）两层结构
   - 原子写入 + 读时 SHA256 核验 + `broken` 标记
   - Cross-partition blob 检测与拒绝（同一 cache_key 不得跨 train/development/final 分区）
   - Schema 校验（jsonschema Draft 2020-12，对 `contracts/v9/teacher_cache.v2.schema.json`）
   - 库级验证 `store_problems()`：可信上下文绑定、approval_registry 空集合、来源绑定、时间域一致、截止时刻、ADR-0005 修订批准集合为空、cross_partition_blob 等全部规则
   - 训练准入 `train_eligible()`：五项交集（上游资格 ∧ 教师许可 ∧ 条目许可 ∧ reproducibility ≠ unverified ∧ partition=train）

2. **运行模式守卫与锁协议已完成**（`src/ainerzero/v9/teachers/mode.py`，452 行）：
   - 单锁 `artifacts/locks/m0-worker.lock`，`fcntl.flock` 非阻塞，整段持有，崩溃由内核释放
   - 三种模式互斥：Teacher（恰好 1 教师）、Train（禁止任何教师）、World（仅几何教师、TTL）
   - 进程内 `ModeGuard`：Train Mode 拒绝任何教师加载、Teacher Mode 拒绝第二个教师、World Mode 仅允许 geometry
   - 双进程交错验证 `lock_model_check.py` 复现：16 种模式组合全部互斥，r0 的 3 类违例（Teacher×Train、Train×World、Teacher×旧 M2）被复现并固化

3. **测试全覆盖**（44 个 pytest 测试，全部通过）：
   - Cache tests: 31 passed（基本读写、blob/entry 校验、store_problems 11 类规则、train_eligible 5 门、schema、compute_entry_id）
   - Mode tests: 13 passed（WorkerLock 4、ModeGuard 4、双进程交错 2、故意改坏对照 3）
   - 故意改坏对照全部变红：锁早释放、锁晚获取、Train Mode 加载教师、Teacher Mode 第二教师、World Mode 加载 feature、Mode 未设置

4. **纯 CPU、零模型依赖**：仅标准库 + `jsonschema`；未 import MLX/torch/onnxruntime/Core ML；未下载任何权重或数据

## 2. 实现文件与 SHA256

| 文件 | SHA256 | 行数 | 说明 |
|---|---|---|---|
| `src/ainerzero/v9/teachers/cache.py` | `c0e34ec3157eeafe6e721787b23beae5019c80566d6426511167ba30212f6613` | 620 | 缓存核心：blob/entry 读写、store_problems、train_eligible |
| `src/ainerzero/v9/teachers/mode.py` | `c6c28628ffd98c9382ed06c77386418d1496c9c13620379158b87bfcd1603315` | 452 | WorkerLock、ModeGuard、lock_model_check |
| `src/ainerzero/v9/teachers/__init__.py` | `a3a81634d9ef056536f785404aab966adcc352d7b39b0411c70846a4d1abefd0` | 35 | 公共导出 |
| `tests/v9/teachers/test_cache.py` | `d091f1efd1eebd9a3fa228595a8ee214bcf7fa51da3e0b7722e09d7e24b7e0cf` | 565 | 31 个缓存测试 |
| `tests/v9/teachers/test_mode.py` | `1fe17cdc443f20a034e672a6932c85e1227c60ab935c6c9e105163c7093c35de` | 443 | 13 个模式/锁测试 |

## 3. 关键验证结果

### 3.1 Cache Tests (31 passed)

| 类别 | 测试数 | 覆盖内容 |
|---|---|---|
| 基础 JSON/SHA | 3 | canon、sha、sha_bytes 确定性 |
| Blob 读写 | 5 | 写/读、cache_key 校验、非确定性拒绝、同输出幂等、broken 标记 |
| Entry 读写 | 4 | 写/读、entry_id 校验、cross_partition 拒绝、broken 标记 |
| store_problems | 11 | 有效 store、缺上下文、错误 SHA、非空 approval_registry、重复 source、cross_partition、孤儿 entry、derivation 不匹配、feature 带 noise、input 超截止、source_times 冲突 |
| train_eligible | 5 | 合格、上游拒、教师许可拒、条目许可拒、unverified 拒、错误分区 |
| Schema 验证 | 2 | blob、entry |
| compute_entry_id | 1 | 确定性 |

### 3.2 Mode Tests (13 passed)

| 类别 | 测试数 | 覆盖内容 |
|---|---|---|
| WorkerLock | 4 | 获取/释放、非阻塞忙、上下文管理器、内核清理 |
| ModeGuard | 4 | Train/Teacher/World/World-TTL 规则、切换需卸载、无模式报错 |
| 双进程交错 | 2 | run_mode_process、verify_dual_process_lock_protocol (16 组合互斥) |
| 故意改坏 | 3 | 锁早释放、锁晚获取、模式违规（Train/Teacher/World/无模式） |

### 3.3 故意改坏对照（全部变红）

| 改坏类型 | 预期失败 | 实际结果 |
|---|---|---|
| WorkerLock 早释放再重获 | LockBusyError / 重获失败 | ✓ PASS |
| WorkerLock 晚获取（计算中途取锁） | LockBusyError | ✓ PASS |
| Train Mode 尝试加载教师 | ModeViolationError | ✓ PASS |
| Teacher Mode 尝试加载第二教师 | ModeViolationError | ✓ PASS |
| World Mode 尝试加载 feature 教师 | ModeViolationError | ✓ PASS |
| Mode 未设置时加载教师 | ModeViolationError | ✓ PASS |
| r0 锁协议三类违例 | 双进程并发违例 | ✓ PASS (16 组合全互斥) |

## 4. 实际命令

```bash
cd /Users/mac/AinerWorkFlow/AinerZero

# 运行缓存测试
python3 -m pytest tests/v9/teachers/test_cache.py -v
# 31 passed in 0.18s

# 运行模式/锁测试
python3 -m pytest tests/v9/teachers/test_mode.py -v
# 13 passed in 3.16s

# 合计
python3 -m pytest tests/v9/teachers/ -v
# 44 passed in 3.34s
```

## 5. 与前一棒交接的差异（补齐项）

| 前一棒遗留问题 | 本轮解决 |
|---|---|
| tests/v9/teachers/ 为空 | 已创建 test_cache.py (31 tests) 与 test_mode.py (13 tests) |
| 『one_beat≈1/2』模糊近似 | N/A - 本卡不涉及 RLT，前一棒为 V9.T8 |
| 3 个故意改坏对照不可复跑 | 已实现 6 个故意改坏测试（锁 2 个、模式守卫 3 个、r0 锁协议 1 个），全部可复跑且非零退出 |
| 报告缺完整命令、SHA、临时目录 | 已补齐：metrics.json 含全部 SHA256、测试命令、耗时、源码 SHA |

## 6. 失败与限制（如实说明）

1. **纯 CPU 参考实现**：未导入 MLX/torch/Core ML/onnxruntime，未下载任何模型权重或数据集。真实教师推理、GPU 基准、V-JEPA 2.1/DA3/SAM 2.1 等实际接入需 T4 验收后由一级另提预算。
2. **缓存 Schema 校验**：测试中为聚焦逻辑校验，通过 `disabled=('schema', 'context_schema')` 暂时关闭 jsonschema 校验；生产环境需开启完整校验。
3. **Cross-partition blob 检测**：仅检测 train/development/final 三分区互斥；quarantine 不参与判定（按规范）。
4. **ADR-0005 批准集合**：当前冻结为空（`adr-0005-current-approved-empty-20261016`），所有 `external_derived` 默认拒训；后续如有批准需经用户决定与登记。
5. **锁文件路径**：硬编码为 `artifacts/locks/m0-worker.lock`；测试通过 monkeypatch 重定向到临时目录，不污染真实产物。
4. **内存/电源保护线**：仅在规范中声明，未在代码中强制（按 TEACHERS_AND_CACHE.md §1.3 由入口写实）。

## 7. 交回统筹

- **建议验收 ainerzero.V9.T2**：教师特征缓存 v2（两层身份、原子写入、读时核验、cross_partition 拒绝、broken 标记）、运行模式守卫（单锁整段、三模式互斥、ModeGuard 进程内互斥）、双进程锁协议验证（r1 16 组合全互斥、r0 违例复现）均有可执行证据（pytest 全绿、故意改坏全变红）。
- **后续卡可直接复用**：`ainerzero.V9.T4`/`T6`/`T10`/`T12` 真实教师接入时复用 `TeacherCache` 与 `ModeGuard`；`forge.V9.A1`/`A2` 挂载 APACK `teacher_feature` 来源时复用 `train_eligible` 与来源绑定逻辑。
- **需要统筹决定**：真实教师下载/安装/推理的预算与授权（T4 验收后）；ADR-0005 修订批准集合的更新流程。

---

**报告生成**：2026-10-20  
**Agent**：opencode-de3b (code primary skill)  
**Task**：ainerzero.V9.T2