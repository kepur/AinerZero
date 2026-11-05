"""由 r1 PROTOCOL.md 生成 r2 PROTOCOL.md：只做枚举的段落替换（每处断言旧文本恰好出现一次），其余逐字不变。同时生成 AMENDMENT.md。"""
from __future__ import annotations

import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
T28 = HERE.parent
r1 = (T28 / "PROTOCOL.md").read_text(encoding="utf-8")
r2_sha = (HERE / "proposal.sha256").read_text().split()[0]
p2 = json.loads((HERE / "proposal.json").read_text())
ev = p2["amendment"]["evidence"]
NPATHS = len(json.loads((HERE / "diff_r1_r2.json").read_text())["changed_paths"])

REPL = [
    ("# DA3 有界标定方案 r1：已知内参、锚帧对齐的诊断候选", "# DA3 有界标定方案 r2：模型自估内参、锚帧对齐的诊断候选"),
    ("机器文件 `proposal.json` SHA256 `af3131a51bf93ff12b43c08b4ca564124c1b1542cf9f9e196316cfa6e391cb4a`",
     f"机器文件 `r2/proposal.json` SHA256 `{r2_sha}`（取代 r1 的 `af3131a5…`；r1 文件原样保留，未被改写）"),
    ("须由 T29 不同作者复核，再由当前一级登记精确 SHA",
     "须由新的独立数学复核卡复核（作者 claude-az，复核人必须不同；r1 当时是 T29，r2 是 T39），再由当前一级登记精确 SHA"),
    ("所有正例前向提供冻结的真实 K；不向 DA3 提供真实外参。输入均为 development，280×210，process_res=280。因此只测 **已知内参条件下** 的相对位姿与相对深度，不称盲内参恢复、绝对米制输出或真实世界能力。若需要未知 K 的教师能力，要另一个冻结 profile；不能把两类样本混进一个噪声模型。",
     "所有前向都**不向 DA3 提供内参或外参**（真值 K 只记录，用于描述性比较）。输入均为 development，280×210，process_res=280。因此测的是 **在不向 teacher 提供任何相机参数的条件下** 的相对位姿与相对深度；teacher 自己读出的焦距只作描述，不是条件化；不称已知 K 条件化、盲内参恢复、绝对米制输出或真实世界能力。若需要已知 K 条件化的教师能力，那是另一个冻结 profile（在这版 DA3 上只能同时给外参，见 AMENDMENT.md 选项 B，会让位姿标定失去意义）；不能把两类样本混进一个噪声模型。"),
    ("当前 pipeline 尚无显式已知 K 接口；必须在 T6 正式领取后的范围内补充、记录源码 SHA 并经不同作者 CPU 审查，再执行该方案。这份文件不是已经可用的代码。K 必须随上游预处理正确变换，输出尺寸必须与固定 GT 一致，否则拒绝；不临时改分辨率/插值来通过。",
     "本方案**不需要任何 K 接口**：管线 `process_keyframes` 原样使用，DA3 自己预测的内参随输出保存。输出尺寸必须与固定 GT 一致（process_res=280 时为 210×280），否则拒绝；不临时改分辨率/插值来通过。这份文件不是已经可用的代码；标定 runner 由 ainerzero.V9.T37 重写并经 T38 复核。"),
    ("两型号各以 world00 已知K的 MPS/F32 正例作为引用", "两型号各以 world00 的 MPS/F32 正例作为引用"),
    ("错K负对照将所有3帧fx×1.5、fy×0.75，主点不改。正例已使用正确K，保证比较的是同一个条件profile。每阶段输入关联及错K值预先冻结为允许的有界压力输入，不靠生产绕过开关。",
     "r1 的错K负对照已移除（见 AMENDMENT.md：这版 DA3 在没有外参时忽略内参，该对照按构造不可满足）；本方案**不**引入替代对照。输入关联预先冻结为允许的有界压力输入，不靠生产绕过开关。"),
    ("不能保证模型必然对错K更差，发现没有更差本身就是失败结果", "不能保证模型必然对帧序错乱更差，发现没有更差本身就是失败结果"),
    ("| MPS/F32错K负对照 | 1 | 3 | 3 |\n", ""),
    ("| 每型号合计 | 11 | — | 31 |", "| 每型号合计 | 10 | — | 28 |"),
    ("| 两型号合计 | 22 | — | 62 |", "| 两型号合计 | 20 | — | 56 |"),
    ("MPS/F32四阶段连续完成后卸载", "MPS/F32三阶段连续完成后卸载"),
    ("剩余2视图不用于自动补跑", "剩余视图（预留数 − 计划 56）不用于自动补跑；预留数的记账口径见 open_items，尚待用户决定"),
]
out = r1
for old, new in REPL:
    assert out.count(old) == 1, f"r1 PROTOCOL.md anchor not found exactly once: {old[:40]!r}"
    out = out.replace(old, new)

