# B14 独立复核：request_changes

二级复核者 codex-b14-20261028；2026-10-28；仅复核 B12 r2，不办理实现 accept。
本会话为用户指定的新独立会话，非 deepseek-q7m2 / claude-az 或其派生会话；没有继承作者上下文。
已读 AGENTS、README、COORDINATION（独立性/证据卫生/普通负例与拆门分账）、AGENT_TASKS 当前入口、RESEARCH_LOG 当前记录、B14 prompt、B12/B13 full 报告和 ADR-0014 accepted r3。
成功以 tier 2 注册并普通 claim，无 force、无抢占；本次仅此卡，不 --next。

## 裁决与主要证据

**request_changes**。B13 F1 的精确小写 llm/teacher + 合法 independent_test producer 漏洞已关闭；但按本卡要求的伪造对象/字段修改纵深尚不完整，不能建议接受 B12 r2。

1. **F1 / P1：未知或畸形起源在 promote 放行。** `interfaces/validation.py:344–357` 的 `require_slow_eligible_origin` 仅拒绝两个精确值；`interfaces/spatial_memory.py:101–118` 不重新校验枚举。独立构造有效证据，再通过 `object.__new__` 复制字段并改 origin 为 `LLM`、`Teacher`、`llm `、空字符串、None、unregistered，六者均真实进入 SLOW，且出现在 usable_slow_items。未修改实现、登记表或 producer。合法 producer 和 trusted_context 完全相同；不是要求把变体规范化放行，而是应 fail-closed 拒绝非允许值。
2. **F2 / P1：晋升不复验完整证据，嵌套字典可在构造后失效。** 同一独立合法证据只执行 `e.data_identity['test'] = e.data_identity['discovery']`，不绕过 frozen dataclass，不修改产品内部状态，仍晋升且可用。另用伪造对象的 D/C/T 全重合、kind=self_report 也能晋升。`PromotionEvidence.__post_init__/_validate_v2` 仅在构造时检查；promote 只重新检查版本、producer、起源黑名单与 Fragment 绑定。要求在消费边界重新验证必要不变量，避免构造时验证被当成永久可信。
3. **F3 / P2：原 16/16 承重声明过强。** 16 组基线均绿、删除守卫后的测试均红，但 G1 只是仍被 trusted_context_missing 拒绝而错误字符串不匹配（不是拒绝翻为成功）；G5 在 matched=None 上调用 .get 导致 AttributeError（不是非法输入被放行）。不得把测试任意报红等同承重。保留原件，由实现方补确实达到目标成功路径的隔离对照；本复核不改它的夹具或代码。

## 验证结果（分账）

- 合同回归：完整输入隔离副本 `295 passed`，原始日志/XML 在 evidence/complete-input-rerun/contracts.*。
- 独立新夹具：probe.py 不导入作者 fixture；手工用标准 JSON/SHA256 构造 producer 绑定，独立的 fragment、世界集身份、校准规模、错误预算引用、版本和测试 ID。24 项中 15 符合预期、9 项拒绝预期失败；每条失败均实际进入 SLOW，而非异常或仅返回状态。
- 普通起源负例：llm/teacher 各自正常构造、object.__new__ 复制、从合法证据修改起源三种，6/6 拒绝；拒绝后条目仍可 query_topology，未进入 SLOW。
- 正对照：sindy/symbolic/human/engineered 4/4 晋升并出现在 usable_slow_items。
- student producer、空 trusted_context、v1 三个纵深反例均拒绝；v1 可构造可读（另有合同验证）。revoke/demote 后均退出 usable_slow_items 且拓扑仍可读。
- 原 16 坏控：逐项隔离复制、仅移除指定守卫、单独执行作者目标测试，完整 stdout/stderr 和命令均保留。G1/G5 按上述证据降格，其余目标测试在拆门后断言失败；不把所有红测试统一称为成功路径承重。
- **独立起源坏控**：只拆 require_slow_eligible_origin 的调用，复用同一 probe.py 和相同输入，前述 6 条 llm/teacher 负例全部由 rejected 翻为 promoted（测试从符合预期变为失败），四个合法正对照仍 promoted。对应 evidence/complete-input-rerun/independent-origin-gate-removed.txt；证明新增门实际承重，但不抵消 F1/F2。

## 实际执行、身份及失败卫生

命令：`python3 reports/V9-B14/codex-b14-20261028/run_review.py`；补齐隔离输入后 `python3 reports/V9-B14/codex-b14-20261028/run_complete.py`。各子命令 argv、cwd、PYTHONPATH、退出码和完整输出在逐项日志首行；均通过仓库 .venv/bin/python 在临时 src/tests 副本运行，无作者 main 脚本原地再生成。

首轮因复核脚本漏复制 reports/V9-B12/cmfl_registration.json，出现 12 failed/283 passed，G15 基线也失败；这是复核环境错误，不归因产品。首轮全部原件位于 evidence/ 根，未覆盖。第二轮仅补齐该原字节输入，另目录 complete-input-rerun，295 全过、16 组基线全绿。

完整源码、合同测试、B12/B13 交付物和 ADR 前后 SHA256 清单见 evidence/complete-input-rerun/source-before.json 与 source-after.json；逐项零变化。evidence/complete-input-rerun/execution.json 的 changed_inputs=[]。关键源码与 ADR 完整 SHA 同时写入 metrics.json；新报告与全部产物 SHA 在 SHA256SUMS.json。

临时目录由 tempfile 创建，真实路径逐条归档，结束清理；不触及生产服务。模型导入由隔离 sitecustomize 与独立探针的 import finder 拦截，探针 loaded_models=[]。零模型、零 MLX/torch 导入、零下载/安装/付费/部署、零真实模型与预算台账写入；没有读取/连接生产 RunStore，不声称全系统零写或模型能力通过。
只写 reports/V9-B14/codex-b14-20261028/；未改实现/作者报告，不提交、不推送。任务执行不足 10 分钟，未到周期心跳间隔；交回前另发一次进度心跳。

## 交回统筹

请修复并重新交付：晋升起源采用合法集合的 fail-closed 消费校验；消费时复验会被构造器绕过或嵌套可变字段破坏的证据不变量；补 G1/G5 的真实承重证据。不得据本报告自动 accept 实现。规范化来源、可信上下文和证据出具者是不同轴；本报告不主张现有摘要绑定是密码学身份认证，也不声称能识破把真实 llm 来源故意谎报为合法 sindy 的语义造假。
