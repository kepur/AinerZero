# E1 r2 代码非作者独立复核报告 (ainerzero.V9.P106)

- **复核者**：`gemini-9f3k`（AinerRelay 二级执行 Agent）
- **复核日期**：2026-11-05
- **复核任务**：`ainerzero.V9.P106`
- **复核范围**：E1 实验代码 r2 修订（先验接触、F1 预测侧、final 入口、预算及向后兼容性）
- **数据与指标产物**：
  - 指标文件：`reports/V9-E1R2-REVIEW/gemini-9f3k/metrics.json`
  - 汇总表格：`reports/V9-E1R2-REVIEW/gemini-9f3k/generated_tables.md`
  - 验证脚本：`reports/V9-E1R2-REVIEW/gemini-9f3k/run_review_audit.py` 等

---

## 0. 领卡自证说明 (Self-Certification)

本人为二级独立执行 Agent `gemini-9f3k`，在接收本任务前：
1. **非作者**：本人不是代码修改作者（claude / claude 系列代理），未参与本次 E1 r2 代码修改与提交；
2. **独立性**：本人不在任务排除执行者（excluded_agents）列表中，无本次改动先验假设，全部复核结论均基于从快照 `reports/V9-E1RUN-C/r1_source_snapshot/e1_source_r1.tar`、当前源码、AnimeWorldZero E0 参考实现及独立编写的验证脚本所得证据。

---

## 1. 核心结论：建议通过 (Recommended for Approval)

经过 10 项严密审计、5000 对随机 SAT 对比、5000 对 E0 几何对齐、400 集全量开发集真值完美预测检验、1200 单元 Arm ② 重算校验及变异测试，本次 r2 代码修订**建议通过**。

### 关键核查结果概览
1. **Diff 范围收敛性**：`prior.py` 严格收敛，球-球分支与所有静态接触分支（地面、斜面、静态盒）逐字未变；
2. **SAT 几何准确性**：独立 SAT 实现 5000 对随机姿态零分歧（`mismatches = 0`），接触时最大穿透深度差 `2.00e-15 m`，法向完全一致；
3. **E0 判定对齐性**：与 AnimeWorldZero E0 `compute_exact_shape_distance` 对齐测试 5000 对，接触判定一致率 `100.0%`（0 分歧），接触距离最大差 `2.22e-16 m`；
4. **Dev 全量完美预测**：两族各 200 集（合计 400 集）全场景真值输入得分均达 `F1 = 1.0000`，`FP = 0`，`FN = 0`；
5. **Arm ② 沿用有效性**：内存重算 1200 评测单元，与 r1 记录相比最大坐标偏差 `0.00e+00 m`（完全 bitwise 相同），不依赖先验修改，完全允许沿用；
6. **Final 入口安全性**：模型构建在前、令牌开封在后，模型失败不损耗读取标记；S 与 P 分区解耦，支持任意先后次序；缺少 `final-eval` 专用审批行时严格拒绝；
7. **预算合规性**：训练 (9900s) + 开发评测 (1500s) = 11400s $\le$ 用户批准上限 11520s（3.2h，留有 120s 余量）；Arm ③ (500s 上限 vs 实际 298s，余量 67.7%) 充裕；Arm ⑥ (1150s 上限 vs 实际 965s，余量 19.2% / 185s 缓冲) 满足需求；
8. **测试套件表现**：全量单测套件通过率 100%（250 passed, 0 failed in 40.57s）。

> [!NOTE]
> **注意事项 (Caution Note)**：
> 1. Arm ⑥ 训练单单元墙钟上限 1150s 对应历史最大耗时 964.76s，余量为 185s（+19.2%）。由于 `train_runner` 超时直接触发 `BudgetStop` 且不保存模型权重，在执行 Arm ⑥ 训练期间宿主机应避免突发重载。
> 2. 变异测试发现：`prior.py` 的边缘偏好偏置 `EDGE_AXIS_PREFERENCE_M` 被篡改为 0.0 时，单元测试因引用同一常量未能阻断，建议后续补充固定数值的边缘决胜单测。

