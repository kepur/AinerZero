# A18 合并复核：A17 r2 + A19 r3（E1/S1 测试封闭）

- **复核者：** 一级 claude（非作者；A17/A19 作者为 gemini-f8a2）
- **时间：** 2026-11-07
- **授权：** 用户 11-07「你直接一级二级全做」
- **结论：** RECOMMEND_ACCEPT（A17 r2 与 A19 r3 都通过），另开一张后续卡补三处缺口，见第五节。

## 一、范围
- A17/A19 的改动只涉及 tests/：
  - `conftest.py`
  - `probe_replay.py`（加了 `-B`）
  - `test_s1_r7_host_anchor.py`
  - `test_s1_r7_lock.py`
  - 新增的 `test_hermetic_guards.py`
- 工作树里 `src/ainerzero/cli.py` 新增的 56 行属于 S2 的 `s2-phase1` 子命令接线（S2 卡），不是 A17 的改动。
- conftest 的 NATIVE_MODULES 新增 2 个 S2 MLX 原生测试模块。两者都在模块级导入 mlx，排除出默认套件是正当的，不算消红。

## 二、没有偷偷消红
- 两条 S1 用例改为在 tmp 暂存树上跑：账本复制品、伪造的 host root、伪造的锁目录。
- 断言内容没有削弱：
  - 账本 SHA 前后相等；
  - 锁 busy 时返回 3、释放后返回 0。
- r3 的节点清单比 r2 只多 1 条（安装断言），没有删除，也没有新增 skip。

## 三、一级自做变异
隔离副本：`$S/a18iso-*`；import 解析到副本的 src 与 tests；每处变异后按字节还原，并核对 SHA。脚本见 `mut.py`。

| 变异 | 结果 |
|---|---|
| 基线 | 5 passed |
| X1：fd 不解析（`guard_resolve_path` 对 int 直接返回 None） | 变红 |
| X2：`file:` URI 不解析 | 变红 |
| X3：快照模式去掉 `v9/**/control.sqlite3*` 与 `s1/**/*.sqlite3*` | 变红 |
| X4：会话级强制失效（fixture 的 `assert not diff` 改恒真） | **存活**，5 passed |
| X5：守卫恒不激活（`_hermetic_guards_active=False`） | 变红 |
| 还原后 | 5 passed |

## 四、零写入
- 一级本人在实盘前台跑全量（SIG_DFL+execv）：**3621 passed, 6 deselected**，用时 296.8 s。
- 跑之前和之后各对实盘 artifacts 拍一次快照：
  - 共 84,247 个条目，含目录本身与软链；
  - 记录 lstat 的 mtime_ns、ctime_ns、size、ino；
  - 前后差异为 **0**。
- utime 还原（R20261106-A17-live-shm-touch）之后，实盘有没有再被改动：
  - S1 的 `-shm` 的 ctime 为 11-06 09:54:32，`-wal` 为 09:53:34，`locks/m0-worker.lock` 为 09:39:26，都在 A17 r1 期间。三者的 mtime 都没变，说明 r1 还对 `-wal` 和锁文件做过元数据操作（ctime 变了，mtime 没变）。事件记录里只写了 `-shm`，这里补记。
  - 09:55 之后，artifacts 里 ctime 有变化的只有 3 项：
    - `v9/e1/phase2/`：目录本身，11-06 11:32:18；
    - `reports/E24-mixed/review/mutants2/work/artifacts`：23:14:52，一级清理软链环；
    - `reports/E24-mixed/review/mutants3/work/artifacts`：23:14:52，同上。
- **新发现（另行登记）：** 11-06 11:32:18，`v9/e1/phase2/` 的目录项有变化。
  - E1 账本是 WAL 模式，目前没有 `-wal`/`-shm`。由此判断，当时有进程以读写方式打开过已收口的 E1 账本，关闭时删掉了附属文件。
  - 主库字节与 r4 基线一致，SHA 为 `5990ed6c…`。e1 目录下其他文件的 ctime 都没变。
  - 同一分钟内有两个活动，无法确定是哪一个：
    - A19 r3 的 `run_mutations.py` 写于 11:32:08；
    - P109-inventory 写于 11:32:31–11:33:23，它当时在通读 E1 的 worker/commands。
  - 这次打开发生在受守卫的 pytest 会话之外，或发生在子进程里，所以没有被拦住。

## 五、缺口（不阻塞验收，开后续卡）
1. **X4 存活：** 会话级强制（fixture 的断言，以及 sessionfinish 里置 exitstatus）没有任何测试覆盖。另外，`test_hermetic_guards.py` 的文档串声称做了「子进程对抗验证」，文件里并没有这样的用例。
2. **子进程不受函数级守卫保护：** 测试启动的子 Python 不会加载 conftest。会话 stat 快照只能发现改动，发现不了只读打开或拿锁。只读打开 WAL 库会产生 `-shm`，因此只有在 `-shm` 原先不存在时才会被发现。
3. `test_the_real_ledger_is_untouched_by_the_anchor_checks` 现在要 `copyfile` 实盘 S1 账本（只读），所以依赖实盘账本存在。可以接受，但应在用例内注明。
4. `os.environ['PYTHONDONTWRITEBYTECODE']='1'` 全局设置：子进程继承这个变量，正是想要的效果（不让 `__pycache__` 落进暂存树或 artifacts）；全量全绿，可以接受。
