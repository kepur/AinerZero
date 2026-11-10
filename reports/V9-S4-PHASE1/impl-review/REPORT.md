# S4 第一阶段实现的非作者复核（未完成）

复核者：`claude-s4impl-rev-1110`，2026-11-10。被审提交：`eb4cc51`（含 `0427324`、`d100ead`）。复核时工作树里 `reports/V9-S4-PHASE1/mutants/mutate.py` 和 `tests/v9/experiments/test_s4_learned_mlx.py` 有作者的未提交改动，我没有读这两处改动。

## 结论

**复核未完成，不能作为放行登记运行的依据。** 会话用量到了上限，只完成了通读一部分源码。就已读部分暂判**打回**：1 项必修、4 项应修。

下面所有判断都来自逐行阅读，**没有执行任何代码**：测试没有复跑，没有做变异，没有建隔离副本，`evidence/` 目录没有内容。

已读完的文件：`DESIGN-r3.md`、`learned_mlx.py`、`analysis.py`、`metrics.py`、`filter.py`、`worker_mlx.py`、`models.py`、`world.py`、`run_s4p1.py`、`s3/run_guard.py`。

## 必修项

### 1. 写下 final 标记之前不检查剩余墙钟够不够评测，final 可能被白白花掉

文件：`reports/V9-S4-PHASE1/run_s4p1.py`。

- 第 284 行 `deadline.check()` 只要求剩余时间大于 0。
- 第 289 行随即 `GD.consume_final_read(...)` 写下只读一次标记。
- 第 223–227 行，评测中 `left <= 0` 时抛 `GD.GuardError("wall-clock limit reached")`。
- 逐世界记录要到第 299–302 行、`evaluate_parallel` 全部返回之后才落盘，所以超时的时候已算完的世界也不留下。
- 训练的单格上限没有强制：第 155 行的 `deadline.check()` 只在两格之间执行，`L.train` 不接收 deadline；第 166 行 `"over_cell_limit": secs > CELL_LIMIT_S` 只是记录。

后果：训练格超时会悄悄吃掉评测的余量。设计稿 §7 的计划是训练最多 3 小时、硬上限 4 小时。训练如果用到 3.9 小时，标记照样写下，评测随后超时，final 的这一次读取被消耗，一个数也拿不到。

建议修法：
- 写标记之前要求剩余时间不小于登记的评测预算（由探针实测定），不够就在标记之前拒绝。
- 单格超过 `CELL_LIMIT_S` 时在标记之前失败，或把 deadline 传进 `L.train` 的循环。
- 评测改为每完成一个世界就追加落盘，超时后至少留下可复算的部分。

复现方式（未执行，供作者或下一位复核者用）：在替身命名空间的隔离副本里把 `STAGES` 的 `limit` 设成略大于训练耗时，观察是否先写标记再超时。

## 应修项

1. **学生视图检查不要求变异生效。** `run_s4p1.py` 第 200 行：`return {"passed": bool(keys_ok and all(r["prefix_equal"] for r in rows)), "keys_ok": keys_ok, "rows": rows}`。`suffix_changed` 只记录不判定，未来帧变异如果实际没有改到输入，这一门也会通过。另外 `keys_ok` 检查的是 `W.student_view` 的返回键，而跟踪器实际读的是 `[s.detections for s in ep.steps]`（`analysis.py` 第 126 行），没有经过 `student_view`，白名单检查近似恒真。建议要求每一行 `suffix_changed` 为真。
2. **训练设备与设计稿不符。** 设计稿第 261 行写「本机 MLX CPU，不付费，不用云」，`run_s4p1.py` 第 141 行是 `mx.set_default_device(mx.gpu)`。需要在设计稿或预登记里声明。确定性门只从落盘权重重放跟踪，不受影响；但 GPU 训练的权重能否逐位复现我没有验证。
3. **批的构成需要在设计稿里声明。** `learned_mlx.py` 第 44 行 `COLL_SHARE = 0.5`、第 45 行 `NEAR_SHARE = 0.0`、第 46 行 `NEAR_GAP = 2 * RADIUS + 0.3`。近失样本的距离与 HF 的擦边步定义相同（`metrics.py` 第 19 行 `GRAZE_MARGIN = 0.3`，第 59 行）。`sample_kinds`（第 268–278 行）只读训练池的标签，没有读到评测数据，所以这不是数据泄漏；但它是照着评测指标的定义来配训练分布，应当写进设计稿，并说明这些常数在冻结后不再改。同样要声明的还有 `CLIP`、`EPS_DIR`、非有限即停、`perturb` 里的 `np.clip` 和「至少保留两个盘」。
4. **bootstrap 查不出分母变号。** `metrics.py` 第 88–94 行只把非有限的重采样算作无定义。`stat_C` 的分母 `p - b` 在某次重采样里为负时，比值有限但符号翻转，仍会进入区间。200 个世界、差约 0.23 时这种情况大概很少见，这一句是推测，没有算过。建议分母不为正的重采样也按无定义处理。

## 读过并且没有发现问题的要点

- **代码约束（`learned_mlx.py` 第 62–148 行）：** 前向路径里没有反射或交换速度的运算，模块不导入世界模块。接触头的 logits 只作为输出返回（第 124、148 行），不拼进更新网络的输入。L-ind 在 `self.interact` 为假时不调用 `messages`，输入只有自身状态和墙、柱几何。L-int-c 把相对速度投影到盘心连线、输出再沿连线转回，这是很强的结构先验；设计稿 §3 已声明为「解析规范化」，它也不是过门的臂。
- **门的阈值与区间界（`analysis.py` 第 45–53、229–260 行）：** HD、HF、HD-x、H1、H2、H3 和负对照的数值、用下界还是上界，与设计稿 §5 一致。负对照失败只作废 HD、H1，与设计稿第 208 行一致。合法性失败时全部门作废。
- **`None` 的处理：** `ok()` 要求每个值不为 `None`；负对照的区间为 `None` 时判失败，进而作废 HD、H1。没有读到「缺数据默认通过」的路径。
- **bootstrap 的规则：** 任何一次重采样无定义就不给区间，对所有门都是偏保守的，没有读到反向放行的路径。
- **主评测与外推评测：** `evaluate` 里 HD、HF、H1、H2、负对照用 `main`，HD-x、H3 用 `extrap`，各自用本分区的 E-B 作分母。
- **`allow_registered`：** 运行器里只有第 292 行一处传入，在写标记之后。`worker_mlx.py` 没有调用 `generate_episode`。
- **门从落盘文件算：** 第 320 行重新读 `worlds.jsonl`，再交给 `evaluate`。

## 没来得及看的部分

任务第 5、7、8、9、10 项全部没做，第 4 项只做了一部分：

- `verify_labels.py`、`verify_replay.py`、`make_prereg.py`；
- 全部测试文件和作者的变异脚本、结果，包括 `fi_gate_strict`、`as_pad_small` 是否等价；
- 冻结清单是否覆盖传递闭包和设计稿（依赖 `make_prereg.py`）；
- S4 测试的复跑与数量核对（作者报告 113 项）；
- `RESEARCH_LOG.md` 的 S4 条目与摸底日志的数字对照；
- `filter.py` 的 `on_predict` 钩子、`analysis.py` 的描述量只读过，没有对抗检查。

## 变异清单

没有做。
