# P261：S6 预登记入口证据闭包与预算守卫修复

作者：codex-s6preregfix-1115（tier2 / codex / code,math）。任务已领取，完整prompt已读。

摘要：
- 修复范围仅 make_prereg.py、prereg_evidence.py、新 CPU 测试、本 prereg-fix 目录。
- F1：冻结入口核验原始证据闭包、类型、准确集合与四轮完整性；既有 analysis 重算全部门和描述量，能力门失败仍允许流程完整。
- F2：入口绑定 train ledger / eval / 当前源码与提交源码；原 run_eval 的 probe 来源自检缺口仍存在，未冒称修好了运行器。
- F3：正有限耗时、原始 cell/round/ledger/report 计时对照，准确六格，不允许虚增分母。28格、6h/1h与原式不变。
- 原42文件数值manifest仍为 `839063099cd798e73fa3e26cdaba3b859b2d63360f4ed8d3cc2ec54e25d610d3`。
- 正式冻结manifest另加入builder/helper，数值manifest不加入它们，不需要为入口修复重训。
- CPU正反例、零写入、预算等于/略超边界及6处对抗变异见下；禁止MLX导入的驱动均确认sys.modules无MLX。
- 真实eval在最终取样时已完成：84文件闭包和门重算通过；训练外推18072.25秒，评测4212.693333秒>3600，入口按原上限拒绝。
- 未改原probe源码/产物/设计，未提交推送、冻结、启动final、生成世界或训练；代码待非作者复查。

## 实现与边界

`make_prereg.py` 调用真实helper验证后才外推预算。校验、文档构建、JSON序列化与末次内容校验全部在排他创建输出之前；已有输出不覆盖。所有拒绝测试比较整个合成目录的内容摘要，包含Git索引，证明零部分正式文件且原始证据不改。

`prereg_evidence.py` 不导入 runner/cells/MLX。以静态配置表达式读取真实runner的三个set与cells的尺寸/臂配置；严格限制表达式类型，不执行模块体。原始数据路径从仓库固定probe根解析，不接受报告提供任意产物路径。依次核对：

1. schema/set/config/sets/第三方版本/报告源码身份与提交树字节；重复JSON键拒绝。
2. 六个原始cell与报告SHA；每格12个权重文件的准确集合和SHA；picks、reveals、四轮、编号范围/不重复、track数、seed/pool身份、分数摘要、T/R共同挑选。
3. 所有训练ledger行closed为真布尔；代码摘要与报告/当前42文件一致；版本一致；六格恰好一次且计时与cell/report一致。逐调用实际间隔覆盖其cell耗时，累计不得越probe训练上限。
4. 原始verify.json/hash与报告一致；六格重放、两项预指定复训、pool均为真布尔；逐轮数组长度与track数准确，三网络×四轮齐全。
5. errors.npz、worlds.json、verify.json准确集合与SHA；测试world ID/盘数/数量；原始数组key、dtype、shape、有限非负值。allow_pickle=False，不加载模型权重。
6. 原有AN.decide（10000 bootstrap，原seed/门/判据）、四轮AN.describe、选择重合度逐项重算对比；不要求all_pass。原公式允许的未定义科学统计，只有与原数组重算一致才接受，不改门。
7. report验证/评测时间正有限，二者之和不得大于报告总墙钟（计时舍入容差0.15秒），总墙钟不得越probe评测上限。round选择耗时允许0（原runner四舍五入会产生0），训练耗时必须正。

预算保持 `1.15*(Σ 每臂probe耗时*final重复数 + 5*90)` 和 `1.30*(verify*28/6 + eval*28/6*300/75)`，6h/1h未放宽，边界以未舍入数比较。等于接受、略超拒绝。

完整闭包记录84个文件的SHA（报告、pools、ledger、6个cell、72个权重、3个eval文件）。生成时还重查证据与正式manifest避免校验期间变化。正式manifest为原42文件加设计、builder、helper共45文件；builder/helper不会反向污染原runner的42文件code_manifest。

## 身份与不能声称的部分

工作仓库HEAD见 `evidence/head-delivery.txt`，三份改动源码SHA见 `evidence/code-sha256.json`；原42文件逐项摘要和聚合摘要见 `numerical-before.json`、`numerical-after.json`。对照当前已提交源码以及原probe报告的git commit树，每个数值源码文件的字节必须一致；因此允许只改builder/helper后的新提交，禁止把不同训练数值源码冒称为同一次probe。

原probe训练startup返回 `git_head=null`，helper保留这个事实，不补造训练commit；通过ledger代码摘要、报告commit源码树、当前提交树形成数值源码闭环。若ledger显式提供commit，也必须核对。Git读取用 `--no-optional-locks`，不刷新索引。

