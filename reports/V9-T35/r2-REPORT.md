# ainerzero.V9.T35 r2 执行报告：唯一一次 18 视图真跑——**失败（代码缺陷），授权已耗尽**

角色：claude-az（一级托管，用户 2026-10-27 指示亲自执行）。r1（antigravity-u2a7）的证据原样保留未改。

## 结论（先说）
- 做了：开跑前备份、零副作用 inspect、一次持锁真跑（中央入口，`--coordinator-release`）。
- **结果：失败。** 模型前向实际执行（0.59 s），随后 `ValueError: paired depth shapes must agree` 崩在后处理，**没有产出任何统计，仅留下 1/6 世界的 da3_small 预测**。
- **18 视图与 60 秒预留已被消耗**（累计 81/82 视图，1170/1200 s），不能重试。
- 不宣称能力通过；不登记噪声模型；`candidate_unregistered` 的结论都谈不上——没有候选。

## 前置（全部实测）
AC 供电（`pmset`）、`ps`/`killpg` 通过、一级会话属 auto-deep、inspect `can_run=true`、内存余量 82%、swap 111 MB。
开跑前备份 `reports/V9-T35/runs-db-before-run-r2.sqlite3` SHA256 `f84337f59a14ac163b30e5fe5b404fa15f8d798c5dcb50d79e82e8b445ff3a1f`。

## 失败根因
- 真值深度 **210×280**（`depth_camera_z.npy`），DA3 输出 **378×504**（`process_res=504`）。
- `da3_calibration_runner.py:240` 与 `:392` 两处 `compute_depth_metrics(res["depth"][1], gt_depths[1])` 直接传入未缩放的预测深度，而 `compute_depth_metrics` 要求严格同形。
- 同文件 `compute_t28_7d_residual`（行 100–108）已有“预测 resize 到真值尺寸”的逻辑，**但没复用到这两处调用**。
- **全仓库没有任何测试引用 `da3_calibration_runner` / `run_full_calibration`**——这唯一一次授权真跑是该路径第一次被执行。T26/T27/T30/T31 验收的是监督与账本，没有覆盖标定 runner 本身。

## 预测原件：部分保留（更正）
持锁 worker 子进程写出了 **da3_small 第 1 个世界 `t6-analytic-room-00` 的 3 个视图**（`predictions/da3_small/t6-analytic-room-00/`：view_0/1/2.safetensors、prediction.safetensors、candidate.json，SHA 见 `r2-metrics.json`），随后在该世界的 `compute_depth_metrics` 崩溃。其余 5 个世界与整个 da3_base 均未处理。
**1/6 世界不足以做 fit3/holdout3 的统计，因此仍然没有任何标定结论。**
（我最初在草稿里写“无预测原件”是错的：用 `find -newer` 检查时，start 文件已被我追加改写，时间戳反超预测文件，导致漏检。已更正。）
同时 `da3_controlled.py:624` 的 worker 工作目录是 `TemporaryDirectory`，CLI 退出即删——这次能留下文件，是因为 runner 把预测直接写进了 `reports/V9-T35/predictions`。

## 台账（run `407dae53dfe943c19f48e60b02830b21`）
state=failed，exit_code=1，worker pid/pgid 12140，`empty_group_proven=true`，elapsed 7.11 s，peak RSS 0.91 GB，无违规。
前后对比：视图 63→81（上限 82），预留 1110→1170 s（上限 1200，仅剩 30 s）。

## 再跑需要什么（均需用户新批准，我不自行扩）
- 累计视图上限 ≥ 99（81+18）；累计墙钟上限 ≥ 1230 s（1170+60）。
- 先修缺陷并加覆盖该路径的 CPU 测试（见建议卡），**否则只是再烧一次授权**。

## 更正此前的说法
- r1 metrics 的 `single_true_forward_attempted=true` 不准确（r1 在门口被拒，未进入前向）。
- 一级通知 #687/#688 只谈日预算，漏了累计墙钟上限；本次 60 s 预算恰好装得下，未造成后果。

## 产物与 SHA
见 `r2-metrics.json` 的 `artifacts`。
