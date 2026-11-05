# T28 r2 修订说明（作者 claude-az，2026-10-27）

状态：**proposal_unapproved / execution_permitted=false**。r2 SHA256 `2a984531e6a55232b6d42ab90ae6db364dfda5928acaef44b90b3747b564c0a0`。未经独立数学复核与一级 SHA 登记前不得用于任何运行。

## 用户批准（逐字）
> 按选项 A 修订 T28：known_intrinsics 改为 false（模型自估内参），去掉内参逆向控制，保留逆序控制和 CPU 边界守卫；请起草 T28 r2 并新建独立数学复核卡，配额口径我另行告知

（2026-10-27，一级 claude-az 会话。配额口径用户另行告知，尚未给出。）

## 为什么修订
r1 要求"已知内参 K 条件化 teacher、不给外参"，并要求"内参逆向控制必须变红（S_bad ≥ S_clean + max(0.0001, 0.1·S_clean)）"。
这版 DA3 在没有外参时**完全忽略内参**，因此预测不可能随 K 变化，S_bad = S_clean，该控制按构造不可能通过。证据（静态，没有做任何模型前向）：

| 证据 | 位置 | 文件 SHA256 |
|---|---|---|
| 内参只在给了外参时才进入前向：`if extrinsics is not None: cam_token = self.cam_enc(extrinsics, intrinsics, x.shape[-2:]) else: cam_token = None` | `envs/teachers/t6/Depth-Anything-3/src/depth_anything_3/model/da3.py:126` | `c7d5f88962e05c02…` |
| 无外参时 `_align_to_input_extrinsics_intrinsics` 直接返回预测，连输入内参都不写回 | `envs/teachers/t6/Depth-Anything-3/src/depth_anything_3/api.py:350` | `042ae8f6bfd1e561…` |
| 管线 `process_keyframes` 没有内参参数 | `envs/teachers/t6/pipeline.py` | — |

漂移探测：`tests/test_da3_calibration_runner.py::test_upstream_da3_still_gates_intrinsics_behind_extrinsics`。
r1 的 runner 靠对该控制无条件写 `"verified": True` 掩盖了这一点（那个字段没有任何计算）。

## 改了什么 / 没改什么
改了（32 条路径，见 `diff_r1_r2.json`）：
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
> 选 A：从 T28 r2 删除 half_parity（每型号 9 次/25 视图，合计 18 次/50 视图），你修订 r2 并做差异复核；cpu_parity 保持现状。配额口径我另行告知。

内容：删除 `half_parity` 阶段；`cpu_parity` 规则保持现状；配额口径仍待用户告知。理由、证据与影响见 PROTOCOL.md「第二次修订（E15）」与机器文件 `numerical_parity.retired_stages`。
修订前的版本（SHA `76f4c9fb…`）原样封存在 `pre-half-parity-removal-76f4c9fb/`；T39 复核过的更早版本（`0e15033a…`）在 `reviewed-0e15033a/`。

## 第三次修订（E16，2026-10-28）
- 用户决定（逐字）：> 配额口径用前向视图（诚实口径，每次记 50）。具体数字我随后告知；你先不要动账本。
- 内容：①`budget.view_accounting` 基准定为前向视图，每次完整运行记 50，数字待告知；②按 V9.T46（deepseek-q7m2，accept_with_changes）的必改项修正措辞，并改正 `retired_stages` 的 MPS 表述（标为作者报告）；③`open_items` 增加 `REGISTERED_CALIBRATION_VIEWS` 的下游后果。
- **没有照单全收的一条**：T46 建议写入「当前 torch 2.3.1 的 MPS autocast 是空操作」。我在真实教师环境 `envs/teachers/.venv-t6`（torch 2.14.1）里核对：`torch.autocast(device_type="mps")` 可以构造且 enabled；该说法只对 `.venv`（torch 2.3.1）成立，而它不是教师运行环境。已改为经核对的表述（`model/da3.py:139` 的 `enabled=False` 段）。
- 修订前的版本（SHA `86f5ece6…`，T46 复核的对象）原样封存在 `pre-E16-86f5ece6/`。
- `reviewed-0e15033a/` 只存了交付物，T39 当时复核的三个脚本版本（`build_proposal_r2.py`/`build_docs_r2.py`/`check_r2.py`）没有留存，其 `SHA256SUMS.txt` 里对应三行无法核对；这是已知的可复现性缺口，不影响 `proposal.json` 的可验证性。

## E17（2026-10-28，一级 claude）：写入用户批准的配额数字

- 用户原话：「Approve as proposed」（回复一级的提议：Approve the DA3 quota: view cap 131, wall cap 1290 s, 120 s per run? | reports/coordination/PENDING-USER-20261028.md §1: 建议：视图上限 131、墙钟上限 1290 s、单次 120 s，只跑一次，不重试）
- 只动了 `amendment`、`budget.view_accounting`、`budget.cumulative_wall_seconds_max`、`budget.wall_accounting`、`open_items`。
- 累计视图上限 131（已用 81 + 本次 50）；累计墙钟上限 1290 s（已预留 1170 + 本次 120）；只跑一次，不重试。
- 上一版 `2a984531e6a55232b6d42ab90ae6db364dfda5928acaef44b90b3747b564c0a0`（经 ainerzero.V9.T48 复核通过）封存在 `pre-E17-2a984531/`。新 SHA256 `1694ed305c1a80d14ec0bfcf4117e16b246ce82b85c51fab16394e530dda9ff5`。
- 仍为 `proposal_unapproved`、`execution_permitted=false`，等不同作者确认 E17 之后，一级才登记 SHA。
