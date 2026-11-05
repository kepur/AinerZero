# ainerzero.V9.P36 执行报告
角色：executor；负责人：composer-x7k2；时间：2026-10-24 21:05 +0300
任务状态：reported（failed）；实验状态：部分完成 / 阶段墙钟耗尽后按冻结规则停手
任务依据：ainerzero.V9.P36 参数 v1；授权见 RESEARCH_LOG `R20261021-P1-stageA-budget` 批准行 document SHA `044d5599…18dd`；续跑卡协议与 P32 相同，幂等键前缀 `s1-r12b-`
输入身份：prereg 文件 SHA `fe539209…9658`；document SHA `044d5599…18dd`；领取时生产台账 SHA `6b604983…3f44`（WAL 0）；数据集 `8234f2f3…ad26`
修改文件：仅 `reports/V9-S1-r12/` 下本报告、指标与进度；未改源码/参数/批准行；未向生产 output-root 提交新作业
实际执行：本棒未启动任何正式 train/eval（阶段墙钟已超）；盘点上一棒产物并做副本 verify
验证结果：副本 verify status=completed、source_binding=passed、approval.approved=true（见 `verify-copy-p36.json`）；生产台账 verify 前后 SHA 不变
产物：本报告、`P36-metrics.json`、`verify-copy-p36.json`、更新后的 `PROGRESS.md`
失败与限制：阶段墙钟 `phase_wall_max_s=14400` 自 08:50 实验行起约到 12:50 关闭；本棒领取时已过约 +29620 s；按冻结规则不延长、不开新作业。剩余 arm3-s2、arm4×3 与全部评测未执行。不做能力宣称。
交回统筹：若需续跑，须一级另开授权/实验窗口（不得在本 r12 窗口内挪用额度或重跑失败种子）。

## 运行环境与 precondition 四项实测（报告第一行要求）

环境：Cursor 二级执行 agent `composer-x7k2`（kind=composer，model_version=未知）；主机 darwin；relay http://127.0.0.1:8790。
1. 本棒未在执行者环境起任何 train/eval 进程；此前 P36 作业均经 `relay submit-job` 由 runner 执行。
2. 组空以 runner `job-status.supervision.confirmed_empty` 为准（见下表）；本棒无新作业需归档。
3. 临时目录写文件与 `os.unlink`：ok（副本 verify 用 `/tmp/p36-verify-*`）。
4. 会话与心跳：领取后按 ≤10 分钟心跳；本棒因墙钟停手，墙钟内工作量短。

补充：本环境 `ps` 可用（rc=0）；仍遵守「组空以 runner 为准」。

## 开工核对（本棒 21:04）

| 项目 | 期望 / 说明 | 实测 |
|---|---|---|
| r12 prereg 文件 SHA | `fe539209…9658` | 一致 |
| 生产台账（领取时） | 放行时为 `77cb64d1…922c`（含 arm2×3）；P36 上一棒后又前进 | `6b604983…3f44`，WAL 0 |
| 副本 verify | status/source_binding/approval | completed / passed / approved=true，doc `044d5599…18dd` |
| 生产台账是否被 verify 改写 | 不许 | 前后均为 `6b604983…3f44` |

说明：任务卡正文「应为 `36426891…b67d`」对应 P32 开工前；P36 放行注记已更新为 `77cb64d1…`。当前 SHA 因上一棒 arm3-s0/s1 而前进，属预期进度，不构成绑定漂移。

## 训练作业盘点（含 P32 + P36 上一棒；本棒零新增）

| label | idempotency | job | 结果 | rc | RunStore/worker 墙钟 | 步数 | 1200s 内满 3510？ | 组空 |
|---|---|---|---|---|---|---|---|---|
| arm2-s0 | s1-r12-train-arm2-s0 | job-07e97f23… | completed | 0 | ~775–779 s | 3510/3510 | 是 | confirmed_empty=true |
| arm2-s1 | s1-r12-train-arm2-s1 | job-796cf5cd… | completed | 0 | ~709–713 s | 3510/3510 | 是 | confirmed_empty=true |
| arm2-s2 | s1-r12-train-arm2-s2 | job-60ff8abd… | failed | 1 | wall 1209.95 s | 2556/3510 | 否 | confirmed_empty=true |
| arm3-s0 | s1-r12b-train-arm3-s0 | job-e03bcde3… | completed | 0 | ~648–652 s | 3510/3510 | 是 | confirmed_empty=true |
| arm3-s1 | s1-r12b-train-arm3-s1 | job-a6b2004b… | failed | 1 | wall 1609.75 s；elapsed~236 s | 1341 reserved / 2169 remaining | 否 | confirmed_empty=true |
| arm3-s2 | — | — | 未提交 | — | — | — | — | — |
| arm4-s0/1/2 | — | — | 未提交 | — | — | — | — | — |

