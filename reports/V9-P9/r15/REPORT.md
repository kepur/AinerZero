# ainerzero.V9.P53 报告：S1 r15——修 few-shot 查询切片、多来源继承、重冻结

- **作者**：一级 `claude`。**需要非作者复核**，见 `ainerzero.V9.P54`（gemini）。
- **依据**：RESEARCH_LOG `## R20261028-S1-phase1-r15-budget`（用户 10-28「批准 r15含补训」）。
- **未做的事**：没有在生产 output-root 上训练或评测；没有写批准行；没有改 `src/ainerzero/runtime/`。
- **生产台账**：开工与收尾都是 `b0314c9d44a356d5330a71ca80951c3c1b6e08e49da123b3e44dcb9bc8ac2648`（`evidence/production-ledger-{start,end}.txt`）。这是 r14 正式运行写入后的值；本卡只做 shasum 读取。

## 1. 结论（≤10 行）

1. **缺陷已修**。位置图/度量图的写入与 few-shot 查询现在共用 `spec.memory_key_slices`：arm2 `(0,32)`，arm3 `(0,32)`，arm4 map `(0,24)` / graph `(24,48)`，probe 与 graph 相同。
   - 回归用例在 r14 代码上失败（`matmul … size 5 is different from 2`），在 r15 代码上通过。
   - 三个臂各一格的真实 MLX 评测，在隔离副本上全部 completed。
2. **训练数学逐位不变**：arm2/3/4 seed 0 的真实 MLX 窗口探针损失，在 r14 源码与 r15 源码下逐位相同（`logs/equivalence.json`）。
3. **新身份** `s1-phase1-20261028-r15`；**多来源继承 8 格**：r13 三格、r14 五格，每格各带源实验，r14 的单来源格式仍然有效。
4. **冻结**：`artifacts/v9/s1/phase1/r15/pre_registration.json`。
   - document SHA：`2174de670c844535ce63795a23ba4b413ad70ef3f1c2cf7a929b3de5bb5a99f9`
   - file SHA：`361e57f3f78fb2e0d76a0ed5980662da851f56d97de523c979d87a33361ee75d`
5. **r14→r15 逐叶差异**：56 叶变化，**白名单外为 0**。
   - inheritance 节外有 10 叶：experiment_id、created_unix，以及本卡改动的 6 个文件的来源 SHA 和 2 个摘要。
   - 七个科学节与 effective_metadata 全部相等。
6. **隔离副本入口检查 12/12 通过**。
7. **测试**：`tests/v9` 共 981 项，978 通过，失败的 3 项与 P38/P49 相同、均为已知问题。

## 2. 改动

| 文件 | 改动 |
|---|---|
| `spec.py` | `R15_EXPERIMENT_ID`；`R15_INHERITANCE`（`sources` 分别给出 r13 与 r14 的预登记 file/document SHA，8 个 cell 各带 `source_experiment_id`、run_id 与 params SHA；批准总墙钟 5400 s）；`INHERITANCE_BY_EXPERIMENT` 增加 r15；`REGISTERED_EXPERIMENT_IDS` 增至五个；`CURRENT_EXPERIMENT_ID = r15`；新增纯函数 `memory_key_slices`，不依赖 MLX |
| `arms.py` | 基类新增 `ARM_ID`、`memory_slice(kind)`、`probe_key(h)`；三个臂的 `memory_update` 改为调用 `memory_slice`，结果与原来的字面切片逐位相同（见 §3） |
| `runtime.py` | `MlxBackend.probe_query(model, obs)` = `model.probe_key(encode(...))` |
| `evaluation.py` | few-shot 的两处查询从 `backend.encode` 改为 `backend.probe_query`；`_cosine_match` 遇到维度不符时给出明确报错 |
| `prereg.py` | `inheritance_structure_reasons` 同时支持单来源（r14）与多来源（r15）两种格式：每个源必须是另一个已登记身份且带 64 位十六进制 SHA；每格的源必须出现在 sources 里；多来源节不得另写单一来源；单来源节的格不得自带源 |
| `worker.py` | `inherited_cell` 按格解析源实验与源预登记 SHA；训练拒绝和评测绑定的逻辑沿用 P49，没有改动 |
| `test_s1_r15_registration.py` | 新增 15 项：切片宽度等于节点宽度、且不等于 hidden；写入切片等于 r14 的字面切片，arms.py 里不再有字面切片；切片型 few-shot 完成；r14 行为下报出明确错误；身份；多来源冻结且 r14 归档仍能通过校验；5 种多来源结构坏对照；单来源节拒绝按格写源；按格解析源；8 个继承格全部拒训、arm4 s0 放行；评测按各自的源绑定，换错源则拒绝 |
| 三个已有测试的假后端 | 补上 `probe_query`：这些假后端的编码已经在节点空间里，直接返回 `encode` 的结果 |
| `test_s1_r12/r13/r14_registration.py` | 只同步「当前身份 = r15」这一类断言；r14 测试里的未登记占位身份由 r15 改为 r16 |

## 3. 证据（`harness/`，输出在 `logs/`）

- **`equivalence_checks.py`**：在临时目录建 r14（`before/`）和 r15 两棵源码树。
  - r14 树上，切片型 few-shot 报 `ValueError`；r15 树上 completed。
  - arm2/3/4 seed 0 的真实 MLX 窗口探针损失，两棵树逐位相同（float hex 比较）。
- **`prereg_leaf_diff.py`**：r14→r15 白名单外差异 0；七个科学节与 effective_metadata 相等。
- **`entry_checks.py`**（12/12）：
  - CLI 检查：verify 为 completed、source_binding 通过、未批准；CLI train/eval 在副本根上以 `output_root_not_canonical` 拒绝。
  - worker 拒绝路径：未批准的 arm4 s0 训练被拒；arm4 s0 评测被拒（`eval_binding_unavailable`）。
  - 继承格：副本日志里把 r14 批准行替换成 r15 后，8 个继承格全部 `inherited_cell_not_trainable`；只读绑定 8/8 绑到登记的 run，arm4 s0 被拒。
  - 真实评测：在副本上评测 arm2 s0（r13 来源）、arm3 s1（r14）、arm4 s2（r14），全部 completed。这一步和正式评测一样以读写方式打开副本台账，所以副本台账会变，作为观察值记录。
  - 台账与日志：生产台账没有变化；仓库 RESEARCH_LOG 运行前后 SHA 一致。

## 4. 已知限制

- 继承格评测绑定的是源实验的 run；r15 里只有 arm4 s0 的训练和全部评测是新的。
- arm1 D 已在 r14 完成过一次；按登记，r15 再跑一次（11 s）。

## 5. 复跑

```
env -u PYTHONPATH .venv/bin/python -m pytest tests/v9/experiments -q -p no:cacheprovider
env -u PYTHONPATH .venv/bin/python reports/V9-P9/r15/harness/equivalence_checks.py
env -u PYTHONPATH .venv/bin/python reports/V9-P9/r15/harness/prereg_leaf_diff.py
env -u PYTHONPATH .venv/bin/python reports/V9-P9/r15/harness/entry_checks.py
```

复核者请先把 harness 复制到 `reports/V9-P54/<你的ID>/`，并把其中的 `OUT` 改到那里再运行（COORDINATION 规则 8）。
