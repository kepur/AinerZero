# E1/S1 测试封闭性补丁报告（V9.A19 r3，2026-11-06）

## 一、执行摘要（30 行内）
- **任务目标**：针对一级 11-06 对 A17 r2 预检指出的两项核心缺陷完成闭环：1) 补齐守卫全局安装断言；2) 坏对照变异直接修改隔离副本中的真 `tests/conftest.py`。
- **守卫安装断言**：在 `tests/test_hermetic_guards.py` 新增 `test_hermetic_guards_installed_globally`，断言 `sqlite3.connect`、`fcntl.flock`、`fcntl.lockf` 以及 `import sqlite3 as s; s.connect` 均全局安装为 `conftest` 真实守卫函数。守卫自测增至 5 条全绿。
- **真守卫坏对照（隔离副本）**：交付 `reports/test-hermetic-20261106/r3/run_mutations.py`。在临时目录完整克隆 `src/`、`tests/`、`pyproject.toml`，断言 import 解析严格收敛至副本，**直接在副本中就地修改真实 `tests/conftest.py`** 实施 4 处变异：
  1. M1 连接检查失效（`make_guarded_connect` 检查旁路）：变红（`RuntimeError: Hermetic test guard violation`）。
  2. M2 flock 检查失效（`make_guarded_flock` 检查旁路）：变红（`RuntimeError: Hermetic test guard violation`）。
  3. M3 快照漏掉 `-shm`（`guard_snapshot` 跳过 `-shm`）：变红（`AssertionError: Session guard missed -shm`）。
  4. M4 全局安装被删（`_install_hermetic_function_guards` 旁路/删除）：变红（`AssertionError: assert <built-in connect> is <guarded_connect>`）。
- **SHA 校验与按字节还原**：每处变异执行后按原字节严格写回并完成 SHA-256 校验对比，还原后 baseline 保持 5 passed 全绿。
- **实盘零触碰与零差异**：变异只跑守卫自测（针对 tmpdir 下伪造根）。全量套件运行与变异两段前后对实盘 `artifacts/` 80,851 个条目进行 stat（mtime_ns, size, inode）对比，**0 新增、0 删除、0 修改（-shm/-wal 变动为 0）**。严禁且未调用 utime 或任何元数据还原手段。
- **全量计数**：纯 CPU 默认套件前台运行（SIG_DFL + execv）：**3436 passed, 6 deselected**（耗时 254.74s）。节点清单较 r2 精确增加 1 项新增安装断言自测。

---

## 二、一级预检问题与整改对照

| 一级 11-06 预检结论 | r2 缺陷现象 | r3 修复与闭环措施 | 验证结果 |
| :--- | :--- | :--- | :--- |
| **Mc_not_installed 存活** | 删去 `_install_hermetic_function_guards()` 安装逻辑后，自测 4 项仍全绿，无测试检验真实猴子补丁。 | 在 `tests/test_hermetic_guards.py` 增加 `test_hermetic_guards_installed_globally`，检验全局模块引用。 | 全局安装被删时自测立即变红（M4，`AssertionError`）。 |
| **变异未改真守卫** | `run_mutations.py` 脚本内部单独重写了一份精简守卫，未测试 `tests/conftest.py` 源码。 | 重写 `r3/run_mutations.py`，完整复制隔离副本并在副本内**直接按字符串改写真实 `tests/conftest.py`**。 | 4 处变异全部直接作用于真实 `conftest.py`，全数变红。 |
| **变异覆盖不全** | 缺少 flock 检查失效变异。 | 在副本内针对 `make_guarded_flock` 实施检查失效变异（M2）。 | 变红（`RuntimeError` 拦截断言失败）。 |
| **实盘零触碰与不改元数据** | 保证两段前后实盘无变化，不用 utime。 | 全量与变异双段前后做全树 80,851 项 stat 对比，自测全部使用伪造根。 | 0 新增、0 删除、0 修改；零 utime。 |

---

## 三、4 处真守卫变异详细结果（隔离副本）

