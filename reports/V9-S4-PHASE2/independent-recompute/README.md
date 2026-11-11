# S4 二期 final 非作者独立复算工具 (`recompute_p2.py`)

本工具为 S4 第二阶段（Phase 2）final 评测的独立复算脚本。
作者：二级执行 agent（`gemini-k7b2`，非作者模型）。
设计依据：`reports/V9-S4-P2-DESIGN/DESIGN-r1.md` §5。

---

## 1. 原则与依赖

- **零项目代码导入**：纯 Python 标准库（`json`, `math`, `argparse`, `pathlib`）与 `numpy`。**绝对不导入 `ainerzero`、`mlx` 或任何仓库代码**。
- **独立实现**：重采样、比值计算、门判据及合法性核验公式全部独立编码。
- **可复现性**：使用登记的重采样配置（配对 bootstrap，种子 20261111，10,000 次重采样，Bonferroni $m=12$ 校正）。

---

## 2. 如何在 Final 数据上运行

### 2.1 依赖准备
环境需安装 Python 3.10+ 及 NumPy：
```bash
python3 -c "import numpy; print(numpy.__version__)"
```

### 2.2 运行命令
当 Phase 2 final 运行结束，落盘产生 `worlds.jsonl` 与 `PREREG-r1.json` 后，执行：

```bash
python3 reports/V9-S4-PHASE2/independent-recompute/recompute_p2.py \
  --records <path-to-final-worlds.jsonl> \
  --params <path-to-PREREG-r1.json> \
  --out <path-to-output-recompute.json>
```

若需直接在摸底 G 轮落盘文件 `results-p2g.json` 上运行核验：
```bash
python3 reports/V9-S4-PHASE2/independent-recompute/recompute_p2.py \
  --records reports/V9-S4-P2-DESIGN/tier1-explore/results-p2g.json \
  --params reports/V9-S4-PHASE2/independent-recompute/evidence/params_p2g.json \
  --assert-stored \
  --out reports/V9-S4-PHASE2/independent-recompute/evidence/recomputed-p2g.json
```

### 2.3 命令行参数说明

| 参数 | 类型 | 说明 |
|---|---|---|
| `--records` | 路径 (必需) | 输入记录文件，支持 `.jsonl`（逐行记录）或 `.json`（包含 `records` 列表） |
| `--params` | 路径 (可选) | 预登记或参数配置 JSON（如 `PREREG-r1.json`）。从中读取门阈值、重采样配置、主/对照臂名称、世界数量 |
| `--out` | 路径 (可选) | 复算结果 JSON 输出路径 |
| `--n-main` | 整数 (可选) | 注册的主评测世界数（未传 `--params` 时可用） |
| `--n-extrap` | 整数 (可选) | 注册的外推评测世界数（未传 `--params` 时可用） |
| `--bootstrap-n` | 整数 (可选) | 重采样次数，默认 10000 |
| `--bootstrap-seed`| 整数 (可选) | 重采样 RNG 种子，默认 20261111 |
| `--bonferroni-m`| 整数 (可选) | Bonferroni 比较次数 $m$，默认 12 |
| `--level` | 浮点 (可选) | 置信水平，默认 0.95 |
| `--seeds` | 整数列表 (可选) | 跟踪种子列表，默认 `1 2 3` |
| `--main-arm` | 字符串 (可选) | 主臂名称，默认 `L-int-g` |
| `--scatter-arm`| 字符串 (可选) | 散射对照臂名称，默认 `L-sc-g` |
| `--negative-arm`| 字符串 (可选) | 负对照臂名称，默认 `L-ind-geo` |
| `--assert-stored`| 开关 (可选) | 若输入 JSON 中包含原始 `stats` 与 `passed`，自动断言逐位完全一致 |

---

## 3. 复算内容与输出结构

输出 JSON 包含四大块：
1. `stats`：14 项门与负对照统计量（`GN`, `GA`, `GC`, `GK1_all`, `GK1_collision`, `GK2_non_collision`, `GK2_collision`, `GD_D`, `GD_ratio`, `GX_diff`, `GX_C`, `GR`, `neg_C`, `neg_D`），每项包含：
   - `value`：点估计；
   - `ci_low`, `ci_high`：95% 置信区间；
   - `bonf_low`, `bonf_high`：Bonferroni 校正区间（$m=12$）；
   - `n_worlds`：参与统计的世界总数；
   - `n_boot_finite`：有限有效重采样次数。
2. `passed`：8 项主门（`GN`, `GA`, `GC`, `GK1`, `GK2`, `GD`, `GX`, `GR`）布尔通过状态。
3. `negative_control`：负对照通过状态（`neg_C` 与 `neg_D` 的 Bonferroni 上界均 $< 0.5$）。
4. `legality`：可从记录中直接复算的 3 项合法性门（`floor`, `samples`, `complete`）。

---

## 4. 无法由本脚本单独计算的合法性门及另行核对方法

`recompute_p2.py` 处理落盘的结构化记录（事件、单元格指标、真值动力学误差）。依据 `DESIGN-r1.md` §5，下列合法性门涉及底层世界状态或独立外部核验，**不能仅凭 records 计算**，必须通过独立的外部工具和检查清单另行核验：

| 门类别 | 判据要求 | 为什么记录算不了 | 独立核对方法与命令 |
|---|---|---|---|
| **标签 (labels)** | 重新出现事件与「有碰撞」由接触日志独立重算一致 | records 中只记录已抽取的事件和各格对错，不包含完整的逐步接触日志与障碍物遮挡原始时间序列 | 使用 `verify_labels_p2.py` 重新读取环境 episode 逐步接触日志独立抽取事件并逐字核对：<br>`python reports/V9-S4-PHASE2/verify_labels_p2.py --records worlds.jsonl` |
| **确定性 (determinism)** | 另一个独立进程从权重重放主评测前 3 个、外推前 2 个世界全部 33 格，分配摘要与事件对错逐位相同 | 需要重新初始化卡尔曼滤波器、随机数发生器与模型推理计算 | 使用 `verify_replay_p2.py`：<br>`python reports/V9-S4-PHASE2/verify_replay_p2.py --records worlds.jsonl --weights artifacts/v9/s4/phase1/final-final/weights` |
| **权重完整性 (weights)** | 6 个权重文件的 SHA256 与预登记一致 | records 中不包含物理权重文件二进制内容 | 独立执行哈希校验：<br>`shasum -a 256 artifacts/v9/s4/phase1/final-final/weights/*.safetensors` 并比对 `PREREG-r1.json` 中登记的哈希字典 |
| **学生视图 (student_view)** | 跟踪器仅读取 student_view 检测，未来帧不可见 | 属于运行时代码侵入性检查，records 中无从得知是否发生了未来信息泄露 | 检查 `run_s4p2.py` 运行日志中未来帧扰动变异测试（`future_frame_mutation_test`）的通过记录 |

---

## 5. 校验与对抗自检留档

所有在 G 轮记录上的逐位比对证据与 4 种对抗性篡改实验留存于 `evidence/` 目录，详见 `REPORT.md`。