---

## 2. 逐项审查与详细证据

### Item 1: Diff 范围审计
对快照 `reports/V9-E1RUN-C/r1_source_snapshot/e1_source_r1.tar` 进行完整比对：
- **新增文件**：`src/ainerzero/v9/experiments/e1/contact_geometry.py`（纯 Python 精确几何距离模块，移植自 AWZ E0）；
- **删除文件**：无；
- **修改文件**：
  - `analysis.py`：`load_cells` 增加 `partition` 过滤；
  - `commands.py`：修改预算提取、路径解析、禁止数据生成、继承 Arm ② 检查点、final-eval 独立审批校验及去除全局 `.read_once`；
  - `eval_runner.py`：预测侧碰撞检测重构（移除 `_compute_active_static_pairwise`，增加 `_predicted_pair_contact_series` 及 `_evaluate_arm_on_final`）；
  - `prereg.py`：增加 `find_final_eval_approval`，支持独立审批流；
  - `prior.py`：新增 3 个几何辅助函数（`_box_interbody_contact`, `_obb_obb_contact`, `_sphere_obb_contact`），修订 `step_substep` 含箱分支；
  - `spec.py`：更新实验 ID 为 `e1-phase2-20261105-r2`、预算字典 `BUDGET_CAPS` 及继承检查点散列；
  - `worker.py`：实现 Arm ② 复制校验（`ensure_inherited_arm2`）、终验单元分发与结果落盘。
- **`prior.py` 逐字核对**：
  - `step_substep` 从开头到第 635 行（含重力、地面、斜面、桌面、静态盒以及球-球碰撞分支）：与 r1 源码逐字符对比完全一致（`True`）；
  - 从第 700 行到文件末尾（姿态欧拉积分、位置更新、`simulate_frame`、`rollout`）：与 r1 源码完全一致（`True`）；
  - 确认除文档、新增几何函数与含箱分支外无任何意外改动。

### Item 2: SAT 独立参考实现比对 (5000 对随机姿态)
复核者完全独立基于分离轴定理第一性原理编写 15 轴分离判定脚本（不引用任何测试私有函数）：
- **测试样本**：5,000 组随机位置、半跨与朝向的 OBB 对；
- **重叠检出**：检出接触 1,383 对，无接触 3,617 对；
- **一致性**：判定不一致数 `0`（100.0% 一致）；
- **数值精度**：
  - 穿透深度最大误差：`2.00e-15 m`（数值舍入误差极限）；
  - 分离轴法向最大偏差：`0.00e+00`（轴方向完全重合）；
- **3 种边界姿态验证**：
  1. *完全重合*（中心 `[1, 2, 3]`，尺寸朝向一致）：正确检出沿最小轴穿透 `depth = 0.6000 m`，法向 `[0.0, 0.0, 1.0]`；
  2. *平行棱接触*（朝向相同，轴间距退化）：正确跳过退化棱棱叉积（`sq < 1e-12`），返回面接触 `depth = 0.1000 m`，法向 `[0.0, 0.0, 1.0]`；
  3. *远离*（间距 >30m）：正确立即返回 `None`。

### Item 3: 与 AWZ E0 `blender_worker.py` 对齐验证 (5000 对)
使用 Python `importlib` 加载 `/Users/mac/AinerWorkFlow/AnimeWorldZero/python/animeworld/e0/blender_worker.py`：
- **测试样本**：5,000 组包含 SPHERE-SPHERE, SPHERE-BOX, BOX-SPHERE, BOX-BOX 的随机组合；
- **接触阈值**：`0.004 m`；
- **决策一致性**：`c_e0 == c_cg` 一致率 `100.0%`（5000/5000，零分歧）；
- **接触精度**：检出接触状态 659 对，距离最大偏差 `2.22e-16 m`，法向最大偏差 `0.00e+00`。
- **关于早退的理论闭环**：`surface_distance` 中当沿任一轴 `-overlap > contact_tolerance` 时立即返回 `-overlap`。因投影间距为三维欧式最短距离的严格下界（$d_{\text{proj}} \le d_{\text{true}}$），下界大于阈值必然保证真值距离大于阈值，判定恒为 `False`，数学上完全等价且加速计算。