版本查询不导入MLX：检查MLX安装为namespace package并核对来源位置；与原GD第三方版本语义一致，顶层MLX没有__version__，原报告记录unknown。**unknown不是已确认的MLX distribution版本**，无法追溯训练时的未记录版本；没有冒称版本来源认证。其它布局拒绝，NumPy版本真实读取。测试仅替换此版本查询接缝，路径重绑定仅为隔离fixture，其余完整性/Git/预算/analysis皆真实实现。

哈希与闭包证明内部一致性，不能认证对恶意作者完全重造全部原始产物的真实性。本任务不运行实际重放/复训或加载权重，而是核对其既有原始校验证据。

原 `run_eval` 仍仅final核对训练账本源码，probe分支本身没有这道自检；本轮只在**冻结入口**拒绝来源不一致。不改run_eval是卡面明确边界，保住既有probe数值代码身份。

原报告没有单独落盘的verify/eval原始开始结束时间；能核对的是报告内计时与总墙钟、原始round/cell/ledger计时及SHA，不能把报告签名当外部可信计时来源。5×90候选池估计、15%/30%余量仍是原先外推，非未来实测保证。

## CPU结果、反例与变异

**最终102项通过（tests-delivery.log），6/6变异被杀死，静态检查通过。** 最终结果以 `evidence/tests-delivery.log` 为准，原命令见 `evidence/COMMANDS.md`。夹具全部标明SYNTHETIC：权重仅是文本字节，没有模型或世界，科学统计仅为测试入口控制流，不代表能力证据。真实Git检查使用临时合成仓库的临时提交；工作仓库没有暂存/提交。

正例六臂相等，GS/GP等科学门失败但完整流程接受；正式预算16618秒/3033秒，28格、6h/1h。反例包含空/改值门、truthy汇总、错schema/config/sets/版本/commit/代码SHA、缺格/伪增格、所有计时字段的负/零/NaN/±Inf/bool/字符串、错误轮数、篡改picks/reveals/权重、重算hash后的错误world/array/verify、账本开放/漏格/重复/旧源码、统计描述损坏。拒绝后目录内容摘要不变。

6个最终源码副本变异见 `evidence/mutations-delivery/results.json` 与各自pytest.log：

| 变异 | 应暴露的反例 | 结果 |
|---|---|---|
| M1 去掉逐项原始verify检查 | replay-false/truthy、retrain-false | killed |
| M2 去掉训练源码一致检查 | ledger旧训练源码 | killed |
| M3 信任报告门而不重算 | empty-gates、gate-value、gate-bool | killed |
| M4 去掉预算比较 | 两种超上限与略超边界 | killed |
| M5 去掉文件SHA比较 | 实际权重内容变化 | killed |
| M6 去掉逐轮重放检查 | rounds_ok中1代替真布尔 | killed |

每个变异都是明确的 `DID NOT RAISE` 断言失败，非导入/环境异常；6/6被杀死且MLX_IN_SYS_MODULES False。保留前一轮变异及每个副本源码/hash/完整argv/原输出，不覆盖旧证据。

首次CPU结果59失败/18通过是Git状态查询刷新**临时fixture索引**导致零写入断言失败，原日志 `tests-first.log` 留存；禁用Git optional locks后77/77通过，后续加强整数类型/MLX-free版本查询后80/80通过。最终又补完整计时矩阵和不完整eval拒绝，结果另记，不把旧版通过充作最终SHA通过。

## 真实probe、资源和交接

初次 `evidence/live-state.log` 取样时报告未完成，入口明确拒绝且不写预登记。**最终取样 `evidence/live-state-delivery.log` 时，原eval已经完成**：实际84文件闭包完整核验，原始errors重算的result/descriptive/selection与报告逐值一致，science_all_pass=true。源码未改、未导入MLX、未重新运行任何世界/训练/模型评测。闭包逐文件SHA见 `evidence/live-closure.json`，真实报告SHA `4a79000a646e8a817bd2916dd0471fb9ca221b2dac9d30fd67d00bc01ac16e9e`。

原公式实算：训练外推 **18072.25秒 ≤21600**；评测外推 **4212.693333秒 >3600**（约超612.69秒）。入口抛 `EvidenceError: 预计超出上限`，没有写任何正式预登记。真实计时与预算明细见 `evidence/live-budget.json`。这证明拒绝守卫按原线生效，不等同probe科学门失败；**不能为通过而调6h/1h、余量或公式**。下一步由一级依据预算拒绝和非作者复核裁决，不自行启动final。

模型预算预留0、优化更新0、环境交互0、下载0、付费调用0；没有拿模型共享锁或访问中央RunStore。只改卡面授权路径，根目录其它会话改动保留。提交工作为实现+作者CPU证据，**非独立验收、不自动冻结/晋升/启动final**。下一步：非作者复核此精确SHA及真实闭包；一级处理已核实的评测预算拒绝，再裁决后续。
