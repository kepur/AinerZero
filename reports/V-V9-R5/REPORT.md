# ainerzero.V9.R6 独立复核报告：V9-R5 适配器注册表核验

## 总结（30行内）
1. **复核对象与结论**：对 `ainerzero.V9.R5` 交付的 51 项条目及文档进行逐行独立核验，正向与反例校验全通，建议统筹予以验收。
2. **DA3 许可逐模型核实**：ByteDance-Seed/Depth-Anything-3 官方代码为 Apache-2.0。模型权重严格分级：Small (0.08B)、Base (0.12B)、Metric-Large (0.35B)、Mono-Large (0.35B) 为 **Apache-2.0**；Large (0.35B)、Giant (1.15B)、Nested (1.40B) 明确为 **CC BY-NC 4.0**。R5 记录完全准确。
3. **DINOv3 条款核实**：确认采用非 OSI 自定义许可；1.b.v 明确排除受 ITAR 及美国出口管制法规管辖的军事武器活动；1.b.i 包含同类传染/共享分发限制要求。R5 提炼严谨无遗漏。
4. **其他关键出处核实**：TapNet 代码与所有权重（含 TAPIR、TRAJAN 等）逐字核实为 Apache-2.0；CUT3R 确为 CC BY-NC-SA 4.0（带 SA 条款）；AM-RADIO 确含 Clause 3.3 非商业条款；Moonlight 论文确有 ~2× 效率报告；10 项未开源论文均严格标注 `无法核`。
5. **指出缺陷与勘误**：
   - `adapter_registry.json` 顶层 `revision` 与 `r3_summary` 仍遗留 r3 文本（写 28 条），未同步刷新为 51 条（底层 entries 实为 51 条）。
   - `reports/V9-R5/报告.md` 表格 3.3 笔误将 dino-wm、pldm、pushforward、slotssms 写为 Apache-2.0，但在交付物 `adapter_registry.json` 与 `ADAPTER_REGISTRY.md` 中均正确登记为 MIT。
6. **不利反例与执行规范**：自写 8 个不利反例（变坏必红检验）100% 捕获（8/8 RED PASS）。全程纯 CPU、无额外下载、无跨界修改、不自行验收。

---

## 详细核验结果与反例证明
- **正向独立核验脚本**：`reports/V-V9-R5/verify_r5_independent.py`（正向断言 51 条目完整通过）
- **自写不利反例捕获矩阵（8/8 RED PASS）**：
  1. `C01_da3_small_falsely_noncommercial`: 伪造 Small 为非商业 -> 成功变红捕获
  2. `C02_da3_giant_falsely_apache`: 伪造 Giant 为 Apache -> 成功变红捕获
  3. `C03_dinov3_itar_export_stripped`: 抹除 DINOv3 非 OSI/ITAR 条款 -> 成功变红捕获
  4. `C04_cut3r_laundered_as_mit`: 伪造 CUT3R 为 MIT -> 成功变红捕获
  5. `C05_radio_noncommercial_omitted`: 隐瞒 RADIO 3.3 非商业限制 -> 成功变红捕获
  6. `C06_titans_fake_official_repo`: 伪造 titans 官方仓库 -> 成功变红捕获
  7. `C07_tapnet_weights_falsely_proprietary`: 篡改 tapnet 权重许可 -> 成功变红捕获
  8. `C08_md_sync_entry_missing`: 篡改 MD 导致与 JSON 脱节 -> 成功变红捕获
- **指标文件**：`reports/V-V9-R5/metrics.json` 与 `reports/V-V9-R5/check_result.json`
