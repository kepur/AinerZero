# S01-R1：时空契约消费入口与修订校验修复

日期：2026-10-12 · 主责统筹：Codex · S01/R1原作者：grokbot-newbot · 状态：**R1/R2及S02-R1的CPU契约已验收；后续S03公开样例/fixture/引用保存也已限范围验收**。

依据：[内部 S02](artifacts/reports/S02-spacetime-contract-audit-20261012.md)、[外部 S02](artifacts/reports/S02-s02_spacetime_contract_audit-20261012T104900+0300.md)、[修复范围复核](artifacts/reports/S01-repair-scope-review-20261012.md)。外部测试读过内部结论，不称为盲测独立。原失败、XML/日志和原报告保留。

## 统筹决定

公共消费 API 必须重新校验收到的 Python 对象，包括 model_copy/model_construct 生成的对象，不只验证正常 JSON 构造。已有 Contract 的 revalidate_instances="always" 保持，不修改全局配置、v2 记录、采集器、训练器或数据文件。

R1交付后的身份澄清：重复支持和自证按 **(observation_id, cell)** 判断，规范摘要用于内容核对/序列化/修订身份。改变available_at_step、stream_seq或其他引用元数据不产生新证据；同观察的不同格可以作为不同格引用，不称为独立采样。对象重验直接使用现有revalidate_instances=always下的model_validate(instance)，不能先model_dump丢弃非法extra后再认为原对象有效。非法对象采用ValueError系异常（含Pydantic ValidationError）；合法不可比仍返回NOT_COMPARABLE。

引用解析和修订集合校验纳入本次单模块 CPU 修复，新增明确的映射/集合接口，不建立数据库。schema loader 只承诺结构，不能靠 UUID/哈希自行证明观察存在或来源真实。两份 S02 测试保留，不把内部真失败转为 xfail 来恢复全绿。

## API 的固定职责

| API | 必须做到 |
| --- | --- |
| observation_digest / cell_ref_from_observation | 重验 ObservationV2 及嵌套 payload；非法 copied 对象拒绝，不为其生成合法引用 |
| verify_cell_ref | 重验 ref/观察，再核对 ID、规范摘要、run/episode/world/partition/step/origin；格范围和 physical_xyz 固定 None 仍需有效 |
| compare_time | 重验索引；合法但不可比返回 NOT_COMPARABLE，非法结构抛 ValueError/ValidationError |
| EvidenceLink | 所有引用同作用域/分区且 observed；按observation_id+cell身份拒绝自证与重复support；same_cell_later同格且subject严格BEFORE每个support |
| to_canonical_json / record_digest | 重验单体及嵌套结构；不要求外部观察或修订前驱，否则会混淆序列化与解析责任 |
| load_cell_ref / load_evidence_link | 仍是结构加载；合法孤立 revision 可以加载，但不能因此进入消费历史视图 |
| 新 resolve_link(link, observations_by_id) | 重验 link；逐 UUID 解析 subject/support，映射 key 与 observation.id 一致，调用 verify；缺失、摘要/来源/作用域不符抛错 |
| 新 validate_link_history(links) | 重验集合；按规范 digest 解析前驱，拒绝缺失、环、重复身份、同一前驱分叉、revision 跳号/倒序和关系身份变更 |
| links_visible_at(links, step) | 重验记录及 step、验证完整修订历史，再按在线断言步过滤；异常历史抛错，不静默删除错误 |

可添加带 observation mapping 的薄组合消费函数，顺序为逐条 resolve → validate history → as-of filter。无 mapping 的 as-of 只能承诺结构/修订闭包，不能声称观察引用已解析。

observations_by_id 必须来自调用者明确提供的公开观察加载路径，不自动读私有状态。结构/内容匹配不等于生产者真实性：攻击者若同时伪造映射和声明，当前机制没有签名认证能力，文档不能承诺能鉴别。

## 时间、关系与修订策略

