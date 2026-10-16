# ainerzero.V9.T1 r3 报告：来源、批准、时间与指纹绑定（T19）

- 作者：二级执行 agent `catjam-m9v2`，2026-10-16。纯 CPU；只改本卡文件范围内文档、schema、合成夹具与报告目录；未启动模型/GPU/训练，未下载/付费，未提交推送。
- 父任务：AinerZero.V9.T1（Codex 持有）。依据：`reports/V9-T1/r3/COORDINATOR_DECISIONS.md`（未修改）。旧报告/检查器/失败证据保留，未覆盖。
- 前置：T17 非作者负审 B1–B4；r2 原件已归档在 `reports/V9-T1/r2-archive/`（`SHA256SUMS`，20 条全部匹配）。

## 改了什么（关闭表见规范 §10）
1. 候选契约仍在 `teacher_cache.v2` 内修订：新增 `observation_time_domain`、`ticks`、`trusted_context`、`approval`、`source_manifest_item`；`key_material.input` 强制 `time_domain` 与 `timestamps_ticks`；entry 强制 `as_of_t_ticks`；source 增加 `time_domain`、`timestamps_ticks`、`manifest_ref`。
2. AWZ → `external_derived` 强制组合保留；教师 actor 不可改写 origin。每条 entry 以 `source.manifest_ref` 绑定独立冻结的原来源清单；world/partition 及 upstream 的 system/origin/actor/input_ref/eligibility 逐项相同；不同来源不得继承资格。
3. 时间只用 Observation episode-relative `t_ticks / 120`；`timestamps_ticks` 为整数 tick，`timestamps_s` 为逐项换算副本。trusted Observation 是唯一截止来源；所有 time_domain 跨 manifest/source/blob/Observation 必须一致；input 不得含未来帧；target 可含未来帧但不得当输入。未来 target 与等于截止边界保留为正例。
4. 当前 ADR-0005 获批例外集合明确为空；非空 `revision_ref` 不构成批准。reference checker 现在固定登记身份 `adr-0005-current-approved-empty-20261016` 且 `entries=[]`；任何非空/假/未批准/错引/无法解析的批准登记均拒训。
5. `derivation.teacher_id`、有序 `weights_sha256`、`preprocess_spec_sha256` 分别与引用 blob 逐项一致。直接资格入口 `train_eligible` 先执行完整 `store_problems`；disabled 单规则破坏时专用反例必须漏检；五项交集单锁模式不变。
6. trusted context 与待验记录分离，预期 SHA 由调用方固定；缺失/摘要错误/替换上下文均有负例。所有夹具 `synthetic=true`，仅证明契约规则，不声称来源认证或审批服务已实现。
7. 已更新 `docs/v9/TEACHERS_AND_CACHE.md` 到 r3 候选入口，并指向 `reports/V9-T1/r3/check_teacher_cache_v2.py`；旧 r2 入口保留在原目录/归档。

## 实际命令与结果

1. 契约核对（生成/验证合成夹具）：
```bash
/Users/mac/AinerWorkFlow/AnimeWorldZero/.venv/bin/python reports/V9-T1/r3/check_teacher_cache_v2.py --suite
```
- 返回码：0
- 结果：`all_ok=true`
- `counts`: `{"positive_cases": 3, "negative_cases": 41, "r3_controls": 29, "r3_isolated_controls": 29, "r2_sabotage": 11}`
- `failures`: []、`control_failures`: []、`nonisolated_regression_controls`: []

2. 归档完整性核对：
```bash
/Users/mac/AinerWorkFlow/AnimeWorldZero/.venv/bin/python - <<'PY'
import hashlib
bad=0
for line in open('reports/V9-T1/r2-archive/SHA256SUMS'):
    digest,path=line.split()
    actual=hashlib.sha256(open('reports/V9-T1/r2-archive/'+path,'rb').read()).hexdigest()
    if actual!=digest: bad+=1
print('archive_bad=',bad)
PY
```
- 返回码：0；`archive_bad=0`（20/20）

3. 旧 r2 复现（脚本自动在隔离目录执行）：
- `r2-reproduction/result.json`：`failures=[]`，sabotage=11，全部 `turned_red=true`。

4. 语法与 schema：
```bash
/Users/mac/AinerWorkFlow/AnimeWorldZero/.venv/bin/python -m py_compile reports/V9-T1/r3/check_teacher_cache_v2.py
```
- 通过；schema 通过 `Draft202012Validator.check_schema`。

## 摘要（完整身份见 metrics.json）
本次 candidate r3 的关键输出：
- `contracts/v9/teacher_cache.v2.schema.json`（含 trusted context / approval / time domain / manifest binding）
- `contracts/v9/examples/teacher_cache_v2/`（valid + invalid + contexts + expected-context-identities）
- `reports/V9-T1/r3/check_teacher_cache_v2.py` 与 `check_result_v2.json`
- `reports/V9-T1/r3/sabotage-schemas/`（6 种 schema 破坏）
- `reports/V9-T1/r3/r2-reproduction/`（旧 r2 正反例复现）

## 未验证与限制
- 本报告仅 CPU 契约/合成夹具核对；不代表来源认证、审批服务、媒体解析、缓存/ModeGuard、Forge 映射或训练消费者已实现。
- trusted context 的真实固定身份、认证与加载适配归属 T2 / `forge.V9.A2`，本轮未实现。
- `teacher_cache.v2` 仍为未采用候选；最终验收需非作者 T18 复核，且 A10 总门未放行。
- 成功的库级核对不等于能力通过；后续仍需独立复核，不自动晋升。
