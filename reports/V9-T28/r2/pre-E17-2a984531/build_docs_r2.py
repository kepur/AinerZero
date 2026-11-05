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
    ("两型号各以 world00 已知K的 MPS/F32 正例作为引用，比较CPU/F32和MPS/F16的depth/confidence/extrinsics/intrinsics；",
     "两型号各以 world00 的 MPS/F32 正例作为引用，比较CPU/F32的depth/confidence/extrinsics/intrinsics；"),
    ("CPU/F32的atol/rtol均0.001；MPS/F16均0.01。",
     "CPU/F32的atol/rtol均0.001。（r1 另有 MPS/F16 一致性阶段，atol/rtol 均0.01；r2 已按用户 2026-10-28 批准的选项 A 删除该阶段，原因与证据见下文「第二次修订」；其容差键在机器文件中原值保留但无任何阶段使用。）"),
    ("错K负对照将所有3帧fx×1.5、fy×0.75，主点不改。正例已使用正确K，保证比较的是同一个条件profile。每阶段输入关联及错K值预先冻结为允许的有界压力输入，不靠生产绕过开关。",
     "r1 的错K负对照已移除（见 AMENDMENT.md：这版 DA3 在没有外参时忽略内参，该对照按构造不可满足）；本方案**不**引入替代对照。输入关联预先冻结为允许的有界压力输入，不靠生产绕过开关。"),
    ("不能保证模型必然对错K更差，发现没有更差本身就是失败结果", "不能保证模型必然对帧序错乱更差，发现没有更差本身就是失败结果"),
    ("| MPS/F32错K负对照 | 1 | 3 | 3 |\n", ""),
    ("| MPS/F16一致性 | 1 | 3 | 3 |\n", ""),
    ("| 每型号合计 | 11 | — | 31 |", "| 每型号合计 | 9 | — | 25 |"),
    ("| 两型号合计 | 22 | — | 62 |", "| 两型号合计 | 18 | — | 50 |"),
    ("MPS/F32四阶段连续完成后卸载，再CPU/F32卸载，再MPS/F16卸载；每型号3次加载，两型号6次，全部计入1200s。",
     "MPS/F32三阶段连续完成后卸载，再CPU/F32卸载；每型号2次加载，两型号4次，全部计入1200s。"),
    ("剩余2视图不用于自动补跑", "剩余视图（预留数 − 计划 50）不用于自动补跑；预留数的记账口径见 open_items，尚待用户决定"),
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

另有一条**已披露但未改动**的风险：`cpu_parity` 是"全元素逐点"门。没有 cam_token 时 DA3 用离散 argmin 选参考视角并重排，
这个分支在 CPU 与 MPS 之间一旦翻转，输出坐标系整体改变，任何容差都救不回来。容差和规则**没有**被放宽（`numerical_parity.known_risks`）。
用户 2026-10-28 已决定**保持现状**：`cpu_parity` 变红就如实报告（退出码 5，标定证据与全部预测都保留）；r1 原文也说它不是几何能力门槛。

## 2026-10-28 第二次修订（E15）：删除 half_parity

