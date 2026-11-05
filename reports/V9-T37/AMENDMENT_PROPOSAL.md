# T28 预登记的一处不可满足项：申请修订（需用户批准）

提出：一级 claude-az，2026-10-27。依据：V9.T37 对 `da3_calibration_runner.py` 的逐条核对。
**本文只是申请。冻结口径（协议、门槛、对照）的修改属于需要用户逐项批准的范围；我没有改动 T28，也不会在批准前改。**

## 一句话
T28 要求"已知内参 K 条件化 teacher（不给外参）"，并要求"内参逆向控制必须变红"。但这版 DA3 在**没有外参时完全忽略内参**，
所以预测不可能随 K 变化，这个控制**按构造就不可能通过**。这是协议自身的问题，不是 runner 的问题。

## 证据（静态，可复核，没有为此做任何模型前向）
1. `envs/teachers/t6/Depth-Anything-3/src/depth_anything_3/model/da3.py` 第 126 行：
   ```python
   if extrinsics is not None:
       cam_token = self.cam_enc(extrinsics, intrinsics, x.shape[-2:])
   else:
       cam_token = None
   ```
   内参只被 `cam_enc(extrinsics, intrinsics, …)`（以及 `infer_gs` 的高斯头）使用；没有外参，`cam_token=None`，内参整个不参与前向。
2. `api.py` 的 `_align_to_input_extrinsics_intrinsics` 在 `extrinsics is None` 时直接 `return prediction`，连"把输入内参写回预测"都不做。
3. T28 `profile.extrinsics_supplied_to_teacher: false`、`profile.known_intrinsics: true`、`negative_controls.intrinsics`
   （焦距 x×1.5、y×0.75，要求 `S_bad ≥ S_clean + max(0.0001, 0.1·S_clean)`）。
   K 不影响输出 ⇒ `S_bad == S_clean` ⇒ 差额为 0，永远小于要求的最小差额 0.0001。
4. 管线 `pipeline.py` 的 `process_keyframes` 根本没有内参参数（T28 执行前提 [3] 要求的"已知 K 适配器"不存在）。
5. 漂移探测：`tests/test_da3_calibration_runner.py::test_upstream_da3_still_gates_intrinsics_behind_extrinsics`，上游改了这个门就会失败。

## 后果
- r1 runner 靠对这个控制无条件写 `"verified": True` 掩盖了不可满足性（该字段没有任何计算）。
- 如果不修订协议，任何忠实实现 T28 的真跑都会在内参控制上失败并退出非零：**再烧一次授权，得到的只是确认协议不成立**。
- 因此 T37 的 runner 在**加载任何模型之前**做可满足性预检，当前对真实 DA3 直接拒绝（退出码 6，零前向、零账本）。

## 选项
| | 内容 | 代价 / 风险 |
|---|---|---|
| **A（建议）** | 修订 T28：`known_intrinsics → false`（模型自估内参，真值 K 仅记录；预测 K 与真值 K 的偏差作为**描述性**附加量报告）；**去掉**内参逆向控制，保留逆序控制 + CPU 边界守卫；每模型 10 次前向/28 视图，合计 56。 | 要新 T28 r2 + 独立数学复核（T29 同类）+ 一级登记新 SHA。结论口径更窄：不再声称"已知 K"。 |
| B | 同时给 teacher 喂真值外参和内参（DA3 唯一能用 K 的方式）。 | 把真值位姿喂进去，位姿标定就失去意义；与 `extrinsics_supplied_to_teacher:false` 直接矛盾。不建议。 |
| C | 维持 T28 不变。 | 真跑必然失败，纯浪费授权。 |
| A′ | 在 A 的基础上，再补一个 K 真正有影响的控制（例如对输入图像做固定中心裁剪，使"有效内参"变化，要求得分变红）。 | 需要重新预登记该控制的构造和阈值，并复核；工作量更大。可作为后续另立。 |

A 修订后的 runner 不需要再改：`tests/test_da3_calibration_runner.py::test_runner_is_ready_for_an_amended_protocol_without_known_k`
用与真实 DA3 相同的能力位把修订版整条跑通（前向账目 10 次/28 视图）。

## 同时需要你知道的另一件事：配额按什么记
- 账本记的是 CLI 的 `--views` 参数（T35 传的 18），**不是 worker 实际做的前向视图数**。
- T28 原计划每模型 31 个前向视图、合计 **62**（先预留 64）；按选项 A 修订后合计 **56**。
- 这和 T33 时 Codex 提过的问题是同一类（#650：`--views 10` 实际处理 18）。
- 你 10-27 批准的是"视图上限 64→82，只用于一次冻结的 18 视图完整标定"。这里的"18"指**数据集视图数**（6 世界×3 视图），
  但真实前向视图数是它的 3 倍多。请你明确：**以后按数据集视图数记账，还是按前向视图数记账。**
  - 按数据集视图数（现状）：新一次真跑再要 18，累计上限 ≥ 99（现已用 81）。
  - 按前向视图数（诚实口径）：累计上限 ≥ 81 + 56 = 137。
- 累计墙钟上限 1200 s 已预留 1170 s（T35 失败那次预留了 60 s，虽然实际只跑了 7 s），新一次真跑至少需要上限 ≥ 1230 s。

## 我建议的顺序
1. 你决定选项 A / A′ / 其它，并明确配额口径；
2. 我起草 T28 r2，**新建**独立数学复核卡（作者与复核人不同），一级登记新 SHA；
3. T38 复核 T37 的 runner；
4. 跑 `da3_calibration_runner.py --preflight-only`（零模型、零账本）确认协议在真实 DA3 上可满足；
5. 到这一步我再来向你申请具体配额数字，之后才有第二次真跑。
