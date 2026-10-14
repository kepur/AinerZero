# E13a-R2：固定登记身份与窗口消费边界

日期：2026-10-12 · 主责统筹：Codex · 状态：accepted，仅CPU身份/消费边界；e13a_r2_identity_boundary实现，[独立109项回验](artifacts/reports/E14a-R2-independent-review-20261012.md) 通过，Codex限范围验收；不启动模型。

接收 [R1报告](artifacts/reports/E13a-R1-grokbot-newbot-20261012T160618+0300.md) 的50项CPU测试证据。独立回验发现剩余F02边界：可传入其他registered身份，默认REGISTERED_INPUT也可改；无公开记录核对时source_verified仍为True；验证后的episode/展开动作步号可修改，而预算检查和键绑定继续信任旧状态/摘要。下面只修这些消费边界，不改变窗口、调度、逐调用seed、损失、参数、科学门或预算。

## 当前三个统筹决定

1. **本阶段不单独登记含MLX全量。** R1只改纯CPU层，先用定向测试、独立反例和公开数据只读核对验收。现有全量中有直接MLX前向/反向/优化及其他环境路径，尚无已登记的全量调用/更新/资源清单或受控测试入口。E13b/E14b之后C06a登记有限必要的数值/梯度/冻结/资源验证；不是把直接全量pytest包装成训练收尾。完整全量如后续确有必要，再单独清点和登记，不作为本CPU验收前提。
2. **固定M2m-d入口去掉registered覆盖参数。** 内置登记值使用不可变映射/独立常量，返回副本不能改权威值。通用窗口计算仍可接受合成样本；只有固定登记验证器能宣称匹配当前M2m-d池。
3. **v2摘要经独立复算后登记为E13b的固定预期值。** v1键内容SHA仍单独保留，v2绑定SHA不是新随机seed。E13b从真实文件/公开记录/账本建立expected binding并复算比对固定值，不能从待验证cache抄出expected；typed缓存验证不是完整身份闭包。

## 文件移交与实现

原作者grokbot-newbot的R1已reported。待独立审查完成稳定b6c39b76版本和末尾哈希检查后，由任务表指定的R2执行者接手 `src/ainerzero/learning/action_preservation.py` 与 `tests/test_action_preservation.py`。fixture `tests/fixtures/m2md_pool_manifest.json` 原字节保留；worker、CLI、tail_update、旧协议和原报告不改。执行者只写自己的实现报告/XML/log，根目录结论由Codex整合。

- `verify_registered_inputs` 删除调用者自填registered入口，固定原samples/schedule/report身份及train规则。REGISTERED_INPUT不可原地修改；返回registered_input即使被改，也不影响下一次验证。
- 明确两个CPU状态：`registered_manifest_verified`表示清单匹配固定登记；`public_records_checked`表示逐项核对了传入公开记录。无records不得声称公开源已核对。删除模糊的source_verified证明，或仅作明确恒False的过渡字段；本次选择删除，不留两个来源判据。`check_budget`只返回数字核算，不传播任何来源验证标记。两个CPU状态均不代表真实文件、中央run或缓存生产预算闭包已通过。
- 新增/复用一个CPU窗口内容重验入口：从当前rows重算v2窗口摘要，从当前schedule重算调度摘要及qmax/units；验证256行顺序、world/q/s/feedback合法且一致、四步展开的动作步号、schema和存储字段。`check_budget`与`key_manifest`消费前均调用它，不能把存储摘要或可改的verified布尔值作为证据。保持通用计算器和合成测试可用，不要求所有通用窗口都是登记池。
- v2摘要结构及原逐调用seed保持；真实登记的样本/调度生成相同v2窗口和键绑定。重算拒绝旧摘要下篡改episode/world/q/展开步号/schedule/qmax/units；不得通过刷新自填摘要将另一池认证成固定M2m-d输入。

## 定向测试和验收

保留原科学值及23项正向能力/预算/损失断言；R1中错误的source_verified=True断言须改为明确的清单/公开记录分层语义，这属于纠正API声明，不是降低科学门。新增普通失败测试覆盖：registered参数被拒绝、内置映射不可改、返回副本隔离、无records不宣称公开核对、check_budget无来源认证字段、验证后篡改episode/展开步号/schedule/qmax等被消费者拒绝。固定fixture的v2摘要及v1键内容值不变。

仅运行本模块无MLX定向CPU测试并保存实际XML/log；不跑全量、不创建run、模型缓存、预算预留、环境动作或优化更新。独立审查者复核R2源码、失败案例及原50项适当语义更新，确认已修而未放宽；之后由Codex限范围验收E13a，开放E13b领取。R1及其50项通过快照保留，不能覆盖成R2结果。

完整账本/M2l基线/文件闭包、AdamW后282,128元素逐位保护、worker/CLI/MLX及数值/耗时仍为 [E13b/C06a](M2MD_ACTION_PRESERVATION.md) 的未实现或未验证项。
