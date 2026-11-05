# B15 非作者独立复核报告：accept

- 任务：`ainerzero.V9.B15` 【L3·非作者复核】B12 r3：消费端全证据复验与真实拆门承重（B14后续）
- 复核者：`gemini-k8m4`（tier 2，kind gemini）；独立外部新会话，不在排除名单（排除名单：`deepseek-q7m2`, `claude-az`, `codex`, `codex-b12-r3-fix-20261028`, `codex-b14-20261028`, `codex-g8-20261028`, `codex-h1-r4-fix-20261028`）。
- 审核对象：`ainerzero.V9.B12` 新候选（r3，作者 `codex-b12-r3-fix-20261028`）。
- 裁决结论：**accept**（建议主责统筹采纳验收 B12 r3）。

---

## 1. 核心裁决与验收结论

**accept**。经本独立会话在隔离沙箱环境中对 B12 r3 候选进行无偏见复验与真实拆门承重测试：

1. **B14 退回项全闭环修复**：
   - **起源合法集合 fail-closed（关闭 B14 F1）**：`require_slow_eligible_origin` 采用 `KNOWLEDGE_ORIGIN_CATEGORIES` 白名单校验与 `SLOW_FORBIDDEN_ORIGINS` 黑名单双重防御；对变体、大小写（`LLM`、`Teacher`）、带空格（`llm `）、空字符串、None、未注册字符串、非字符串类型（list、dict）全部 fail-closed 抛出 `EvidenceRequired`，严防构造器绕过进入 SLOW。
   - **消费边界完整不变量复验（关闭 B14 F2）**：`spatial_memory.py` 的 `require_evidence` 不信任外部构造历史，在消费入口以提取的原始字段全新实例化基础 `PromotionEvidence`，并在内部触发 `_validate_v2()`。在对象构造后对嵌套字典的恶意篡改（包括但不限于将 `data_identity['test']` 改为 `data_identity['discovery']` 造成 D/T 重叠、以及修改 `calibration`、`error_control` 等元数据）在消费边界均被严格捕获并转换为 `EvidenceRequired`。子类重写 `is_v2` / `__post_init__` / `_validate_v2` 无法绕过校验。
   - **合法起源可用性与 MID 语义保持**：合法起源（`sindy`, `symbolic`, `human`, `engineered`）正常晋升并进入 `usable_slow_items`；被拒绝条目及 v1 条目保持在拓扑存储中可查（MID 语义不丢失）；`revoke` 与 `demote` 正常退出 SLOW 并保留拓扑可读性。

2. **G1 与 G5 真实拆门承重认证（关闭 B14 F3 / 坏控分账）**：
   - 彻底澄清并分账旧 16 坏控的虚假报红：旧 G1 拆除仅导致下层守卫抛出 `trusted_context_missing` 错误字符串不匹配；旧 G5 拆除直接引发 `AttributeError: 'NoneType' object has no attribute 'get'` 异常崩溃。两者均未达成非法晋升成功路径。
   - 独立验证 r3 补全的 **5 组真坏控（真实达到非法晋升成功路径）**：
     - **真 G1**：构造除 `schema_version='v1'` 外所有字段齐全合法的 v1 证据。基线拒绝；仅移除版本守卫后，条目**真实晋升为 SLOW 并进入 `usable_slow_items`**（`rejected -> promoted_and_usable`）。
     - **真 G5**：构造无 producer 绑定的证据。基线拒绝；将缺绑定分支由抛错改为直接放行后，条目**真实晋升为 SLOW 并进入 `usable_slow_items`**（`rejected -> promoted_and_usable`）。
     - **真 Origin**：构造 `origin_category='llm'` 的合法结构证据。基线拒绝；仅移除起源守卫后，条目**真实晋升为 SLOW 并进入 `usable_slow_items`**。
     - **真 Overlap**：构造消费前篡改 D/T 重叠的证据。基线拒绝；仅移除消费端重建复验后，条目**真实晋升为 SLOW 并进入 `usable_slow_items`**。
     - **真 Kind**：构造 `kind='self_report'` 的绕过证据。基线拒绝；仅移除消费端重建复验后，条目**真实晋升为 SLOW 并进入 `usable_slow_items`**。
     - 每条真坏控在拆除目标门时，**正对照依然成功，且其他正交守卫保持拒绝**，无异常崩溃，承重真实确凿。