### Item 4: Dev 400 集真值完美预测 (Ground Truth as Prediction)
使用 `GroundTruthArm` 将真值轨迹送入 `eval_runner.evaluate_episode`，对全部 400 集开发集（P 族 200 集、S 族 200 集）进行逐集测试：
- **两族整体**：
  - P 族：200 集，真实事件 281 起，预测 TP 281，FP 0，FN 0，`F1 = 1.0000`；
  - S 族：200 集，真实事件 271 起，预测 TP 271，FP 0，FN 0，`F1 = 1.0000`；
- **全场景细分**：
  - `bounce_collision`：P 族 98/98 事件，S 族 97/97 事件，全部 `F1 = 1.0000`；
  - `box_stack`：P 族 114/114 事件，S 族 109/109 事件，全部 `F1 = 1.0000`；
  - `occlusion_pass`：P 族 40/40 事件，S 族 40/40 事件，全部 `F1 = 1.0000`；
  - `ramp_roll`：P 族 29/29 事件，S 族 25/25 事件，全部 `F1 = 1.0000`；
  - `table_slide`：0 起事件（无碰撞），两族均无误报（FP=0），`F1 = 1.0000`。
- **结论**：彻底消除 r1 中预测侧静态盒与法向误算导致真值无法达到 F1=1 的系统性缺陷。

### Item 5: Arm ② (PureNetArm) 沿用可行性核查
加载 r1 留存检查点 `artifacts/v9/e1/phase2/checkpoints/arm2_{fam}_seed{seed}/model_weights.npz`：
- **评测范围**：P / S 两族 $\times$ 3 个种子 (42, 43, 44)，共 6 组，每组 200 集开发集；
- **比对点数**：比对全部轨迹三维坐标点共 172,800 个；
- **比对结果**：与 `artifacts/v9/e1/phase2/eval/eval_arm2_*.json` 中的记录相比，最大偏差为 **`0.00e+00 m`**（全量 bitwise 相同）；
- **原因与结论**：Arm ② 为纯神经网络预测器，前向推理过程中不调用任何物理先验积分器；先验代码的修改对 Arm ② 的轨迹输出无任何影响。因此，**Arm ② 完全可以且应当直接沿用**。

### Item 6: Final 入口代码逐字核对答复

**(a) 只用 CLI 跑 final-eval 会评测哪些臂？**
> **逐字代码引用**（`src/ainerzero/v9/experiments/e1/worker.py` L421-435, L438-456）：
> ```python
> def registered_final_cells(family: str) -> list[tuple[int, int | None]]:
>     """Registered work cells for a final-eval run on one family."""
>     cells: list[tuple[int, int | None]] = []
>     for arm in spec.EVAL_ARMS:
>         if arm in spec.TRAINABLE_ARM_IDS:
>             for seed in spec.TRAINING_SEEDS:
>                 cells.append((arm, seed))
>         else:
>             cells.append((arm, None))
>     return cells
> ```
> **结论**：评测全部臂 ①–⑦：非训练臂 ①, ④, ⑤, ⑦ 各 1 个单元；可训练臂 ②, ③, ⑥ 各 3 个种子单元（42, 43, 44），指定族单次运行共评测全部 **13 个单元**。

