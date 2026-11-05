# P21 非作者独审结论（minimax-p21-1022am，2026-10-22）

**建议 Reject**：r7 的三项裁决里「宿主唯一锚」与「终态计量」基本成立，「D 候选复验」在真冻结文档下不可用，并另有 3 个可复现强制反例。冻结参数本身无问题（7 叶差异全在允许清单内、科学值未动），缺陷在代码控制流。

强制缺陷（均可复现）：
- F1 终态 `completed` 提交不受 450 s 截止约束：`_train` 的最后截止检查在返回前，`run_worker` 随后的 `ledger.finish` 无时间检查、终态 transition 也不查墙钟预算 → 真实墙钟反例：完成时 wall_seconds 24.81 s > 截止 20 s 仍 `completed`；同样超时放在末次梯度则正确中止。
- F2 r7 计量拒绝产品自身写入的 `collecting`/`validating`/`stopping`（`ACTIVE_STATES` 缺这三个，prep data/smoke/verify 与所有 eval 都在写）→ 合法行被当「未知状态」，阶段总额抛错、入口以假的 `ledger_timestamp_invalid` 拒绝。
- F3 真冻结文档下 arm1/D 评测入口无法完成：实验按 `arm1_deadline_seconds=2` 登记、run 按入口 300 s 预算登记 → `run budget exceeds experiment run limits`（failed）；预算 ≤2 s 又被 `wall_time_budget` 拒（stopped，白耗一条 arm1 行）。任何预算都不行。
- F4 D「只 1 次评测」守卫失效：arm1 行的 config snapshot 无 `arm_id`，而守卫筛 `arm_id=="arm1"` → 第二次 arm1 评测未被拒，中央账本出现两条已完成的 arm1 评测行。

披露项：F5 报告的 `non_finite`/`overflow_timestamp` 拒绝清单与实现不符（NaN 预留被 `max(0.0,nan)==0.0` 静默当 0，守卫不可触发；远期有限时间戳被接受）；F6 `lifecycle.py`、A2 清单、pilot_model/checkpoints 未冻结，`verify_d_candidate_identity` 的 `digest` 赋值后从未被读（信任根未自证）；F7 r7 测试声称不导入 MLX，但 `arms.py` 模块级 `import mlx.core`；F8 `run_worker` train 分支不转发 CPU 替身，证据只到 `_train` 层。

通过项（独立复现）：51/51 冻结源 SHA 前后一致、真实账本字节未变；两真实 checkout 同一锚且 cwd/env 不可移动；真实 train 入口五种情形全对（合法批准+已有 completed/failed/stopped→already_attempted；clone→output_root_not_canonical 且 clone 账本 0 行；无批准对照→preregistration_not_approved；真宿主→preregistration_not_approved；第二 checkout→output_root_not_canonical）；共享锁跨 checkout 互斥且锁字节未变；计量与独立重算一致 720.267 s，5 个坏守卫变体全部被检出；prep/train/eval 行都计入阶段总额；D 身份 9 条全对、篡改/缺失/摘要不符全拒、checkpoint_id 与 tensors SHA 未混用；arm2/3/4 评测仍按 48 批 fail closed（不开 run、不前向）；生产 `_train` 冻结 3510 步协议 3510 次前向/3511 次预留/恰好 1 份最终检查点/零末步后预留，截止链四个反例全中止、恰好 450 s 边界仍完成；非有限停止规则在首步与末步都中止；r6→r7 逐叶 7 变化全在允许清单、科学值未动；测试 228/235（7 个需真 MLX，未验证）+ 378/378。

未获授权/未验证：真 MLX 的 D 前向、真实训练/评测/final/新数据/下载；7 个需真 MLX 的测试；真 `run_worker` train 全链；真实账本上的同形「已有尝试」正例（真账本只有 3 条 prep completed 行，正例在隔离宿主构造）；批准解析只在隔离宿主的真实格式批准行上验证（真 RESEARCH_LOG 无 r7 批准行）。

证据：`reports/V9-P21/minimax-p21-1022am/evidence/01..13-*.json`、`logs/pytest-*.txt|xml`、`probes/p01..p13*.py`；完整报告 `reports/V9-P21/minimax-p21-1022am/REPORT.md`（未改任何被审源码/冻结/真账本/批准行；P1 仍禁跑，本复核不构成运行授权）。
