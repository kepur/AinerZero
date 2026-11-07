# W1 r2（P163）：数据与训练接线（附录 D1/D2，打回项 F1–F8）

- **作者：** r1 为 gemini-k4m9；r2 的大部分由 gemini-8f4b 完成（停滞前，最后一次落盘 02:40）；剩余部分由一级 claude 收尾（11-07 05:xx，用户授权一级做二级活）。
- **复核：** P165 须由三位作者以外的 gemini 承担，排除 k4m9、8f4b、claude。

## F1–F8 落点
| 项 | 落点 | 用例（`test_s2_w1_wiring.py`） |
|---|---|---|
| F1 smoke 步数 | `commands._resolve_smoke_train_steps`：经 `ledger_read_snapshot` 读取；只看最近一次 smoke；须为 completed 且 metrics 中 `passed` 为 True；步数取自 metrics | `test_train_refused_without_smoke_record`、`..._latest_smoke_failed`、`test_completed_smoke_with_passed_false_is_not_usable`、`test_steps_come_from_passed_smoke_metrics_without_touching_live_ledger`、`test_smoke_without_steps...` |
| F2 smoke 包装 | runner 只返回结果；`worker.execute_work_cell` 遇 passed=False 时记 failed 并写入 metrics；不再改写 config_json | `test_failed_smoke_result_is_recorded_failed_not_completed` |
| F3 arm/seed | 必须显式给出；arm 限 A/B/C，seed 取自 `spec.TRAINING_SEEDS`；**一级补了规范化**（`canonical_arm`），与检查点路径、加载方一致 | `test_train_requires_registered_arm_and_seed`（5 种）、`test_train_arm_is_canonicalized_before_execution` |
| F4 partition | 只认 `--partition`；带 `--arm` 时拒绝；**一级删除了种子命名空间的三层回退** | `test_generate_data_requires_partition`、`..._refuses_arm`、`test_seed_namespaces_come_from_spec_only` |
| F5 留出集 | `HOLDOUT_WORLDS.json` 必须存在；按规则重算后比对，不一致即判为篡改；为空或目录名无法解析都报错 | `test_holdout_file_is_mandatory_and_tamper_checked`、`test_holdout_refuses_empty_list_and_bad_world_dirs` |
| F6 步数覆盖 | args 中带 steps 即拒绝 | `test_train_refuses_steps_override` |
| F7 代码身份 | 删除 `--repo-root`/`--lock`；repo_root 由包文件位置推出，并断言其中正是正在执行的 commands.py | `test_repo_root_must_contain_the_executing_code`、`test_default_repo_root_is_the_package_checkout_not_cwd`、`test_cli_has_no_repo_root_or_lock_alias` |
| D2 训练接线 | 数据目录为 `datasets/train`；间隔取 `MODEL_SELECTION_EVERY_STEPS`=200 | `test_production_train_runner_reads_registered_data_dir_and_smoke_steps`、`test_model_selection_cadence_is_registered` |

## 验证
- `test_s2_w1_wiring.py`：23 条通过。默认全量 3683 passed, 6 deselected；实盘 artifacts 前后 lstat 比对（含 ctime）差异为 0。
- 隔离副本坏对照（`w1mut.py` + `w1muts.py`）：6/6 变红，分别是失败的 smoke 被当成可用、去掉篡改检查、间隔改为 5、数据目录改为 `data`、去掉规范化、改回 cwd。其中 M1 和 M4 第一轮存活，一级补用例后变红。

## 范围
本卡在 `worker.py` 增加了 `record_metrics` 和 `get_run_metrics`，W2 的 `ledger_checkpoint_sha` 依赖这两个接口。cli 只新增了 `--partition`。
