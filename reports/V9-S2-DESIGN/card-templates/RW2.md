**非作者复核 S2 生产路径集成 W2。** 交回目录：`reports/V9-S2-W2/`；卡面见被复核卡。只读核对，变异一律在隔离副本里做。

## 要核
1. **范围**：只改了卡面列出的文件。用 git diff 与 `git status` 核对，并说明工作树里其他文件的来源。
2. **回退清零**：在改过的模块里 grep 以下写法，逐条判断缺数据时走向哪里（规矩：缺数据只能拒绝或报错）：
   - `or []`、`or {}`、`getattr(..., 默认值)`、`if ... is None else`、`default_`
   - `0.5`、`base_success_rate`、`preferred_`、`eval_episode`
3. **生产调用点**：从 `ainerzero.cli.main` 一路读到 runner，确认生产路径真的传了实测量、真的加载了检查点，而不是只有测试传了。
4. **亲手变异**：卡面坏对照里的每一项都在隔离副本里亲手复做一遍，另外自选 1 处。隔离副本复制 src、tests、pyproject.toml，并断言 import 解析到副本。每处变异都要变红；还原后核对 SHA。
5. **全量**：前台跑默认全量（SIG_DFL+execv），前后对实盘 artifacts 做 lstat 比对（mtime、ctime、size、ino），差异必须为 0。
6. **逐字抽查**：从交回报告里任取 3 处声明，与盘上内容逐字核对。

## 禁止
不改任何仓库文件，不运行 MLX，不跑生产 s2-phase1，不写 artifacts/，不提交，不推送。

## 交回 `reports/V9-S2-W2/review/`
REVIEW.md，结论只能是 RECOMMEND_ACCEPT 或 REJECT。REJECT 时要写明必改项。
