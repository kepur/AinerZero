# P235 第 3 轮一级补充测试非作者复核报告（二级评审）

- **任务 ID**：`ainerzero.V9.P237`
- **被复核任务**：`ainerzero.V9.P235`（accepted，commit `e4d374d`）
- **复核对象**：一级评审（claude）在第 3 轮为 P235 补充的三条测试及相关辅助函数：
  - 文件：`tests/v9/experiments/test_s5_train_mlx.py`（L600–L675）
  - 辅助函数：`_fill_dropped`（L603–L613）、`_r1_weights`（L616–L617）
  - 测试用例：
    1. `test_predict_restores_dropped_positions_from_run_start`（L620–L640）
    2. `test_train_heads_r1_ignores_dropped_token_values`（L642–L659）
    3. `test_a0r_r1_loss_ignores_dropped_token_values`（L661–L675）
- **复核执行者**：`gemini-r7b2`（Tier 2 Reviewer，独立无关联执行者）
- **评审结论**：**需补**（一级补充的三条测试在 R1 头还原上逻辑严谨且容差严格，但在 `predict` 接口对 R2/R3 GridHead 的约束上存在显著漏测盲区，未能覆盖设计稿关于「GridHead 不得使用还原 token 且必须传递 mask」的约束，自制坏对照出现 2 例漏网）。

---

## 1. 一级补充测试逐条深入核查

### 1.1 辅助函数 `_fill_dropped` 机制与隔离性分析

- **代码位置**：`tests/v9/experiments/test_s5_train_mlx.py` L603–L613
- **逐字摘录**：
  ```python
  def _fill_dropped(fill):
      """Wrap Student.__call__ so that dropped (keep=False) token outputs are `fill` instead of zeros."""
      orig = Student.__call__

      def wrapped(self, patches, keep=None, run_len=None):
          tokens, mask = orig(self, patches, keep=keep, run_len=run_len)
          if keep is None:
              return tokens, mask
          return mx.where(mask[..., None], tokens, mx.array(fill, dtype=tokens.dtype)), mask

      return wrapped
  ```
- **工作机制核查**：
  1. 包装函数首先调用原生的 `orig(self, patches, keep=keep, run_len=run_len)`，保证 Student 内部的前向计算、梯度流以及内部状态计算完全执行正常逻辑。
  2. 若 `keep is None`（非 RLT 模式），直接透传返回值 `tokens, mask`。
  3. 若 `keep is not None`，`mask` 为形状 `(B, T*H*W)` 的布尔掩码（`True` 表示保留，`False` 表示丢弃）。通过 `mx.where(mask[..., None], tokens, mx.array(fill, dtype=tokens.dtype))`，将所有未保留位置（即 dropped token）的输出张量强制替换为标量常量 `fill`（测试中分别对比 `0.0` 与 `1.0e3`）。
- **隔离性与全局污染核查**：
  - 测试中严格使用 `monkeypatch.setattr(Student, "__call__", _fill_dropped(fill))` 进行临时动态 patch。
  - `monkeypatch` 是 pytest 框架级的内建 fixture，每个测试函数执行完毕后会自动触发 teardown 恢复 `Student.__call__` 原属性，不会泄露或污染其他测试文件或全局状态。
  - 该替换仅作用于被测实例的输出张量切片，并未修改学生网络参数或文件系统。
  - **核查结论**：机制安全，无全局污染，具备极佳的故障注入（fault injection）辨识力。

---

### 1.2 调用计数包装 `calls.append(keep is not None)` 的有效性核查

- **代码位置**：
  - L648：`monkeypatch.setattr(T, "restore_runs", lambda tok, keep: (calls.append(keep is not None), real(tok, keep))[1])`
  - L656：`assert calls and all(calls), "train_heads must call restore_runs with a keep mask under RLT"`
  - L667：`monkeypatch.setattr(T, "restore_runs", lambda tok, keep: (calls.append(keep is not None), real(tok, keep))[1])`
  - L674：`assert calls and all(calls), "A0-R must call restore_runs with a keep mask"`
