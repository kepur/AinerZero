# ainerzero.V9.T54 报告：T28 r2 DA3 标定唯一一次真跑

- **执行者**：一级 `claude`（relay.P2.E46）。**需要非作者复核**：`ainerzero.V9.T55`（gemini）。
- **依据**：
  - 用户「Whole line, 249/1440」，按全线合计记账；
  - T28 r2 E18（`31eef666…`），登记文件 `reports/V9-T28/REGISTERED.json`（`bf5ea73d…`）；
  - 复核：T48、T50、T53；代码：T51、T52。
- **只跑一次，不重试，失败不补额度。**

## 1. 结论（≤10 行）

1. **运行**：
   - 经 relay exec 监督与中央入口 `teacher-da3 --mode run --allow-model-execution --coordinator-release`，持 `m0-worker.lock`；
   - 时间 01:15:54–01:16:08，进程组墙钟 13.4 s，runner 自报 11.34 s；
   - 运行时开盖、接电，在 `caffeinate -i` 下。
2. **记账精确**：两型号各 9 次调用、25 个前向视图，计划与实际一致，合计 50。
   - 账本新增 run `a7bcc4c9…`：task 为 `ainerzero.V9.T6`，views 50，active 120 s，状态 failed。
   - 全线累计 249 视 / 1440 s，正好用完批准的额度。
3. **协议结果：failed**（runner 退出码 5，证据全部保留）。唯一的失败项：
   - DA3-SMALL 的 `frame_order_adverse` 没有变红：S_clean 0.6387，S_bad 0.6534，要求增幅 ≥ 0.0639；
   - 也就是说，SMALL 在干净条件下的分数本身就差，交换视图的关联几乎没有影响。
4. **DA3-BASE 全部阶段通过**：逆序控制明显变红（0.156 → 1.118）。
5. **cpu_parity 两型号都通过**：最大逐元素差，depth 约 6e-6，intrinsics 约 2.7e-4，都在 atol/rtol 1e-3 之内。这与 T46 的「大概率判红」预测相反。
6. **边界守卫 3 项都按预期拒绝**：零深度、非 SO(3) 旋转、零基线。
7. **范围**：标定统计（fit 3 个世界、holdout 3 个世界）只作描述。输出状态是 `limited_aligned_diagnostic_candidate_unregistered`，不登记噪声模型，不宣称能力，不进训练（protocol `claims_forbidden`）。

## 2. 证据

- **运行**：`run.stdout.json`（CLI 输出）、`run.stderr.log`（relay exec 监督证据：进程组确认已清空）、`run.rc`、`pre_run_state.txt`；
- **标定**：`calibration_evidence.json`（各阶段、记账、数值一致性、负对照、失败项）、`predictions/`；
- **账本**：运行后的生产账本 SHA 记在 `runs-db-after-run.sha256`；运行前 `1b60150f…`（写入覆盖之后）。
- **运行前置**：在 `reports/V9-T28/registration/`，含
  - 登记文件 SHA；
  - 预检记录（四项全部 ok）；
  - 账本覆盖前的一致性备份与 SHA，以及覆盖值；
  - 真实账本上 inspect 的结果（can_run=true，199+50≤249，1320+120≤1440）。

## 3. 注记

- `relay exec` 的退出码是 1：CLI 把 runner 的退出码 5 包装为 `refused`。台账里这个 run 的状态是 failed，原因写的是 runner 退出码 5。
- 运行用 `T6_PROPOSAL_PATH` 显式指向 r2，runner 的默认值仍是 r1（测试固定了这个默认值）。后续应让 runner 拒绝与登记 SHA 不一致的提案，作为小后续卡。
- 下一次真跑需要用户另批额度：全线额度已经用尽。
