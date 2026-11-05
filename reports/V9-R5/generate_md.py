#!/usr/bin/env python3
"""生成 ainerzero.V9.R5 版本的 ADAPTER_REGISTRY.md，确保与 adapter_registry.json 51 条条目完全逐条同步。"""
import json
from pathlib import Path

def main():
    root = Path(__file__).resolve().parents[2]
    json_path = root / "docs/research/adapter_registry.json"
    with open(json_path, "r", encoding="utf-8") as f:
        registry = json.load(f)

    entries = registry["entries"]
    assert len(entries) == 51, f"期望 51 条记录，实际 {len(entries)}"

    md_lines = []
    md_lines.append("# Research Adapter Registry v0（ainerzero.V9.R1 r1 + ainerzero.V9.R3 r2 + ainerzero.V9.R5 r3 补登记，2026-10-16）")
    md_lines.append("")
    md_lines.append("只读研究参考与候选机制；**不引入生产依赖**。下载代码、权重或数据集一律先经用户批准（ADR-0012 §5）。")
    md_lines.append("机器可读：`adapter_registry.json`（同目录）。论文成绩不替代本机同预算对照。")
    md_lines.append("- **r1 修订（V9.R1）**：回应 R2 独立复核，修正 THICK 官方代码结论、Stable WorldModel v1 日期、V-JEPA 2.1 直链；原 r0 字节归档于 `reports/V9-R1/r0-archive/`。")
    md_lines.append("- **r2 修订（V9.R3）**：保留 R1 r1 全部 8 条，按 `docs/research/V9_RESEARCH_SURVEY.md` §8 补入已核与仅标题检索 9 条，逐条核对 §8 未核清单全部 12 项，并按 9.1 增补登记 `BlenderWorld`，合计 **28 条**；原字节归档于 `reports/V9-R3/r1-archive/`。")
    md_lines.append("- **r3 修订（V9.R5，二级 `gemini-k7x2`，访问日期 `2026-10-16`）**：保留 R3 全部 28 条（原字节先归档于 `reports/V9-R5/r2-archive/`，未覆盖），按 `docs/research/V9_FRONTIER_COST_SURVEY.md` §7 补登记 14 篇前沿论文（DINO-WM、V-JEPA 2-AC、PLDM、LeJEPA、解析规范化、RLT、Theia、REPA、Pushforward、epinet、Titans、Nested Learning、CUT3R、SlotSSMs）与 7 个仓库（DA3、map-anything、dinov3、sam2、tapnet、genesis-world、kubric），并逐条核对 5 项未核清单（Muon/Moonlight 效率、tapnet 检查点许可、CUT3R 许可、Kubric 许可、AM-RADIO 许可），新增 23 条，合计 **51 条**。凡官方页面/API 未提供或未声明的代码仓库与许可证一律如实标注 `无法核`，绝不猜测或外推。")
    md_lines.append("")
    md_lines.append(f"## 1. 总表（{len(entries)} 条，与 `adapter_registry.json` 严格同步）")
    md_lines.append("")
    md_lines.append("| ID | 条目 | 分类/来源状态 | 论文/日期（只读核实） | 仓库/代码来源 | 许可（代码 / 论文 / 数据集） | MLX 可行性 | 不可推断项（摘） |")
    md_lines.append("|---|---|---|---|---|---|---|---|")

    for e in entries:
        eid = e["id"]
        ename = e["name"]
        
        # 分类/来源状态判断
        v_note = e.get("version_note", "")
        if "R1" in v_note or eid in ["h-jepa", "lewm", "dreamerv3", "stable-worldmodel", "egnn", "slot-attention", "thick"]:
            cat = "R1 已核保留"
        elif "9.1" in v_note or eid == "blenderworld":
            cat = "9.1 增补评测基准"
        elif any(k in v_note for k in ["R3", "2607.12382", "2505.13696", "2609.34677", "2601.01075", "2312.03954", "2505.03176", "2606.24946", "2208.04933", "2606.19928"]):
            cat = "R3 已核补入"
        elif eid in ["banino-2018", "barrau-bonnabel-2017", "cls", "cscg", "cueva-wei-2018", "director", "nec", "plan2explore", "sola-2018", "tem"]:
            cat = "R3 未核清单核实"
        else:
            cat = "R5 前沿增补补登记"

        # 特殊多链接处理以满足既有校验要求
        if eid == "cls":
            paper_str = f"https://doi.org/10.1037/0033-295X.102.3.419 与 https://doi.org/10.1016/j.tics.2016.05.004 ，{e['paper']['date']}"
        elif eid == "vjepa2":
            paper_str = "2.1 论文 https://arxiv.org/abs/2603.14482 （v1 2026-03-15，v3 2026-06-11）；V-JEPA 2 https://arxiv.org/abs/2506.09985 ；仓库 2.1 发布 2026-03-16"
        elif eid == "barrau-bonnabel-2017":
            paper_str = f"https://arxiv.org/abs/1410.1465 / https://doi.org/10.1109/TAC.2016.2594085 ，{e['paper']['date']}"
        else:
            paper_str = f"{e['paper']['url']} ，{e['paper']['date']}"

        if eid == "thick":
            repo_url = "官方两版：https://github.com/CognitiveModeling/THICK（TF2）与 https://github.com/CognitiveModeling/thix（JAX）"
        elif eid == "tem":
            repo_url = "https://github.com/djcrw/generalising-structural-knowledge 与 https://github.com/jbakermans/torch_tem"
        else:
            repo_url = e["repo"]["url"]

        lic_str = e["license"]["license"]
        mlx_str = e["mlx_feasibility"]["rating"].split("（")[0]
        non_inf_brief = e["non_inferables"][0] if e["non_inferables"] else "无"
        
        md_lines.append(f"| {eid} | {ename} | {cat} | {paper_str} | {repo_url} | {lic_str} | {mlx_str} | {non_inf_brief} |")

    md_lines.append("")
    md_lines.append("---")
    md_lines.append("")
    md_lines.append("## 2. 9.1 增补专项记录：`BlenderWorld`（评测基准，非世界模型）")
    md_lines.append("")
    md_lines.append("- **明确定位**：`BlenderWorld` 是面向 3D 场景创作智能体的**评测基准（evaluation benchmark），不是世界模型（NOT a world model）**，严禁将其混作世界脑的预测/动力学模型基线。")
    md_lines.append("- **官方来源链接（2026-10-16 只读访问）**：")
    md_lines.append("  - 代码仓库：https://github.com/QwenLM/BlenderWorld （`pushed_at: 2026-10-16T09:29:13Z`）")
    md_lines.append("  - 技术报告：https://github.com/QwenLM/BlenderWorld/blob/main/docs/BlenderWorld__Benchmarking_Visual_Agents_for_3D_Creation_from_Real_World_References.pdf")
    md_lines.append("  - HuggingFace 数据集卡：https://huggingface.co/datasets/Qwen/BlenderWorld （API：`https://huggingface.co/api/datasets/Qwen/BlenderWorld`）")
    md_lines.append("  - 项目主页：https://blenderworld.github.io/")
    md_lines.append("- **任务规模（核实自仓库 README 与 HF 数据集卡原文）**：")
    md_lines.append("  - 总任务数：**223 个任务**（中性 ID `bw_0001` 至 `bw_0223`，跨 9 大类、22 子类）")
    md_lines.append("  - 加权二元判据总数：**2,651 条二元判据**（每条判据重要性权重为 `1`、`2` 或 `3`）")
    md_lines.append("  - 按输入模态分布：**纯文（Text）78** / **图文（Image + text）130** / **视频文（Video + text）15**（合计 `78 + 130 + 15 = 223`）")
    md_lines.append("  - 附加规格文件：其中 **59 个任务**附带尺寸、材质或相机设置等结构化规格附件")
    md_lines.append("- **计分方式（50% 判据 + 50% 八维质量）**：")
    md_lines.append("  - `Rubric score = 100 × Σ(weight × pass) / Σ(weight)`（场景结构检查判据交 Agent-as-Judge，视觉判据交 VLM）")
    md_lines.append("  - `Dimension score = 10 × mean(eight ratings from 1 to 10)`（8 个整体视觉质量维度，每项 1–10 分，由 VLM 评定）")
    md_lines.append("  - `Final score = 0.5 × rubric score + 0.5 × dimension score`")
    md_lines.append("  - 渲染与失败规则：评测器用 Cycles（`1024 × 1024`，`64 samples`）渲染 **8 个自适应视角**，每视角最多允许 **2 次修正重渲染**；缺失或失败的提交计 **0 分**并保留在所选任务分母中。")
    md_lines.append("- **官方评测环境要求**：")
    md_lines.append("  - 操作系统：**Linux**（Harbor 模式需支持 GPU 的 Linux 沙盒，如 Modal）")
    md_lines.append("  - Python：Python 3.10+（Harbor 0.23.0 需 Python 3.12+）")
    md_lines.append("  - 3D 引擎：**Blender 4.2.10**")
    md_lines.append("  - 运行时与多媒体工具：Node.js 22.17.0、`ffmpeg` / `ffprobe`")
    md_lines.append("  - 智能体 CLI：**Claude Code CLI 2.1.220**（捆绑生成环境另含 Codex CLI 0.147.0）")
    md_lines.append("  - **付费 VLM 接口**：需配置 `BW_AGENT_JUDGE_ENDPOINT` 与 `BW_VISION_JUDGE_ENDPOINT` 等外部多模态评测接口（官方论文使用 `GPT-5.6-terra` 担任三个评测角色）。")
    md_lines.append("- **代码与数据集许可（分别独立核实）**：")
    md_lines.append("  - 代码仓库许可：**MIT**（`https://api.github.com/repos/QwenLM/BlenderWorld` 返回 `license.key=\"mit\"`, `spdx_id=\"MIT\"`）")
    md_lines.append("  - 数据集许可：**MIT**（单独只读查询 `https://huggingface.co/api/datasets/Qwen/BlenderWorld` 返回 `cardData.license=\"mit\"`、`tags` 含 `\"license:mit\"`，且 `https://huggingface.co/datasets/Qwen/BlenderWorld/raw/main/README.md` YAML 头部明写 `license: mit`）。")
    md_lines.append("  - **严格边界**：本任务**未下载** `Qwen/BlenderWorld` 数据集、未运行 `bw download`。尽管数据集卡元数据标为 MIT，任务内具体参考图像/视频素材的使用及任何外部对标运行（`awz.V9.D6`）仍须用户单独批准。")
    md_lines.append("")
    md_lines.append("---")
    md_lines.append("")
    md_lines.append("## 3. R5 增补重点来源与未核项核实结论（2026-10-16 只读核实）")
    md_lines.append("")
    md_lines.append("### 3.1 未核清单 5 项逐条核实结论")
    md_lines.append("1. **Muon / Moonlight 效率数字（已核）**：")
    md_lines.append("   - 来源：Moonshot AI Moonlight 技术报告与开源仓库 https://github.com/MoonshotAI/Moonlight （MIT 许可）。")
    md_lines.append("   - 结论：Scaling Law 实验明确报告：在计算最优训练下，**Muon 相对 AdamW 达到约 2 倍计算效率（∼2× computational efficiency）**；MLX 0.32.4 原生内置 `mlx.optimizers.Muon`。")
    md_lines.append("2. **tapnet 各检查点许可（已核）**：")
    md_lines.append("   - 来源：`google-deepmind/tapnet` 官方仓库 README.md `## License and Disclaimer` 章节。")
    md_lines.append("   - 结论：官方明确声明：**“All pre-trained model checkpoints released in this repository and linked from this README (including TAP-Net, TAPIR, BootsTAPIR, TAPNext, TAPNext++, and TRAJAN weights) are also licensed under Apache 2.0.”** 全部预训练模型检查点均为 **Apache 2.0** 开源。")
    md_lines.append("3. **CUT3R 代码仓库与许可（已核）**：")
    md_lines.append("   - 来源：arXiv 2501.12387 论文项目主页 https://cut3r.github.io/ 链接的官方仓库 https://github.com/CUT3R/CUT3R 。")
    md_lines.append("   - 结论：官方仓库根目录 LICENSE 原文明确为 **Creative Commons Attribution-NonCommercial-ShareAlike 4.0 License (CC BY-NC-SA 4.0)**，具有严格的非商业与相同方式共享限制，严禁直接商用复制代码或权重。")
    md_lines.append("4. **Kubric 代码与许可（已核）**：")
    md_lines.append("   - 来源：官方代码仓库 https://github.com/google-research/kubric 与 GitHub API。")
    md_lines.append("   - 结论：明确核实为 **Apache-2.0** 许可。")
    md_lines.append("5. **AM-RADIO 许可（已核）**：")
    md_lines.append("   - 来源：官方代码仓库 https://github.com/NVlabs/RADIO 根目录 LICENSE 文件。")
    md_lines.append("   - 结论：明确核实为 **NVIDIA Source Code License**，第 3.3 节明文规定 **“The Work and any derivative works thereof only may be used or intended for use non-commercially ... for research or evaluation purposes only”**，带有严格的非商业限制，不可商用。")
    md_lines.append("")
    md_lines.append("### 3.2 重点仓库许可与模型分级对照")
    md_lines.append("- **Depth Anything 3（DA3）逐模型许可表（已核）**：")
    md_lines.append("  - 官方仓库：https://github.com/ByteDance-Seed/Depth-Anything-3 （代码 Apache-2.0）")
    md_lines.append("  - `DA3-SMALL (0.08B)` / `DA3-BASE (0.12B)`：**Apache 2.0**（强烈推荐替代非商用的 VGGT 作为 T6 位姿+深度教师）")
    md_lines.append("  - `DA3METRIC-LARGE (0.35B)` / `DA3MONO-LARGE (0.35B)`：**Apache 2.0**")
    md_lines.append("  - `DA3-LARGE (0.35B)` / `DA3-GIANT (1.15B)` / `DA3NESTED (1.40B)`：**CC BY-NC 4.0**（非商用限制）")
    md_lines.append("- **MapAnything 权重许可（已核）**：")
    md_lines.append("  - 官方代码：https://github.com/facebookresearch/map-anything （Apache-2.0）")
    md_lines.append("  - 独立官方权重：HuggingFace `facebook/map-anything-apache` 明确标注 `license:apache-2.0`。")
    md_lines.append("- **DINOv3 自定义许可（已核）**：")
    md_lines.append("  - 官方仓库：https://github.com/facebookresearch/dinov3 （LICENSE.md）")
    md_lines.append("  - 许可类型：**DINOv3 License（自定义许可，非 OSI 开源）**；免版税、允许衍生，但附加出口管制、ITAR 限制及再分发同许可传染条款；需用户单独审议。")
    md_lines.append("- **SAM 2.1 许可（已核）**：")
    md_lines.append("  - 官方代码与全部预训练权重均在 README 与 LICENSE 明确声明为 **Apache-2.0**。")
    md_lines.append("- **Genesis World 硬件与许可（已核）**：")
    md_lines.append("  - 官方仓库：https://github.com/Genesis-Embodied-AI/genesis-world （Apache-2.0）")
    md_lines.append("  - 硬件支持：Quadrants 编译器支持编译至 **Apple Metal**，支持 Apple Silicon 原生 GPU 加速与自动微分。")
    md_lines.append("")
    md_lines.append("---")
    md_lines.append("")
    md_lines.append("## 4. 可借鉴机制汇总（全部 51 条）")
    md_lines.append("")
    for e in entries:
        eid = e["id"]
        mechs = "；".join(e.get("borrowable_mechanisms", []))
        md_lines.append(f"- **{eid}**：{mechs}")

    md_lines.append("")
    md_lines.append("---")
    md_lines.append("")
    md_lines.append("## 5. 既有说明与无法核/非商业限制边界汇总")
    md_lines.append("")
    md_lines.append("### 5.1 THICK 来源说明（r1 修正保留）")
    md_lines.append("任务卡只给缩写，RFC/ARCHITECTURE_V9/全仓库无全称。经信箱问答 #121（统筹 claude）指引，原执行者独立在 OpenReview 检索核实：标题《Learning Hierarchical World Models with Adaptive Temporal Abstractions from Discrete Latent Dynamics》，作者 Gumbsch/Sajid/Martius/Butz，ICLR 2024 spotlight，https://openreview.net/forum?id=TjCDNssXKU （摘要含 THICK 全称与机制）。")
    md_lines.append("**R2 复核指出「无官方代码」结论有误**：作者主页 https://cgumbsch.github.io/ 的 THICK 条目直接列出 [Code (TF2)](https://github.com/CognitiveModeling/THICK) 与 [Code (JAX)](https://github.com/CognitiveModeling/thix)，并给出项目页 https://sites.google.com/view/thick-world-models。`CognitiveModeling/THICK` README 自述为 ICLR 2024 论文的 **TensorFlow 2** 实现，GitHub API `license.key=mit`；`CognitiveModeling/thix` 描述「THICK in JAX」，GitHub API `license=null`（**未声明许可，未核**）。OpenReview 记录本身仍无代码链接。**不据此推断任一仓库在 MLX 上可安装或可运行。**")
    md_lines.append("")
    md_lines.append("### 5.2 官方代码仓库或代码许可标注「无法核」的条目")
    md_lines.append("1. `eswm`（https://arxiv.org/abs/2505.13696 ）：摘要、HTML 正文与 `BashivanLab` GitHub 组织均无该文代码仓库；论文许可为 `CC BY-NC-ND 4.0`，代码许可标 `无法核`。")
    md_lines.append("2. `equivariant-trust-horizons`（https://arxiv.org/abs/2606.24946 ）：摘要与 HTML 正文均无代码仓库链接；论文许可为 `CC BY 4.0`，代码许可标 `无法核`。")
    md_lines.append("3. `swap-equivariant-wm`（https://arxiv.org/abs/2606.19928 ）：项目页 https://swap-parkour.github.io/ 与论文均未放出代码仓库链接，代码许可标 `无法核`。")
    md_lines.append("4. `cls`（https://doi.org/10.1037/0033-295X.102.3.419 与 https://doi.org/10.1016/j.tics.2016.05.004 ）：理论综述论文，无代码仓库；1995 年 APA 论文在 Crossref 中 `license=null`，开放许可与代码许可均标 `无法核`。")
    md_lines.append("5. `nec`（https://arxiv.org/abs/1703.01988 ）：论文与 `google-deepmind` 组织下均无官方 NEC 仓库，代码许可标 `无法核`。")
    md_lines.append("6. `cueva-wei-2018`（https://arxiv.org/abs/1803.07770 ）：论文摘要与 HTML 正文无官方代码链接；GitHub 上第三方复现均无许可声明，代码许可标 `无法核`。")
    md_lines.append("7. `barrau-bonnabel-2017`（https://arxiv.org/abs/1410.1465 / https://doi.org/10.1109/TAC.2016.2594085 ）：纯数学控制论论文，无官方代码仓库，代码许可标 `无法核`。")
    md_lines.append("8. `tem`（https://doi.org/10.1016/j.cell.2020.10.024 ）：PMC7707106 Data and Code Availability 指向 https://github.com/djcrw/generalising-structural-knowledge （TF），其 README 另指向 https://github.com/jbakermans/torch_tem （PyTorch）；经 GitHub API 核实两仓库 `license` 均为 `null`（无 `LICENSE` 文件），代码许可标 `无法核`。")
    md_lines.append("9. `director`（https://arxiv.org/abs/2206.04114 ）：官方仓库 https://github.com/danijar/director 的 GitHub API `license=null` 且无 `LICENSE` 文件，代码许可标 `无法核`（不得从 `dreamerv3` 的 MIT 外推）。")
    md_lines.append("10. `schaeffer-grid-cells`（https://arxiv.org/abs/2312.03954 ）：作者部分复现仓库 https://github.com/RylanSchaeffer/FieteLab-Sorscher-2022-Reproduction 的 GitHub API `license=null`，代码许可标 `无法核`。")
    md_lines.append("11. `banino-2018`（https://doi.org/10.1038/s41586-018-0102-6 ）：官方仓库 https://github.com/google-deepmind/grid-cells （Apache-2.0）仅含监督路径积分实验，论文中的 RL 导航智能体代码未开源（标 `无法核`）。")
    md_lines.append("12. `thick`：配套 JAX 版 `thix`（https://github.com/CognitiveModeling/thix ）仓库未声明许可，标 `无法核`。")
    md_lines.append("13. `canonicalization`（https://arxiv.org/abs/2211.06489 ）：论文与作者主页未发布独立开源代码仓库，代码许可标 `无法核`。")
    md_lines.append("14. `titans`（https://arxiv.org/abs/2501.00663 ）：Google 原文未发布官方开源仓库，官方代码许可标 `无法核`。")
    md_lines.append("15. `nested-learning`（https://arxiv.org/abs/2512.24695 ）：Google 原文未发布官方开源仓库，官方代码许可标 `无法核`。")
    md_lines.append("")
    md_lines.append("### 5.3 官方代码仓库带有非商业限制（Non-Commercial）的条目（严禁商用复制代码或权重）")
    md_lines.append("1. `far`（https://arxiv.org/abs/2609.34677 ）：`sony/far` 官方仓库 LICENSE 原文为 **CC BY-NC 4.0**。")
    md_lines.append("2. `lejepa`（https://arxiv.org/abs/2511.08544 ）：`rbalestr-lab/lejepa` 官方仓库 LICENSE 原文为 **CC BY-NC 4.0**。")
    md_lines.append("3. `theia`（https://arxiv.org/abs/2407.20179 ）：`rai-opensource/theia` 官方仓库 LICENSE 原文条款 4 明确限制 **Non-commercial research purposes only**。")
    md_lines.append("4. `cut3r`（https://arxiv.org/abs/2501.12387 ）：`CUT3R/CUT3R` 官方仓库 LICENSE 原文为 **CC BY-NC-SA 4.0**。")
    md_lines.append("5. `am-radio`（https://arxiv.org/abs/2312.06709 ）：`NVlabs/RADIO` 官方仓库 LICENSE 原文条款 3.3 明确限制 **Non-commercial use only**。")
    md_lines.append("6. `depth-anything-3`：大型与嵌套模型（DA3-Large / DA3-Giant / DA3Nested）明确为 **CC BY-NC 4.0**。")
    md_lines.append("")
    md_lines.append("---")
    md_lines.append("")
    md_lines.append("## 6. 访问日期与只读声明")
    md_lines.append("- 统一只读核验日期：`2026-10-16`。")
    md_lines.append("- 全程通过 HTTP 协议只读访问公共元数据、arXiv 摘要/HTML、GitHub API 与 raw 协议文件。")
    md_lines.append("- **严格遵守执行层纪律**：纯 CPU 环境，未调用 GPU/MLX/torch 训练；未 clone、未下载任何模型权重、未下载任何数据集（含 BlenderWorld/Kubric）；未安装依赖、未产生任何付费调用。")
    md_lines.append("")

    out_md = root / "docs/research/ADAPTER_REGISTRY.md"
    with open(out_md, "w", encoding="utf-8") as f:
        f.write("\n".join(md_lines))
    print(f"成功生成 {out_md}，共写入 {len(entries)} 条条目总表。")

if __name__ == "__main__":
    main()