- **逐字摘录分析**：
  ```python
  monkeypatch.setattr(T, "restore_runs", lambda tok, keep: (calls.append(keep is not None), real(tok, keep))[1])
  ```
- **约束有效性判断**：
  1. 表达式利用元组构造 `(calls.append(...), real(...))[1]`，每次调用 `restore_runs` 时均先向 `calls` 列表推入布尔值 `keep is not None`，并返回真实调用的张量结果。
  2. 验收断言为 `assert calls and all(calls)`：
     - 若 `restore_runs` 未被调用，`calls` 为空列表 `[]`，断言失败；
     - 若 `restore_runs` 被调用多次，但其中哪怕有一次传入的 `keep` 为 `None`，`calls` 中就会出现 `False`，导致 `all(calls)` 为 `False`，断言立即失败。
  3. 因此，该断言不仅保证了「至少被调用一次」，而且**严格保证了在整个训练循环/缓存阶段中的每一次调用都携带了非空的 `keep` 掩码**。
  - **核查结论**：计数与非空约束真实有效，无法被伪造或单次调用糊弄。

---

### 1.3 容差阈值（`atol` 与 `rtol`）合理性核查

1. **`test_predict_restores_dropped_positions_from_run_start` 中的 `atol=1e-6`**：
   - **代码行**：L635–L636
   - **逐字摘录**：
     ```python
     np.testing.assert_allclose(out["r1_logd"][n, 2 * t:2 * t + 2, h, w],
                                out["r1_logd"][n, 2 * a:2 * a + 2, h, w], atol=1e-6)
     ```
   - **分析**：根据 `restore_runs` 语义，丢弃帧 `t` 复制了同一 run 起始帧 `a` 的特征表示。当送入静态头网络（`R1Head`）时，两处切片接收的输入张量在数学上完全等价。`atol=1e-6` 对应 float32 下的严格数值等价性，兼顾了 GPU/Metal 并行浮点运算的极微小舍入误差，既未放水，也不会因硬件抖动误报。
2. **`test_train_heads_r1_ignores_dropped_token_values` 中的 `atol=1e-5`**：
   - **代码行**：L658
   - **逐字摘录**：
     ```python
     np.testing.assert_allclose(results[0][k], results[1][k], atol=1e-5, err_msg=k)
     ```
   - **分析**：对比 `fill=0.0` 与 `fill=1000.0` 时训练得到的头网络权重。若 `restore_runs` 生效，输入特征对未保留位置的扰动完全免疫；若失效，扰动幅度达 $10^3$，权重大范围发散（实验证实差异超过 200 倍）。`atol=1e-5` 极其敏感，完全能够捕捉任何 token 泄露，同时容忍了两次运行间非关键浮点累加误差。
3. **`test_a0r_r1_loss_ignores_dropped_token_values` 中的 `rtol=1e-5`**：
   - **代码行**：L675
   - **逐字摘录**：
     ```python
     np.testing.assert_allclose(losses[0], losses[1], rtol=1e-5)
     ```
   - **分析**：相对误差阈值 $10^{-5}$（即 0.001%）。在学生端到端训练中，如果未保留位置发生泄露，`fill=1000.0` 下损失值会从约 2.65 骤增至 116.5 以上（相对误差数千倍）。`rtol=1e-5` 具有极高判别力，设定合理。

---

## 2. 独立坏对照实验（4 个全新对抗突变）

在完全隔离的副本目录 `/tmp/mut_p237` 中对 `src/ainerzero/v9/experiments/s5/train.py` 实施了 4 个全新对抗突变（与一级评审的 U1–U5 完全不重样）。

### 2.1 突变设计与机理

