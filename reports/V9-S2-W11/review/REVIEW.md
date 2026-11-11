# P190 非作者复核 · S2 集成 W11（P189）

- **结论：`RECOMMEND_ACCEPT`**
- **复核者：** `gemini-k8d4`（二级执行层；非 P189 作者；P189 作者为一级 `claude`）
- **被复核任务：** `ainerzero.V9.P189`（reported）
- **复核日期：** 2026-11-08
- **任务目标：** 非作者只读审查 S2 集成 W11（世界重抽上限改为 30，生成器读取 spec 单一来源，补齐登记困难世界单测）。验证用户批准与只追加规则；在内存中亲手全量复跑 train (0–199) 与 dev (0–49) 种子生成；在隔离副本中亲手复做 M1–M5 及自选 M6 坏对照；前台运行全量回归并核对实盘 artifacts 零改动。

---

## 1. 范围（Scope）

- **W11 声明修改文件**（共 3 个模块）：
  - `src/ainerzero/v9/experiments/s2/spec.py`
  - `src/ainerzero/v9/experiments/s2/world.py`
  - `tests/v9/experiments/test_s2_world_redraw.py`（新增）
- **SHA256 逐一校验**：
  实盘盘上 3 个文件与 `reports/V9-S2-W11/sha256.txt` 逐字 100% 完全匹配：
  - `src/ainerzero/v9/experiments/s2/spec.py`: `629b2d0412e0a0d582bb2a233ea146d7eaac9cf89c972ef3437d455ffaa31df8`
  - `src/ainerzero/v9/experiments/s2/world.py`: `143e807e69d329e17b1929c9cc2383d80d3f43ca98f88084db9732bf18a7de78`
  - `tests/v9/experiments/test_s2_world_redraw.py`: `e39f5d61fecf5b5ef30f979cff8ff8ac6e0b48feab584a282631ff8956ac1dc3`
- **补丁核对**：
  `git diff 2227d58~1 2227d58 -- src/ tests/` 与作者报告提交的补丁 `reports/V9-S2-W11/git_diff.patch` 逐文件比对，差异严格为 0。
- **工作树其他文件说明**：
  工作树中未跟踪文件均为历史任务输出及上一轮验收归档，未触碰任何受保护文件。

---

## 2. 回退清零（Zero Fallback Check）

对 `src/ainerzero/v9/experiments/s2/world.py` 与 `spec.py` 全面 grep 目标模式：

| 检查模式 | 命中位置 | 缺数据时的流向与处理 | 判定 |
|---|---|---|:---:|
| `or []` | 无命中 | — | **通过** |
| `or {}` | 无命中 | — | **通过** |
| `getattr(..., default)` | 无命中 | — | **通过** |
| `if ... is None else` | `line 455` | `limit = float(spec.MAX_REJECTION_RATE) if threshold is None else float(threshold)`：未传参时从 spec 读取单一来源 0.30，绝无放宽回退。 | **通过** |
| `default_` | 无命中 | — | **通过** |
| `0.5` | `line 102-103` | `_ray_cast_cells` 中坐标浮点四舍五入的网格中心偏移，非概率或放宽默认值。 | **通过** |
| `base_success_rate` | 无命中 | — | **通过** |
| `preferred_` | 无命中 | — | **通过** |
| `eval_episode` | 无命中 | — | **通过** |
| **非法上限报错** | `line 654-655` | `if int(max_world_redraws) < 1: raise ValueError(...)` 严格 fail-closed。 | **通过** |

---

## 3. 生产调用链路与单一来源（Single Source of Truth Trace）

- **调用链路**：
  `ainerzero.cli` -> `commands.py:s2_phase1_command` -> `data_runner.run_generate_data` -> `data.generate_partition` -> `world.prepare_world_with_long_pairs`
- **单一来源核查**：
  - `data.generate_partition`（`data.py:426`）调用 `prepare_world_with_long_pairs` 时未显式传递上限和门槛（传 `None`）；
  - `prepare_world_with_long_pairs`（`world.py:650-653`）在调用时刻动态读取 `spec.MAX_REDRAW_RETRIES`（30）与 `spec.MAX_REJECTION_RATE`（0.30）；
  - `world_rejection_requires_redraw`（`world.py:455`）在调用时刻动态读取 `spec.MAX_REJECTION_RATE`（0.30）；
  - `prereg.build_draft()["world"]` 记录的 `max_redraw_retries` 与 `max_rejection_rate` 同样读取 `spec`；
  - 彻底解决了过去 `world.py` 在模块加载时就静态绑定默认值导致与 `spec.py` / `prereg` 脱节的历史隐患。
- **前缀不可变性与只追加**：
  `spec.py` 保留原第 76 行 `MAX_REDRAW_RETRIES = 5` 不变，在末尾第 346 行追加 `MAX_REDRAW_RETRIES = 30`；`test_spec_existing_prefix_byte_for_byte_unchanged` 测试通过，严格遵守前缀只读不可变契约。

