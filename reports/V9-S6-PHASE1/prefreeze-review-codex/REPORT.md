# P259：S6 a33d34b 冻结前独立复核

复核者：codex-s6freeze-rv-1115，tier2 / codex / code,math。2026-11-15。

结论：**建议打回，3 项必修（F1、F2、F3）。** 任务已完成，交回一级判断；不构成任何运行授权。

摘要（本段少于 30 行）：

- 审查对象：`a33d34b5cb8d06800f584a0abcfd788d16f80fcb`，聚焦新增构建器、候选编号增量及 6h/1h 配置。
- F1 / P1：构建器接受不完整、内部矛盾的“探针”，未核对原始校验证据与产物。
- F2 / P1：probe 评测跳过训练账本与当前源码身份的一致性核对；final 有此检查。
- F3 / P2：负/零耗时、伪增格数可进入预算外推，产生负预算或压低估计。
- 候选按盘数分组、组内按抽样次序编号：本次纯 CPU 核对符合设计。
- final 训练 21600 秒、评测 3600 秒：与设计 r2 一致。
- 本次运行：9 项静态检查通过；22 个构建器输入分支检查；候选顺序核对；probe/final 身份分支对照。
- 纯 CPU；未导入 MLX；未训练、推理、生成任何世界、读取实盘 artifacts、提交或推送。
- 所有自有写入均在本目录。其他会话修改保留，未回退。

## 1. 范围、独立性与输入身份

领取前未参与被审实现或此前 P257 工作。本会话使用唯一 ID 注册、领取 P259，按不超过约 3 分钟间隔主动心跳。卡面、AGENTS/CLAUDE、README、协作/任务/研究记录当前相关段落、DESIGN-r2、r2 复核、P257 报告均已读取。P257 是前次审查，不能替代本次新增构建器的复核。

`evidence/head-before.txt`、`head-after.txt` 确认本次两次取样 HEAD 都为目标提交。所有行号指向该提交的原文件，而非报告内的副本行号。`evidence/citations.txt` 保存带原行号的逐字引文；`input-identities.json` 保存提交字节与工作树字节 SHA256。取样时 9 个受审/引用文件均与目标提交相等。

重点文件 SHA256：

| 文件 | SHA256 |
|---|---|
| `reports/V9-S6-PHASE1/make_prereg.py` | `f2bd464f3a7e188c89cda7661d5fd61313f043baff5cb8c81ba59b20e3295a73` |
| `reports/V9-S6-PHASE1/run_s6p1.py` | `10998013257f8c781f265b3a150cddc3a838f7fc565aa362d46fdf36fa10de0c` |
| `reports/V9-S6-PHASE1/verify_s6p1.py` | `116f45ef23bcbf5e91cf64bb800db15eba9ff52da5a49a3dbcb3c5de4e1d0885` |
| `src/ainerzero/v9/experiments/s6/cells.py` | `08cc78493c865981583924a1bf217ae0be890ffc6478b446284f72e2ce1baa2e` |

隔离来源为 `git archive`，完整 argv 见 `evidence/archive-command.json`；只导出源码、有关运行脚本、设计和被检查的测试。未创建工作树、修改 git 索引或建立提交。快照约 3.6 MB，未复制模型/运行产物。

## 2. 必修 F1：探针真实性、完整性只检查了几个自述字段（P1）

`make_prereg.py:32` 原文：

```python
if pr.get("set") != "probe" or not pr.get("verify", {}).get("passed") or "gates" not in pr.get("result", {}):
```

它只要求 truthy 的汇总 passed 和存在 gates 键。`make_prereg.py:36` 检查报告自述的源码摘要与 `code_dirty == []`，但没有核验 schema、六个格的完整集合、六项重放、两项复训、pool 校验、8 个门的计算记录、errors/worlds/verify 文件及内容 SHA。随后直接把该 JSON 的哈希写入预登记（62–63 行）；哈希固定的是所提供的字节，不能补回缺失的运行证据。

独立 CPU 反例，见 `evidence/cpu-review-r3.out`、`cpu-results-r3.json` 与 `snapshot/cpu-cases-r3/`：

| 合成输入 | 构建器实际结果 |
|---|---|
| 没有任何真实 cell/verify/errors 产物，只填 JSON 和伪占位摘要 | 接受，生成预登记 |
| `result={"valid":false,"gates":{}}`，`verify={"passed":true}`，缺 cells/files 清单 | 接受 |
| 汇总 passed=true，但 `verify.replay.E-r0.passed=false` | 接受 |
| `verify.passed="false"` 字符串 | 接受 |
| 缺 schema、缺 git_head，报告第三方版本不同 | 接受 |

这些输入都标有 SYNTHETIC，不能当作真实探针。合成反例不是在证明当前实跑探针坏了，而是证明声称“必须来自正式运行器、校验通过且完整”的构建器并未做到该拒绝边界。

建议：从预期目录核对完整产物闭包与哈希，使用准确类型和预期键集合核验校验记录/配置/计算完成度；核对源码提交及运行版本。**不应要求能力门全部通过**，也不应修改门槛；探针只需流程合法完整、所有门有计算记录。`analysis.decide` 正常结果没有强制的 `valid=true` 字段，修复不能简单新增这个必填假设。

