# Character First 工作台登记候选

- 用户选定既有 AinerRelay 工作台；不新建网页，不升级服务源码。
- 数据执行负责人：workbench_landing（二级）；主责注册/写 API 与最终验收：Codex（codex-cf-20261017）。
- 本目录数据作者不验收自己交付；等 character_inventory 读最终文档、实际新卡、模块与原卡例外后给独立结论。
- 实际在线登记结果唯一入口为主责维护的 `registration-result.json`；本页数据已按实际 GET 核对29卡；独立验收仍由非作者完成。

## 已直接核实的生产边界

- 8790 health：部署 `20261016-dispatch-pagination`，source digest `34bb5efdd960570c3ccb9a7f77f08bf3f52c2bec55dece1b7525b6d2cb758c61`。
- 已读部署 server.py/TaskIn 与 db.py/create_task：任务 ID由 project/phase/track/seq生成；须先创建phase/track；该版TaskIn无module。
- GET `/api/modules` 是legacy共享JSON口径，91模块、errors=[]；未部署的native模块激活/回填不能当上线能力。
- 故候选仅以 params.module_hint + modules.v1.json唯一tasks成员归档。未使用DB/API写入、import全项目、project登记或catalogue。

## 实际登记与保留状态

合计29卡：awz 23卡、hub 6卡；A1/A2/A3为当前文档/非作者核对/一级发布，余13对是一个设计映射对和12个实现/验证对。所有新运行预算未批准。

- A1/A2/A3：design_only；A2 verifies A1，A3只办理CF设计发布，不办理A10。
- awz.CF.B1/B2：design_only，ready但等A3/B1前置；仅文档与只读核对。
- 其余24个产品实现/验证：blocked，execution_authorization=implementation_requires_A10+registered_budget；保留原业务实现与非作者复核前置。
- H1/H2完整验收候选额外标needs_gpu=2，尚无运行授权。未来X14仅留文档，不建执行卡。

| 本地键 | 新任务 → 非作者验证 | 唯一模块 | 职责 |
|---|---|---|---|
| CF-D01 | awz.CF.B1 → awz.CF.B2 | 4.10 | 【设计】合同与实际消费者映射 |
| CF-R02 | awz.CF.C1 → awz.CF.C2 | 1.3.4 | 【代码】runtime rig/control可执行绑定 |
| CF-G04 | awz.CF.D1 → awz.CF.D2 | 1.2.2 | 【代码】最小跨工具编译DAG与派生IR |
| CF-K05 | awz.CF.D3 → awz.CF.D4 | 1.2.2 | 【代码】最小内容缓存身份与闭包失效 |
| CF-W03H | hub.CF.B1 → hub.CF.B2 | 3.5.2 | 【代码】既有Hub worker消费核准角色与表演 |
| CF-P06 | awz.CF.E1 → awz.CF.E2 | 1.3.4 | 【代码】Body/Gaze/Hands同步曲线编译 |
| CF-P07 | awz.CF.E3 → awz.CF.E4 | 1.3.3 | 【代码】Face/Voice/Mouth音频同步编译 |
| CF-U08 | hub.CF.C1 → hub.CF.C2 | 4.6 | 【代码】表演版本提交与回放消费者 |
| CF-U09 | hub.CF.D1 → hub.CF.D2 | 4.6 | 【代码】AinerStudio角色可编辑表演曲线 |
| CF-Q10 | awz.CF.F1 → awz.CF.F2 | 1.4.2 | 【代码】基础ACIS/TACE身份与真实通道QA |
| CF-A11 | awz.CF.G1 → awz.CF.G2 | 1.3.4 | 【代码】根轨迹接触计划与风格化后校验 |
| CF-A12 | awz.CF.G3 → awz.CF.G4 | 1.3.4 | 【代码】双人共享节拍与有限联合约束 |
| CF-Q13 | awz.CF.H1 → awz.CF.H2 | 4.8 | 【有界运行候选】跨镜头与完整15秒可编辑验收 |

## 旧卡与项目保留

`projects.json` 保存全部5项目root/related_roots；`old-gated-tasks-before.json` 保存A10加22张依A10旧卡详情（公开21卡之外实际还有ainerzero.V9.G5），`old-gated-fields-before.json`聚焦冻结对照。`business-preconditions-before.json`保存32张相关业务卡详情；accepted只表示该任务交付接受，必须读范围，不能推断执行/能力。hub.P1.D3是旧复核，D2补修须等D6；E3是设计，执行仍等E5/E6；角色包D5/D10/D11原链与paused原样。

唯一主责批准的旧卡例外：`awz.P3.A3`追加`awz.CF.B2`、`awz.CF.C2`、`hub.CF.B2`三个前置；原A2/A10顺序、status/file_scope/params全保留。见old-task-additive-patch.json；其他22卡不改。R02和Hub worker不反依赖原A3，避免循环。所有原A3/A4与NPR D2/D3旧范围继续原卡承载，不另造同范围任务。

Hub实际链为blender_run→world_multicam；新卡只连接该链，worker.py历史入口只读。U08在已挂载production.py router接新adapter，U09明确Root.tsx最小挂载。新控制器/Body/Face、graph/cache、单人/双人各分文件，无并行同文件作者。

## 文件与操作

- payloads.json：全部29个已核对TaskIn候选；主责已逐卡POST创建全部29卡。
- phase-track-payloads.json：2个CF phase、11条track；主责已创建。
- current-doc-newcard-patches.json：A2新增只读核旧卡例外的候选PATCH。
- task-id-mapping.json/module-mapping.json：正式ID、seq、项目及单一模块映射。
- registry-before.json：本执行者改共享模块JSON前原字节备份；registry-mutation-log.json记录追加。level/paused/evidence/既有成员不变。
- registration-ready.json：主责登记后、待非作者复核状态；不是独立验收通过。

本执行者只做文件读取、只读GET、候选数据写入及已确认任务的legacy模块JSON追加；无数据库访问/API写入、产品实现、测试、模型、训练、渲染、仿真、下载、安装、付费、提交、推送、部署或服务重启。

## 主责登记后的只读元数据核对

- live-cf-tasks.json：29卡GET逐字段符合候选；A1真实已被文档作者claim。H1/H2返回needs_gpu=true，但gpu_level=2，按gpu_level核对重型等级。
- metadata-check-result.json：将4项目原board、29卡和唯一A3追加前置合图，从CF可达71节点；无缺依赖、无环；verifies/needs/blocked+A10/唯一模块全部通过。此为任务数据检查，不是产品测试或自我验收。
- old-gated-tasks-after.json：旧A10+22卡逐项核对，只有原A3追加指定3前置；其余字段/卡不变。projects-after.json与前照全部5项目元数据一致。
- registry-mutation-log.json：备份后追加29卡到9个既有模块；原91模块、既有成员、level/paused/evidence及顶层元数据不变。1.4.3继续paused=true。
- live-modules-after.json/live-module-check.json：29/29新卡在legacy模块API可见且唯一归属，errors=[]。

本执行者未写registration-result.json或service-restoration.json，两者由主责维护；在线API写入、唯一旧卡PATCH及最终验收归主责。

AGENTS轮末派生看板：已执行一次 `bin/relay-modules --strict --write`，退出0，自动生成modules/BOARD.md。strict未归档/登记缺失均无，详情及BOARD摘要见board-generation.json；本操作不是产品测试。
