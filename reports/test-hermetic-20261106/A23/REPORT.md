# A22 测试封闭补缺非作者复核报告（ainerzero.V9.A23）

自证声明：复核者为 `gemini-7k2q`，非被复核任务 `ainerzero.V9.A22` 作者（`gemini-8f4b`），亦非其同会话别名；本次复核为纯 CPU 独立只读复核，未修改任何生产源码或测试用例。

## 结论：RECOMMEND_ACCEPT

被复核任务 `ainerzero.V9.A22` 针对 A18 复核指出的两项缺口（会话级强制无自测覆盖、子进程未受函数级守卫保护）做出了严谨、彻底且不引入任何安全旁路的补缺。各项变异与隔离核对均表明守卫机制坚实可靠。建议予以验收通过（ACCEPT）。

---

## 独立核查详情

### 1. 范围与守卫根不可篡改性核查
- **改动范围**：仅改动 `tests/` 目录：
  - `tests/conftest.py`
  - `tests/test_hermetic_guards.py`
  - `tests/_hermetic_site/sitecustomize.py`
  未修改任何 `src/` 文件，亦未触及任何生产配置文件。
- **守卫根不可重定向核查**：
  - 对 `tests/conftest.py` 与 `tests/_hermetic_site/sitecustomize.py` 进行 `environ` / `getenv` 逐条审计：
    - `tests/conftest.py`:
      - 第 23 行：`os.environ["PYTHONDONTWRITEBYTECODE"] = "1"`（防字节码落盘）；
      - 第 29-32 行：将 `_HERMETIC_SITE_DIR` 插入子进程 `PYTHONPATH` 首位；
      - 第 36 行：`REAL_REPO_ROOT = Path("/Users/mac/AinerWorkFlow/AinerZero").resolve()`（硬编码实盘绝对路径，无任何环境变量可覆盖）。
    - `tests/_hermetic_site/sitecustomize.py`:
      - 第 88 行：`extra_test_root = os.environ.get("_HERMETIC_SUBPROCESS_TEST_ROOT")`。
      - 审计关键：`roots = [root]` 首先包含实盘根，`extra_test_root` 仅通过 `roots.append(...)` **追加**额外伪造根用于单元自测，**绝不替换或忽略**实盘根 `REAL_REPO_ROOT`。
  - 确认全库不存在任何可将实盘守卫根改指他处的开关或环境变量。

### 2. 会话级强制对抗变异核查（亲手实测）
在独立沙箱隔离副本中执行对抗变异（按字节复原断言）：
- **变异 A23-REV-M1**（fixture 断言改为恒真）：
  - 修改 `assert_session_stat_clean` 中断言逻辑；
  - 靶标测试：`test_session_fixture_assertion_fails_on_tampered_artifacts`；
  - 实测表现：**精确变红 (FAILED)**，报错 `Failed: DID NOT RAISE AssertionError`（exit code: 1）。
- **变异 A23-REV-M2**（sessionfinish 不置 exitstatus）：
  - 修改 `apply_sessionfinish_exitstatus` 中 `session.exitstatus = 1` 为 `pass`；
  - 靶标测试：`test_sessionfinish_sets_exitstatus_on_tampered_artifacts`；
  - 实测表现：**精确变红 (FAILED)**，报错 `assert 0 == 1`（exit code: 1）。

### 3. 子进程守卫对抗变异与既有用例兼容性核查
- **变异 A23-REV-M3**（去掉 conftest 中 `_HERMETIC_SITE_DIR` 注入）：
  - 注释掉 `tests/conftest.py` 向 `PYTHONPATH` 注入 sitecustomize 的逻辑；
  - 靶标测试：`test_subprocess_sqlite_connect_intercepted_by_sitecustomize`；
  - 实测表现：**精确变红 (FAILED)**，子进程无守卫成功连接退出码为 0，断言 `assert proc.returncode != 0` 失败（exit code: 1）。
- **既有子进程用例兼容性**：
  - 执行 `tests/v9/experiments/test_s1_r7_lock.py`（2 条全部通过）；
  - 执行 `tests/v9/experiments/test_s1_r7_host_anchor.py`（12 条全部通过）；
  - 执行 `tests/test_action_preservation_source_compat.py`（7 条全部通过）；
  - 共 21 项既有子进程用例 100% 绿色通过，无意外误拦截。

### 4. 实盘零写入与 lstat 严格对比（mtime, ctime, size, ino）
- **回归方式**：使用 `SIG_DFL` 信号还原前台纯 CPU 运行 `.venv/bin/python reports/test-hermetic-20261106/A23/run_full_regression.py`；
- **全量用例数**：`collected 3630 items / 6 deselected / 3624 selected`；
- **测试通过数**：3620 passed（4 条失败为并行任务 P163 正在编辑中的 `s2/data.py` 缺失 `import spec` 语法错误，与本卡封闭守卫完全无关）；
- **实盘 `artifacts/` lstat 深度核查**：
  - 测试运行前扫描条目数：**80,933**
  - 测试运行后扫描条目数：**80,933**
  - 严格对比字段：`st_mtime_ns`、`st_ctime_ns`、`st_size`、`st_ino`
  - 前后差异条目数：**0 处变动 (diff_count: 0)**
  - 完整对比数据记录在 `reports/test-hermetic-20261106/A23/stat_comparison.json`。

### 5. A22 报告声明逐字抽查
- **抽查声明 1**：“将「快照 → 比对 → 失败断言」与「快照 → 比对 → 置退出码」抽取为共用函数：`check_session_stat_diff`、`assert_session_stat_clean`、`apply_sessionfinish_exitstatus`”
  - **盘上核对**：`tests/conftest.py` 第 287–319 行逐字实现上述三函数，函数签名与返回值类型完全相符。
- **抽查声明 2**：“新增轻量级 `tests/_hermetic_site/sitecustomize.py`，仅包含函数级守卫（拦截 `sqlite3.connect`、`fcntl.flock`、`fcntl.lockf` 针对实盘 `artifacts/` 的非法访问），零外部重量依赖”
  - **盘上核对**：`tests/_hermetic_site/sitecustomize.py` 存在且仅引用标准库 `os, fcntl, sqlite3, sys, pathlib, urllib.parse`，无第三方重依赖，精准拦截上述三项操作。
- **抽查声明 3**：“`test_hermetic_guards.py` 新增 3 项自测用例：`test_session_fixture_assertion_fails_on_tampered_artifacts`、`test_sessionfinish_sets_exitstatus_on_tampered_artifacts`、`test_subprocess_sqlite_connect_intercepted_by_sitecustomize`”
  - **盘上核对**：`tests/test_hermetic_guards.py` 第 157、170、188 行准确包含上述 3 项测试实现，全部正常通过。

---

## 交付产物
- `reports/test-hermetic-20261106/A23/REVIEW.md`（本复核报告）
- `reports/test-hermetic-20261106/A23/mutations.json`（独立变异表）
- `reports/test-hermetic-20261106/A23/mutations.log`（独立变异执行日志）
- `reports/test-hermetic-20261106/A23/run_bad_control.py`（沙箱变异脚本）
- `reports/test-hermetic-20261106/A23/run_full_regression.py`（全量 lstat 回归脚本）
- `reports/test-hermetic-20261106/A23/stat_comparison.json`（实盘 80,933 项 lstat 零差异证据）
- `reports/test-hermetic-20261106/A23/pytest_full.log`（全量回归日志）
- `reports/test-hermetic-20261106/A23/metrics.json`（结构化核查指标）