## 3. 必修 F2：probe 训练身份未与评测身份核对（P1）

`run_s6p1.py:257–261` 原文：

```python
if registered:     # every training invocation ran the frozen code under this preregistration
    _, rows = ledger_used(set_root / "train-ledger.json")
    code_now = manifest_sha(code_manifest())
    if not rows or any(r["prereg_sha256"] != pre_sha or r["code_manifest_sha256"] != code_now for r in rows):
        raise GD.GuardError("some training ran under a different preregistration or code")
```

`REGISTERED_SETS=("final",)`（48 行）。因此 probe 不检查训练账本，即便账本登记 OLD-training-code，评测报告依然在 268–274 行记录当前代码的摘要和 clean 状态。训练时这些身份本来就有记录（148–149 行），只是 probe 不消费。

另见 `startup_checks:86–87`，非 final 直接返回；`cells.check_cell_record:363–380` 验证挑选/揭示/权重文件集合，不把每格绑定到源码/库版本；`verify_cell_dir:383–390` 重算的是文件内容哈希。重放和仅 E/P 两格的复训也不能代替其余训练格的来源核对。

本次动态 CPU 对照执行从提交 AST 提取的原样 `run_eval`，输入完全相同的旧身份账本：

| 分支 | 实际结果 |
|---|---|
| probe | 写出当前身份报告，走到 `independent_verify`，由审查专用哨兵立刻停止 |
| final | 在报告/校验开始前以 `GuardError: some training ran under a different preregistration or code` 拒绝 |

这只验证守卫分支，不声称真实 MLX 全流程已经绕过。未执行校验子进程、模型加载、评测或世界生成。测试接缝详见 §7。

实际风险路径：同一 probe 目录的旧训练格在实现修复后保留；新代码重新做评测，报告 code_sha 指向新源码；构建器只看该报告而将探针称作在将冻结源码上训练完成。R/T 等非预登记复训格的训练差异不能由 E/P 的两格复训自动排除。

建议：probe 评测也核对每次训练的源码、提交状态、版本、配置与当前评测身份；报告保存可核验的训练身份闭包。代码修复后的旧产物如何使用由一级决定，本卡不授权补跑、改名重跑或修改现有运行。

## 4. 必修 F3：预算外推缺少耗时和格集合约束（P2）

`make_prereg.py:48–54` 原文：

```python
for cell, sec in pr["train_seconds"].items():
    per_arm.setdefault(cell.split("-r")[0], []).append(sec)
est_train = 1.15 * (sum(max(per_arm[arm]) * k for arm, k in reps_final.items()) + 5 * 90)
n_cells_probe, n_cells_final = len(pr["train_seconds"]), sum(reps_final.values())
est_eval = 1.30 * (pr["verify_seconds"] * n_cells_final / n_cells_probe
                   + pr["eval_seconds"] * n_cells_final / n_cells_probe * sum(worlds_final) / sum(worlds_probe))
if est_train > train_cap_s or est_eval > eval_limit_s:
```

没有要求耗时为正有限数、没有精确校验应为六个 `*-r0` 格、没有将耗时对回 cell/账本的原始记录。

CPU 输出：

| 输入 | 训练估计/秒 | 评测估计/秒 | 结果 |
|---|---:|---:|---|
| 六臂各 500 秒，verify=100、eval=100 | 16618 | 3033 | 接受，算术本身正确 |
| 六臂各 -500 秒，verify=-100、eval=-100 | -15582 | -3033 | 接受，错误 |
| 所有耗时 0 | 518 | 0 | 接受，完整规模探针不合理 |
| 正常六格外，额外加入六个不存在的 `*-r999=0` | 16618 | 1517 | 接受，评测估计被减半 |

边界检查有好有坏，不能一概说 fail-open：wrong set、明确 verify=false、源码摘要不符、dirty 标记、明显超预算、已有输出均拒绝；缺 timings/缺 G 臂/零世界在输出前异常拒绝；NaN 在 `round` 处异常拒绝，+Inf 在预算比较处拒绝。精确等于训练上限接受，略超上限拒绝。详见 r3 原始输出。

建议：校验耗时正有限、准确的臂/重复集合、世界数与重复数及预算常量，重算并绑定原始计时证据，再外推。异常拒绝最好提供明确原因，但不得转成默认 0。5×90 秒候选池估计和 15%/30% 余量是估算，当前实测总预算是否足够尚无完整探针报告可供本卡确认。

## 5. 本次确认的正确增量

