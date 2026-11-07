# 任务执行报告：测试封闭补缺（ainerzero.V9.A22）

- **任务**：`ainerzero.V9.A22`【L2·测试】测试封闭补缺：会话级强制自测＋子进程守卫（A18 缺口 1、2）
- **执行者**：`gemini-8f4b`（二级执行层）
- **日期**：2026-11-07
- **主工作目录**：`/Users/mac/AinerWorkFlow/AinerZero`
- **运行模式**：纯 CPU（Zero MLX / Zero GPU），未改动 `src/`，未写入 `artifacts/`，未提交或推送

---

## 一、改动依据与解决的缺口

依据 `reports/test-hermetic-20261106/A18-tier1-review/REPORT.md` 第五节缺口 1、2：
1. **会话级强制无自测覆盖（X4 变异存活问题）**：此前 fixture 中的 `assert not diff` 与 `sessionfinish` 中置 `session.exitstatus = 1` 缺乏单元自测，变异后无用例变红；
2. **测试启动的 Python 子进程未受函数级守卫保护**：子进程不自动加载 `conftest.py`，若子进程打开受保护账本或拿锁，函数级守卫无法拦截；
3. **`test_hermetic_guards.py` 文档串失真**：文档串声称包含子进程对抗验证，实际用例中未实现。

---

## 二、改动内容

### 1. 会话级强制逻辑抽取与共用 (`tests/conftest.py`)
- 将「快照 → 比对 → 失败断言」与「快照 → 比对 → 置退出码」抽取为共用函数：
  - `check_session_stat_diff(before: dict, root: Path = REAL_REPO_ROOT) -> dict[str, str]`
  - `assert_session_stat_clean(before: dict, root: Path = REAL_REPO_ROOT) -> dict[str, str]`（供 `hermetic_artifacts_guard` 会话 fixture 使用并接受伪造根进行自测）
  - `apply_sessionfinish_exitstatus(session, before: dict, root: Path = REAL_REPO_ROOT) -> dict[str, str]`（供 `pytest_sessionfinish` 使用并接受伪造根进行自测）
- **严守安全原则**：生产守卫根仍然硬编码为 `REAL_REPO_ROOT`，未引入任何能将生产根重定向到别处的环境变量或全局开关。

### 2. 子进程函数级守卫注入 (`tests/_hermetic_site/sitecustomize.py`)
- 新增轻量级 `tests/_hermetic_site/sitecustomize.py`，仅包含函数级守卫（拦截 `sqlite3.connect`、`fcntl.flock`、`fcntl.lockf` 针对实盘 `artifacts/` 的非法访问），零外部重量依赖；
- 在 `tests/conftest.py` 启动阶段将 `_HERMETIC_SITE_DIR` 自动插入至 `PYTHONPATH` 首位，使得测试启动的所有原生 Python 子进程均在启动时自动装载守卫；
- 预留 `_HERMETIC_SUBPROCESS_TEST_ROOT` 仅用于隔离测试中模拟伪造根拦截。

### 3. 测试增强与文档串修正 (`tests/test_hermetic_guards.py`)
- 修正顶部文档串，准确客观反映实际覆盖的 6 大领域；
- 采用直接路径规范导入根 `conftest`，避免受子目录同名 conftest 干扰；
- 新增 3 项自测用例：
  1. `test_session_fixture_assertion_fails_on_tampered_artifacts`：伪造根文件篡改时断言失败（拦截 A22-M1）；
  2. `test_sessionfinish_sets_exitstatus_on_tampered_artifacts`：伪造根文件篡改时置 `exitstatus = 1`（拦截 A22-M2）；
  3. `test_subprocess_sqlite_connect_intercepted_by_sitecustomize`：子进程对伪造受保护路径调用 `sqlite3.connect` 时被精准拦截并抛出 `RuntimeError: Hermetic test guard violation`（拦截 A22-M3）。

### 4. 既有子进程用例兼容性验证
- 验证 `test_s1_r7_lock.py`、`test_s1_r7_host_anchor.py` 全部 14 项用例通过；
- 验证基于 `probe_replay` 的子进程重放用例（如 `test_action_preservation_source_compat.py` 等 7 项用例）全部通过。

---

## 三、坏对照变异实测（Bad Control）

在隔离沙箱 `/tmp/ainerzero_a22_bad_control`（独立复制 `src/`、`tests/`、`pyproject.toml`，并核验 import 解析到沙箱）中逐项执行坏对照变异：

| 变异编号 | 变异操作 | 靶标测试 | 变异表现 | 逐字节 SHA 还原 |
| :--- | :--- | :--- | :--- | :--- |
| **A22-M1** | 将 `assert_session_stat_clean` 中 `assert not diff` 改为 `assert True` | `test_session_fixture_assertion_fails_on_tampered_artifacts` | **变红 (FAILED)**：`Failed: DID NOT RAISE AssertionError` | 100% 匹配 |
| **A22-M2** | 将 `apply_sessionfinish_exitstatus` 中 `session.exitstatus = 1` 注释掉 | `test_sessionfinish_sets_exitstatus_on_tampered_artifacts` | **变红 (FAILED)**：`assert 0 == 1` | 100% 匹配 |
| **A22-M3** | 在 `conftest.py` 中注释掉将 `_HERMETIC_SITE_DIR` 注入 `PYTHONPATH` 的逻辑 | `test_subprocess_sqlite_connect_intercepted_by_sitecustomize` | **变红 (FAILED)**：子进程连接成功退出码为 0，`assert 0 != 0` 失败 | 100% 匹配 |

变异日志详见 `reports/test-hermetic-20261106/A22/mutations.log`，变异结构化数据见 `reports/test-hermetic-20261106/A22/mutations.json`。

---

## 四、全量纯 CPU 回归与实盘 ctime 零差异核实

- **执行方式**：显式设置 `SIG_DFL` 信号还原，纯 CPU 执行 `.venv/bin/python -m pytest`；
- **全量用例数**：`collected 3630 items / 6 deselected / 3624 selected`（在基线 3621 条基础上新增 3 条有效自测）；
- **执行结果**：**3624 passed, 6 deselected, 0 failed**，耗时 298.40s；
- **实盘 `artifacts/` 保护（含 `ctime` 严格核查）**：
  - 测试运行前 `os.lstat` 扫描条目数（含所有目录与软链）：**80,933**
  - 测试运行后 `os.lstat` 扫描条目数（含所有目录与软链）：**80,933**
  - 校验维度：`mtime_ns`、`ctime_ns`、`size`、`inode`
  - 前后变动条目数：**0 处变动 (diff_count: 0)**
  - 详细数据见 `reports/test-hermetic-20261106/A22/stat_comparison.json`。

---

## 五、交付物清单

- `reports/test-hermetic-20261106/A22/REPORT.md`（本报告）
- `reports/test-hermetic-20261106/A22/diff`（源码差异补丁）
- `reports/test-hermetic-20261106/A22/mutations.json`（变异表）
- `reports/test-hermetic-20261106/A22/mutations.log`（变异执行日志）
- `reports/test-hermetic-20261106/A22/stat_comparison.json`（实盘前后 stat 对比，含 ctime）
- `reports/test-hermetic-20261106/A22/pytest_full.log`（全量回归日志）
- `reports/test-hermetic-20261106/A22/metrics.json`（结构化指标）