**(b) 什么时候写读取标记？模型加载失败时标记写了吗？**
> **逐字代码引用**（`src/ainerzero/v9/experiments/e1/worker.py` L712-738；`eval_runner.py` L760-762）：
> ```python
> # worker.py:
> # Build every arm first: a bad checkpoint then fails while the read is still unspent.
> arm_factory = kwargs.get("arm_factory")
> cells: dict[str, tuple[int, int | None]] = {}
> if arm_factory is None:
>     arm_factory = build_final_eval_arms(family, output_root, sealed_dir_candidate)
> ...
> final_res = self.final_eval_fn(...)
>
> # eval_runner.py:
> # Token must be obtained via open_sealed_final_once
> token = open_sealed_final_once(sealed_dir, expected_digest=expected_digest, reader=reader)
> ```
> **结论**：读取标记由 `open_sealed_final_once` 在 `eval_runner.evaluate_final_once` 内部打开封存数据集时写入。由于 `worker.py` 在调用 `final_eval_fn` 之前首先执行 `build_final_eval_arms` 加载全部检查点，**若模型加载失败，在构建阶段即抛出异常中断，尚未执行 `open_sealed_final_once`，因此读取标记绝对未写**（封存数据未被损耗）。

**(c) 先跑 S 再跑 P 能跑吗？**
> **逐字代码引用**（`src/ainerzero/v9/experiments/e1/commands.py` L340-362）：
> ```python
> # Check read-once marker on final partition before opening ledger
> fam_sealed_root = paths["data_dir"] / "sealed_final" / family
> has_marker = False
> if fam_sealed_root.is_dir():
>     for sub in fam_sealed_root.iterdir():
>         if sub.is_dir():
>             marker = export.final_marker_path(sub)
>             if marker.is_file():
>                 has_marker = True
>                 break
>
> if has_marker:
>     return {
>         "status": "refused",
>         "mode": mode,
>         "stage": "final_eval_already_read_once",
>         "message": f"Final partition for family {family} has already been read once; further access is permanently forbidden.",
>     }, EXIT_FAILED
> ```
> **结论**：**完全能跑**。r2 删除了 r1 中对全局 `.read_once` 的检查与写入，S 族与 P 族分处独立的封存目录（`sealed_final/S` 与 `sealed_final/P`），各自读取标记完全隔离，先跑 S 仅标记 S 族已读，不影响后续 P 族的运行。

**(d) 只有 `APPROVED e1-phase2 prereg` 那一行时，final-eval 会怎样？**
> **逐字代码引用**（`src/ainerzero/v9/experiments/e1/commands.py` L330-339；`prereg.py` L511-534）：
> ```python
> # The read is irreversible: it needs its own approval line, beyond the one for train and dev.
> try:
>     prereg.find_final_eval_approval(paths["research_log"], expected_sha256=digest)
> except prereg.ApprovalRefused as exc:
>     return {
>         "status": "refused",
>         "mode": mode,
>         "stage": "final_eval_approval",
>         "reasons": exc.reasons,
>     }, EXIT_REFUSED_APPROVAL
> ```
> **结论**：`prereg.find_final_eval_approval` 使用正则 `^APPROVED e1-phase2 final-eval document_sha256=...$` 匹配独立的终验审批行。若只有 prereg 审批行，匹配结果为 0 行，抛出 `ApprovalRefused`，CLI 返回状态 `"refused"`，阶段 `"final_eval_approval"`，退出码为 **`EXIT_REFUSED_APPROVAL` (3)**，在接触账本与数据前被安全拦截。