| 编号 | 突变目标 | 突变注入逻辑 | 设计初衷与预期 |
| :--- | :--- | :--- | :--- |
| **J1** | `restore_runs` 填充方向反转 | 从后向前填充：`curr = mx.where(mask_t, t_4d[:, -1 - t], curr)` | 检验测试是否真正锁定了从「历史 run 起始点」向前向后传播的因果时间语义。 |
| **J2** | `predict` 接口丢弃 GridHead mask | `r2_logit = model.heads["r2"](tokens, mask=None)`<br>`r3_logit = model.heads["r3"](tokens, mask=None)` | 检验测试是否检查了 `predict` 在 RLT 激活时向空间头 R2/R3 传递有效掩码 `grid_mask`。 |
| **J3** | `train_heads` 缓存中置空 `b_keep` | `r1_tokens = restore_runs(b_tokens, None)` | 检验 `train_heads` 是否能检测到传给 `restore_runs` 的 keep 为空（即逃避还原）。 |
| **J4** | `predict` 错误将还原 token 喂给 R2/R3 | `r2_logit = model.heads["r2"](r1_tokens, mask=grid_mask)`<br>`r3_logit = model.heads["r3"](r1_tokens, mask=grid_mask)` | 检验设计规范《DESIGN-r1.md》核心约束：R1 必须用还原 token，而 R2/R3 是 GridHead 必须用原始带洞 token。 |

### 2.2 突变测试执行结果

| 突变编号 | 状态 | 击杀测试用例 / 漏网现象 | 关键日志摘录 |
| :---: | :---: | :--- | :--- |
| **J1** | **KILLED** | `test_predict_restores_dropped_positions_from_run_start`<br>`test_restore_runs_properties` | `FAILED tests/v9/experiments/test_s5_train_mlx.py::test_predict_restores_dropped_positions_from_run_start`<br>`1 failed, 28 passed` |
| **J2** | **SURVIVED (漏网)** | **无任何测试失败！所有 29 项测试全部通过！** | `29 passed in 22.31s`（严重漏测盲区） |
| **J3** | **KILLED** | `test_train_heads_r1_ignores_dropped_token_values` | `AssertionError: train_heads must call restore_runs with a keep mask under RLT`<br>`1 failed, 28 passed` |
| **J4** | **SURVIVED (漏网)** | **无任何测试失败！所有 29 项测试全部通过！** | `29 passed in 22.25s`（严重漏测盲区） |

- **坏对照原始运行日志归档**：`reports/V9-S5-IMPL-5/r3-review/evidence/mutations-output.txt`
- **坏对照驱动脚本归档**：`reports/V9-S5-IMPL-5/r3-review/evidence/mutations.py`

---

## 3. 盲区分析与漏网根因定位

### 3.1 为什么 J2 与 J4 会完全存活（SURVIVED）？

在 `src/ainerzero/v9/experiments/s5/train.py` 的 `predict` 函数实现中（L690–L705）：
```python
    k_mx = mx.array(keep) if keep is not None else None
    r1_tokens = restore_runs(tokens, k_mx if tau is not None else None)
    r1_logit = model.heads["r1"](r1_tokens)

    grid_mask = None
    if keep is not None:
        grid_mask = mx.array(keep, dtype=mx.bool_)
    r2_logit = model.heads["r2"](tokens, mask=grid_mask)
    r3_logit = model.heads["r3"](tokens, mask=grid_mask)
```
对照设计规范《DESIGN-r1.md》「实现阶段补记 3」明确指出：
> 「RLT 下 R1 的取法：R1 只有当 RLT 处于激活状态时才通过 restore_runs 填补被丢弃的 token；R2、R3 是 GridHead，必须用原始含空洞的未还原 token（配合 mask 评估）。」

