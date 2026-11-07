**S2 W6b：清除 probe_eval 的三处回退（P174 复核的后续项）。** 只改 `src/ainerzero/v9/experiments/s2/probe_eval.py`、`spec.py`（只在末尾追加）、`tests/v9/experiments/test_s2_probe_eval.py`，交回目录为 `reports/V9-S2-W6b/`。纯 CPU，不导入 MLX。

## 要做（依据 `reports/V9-S2-W6/review/REVIEW.md` 中的「后续 W6b 必改」）
1. **`fit_probe` 的留出集：** 改为调用 `train_runner.get_holdout_world_indices(train_root)`（带篡改检查），文件缺失即报错。同时传入的 `holdout_worlds` 必须与文件一致，否则报错。
2. **回合文件：** 只认 `world_XXXX/episode_*.json`，删除所有平铺的 `*.json` 回退分支；`probe_errors` 把平铺文件统一记为世界 0 的分支一并删除。
3. **判门步数：** 在 spec 末尾追加 `PROBE_GATE_STEP = 30`；`prediction_noninferiority` 的 k 默认值改为取这个常量。

## 测试与坏对照
- **测试：** 留出文件缺失时报错；传入的留出集与文件不一致时报错；没有世界目录时报错。
- **坏对照**（隔离副本：复制 src、tests、pyproject.toml，断言 import 解析到副本；每处按字节还原并核对 SHA）：分别恢复上面三处回退，必须变红。

## 禁止
- 不碰 eval_runner.py、commands.py（归 W3 r2），也不碰 prereg.py（归 W7）。
- 不提交，不推送。
- pytest 前台跑，用 SIG_DFL+execv 还原信号。

## 交回
REPORT.md、diff、变异表，以及跳过 W3 端到端测试文件后的全量计数。