**(e) 跑到一半某个臂抛异常，已完成的结果和读取标记分别怎样？**
> **逐字代码引用**（`src/ainerzero/v9/experiments/e1/eval_runner.py` L800-815；`worker.py` L721-736, L745-758）：
> ```python
> # eval_runner.py:
> for arm_name, arm_obj in arms_map.items():
>     try:
>         arm_result = _evaluate_arm_on_final(arm_name, arm_obj, student_episodes, truth_by_id)
>     except Exception as exc:
>         failed_arms[arm_name] = f"{type(exc).__name__}: {exc}"
>         continue
>     arms_results[arm_name] = arm_result
>     if on_arm_complete is not None:
>         on_arm_complete(arm_name, arm_result)
>
> # worker.py save_cell 回调:
> def save_cell(name: str, cell_result: Mapping[str, Any]) -> None:
>     ...
>     os.replace(tmp, out_dir / f"eval_{name}.json")
> ```
> **结论**：
> 1. **已完成结果**：每个臂运行完毕后立即通过 `on_arm_complete` 回调刷入磁盘（`eval_{name}.json`），即便后续某个臂抛异常，已完成臂的结果完好保留在磁盘上，且异常臂被记录于 `failed_arms` 中，主报告记录 `"status": "failed"`；
> 2. **读取标记**：由于评测循环开始前已开封数据，**读取标记已经写下并作废**，不可再次打开。

**(f) `analysis.load_cells` 怎么区分 dev 和 final？**
> **逐字代码引用**（`src/ainerzero/v9/experiments/e1/analysis.py` L198-202）：
> ```python
> arm = data.get("arm")
> family = data.get("family")
> seed = data.get("seed")
> # A file from another partition must never be counted as this one.
> if data.get("partition", partition) != partition:
>     continue
> ```
> **结论**：`load_cells(eval_dir, partition="development")` 读取每个 JSON 文件的 `partition` 字段，若 `data.get("partition") != partition` 则显式 `continue` 跳过，彻底隔绝开发集与终验集评测报告混淆。

---

### Item 7: 预算核算与历史墙钟比对
- **预算上限核对**：
  - 训练预算：Arm ③ (6 单元 $\times$ 500s) + Arm ⑥ (6 单元 $\times$ 1150s) = 3,000s + 6,900s = **9,900.0 s**；
  - 开发评测预算：2 族 $\times$ (45+20*3+40*3+45+45+130*3+45) = 2 $\times$ 750s = **1,500.0 s**；
  - **训练 + 开发合计**：9,900s + 1,500s = **11,400.0 s**；
  - **用户批准上限**：3.2 小时 = **11,520.0 s**；
  - **判定**：$11400.0 \le 11520.0$，留有 **120.0 秒净余量**，符合用户预算约束。
- **历史墙钟 (r0/r1 `control.sqlite3` 副本) 评估**：
  - **Arm ③**：历史单单元最大墙钟耗时为 **298.16 s**（S 族 seed 44），r2 设置 500s 预算，余量达 **+67.7% (+201.84 s)**，非常充裕；
  - **Arm ⑥**：历史单单元最大墙钟耗时为 **964.76 s**（P 族 seed 43），r2 设置 1150s 预算，余量为 **+19.2% (+185.24 s)**。
  - **警示**：`train_runner` 在超时后直接抛出 `BudgetStop` 且**不保存权重**。虽然 1150s 覆盖了历史最大 965s，但余量比例低于 20%，训练执行期间应严格保证没有其他高负载进程争抢 CPU。

---

### Item 8: 全量单测套件运行结果
执行命令：`.venv/bin/python -m pytest tests/test_e1_*.py -q`
- **运行耗时**：40.57 s
- **测试结果**：**250 passed, 0 failed** (100% 通过)

---

### Item 9: 变异测试 (Mutation Testing)
在隔离工作区副本中实施 5 项代码变异，检验测试覆盖深度：
1. **MUT_1** (`contact_geometry.py` 斜面矩阵转置)：**CAUGHT**（`3 failed, 8 passed`）；
2. **MUT_2** (`eval_runner.py` 预测序列帧下标偏移 `PREFIX_FRAMES + t` $\to$ `t`)：
   - 在 `test_e1_eval_runner.py` 单测中未被抓到（由于合成用例全为球体，球体朝向为 None）；
   - 在包含真实旋转盒子的全量用例 `test_e1_contact_geometry.py` 中被成功捕获（**CAUGHT**, `2 failed`）；