1. 比较范围包含 run、episode、world、partition、clock domain/ID；任一 world=None 保留记录但比较为 NOT_COMPARABLE，不把两个未知世界当成已知同世界。因此未知world不能构成same_cell_later链，这一保守限制接受；不虚构world或借episode偷偷恢复时序推断。其他符合结构的关联可以记录，但不据此认定时序/因果能力。
2. EVENT_STEP 按 `(step, stream_seq)` 比较。计时域缺秒不可比较；任一非零误差的区间相交或接触（含同中心）均不可比较。零误差/未声明误差下的同读数只能表示记录坐标相同，不证明精确物理同时性。
3. SENSOR_MONOTONIC 的步/流序与秒序若方向相反，返回 NOT_COMPARABLE；同秒可能来自采样分辨率，不因不同 step 自动拒绝。WALL_UTC 不假定单调，排序不作为因果证据。缺少同步依据仍不跨时钟比较。
4. SAME_CELL_LATER：subject 为较早的格，supports 是同一格的严格后继。不同格、同刻、较早或不可比较的 support 都拒绝。自证/重复支持不适用于任何 kind。
5. 修订前驱必须存在，revision=前驱+1，asserted_at_step 不小于前驱；kind、subject 的规范内容身份及作用域不变，supports 可修订，作者记录保留。同一前驱只能有一个后继，本轮拒绝分叉，不实现分支合并。未来合法 revision 可存入集合，但不能在它可用之前输出。
6. 保留现有“晚时点返回全部已知历史版本”的语义，不趁修复改成仅最新版本。完整历史无效则抛错，不按查询时点掩盖断链。

## 文件负责人和测试处理

R1原作者已reported并交付。S01-R2由执行者spacetime_identity_repair接手 `src/ainerzero/core/spacetime.py` 与 `tests/test_spacetime_s01.py`，仅修身份判定与直接对象重验；作者归属不倒改。S02-R1执行者c05_budget_reconciliation编辑两份S02测试并CPU回验，s01_repair_scope_review只读源码/最小复现。各自交付后已冻结文件，后续修改重新领取，不交叉改文件。

- 内部 13 项失败保持普通验收，不添加 xfail、不删减门槛。按新“拒绝自证”策略修正 schema-loader 正向 fixture，用两个不同合法引用继续测试结构加载。
- 外部 9 个 BUG 函数共 13 个 strict xfail 全部纳入修复；修复到对应项时移除其标记。保留 BUG ID 和原报告链接，不以 xfailed 作为“修复通过”。
- B7 改用显式 resolve_link 的缺失/伪造 ID/摘要/来源例子；不能要求无观察映射的过滤器认证事实。
- B8/B9 从“返回空/隐藏非法记录”改为期待 ValueError/ValidationError；这是本次明确登记的拒绝策略，保留原失败证据。
- S01 原正向排序 fixture 的 world 使用已知 UUID；unknown world 保留独立不可比测试。已有 same_cell_later 正例已是严格后继，不误改。
- 补修订跳号/分叉/跨 subject/kind/缺前驱/倒写、resolver 映射 key 与 ID 不符、嵌套 copied 对象、正向真实引用与合法未来 revision 的测试。
- R2补同观察同格仅availability/stream_seq变化的重复/自证拒绝，以及root/nested copied extra拒绝；先保存R1源码下的真实失败，再验证R2，不能xfail。保留同观察不同格和合法延迟可用引用的正例。

## 验收和 S03

R1执行者报告全量1,963通过/13失败/1xfail，未留新XML，保留为其原交付快照；本轮未重跑含MLX全量。S02-R1实际留档：原测试93通过/13失败/1xfail → 期望对齐246全过 → 新R2普通负例247过/14失败 → R2后 [277项全过XML](artifacts/reports/S02-R1-post-R2-20261012.xml)，无失败/error/skip/xfail。最终范围为S01自测36、内部S02 48、外部audit63、旧契约50/v2 59/迁移21；原失败和新产物互不覆盖。

全量中现有test_pilot_model.py/test_relabel_memory_mlx.py直接进行MLX CPU数值/梯度计算，并非纯CPU契约测试；不接受“全量运行但无模型调用”的无条件描述。本轮回验只执行明确的无MLX契约范围。必要全量收尾/数值检查要先明确真实模型路径、共享锁/中央预算和资源约束；不能以pytest名绕过入口或将局部绿色写成全量绿色。

依据 [R2实现报告](artifacts/reports/S01-R2-identity-revalidation-20261012.md)、[独立CPU回验](artifacts/reports/S02-R1-cpu-revalidation-20261012.md) 和 [源码关闭复核](artifacts/reports/S02-R1-source-R2-recheck-20261012.md)，Codex接受S01/R2/S02-R1的CPU契约交付；R1原报告保留reviewed并由R2补闭包。源码固定df18bc02…a2727，Contract/v2未改，未训练/提交或推送。后续S03已建立真实公开C0引用样例及固定公开fixture/归档，见 [保存约定](SPACETIME_STORAGE.md) 与独立342项回验；仍不接SQLite、3D/语义或模型输入。CPU工程与含MLX全量/模型验收分开记录。