---

## 2. 候选文件与 SHA256 精确核验

对工作区中 B12 r3 候选文件进行哈希核验，与 B12 r3 报告清单逐字节完全一致：

| 文件路径 | 状态 | SHA256 |
|---|---|---|
| `src/ainerzero/v9/interfaces/spatial_memory.py` | 候选核心实现 | `56bbda8a9a564b18a7ca7d4e570edf5094f3bde715c122a07b18d2435f824208` |
| `src/ainerzero/v9/interfaces/validation.py` | 候选核心实现 | `0781a8272898df9bdcf4e036c69557de3cd142ec79bf31ce134e83997af15739` |
| `tests/v9/contracts/test_promotion_consumption_r3.py` | 候选新增合同 | `293c0dba16e0d1b150b26c1b2e6dfab9fd0a5e01ff93418171ce42b0ebb7bd7b` |
| `reports/V9-B12/cmfl_registration.json` | 冻结登记输入 | `cfef50bb50b551ebf3ec89fe20d0f50800b65cefd27be3ae624ec775aeefbba8` |

工作区源码前后校验：`reports/V9-B15/evidence/source-before.json` 与 `source-after.json` 零差异，工作树除 B15 报告目录外无任何修改。

---

## 3. 隔离验证环境与模型导入阻断

1. 验证全程在 `tempfile.TemporaryDirectory` 创建的独立沙箱中运行，隔离临时路径如 `/var/folders/.../b15-isolated-omqv4n8i`。
2. 注入专用 `sitecustomize.py` 严格拦截模型库导入：
   ```python
   class BlockModels:
       def find_spec(self, fullname, path=None, target=None):
           if fullname.split('.')[0] in ('mlx', 'torch', 'transformers', 'onnxruntime'):
               raise RuntimeError('B15 isolated CPU execution blocked: ' + fullname)
   sys.meta_path.insert(0, BlockModels())
   ```
3. 验证全程 `loaded_models: []`，零 MLX / Torch / ONNX 导入，零 GPU / 锁占用，零真实 RunStore 读写。

---

## 4. 合同全量回归验证

在沙箱中执行全量合同测试：
- 命令：`.venv/bin/python -m pytest tests/v9/contracts -q -p no:cacheprovider --junitxml=contracts.xml`
- 结果：**341 passed / 0 failed / 0 skipped**（用时 0.48s）。
- 日志文件：`reports/V9-B15/evidence/01-contracts.txt`，XML：`contracts.xml`。

---

## 5. 独立探针 55 项全量分账测试

由复核者独立编写探针 `reports/V9-B15/probe.py`（不依赖作者夹具，手工构造完整上下文与摘要绑定），在隔离环境中执行：
- 命令：`.venv/bin/python probe.py`
- 结果：**total: 55, passed: 55, failed: 0**。
- 日志文件：`reports/V9-B15/evidence/02-independent-probe.txt`。

### 探针各类别分账明细：

1. **正对照组（4/4 全部 promoted_and_usable）**：
   - `sindy`, `symbolic`, `human`, `engineered` 均成功进入 SLOW 并进入 `usable_slow_items`。
2. **起源否定与变体防线（10/10 全部 rejected 抛出 EvidenceRequired）**：
   - 精确拒绝：`llm`, `teacher`。
   - 畸形与大小写变体：`LLM`, `Teacher`, `llm `（带空格）。
   - 空值与类型伪造：`''`（空串）, `None`, `unregistered`, `[]`（列表）, `{}`（字典）。
   - 验证：全部拒绝，且条目未进入 SLOW，MID 拓扑可正常查询。
3. **构造器绕过与非法字段（16/16 全部 rejected 抛出 EvidenceRequired）**：
   - `kind='self_report'`, `schema_version='v1'`, `schema_version='v3'`.
   - `producer='student'`.
   - 空引用校验：`report_ref=''`, `test_id=''`, `domain_ref=''`, `counterexample_ref=''`, `regression_ref=''`, `entry_digest='bad'`, `encoder_version=''`, `prior_version=''`.
   - 顶层必要字段缺失：`trusted_context=None`, `calibration=None`, `error_control={}`, `data_identity={}`.