- arm2-s2：一级已核定为主机合盖睡眠环境失败；按协议不重跑。
- arm3-s1：`BudgetExceeded: wall_time_budget`；job 10:51:49→11:18:42；按协议不重跑、不挪用额度。
- P32 名下 409「任务回收中」的 arm3 三作业（job-9677f3a1 / 808e7b74 / 9a3f2702）未启动、不计尝试。
- 成功 run 目录：arm2-s0 `6632a9f0…`；arm2-s1 `ba45a3aa…`；arm3-s0 `ba42ba65…`。arm3-s1 仅有 `01561a10…/checkpoints`（0/439/878），无 completion.json。

### 峰值内存与交换区

resource_gate 快照（作业结束附近，非训练中采样）：process_rss≈0.036 GiB，swap_growth=0，swap_used=0，mlx_peak=0。参数 `unmeasured` 已声明训练后 memory 规模未测；**不以门禁快照当作训练峰值**。

## 评测

未执行（训练未全部结束，且阶段墙钟已耗尽）。arm1 D 复验与 arm2/3/4 development 评测均未提交。

## 解读边界（冻结注记，未评测故无新数字）

held-out=时间续段；checkpoint 0=未训练基线；M2 选点=字典序前 5；k=8 记 insufficient_data。本报告不解读未跑指标，不做能力宣称。

## 阶段墙钟

- 实验行 / 首次训练：约 2026-10-24 08:50 +0300
- `phase_wall_max_s=14400` → 约 12:50 关闭
- 本棒领取：21:03；已超约 29621 s
- 动作：**按冻结规则停止，不延长，不提交后续 train/eval**

## 本棒改动说明

- 未改上一棒科学产物；仅补充核对与报告。
- 未使用 `relay exec`；未写批准行；未读 final 分区；未生成数据。

## 交回阻塞（本棒实测）

`relay report --failed` 返回 409：「尚有未确认组空的 exec 或任务正在回收」。

- `recovery_pending=true`，`waiting_reason=等待匹配的 exec finished/stopped 组空归档`
- 卡在上一棒 exec `0ff85252eeb04015b6ad6d2bba915d3a`（job-a6b2004b…，arm3-s1）；`exec_finish.state=lost`
- runner 已给组空证据：`supervision.confirmed_empty=true`、`members_left=[]`、`group_empty=true`
- `finish_exec` 只能由原 agent `deepseekv41f-h3t8` 将 lost 升格为 finished/stopped；本棒不冒充
- 当前 `recovery.agent/claimed_at` 与本棒 `assignee/claimed_at` **不一致**，普通 `_finish_recovery` 路径无法自清
- 已 `relay ask` 阻塞提问 **#515**，等一级 admin-requeue / 清回收后再交报告

报告与指标文件已落盘，待 409 解除后立即重交。

## 第 3 棒只读复核（composer-m8k4）

角色：executor；负责人：composer-m8k4；时间：2026-10-24 22:08 +0300
动作：按参数 `current_control` 与信箱 #514/#516——**未** submit-job、**未** 新 train/eval、**未** 重跑、**未** 改参数；仅 shasum + job-status 复核并更新本附录。
复核：
- 生产台账 SHA `6b604983…3f44`，WAL 0（与上一棒封存一致）
- prereg 文件 SHA `fe539209…9658`；document SHA `044d5599…18dd`
- job-a6b2004b…：status=failed rc=1；exec_finished=true；group_empty=true；supervision.confirmed_empty=true；members_left=[]；lease_released=true；exec_id=0ff85252…
- 阶段墙钟：实验约 08:50 起，12:50 关闭；本棒领取约 22:07，已超约 +33481 s；按冻结规则停手
- 上一棒报告/指标 SHA（本棒未改正文科学盘点，仅加本附录前）：见本棒 metrics `prior_report_sha256` / `prior_metrics_sha256`
交回：将再试 `relay report --failed`；若 409 orphan recovery，再试 `relay release`；仍阻塞则只 heartbeat 后停写入（#516），不冒充原 holder 归档 lost exec。
不做能力宣称。续跑须一级另开授权/实验窗口。