用户 2026-10-28 选择选项 A（逐字见 AMENDMENT.md）。原因是该阶段在这版管线上**按构造无法完成**，不是结果不理想：
`pipeline.py` 的 `ExplicitPrecisionDA3` 关掉 autocast 并把整网转成 float16，而上游 `CameraDec.forward` 写死 `self.fc_t(feat.float())`；
fp32 输入喂给 fp16 的 Linear，CPU 抛 `mat1 and mat2 must have the same dtype, but got Float and Half`——这一条由 V9.T46（`.venv`，torch 2.3.1）和作者（`envs/teachers/.venv-t6`，torch 2.14.1，真实教师环境）各自独立复现，纯 CPU、不加载 DA3 权重。
MPS 上作者报告为 Metal 断言直接中止进程（SIGABRT，退出码 134）；**没有留存崩溃现场，这一条是报告，不是被独立复现的事实，删除决定不依赖它。**
它是 DA3-SMALL 的最后一个阶段，会崩在 DA3-BASE 开始之前；授权已按预留扣掉，不退还（证据行号与文件 SHA 见机器文件 `numerical_parity.retired_stages`；复现不涉及 DA3 权重，见 `reports/V9-T40/DECISIONS_FOR_USER.md`）。
这不是"结果出来后为通过而改动"：它在任何**产出标定结果**的运行之前提出（V9.T35 那次唯一授权的真跑因 runner 缺陷失败，没有产出任何标定结果；本次依据是不加载权重的 dtype 复现和对源码的静读），且删的是一个不可能产出结果的阶段，而不是一个会变红的判据。
改动的全部内容：每型号 10 次/28 视图 → 9 次/25 视图，合计 20 次/56 视图 → 18 次/50 视图；每型号加载 3 次 → 2 次，合计 6 → 4；`numerical_parity.known_risks` 去掉 fp16 一条；
新增 `numerical_parity.retired_stages`。**没有**引入替代的 fp16 控制，`pipeline.py` 未动（选项 B 未被选，所以其 SHA 绑定仍有效），`mps_float16` 容差键原值保留但不再被使用。
丢掉的东西要如实说：本方案不再给出 fp16 一致性这一项。若以后要它：`torch.autocast(device_type="mps")` 在 `envs/teachers/.venv-t6`（torch 2.14.1）里可以构造，
但 `model/da3.py:139` 把 depth head 与相机估计包在 `autocast(enabled=False)` 里，外层 autocast 够不到这些部分，得到的会是「部分 fp16」的门，需要另立预登记并写明它覆盖什么。

## 2026-10-28 第三次决定（E16）：记账口径＝前向视图

用户 2026-10-28：「配额口径用前向视图（诚实口径，每次记 50）。具体数字我随后告知；你先不要动账本。」机器文件 `budget.view_accounting` 因此由 OPEN 改为 `BASIS_DECIDED_NUMBERS_PENDING`（基准＝前向视图，一次完整运行记 50）。
**具体的累计上限数字用户尚未告知，本文件不构成任何配额批准，账本不得触碰。** 一个下游后果：`da3_worker.REGISTERED_CALIBRATION_VIEWS`（现为 18，worker 与受控 CLI 共用）要随之变为登记的记账值 50，最好从被哈希绑定的 proposal 派生，否则 worker 会拒绝按 50 记账的真跑；这是登记最终 SHA 之后的另一张卡。

## 与 r1 的差异（只有这些）

用户 2026-10-27 批准选项 A（逐字见 AMENDMENT.md）。r2 相对 r1 的全部差异由 `r2/diff_r1_r2.json` 机器列出（{NPATHS} 条路径）：
`known_intrinsics: true → false`；移除内参逆向控制；移除 half_parity 阶段（E15）；每型号 11 次/31 视图 → 9 次/25 视图，合计 62 → 50；
把描述性的"预测 K 与真值 K 对比"加入原始指标；执行前提与禁止宣称相应更新；记录修订来源与未决事项。
对齐、残差定义、估计量、数值对拍的容差与规则、逆序控制的构造与判据、失败策略、输入及其 SHA **均未改动**，由 `r2/check_r2.py` 逐项断言。

## 作者证据和待独立复核