3. **MUT_3** (`prior.py` 球-盒接触法向反向)：**CAUGHT**（`3 failed, 16 passed`）；
4. **MUT_4** (`analysis.py` 移除分区过滤)：**CAUGHT**（`1 failed, 16 passed`）；
5. **MUT_5** (`prior.py` 将 `EDGE_AXIS_PREFERENCE_M` 置 0.0)：**ESCAPED (未抓到)**（`19 passed in 1.82s`）。
   - **原因分析**：测试文件 `test_e1_prior_box.py` 直接从 `prior.py` 导入了 `EDGE_AXIS_PREFERENCE_M`，测试中的参考 SAT 与被测对象同步变成了 0.0，且既有用例中缺乏在 1mm 边缘偏好窗口内的定向决胜测试。

---

### Item 10: 主动找错清单核查
1. **斜面重建旋转矩阵方向**：
   - 源码：`rot = [[1.0, local_y[0], n[0]], [0.0, local_y[1], n[1]], [0.0, local_y[2], n[2]]]`；
   - 验证：矩阵各列依次为局部 X、局部 Y、局部 Z（法向），行列式 $\det(rot) = 1.0$，右手正交基完全正确，与 AWZ E0 Blender 倾角定义一致；
2. **`_predicted_pair_contact_series` 帧下标**：
   - 源码：`frames[PREFIX_FRAMES + t]["objects"]` 与 `pred_positions[name][t]` 对应；
   - 验证：$t \in [0, n\_future)$ 时访问真值帧 $[PREFIX\_FRAMES, PREFIX\_FRAMES + n\_future)$，与真值碰撞提取窗口 $[t\_start, t\_end)$ 完全同步；
3. **`surface_distance` 提前返回**：
   - 源码：当 $-overlap > contact\_tolerance$ 时提前返回投影间距；
   - 验证：投影分离距离为三维欧式几何间距严格下界，下界大于 $0.004\text{m}$ 必然使得真值距离大于 $0.004\text{m}$，接触判定布尔值恒为 False，不改变任何判定；
4. **`ensure_inherited_arm2` 半成品目录处理**：
   - 源码：通过 `partial = dest.with_name(dest.name + ".partial")` 拷贝后再 `os.replace`，原子性避免产生半成品目录；
   - 异常防护：若目标目录已存在损坏数据，`verify_inherited_arm2` 校验 SHA256 散列并抛出 `RuntimeError`，杜绝静默加载残缺权重；
5. **`IMPLEMENTATION_SOURCES` 覆盖**：
   - 验证：`src/ainerzero/v9/experiments/e1/spec.py` 中已包含 `contact_geometry.py`，完整纳入代码散列保护；
6. **`_resolve_paths` 默认数据目录**：
   - 源码：当 `output_root == spec.REGISTERED_HOST_PHASE2` 时，`default_data_dir = spec.REGISTERED_HOST_DATASETS`；
   - 验证：r2 默认只读复用 r0/r1 的数据集，不生成新数据；
7. **旧路径与旧实验 ID 遗留**：
   - 验证：当前实验 ID 全面更新为 `e1-phase2-20261105-r2`，旧实验 ID 仅作为 `SUPERSEDED_EXPERIMENT_IDS` 保留在常量定义中，账本独立且无遗留干扰。

---

## 3. 复核结论与建议

本复核者确认：
1. 本次修订准确修补了 r1 阶段关于先验贴合误报穿透及 F1 预测几何不一致的两个核心缺陷；
2. 完美预测在开发集 400 集全部通过达到 F1=1.0000；
3. Arm ② 预测完全一致，可安全沿用；
4. 预算严格控制在用户批准的 3.2 小时以内。

**综合评定：建议通过 (Recommended for Approval)。**
