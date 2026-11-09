# P192：r3 数据生成完成

- **train：** 1000 个世界、8000 个回合；**dev：** 50 个世界、300 个回合。
- **运行：** 06:43–06:58 UTC，退出码 0。
- **确定性：** train 的 SHA256SUMS 与 manifest 同 P191 那份逐字节相同。
- **已知缺陷：** 汇总字段 `world_redraw_count` 恒为 0，只影响显示。
- 详见 RESEARCH_LOG `R20261109-S2-data-r3-done`。