4. **嵌套数据构造后篡改防御（15/15 全部 rejected 抛出 EvidenceRequired）**：
   - 数据重叠：`data_identity['test'] = D`（D/T 重叠）、`data_identity['calibration'] = D`（D/C 重叠）、`data_identity['test'] = C`（C/T 重叠）。
   - 校准元数据失效：`method='unknown_method'`, `alpha_dom=nan`, `alpha_dom=inf`, `n_cal=1` (<20), 空 `exchangeability_ref`, 空 `fpca_basis_ref`.
   - 错误控制元数据失效：`alpha_t=nan`, `attempts_N=0`, `frozen_test_id='different-test'`, `block_unit='frame'`, 空 `test_id_frozen_ref`, 空 `elond_state_ref`.
5. **生产者与可信上下文绑定否定（5/5 全部 rejected 抛出 EvidenceRequired）**：
   - 缺失对应 producer 的绑定（`absent_binding`）。
   - 重复绑定（`duplicate_binding`）。
   - 绑定中 `context_id` 篡改跨上下文挪用。
   - 绑定中 `category` 篡改。
   - 绑定摘要 `binding_sha256` 篡改或伪造。
6. **子类绕过与缺失属性（2/2 全部 rejected 抛出 EvidenceRequired）**：
   - 子类覆盖 `is_v2()` / `__post_init__()` / `_validate_v2()` 试图放行 `self_report`：在消费端重构为 `PromotionEvidence` 基础类，强制执行不变量，成功拦截。
   - `object.__new__(PromotionEvidence)` 缺属性：捕获 AttributeError 转换为 `EvidenceRequired`。
7. **生命周期与 MID 拓扑保留（3/3 符合预期）**：
   - `revoke`：成功移出 SLOW，保留拓扑查询。
   - `demote`：成功移出 SLOW，保留拓扑查询。
   - `v1`：拒绝晋升，但留在 MID 拓扑中可读。

---

## 6. 旧 16 坏控分账核验（澄清虚假承重）

在沙箱中逐项复跑旧 `guard_removal.py` 定义的 16 项坏控，并分析其报红成因：

| 守卫编号 | 目标测试 | 旧坏控报红机理分类 | 审计判定与说明 |
|---|---|---|---|
| **G1** | `test_v1_evidence_is_refused_at_promote` | **次级守卫拦截（错误字符串不匹配）** | **非真实承重**。旧测试使用裸 v1 证据（无 trusted_context）。拆除版本门后，被下层 `require_independent_slow_producer` 抛出 `trusted_context_missing` 拦截。测试变红仅因断言信息不同，条目并未晋升。 |
| **G2** | `test_empty_conformal_certificate_is_refused` | 目标守卫有效拦截 | 有效承重。拆除 `_validate_v2()` 后构造不抛 ValueError。 |
| **G3** | `test_discovery_calibration_test_identities...` | 目标守卫有效拦截 | 有效承重。拆除相交检查后允许 D/C/T 重合构造。 |
| **G4** | `test_student_self_evidence_is_refused...` | 目标守卫有效拦截 | 有效承重。拆除 `SLOW_FORBIDDEN_CATEGORIES` 拦截后 student 允许写 SLOW。 |
| **G5** | `test_bare_self_reported_string_without_binding...` | **代码崩溃（AttributeError 异常）** | **非真实承重**。拆除 `if matched is None: raise` 后，下一行 `matched.get(...)` 在 `matched=None` 上崩溃报错 `AttributeError`。测试变红因非预期异常，裸 producer 并未晋升。 |
| **G6** | `test_binding_digest_must_be_canonical` | 目标守卫有效拦截 | 有效承重。拆除摘要比较后接受错误摘要。 |
| **G7** | `test_fragment_without_provenance_cannot_be_promoted` | 目标守卫有效拦截 | 有效承重。拆除 `promotion_gaps` 后允许无来源键条目晋升。 |
| **G8** | `test_entry_digest_must_match_the_stored_content` | 目标守卫有效拦截 | 有效承重。拆除摘要比对后允许内容与受检不一致条目晋升。 |
| **G9** | `test_world_truth_identifiers_are_refused` | 目标守卫有效拦截 | 有效承重。拆除世界真值拦截后允许 gt_/eval_ 标识符。 |
| **G10** | `test_slow_entry_is_usable_only_while_versions_match` | 目标守卫有效拦截 | 有效承重。拆除版本比对后漂移条目仍可用。 |
| **G11** | `test_demote_never_lands_on_slow` | 目标守卫有效拦截 | 有效承重。拆除目标级别检查后允许降级到 SLOW。 |
| **G12** | `test_supersede_is_single_shot` | 目标守卫有效拦截 | 有效承重。拆除单次指针检查后允许覆盖 supersede。 |
| **G13** | `test_store_accepts_parametric_writes_only` | 目标守卫有效拦截 | 有效承重。拆除路由检查后允许非 PARAMETRIC 写。 |
| **G14** | `test_nis_routes_must_record_the_statistic` | 目标守卫有效拦截 | 有效承重。拆除统计量检查后允许空 stat。 |
| **G15** | `test_tampering_breaks_the_self_check` | 目标守卫有效拦截 | 有效承重。拆除 digest 比对后允许篡改登记表。 |
| **G16** | `test_llm_or_teacher_origin_cannot_reach_slow...` | 目标守卫有效拦截 | 有效承重（B14 新增）。拆除起源门后允许 llm 晋升。 |

