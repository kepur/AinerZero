# S6 一级接手与进度跟进

用户 2026-11-15 要求读取 Claude 目录、检查进程、一级统筹、释放任务卡片并全权跟进。

主责：codex；原作者：claude。代码基线 a33d34b5cb8d06800f584a0abcfd788d16f80fcb。

既有训练 PID 26667，PGID 26662，S6 probe train，原样继续，不重复启动。当前6臂中R/E/Z/T已完成，P进行中，之后G。锁为 artifacts/locks/m0-worker.lock。Claude 活跃会话出现用量上限，进程本身正常。

Relay 无 claimed 或 reported 卡片，没有可行政回收的在领任务。旧草稿仍有原预算/下载或收口边界，不一键放行。

推进顺序：完成已有探针训练→既定 probe eval（自身持锁，50+25世界、重放与复训、上限1小时）→预算与冻结前检查→预登记独立复核→符合全部守卫再执行下一阶段。未冻结前不读final。科学门槛不变。

当前并行派发：冻结构建器及最后增量的非作者只读审查；探针产物的CPU独立复算与计时检查。卡片、状态和结论写入本目录。

## 接续命令与前置条件

- 已有 probe train 完成判据：`train-probe.log` 明确 training complete；train-ledger 最后一行 closed=true；6个cell.json齐全；原PID退出、共享锁释放。
- probe eval 使用原运行器：`.venv/bin/python -I -X pycache_prefix=<全新目录> reports/V9-S6-PHASE1/run_s6p1.py eval --set probe --report reports/V9-S6-PHASE1/probe/EVAL-probe.json`。运行器自行获取共享锁；存在同名报告/评测目录时拒绝重跑。
- 等P259、P260交回后核对真实证据、引文与SHA，只有通过才能安排冻结。
- 预计final训练按原式 `1.15*(Σ max(probe每臂耗时)*reps + 5*90)`；final仍6h，eval1h，科学门不改。正式运行不以probe门的成绩作选臂/改参依据。

## 常驻接续

探针后续监督作业：`run-20261115-220152-e05f91`，归一级卡 P258，runner PID40173，专属队列 `/Users/mac/AinerWorkFlow/AinerRelay/data/runs-codex-s6-20261115`。旧默认队列未启动、未移动。包装器只等原训练完成，再启动一次既定 probe eval，自检源码SHA和输出不存在；不会启动final。

查询：`RELAY_RUNS=/Users/mac/AinerWorkFlow/AinerRelay/data/runs-codex-s6-20261115 /Users/mac/AinerWorkFlow/AinerRelay/bin/relay --agent codex run-status run-20261115-220152-e05f91`。eval原文：本目录 `evidence/eval-probe.log`。

接续托管实证：第一次 shell 启动的 runner PID39685 在命令结束后退出，没有启动作业；随后改为 launchd 临时作业 `com.ainerrelay.runner.codex.s6.20261115`（不写登录启动配置），PID40173、PPID1。队列作业已进入 running，exec_id `3ff6c60c860f45aa845d85296bfdbf3b`，包装器PID40174。专属队列和默认历史队列隔离。原训练仍由原PID26667持锁。

## P259 审查结论已核实：正式冻结暂不放行

P259独立复核发现F1证据闭包缺失、F2 probe训练来源不核、F3预算输入不严。一级在自有副本复现F1-F3核心反例，380项SHA一致，接受其审查结论（不表示原构建器合格）。修复卡P261已由独立worker领取，只改make_prereg/可选prereg_evidence与CPU测试，严禁修改原probe运行中的42个源码文件。以冻结入口核对train ledger/原始产物/current manifest闭环来最小化修复；run_eval自身不足仍明确保留。须P259非作者或另一非作者复查通过才可能冻结。

## Probe 已完成并独立复算：预算阻断

原训练6/6闭账，总3275.281s；接续作业整组结束、rc0、锁释放。probe eval verify=true(616.0s)，eval=19.6s，50+25世界，8门均算完；K=1仅查流程。P260独立复算601项零差异、完整性0问题，一级复制工具至自有目录复跑，同样601/0/0，原式预算拒绝(预期exit1)。P260审查验收，不代表放行final。

训练外推18072.25s≤21600；评测4212.6933s>3600。当前正式冻结/final阻断，尚无PREREG与FINAL_READ_ONCE。P261已reported（102作者CPU、6变异），P262独立复核中；修复入口正确拒绝本真实probe的超预算，不改公式/上限。
