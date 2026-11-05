# 提交记录（2026-11-05 UTC）

起点 `296589c`。每批提交前都由 `tooling/stage_batch.py` 完成三件事：

1. 按 `manifests/<批>.tsv` 复核盘上每个文件的 SHA256，与隔离验证时一致；
2. 精确暂存（`--literal-pathspecs`），`cli.py` 用分段 blob；
3. 断言暂存集合与清单相同。

随后人工看过 diff 再提交。未推送，未改写历史。

| # | 提交 | 批 | 路径数 | 暂存状态 |
|---|---|---|---:|---|
| 1 | `54ebf62` | b1_contract | 290 | A 286 / M 4（geometry r2） |
| 2 | `393af1a` | b2_cmfl | 10 | A 10 |
| 3 | `896576f` | b3_e1code | 86 | A 85 / M 1（cli.py E1 段） |
| 4 | `cfdc754` | b4_s1code | 75 | A 74 / M 1（cli.py E1+S1 段） |
| 5 | `6f59509` | b5_teachers | 244 | A 242 / M 2（cli.py 定稿、TEACHERS_AND_CACHE.md） |
| 6 | `cac029c` | r1_b | 4,075 | A 4,075 |
| 7 | `5b74d32` | r2_ga | 338 | A 338 |
| 8 | `3e3af71` | r3_registry | 97 | A 95 / M 2（登记表 28 → 96 条，旧 id 全保留） |
| 9 | `b9f5aa5` | r4_s1 | 2,314 | A 2,314 |
| 10 | `b039404` | r5_e1 | 1,954 | A 1,954 |
| 11 | `bead6cc` | r6_teachers | 3,523 | A 3,523 |
| 12 | `52f15b8` | r7_misc | 32 | A 30 / M 2（CLAUDE.md、COORDINATION.md） |
| 13 | 本提交 | 收尾 | — | 本报告目录、`.gitignore` 补充、RESEARCH_LOG 记录 |

## 端到端核对

`tooling/compare_head_tree.py`：`52f15b8` 的每个路径与隔离验证用的 `tree_final` 比对，结果见 `logs/compare_head_vs_tree_final.json`。

- 17,154 个文件的 blob 哈希全部一致，0 缺失；
- 265 个早期提交遗留的符号链接，目标全部一致；
- `tree_final` 中多出的 47 个文件都是测试子进程生成的 `__pycache__`。

结论：已提交内容就是 PLAN.md §3 中跑过测试的那棵树。
