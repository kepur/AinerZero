# Teachers and Cache — v2.1 增量（admission_bindings）

本文件是 `TEACHERS_AND_CACHE.md` r3 的 T2 落地增量，不取代 r3 全文。

## 变更摘要

- **blob / entry 记录形状**：仍为 `az.v9.teacher_cache.v2`（`contracts/v9/teacher_cache.v2.schema.json`）。
- **可信上下文**：`contracts/v9/teacher_cache.v2_1.schema.json` 在 `$defs/trusted_context` 上增加可选字段 `admission_bindings`。
- **语义（一级裁定 F11/F12）**：
  - 盘上 `teacher_license` / `entry.license` / `reproducibility` 是不可信提示；
  - `train_eligible` 对这三项只读 `admission_bindings`；缺失 → 拒训；
  - 绑定存在且与盘上不一致 → `store_problems` 含 `admission_*_mismatch`。

## admission_bindings 项

| 字段 | 含义 |
|---|---|
| `entry_id` / `cache_key` | 绑定目标 |
| `entry_license` | 可信条目许可（含 `scope.train`） |
| `teacher_license` | 可信教师许可 |
| `reproducibility` | 可信可复现等级 |

## 实现入口

`src/ainerzero/v9/teachers/cache.py`：`store_problems` / `train_eligible`。