`r2/build_proposal_r2.py` 读入 r1 的 proposal.json（先核对其与 proposal.sha256 一致），只施加枚举的修改，每处断言旧值；因此未列出的字段与 r1 逐字节一致可被机器证明。
`r2/check_r2.py` 是作者自检：差异只落在枚举范围、未改动口径与 r1 相等、预算算术、并用真实 r2 文件驱动 T37 的 runner。
**复核人不得导入或照抄这些脚本作自证**，应自建独立检查；r1 的所有文件和 18 视图输入均只读。
runner 状态：T37 的 runner 曾读不了 r2（`load_plan` 无条件解析被移除的 `negative_controls.intrinsics`），已由 ainerzero.V9.T40 修复并经 T41 非作者复核；现在 `da3_calibration_runner.py --proposal <本文件旁的 proposal.json>` 可读 r2，默认路径仍是 r1，登记后才切换。
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
3. 预算：每型号移除 `intrinsics_adverse` 阶段（E15 再移除 `half_parity`，见下）→ 9 次/25 视图，合计 18 次/50 视图；`unallocated_views` 随预留数重算为 14。
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
1. **配额记账口径**（用户待告知）：**用户已决定（2026-10-28）：按前向视图记，一次完整运行记 50。** 具体累计上限数字待用户告知；`budget.reserve_before_model_import_views=64` 与 `unallocated_views=14` 沿用 r1 的单次作业约定，登记前须按用户给的数字重述。
2. 下一次真跑的具体视图/墙钟配额数（累计墙钟已预留 1170/1200 s）：用户批准待定。
3. 不同作者对 E16 与最终数字的确认（小卡）+ 一级对最终 SHA 的登记。T39 复核的是 E15 之前的版本；V9.T46 复核了 E15（accept_with_changes，已在 E16 应用，见机器文件 `amendment.review_history`）。

## 在任何真跑之前还必须完成
- runner 读 r2 的修复已由 T40 完成并经 T41 复核；T42 的后续（consume 前拒绝非标定视图等）待完成；登记后把默认 `PROPOSAL_PATH` 切到 r2；
- `da3_calibration_runner.py --preflight-only` 在接 AC、中央预留**之前**通过；
- 用户批准具体配额数字。
**本次修订不构成对任何运行的放行，也不消耗任何配额。**

## 第二次修订（E15，2026-10-28）
用户批准（逐字）：
> {p2["amendment"]["approved_by_user_second"]["verbatim"]}

内容：删除 `half_parity` 阶段；`cpu_parity` 规则保持现状；配额口径仍待用户告知。理由、证据与影响见 PROTOCOL.md「第二次修订（E15）」与机器文件 `numerical_parity.retired_stages`。
修订前的版本（SHA `76f4c9fb…`）原样封存在 `pre-half-parity-removal-76f4c9fb/`；T39 复核过的更早版本（`0e15033a…`）在 `reviewed-0e15033a/`。

## 第三次修订（E16，2026-10-28）
- 用户决定（逐字）：> {p2["amendment"]["approved_by_user_third"]["verbatim"]}
- 内容：①`budget.view_accounting` 基准定为前向视图，每次完整运行记 50，数字待告知；②按 V9.T46（deepseek-q7m2，accept_with_changes）的必改项修正措辞，并改正 `retired_stages` 的 MPS 表述（标为作者报告）；③`open_items` 增加 `REGISTERED_CALIBRATION_VIEWS` 的下游后果。
- **没有照单全收的一条**：T46 建议写入「当前 torch 2.3.1 的 MPS autocast 是空操作」。我在真实教师环境 `envs/teachers/.venv-t6`（torch 2.14.1）里核对：`torch.autocast(device_type="mps")` 可以构造且 enabled；该说法只对 `.venv`（torch 2.3.1）成立，而它不是教师运行环境。已改为经核对的表述（`model/da3.py:139` 的 `enabled=False` 段）。
- 修订前的版本（SHA `86f5ece6…`，T46 复核的对象）原样封存在 `pre-E16-86f5ece6/`。
- `reviewed-0e15033a/` 只存了交付物，T39 当时复核的三个脚本版本（`build_proposal_r2.py`/`build_docs_r2.py`/`check_r2.py`）没有留存，其 `SHA256SUMS.txt` 里对应三行无法核对；这是已知的可复现性缺口，不影响 `proposal.json` 的可验证性。
"""
(HERE / "AMENDMENT.md").write_text(amend, encoding="utf-8")
print("PROTOCOL.md", len((HERE / "PROTOCOL.md").read_text().splitlines()), "lines;", "AMENDMENT.md", len(amend.splitlines()), "lines")
