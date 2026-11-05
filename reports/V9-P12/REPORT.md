# ainerzero.V9.P12 执行报告：独立对抗复核 P9 r3

角色：reviewer（executor 层）；负责人：step5-3cfe（二级）；时间：2026-10-21 11:07–11:45（+03:00）
任务状态：reported；实验状态：未训练、未更新任何参数、未读 final；被复核对象：ainerzero.V9.P9 r3（deepseek-v41-p7k2，reported）
任务依据：接力台 ainerzero.V9.P12 任务卡（参数 v0 `{}` 照用未改）。复核者不是 P9 任何一轮的作者（P9 r1–r3 作者为 deepseek-flash-a7k2 / deepseek-flash-q8m4 / deepseek-v41-p7k2）。
沙箱：`/private/tmp/v9p12/{sandbox,f1,f1_drift,site,p1p4,dataset-copy}`；真实树只读；真实锁/中央账本/RESEARCH_LOG.md 未动（前后 mtime+SHA 逐字节一致，见 `real-files-before/after.txt`）。

## 摘要（≤30 行）

1. **冻结身份复现**：r3 document SHA `ed39c97c…5c94`、file SHA `f33d79ec…623a`、sidecar `8292aeb…daa4` 全部独立重算一致；`reports/V9-P9/r3/pre_registration.json` 与权威件逐字节相同；`validate(r3)` 零问题。r2 document `0547744f…4c07` 同样复现。
2. **r2↔r3 逐叶对比**：差异恰为 **15 叶**（13 改 + 2 增），分组 `approval_rule` 4 / `commands` 1 / `created_unix` 1 / `source_identity` 6 / `timing.smoke_recheck` 3，与 r3 报告宣称完全一致；`arms`、`training_protocol`、`data_identity`、`resource_limits`、`metrics`、`stop_rules`、`budget_estimate` 七块**逐字节相同**。
3. **参数/预算/种子/步数/资源线/指标/停止规则/数据计划零差异**：updates 3510、seeds 0/1/2、deadline 450 s、supervision 500 s、arm1 2 s、phase 4099.605 s、四臂参数 393232/207519/159455/274031、dataset_digest `8234f2f3…ad26`、资源线六项、六指标、停止规则全部相同；测量记录 r1 `b4e7d121…1ce8` 与 r3 复测 `68160d56…92ef` 的 SHA 与报告一致。
4. **变异矩阵 15/15 CAUGHT**（沙箱独立复跑，非引用 r3 结果）：原 12 项全部捕获（失败用例数 4/6/1/1/4/1/1/43/1/13/2/1，与 r3 报告逐项一致）；r3 新增 M13/M14/M15（P-1/P-2/P-3 三门）也全部捕获。基线测试 **126 passed / 0 failed**（r3 为 126）。
5. **P11 F1 用例 13/13 符合预期**：C1–C4 exit 3；**C5a exit 3 `research_log_not_canonical`**（r2 为放行，本轮必须 exit 3——达成）；C5b exit 3；**C6 exit 0 completed**，RunStore 记录批准行原文/行号 6/document SHA/日志 SHA 四字段全部与实际一致，转移 created→initializing→training→completed，optimizer_steps=0；C7 exit 3 `dataset_identity_mismatch`；C8–C11 exit 3（P-4）；C12 exit 3 `source_binding_drift`。C5a/C7/C12 均未登记 run。
6. **C5c 说明**：r3 把 C5c 并入 C6（P-1 后默认日志即唯一可读位置）。我独立复核后同意这一合并是规则变化的必然而非降门槛：C6 正是在执行层可写的规范日志副本里写批准行并放行，凭据全额入账；残余风险（谁能写真日志谁能批准）即 R-6，由一级 notice + P2 比对缓解，非代码问题。
7. **P-1 自写反例 4 例全按预期**：① `--research-log` 指向可写位置伪造日志（内含完全一致批准行）→ exit 3；② `--research-log` 用符号链接指向规范日志的**副本**（副本内有合格行）→ exit 3（resolve 后非同文件）；③ 控制组：符号链接指向规范日志**本体** → exit 0 放行（证明门按 resolve 路径判定，不误伤同文件访问）；④ worker 侧直调 + 伪造日志 → 拒绝 `research_log_not_canonical`。
8. **P-2 自写反例 3 例全按预期**：漂移 `data.py`（追加一行注释）→ exit 3 `source_binding_drift` 且漂移清单正确列出该文件；漂移 `cli.py` → 同样拒绝；worker 侧直调（data.py 已漂移）→ 同样拒绝。批准行均合格，拒绝确由 P-2 门产生。
9. **P-3 自写反例 3 例全按预期**：① 改 manifest 的 counts 并把 `dataset_ref.json` 的 `manifest_sha256` 一并改写（模拟攻击者同步改引用）→ exit 3 `dataset_identity_mismatch`（manifest 体摘要不符）；② 改数据文件 `packets/train.jsonl`（追加 1 字节，manifest 未动）→ exit 3（文件摘要不符）；③ worker 侧直调 → 同样拒绝。
10. **P-4 自写反例 5 例全按预期**：行写在别的小节 / 围栏代码块 / 引用块 / 节内两条合格行 / 节标题被改名，全部 exit 3；两条合格行拒绝原因写明"exactly one is allowed"，改名后拒绝原因写明"no section"。
11. **扫描器级补充探针 9 项全部正确**：四空格缩进代码与制表符缩进被跳过、`~~~` 围栏被跳过、大写 HEX SHA 不接受、行尾多余文本不接受、两个前导空格接受（Markdown 语义）、三级标题不结束小节、围栏内的假标题不计为节标题。
12. **真实文件零改动**：RESEARCH_LOG.md、两层 control.sqlite3、m0-worker.lock、pre_registration.json 及侧车，前后 mtime 与 SHA256 完全一致；真实日志当前无任何批准行（1 节 0 行）；真实树 12/12 源绑定仍 passed。
13. **结论：建议通过**（见"交回统筹"第 1 条的限定）。

