# B12 r3 实现交回（待新非作者复核，不自行 accept）
执行者 `codex-b12-r3-fix-20261028`，tier2/kind codex；普通 claim 成功，无 force；本会话及派生别名均属作者组，仅此卡，未领 B15/H6。
已读必需仓库入口、Relay prompt/latest reject、B14 REPORT、ADR-0014 accepted 与 DESIGN_CORE；本次仅原预算内 CPU 工程。
## 修复
消费入口先检查 v2、独立 producer 与合法起源，再以所有当前字段重建基础 PromotionEvidence，复验 kind、引用、校准、错误控制、D/C/T、版本和摘要等完整构造不变量；畸形/缺属性转 EvidenceRequired。
不调用待检对象的 is_v2/__post_init__/_validate_v2，避免子类覆盖；嵌套字典在消费时重新验证。起源采用合法集合且排除 llm/teacher，未知值/大小写/空值全部拒绝；不规范化放行。
未改 types、ParamBelief、MSGRouteRecord、G7 或登记表权威；v1 可读不可晋升，MID 拓扑保留，四种合法起源仍可晋升且可用。
## 验证（普通负例与真坏控分账）
隔离 src 副本+模型导入阻断：合同 **341 passed / 0 failed / 0 skipped**，新增46例；原295例全部保留。
普通探针：合法正对照可用 SLOW，G1/G5/llm起源/D-T重叠/kind 五条拒绝且条目仍可查询。
真坏控：5条成功路径、4种独立编辑；G1仅删除版本拒绝，使用其余 v2 字段齐全的 v1；G5仅将缺匹配绑定分支改为接受，保留存在绑定时的上下文/类别/摘要检查。
起源仅删除来源门；完整v2复验仅删除重建调用（分别证实 overlap 与 kind）。每条均 rejected→promoted_and_usable，正对照成功，其他独立门保持拒绝；没有把异常或其他门拒绝计为承重。
旧16坏控不重新认证；G1/G5旧声明保留原件，以上新证据替代。复制前/还原后源码逐字节一致；精确 mutant SHA 在 execution.json/metrics.json。
## 原始失败
将拒收r2两文件按原SHA复原到副本，同一新增测试得到33 failed/13 passed，原日志 00-rejected-r2-original-failures.txt。
首轮作者新增测试用错 QueryResult.items 导致41 failed/4 passed；修成 entries 并用固定合法查询版本后通过。原始01-targeted.txt保留，02-contracts.txt为修正后中间340项记录；最终以隔离341项为准。
NaN/Inf负例均拒绝；strict JSON仅使用字符串 "nan"/"inf" 记录观察，不输出非标准数值。
## 命令与身份
实际命令：`PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python -m pytest tests/v9/contracts/test_promotion_consumption_r3.py -q -p no:cacheprovider`（首次失败）；随后合同完整命令见证据；最终 `.venv/bin/python reports/V9-B12/r3-codex-20261028/run_controls.py --output reports/V9-B12/r3-codex-20261028/evidence/isolated-run`。
所有隔离子命令、cwd、PYTHONPATH、rc、stdout/stderr在 evidence/isolated-run/*.txt 与 execution.json；复跑请指定全新 --output，脚本拒绝覆盖。副本保留供复核，未删除。
实际 git HEAD `2de6caef0820894520271a8943761cc0b3cf8c22`；共享工作树未提交。文件前/后精确 SHA 清单：before.json、after.json。
最终 spatial_memory.py SHA256 `56bbda8a9a564b18a7ca7d4e570edf5094f3bde715c122a07b18d2435f824208`。
最终 validation.py SHA256 `0781a8272898df9bdcf4e036c69557de3cd142ec79bf31ce134e83997af15739`。
新增 test_promotion_consumption_r3.py SHA256 `293c0dba16e0d1b150b26c1b2e6dfab9fd0a5e01ff93418171ce42b0ebb7bd7b`。
## 范围、预算与限制
仅改以上两实现文件、新增范围内合同测试与本r3目录；其他已存在 interfaces/fake/contracts 文件与开工SHA一致；所有旧报告未写入。
原预算内短CPU工程测试，无新增模型预留/更新；零模型/下载/付费/部署/推送/提交，未访问真实RunStore/锁，未重启停止8790；开工注册领取与结束前heartbeat已完成，未到10分钟周期。
未跑范围外 tests/v9、未验证模型能力/统计证据真实性/真实生产者身份认证/生产部署；结构校验不证明来源语义真实。G7待审保持不动。
请主责依据 REPORT.md、metrics.json、evidence/isolated-run/ 与 SHA256SUMS.json 安排新非作者复核；本作者报告不构成 accept，不领取其他卡。