- 候选编号：`cells.py:100–105` 使用 `(n_disks, rank, world, step)` 排序。rank 在同一盘数组内保持抽样顺序；仍按盘数分组符合设计。未将“按抽样次序”误解为跨盘数全局打乱。
- 用原函数 AST 和 600 个编码静态状态，固定种子、不生成世界，抽取 500 个。独立构造的抽样次序逐项相同；500 个唯一；相邻同世界连续步比例 `0.002004008016032064`。只证明构造算法，不冒称真实 full 池的邻接比例。
- `test_neighbouring_ids_are_not_neighbouring_steps` 的断言和独立 Z 几何真值测试已经写入目标提交；本卡未执行 native 测试。
- final 的 `train_cap_s=6.0*3600`、`eval_limit_s=3600`（运行器 46 行），对应设计 303 行逐字“训练硬上限 6 小时，评测另限 1 小时”。probe 为每臂 1 个重复、50/25 世界；final 为 5/5/5/5/5/3 个格、200/100 世界，28 格×3 网络=84 网络。
- 运行器 eval 报告包含 `sets`（271 行），新增的配置记录确实存在。
- final 的启动守卫核对 `pre.sets.final == set_summary("final")`（97–98 行）、已提交状态（99–101 行）、版本（95–96 行）。合成篡改 final cap 为 999999 会被构建器写入，但由该下游配置守卫拒绝；本卡没有把它误报为实际突破 6 小时上限。
- r2 的两项文字必修已落实：§0 逐门分结论、门表列出 G 轮且 GK-F 明示预计不过。GK-F/GZ-D 门槛维持不变。r2 复核报告的旧 sha 指向修订前稿件，保留其原语境，不当作最终稿同一 SHA。

## 6. 测试覆盖与验证结果

S6 的七份测试文件未发现 `make_prereg` 引用（逐文件记录于 `test-coverage-inventory.json`）；运行器 native fixture 也只复制 runner、verify。该检索是缺少构建器直接覆盖的证据，不是形式化证明全部仓库绝无间接覆盖。

本次执行：

1. `cpu_review.py r3`：22 个构建器分支输入，10 个接受、12 个拒绝；接受中包含必须修复的反例。脚本断言通过不代表构建器合格。
2. AST 候选顺序、唯一性核对通过。
3. probe/final 旧训练身份分支对照符合上述观察。
4. 静态测试：`9 passed in 0.04s`；`MLX_IN_SYS_MODULES False`。

首次 harness 将输入放在 archive 根之外，触发 `relative_to(REPO)` 的路径异常；这属于审查夹具错误，不能用作通过/打回证据。原失败 `cpu-review.out`、`cpu-results.json`、`cases/` 保留。r2 改为 archive 根内输入，复现问题；r3 追加临界输入，不覆盖 r2。r2/r3 的全部合成输入和生成输出均保留。

## 7. 安全边界、实际命令与未验证项

先静态核对写行为：builder 只以 `out.open("x")` 写指定预登记；真实 GD 版本函数会 `importlib.import_module("mlx")`（run_guard.py:163–177）。因此**没有直接运行未加约束的 builder CLI**。

CPU harness 的限制与接缝：

- `MetaPathFinder` 拒绝所有 mlx/子模块导入，末尾检查 sys.modules；不安装假 mlx。
- builder 仅将 GD.third_party_versions 换成 distribution metadata 读取；没有替换完整性/manifest/预算逻辑，源码文件不改。故本卡不声称验证了真实 MLX 包运行时的版本/来源行为。
- 候选函数由 AST 原样提取；candidate_worlds 只返回预先编码的静态对象，pool_seed 为固定 CPU 夹具，完全不调用世界 API。
- runner 仅 AST 提取 `run_eval` 和其纯辅助函数；startup、cell 数值验证及 git 元数据使用明确的 CPU 夹具；真实 GD 文件锁放本目录 fixture.lock，绝不拿共享模型锁；在 independent_verify 入口抛哨兵。测试保留了原始注册条件/账本比较代码。
- harness 的文件打开审计拒绝本目录之外的写入；禁用字节码。快照源码与测试保持导出字节，生成的合成文件均有 SYNTHETIC 标记。

关键实际命令（均以 `/Users/mac/AinerWorkFlow/AinerZero` 为 cwd）：

```text
.venv-ainerzero/bin/python -B reports/V9-S6-PHASE1/prefreeze-review-codex/evidence/cpu_review.py
.venv-ainerzero/bin/python -B reports/V9-S6-PHASE1/prefreeze-review-codex/evidence/cpu_review.py r3
```

完整 argv/原始输出映射见 `evidence/COMMANDS.md`。静态测试经禁止 MLX 的短驱动调用 pytest，`-c /dev/null --rootdir <snapshot> --confcutdir <snapshot> -p no:cacheprovider`，避免 live conftest/缓存写入。

本卡模型预算预留=0，训练更新=0，环境交互=0；未访问中央模型 RunStore。没有检查实盘训练账本、权重或最终探针评测结果，本卡不判断当前 MLX 运行成功/失败、不宣称真实能力过门或要求中止它。没有启动测试中的 native/MLX 路径。

审查期间初次 status 有其他未跟踪文件；后次 status 出现 `M COORDINATION.md`、`M RESEARCH_LOG.md`，HEAD 未变。本审查未写这些文件、未暂存/撤回任何改动。该并发状态与自有交付分开记录，原始 status 见 evidence。

修复 F1–F3 后需要在新身份上补直接的 CPU 拒绝回归，并由非作者复查。现有原探针、失败、摸底、报告全部保留；不通过改门、改预算、补填汇总字段来消除问题。**本卡只交回 P259，不领取下一卡。**
