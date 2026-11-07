# W6b（P177）非作者复核：composer-m8k4（P178，2026-11-07）

- **作者：** claude（一级实现）
- **复核者：** composer-m8k4（非作者；非 excluded `claude`；本会话未做过 P177）
- **结论：RECOMMEND_ACCEPT**

## 核对摘要
卡面三处回退（留出集权威、禁止平铺、`PROBE_GATE_STEP`）在范围内已落地；隔离变异 4/4 变红并 SHA 还原；`test_s2_probe_eval.py` 10/10；实盘 artifacts lstat 差异 0。工作树另有 W3/W7 脏文件，不归因于 P177。

## 1. 范围
- 交回补丁 `reports/V9-S2-W6b/git_diff.patch` 仅含：
  - `src/ainerzero/v9/experiments/s2/probe_eval.py`
  - `src/ainerzero/v9/experiments/s2/spec.py`（末尾追加 `PROBE_GATE_STEP = 30`）
  - `tests/v9/experiments/test_s2_probe_eval.py`
- 与当前工作树对上述三文件的 `git diff` 逐字一致（288 行）。
- 工作树其他已改文件（`eval_runner.py` / `commands.py` / `adapters_mlx.py` / `worker.py` / `prereg.py` / `train_runner.py` / 相关测试 / `conftest.py`）及未跟踪 `test_s2_production_e2e*.py`：来自并行 W3 / W7（见 `reports/V9-S2-W3/`、`reports/V9-S2-W7/`），**不在 W6b 卡面范围**；本复核未改任何仓库源码。

## 2. 回退清零（改动模块内 grep）
| 命中 | 判断 |
|---|---|
| `getattr(model, "dev_Z"/"dev_XY", None)`、`getattr(..., "encode"/"predict_l1", None)` | 失败闭合探测：存在测试钩子或缺少可调用方法即 raise，不是缺数据静默填值 |
| `st.get("dt", 1)`（fit / probe_errors 三处） | 缺 `dt` 时默认 1；属既有时间步约定，不是本次三处回退目标；未新引入 `or []` / `or {}` / `base_success_rate` / `preferred_` / `eval_episode` / 字面 `0.5` |
| 留出集 | `get_holdout_world_indices(root)` 强制读文件+篡改检查；传入 `holdout_worlds` 与文件不一致 `ValueError`；文件缺失 `FileNotFoundError` |
| 目录 | `_episode_files_by_world` 只认 `world_NNNN/episode_*.json`；无世界目录 / 目录无 episode 一律 `FileNotFoundError`；平铺与「记为世界 0」分支已删除（源码无 `root.glob('*.json')`） |
| k | `prediction_noninferiority(..., k: int = spec.PROBE_GATE_STEP)`；spec 末尾 `PROBE_GATE_STEP: int = 30` |

## 3. 生产调用点（只读）
`src/ainerzero/cli.py`（`s2-phase1`）→ `commands.s2_phase1_command` → `dev-eval` / `final-eval` runner：
- 缺检查点时 `adapters_mlx.load_trained_model(...)` 失败会 `RuntimeError`（`dev-eval missing checkpoint` / `final-eval missing checkpoint`），不是只靠测试注入模型。
- `eval_runner.run_dev_eval` / `run_final_eval` 在存在 `train_root` 时调用 `probe_eval.fit_probe` / `probe_errors`；`fit_probe` 侧已走留出权威，缺文件不会静默用全世界。
- **残余（不在本卡可改范围，不阻塞 W6b 验收）：** `eval_runner` 仍写死 `prediction_noninferiority(..., k=30)`（与当前常量相等）；读 `HOLDOUT_WORLDS.json` 处仍有 `except: pass` 后再把 `h_worlds` 传入——但 `fit_probe` 自身会再强制 `get_holdout_world_indices`，缺/坏文件不会回到「全世界静默拟合」。归 W3 后续清理更合适。

## 4. 亲手变异（隔离副本）
副本：`/tmp/w6b-review-V2fjtV/w6biso-rev-*`（复制 `src`/`tests`/`pyproject.toml`）；`import` 解析到副本：`.../src/ainerzero/v9/experiments/s2/probe_eval.py`。基线 `10 passed`；每处变红后按字节还原，SHA=`59a63cfcdeee0abcb8f43a47f1b31e857eef25c8ff2358b8acad0fa3de7a351f` 一致。证据：`review/mutation_results.json`。

| ID | 变异 | 结果 |
|---|---|---|
| W6b-M1 | 留出集改为 `holdout_idx = set()` | RED（2 failed, 8 passed） |
| W6b-M2 | 无世界目录时恢复平铺 `*.json`→世界 0 | RED（1 failed, 9 passed） |
| W6b-M3 | `k: int = 1` 字面量 | RED（1 failed, 9 passed） |
| W6b-M4（自选） | 删掉传入留出集与文件不一致的 `ValueError` | RED（1 failed, 9 passed） |

击杀率 **4/4**。还原后再次 `10 passed`。

## 5. 全量与实盘
- 前台默认全量（`SIG_DFL`+`execv`，`-p no:cacheprovider`）：**3713 passed，6 failed，7 deselected**（约 547 s）。日志：`review/pytest_full_tail.txt`。
- 失败均不在 W6b 三文件：`test_s2_production_e2e.py`×3（未跟踪，W3）、`test_s2_wiring.py::test_commands_dispatch_to_runners`（W3）、`test_canonical/test_geometry` 的 cpu_only import×2（单独复跑通过，疑为全量中并行脏文件污染）。
- 定向：`tests/v9/experiments/test_s2_probe_eval.py` → **10 passed**。
- artifacts 前后 lstat（mtime/ctime/size/ino）：**差异 0**（`artifacts_stat_before/after/diff.json`，84250 条目）。未写 artifacts、未跑 MLX、未跑生产 s2-phase1。

## 6. 逐字抽查（REPORT.md ↔ 盘）
1. 「`fit_probe` 改为调用 `train_runner.get_holdout_world_indices`」→ `probe_eval.py:111`：`holdout_idx = {int(w) for w in get_holdout_world_indices(root)}`。
2. 「只认 `world_NNNN/episode_*.json`」→ `probe_eval.py:71`：`eps = sorted(w_dir.glob("episode_*.json"))`；无平铺 glob。
3. 「`prediction_noninferiority` 的 k 默认值改为 `spec.PROBE_GATE_STEP`」→ `spec.py:307` `PROBE_GATE_STEP: int = 30`；`probe_eval.py:340` `k: int = spec.PROBE_GATE_STEP,`。

## 结论
**RECOMMEND_ACCEPT。** 无 W6b 范围内必改项。残余 `eval_runner` 写死 `k=30` / 读 holdout 的软 except 记给 W3 并行清理，不构成对本卡 REJECT。
