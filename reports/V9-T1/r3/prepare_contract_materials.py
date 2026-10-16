"""T19 机械契约整理。只写本卡允许的文档/schema/合成夹具。"""
import copy,json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3]
p=ROOT/'contracts/v9/teacher_cache.v2.schema.json';s=json.loads(p.read_text())
s['title']='v9 教师特征缓存 v2 候选 r3：可信来源、观察时间与批准/指纹绑定'
s['description']='T1 r3 / T19：AWZ origin 固定 external_derived；条目绑定调用方独立冻结的原来源清单、Observation 时间上下文和 ADR-0005 批准登记。当前获批例外集合为空。schema 只做结构；跨记录/可信身份/时间/指纹由报告目录参考检查及未来 T2/Forge 消费者核对。v2 尚未采用，本轮修订候选，旧 r2 已归档。'
def obj(props,required=None):return {'type':'object','additionalProperties':False,'required':list(props) if required is None else required,'properties':props}
text={'type':'string','minLength':1};integer={'type':'integer','minimum':0};sha={'$ref':'#/$defs/sha256'}
s['$defs']['observation_time_domain']=obj({'clock':{'const':'episode_relative'},'episode_id':text,'epoch_id':text,'tick_hz':{'const':120}})
s['$defs']['ticks']={'type':'array','minItems':1,'items':integer}
k=s['$defs']['key_material']['properties']['input'];k['required'] += ['time_domain','timestamps_ticks'];k['properties'].update(time_domain={'$ref':'#/$defs/observation_time_domain'},timestamps_ticks={'$ref':'#/$defs/ticks'})
k['properties']['timestamps_s']['description']='逐项等于 timestamps_ticks / 120，非故事 world_time；库级核对，容差 1e-9 秒。'
e=s['$defs']['teacher_entry'];e['required'].append('as_of_t_ticks');e['properties']['as_of_t_ticks']=integer
e['properties']['as_of_t_s']['description']='只作可核对副本，必须等于可信当前 Observation.t_ticks/120；调用方固定上下文身份，条目不得自行推进截止。'
source=e['properties']['source'];source['required'] += ['time_domain','timestamps_ticks','manifest_ref'];source['properties'].update(time_domain={'$ref':'#/$defs/observation_time_domain'},timestamps_ticks={'$ref':'#/$defs/ticks'},manifest_ref=obj({'manifest_id':text,'source_id':text}))
up=e['properties']['provenance']['properties']['upstream'];up['allOf']=[{'if':{'properties':{'system':{'const':'awz'}}},'then':{'properties':{'origin':{'const':'external_derived'}}}}]
e['properties']['provenance']['description']='upstream 整体逐项匹配独立可信来源清单；教师 actor 不可改写 origin。ADR revision_ref 非空只满足结构，不构成批准。'
s['$defs']['source_manifest_item']=obj({'source_id':text,'world_key':text,'partition':{'$ref':'#/$defs/partition'},'upstream':copy.deepcopy(up),'time_domain':{'$ref':'#/$defs/observation_time_domain'}})
# Trusted source records use the same shape; the semantic AWZ combination is checked on records.
s['$defs']['source_manifest_item']['properties']['upstream'].pop('allOf')
s['$defs']['approval']=obj({'revision_ref':text,'user_decision_ref':text,'status':{'enum':['approved','pending','rejected']},'source_scopes':{'type':'array','minItems':1,'items':obj({'manifest_id':text,'source_id':text,'world_key':text,'partition':{'$ref':'#/$defs/partition'},'input_sha256':sha})}})
s['$defs']['trusted_context']=obj({'schema_version':{'const':'az.v9.teacher_cache.context.v1'},'context_id':text,'synthetic':{'type':'boolean'},'source_manifest':obj({'manifest_id':text,'sources':{'type':'array','minItems':1,'items':{'$ref':'#/$defs/source_manifest_item'}}}),'observation':obj({'packet_ref':{'$ref':'#/$defs/file_ref'},'time_domain':{'$ref':'#/$defs/observation_time_domain'},'t_ticks':integer,'t_s':{'type':'number','minimum':0}}),'approval_registry':obj({'registry_id':text,'entries':{'type':'array','items':{'$ref':'#/$defs/approval'}}})})
s['$defs']['trusted_context']['description']='独立于待验缓存记录，由调用方固定预期 SHA256（规范 JSON）；schema 合法或自行重算摘要不构成可信。合成夹具 synthetic=true 不是真实来源认证或授权。当前批准登记 entries=[]。'
p.write_text(json.dumps(s,ensure_ascii=False,indent=2)+'\n')
p=ROOT/'docs/v9/TEACHERS_AND_CACHE.md';d=p.read_text();d=d.replace('规范 r2（','规范 r3（',1).replace('一级设计 **r2**（Claude，2026-10-16）· 待非作者复核','候选契约 **r3**（按 Codex 统筹裁决由 T19 二级整理，2026-10-16）· 待非作者 T18 复核',1)
d=d.replace('- r2 依据：','- r3 依据：T17 非作者负审 B1–B4；裁决固定于 `reports/V9-T1/r3/COORDINATOR_DECISIONS.md`。r2 文档/schema/全部夹具/报告/脚本逐字节归档在 `reports/V9-T1/r2-archive/`（`SHA256SUMS`）。r3 关闭表见 §10。\n- r2 依据：',1)
d=d.replace('`ARCHITECTURE_V9.md` r3 §7','`ARCHITECTURE_V9.md` r5 §7')
d=d.replace('（r2：来源条目带上游来源与训练资格）','（r3 候选：来源清单、时间域与指纹绑定）').replace('核对 `reports/V9-T1/r2/check_teacher_cache_v2.py`','当前参考核对 `reports/V9-T1/r3/check_teacher_cache_v2.py`；旧 r2 核对保留在原目录及归档中')
d=d.replace('key_material = {teacher, preprocess, input{sha256, media_type, timestamps_s}}','key_material = {teacher, preprocess, input{sha256, media_type, time_domain, timestamps_ticks, timestamps_s}}')
d=d.replace('时间用世界时钟秒（`timestamps_s`），与 ObservationPacket 的显式 `dt` 一致，不允许帧序号代替时间。','时间只用 Observation 的 episode-relative `t_ticks / 120`；`timestamps_ticks` 为逐帧整数 tick，`timestamps_s` 是逐项换算副本。`time_domain={clock:episode_relative, episode_id, epoch_id, tick_hz:120}` 必须与可信当前 Observation、来源清单和 blob 一致；不能用故事 `world_time` 或帧序号替代。跨 episode/epoch 或缺上下文拒绝。')
d=d.replace('且必须带 `revision_ref`。','且必须带 `revision_ref`。非空字符串只满足结构；必须经调用方独立冻结的可信批准登记解析，核实用户决定身份及适用 manifest/source/world/input/partition。当前获批集合为空，所有 `external_derived` 仍拒训；不存在、未批准、错引或无法解析一律拒训。')
d=d.replace('- **截止时刻**：`use = input` 的特征，输入片段的全部时间戳都不得晚于条目的 `as_of_t_s`。','- **截止时刻**：`use = input` 时以引用 blob 的真实输入时间与可信当前 Observation 截止比较，全部帧 tick ≤ Observation.t_ticks。`source.timestamps_ticks` / `timestamps_s` 必须与 blob 逐项一致；条目 `as_of_t_ticks` / `as_of_t_s` 必须与可信 Observation 完全绑定（秒换算容差 1e-9）。可编辑副本不能回填输入时间或推进当前截止。')
d=d.replace('schema 强制 external_derived 只能 `adr_0005_default_deny` 且 `train=false`，修订路径必须带 `revision_ref`','schema 强制普通 external_derived 路径 `train=false`，修订路径必须带 `revision_ref`；r2 对批准身份的漏检由 r3 §10 补齐（当前集合为空）')
d += '''

## 10. r3 可信绑定与 T17 关闭表（仅设计与合成 CPU 参考）

本节取代 r2 中仅依赖条目自报资格/截止/非空 revision_ref 的解释，不改变 ADR-0005。`teacher_cache.v2` 仍是未采用的候选，因此在同一候选版本补必填字段；历史 v0/v1、r2 文档/schema/夹具/参考结果全部保留。旧候选需按可信来源重建条目与时间域，不得默认补 observed、当前时间或训练批准。时间域进入 key_material，重算内容键；旧键不覆盖，新条目仍按 §2.1 算身份。

### 10.1 独立可信上下文

参考核对接收 `records`、分开的 `trusted_context` 和**调用方固定的预期 context SHA256**。哈希取 §2.1 规范 JSON。预期身份不从记录、上下文自己的字段或同 blob 的其他条目中获取。缺失、摘要错误、替换上下文均拒绝；调用者用不可信内容自己重算预期摘要不构成可信批准。生产固定身份、认证与加载适配归 T2 / forge.V9.A2，不在本轮实现。

上下文按 schema `$defs/trusted_context` 表示：`source_manifest` 以 manifest_id/source_id 唯一索引原始来源，保存 world_key、partition、完整 upstream 与 time_domain；`observation` 保存可信当前包身份、时间域和截止 tick/秒；`approval_registry` 保存冻结批准登记身份。每个 teacher_entry 以 `source.manifest_ref` 绑定原来源清单，world/partition 及 upstream 的 system/origin/actor/input_ref/eligibility 逐项相同，不借同 blob 的另一来源继承资格。AWZ → external_derived 是强制组合，actor=student 不能改变它。

上下文 source_id 必须唯一，manifest/source 不存在或错引拒绝。source / blob / 原来源 / Observation 的 time_domain 一致；每组 timestamps_ticks/timestamps_s 等长且逐项等于 tick/120（秒换算容差 1e-9）；source 与 blob 两组时间逐项相同。当前 cutoff 仅取可信 Observation；input 不能含未来帧，target 可含未来帧但仍绑定同一时间域及当前截止，未来标签不得当输入。未来 target 与等于截止边界都是正例。

### 10.2 批准与模型指纹

当前 ADR-0005 获批例外集合明确为空；r3 合成上下文的批准登记 `entries=[]`。未来格式中的批准项需同时匹配 revision_ref、approved 状态、用户决定身份与 manifest/source/world/input/partition 适用范围，且由固定登记身份加载。非空 ref、缓存条目自报、上下文自报和自行重算哈希都不产生批准。任何非空批准登记在当前参考策略中拒绝；本轮没有合成“external_derived 可训”正例。

`derivation.teacher_id`、有序 `weights_sha256`、`preprocess_spec_sha256` 分别与引用 blob 的 teacher/weights/preprocess 逐项一致。直接调用参考资格函数也先完成结构、可信上下文、来源/时间/指纹/策略及跨分区检查；失败返回拒绝，不能绕过校验只算五项布尔交集。五项交集、单锁全程、两层缓存和四分区规则不变。

| T17 问题 | r3 定义与参考证据 |
|---|---|
| B1 AWZ 改 observed、来源资格可复制 | schema 强制 AWZ 组合；独立固定清单绑定完整 upstream/world/partition；包含原探针及单条件反例 |
| B2 回填 source 时间或自改 cutoff | blob/source 全列表绑定；Observation episode/epoch/120Hz 绑定；截止取可信包；跨域、回填、自改截止反例及 target/等于边界正例 |
| B3 伪 ADR ref 可训 | 冻结空批准集合；无/假/错/未批准登记拒训；本轮零训练例外 |
| B4 derivation 指纹不符 | teacher_id / 有序权重 / 预处理摘要逐项一致；直接资格入口先校验 |

当前参考入口位于 `reports/V9-T1/r3/check_teacher_cache_v2.py`。`--suite` 只读取/写本卡合成材料和报告；`validate` / `eligible` 子命令不写文件。测试使用 synthetic=true 的冻结上下文；这是契约的 CPU 参考核对，不代表来源认证、审批服务、媒体解析、缓存/ModeGuard、Forge 映射或训练消费者已实现。T2 与 Forge 实现仍受 `awz.V9.A10` 总门约束；旧 r2 失败与所有不利结果保留。
'''
p.write_text(d)
print('updated candidate schema + r3 contract doc')