## 输入身份

| 对象 | 身份 |
|---|---|
| 被复核冻结预登记（权威） | `artifacts/v9/s1/phase1/pre_registration.json`；document `ed39c97c5747daeb3f810658882dd5f9510b854e4f95048dad801205b1f55c94`；file `f33d79ecb1010af0ce9324499c8b257c9538da5e38a9474ff4ff2339eac6623a`；sidecar `8292aeb386df01106e1e9cb2be9b23d146704fb6dabd504eadf2c5e14c5edaa4` |
| r2 冻结（对比基线） | `reports/V9-P9/r2/pre_registration.json`，document `0547744fc142adae198b6d2fcfe6a6ac273fa092857649361bbf2dd157a14c07` |
| 被复核源码 | `src/ainerzero/v9/experiments/s1/`（11 文件）+ `src/ainerzero/cli.py`；真实树 12/12 绑定 passed，我未改任何源码 |
| 数据集 | `artifacts/v9/s1/datasets/8234f2f3…ad26/`（17 MB，digest 与 r2 相同）；P-3 反例用 `/private/tmp/v9p12` 下的两份私有副本 |
| 测量记录 | r1 `b4e7d121…1ce8`（冻结来源）、r3 复测 `68160d56…92ef`，SHA 均复核一致 |
| 我的沙箱 | `/private/tmp/v9p12/`：src/tests/RESEARCH_LOG.md 副本（与真实树 diff 为零）、数据集符号链接 + 两份私有副本、sitecustomize 训练桩 |

## 修改文件

只写 `reports/V9-P12/`（本报告、metrics.json、tests-s1-baseline.xml、harness/ 三个自写复跑脚本及结果 JSON、real-files-before/after.txt）。未改任何源码、未动真实锁/账本/RESEARCH_LOG.md、未提交 git。

## 实际执行（准确命令）

```bash
# 身份与领取
python3 /Users/mac/AinerWorkFlow/AinerRelay/bin/relay register --agent step5-3cfe --tier 2 --kind step --profile-file profile.json
python3 /Users/mac/AinerWorkFlow/AinerRelay/bin/relay claim ainerzero.V9.P12 --agent step5-3cfe --token b609bb60…fd935
# 真实文件前后记录（mtime+SHA）
/tmp/record-real-files.sh reports/V9-P12/real-files-before.txt   # ...-after.txt 同
# 冻结身份与逐叶对比（只读）
PYTHONPATH=src .venv-ainerzero/bin/python -c "prereg.document_sha256 / validate / source_binding_state / scan_approval_log(真日志)"
# 沙箱搭建
rsync -a src/ tests/ RESEARCH_LOG.md → /private/tmp/v9p12/sandbox/；datasets 符号链接；dataset-copy 私有副本
# 15 项变异（沙箱内）
.venv-ainerzero/bin/python reports/V9-P12/harness/mutations_p12.py            # 15/15 CAUGHT
# 基线测试（沙箱内）
cd /private/tmp/v9p12/sandbox && PYTHONPATH=…/src …/pytest tests/v9/experiments -q --junitxml=…/tests-s1-baseline.xml   # 126 passed
# P11 F1 用例 C1–C12（沙箱内）
.venv-ainerzero/bin/python reports/V9-P12/harness/f1_approval_p12.py          # 13/13 符合预期
# P-1~P-4 自写反例 16 例（沙箱内）
.venv-ainerzero/bin/python reports/V9-P12/harness/p1_p4_counterexamples.py    # 16/16 符合预期
```

## 验证结果

