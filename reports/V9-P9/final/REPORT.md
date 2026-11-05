# ainerzero.V9.P59 报告：S1 final——封存数据生成、一次性评测入口、冻结

- **作者**：一级 `claude`。**需要非作者复核**：`ainerzero.V9.P60`（gemini）。
- **依据**：RESEARCH_LOG `## R20261028-S1-phase1-final-eval`（用户 10-28「批准 final 评测」；设计在生成任何数据之前就已冻结）。
- **final 尚未读取**：封存目录旁没有 `READ_ONCE` 标记；复核与入口检查全程没有打开真实的 final 内容。
- **生产台账**：开工与收尾都是 `7244149c2bb87096e0dacf75f7151f15c0253f4bd367b23d0ff456090a2d5f53`，只做 shasum。

## 1. 结论（≤10 行）

1. **封存数据**：final 分区共 200 个世界（每族 50 个）、200 个 episode、950 个观测包，生成用时 3.9 s。
   - 与 train/dev 的世界指纹、scene id 均不重叠（生成器内部检查）。
   - 封存于 `artifacts/v9/s1/final-sealed/057ea6c20f7ec9cadad2e774b21f4b561407cc324114ae8c0e17fc57f82ef887/`，文件只读，附 `SEALED.json`。
   - 临时副本已删除；生成器只输出计数，内容不打印。
2. **只读一次**：
   - `open_sealed_final_once` 先核对封存清单，再以排他方式创建 `<digest>.READ_ONCE.json`，最后才发出令牌；不持有令牌的加载器读不到 `final`。
   - `final-eval` 模式在同一个进程里评完 arm1 D 与九格，第二次调用被拒。
3. **端到端预演**（隔离副本，用 development 改标为 final 的夹具，没有碰真实封存）：
   - 十格全部 completed，用时 45 s；第二次调用以 `final_already_read` 拒绝。
   - 九格的 NLL 与 r15 的 development 结果**逐位相同**，说明 final 视图走的是同一套评测路径。
4. **冻结**：`artifacts/v9/s1/phase1/final/pre_registration.json`。
   - document SHA：`ad21071ec11d3006b9d31e9ac3c0e9a48aa6a94c2efd80807549ca1681e9b60c`
   - file SHA：`e93935e093883e8b85713c7de6efb92d814ac1ecc16672d94e2208e930a2974c`
5. **r15→final 逐叶差异**：白名单外为 0。七个科学节与 effective_metadata 全部相等；变化的来源文件正好是本卡改动的 8 个，其中 `awz_export.py` 没有改，train/dev 的生成逐位不变。
6. **入口检查 6/6 通过**；**测试**：`tests/v9` 994 项通过，失败 3 项为已知问题；新增 final 测试 16 项全部通过。

## 2. 改动

| 文件 | 改动 |
|---|---|
| `awz_final_export.py`（新增） | 只生成 final，命名空间 3。复用 `awz_export` 的确定性辅助函数。拒绝向非空目录写入；拒绝与参考 train/dev 重合的世界指纹或 scene id；只打印计数 |
| `data.py` | `seal_final_dataset`、`verify_sealed_final`（只算 SHA，不读内容行）、`open_sealed_final_once`（排他创建标记后才发令牌）、`FinalReadToken`、`FinalView`。`require_partition`、`load_training_episodes`、`load_truth_view` 只有在持有已发令牌、且目录与令牌一致时才接受 `final` |
| `final_eval.py`（新增） | `section_reasons` 检查 final 节的结构；`preconditions` 里全是只用 CPU、不写任何东西的检查：批准、来源绑定、数据集身份、封存完整且未读、计数一致、final 实验里尚无 run、arm1 身份、九格绑定。`read_once_and_score` 负责创建标记、读取、核对调用预算、逐格评测（单格出错只记录，不重读） |
| `worker.py` | 新增 `final-eval` 模式并加入有界模式：先过全部前置检查，再开一个台账 run，最后读一次并评测。`_evaluate_arm` 新增 `eval_view`，默认仍读 development |
| `commands.py`、`cli.py` | `mode_final_eval`：预算为登记的 1800 s，只能收紧；共享锁与中央台账照旧 |
| `prereg.py` | `validate` 增加 final 节检查：只有 final 文档可以带、而且必须带 |
| `spec.py` | `FINAL_EXPERIMENT_ID`；`FINAL_INHERITANCE`（三个来源，九格）；`FINAL_DATA_PLAN`；封存根目录；预算。当前训练身份保持 r15 |
| `test_s1_final_eval.py`（新增） | 16 项，覆盖封存与只读、篡改、拒绝覆盖、无令牌或伪造令牌、二次读取、令牌不通用、train/dev 路径仍拒绝 final、final 节结构与四类篡改、只有 final 文档可带该节、入口拒绝不写台账也不创建标记、九格拒训 |
| `test_s1_r14/r15_registration.py` | 只同步已登记身份元组：末尾加上 final |

## 3. 证据

- `logs/generate-final.json`：计数；`logs/sealed-record.json`：摘要与文件 SHA。
- `logs/dryrun.json`：端到端预演；`logs/entry-checks.json`：入口检查（全程装有读取绊线）。
- `logs/prereg-leaf-diff.json`；`evidence/diff-*.patch`。前值在 `before/`。

## 4. 已知限制

- 「只读一次」防的是本仓库内的流程误读；同一个系统账户下恶意读文件不在防护范围内，与 AWZ 封存的威胁模型一致。
- arm1 D 只评 C0 固定批次，不读 S1 数据，所以它在 final 上的结果与 development 相同。
- 如果真实 final 的窗口数超过登记的评测调用预算，这次读取会被用掉、但不出任何结果。实际 final 的 episode 数和包数与 development 相同，预计 550 个窗口，与登记值相符。
