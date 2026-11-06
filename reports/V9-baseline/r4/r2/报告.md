# A2 基线清单 r4 终报（第 2 轮修复，2026-11-06）

- **违规情况**：无违规。核实 r3 红项：N=8,057 项全为 10-20 后合法新增，M=0（零内容篡改），D=0（零文件缺失），无任何违规被吸收。
- **F1 覆盖漏洞修法**：选用方案 (a)，直接将 `artifacts/v9/e1/phase2/datasets/{raw,evaluator,student}` 共 7,600 个数据文件以字节 SHA256 钉选，归入新类别 `dataset.e1`，彻底杜绝数据篡改隐患。
- **清单统计与处置**：
  - 钉选：8,519 文件 / 3,583,358,485 字节（包含原 919 钉选项 + 7,600 E1 数据项）；
  - 排除：101（.DS_Store 95、locks 6）；瞬态：8（-wal/-shm）；易变：312；范围外：4,284；未分类：0；策略违规：0。
  - 清单摘要：`f9ec03cb42dbf1aa16e64e8005b60f88a166562506889540077a3675cc6de7a9`，双次构建完全确定（逐字节相同）。
- **核验与对抗自测（26/26 全部通过）**：
  - `verify`：8519/8519 项逐字节匹配，策略规则 59 条全部通过，判定 `ok`。
  - `selftest`：21 注入全部抓获（变红），5 对照全绿。新增 r2 两例：
    1. 改动 `evaluator/P/development/*.json` 1 字节 -> `r2_e1_evaluator_byte_flip` 变红；
    2. 删除 `student/S/train/*.json` 1 文件 -> `r2_e1_student_file_deleted` 变红。
- **实盘零写入**：构建、核验、自测全流程前后对 `artifacts/` 共 84,248 项做 stat/SHA 比对，零变动（`stat_before.json` 与 `stat_after.json` 逐字节相同）。
- **脚本与清单 SHA256**：
  - r1 脚本：`097090d974f8c111c36e7e1460e3e2b230caf056454cb9b2bda8d34a6ae3aed1`
  - r2 脚本：`5bb98a91eefd384dd6fa3f422f211d6af645eb0536c8a5c41ea149bed4ce4ddc`
  - r2 清单：`04186dc46978a5577cdc3a0e7d07f1db61ce23dccf563e83de9754c7b6a05e00`