---

## 7. 五组真坏控复验（真实达到非法晋升成功路径）

在沙箱中，使用专用的非法成功路径探针，对 5 条核心守卫进行单独拆除，验证其是否翻转为 `promoted_and_usable`，并确认正交门不受影响：

| 真坏控编号 | 拆除门与编辑方式 | 测试输入特征 | 基线行为 | 拆门后行为 | 正对照状态 | 正交守卫状态 |
|---|---|---|---|---|---|---|
| **True G1** | `spatial_memory.py` 仅移除 `values["schema_version"] != "v2"` 检查 | 伪造 v1，但携带全部合法 v2 字段（独立 producer、可信绑定、校准等） | `rejected` | **`promoted_and_usable`** (非法 v1 真正晋升成功) | 保持 `promoted_and_usable` | G5, origin, overlap, kind 全部保持 `rejected` |
| **True G5** | `validation.py` 将 `if matched is None` 抛错改为 `return category` | 携带可信上下文但缺少该 producer 的绑定 | `rejected` | **`promoted_and_usable`** (无绑定非法出具者真正晋升成功) | 保持 `promoted_and_usable` | G1, origin, overlap, kind 全部保持 `rejected` |
| **True Origin** | `spatial_memory.py` 仅移除 `require_slow_eligible_origin` 调用 | 携带合法独立 producer 但 `origin_category='llm'` | `rejected` | **`promoted_and_usable`** (LLM 知识真正晋升成功) | 保持 `promoted_and_usable` | G1, G5, overlap, kind 全部保持 `rejected` |
| **True Overlap** | `spatial_memory.py` 仅移除 `PromotionEvidence(**values)` 重建复验 | 构造后篡改 `data_identity['test'] = discovery` 形成 D/T 重叠 | `rejected` | **`promoted_and_usable`** (D/T 污染条目真正晋升成功) | 保持 `promoted_and_usable` | G1, G5, origin 全部保持 `rejected` |
| **True Kind** | `spatial_memory.py` 仅移除 `PromotionEvidence(**values)` 重建复验 | 通过 `object.__new__` 伪造 `kind='self_report'` | `rejected` | **`promoted_and_usable`** (学生自报条目真正晋升成功) | 保持 `promoted_and_usable` | G1, G5, origin 全部保持 `rejected` |

上述 5 组实验证明：
1. 每个守卫在位时均有效防御特定攻击；
2. 拆除该守卫后，攻击输入**切实走通了晋升流程并进入可用缓存**；
3. 拆除过程未产生任何未捕获异常或语法错误；
4. 守卫之间正交独立，互不放行。

---

## 8. 产物与哈希清单

本报告目录（`reports/V9-B15/`）下产物均已就绪：
- `REPORT.md`：本报告文件。
- `metrics.json`：符合 relay 格式的完整指标文件。
- `probe.py`：55 项独立探针源码。
- `run_b15_review.py`：全流程自动化独立沙箱复核脚本。
- `evidence/`：包含全量测试日志、XML、以及前后源码哈希。

---

## 9. 验收建议与移交

- **建议主责统筹**：在接力台正式采纳并验收 `ainerzero.V9.B12`（可安全执行 `relay accept ainerzero.V9.B12`）。
- **后续任务**：B12 守卫补丁与证据体系完整健全，可继续推进依赖 B12 的下游机制与集成工作。
