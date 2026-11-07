4. **测试真伪**：确认测试调用的是被测函数，没有在测试里重写一遍实现，也没有拿常数去比常数。检查各个门限是怎么来的，是不是调到刚好能通过。
5. **自己另做至少 3 处变异**，要在作者的变异表之外。在隔离副本里做：复制 `src`、`tests`、`pyproject.toml`，并断言 import 解析到的是副本。每处跑完按字节还原。逐处报告是变红还是存活；存活的要判断是测试漏洞还是死代码。
6. **纯 CPU**：用 `-I` 子进程导入 s2 包后，`mlx` 不应出现在 `sys.modules` 里。前台跑一次默认全量（SIG_DFL+execv），报告计数。不得加 `--native-mlx`。

## 结论
写在 `{REP}/review/REVIEW.md`，给出以下三者之一：`RECOMMEND_ACCEPT`、`RECOMMEND_ACCEPT_SCOPED`（写明范围）、`RECOMMEND_REJECT`（列出阻断项）。另附 `metrics.json`。不改源码，也不改测试。