变异测试由 `reports/test-hermetic-20261106/r3/run_mutations.py` 驱动：
1. **隔离环境断言**：
   - 副本目录：`/var/folders/zv/vypfm1y977x338zzyccqx3br0000gn/T/hermetic-r3-iso-*/replica`
   - Import 验证：`assert str(conftest.__file__).startswith(str(replica_dir))` 通过。
   - `tests/conftest.py` SHA-256：`4910298bc5bcfa6c92d31e83ca5e46aceb0c0c3d2a940e2571f28328b7235a12`
2. **变异执行矩阵**：
   - **M1 (连接检查失效)**：将 `make_guarded_connect` 内 `check_hermetic_access` 替换为 `pass`。
     - 退出码：1（变红）。
     - 捕获异常：`DID NOT RAISE <class 'RuntimeError'>`。
     - 还原校验：SHA 完全一致。
   - **M2 (flock 检查失效)**：将 `make_guarded_flock` 内 `check_hermetic_access` 替换为 `pass`。
     - 退出码：1（变红）。
     - 捕获异常：`DID NOT RAISE <class 'RuntimeError'>`。
     - 还原校验：SHA 完全一致。
   - **M3 (快照漏掉 -shm)**：在 `guard_snapshot` 循环中注入 `if p.endswith("-shm"): continue`。
     - 退出码：1（变红）。
     - 捕获异常：`AssertionError: Session guard missed -shm: {}`。
     - 还原校验：SHA 完全一致。
   - **M4 (全局安装被删)**：将 `_install_hermetic_function_guards` 函数体替换为 `pass`。
     - 退出码：1（变红）。
     - 捕获异常：`AssertionError: assert <built-in function connect> is <function make_guarded_connect...>`。
     - 还原校验：SHA 完全一致。
3. **变异阶段实盘对比**：
   - 前后实盘条目数：80,851
   - 变异阶段实盘差异数：0

---

## 四、全量纯 CPU 回归与计数

- **执行方式**：前台 `signal.signal(signal.SIGINT, signal.SIG_DFL)` 恢复信号默认行为，并通过 `relay exec` 进行墙钟与心跳监督。
- **全量结果**：`3436 passed, 6 deselected in 254.74s`（通过率 100%）。
- **节点变化分析**：
  - r2 收集节点：3441 items（3435 passed, 6 deselected）
  - r3 收集节点：3442 items（3436 passed, 6 deselected）
  - 节点清单比对：差异精确为 1 项：`+ tests/test_hermetic_guards.py::test_hermetic_guards_installed_globally`。

---

## 五、实盘 artifacts 审计结论

- **覆盖范围**：实盘 `/Users/mac/AinerWorkFlow/AinerZero/artifacts/` 及其子目录全部 80,851 项。
- **记录属性**：`(st_mtime_ns, st_size, st_ino)`。
- **全流程差异统计**：
  - 全量回归前后：0 新增、0 删除、0 修改。
  - 变异脚本前后：0 新增、0 删除、0 修改。
  - 端到端全流程（`stat_comparison.json`）：**0 差异**，`-shm` / `-wal` 变动数 **0**。
- **元数据还原策略**：零调用 `os.utime`，零实盘回滚操作，全凭封闭性守卫保证零写入。

---

## 六、交付文件清单（`reports/test-hermetic-20261106/r3/`）

- `REPORT.md` / `报告.md`：本报告。
- `run_mutations.py`：隔离副本直接修改真实 `conftest.py` 并做 SHA 按字节还原的坏对照验证脚本。
- `mutation_log.txt`：4 处变异与还原执行日志。
- `mutation_summary.json`：变异结果机器可读汇总。
- `artifacts_stat_before.json` / `artifacts_stat_after.json`：实盘 80,851 项 stat 记录。
- `stat_comparison.json`：实盘零差异对比报告。
- `nodes_before.txt` / `nodes_after.txt`：全量用例节点清单。
- `pytest_full.log`：默认纯 CPU 套件全量执行完整日志。
- `git_diff.patch`：包含 `tests/test_hermetic_guards.py` 与 `tests/conftest.py` 改动的补丁文件。
- `metrics.json` / `指标.json`：符合任务规范的最终指标 JSON。