| 项 | 结果 |
|---|---|
| r3 冻结身份 | document/file/sidecar 三 SHA 独立重算一致；reports 副本与权威逐字节相同；validate 零问题 |
| r2↔r3 逐叶 | 15 叶差异（4+1+1+6+3），七不变块逐字节相同；参数/预算/种子/步数/资源线/指标/停止规则/数据计划零差异 |
| 变异矩阵 | **15/15 CAUGHT**（原 12 + 新 3），每项失败用例数与 r3 报告一致 |
| 基线测试 | **126 passed / 0 failed / 0 skipped**（与 r3 相同） |
| P11 F1 | **13/13 符合预期**；C5a exit 3（必须项达成）；C6 exit 0 且 RunStore 四字段匹配；C5a/C7/C12 未登记 run |
| P-1 反例 | 4/4（含 1 个放行对照组，证明门不误伤同文件） |
| P-2 反例 | 3/3（data.py / cli.py / worker 侧），漂移清单正确 |
| P-3 反例 | 3/3（manifest 篡改+引用同步改写 / 数据文件篡改 / worker 侧） |
| P-4 反例 | 5/5（别节/围栏/引用/双行/改名标题） |
| 扫描器探针 | 9/9（缩进代码、~~~围栏、大写 SHA、行尾文本、前导空格、三级标题、假标题等） |
| 真实文件 | 前后 mtime+SHA 完全一致；真日志 0 批准行；真实树源绑定 12/12 passed |

## 产物

- `reports/V9-P12/REPORT.md`（本报告）、`reports/V9-P12/metrics.json`
- `reports/V9-P12/tests-s1-baseline.xml`（126 passed）
- `reports/V9-P12/harness/mutations_p12.py` + `mutations-p12.json`（15 项变异独立复跑）
- `reports/V9-P12/harness/f1_approval_p12.py` + `f1-approval-p12.json`（P11 F1 13 例独立复跑）
- `reports/V9-P12/harness/p1_p4_counterexamples.py` + `p1-p4-counterexamples-p12.json`（16 例自写反例）
- `reports/V9-P12/r2-r3-leaf-diff.json`（逐叶对比明细）
- `reports/V9-P12/real-files-before.txt` / `real-files-after.txt`（真实文件前后指纹）

## 失败与限制

1. ** harness 自身两处已修正并留档**：① 首轮 P2-a/P2-b 误将漂移树与用例根共用同一目录，被 `fresh_case` 清树后 import 回落到真实安装，批准门先拒（拒绝本身正确但门位错误）；改用独立目录后复跑，两例均在 `source_binding_drift` 正确拒绝。② worker 直调初版经 sitecustomize 桩，SystemExit 在 site 初始化阶段被解释器记为退出码 1（worker 报告本身 `worker_exit=2`、拒绝阶段正确）；拒绝类用例不触及 `_train`，复跑去掉 shim 后进程退出码即 worker 自身契约值。两点均为沙箱 harness 伪影，非产品缺陷；supervisor 以 worker JSON 报告定退出码，故 C6 的 CLI exit 0 不受影响。
2. **未验证项**：真实训练/评测未跑（按卡）；`--mode train` 放行路径只到"四门全绿 + 登记 run + 调 `_train`（桩）"为止；`relay exec` 本机沙箱仍报 `exit_unconfirmed`（与 r2/r3 同），本卡未依赖它。
3. **R-6 仍是纪律约束**：谁能写仓库 `RESEARCH_LOG.md` 谁就能批准自己（C6 在沙箱可写日志副本上放行即证明此路径存在）。缓解按一级裁定：一级写入时同时发 relay notice（document SHA + 行号），P2 逐项比对。本卡未写、也不会写批准行。
4. **变异矩阵的测试属性**：变异复跑证明"现有测试能抓住对这些锚点的破坏"，不等于证明系统无其他缺陷；本卡另以 16 例自写反例 + 9 项扫描器探针扩大覆盖。
5. **P-4 的接受语义**：两个前导空格内的批准行会被接受（`stripped` 语义，与 Markdown 行内语义一致）；四个空格/制表符缩进被视为代码跳过。此为既有规则，未见被滥用的路径（节内仍要求唯一一条）。

## 交回统筹

1. **结论：建议通过**。卡面验收标准逐项达成：r3 冻结身份复现且与 r2 实质零差异（15 叶全在批准规则/命令文案/冻结时间/源身份/冒烟复测五组）；12（实跑 15）变异全部按预期；P11 C1–C5c、C6 全部按预期且 **C5a 必须的 exit 3 达成**；P-1～P-4 每条 ≥2 个自写反例（实际 3/3/3/5 例，另加 1 个放行对照组与 9 项扫描器探针）；真实锁/账本/RESEARCH_LOG.md 前后 mtime 与 SHA 不变。
2. 请一级按 r3 报告"交回统筹"第 2 条操作：在 `## R20261021-P1-stageA-budget` 节内写入唯一一行 `APPROVED s1-phase1 prereg document_sha256=ed39c97c5747daeb3f810658882dd5f9510b854e4f95048dad801205b1f55c94`，同时发 relay notice 写明该 document SHA 与行号（R-6）。
3. r3 报告"失败与限制"第 2 条（步数仍按 r1 测量记录冻结、r3 复测 6.524 ms 若直接用得 3752 步）我同意其口径：任务卡要求步数不变，r1 测量记录 `b4e7d121…` 是冻结来源，r3 复测仅作 `smoke_recheck` 交叉记账，规则/上限/预算线未动——建议一级明示确认此口径后即可批准。
4. 本报告不构成运行授权；真实训练（V9.P1）仍须按项目锁/预算规则另行批准。
