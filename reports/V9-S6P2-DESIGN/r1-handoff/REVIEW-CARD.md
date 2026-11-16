你是 S6 二期设计稿 r1 的非作者复核者。设计作者为 claude、codex；参与过本次 r1 编辑/裁决/作者侧检查的会话不得领卡，换 ID 也不算独立。先注册自己的唯一 agent 名并领取本卡，读完整 relay prompt。每几分钟心跳一次。

一、精确对象与先读
卡面 params.review_commit 为完整目标提交 SHA，params.design_sha256 为 r1 文本 SHA。先核对 Git 对象及当前文件 SHA；若工作树有并发改动，使用只读 git show 或在本交付目录中导出副本，不能 checkout/reset/stash。报告写明实际审到的源码/数据/配置身份。
先读 AGENTS.md、README.md、COORDINATION.md 当前首段、AGENT_TASKS.md 和 RESEARCH_LOG.md 最新 S6P2 条目。重点文件：
- reports/V9-S6P2-DESIGN/DESIGN-r0.md、DESIGN-r1.md；r0-review/REPORT.md、evidence/ 与原始不利结果（P268 是复核工作验收，结论为打回 r0）。
- tier1-explore/explore_p2f.py、results-p2i.json、run-p2i.log；必要时只读其依赖 explore_p2a/c/d.py 和旧轮次 JSON。
- src/ainerzero/v9/experiments/s6/world_b.py、tests/v9/experiments/test_s6_world_b.py。
- r1-handoff/REPORT.md、SOURCE_SHA256SUMS.txt 和 r1-author-check/（这些是作者侧检查，不能直接冒充你的独立验证）。

二、必须独立复验
1. P268 三项必修是否关闭：困盘事实与正确步长 0.1；GM3 固定分母 10，没违规也计不过，不允许 0/0 真；便宜规则族是否公平且结论范围准确。GM2/GM3 里的标签打乱并不保证模型一定违规，要核查设计是否自洽、可证伪，不得靠事后挑破坏版本。
2. 不重新训练，独立从 I 轮原始 JSON 与日志重算全部五臂四轮关键字段、首轮相同、最终差值和 GO。特别核查 tiny_world 含两类诱饵，GQ-W 用第 2–4 轮等样本量合计 142/4500，不能用最后轮 0.021333 替代。I 轮只是 1 个重复；固定 v0 参照和正式晋升后切换参照的差异须明确。
3. U/Q 是否确为免模型、免新标签，只读自身旧经验范围；主臂是否仍可能被便宜规则替代，两个独立非劣门有没有漏掉更强对照。核对 N 的20%保底、U/Q无额外保底、第一轮共享、标签封印和统计记录分离。
4. 全文跨节一致性：7 臂、10 重复、70 格、210 网络、840 轮次权重、70 条版本线；10 个区间判据，df9、Bonferroni m10、t=3.689662；GU 与 GU-H 不混淆。独立核算重复层风险，不把两层区间当重复层公式。
5. 起点模型第5–9组是否与一期流程逐位等价可验证，新增种子/命名空间和旧经验摘要/权重钉住的方案是否充分；前5组与后5组推论边界、final只读一次和晋升各段隔离是否成立。列出实现前尚须冻结的字段，不能把设计通过当作运行授权。
6. 预算是否遗漏构池、旧经验重建、起点模型、全部晋升版本 GM1、机制坏更新、挑选重放和复训。r1 的404分钟是含明确未计项的小计，候选8h并非正式授权；判断这种待探针闭合的设计是否可通过，必要时列必须在冻结前关闭的项，禁止为求通过自行放宽预算或门。
7. CPU执行已有 world_b 测试并独立检查大诱饵无新规律、困盘、无大柱子世界与一期规律相同；核对一期冻结清单仍完整。负对照须记录实际错误或拒绝原因，不能以非零退出自动算杀死。

三、严格边界
本卡只授权只读核对、纯CPU数学/动力学检验及现有纯NumPy测试。不得导入MLX、训练或重跑摸底，不生成 s6p1-* / s6p2-* 正式世界，不写 artifacts/，不改源码、测试、设计稿或原报告；不提交、不推送，不stash/checkout/reset，不挪文件，不杀进程。CPU生成世界仅用 s6t-* 替身。若认为确需额外MLX复现，报告未验证项并 relay ask 说明具体命令/成本，等待主责登记，不能自行开跑或绕锁。

四、交付与交回
仅写 /Users/mac/AinerWorkFlow/AinerZero/reports/V9-S6P2-DESIGN/r1-review/：REPORT.md、metrics.json、evidence/（独立复算工具、完整stdout/stderr、实际returncode、逐字 citations.txt）、SHA256SUMS.txt。证据脚本默认只读原产物，复跑写新的输出目录，不能覆盖交付证据。引文必须逐字且带核准后的文件/单行行号；脚本校验引文存在且行号正确，报告给“建议通过”或“打回”，后者分必修/应修；对预算、模型复现等限制明确写未验证。
完成后用原agent ID relay report 本卡 --result-file <REPORT.md绝对路径> --data-file <metrics.json绝对路径>。如有不能继续的条件，先留下已做和下一步，勿把作者自测当独立验收。
