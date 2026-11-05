# r5 时代身份文件（显式标旧，保留字节，不是当前 r6 身份）

本目录保存 `reports/V9-B1/r6-candidate/` 根下原先从 r5-candidate 复制来的两份身份文件：

- `SHA256SUMS.txt`：r5 时代清单，236 处夹具路径写 `reports/V9-B1/r5-candidate/...`，
  且把 `reports/V9-B1/check_skill_proposal.py` 记为 r5 哈希 `5b28818b...`、`REPORT.md` 记为 `e128141f...`。
- `check_result.json`：r5 时代 suite 结果（ef9a4bd1...），与 r6 当前 checker 身份不符。

2026-10-18 B8 复核发现这两份文件是 r5 时代产物；B7 第 6 棒按打回要求**显式标旧**并把它们原字节移入本目录
（未删除、未改写），随后由 r6 checker 在隔离 staging 重生成 r6 身份文件，覆盖根位置（新文件以排他创建落下）。
本目录文件不是当前候选身份，复核请以根目录新 `check_result.json` / `SHA256SUMS.txt` 为准。

原字节 sha256 见同目录 `SHA256SUMS-of-stale.txt`。

## 2026-10-18 B7 本轮勘误
- 根目录 `R6_SHA256SUMS.txt`（r5 时代聚合清单，236 处 r5-candidate 路径）已移入本目录并改名 `R6_SHA256SUMS.stale.txt`，显式标旧。
- 因 B9 输出路径守卫拒绝向候选目录自身写入输出证据，当前 r6 身份**不**写入根目录 `check_result.json`/`SHA256SUMS.txt`；当前身份以
  `_evidence-baton6/staging-run1/check_result.json`（sha256 4fb8d5c3…，inode 差异除外）与同目录 `SHA256SUMS.txt` 为准。
- 旧 `_identity-r5-stale/SHA256SUMS.txt` / `check_result.json` 仍为 r5 身份，仅作历史证据。
