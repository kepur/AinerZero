# r1 归档说明（ainerzero.V9.P9 r1，被 V9.P10 打回）

本目录是 r1（执行者 `deepseek-flash-a7k2`，2026-10-21 11:49–11:51）的原样产物，**未改写**。保留它是因为 r1 的 document SHA 被 V9.P10 复核引用，且 r2 的冻结预算以 r1 的冒烟实测为测量记录（`smoke_metrics.json`，sha256 `b4e7d1218b29652c188425ec6d1def2fe49d8fd1a22e7192d01b705ae4b11ce8`）。

| 文件 | 说明 |
|---|---|
| `pre_registration.json` + `.sha256` | r1 冻结预登记，document SHA `32c30f5005a438f759e14641f5ea77b635eb4020af7fa9ba823b7ad05bb74de6` |
| `draft_preregistration.json` | r1 草稿 |
| `smoke_metrics.json` / `smoke_report.json` | r1 无更新冒烟实测（**r2 的预算测量记录**） |
| `dataset/` | r1 数据集（digest `8234f2f3…ad26`，与 artifacts 下同名目录内容相同；notice #297 之后数据集正式位置在 `artifacts/v9/s1/datasets/`） |
| `control.sqlite3` | r1 卡片本地 RunStore 账本 |
| `evidence/` | r1 的拒绝证据（资源门/锁/预算/未批准 train） |
| `tests-s1.xml` / `metrics.json` / `data_report.json` / `verify_report.json` / `REPORT.md` / `SHA256SUMS.txt` | r1 交付物 |

r2 的修复项（F1–F4、notice #297）与新旧 document SHA 对照见 `../r2/REPORT.md`。
