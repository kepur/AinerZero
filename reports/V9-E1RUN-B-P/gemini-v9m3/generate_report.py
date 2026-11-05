import json
from pathlib import Path

out_dir = Path("reports/V9-E1RUN-B-P/gemini-v9m3")
with open(out_dir / "metrics.json", encoding="utf-8") as f:
    m = json.load(f)

lines = []
lines.append("# 任务 ainerzero.V9.P100 执行报告：E1 运行卡 B-P（训练 P 族 9 格）")
lines.append("")
lines.append("- **任务卡号**：`ainerzero.V9.P100`")
lines.append("- **执行者**：`gemini-v9m3`（二级执行 agent，Tier 2）")
lines.append("- **实验阶段**：AinerZero V9 E1 Phase 2（P 族 9 格串行训练）")
lines.append("- **执行原则**：严格串行、CLI 唯一入口、relay exec 进程组监督、显式按格预留、严格防撞熔断守卫、零 final-eval、零源码修改")
lines.append("- **统筹授权**：`RESEARCH_LOG.md` 批准行 `R20261029-E1-approval`（第 2106 行），预算 `R20261102-E1-go-ahead`（5 h），预留与顺序裁定 `R20261103-E1-reservation-budget`")
lines.append("")
lines.append("---")
lines.append("")
lines.append("## 一、前置环境与身份校验（Pre-flight Verify）")
lines.append("")
lines.append("在正式启动训练前，通过 `relay exec` 运行了前置校验命令：")
lines.append("```bash")
lines.append("relay exec ainerzero.V9.P100 --agent gemini-v9m3 -- .venv/bin/python -m ainerzero.cli e1-phase2 --mode verify")
lines.append("```")
lines.append("校验结果全绿通过：")
lines.append("- `status`: `verified`")
lines.append("- `document_sha256`: `db75d096a048b505718690c6aec4d4f8a4d2cede4d0b32658fd395eb7c5beafd`")
lines.append("- `approval.status`: `approved`（行号 2106）")
lines.append("- `identity.status`: `passed`（16 个源代码模块与 8 个生成器代码 SHA-256 校验全部匹配）")
lines.append("")
lines.append("---")
lines.append("")
lines.append("## 二、P 族 9 格训练执行汇总表")
lines.append("")
lines.append("严格按照一级参数 `budget_override_20261103` 规定的重型优先顺序执行：")
lines.append("`(6,42) -> (6,43) -> (6,44) -> (2,42) -> (2,43) -> (2,44) -> (3,42) -> (3,43) -> (3,44)`。")
lines.append("")
lines.append("| 格次 | 单元 (臂/族/种子) | 账本 run_id | 预留 (s) | 实际墙钟 (s) | 熔断线 (s) | 退出码 | 步数 (总/最佳/早停) | 均值损失 | 终值损失 | Checkpoint 权重 SHA-256 (前16位) | 状态 |")
lines.append("| :--- | :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :--- | :---: |")

for idx, c in enumerate(m["cells"], 1):
    arm = c["arm"]
    fam = c["family"]
    seed = c["seed"]
    cell_tag = f"({arm}, {fam}, {seed})"
    rid = c["run_id"][:8] + ".."
    b_s = c["wall_budget_seconds"]
    w_s = f"{c['actual_wall_seconds']:.1f}"
    thresh = "1000.0" if arm == 6 else "400.0"
    ec = c["exit_code"]
    steps_info = f"{c['steps_completed']} / {c['best_step']} / {c['stopped_step']}"
    m_loss = f"{c['mean_loss']:.4f}"
    f_loss = f"{c['final_loss']:.4f}"
    sha = c["checkpoint_weights_sha256"][:16] + ".."
    st = "completed" if ec == 0 else "failed"
    lines.append(f"| {idx} | {cell_tag} | `{rid}` | {b_s} | {w_s} | {thresh} | {ec} | {steps_info} | {m_loss} | {f_loss} | `{sha}` | {st} |")

