# ainerzero.V9.B12 r2 报告：补起源硬门（关闭 B13 K3；执行者 claude-az，复核必须由他人，见 B14）

零模型、零训练；`runs.db` SHA 前缀 `64b668050dfbab7a` 不变。B12 r1 交付的 `reports/V9-B12/` 原样未改（本次只写本目录）。ADR-0014 r3（SHA `8c9b861a…c585`）未改，C6 未碰。

## 1. 缺口（B13 K3，我复现并认可）
`PromotionEvidence` v2 只校验 `origin_category ∈ KNOWLEDGE_ORIGIN_CATEGORIES`，producer 守卫只看 producer 的类别。所以 `origin_category="llm"|"teacher"` + 合法 producer（`contract-harness`）+ 合法 `trusted_context` 可以 `promote` 进 SLOW——这正是 ADR-0014 §2 D5「LLM / 教师起源只进 MID、永不直写 SLOW」想堵的口子。

## 2. 改了什么（3 个文件 + 本目录）
1. `interfaces/validation.py`：新增 `SLOW_FORBIDDEN_ORIGINS = ("llm", "teacher")` 与 `require_slow_eligible_origin(origin_category)`（fail-closed 抛 `EvidenceRequired`，消息含 `origin_category`、`MID`）。起源轴与出具者轴相互独立，两条都要过。
2. `interfaces/spatial_memory.py` 的 `require_evidence`（C1+C2 的共同入口，所有实现共用）：producer 守卫之后调用起源守卫。
3. `tests/v9/contracts/test_spatial_memory.py`：+7 条——LLM/教师起源 × 合法 producer 必拒（2）；其余四种起源（sindy/symbolic/human/engineered）同一份证据只换起源即可晋升（4，正对照，证明拒绝来自起源门而非环境）；起源守卫作为独立函数 fail-closed（1）。
没改 `types.py`（`PromotionEvidence` v2 的构造校验不变；v1 仍可读不可晋升）。

## 3. 验证
- `tests/v9/contracts`：**295 passed**（288 + 7）。
- 拆守卫坏控：沿用 B12 的 `guard_removal.py`（只 import，不改、不覆盖其已交付证据）追加 **G16**（拆掉起源门）整套重跑：**16/16 承重**（原 15 条仍全红 + G16 红），`evidence/03-guard-removal-r2.txt`；副本与仓内逐字节一致，还原后三方 SHA 一致。
- 范围外：整个 `tests/v9` 树有 5 个失败，**都与本次无关**：`test_s1_r7_phase_accounting`（用真实台账副本的数值期望，既有）、`tests/v9/geometry` 两条 `*_cpu_only_imports`（单独跑通过；`tests/v9/experiments` 先于它们导入 torch/mlx 引起的顺序依赖，`contracts+geometry` 444 passed、`experiments+geometry` 复现）、`test_cmfl_prototype` 两条（G7 的未完成原型）。

## 4. SHA（改动后）
```
99d56e89781e5b86…  src/ainerzero/v9/interfaces/validation.py
a33ce5707b156c21…  src/ainerzero/v9/interfaces/spatial_memory.py
58eedc931fe59280…  src/ainerzero/v9/interfaces/types.py   （未改）
08d06737e94d985082…  tests/v9/contracts/test_spatial_memory.py
```
（`reports/V9-B12/指标.json` 里 B12 r1 声明的 `key_source_sha256` 对 `validation.py`、`spatial_memory.py` 已过期，以此表为准。）

## 5. 给 B14（非作者复核）的攻击点
- 起源守卫放在 `require_evidence`：有没有不经过它的晋升路径（真实实现、其他 fake、直接改 `_entries`）？
- `origin_category` 取值不在白名单内会在 v2 构造时被拒；有没有 `object.__new__` 之类绕过构造再进 `promote` 的路径，`require_evidence` 是否仍挡住（它只看 `in SLOW_FORBIDDEN_ORIGINS`，未知值不会走到这里，但值为 `LLM`/`Teacher` 大小写变体呢？构造期已因不在白名单被拒，请验证）。
- 「起源」是证据里的自报字段；这道门防的是「误标/忘标」而不是「恶意改标」——恶意改标要靠 producer 的 trusted_context 与出具者隔离，请复核人评价这个边界在报告里是否说清。