tail_marker = "## CPU作者证据和待独立复核"
assert out.count(tail_marker) == 1
head = out[: out.index(tail_marker)]
tail = f"""## T39 复核后补入的三条说明

1. **逆序控制检验的是"关联错乱"，不是时序推理。** 它变红来自协议自己的槽位对齐：锚点槽（0）和尺度槽（2）收到了不同的物理相机，而 GT 标签仍是 [0,1,2]。
   一个完全不做跨视图推理、每个槽只看自己那张图的 teacher 同样会变红；一个被先验主导、输出与输入无关的 teacher 反而不变红。所以它说明的是评分流水线对错误关联敏感，不证明 DA3 利用了时序或跨视图信息。
2. **残差对 K 的依赖。** 在"内参与几何自洽"的极限下，错误的 K 只是相似规范的重参数化，z 深度不受影响，三项残差对 K 严格不变；
   只有在 teacher 内部不自洽时，平移残差才会带一个对 6 个世界共同的横向各向异性拉伸（共模）。共模只进入 fit 均值而不进入去均值后的协方差，所以 fit 均值**不能**当作纯几何误差的估计。
   r2 本来就禁止把它登记为噪声模型（秩 ≤ 2、不求逆、`sensor_noise_registration_allowed=false`、`nees=null`），因此不丢失任何已有保证。
3. **预测 K 的主点不是估计出来的。** DA3 的相机解码器把预测主点写死为 (W/2, H/2)，而真值用像素中心约定 ((W-1)/2, (H-1)/2)，两者恒差 0.5 px，是约定差而不是模型误差。
   所以描述性对比只比较 fx、fy，cx、cy 单列排除。

另有一条**已披露但未改动**的风险：`cpu_parity` / `half_parity` 是"全元素逐点"门。没有 cam_token 时 DA3 用离散 argmin 选参考视角并重排，
这个分支在 CPU/MPS 或 fp32/fp16 之间一旦翻转，输出坐标系整体改变，任何容差都救不回来；fp16 的全元素最大值门也只是勉强。容差和规则**没有**被放宽（`numerical_parity.known_risks`）。
是否要为此再修订对拍规则，是需要用户决定的事，见 `open_items`。

## 与 r1 的差异（只有这些）

用户 2026-10-27 批准选项 A（逐字见 AMENDMENT.md）。r2 相对 r1 的全部差异由 `r2/diff_r1_r2.json` 机器列出（{NPATHS} 条路径）：
`known_intrinsics: true → false`；移除内参逆向控制；每型号 11 次/31 视图 → 10 次/28 视图，合计 62 → 56；
把描述性的"预测 K 与真值 K 对比"加入原始指标；执行前提与禁止宣称相应更新；记录修订来源与未决事项。
对齐、残差定义、估计量、数值对拍的容差与规则、逆序控制的构造与判据、失败策略、输入及其 SHA **均未改动**，由 `r2/check_r2.py` 逐项断言。

## 作者证据和待独立复核

`r2/build_proposal_r2.py` 读入 r1 的 proposal.json（先核对其与 proposal.sha256 一致），只施加枚举的修改，每处断言旧值；因此未列出的字段与 r1 逐字节一致可被机器证明。
`r2/check_r2.py` 是作者自检：差异只落在枚举范围、未改动口径与 r1 相等、预算算术、并用真实 r2 文件驱动 T37 的 runner。
**复核人不得导入或照抄这些脚本作自证**，应自建独立检查；r1 的所有文件和 18 视图输入均只读。
已知缺陷：T37 的 runner 目前读不了 r2（`load_plan` 无条件解析被移除的 `negative_controls.intrinsics`），已通报 T38，最小修复已在仓外镜像验证；这属于 runner，不影响本协议文件的正确性。
"""
(HERE / "PROTOCOL.md").write_text(head + tail, encoding="utf-8")

