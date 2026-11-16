# S6 一期设计稿 r3 非作者复核（只审 §5 预算与 §7 第 5 条）

> 一级 claude 照子代理最终回复原文落盘（HTML 转义已还原）。

- 对象：`reports/V9-S6-DESIGN/DESIGN-r3.md`，sha256 a9013cc5…bfc。
  与 a33d34b 中的 r2 相比只改了头部、§5、§7 第 5 条和 §12（`evidence/citations.txt`）。
- 复核者：claude 子代理（r0–r2 复核的同一会话）；2026-11-16。
- 范围与约束：
  - 纯 CPU，不跑 MLX。`identity_check.py` 调用 `run_guard.third_party_versions` 时只导入了 `mlx` 命名空间包，没有导入 `mlx.core`，也不碰 GPU（`mlx_namespace_only.out`）。
  - 只写本目录；未提交。

## 结论：打回（必修 1 项）

预算数字逐位正确；重新分段站得住；代码身份规则能实现，也足以让探针继续作为依据。缺的一块是第三方库的身份：MLX 版本现在实际上没有被锁定。

### 必修

1. **§7.5 加第三方库身份，并修好记录方式。**
   - 现状：`run_guard.third_party_versions` 读 `mlx.__version__`（`run_guard.py:175`）。`mlx` 是命名空间包，没有这个属性，于是记成 `"unknown"`。
   - 探针报告和探针账本里记的都是 `{'numpy': '2.5.3', 'mlx': 'unknown'}`（`identity_check.out` 第 4 段）。
   - 后果：final 启动时会核对版本（`run_s6p1.py:95`），但比的是 unknown 对 unknown。冻结后 MLX 被升级，这道检查拦不住；§7.5 也完全没提第三方库。
   - 建议改法：
     - 运行器的语法树差异再放开一处：`THIRD_PARTY` 从 `("numpy", "mlx")` 改为 `("numpy", "mlx.core")`。`mlx.core.__version__` 是 0.32.2，这个改动不碰数值路径。
     - 冻结入口用 `importlib.metadata` 记下 mlx、mlx-metal、numpy 的版本（还可以加安装记录文件的哈希），遇到 `unknown` 就拒绝。
     - 探针当时的 MLX 版本只能间接推定：三个包的 dist-info 都是 2026-10-14 安装的，早于 11-15 的探针，所以是 0.32.2。把这条推定写进预登记。

### 应修

1. 写明旧值怎么读、新值怎么写。
   - 旧训练上限在源码里是 `6.0 * 3600`（BinOp），不是字面量 21600；旧评测上限是常量 3600（`identity_check.out` (3)）。
   - 规定新值必须是数字字面量；旧值只允许做数字常量折叠。不能对任意表达式求值：占位节点里放一个带副作用的表达式也能「数值相等」。
2. §7.5 第 4 条写明「新上限取自当前运行器，不取探针记录」。现在的 `estimate_budget` 读的是探针记录里的上限（`prereg_evidence.py:363`、`:369`），那里是旧值。另外 `:120-121` 要求探针记录里的上限等于 21600 与 3600，这条应保留，正好对应规则 3 的「旧值」。
3. §5 写明校验的成本构成。探针的 616 秒校验里包括重训两个网络（E-r0-n0、P-r0-n0），这一部分到 final 仍然只有两个，不随格数增长。按格算，一个网络 4 轮约 180–200 秒，所以两次重训约 380 秒，占校验一半以上。这是推算，没有分段计时。公式把它也乘了 28/6，所以评测外推偏保守。现有写法「28 格比 6 格贵得多」只说了会增长的那一半。
4. 冻结入口记下 `MLX_*` 环境变量，出现非预期的就拒绝。`python -I` 只屏蔽 `PYTHON*` 变量。

---

## 1. 数字核对（`evidence/recompute_budget.py` → `.out`）

    est_train = 1.15 x (15265.00 + 450) = 18072.250000
    est_eval  = 1.30 x (616.0 x 28/6 + 19.6 x 28/6 x 300/75) = 4212.693333
      of which verify 3737.07 s (88.7%), eval 475.63 s
    r2: train 18072.25 <= 21600: True (margin 3527.75 s, 19.5%); eval 4212.69 <= 3600: False (margin -612.69 s, -14.5%)
    r3: train 18072.25 <= 19800: True (margin 1727.75 s, 9.6%); eval 4212.69 <= 5400: True (margin 1187.31 s, 28.2%)
    estimate_budget with r2 caps refuses: EvidenceError: 预计超出上限：训练 18072.250000 秒（上限 21600），评测 4212.693333 秒（上限 3600）
    estimate_budget with r3 caps -> (18072.25, 4212.693333333334)