然而，一级在第 3 轮补充的 `test_predict_restores_dropped_positions_from_run_start`（L620–L640）：
```python
    checked = 0
    for n in range(len(idx)):
        keep, _ = rlt_keep(D.load_item(idx, n)["patches"], 0.02)
        for t in range(1, 8):
            for h, w in zip(*np.where(~keep[t])):
                a = max(s for s in range(t + 1) if keep[s, h, w])
                np.testing.assert_allclose(out["r1_logd"][n, 2 * t:2 * t + 2, h, w],
                                           out["r1_logd"][n, 2 * a:2 * a + 2, h, w], atol=1e-6)
                checked += 1
    assert checked > 0, "fixture must contain dropped tokens at tau=0.02"
    assert not np.allclose(out["r1_logd"], plain["r1_logd"])
```
**严重漏洞**：该测试仅仅断言了 `out["r1_logd"]`，对 `out["r2_logd"]` 和 `out["r3_logd"]` 完全视而不见！
而早期由实现者编写的 `test_predict_shapes_and_tau` 也仅检查了 `out["r2"].shape`，无论传入 `tokens` 还是 `r1_tokens`，无论 `mask` 是否为 `None`，张量形状完全一致！
这就导致：
1. **J2 漏洞**：如果实现者在 `predict` 里漏传了 `mask=grid_mask`（传入 `None`），没有任何测试能发现！
2. **J4 漏洞**：如果实现者错误地把 `r1_tokens`（已通过填补抹平空洞的 token）送入了 R2/R3，违反了 GridHead 必须使用带洞原始 token 的设计契约，现有一切测试依然全部绿灯！

---

## 4. 必须补充的测试条目（需补清单）

为补齐上述盲区，一级评审或作者应在 `tests/v9/experiments/test_s5_train_mlx.py` 中补充以下测试验证：

### 补测项 1：`predict` 接口在 RLT 激活下对 R2/R3 掩码有效性的敏感性断言
- **测试逻辑**：
  在 `test_predict_restores_dropped_positions_from_run_start` 中（或新增专用测试 `test_predict_gridhead_mask_and_tokens_under_rlt`）：
  使用 `monkeypatch` 包装 `R2Head.__call__` 与 `R3Head.__call__`，或者直接检验传给 `GridHead` 的 `mask` 参量：
  ```python
  def test_predict_passes_correct_tokens_and_mask_to_gridheads(train_fixture, monkeypatch):
      idx = D.ClipIndex(train_fixture / "part")
      student = _make_small_student()
      grid_calls = []

      orig_r2 = GridHead.__call__
      def wrapped_r2(self, x, mask=None):
          grid_calls.append({"x": np.array(x), "mask": None if mask is None else np.array(mask)})
          return orig_r2(self, x, mask=mask)

      monkeypatch.setattr(GridHead, "__call__", wrapped_r2)
      heads = T.HeadsContainer(r1=R1Head(d=32), r2=GridHead(out=(12, 7), d=32, heads=2),
                               r3=GridHead(out=(12, 7), d=32, heads=2))

      out = T.predict(student, heads, idx, tau=0.02)
      assert len(grid_calls) > 0
      for call in grid_calls:
          # 必须传入非空掩码
          assert call["mask"] is not None, "predict must pass grid_mask to GridHead under RLT"
          assert call["mask"].dtype == bool or call["mask"].dtype == np.bool_
  ```

### 补测项 2：`predict` 接口中 GridHead 必须接收原始未还原 token（严禁接收 `r1_tokens`）
- **测试逻辑**：
  通过 `_fill_dropped(1.0e3)` 注入显著的扰动值，验证传给 GridHead 的 token 在未保留位置确实保留了原始带洞/未填充的数值，而不是被 `restore_runs` 覆盖为前序帧的特征；或者直接在测试中对比：
  ```python
      # 验证传给 GridHead 的 tokens 与未经 restore_runs 处理的原始 student 输出完全一致
      # 而与 restore_runs 处理后的 r1_tokens 在丢弃位置存在显著差异
  ```

---

## 5. 结论

- **判定**：**需补**
- **简要理由**：一级在第 3 轮补充的 3 条测试在 R1 头（`restore_runs`）的三个调用点上验证了容差与不变性，但存在重大边界盲区：对 `predict` 中 R2/R3 GridHead 的 `mask` 传递与 `tokens` 未还原约束缺乏有效断言，导致对抗突变 J2（丢弃 mask）与 J4（错误传入还原 token）完全存活。需在后续轮次或阶段中补全上述约束测试。
