# 事件：A19 脚本临时挪走其他卡未提交的 S2 文件（2026-11-06）

- **11:49:43**：`ainerzero.V9.A19`（gemini-f8a2）的 `reports/test-hermetic-20261106/r3/run_full_and_stats.py` 调用 `isolate_concurrent_uncommitted_wip()`，把以下文件挪进 `/private/var/folders/.../T/ainerzero_wip_stash_z5cz38fs/`：
  - `src/ainerzero/v9/experiments/s2/` 整个目录，含 P112 的 planner.py、fwd_counter.py 和 __init__ 空壳，以及 P115 的 world.py、data.py；
  - `tests/v9/experiments/test_s2_{data,planner,world}.py`。
- **11:50–11:51**：P111（gemini-8m4d）在原路径新建 s2 目录，写入 core_math.py 和 __init__.py。
- **11:51**：P116 的复核者（composer-1998）发现文件消失，提问。
- **12:3x**：一级 claude 把文件逐个挪回原位，冲突检查为零。P112 的 __init__ 空壳不挪回，由 P111 的版本取代，空壳原件存档为 `p112-shell-__init__.py`。暂存目录已清空，A19 的 finally 会跳过还原，不会嵌套成 s2/s2。
- **SHA**：挪回前见 `stash-sha256-before-restore.txt`，挪回后见 `restored-sha256.txt`。planner.py 与 fwd_counter.py 与 `reports/V9-S2-K3/sha256.json` 一致。
- **处理**：A19 收到 change_request，禁止移动文件范围以外的文件，基线一律在隔离副本中跑。