amend = f"""# T28 r2 修订说明（作者 claude-az，2026-10-27）

状态：**proposal_unapproved / execution_permitted=false**。r2 SHA256 `{r2_sha}`。未经独立数学复核与一级 SHA 登记前不得用于任何运行。

## 用户批准（逐字）
> {p2["amendment"]["approved_by_user"]["verbatim"]}

（{p2["amendment"]["approved_by_user"]["date"]}，{p2["amendment"]["approved_by_user"]["where"]}。配额口径用户另行告知，尚未给出。）

## 为什么修订
r1 要求"已知内参 K 条件化 teacher、不给外参"，并要求"内参逆向控制必须变红（S_bad ≥ S_clean + max(0.0001, 0.1·S_clean)）"。
这版 DA3 在没有外参时**完全忽略内参**，因此预测不可能随 K 变化，S_bad = S_clean，该控制按构造不可能通过。证据（静态，没有做任何模型前向）：

| 证据 | 位置 | 文件 SHA256 |
|---|---|---|
| 内参只在给了外参时才进入前向：`{ev["da3_forward_gate"]["text"]}` | `{ev["da3_forward_gate"]["file"]}:{ev["da3_forward_gate"]["line"]}` | `{ev["da3_forward_gate"]["sha256"][:16]}…` |
| 无外参时 `_align_to_input_extrinsics_intrinsics` 直接返回预测，连输入内参都不写回 | `{ev["api_early_return"]["file"]}:{ev["api_early_return"]["line"]}` | `{ev["api_early_return"]["sha256"][:16]}…` |
| 管线 `process_keyframes` 没有内参参数 | `envs/teachers/t6/pipeline.py` | — |

漂移探测：`tests/test_da3_calibration_runner.py::test_upstream_da3_still_gates_intrinsics_behind_extrinsics`。
r1 的 runner 靠对该控制无条件写 `"verified": True` 掩盖了这一点（那个字段没有任何计算）。

## 改了什么 / 没改什么
改了（{NPATHS} 条路径，见 `diff_r1_r2.json`）：
1. `profile.known_intrinsics` true → false；新增 `profile.intrinsics_policy`（不提供 K；真值 K 仅记录；预测 K 与真值 K 的对比为描述性）。
2. 移除 `negative_controls.intrinsics`，新增 `removed_controls`（含原因）与 `real_forward_controls=[frame_order_adverse]`；`same_clean_profile` 文字更新。
3. 预算：每型号移除 `intrinsics_adverse` 阶段 → 10 次/28 视图，合计 20 次/56 视图；`unallocated_views` 随预留数重算为 8。
4. `numerical_parity.reference` 文字去掉"known-K"；`raw_metrics` 末项改为描述性。
5. `execution_prerequisites[3]` 替换（不再要求已知 K 适配器），并追加两条：`--preflight-only` 必须在中央预留**之前**通过；用户确认记账口径与具体配额数。
6. `claims_forbidden` 追加"任何声称 teacher 受真值/已知内参条件化"；新增 `amendment`、`open_items`、`supersedes`；作者/复核卡/协议 id 更新。

**没改**（由 `check_r2.py` 逐项断言与 r1 相等）：对齐与残差定义、估计量与有限样本边界、数值对拍容差/字段/规则、逆序控制的构造与判据（含 `required_red`）、
边界拒绝语义、失败策略、fit/holdout 划分与锚点/尺度/评分视图、墙钟/RSS/单模型常驻/重试限制、全部输入及其 SHA。

## 修订带来的含义变化（请复核人重点想）
- 噪声候选的 profile 从"已知 K 条件下"变为"**模型自估内参条件下**"：7 维残差里现在包含了 DA3 自估内参的误差。两类样本不能混进同一个噪声模型。
- 旋转/平移残差用锚点相对量，深度残差用锚点 `s_depth`：它们对"自估 K 与真值 K 不一致"的敏感程度需要复核人判断（我的看法：相对量能吸收一部分，但不能吸收全部，所以才加描述性的 K 对比）。
- 控制集合收窄：只剩一个真实前向控制（逆序）+ CPU 边界守卫。r2 **不**引入替代的 K 敏感控制；如需要，另立预登记（选项 A′）。
- 逆序控制本身是否在真实 DA3 上变红是**经验结果**，不是保证；按 r1 的原则，没变红本身就是失败结果，不事后换指标。

## 未决事项（open_items）
1. **配额记账口径**（用户待告知）：账本按 CLI `--views` 记，而 worker 的前向视图数是它的数倍（r2 为 56）。`budget.reserve_before_model_import_views=64` 与 `unallocated_views=8` 沿用 r1 约定，登记前必须重述。
2. 下一次真跑的具体视图/墙钟配额数（累计墙钟已预留 1170/1200 s）：用户批准待定。
3. 独立数学复核 + 一级对该 SHA 的登记。

## 在任何真跑之前还必须完成
- T37 的 runner 修复（读 r2、`PROPOSAL_PATH`/`--proposal`、证据记录 proposal 路径）并经 T38 复核；
- `da3_calibration_runner.py --preflight-only` 在接 AC、中央预留**之前**通过；
- 用户批准具体配额数字。
**本次修订不构成对任何运行的放行，也不消耗任何配额。**
"""
(HERE / "AMENDMENT.md").write_text(amend, encoding="utf-8")
print("PROTOCOL.md", len((HERE / "PROTOCOL.md").read_text().splitlines()), "lines;", "AMENDMENT.md", len(amend.splitlines()), "lines")
