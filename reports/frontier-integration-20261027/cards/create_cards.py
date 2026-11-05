"""Create the CMFL landing cards on AinerRelay (one-shot, idempotent via --dedupe).

Run from anywhere: python3 create_cards.py [--dry-run]
Each card's prompt is also written next to this script as <id-hint>.md for provenance.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
RELAY = str(Path.home() / "AinerWorkFlow/AinerRelay/bin/relay")
REPORT = "reports/frontier-integration-20261027/REPORT.md"
DESIGN = "reports/frontier-integration-20261027/DESIGN_CORE.md"
AZ = "/Users/mac/AinerWorkFlow/AinerZero"
AWZ = "/Users/mac/AinerWorkFlow/AnimeWorldZero"

COMMON = (
    "依据：AinerZero/" + REPORT + " 与 " + DESIGN + "（一级 claude，2026-10-28）；"
    "用户 2026-10-28 指令「落地并入工作台」。\n"
    "主责统筹：claude（CMFL 研究线）。S1、T6 等既有线的主责不变。\n"
    "本卡不授权：训练、MLX 运行、下载、安装第三方包、付费、云 GPU、修改冻结参数或门槛。"
    "复跑不得改写已交付证据（COORDINATION 规则 8）。\n"
)

ALIAS = "及今后任何申报或被查出与之同会话的别名（COORDINATION 10-22 裁定）"

CARDS = [
    {
        "key": "A11", "project": "ainerzero", "phase": "V9", "track": "A",
        "tier": 1, "kind": "design", "ready": True, "needs": "text,math",
        "title": "【一级·架构】ADR-0014 草案：受限机制形成环（CMFL）——机制充分性门、单侧晋升门、教师三职责、E1 增补候选",
        "scope": f"{AWZ}/docs/adr/ADR-0014-constrained-mechanism-formation.md,{AZ}/reports/frontier-integration-20261027/",
        "context": f"{AZ}/{REPORT},{AZ}/{DESIGN},{AZ}/ARCHITECTURE_V9.md,{AZ}/ARCHITECTURE_BASELINE.md,{AWZ}/docs/adr/ADR-0012-v9-neurogeometry-hjepa.md,{AWZ}/docs/adr/ADR-0013-character-first-production.md",
        "prompt": COMMON + (
            "一级作者工作。把 DESIGN_CORE.md 写成 AWZ docs/adr/ADR-0014（状态 proposed）：\n"
            "1. 定位：AinerZero 学习平面的 S6/E1 扩展，不改 ADR-0013 角色优先主线；世界脑仍是旁路。\n"
            "2. 内容：机制充分性门（7 个有序路由、阈值登记时冻结、只读信念与允许观察）；离线发现（MID）；"
            "单侧晋升门（优越性、式 6、多重比较与在线 FDR、有限样本适用域、逐例不回归、出处与独立出具者、留出集标定）；"
            "教师三职责；E1 增补候选 ⑤⑥⑦⑧ 与 P/S 两族世界。\n"
            "3. 契约变更清单与迁移、回滚：PromotionEvidence v2、Fragment 来源/对象/动作键、SLOW 撤销与降级、"
            "探针实验先走 SkillProposal v1 内登记的探针能力（带假设标签需另升 v1.1）。\n"
            "4. 明确不改：r5 冻结基线、E1 原门槛、S1 r13 冻结件、§8.6 信息边界、教师与 LLM 不能写 SLOW。\n"
            "交付后放出 ainerzero.V9.A12 非作者审议。"
        ),
        "acceptance": "ainerzero.V9.A12 非作者审议建议通过且必修项关闭。",
        "params": {"author": "claude", "adr_number": "ADR-0014", "status_on_delivery": "proposed"},
    },
    {
        "key": "A12", "project": "ainerzero", "phase": "V9", "track": "A",
        "tier": 2, "kind": "review", "ready": False, "needs": "text,math", "depends": "A11", "verifies": "A11",
        "title": "【L3·强代理】【非作者·架构审议】审议 ADR-0014（CMFL）草案",
        "scope": f"{AZ}/reports/V9-A12/",
        "context": f"{AWZ}/docs/adr/ADR-0014-constrained-mechanism-formation.md,{AZ}/{REPORT},{AZ}/{DESIGN},{AZ}/ARCHITECTURE_V9.md,{AZ}/ARCHITECTURE_BASELINE.md",
        "prompt": COMMON + (
            "独立审议 ADR-0014 草案，只读，报告写入 reports/V9-A12/。逐项回答：\n"
            "1. 是否守住 r5 冻结边界：§8.6 学习侧信息边界（MSG 是否只读信念与允许观察）、FAST/MID/SLOW、"
            "教师与 LLM 不能写 SLOW、ADR-0013 世界脑旁路。\n"
            "2. 统计论断是否正确：χ² 充分性检验、Fisher 信息与 EIG、配对 bootstrap 优越性、共形有限样本修正、"
            "e-process 交并合成与 e-LOND、data thinning。指出任何把连续时间、渐近或可交换前提下的结论外推的地方。\n"
            "3. 有无借“新增机制”之名暗改冻结门槛、公共接口语义或训练资格而缺迁移与回滚。\n"
            "4. MSG 的阈值是否都在登记时冻结，能否变成调参自由度。\n"
            "5. 自己从一手来源重核 5 条承重文献：EMPIRIC 2609.35047、MDA 2608.09696、OSVerify 2610.18089、"
            "Evidence-Gated Research 2610.01751、MOS-discrepancy 2610.09261。不得沿用报告 raw/ 的结论作判据。\n"
            "结论给 accept / request_changes 与必修项清单。"
        ),
        "acceptance": "报告含 5 项逐条结论、5 条文献的一手来源复核、明确的 accept 或 request_changes。",
        "params": {"excluded_agents": ["claude"], "excluded_note": "作者 claude " + ALIAS, "level": "L3"},
    },
    {
        "key": "awzB20", "project": "awz", "phase": "V9", "track": "B",
        "tier": 2, "kind": "implement", "ready": True, "needs": "code",
        "title": "【L3·强代理】【代码·Blender·CPU】E0 真值修复：精确接触判定、速度来源与误差界、静态面隐藏参数入档（B11 后续，小样）",
        "scope": f"{AWZ}/python/animeworld/e0/,{AWZ}/tests/e0/,{AWZ}/reports/V9-B20/",
        "context": f"{AWZ}/python/animeworld/e0/blender_worker.py,{AWZ}/python/animeworld/e0/scenarios.py,{AWZ}/python/animeworld/e0/hidden_params.py,{AWZ}/python/animeworld/e0/dataset.py,{AZ}/{REPORT},{AZ}/ARCHITECTURE_V9.md",
        "prompt": COMMON + (
            "背景（一级已对照源码复核）：\n"
            "- 接触用包围球启发式（blender_worker.py:306-310，半径取最大尺寸的一半，阈值 rad_a+rad_b+0.04）。"
            "地面 30×30×1 取半径 15，活动物体几乎每帧都被判为与地面接触，碰撞 F1 真值不可用；\n"
            "- 速度是 60 fps 逐帧后向差分（:255，未取整位姿，输出取 6 位小数），不是求解器速度，滞后半帧；\n"
            "- 静态地面和斜坡的摩擦、弹性随机化了（scenarios.py:62-63、88-89）却没写进 hidden_parameters，"
            "E1 的 ④ 真参数上界无法从数据还原。\n"
            "B11 r2 已验收，本卡是后续修复。要求：\n"
            "1. 接触：改为按实际碰撞形状的精确最近距离判定（地面、斜坡按平面或盒体，盒、球按解析式或 mathutils.bvhtree），"
            "登记容差（含 Bullet collision margin），只在容差内记接触。Blender Python 拿不到 Bullet 原生接触点就如实写明。\n"
            "2. 速度：给出速度来源字段与登记误差界，可用子步分辨率差分或中心差分；取整只在导出时做。\n"
            "3. 静态面的摩擦、弹性写入 hidden_parameters（hidden_params_side 仍为 world）。\n"
            "4. 解析测试：自由落体球在空中时接触为 false，首次碰撞在解析时刻 ±1 帧内为 true；静置盒持续接触；"
            "空中速度与 v=g·t 的偏差在登记界内。\n"
            "5. 按 B11 r2 同样规模（≤18 段）重新生成小样到新目录 reports/V9-B20/r1/，同种子跑两次逐字节一致；"
            "确定性域按 EVENT_PROTOCOL.md:183-191 登记，Blender 版本写实际的 5.2.2。不批量、不渲染。\n"
            "6. 60 fps 对 120 Hz、“3 个随机种子”实现成每分区一个，这两项只记入已知问题，本卡不改。\n"
            "权威模块：采样必须继续只读调用 e0/hidden_params.py 的 DEFAULT_RANGES，划分与种子继续用 e0/dataset.py，"
            "不得另写一套。B11 r1/r2 证据不得覆盖；e0/ 目前未入 git，开工前记录改动前各文件 SHA。\n"
            "领卡前置：接交流电（ADR-0009 用电池时不跑重任务）；本机 /Applications/Blender.app 可运行。"
        ),
        "acceptance": "awz.V9.B21 非作者对抗复核建议通过；含拆守卫坏控证据。",
        "params": {"level": "L3", "blender_version": "5.2.2", "pilot_max_segments": 18, "authority_modules": ["e0/hidden_params.py:DEFAULT_RANGES", "e0/dataset.py"], "no_overwrite": ["reports/V9-B11/r1", "reports/V9-B11/r2"]},
    },
    {
        "key": "awzB21", "project": "awz", "phase": "V9", "track": "B",
        "tier": 2, "kind": "review", "ready": False, "needs": "code", "depends": "awzB20", "verifies": "awzB20",
        "title": "【L3·强代理】【非作者·对抗复核】复核 awz.V9.B20 E0 真值修复",
        "scope": f"{AWZ}/reports/V9-B21/",
        "context": f"{AWZ}/reports/V9-B20/,{AWZ}/python/animeworld/e0/,{AZ}/{REPORT}",
        "prompt": COMMON + (
            "在隔离副本里复核，报告写入 reports/V9-B21/：\n"
            "1. 自己写解析场景（不复用作者夹具）：空中球、首次碰撞时刻、静置盒、斜坡滑块；核对接触与速度误差界。\n"
            "2. 拆守卫坏控：只把接触判定改回包围球启发式，空中球用例必须变红；只把速度改回逐帧后向差分，"
            "速度误差界用例必须变红。普通负例与坏控分开记账。\n"
            "3. 静态面隐藏参数确已入档，且与场景采样值一致。\n"
            "4. 同种子两次逐字节一致；B11 r1/r2 证据 SHA 未变。\n"
            "5. 确定性域登记写的是实际 Blender 5.2.2。"
        ),
        "acceptance": "五项逐条结论与证据路径；明确 accept 或 request_changes。",
        "params": {"level": "L3", "excluded_note": "awz.V9.B20 作者" + ALIAS},
    },
    {
        "key": "P47", "project": "ainerzero", "phase": "V9", "track": "P",
        "tier": 2, "kind": "audit", "ready": True, "needs": "code,math",
        "title": "【L2·零运行审计】S1 预登记“等变来源＝G3 估计位姿＋协方差注入误差”与实现一致性核查（r14 冻结前）",
        "scope": f"{AZ}/reports/V9-P47/",
        "context": f"{AZ}/src/ainerzero/v9/experiments/s1/prereg.py,{AZ}/src/ainerzero/v9/experiments/s1/arms.py,{AZ}/src/ainerzero/v9/experiments/s1/data.py,{AZ}/src/ainerzero/v9/experiments/s1/awz_export.py,{AZ}/src/ainerzero/v9/geometry/canonical.py,{AZ}/reports/V9-S1-r14-budget-proposal.md,{AZ}/{REPORT}",
        "prompt": COMMON + (
            "零运行审计：不跑 MLX、train、eval、verify，只写 reports/V9-P47/。\n"
            "已知事实（一级已核）：prereg.py:393-394 的 effective_metadata.equivariant_source 写着"
            "“analytic normalisation (G3 estimated pose + covariance-injected error)”；"
            "arms.py 没有导入 ainerzero.v9.geometry 或 canonical，用的是自写的 yaw 积分（:127-141、:320-331）。\n"
            "逐项回答并给 file:line：\n"
            "1. S1 各臂做规范化用的位姿估计来自哪里，是否就是 G3 canonicalize。\n"
            "2. “协方差注入误差”在 S1 数据或运行路径里是否实现，来源（例如 AWZ sensing/noise.py）与量级。\n"
            "3. 真值位姿规范化有没有在任何计分路径上被使用。\n"
            "4. r13 冻结件 artifacts/v9/s1/phase1/r13/pre_registration.json 与 r14 申请是否沿用同一表述。\n"
            "5. 哪些第一阶段结论依赖这条表述。\n"
            "6. 建议的最小修正：改表述，或最小实现改动。不得改冻结值。\n"
            "结论抄送 S1 主责（claude-az；COORDINATION 10-26 节 G1 为 codex），供用户批准 r14 前参考。"
        ),
        "acceptance": "六项逐条结论与 file:line 证据；明确是否建议在 r14 冻结前修正。",
        "params": {"level": "L2", "excluded_agents": ["deepseek-v41-p7k2", "deepseek-v41f-r9x2", "deepseek-p34x", "geminiflash-9a7c", "antigravity-v9k2"], "excluded_note": "S1 代码作者（P9/P13/P15/P34/P38）" + ALIAS, "zero_run": True},
    },
    {
        "key": "R11", "project": "ainerzero", "phase": "V9", "track": "R",
        "tier": 2, "kind": "implement", "ready": True, "needs": "text,code",
        "title": "【L2·文本·代码】研究注册表 r4：补登记 2026 前沿来源（CMFL 调研已核条目）＋校验器去掉 51 条硬编码",
        "scope": f"{AZ}/docs/research/ADAPTER_REGISTRY.md,{AZ}/docs/research/adapter_registry.json,{AZ}/reports/V9-R11/",
        "context": f"{AZ}/{REPORT},{AZ}/reports/frontier-integration-20261027/raw/,{AZ}/docs/research/ADAPTER_REGISTRY.md,{AZ}/docs/research/adapter_registry.json,{AZ}/reports/V9-R5/validate_registry_r5.py",
        "prompt": COMMON + (
            "0. 开工前把 r3 原字节归档到 reports/V9-R11/r3-archive/ 并写 SHA256SUMS。"
            "adapter_registry.json 应为 5c1564b0…、ADAPTER_REGISTRY.md 应为 332c5036…，不一致就停下报告。\n"
            "1. 补登记 REPORT.md §1.2 与 §1.3 列出的条目。已在册的 lewm、equivariant-trust-horizons 只追加更正说明"
            "（SIGReg 出自 LeJEPA 2511.08544；ETH 的 γ≥1 恒成立、漏了有限样本修正）。"
            "每条都要自己打开一手来源（arXiv abs、期刊页、GitHub LICENSE）核对；raw/ 只作线索，不作依据。"
            "字段沿用现有 schema，查不到的如实标“无法核”；分类按 REPORT.md §4（协议借鉴 / 自实现 / 待批准安装 / S2-S5 / 观察 / 排除）。"
            "发现与报告不一致的，以一手来源为准，并在交付报告里列出。\n"
            "2. 新写 reports/V9-R11/validate_registry_r4.py：期望 ID 从 json 推导，md 与 json 严格同步，不硬编码条数；"
            "默认只读交付物，提供 --root；不改 r5 校验器。\n"
            "3. 只读网页，不下载代码、权重或数据集。"
        ),
        "acceptance": "ainerzero.V9.R12 非作者复核建议通过。",
        "params": {"level": "L2", "r3_sha_json": "5c1564b0", "r3_sha_md": "332c5036"},
    },
    {
        "key": "R12", "project": "ainerzero", "phase": "V9", "track": "R",
        "tier": 2, "kind": "review", "ready": False, "needs": "text,code", "depends": "R11", "verifies": "R11",
        "title": "【L2·非作者复核】复核 ainerzero.V9.R11 注册表 r4 补登记与新校验器",
        "scope": f"{AZ}/reports/V9-R12/",
        "context": f"{AZ}/reports/V9-R11/,{AZ}/docs/research/ADAPTER_REGISTRY.md,{AZ}/docs/research/adapter_registry.json,{AZ}/{REPORT}",
        "prompt": COMMON + (
            "只读复核，报告写入 reports/V9-R12/：\n"
            "1. 随机抽 ≥10 条新增条目，自己从一手来源复核身份与全部许可断言。\n"
            "2. 校验器反例：md 与 json 不同步、重复 ID、缺必填字段，都必须变红；关闭对应检查后反例必须漏检。\n"
            "3. r3 归档 SHA 与 SHA256SUMS 一致；交付物在复核前后字节不变。"
        ),
        "acceptance": "三项逐条结论；明确 accept 或 request_changes。",
        "params": {"level": "L2", "excluded_note": "ainerzero.V9.R11 作者" + ALIAS},
    },
    {
        "key": "B12", "project": "ainerzero", "phase": "V9", "track": "B",
        "tier": 2, "kind": "implement", "ready": False, "needs": "code", "depends": "A12",
        "title": "【L3·强代理】【代码·守卫】按 ADR-0014 修补 SLOW 晋升证据：PromotionEvidence v2、Fragment 来源/对象/动作键、撤销与降级",
        "scope": f"{AZ}/src/ainerzero/v9/interfaces/,{AZ}/src/ainerzero/v9/fakes/spatial_memory.py,{AZ}/tests/v9/contracts/,{AZ}/reports/V9-B12/",
        "context": f"{AWZ}/docs/adr/ADR-0014-constrained-mechanism-formation.md,{AZ}/{DESIGN},{AZ}/src/ainerzero/v9/interfaces/types.py,{AZ}/src/ainerzero/v9/interfaces/validation.py,{AZ}/src/ainerzero/v9/interfaces/spatial_memory.py",
        "prompt": COMMON + (
            "草稿：等 ainerzero.V9.A12 审议通过、ADR-0014 定稿后由一级放出，届时以 ADR 正文为准。现已确定的要点：\n"
            "1. 现状缺陷（types.py:458-477、validation.py:268-299）：producer=\"student\"（类别 self）可以通过，等于学生自证；"
            "producer 是自报字符串；Fragment 缺 ARCH §2 要求的来源、对象、动作键；接口没有撤销与降级。\n"
            "2. 必须只读调用 validation.validate_producer 作为唯一登记表权威并在其上扩展，不得另建一套登记表；"
            "producer 改为由可信上下文绑定（照 teacher_cache 的 trusted_context / admission_bindings 做法）。\n"
            "3. PromotionEvidence v2 字段按 ADR：适用域引用、校准（方法、α、n_cal、可交换性自检引用）、"
            "错误接受控制（在线 FDR 状态引用、尝试数 N）、反例引用、知识起源类别、发现数据与测试数据身份（强制不相交）、"
            "式 6 回归引用、条目摘要与编码器版本校验。\n"
            "4. 公共接口变化：同步合同测试与迁移说明；未入 git 的接口文件开工前先记 SHA。"
        ),
        "acceptance": "ainerzero.V9.B13 非作者对抗复核建议通过，含拆守卫坏控。",
        "params": {"level": "L3", "authority_modules": ["interfaces/validation.py:validate_producer"]},
    },
    {
        "key": "B13", "project": "ainerzero", "phase": "V9", "track": "B",
        "tier": 2, "kind": "review", "ready": False, "needs": "code", "depends": "B12", "verifies": "B12",
        "title": "【L3·强代理】【非作者·对抗复核】复核 ainerzero.V9.B12 晋升证据修补",
        "scope": f"{AZ}/reports/V9-B13/",
        "context": f"{AZ}/reports/V9-B12/,{AWZ}/docs/adr/ADR-0014-constrained-mechanism-formation.md",
        "prompt": COMMON + (
            "草稿，随 B12 一起放出。要点：学生自证证据必须被拒；发现数据与测试数据有交集必须被拒；"
            "LLM 或教师起源的条目换一个合法 producer 也不能晋升；撤销后查询不再返回该条目。"
            "每条守卫都要在隔离副本里只改守卫条件做坏控，对应反例必须由拒绝翻成通过；普通负例与坏控分开记账。"
        ),
        "acceptance": "逐条结论与坏控证据；明确 accept 或 request_changes。",
        "params": {"level": "L3", "excluded_note": "ainerzero.V9.B12 作者" + ALIAS},
    },
    {
        "key": "G7", "project": "ainerzero", "phase": "V9", "track": "G",
        "tier": 2, "kind": "implement", "ready": False, "needs": "code,math", "depends": "A12",
        "title": "【L3·强代理】【代码·数学·CPU】CMFL 原型：机制充分性门、参数辨识、弱形式稀疏回归、单侧晋升门（合成玩具力学，纯 NumPy）",
        "scope": f"{AZ}/src/ainerzero/v9/mechanism/,{AZ}/tests/v9/mechanism/,{AZ}/reports/V9-G7/",
        "context": f"{AWZ}/docs/adr/ADR-0014-constrained-mechanism-formation.md,{AZ}/{DESIGN},{AZ}/src/ainerzero/v9/geometry/",
        "prompt": COMMON + (
            "草稿：等 ADR-0014 定稿后由一级放出，以 ADR 正文为准。现已确定的要点：\n"
            "1. 新包 src/ainerzero/v9/mechanism/，只用 NumPy，不导入 MLX，不装新包；GeometryCore 不改。\n"
            "2. 玩具世界（1D/2D 质点）：重力、线性与二次阻力、库仑摩擦、弹簧。四族：P 只有参数偏差；S 先验缺一项；"
            "N 只有积分误差；改动定律（如 1/r 引力）。另设负对照：候选库缺项时晋升准入率应为 0。"
            "真实路由标签只给评测，不进任何判定输入。\n"
            "3. 实现：MSG 七路由（阈值由冻结配置给出）；参数辨识（增广滤波或带协方差的最小二乘）；"
            "Fisher 信息与高斯 EIG；弱形式 STLSQ 加 data thinning；残差与 ∂F/∂φ 正交投影；"
            "单侧晋升门（配对 bootstrap 优越性、带有限样本修正的共形包络、逐例不回归、发现与测试数据不相交）。\n"
            "4. 报告：MSG 混淆矩阵、φ 的 NEES 校准、发现恢复率、负对照的错误准入率。全部是 CPU 测试，不训练。"
        ),
        "acceptance": "ainerzero.V9.G8 非作者对抗复核建议通过。",
        "params": {"level": "L3", "numpy_only": True},
    },
    {
        "key": "G8", "project": "ainerzero", "phase": "V9", "track": "G",
        "tier": 2, "kind": "review", "ready": False, "needs": "code,math", "depends": "G7", "verifies": "G7",
        "title": "【L3·强代理】【非作者·对抗复核】复核 ainerzero.V9.G7 CMFL 原型",
        "scope": f"{AZ}/reports/V9-G8/",
        "context": f"{AZ}/reports/V9-G7/,{AWZ}/docs/adr/ADR-0014-constrained-mechanism-formation.md",
        "prompt": COMMON + (
            "草稿，随 G7 一起放出。要点：自己写独立的玩具生成器；坏控至少包括——调换 PARAMETRIC 与 STRUCTURAL 的判定顺序、"
            "去掉共形有限样本修正、让发现与测试数据重叠、去掉正交投影，对应测试都必须变红；负对照准入率必须为 0。"
        ),
        "acceptance": "逐条结论与坏控证据；明确 accept 或 request_changes。",
        "params": {"level": "L3", "excluded_note": "ainerzero.V9.G7 作者" + ALIAS},
    },
    {
        "key": "P48", "project": "ainerzero", "phase": "V9", "track": "P",
        "tier": 1, "kind": "design", "ready": False, "needs": "text,math", "depends": "A12,awzB21,P47",
        "title": "【一级·预登记草案】S1 第二阶段：E1 四组＋增补臂 ⑤⑥⑦（⑧可选）与 P/S 两族世界（待 S1 第一阶段过门与用户批准预算）",
        "scope": f"{AZ}/reports/V9-P48/",
        "context": f"{AZ}/{DESIGN},{AZ}/ARCHITECTURE_V9.md",
        "prompt": COMMON + (
            "草稿，一级占位。前置：ADR-0014 定稿、E0 真值修复（awz.V9.B21）通过、P47 审计结论、S1 第一阶段过门，"
            "并由用户批准第二阶段训练预算。E1 原门槛不改；新臂与世界族逐项预登记数据、预算、种子与指标；"
            "另须处理 E0 的 60 fps 对 120 Hz 对齐与 Z-up 到重力坐标的映射。"
        ),
        "acceptance": "预登记草案经非作者复核，用户批准预算后才可放出执行卡。",
        "params": {"level": "tier1"},
    },
]


def main(dry: bool) -> None:
    ids: dict[str, str] = {}
    for card in CARDS:
        prompt_path = HERE / f"{card['key']}.md"
        prompt_path.write_text(card["title"] + "\n\n" + card["prompt"] + "\n\n验收：" + card["acceptance"] + "\n", encoding="utf-8")
        cmd = [RELAY, "--agent", "claude", "--json", "create",
               "--project", card["project"], "--phase", card["phase"], "--track", card["track"],
               "--title", card["title"], "--tier", str(card["tier"]), "--kind", card["kind"],
               "--prompt-file", str(prompt_path), "--params", json.dumps(card["params"], ensure_ascii=False),
               "--acceptance", card["acceptance"], "--context", card["context"], "--scope", card["scope"],
               "--needs", card["needs"], "--dedupe", "cmfl-20261028-" + card["key"]]
        if card.get("depends"):
            cmd += ["--depends", ",".join(ids[d] for d in card["depends"].split(","))]
        if card.get("verifies"):
            cmd += ["--verifies", ",".join(ids[d] for d in card["verifies"].split(","))]
        if card.get("ready"):
            cmd.append("--ready")
        if dry:
            print("DRY", card["key"], " ".join(c if len(c) < 60 else c[:57] + "..." for c in cmd[4:12]))
            ids[card["key"]] = "<" + card["key"] + ">"
            continue
        out = subprocess.run(cmd, capture_output=True, text=True)
        if out.returncode != 0:
            print("FAILED", card["key"], out.stdout[-800:], out.stderr[-800:])
            sys.exit(1)
        lines = [l for l in out.stdout.splitlines() if l.strip().startswith("{")]
        data = json.loads(out.stdout[out.stdout.index("{"):]) if lines or "{" in out.stdout else {}
        task_id = data.get("id") or data.get("task", {}).get("id")
        ids[card["key"]] = task_id
        print("CREATED", card["key"], task_id, data.get("status") or data.get("task", {}).get("status"))
    (HERE / "created_ids.json").write_text(json.dumps(ids, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main("--dry-run" in sys.argv)
