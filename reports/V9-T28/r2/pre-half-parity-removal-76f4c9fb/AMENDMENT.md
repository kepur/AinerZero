# T28 r2 修订说明（作者 claude-az，2026-10-27）

状态：**proposal_unapproved / execution_permitted=false**。r2 SHA256 `76f4c9fbbf8b0889736904c8408dec11f62c2b9c7a3d60a2210c969ef2a922b4`。未经独立数学复核与一级 SHA 登记前不得用于任何运行。

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
改了（31 条路径，见 `diff_r1_r2.json`）：
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