- 输入：`train_seconds` 为 R 539.2、E 551.3、Z 550.3、T 530.6、P 590.6、G 485.0；`verify_seconds` 616.0；`eval_seconds` 19.6；探针世界 [50, 25]；final 世界 [200, 100]；28 格。
- §5 的四个数（18072.25、4212.69、+1727.75、+1187.31）和「超出 612.69」都正确。
- 直接调用实现的 `estimate_budget`（把上限分别换成 r2、r3 的值）：r2 拒绝，报错文字与 Codex 报告的一致；r3 通过。

## 2. 重新分段是否站得住（`evidence/train_margin.py` → `.out`）

    R: probe  539.2 s [135.1, 135.4, 134.3, 134.3]  | round G  557.3 s [140.8, 138.8, 139.5, 138.1]  | probe/G 0.968
    Z: probe  550.3 s [134.4, 138.1, 138.4, 139.2]  | round G  481.4 s [127.8, 100.8, 128.2, 124.5]  | probe/G 1.143
    per-round training time over both runs: min 99.8 s, max 140.8 s, max/min 1.41
    every round at the slowest observed 140.8 s:  16158.1 s  -> cap/total 1.225; slack  3641.9 s = 4.0 crashes at 900 s each
    uniform slowdown of every cell (vs probe) that reaches the cap with no crash: x1.288

- 每轮训练时间取决于机器状态，与臂无关：同一个臂在两次运行里相差可达 1.14 倍。探针的格本来就落在偏慢的一端（每轮约 134–139 秒）。
- 训练上限 19800 秒：每格都比探针慢 1.288 倍才会碰到；即使每轮都按观测到的最慢 140.8 秒算，也还剩约 3640 秒，够 4 次中断（账本每次中断多记 900 秒，`run_s6p1.py:126`）。训练撞上限就意味着 final 做不完，所以这是要紧的一侧，目前余量够用。
- 评测上限 5400 秒：按公式有 28% 余量。按应修 3 的推算，实际余量更大。如果在评测读过 final 分区之后才超时，后果不可挽回；但评测本身只占原始外推里的约 366 秒，校验结束后的剩余时间足够。
- 总量 7 小时不变，没有借用额度。

## 3. 身份规则是否充分（`evidence/identity_check.py` → `.out`）

    (1) a33d34b manifest from git archive: 42 files, sha 839063099cd798e73fa3e26cdaba3b859b2d63360f4ed8d3cc2ec54e25d610d3
        probe EVAL code_manifest_sha256      839063…  equal: True
        probe ledger code_manifest_sha256    839063…  equal: True
    (2) working tree manifest now: 42 files … equal to a33d34b: True; differing files: []

- **规则 1（探针身份）能实现。** 把 a33d34b 用 `git archive` 导出，用 `build_manifest` 按原入口重算，结果与探针报告和账本里自报的值都相等。实现时应在导出的 a33d34b 目录里重算文件清单，不能拿当前目录的清单去套 a33d34b 的内容。
- **两个常数不在数值路径上。** `train_cap_s`、`eval_limit_s` 只出现在训练截止、评测截止、`set_summary`、预登记核对和外推里（`citations.txt` 中的 grep 结果）。只要运行完成，结果与常数无关，所以探针的数值证据和计时证据都能延用到冻结代码上。
- **规则 2、3 难以被钻空子。**
  - 文件集合必须相同，其余文件逐字节相同；运行时 `check_loaded_modules` 会拒绝清单之外的仓库模块，验证子进程的导入闭包也在 42 个文件之内。
  - 语法树对比能挡住几种绕法：新增语句、改用别的变量名、在后面重新赋值、改其他集的上限，都会使语法树不同。
  - 注释可以随便改，没有影响。
- **漏洞：**
  - 第三方库身份（必修 1）；
  - 占位节点如果允许写任意表达式，可以夹带代码（应修 1）；
  - 预算用的上限从哪里取（应修 2）；
  - `MLX_*` 环境变量（应修 4）。
- **结论：** 补上必修 1 后，规则足以让探针继续作为冻结代码的依据，不需要重跑探针。

## 4. r3 正文其他问题

- 见应修 3：「28 格比 6 格贵得多」只说出了随格数增长的那一半成本。
- 未核实：§5 引用的「P260 独立复算 601 个字段零差异」不在本次范围内。

## 附：文件

- `evidence/recompute_budget.py`、`.out`：预算外推与直接调用实现的结果。
- `evidence/train_margin.py`、`.out`：探针与 G 轮每格每轮的训练时间、余量与中断次数。
- `evidence/identity_check.py`、`.out`：从 git 重算的清单、语法树节点形态、第三方库版本。
- `evidence/mlx_namespace_only.out`：证明只导入了 `mlx` 命名空间包。
- `evidence/make_citations.sh`、`citations.txt`：引文的原始输出。