---

## 4. 亲手全量注册种子扫描（In-Memory Seed Scan Verification）

复核者亲手执行内存种子生成脚本，遍历 `train`（0–199）与 `dev`（0–49）全部注册种子（严禁触碰 `final` 命名空间，全程无实盘写操作）：

- **扫描结果**：
  - `train`: 200 个世界全部在 92.76s 内生成成功，最大尝试次数为 20 次（world 173）。
  - `dev`: 50 个世界全部在 28.55s 内生成成功，最大尝试次数为 17 次（world 14）。
  - **关键世界重抽次数逐一核实**：
    - `train world 11`: 尝试 8 次（7 次重抽）通过（即原 P188 在上限 5 次时失败的世界）；
    - `train world 173`: 尝试 20 次（19 次重抽）通过（登记 train 最难世界）；
    - `dev world 14`: 尝试 17 次（16 次重抽）通过（登记 dev 最难世界）；
  - 拒绝率均低于 0.30，且全部生成成功，无任何崩溃或超时。详细记录见 `reports/V9-S2-W11/review/seed_scan_output.txt`。

---

## 5. 亲手隔离变异（Isolated Mutations M1–M6）

在独立目录 `/tmp/s2_w11_mutation_env` 中执行变异（复制 `src/`, `tests/`, `pyproject.toml`，并断言 `import ainerzero` 指向副本）：

亲手复现作者 5 处坏对照 M1–M5，并增加复核者自选变异 M6（共 6 处），全部精准变红失败（Exit code 1），还原后 SHA256 100% 恢复，干净环境 8 条测试全绿通过：

| # | 变异操作 | 目标文件 | 变异后测试结果 (RED) | 还原 SHA 核对 |
|---|---|---|---|:---:|
| **M1** | 上限硬编码为 5（`max_world_redraws = 5`） | `world.py` | 3 项失败（train 11, 173, dev 14 失败） | 100% MATCH |
| **M2** | 去掉 spec 覆盖值（`MAX_REDRAW_RETRIES = 5`） | `spec.py` | 5 项失败 | 100% MATCH |
| **M3** | 判定函数门槛硬编码为 0.30（`limit = 0.30`） | `world.py` | 1 项失败（动态 monkeypatch 门槛未生效） | 100% MATCH |
| **M4** | 生成器门槛放宽到 0.5（`rejection_threshold = 0.5`） | `world.py` | 4 项失败 | 100% MATCH |
| **M5** | 禁用上限守卫（`if False:`） | `world.py` | 1 项失败（nonpositive_cap 未被拒绝） | 100% MATCH |
| **M6** | **自选**：别名脱节（`WORLD_REDRAW_MAX = 5`） | `world.py` | 1 项失败（`assert 5 == 30` 契约断言） | 100% MATCH |

详细变异结果记录于 `reports/V9-S2-W11/review/mutations_summary.json`。

---

## 6. 全量测试与实盘 artifacts 零改动审计

- **执行方式**：
  `SIG_DFL+execv` 前台替换执行，通过 `relay exec --every 120` 进行全程心跳与墙钟监控：
  `python3 /tmp/run_pytest_full_w11.py`（内部执行 `.venv/bin/pytest tests/ -ra -q`）。
- **实盘 `artifacts/` lstat 比对**：
  - 测试前扫描：84,432 项（`artifacts_stat_before.json`）
  - 测试后扫描：84,432 项（`artifacts_stat_after.json`）
  - 比对差异：新增 0，删除 0，修改 0（`artifacts_diff.json` 净差异严格为 0）。
- **测试结果**：
  - 3733 passed, 7 deselected in 1338.73s (0:22:18).
  - 退出码：0。

---

## 7. 逐字抽查（Spot Checks）

从 `reports/V9-S2-W11/REPORT.md` 中抽取 4 处声明与实盘/代码/日志逐字比对，全部 100% 一致：
- **SC-1**：用户批准词与 RESEARCH_LOG `R20261108-S2-redraw-30` 逐字匹配；
- **SC-2**：`spec.py` 末尾追加 `MAX_REDRAW_RETRIES = 30` 且第 76 行未变动；
- **SC-3**：`world.py` 动态读取 `spec` 及上限 `< 1` 守卫与卡面描述完全一致；
- **SC-4**：最难世界（train 11, 173, dev 14）重抽次数与实测扫描结果完全吻合。
详细抽查对照见 `reports/V9-S2-W11/review/spot_checks.json`。

---

## 8. 总结与建议

S2 集成 W11 改动精准、严谨且完全符合用户授权与只追加工程规范。所有坏对照及自选变异均在隔离环境中亲手验证变红，全量注册种子扫描验证了上限 30 的充分性与必要性，全量回归测试通过且实盘 artifacts 零污染。

**建议统筹者与一级作者：`RECOMMEND_ACCEPT`（予以接收并推进至下一阶段）。**
