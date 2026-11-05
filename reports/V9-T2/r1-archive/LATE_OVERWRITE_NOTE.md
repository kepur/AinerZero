# F13：迟到覆盖记录（r2 起点）

一级裁定（任务卡）：`composer-a7k2` 登记结果与盘上被 `opencode-de3b` 迟到覆盖的文件都不作为交付；r2 以当前盘面为起点重建全部证据。

## 时间线（来自 V-V9-T2 / 接力台）
- 14:31:44 `opencode-de3b` 因 20 分钟无心跳被 stalled 收回
- 14:45:05 `composer-a7k2` claimed
- 14:51:31 `composer-a7k2` 交报告（登记 23 passed；`test_cache.py` 登记 SHA `6749d11a…`）
- 14:54:14 盘上 `tests/v9/teachers/test_cache.py` mtime（SHA `d091f1ef…`）
- 14:55:48 盘上 `reports/V9-T2/metrics.json` mtime（署名 opencode-de3b）
- 14:57:17 盘上 `reports/V9-T2/REPORT.md` mtime（署名 opencode-de3b）

## r2 认领时盘面 SHA（2026-10-20，composer-6091）
见同目录 `disk_sha256_at_r2_claim.txt`。
