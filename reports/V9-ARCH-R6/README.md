# 架构 r6 候选稿（证据回写修订）

- **状态：候选稿，未采纳。** 现行基线仍是 `V9-r5-20261016`；仓库根的 `ARCHITECTURE_V9.md`、`ARCHITECTURE_BASELINE.md`、`docs/architecture/baseline.v1.json` 都没有改动。
- **作者：** 一级 claude，2026-11-17，依据用户当日指示「起草 r6」。
- **下一步：** 两张非作者复核卡，之后由用户决定是否采纳。
  - `ainerzero.V9.A24`：二级，数字与出处逐条核对，纯 CPU；
  - `ainerzero.V9.A25`：一级，设计审议。
  - claude 及同会话别名不得领取。

## 文件

| 文件 | 内容 |
|---|---|
| `ARCHITECTURE_V9.r6-candidate.md` | 候选稿全文。先读 §12–§14 |
| `build/r5-base.md` | 生成用的 r5 原文，与现行文件逐字节相同 |
| `build/build_r6.py` | 从 r5 逐处替换生成候选稿；每一处都要求原文恰好出现一次 |
| `build/r5-to-r6.diff` | r5 到 r6 的统一差异 |
| `build/check_r6.py` | 作者侧自查，纯 CPU，只读 |
| `evidence/unchanged-sections.txt` | 声明没有改的章节与 r5 的逐字比对 |
| `evidence/citations.txt` | 候选稿引用的数字在出处报告里的原文行 |
| `evidence/external-citations.txt` | 式 14 引的三篇外部文献的编号、标题、作者 |
| `REVIEW-CARDS.md` | 两张复核卡的卡面 |
| `SHA256SUMS.txt` | 本目录文件的 sha256 |

## 复现（仓库根目录）

```bash
python3 reports/V9-ARCH-R6/build/build_r6.py
python3 reports/V9-ARCH-R6/build/check_r6.py
```

## 没有做的

- 没有运行任何模型、训练或评测；没有改源码、测试、已有报告和冻结文件。
- 自查是作者做的，不能代替非作者复核。
- 候选稿 §13.4 列出了起草时没有核对的内容。