lines.append("")
lines.append("---")
lines.append("")
lines.append("## 三、完整 Checkpoint 产物与 SHA-256 凭证")
lines.append("")
lines.append("所有 Checkpoint 均按规格写入 `artifacts/v9/e1/phase2/checkpoints/` 且包含 `model_weights.npz`、`normalization.npz` 与 `checkpoint_meta.json`：")
lines.append("")

for c in m["cells"]:
    arm = c["arm"]
    fam = c["family"]
    seed = c["seed"]
    ckpt_path = Path(c["checkpoint_path"])
    lines.append(f"### 单元 ({arm}, {fam}, {seed})")
    lines.append(f"- **目录**：`{ckpt_path.parent}`")
    lines.append(f"- **model_weights.npz SHA-256**：`{c['checkpoint_weights_sha256']}`")
    lines.append(f"- **normalization.npz SHA-256**：`{c['checkpoint_normalization_sha256']}`")
    lines.append(f"- **run_id**：`{c['run_id']}`")
    lines.append(f"- **best_step**：`{c['best_step']}`，**stopped_step**：`{c['stopped_step']}`（早停机制触发生效）")
    lines.append("")

lines.append("---")
lines.append("")
lines.append("## 四、预算管理与防撞熔断守卫验证")
lines.append("")
lines.append("1. **防撞熔断守卫**：")
lines.append("   - 臂 6 阈值 1000s：实际分别为 842.8s、965.8s、962.6s，全部低于 1000s 保护线。")
lines.append("   - 臂 2/3 阈值 400s：实际分别为 191.0s、304.5s、206.6s、137.8s、210.7s、206.3s，全部低于 400s 保护线。")
lines.append("   - 9 格实际总运行墙钟：**4028.1s**（约 67.1 分钟）。")
lines.append("")
lines.append("2. **中央账本累计预留额度核对（`artifacts/v9/e1/phase2/control.sqlite3`）**：")
lines.append("   - 数据生成卡 P98 预留：`3600.0s`")
lines.append("   - 本卡 P100 训练 9 格预留：`3 × 1100s + 6 × 450s = 6000.0s`")
lines.append("   - 当前账本累计预留 active_seconds：`9600.0s`")
lines.append("   - 阶段实验总上限：`18000.0s`（5 小时），完全处于上限安全范围内（剩余额度 `8400.0s`，足够后续 S 族 9 格与 dev 评测）。")
lines.append("")
lines.append("3. **共享锁状态核对**：")
lines.append("   - 锁文件 `artifacts/locks/m0-worker.lock` 在每格训练间歇及 9 格训练结束后均已自动释放，内容为空，无任何进程挂留。")
lines.append("")
lines.append("---")
lines.append("")
lines.append("## 五、消极声明（未做事项）")
lines.append("")
lines.append("按照规范与安全守则，严正声明：")
lines.append("1. **绝对零 final-eval**：未执行任何 `--mode final-eval` 命令。")
lines.append("2. **绝对零封存数据触碰**：未以任何方式读取或打开 `artifacts/v9/e1/phase2/datasets/sealed_final/` 下的数据文件。")
lines.append("3. **绝对零源码修改**：未修改 `src/`、`tests/`、`prereg.json` 或 `RESEARCH_LOG.md`。")
lines.append("4. **唯一入口**：所有训练均由 `.venv/bin/python -m ainerzero.cli e1-phase2` 权威入口触发，并由 `relay exec` 绑定监督拉起，未绕过 CLI，未另起未监督进程。")
lines.append("5. **无云 GPU/付费/外部依赖**：全部计算在本机单实例串行完成，无外部下载与网络请求。")
lines.append("")

content = "\n".join(lines) + "\n"
(out_dir / "REPORT.md").write_text(content, encoding="utf-8")
(out_dir / "报告.md").write_text(content, encoding="utf-8")
print("REPORT.md and 报告.md written successfully.")
