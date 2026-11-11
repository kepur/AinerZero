# ainerzero.V9.P223 执行报告：仓库卫生盘点（98 项未提交路径出处与处置建议）
角色：executor；负责人：gemini-f8a3；时间：2026-11-11
任务状态：reported；实验状态：completed（纯 CPU 只读核对与盘点分析，零真实训练，零 GPU，不动工作区现有文件）
任务依据：任务 ainerzero.V9.P223 规格、COORDINATION.md、RESEARCH_LOG.md、AGENTS.md 工作规则
输入身份：工作区 HEAD `95bac00`，98 项未提交路径，`reports/git-batch-commit-20261105/` 排除台账，中央 relay-board JSON
修改文件：仅新增 `reports/repo-hygiene-20261111/`（REPORT.md、metrics.json、SHA256SUMS.txt 及 evidence/）；严格零修改已有代码/报告/基线
实际执行：`python3 /tmp/generate_hygiene_report.py` 对 98 项未提交路径全面采集 stat、出处卡号、代理、运行身份、引用关系及敏感信息
验证结果：98 项路径 100% 查清出处与状态；其中已验收任务 98 项、打回 0、失败 0、取消 0；给出四分类建议（提交 7 项、加入 .gitignore 35 项、保留不提交 55 项、候选删除 1 项）
产物：`reports/repo-hygiene-20261111/REPORT.md`、`metrics.json`、`SHA256SUMS.txt`、`evidence/`（包含 git status、du、relay show、citations、sensitive 扫描原始数据）
失败与限制：纯只读分析，未对实盘执行任何 git add、git rm、git checkout 或文件修改操作；具体入库与删除操作由一级统筹确认后执行
交回统筹：交一级统筹审阅处置清单；特别注意审查建议提交的 7 项报告与关键指纹，以及候选删除的 1 项临时测试软链接

---

## 摘要（30 行内）

- **背景与目标**：`git status --short` 存在 98 项未提交路径。本任务逐项查清其物理属性、接力卡号、产生代理、运行身份、验收状态、报告引用与敏感信息，输出建议清单，严格不动任何文件。
- **盘点概况**：98 项未跟踪路径覆盖 26 个目录分组，全部对应已在接力台亮绿灯验收（`accepted`）的任务产物。
- **四分类处置建议**：
  1. **提交（7 项）**：报告已引用或关键验收交付物（如 `PRE-DATASETS.sha256`、`gemini-loop-20261106`、`S4-P2-DESIGN/r1-review`，以及 `W9~W12` 复核报告 markdown/指标）；
  2. **加入 .gitignore（35 项）**：全部位于 `reports/V9-B3-mlx-unitcost/`，系 pytest 运行夹具生成的 `*current` 软链接（30 个）与 `*0/` 临时目录（5 个），纯属可再生临时产物；
  3. **保留不提交（55 项）**：大文件（>1 MB 至 27 MB，包含 25 个 `artifacts_stat_*.json` 封闭性快照、26 个 dev 评测原始日志、多份数据集 jsonl/PyPI 缓存），属于已验收证据本体，应留在本机不入库；
  4. **候选删除（1 项）**：`reports/V9-P25/.tmp-r1/sabotage-host/artifacts`，系 P25 探针 `r1_probe.py` 残留的软链接，指向绝对机器路径，无报告引用且可再生，建议一级批准后删除。
- **高优先级标出**：
  - **报告引用但未提交**：`PRE-DATASETS.sha256`（被 RESEARCH_LOG 及 CARD-P105/REVIEW-P105 引用）、`S4-P2-DESIGN/r1-review/`（被 RESEARCH_LOG 及 r1-review-b 引用）、`V9-S2-W9~W12/review/`（被相应卡及台账引用）；
  - **敏感信息**：共 62 处包含本机路径（如绝对软链接指向或执行日志首行 `/Users/mac/...`），4 处包含 PyPI 官方元数据公开邮箱；零私有令牌/密钥泄露。
- **合规自证**：零修改、零移动、零删除工作区文件；未写 `artifacts/`，零 GPU/MLX 运行，零外部网络访问。

---

## 一、盘点总体统计

| 分类建议 | 路径项数 | 总占用空间（真实物理） | 文件数 | 说明 |
|---|---:|---:|---:|---|
| **提交** | 7 | ~1.4 MB | 61 | 核心交付报告、被引用证据与提示词模板 |
| **加入 .gitignore** | 35 | ~1.3 KB | 40 | pytest 运行时生成的临时软链接与夹具目录 |
| **保留不提交** | 55 | ~688.2 MB | 106 | 超过 1 MB 的原始日志、封闭性 stat 快照与数据集 |
| **候选删除** | 1 | 44 B | 1 | 探针测试残留的单条绝对路径软链接 |
| **合计** | **98** | **~689.6 MB** | **208** | 全部 98 项未跟踪路径（注：软链接未递归计算宿主） |

### 关联任务与业务线分布

- **B 线（基线与测量）**：35 项（V9-B3-mlx-unitcost，卡号 `ainerzero.V9.P28`，pytest 临时产物）
- **E1 线（发育实验 1）**：12 项（V9-E1-A1、V9-E1R2-RUN-D/T、V9-E1RUN-B-P/S，卡号 `P100`、`P101`、`P104`、`P105`、`P107`、`P108`）
- **S1 线（空间时空 1）**：16 项（V9-P25、V9-P44、V9-P52、V9-P9、V9-S1-final，卡号 `P9`、`P25`、`P44`、`P52`、`P61/P62`）
- **S2 线（时空进阶 2）**：17 项（V9-S2-P118、P122、W4、W6b、W7、W8、W9、W10、W11、W12，卡号 `P118/119`、`P122/123`、`P169`、`P176`、`P178`、`P181`、`P183`、`P185`、`P190`、`P195`）
- **S4 线（时空架构 4）**：1 项（V9-S4-P2-DESIGN/r1-review，卡号 `ainerzero.V9.P215`）
- **基线与测试封闭（Hermetic）**：13 项（V9-baseline/r4、test-hermetic-20261106，卡号 `A2`、`A15`、`A17`、`A19`、`A21`）
- **教师线（Teachers）**：5 项（teachers-install-download-20261020，卡号 `T21`）
- **统筹协调（Coordination）**：1 项（coordination/gemini-loop-20261106，一级 claude 模板）

---

## 二、可直接执行的建议清单

### 1. 建议提交入库清单（共 7 项路径）

> 适用：已验收任务交付物，或被 `RESEARCH_LOG.md` / 已有报告强引用的核心材料。

```bash
# 建议提交命令（由一级执行）：
git add reports/coordination/gemini-loop-20261106/GEMINI_PROMPT.md
git add reports/V9-S4-P2-DESIGN/r1-review/
git add reports/V9-E1-A1/PRE-DATASETS.sha256
# 对于 W9~W12，仅提交 review/ 目录下的 markdown 报告与轻量 json（排除 23~27MB 的 artifacts_stat_*.json）：
git add reports/V9-S2-W9/review/REVIEW.md reports/V9-S2-W9/review/*.txt reports/V9-S2-W9/review/spot_checks.json reports/V9-S2-W9/review/metrics.json reports/V9-S2-W9/review/artifacts_diff.json reports/V9-S2-W9/review/mutations_summary.json
git add reports/V9-S2-W10/review/REVIEW.md reports/V9-S2-W10/review/*.txt reports/V9-S2-W10/review/spot_checks.json reports/V9-S2-W10/review/metrics.json reports/V9-S2-W10/review/artifacts_diff.json reports/V9-S2-W10/review/mutations_summary.json
git add reports/V9-S2-W11/review/REVIEW.md reports/V9-S2-W11/review/*.txt reports/V9-S2-W11/review/spot_checks.json reports/V9-S2-W11/review/metrics.json reports/V9-S2-W11/review/artifacts_diff.json reports/V9-S2-W11/review/mutations_summary.json
git add reports/V9-S2-W12/review/REVIEW.md reports/V9-S2-W12/review/*.txt reports/V9-S2-W12/review/spot_checks.json reports/V9-S2-W12/review/metrics.json reports/V9-S2-W12/review/artifacts_diff.json reports/V9-S2-W12/review/mutations_summary.json reports/V9-S2-W12/review/branch_analysis.json
```

### 2. 建议追加到 `.gitignore` 的规则清单

> 适用：pytest 运行中生成的 `*current` 临时软链接及 `*0/` 临时测试目录，完全由 pytest 夹具自动生成且可再生。

```gitignore
# 追加到 .gitignore 规则：
# pytest tmp_path 运行时软链接与临时测试夹具
reports/V9-B3-mlx-unitcost/**/test_*current
reports/V9-B3-mlx-unitcost/**/test_*0/
```

### 3. 建议保留不提交的清单及理由（共 55 项）

> 适用：属于已验收任务的原始凭据、stdout 日志、全量数据集或 hermetic 封闭性快照。由于体积大（单文件 >1 MB 至 27 MB）或包含大量本机路径，不应提交污染 git 仓库，但**严禁删除**，应永久保留在本机工作区。

- **测试封闭性快照（25 项，12~27 MB/个）**：
  - `reports/V9-S2-P118/artifacts_stat_{before,after}.json` (19.1 MB)
  - `reports/V9-S2-P122/artifacts_stat_{before,after}.json` (18.2 MB)
  - `reports/V9-S2-W4/review/artifacts_stat_{before,after}.json` (12.4 MB)
  - `reports/V9-S2-W6b/review/artifacts_stat_{before,after}.json` (20.9 MB)
  - `reports/V9-S2-W7/review/artifacts_stat_{before,after}.json` (16.1 MB)
  - `reports/V9-S2-W8/review/artifacts_stat_{before,after}.json` (21.2 MB)
  - `reports/V9-S2-W9~W12/review/artifacts_stat_{before,after}.json` (23.2~27.6 MB)
  - `reports/test-hermetic-20261106/{,r2/,r3/,r3b/}artifacts_stat_{before,after}.json` (15.4~19.1 MB)
  - `reports/V9-baseline/r4/{,r2/}stat_{before,after}.json` (14.6~15.4 MB)
  - *理由*：记录测试前后实盘 70,000+ 文件的 stat 快照，用于确证实盘零写入，已在 `post-intake-20261106.tsv` 登记。
- **原始执行 stdout / 进度日志（14 项，1~45 MB）**：
  - `reports/V9-E1R2-RUN-D/gemini-k7x3/raw_logs/` (26 个 cell 日志，45.1 MB)
  - `reports/V9-E1R2-RUN-T/gemini-m9x1/raw_stdout_cell_*.txt` (5 个 cell 日志，7.8 MB)
  - `reports/V9-E1RUN-B-P/gemini-v9m3/progress.json` (1.77 MB)
  - `reports/V9-E1RUN-B-S/gemini-e8x1/{progress.json, raw_output_*.txt}` (4 个文件，6.4 MB)
  - `reports/V9-S1-final/final-eval-stdout.json` (2.37 MB)
  - *理由*：真实 MLX 运行与 dev 评测全量原始输出，指标已被同目录已提交报告引用，原始日志作为底据留存。
- **归档数据集与证据清单（16 项，1~8 MB）**：
  - `reports/V9-P44/{jobs-summary.json, raw/*}` (7 个文件，16.3 MB)
  - `reports/V9-P9/{r1-archive/dataset/*, r2/dataset_manifest.json}` (5 个文件，17.0 MB)
  - `reports/V9-P52/gemini-b4e7/isolated/phase1_copy/train_report.json` (1.84 MB)
  - `reports/teachers-install-download-20261020/20261020T181817/pypi-*.json` (5 个文件，12.5 MB)
  - `reports/V9-baseline/r4/{baseline_manifest.json, r3-verify-before.json}` (2 个文件，5.4 MB)
  - *理由*：S1 预登记数据/真值 jsonl、离线 PyPI 元数据缓存与基线清单全集，已在分批入库 TSV 中登记。

### 4. 建议候选删除清单（共 1 项）

> 适用：纯属测试过程中产生的多余临时残留，无任何报告引用，可由测试脚本再生，且包含本机绝对路径。

```bash
# 候选删除路径（由一级统筹决定并执行）：
reports/V9-P25/.tmp-r1/sabotage-host/artifacts
# 说明：系 P25 探针脚本 r1_probe.py 执行破坏性测试时建立的单条软链接（44 字节），目标指向绝对路径 /Users/mac/AinerWorkFlow/AinerZero/artifacts；无任何报告引用，重新运行探针会自动重建。
```

---

## 三、特别标注项

### 1. 报告引用但未提交的文件（最该提交）

| 路径 | 引用来源报告 / 文件 | 出处任务卡号 | 建议处理 |
|---|---|---|---|
| `reports/V9-E1-A1/PRE-DATASETS.sha256` | `RESEARCH_LOG.md` (L2317 等)、`CARD-P105.md`、`REVIEW-P105.md` | `ainerzero.V9.P104/P105` | **建议提交**（1.02 MB，纯文本哈希指纹，不应因微弱超出 1MB 被弃） |
| `reports/V9-S4-P2-DESIGN/r1-review/` | `RESEARCH_LOG.md` (L3531)、`r1-review-b/REPORT.md` (L9) | `ainerzero.V9.P215` | **建议提交**（全目录仅 325 KB，无大文件，是 r1-review-b 输入底据） |
| `reports/V9-S2-W9/review/` | `RESEARCH_LOG.md` (L2693)、任务卡 `ainerzero.V9.P183` | `ainerzero.V9.P183` | **建议提交**（提交 markdown 与轻量 json 证据，排除 23MB 快照） |
| `reports/V9-S2-W10/review/` | `RESEARCH_LOG.md` (L2693)、任务卡 `ainerzero.V9.P185` | `ainerzero.V9.P185` | **建议提交**（提交 markdown 与轻量 json 证据，排除 23MB 快照） |
| `reports/V9-S2-W11/review/` | 任务卡 `ainerzero.V9.P190` | `ainerzero.V9.P190` | **建议提交**（提交 markdown 与轻量 json 证据，排除 23MB 快照） |
| `reports/V9-S2-W12/review/` | 任务卡 `ainerzero.V9.P195` | `ainerzero.V9.P195` | **建议提交**（提交 markdown 与轻量 json 证据，排除 27MB 快照） |
| `reports/coordination/gemini-loop-20261106/` | 一级协同规范（对照 20261028 版） | 一级统筹 | **建议提交**（9.5 KB 提示词模板） |

### 2. 含敏感信息的文件与位置标出（不摘录敏感内容）

> 遵循工作规则：仅标出敏感信息的文件位置与类型，严禁把敏感内容抄入报告。

| 文件 / 路径 | 发现位置 | 敏感信息类别 | 安全建议 |
|---|---|---|---|
| `reports/V9-P25/.tmp-r1/sabotage-host/artifacts` | 软链接目标指向 (`symlink target`) | 本机绝对路径 (`/Users/mac/...`) | 建议删除该软链接 |
| `reports/V9-B3-mlx-unitcost/**/test_*current` (30 个) | 软链接目标指向 (`symlink target`) | 本机绝对路径 (`/Users/mac/...`) | 加入 `.gitignore`，不提交到远程 |
| `reports/coordination/gemini-loop-20261106/GEMINI_PROMPT.md` | 第 13、14 行 | 本机运行命令路径 (`/Users/mac/...`) | 统筹模板中建议后续使用环境变量或相对路径 |
| `reports/V9-E1R2-RUN-D/gemini-k7x3/raw_logs/*.log` (26 个) | 各文件前 1~5 行日志参数输出 | 本机执行路径 (`/Users/mac/...`) | 保留本机，不提交 |
| `reports/V9-E1R2-RUN-T/gemini-m9x1/raw_stdout_*.txt` (5 个) | 各文件头部命令输出 | 本机执行路径 (`/Users/mac/...`) | 保留本机，不提交 |
| `reports/V9-E1RUN-B-S/gemini-e8x1/raw_output_*.txt` (3 个) | 文件首行 | 本机执行路径 (`/Users/mac/...`) | 保留本机，不提交 |
| `reports/V9-P44/jobs-summary.json` 及 `raw/*` 日志 | 多处日志/命令配置字段 | 本机执行路径 (`/Users/mac/...`) | 保留本机，不提交 |
| `reports/teachers-install-download-20261020/**/pypi-*.json` | PyPI JSON `author_email` 字段 | 公开维护者邮箱地址 | 保留本机，不入库 |
| *全量文件扫描结果* | *全量扫描* | **零私有 API Key、零鉴权 Token、零密码** | 纯净，无安全凭证泄露风险 |

---

## 四、98 项未提交路径逐项盘点表

| # | 未提交路径 | 类型 | 大小/文件数 | 最后修改时间 | 出处卡号 · 代理 | 卡状态 | 建议分类 | 理由摘要 |
|---:|---|---|---:|---|---|---|---|---|
| 1 | `reports/V9-B3-mlx-unitcost/cpu-tests-pytest-r2/test_entire_cpu_dryrun_importscurrent` | 目录 | 113 B (1 个) | 2026-10-22 19:00:20 | `ainerzero.V9.P28` · codex-0fqn | accepted | **加入 .gitignore** | pytest tmp_path 临时软链接 |
| 2 | `reports/V9-B3-mlx-unitcost/cpu-tests-pytest-r2/test_failure_preserves_completcurrent` | 目录 | 113 B (1 个) | 2026-10-22 19:00:19 | `ainerzero.V9.P28` · codex-0fqn | accepted | **加入 .gitignore** | pytest tmp_path 临时软链接 |
| 3 | `reports/V9-B3-mlx-unitcost/cpu-tests-pytest-r2/test_final_path_refused_beforecurrent` | 目录 | 113 B (1 个) | 2026-10-22 19:00:18 | `ainerzero.V9.P28` · codex-0fqn | accepted | **加入 .gitignore** | pytest tmp_path 临时软链接 |
| 4 | `reports/V9-B3-mlx-unitcost/cpu-tests-pytest-r2/test_final_symlink_target_refu0/` | 目录 | 0 B (0 个) | 2026-10-22 19:00:18 | `ainerzero.V9.P28` · codex-0fqn | accepted | **加入 .gitignore** | pytest tmp_path 测试夹具临时目录 |
| 5 | `reports/V9-B3-mlx-unitcost/cpu-tests-pytest-r2/test_final_symlink_target_refucurrent` | 目录 | 113 B (1 个) | 2026-10-22 19:00:18 | `ainerzero.V9.P28` · codex-0fqn | accepted | **加入 .gitignore** | pytest tmp_path 临时软链接 |
| 6 | `reports/V9-B3-mlx-unitcost/cpu-tests-pytest-r2/test_unit_timer_waits_for_evalcurrent` | 目录 | 113 B (1 个) | 2026-10-22 19:00:18 | `ainerzero.V9.P28` · codex-0fqn | accepted | **加入 .gitignore** | pytest tmp_path 临时软链接 |
| 7 | `reports/V9-B3-mlx-unitcost/cpu-tests-pytest-r3/test_entire_cpu_dryrun_importscurrent` | 目录 | 113 B (1 个) | 2026-10-22 19:01:59 | `ainerzero.V9.P28` · codex-0fqn | accepted | **加入 .gitignore** | pytest tmp_path 临时软链接 |
| 8 | `reports/V9-B3-mlx-unitcost/cpu-tests-pytest-r3/test_failure_preserves_completcurrent` | 目录 | 113 B (1 个) | 2026-10-22 19:01:58 | `ainerzero.V9.P28` · codex-0fqn | accepted | **加入 .gitignore** | pytest tmp_path 临时软链接 |
| 9 | `reports/V9-B3-mlx-unitcost/cpu-tests-pytest-r3/test_final_path_refused_beforecurrent` | 目录 | 113 B (1 个) | 2026-10-22 19:01:57 | `ainerzero.V9.P28` · codex-0fqn | accepted | **加入 .gitignore** | pytest tmp_path 临时软链接 |
| 10 | `reports/V9-B3-mlx-unitcost/cpu-tests-pytest-r3/test_final_symlink_target_refu0/` | 目录 | 0 B (0 个) | 2026-10-22 19:01:57 | `ainerzero.V9.P28` · codex-0fqn | accepted | **加入 .gitignore** | pytest tmp_path 测试夹具临时目录 |
| 11 | `reports/V9-B3-mlx-unitcost/cpu-tests-pytest-r3/test_final_symlink_target_refucurrent` | 目录 | 113 B (1 个) | 2026-10-22 19:01:57 | `ainerzero.V9.P28` · codex-0fqn | accepted | **加入 .gitignore** | pytest tmp_path 临时软链接 |
| 12 | `reports/V9-B3-mlx-unitcost/cpu-tests-pytest-r3/test_real_mode_requires_freezecurrent` | 目录 | 113 B (1 个) | 2026-10-22 19:01:58 | `ainerzero.V9.P28` · codex-0fqn | accepted | **加入 .gitignore** | pytest tmp_path 临时软链接 |
| 13 | `reports/V9-B3-mlx-unitcost/cpu-tests-pytest-r3/test_unit_timer_waits_for_evalcurrent` | 目录 | 113 B (1 个) | 2026-10-22 19:01:58 | `ainerzero.V9.P28` · codex-0fqn | accepted | **加入 .gitignore** | pytest tmp_path 临时软链接 |
| 14 | `reports/V9-B3-mlx-unitcost/cpu-tests-pytest-r4/test_entire_cpu_dryrun_importscurrent` | 目录 | 113 B (1 个) | 2026-10-22 19:15:47 | `ainerzero.V9.P28` · codex-0fqn | accepted | **加入 .gitignore** | pytest tmp_path 临时软链接 |
| 15 | `reports/V9-B3-mlx-unitcost/cpu-tests-pytest-r4/test_failure_preserves_completcurrent` | 目录 | 113 B (1 个) | 2026-10-22 19:15:45 | `ainerzero.V9.P28` · codex-0fqn | accepted | **加入 .gitignore** | pytest tmp_path 临时软链接 |
| 16 | `reports/V9-B3-mlx-unitcost/cpu-tests-pytest-r4/test_final_path_refused_beforecurrent` | 目录 | 113 B (1 个) | 2026-10-22 19:15:44 | `ainerzero.V9.P28` · codex-0fqn | accepted | **加入 .gitignore** | pytest tmp_path 临时软链接 |
| 17 | `reports/V9-B3-mlx-unitcost/cpu-tests-pytest-r4/test_final_symlink_target_refu0/` | 目录 | 0 B (0 个) | 2026-10-22 19:15:44 | `ainerzero.V9.P28` · codex-0fqn | accepted | **加入 .gitignore** | pytest tmp_path 测试夹具临时目录 |
| 18 | `reports/V9-B3-mlx-unitcost/cpu-tests-pytest-r4/test_final_symlink_target_refucurrent` | 目录 | 113 B (1 个) | 2026-10-22 19:15:44 | `ainerzero.V9.P28` · codex-0fqn | accepted | **加入 .gitignore** | pytest tmp_path 临时软链接 |
| 19 | `reports/V9-B3-mlx-unitcost/cpu-tests-pytest-r4/test_real_mode_requires_freezecurrent` | 目录 | 113 B (1 个) | 2026-10-22 19:15:45 | `ainerzero.V9.P28` · codex-0fqn | accepted | **加入 .gitignore** | pytest tmp_path 临时软链接 |
| 20 | `reports/V9-B3-mlx-unitcost/cpu-tests-pytest-r4/test_real_worker_lock_io_boundcurrent` | 目录 | 113 B (1 个) | 2026-10-22 19:15:47 | `ainerzero.V9.P28` · codex-0fqn | accepted | **加入 .gitignore** | pytest tmp_path 临时软链接 |
| 21 | `reports/V9-B3-mlx-unitcost/cpu-tests-pytest-r4/test_unit_timer_waits_for_evalcurrent` | 目录 | 113 B (1 个) | 2026-10-22 19:15:45 | `ainerzero.V9.P28` · codex-0fqn | accepted | **加入 .gitignore** | pytest tmp_path 临时软链接 |
| 22 | `reports/V9-B3-mlx-unitcost/cpu-tests-pytest-r5/test_entire_cpu_dryrun_importscurrent` | 目录 | 113 B (1 个) | 2026-10-22 19:28:14 | `ainerzero.V9.P28` · codex-0fqn | accepted | **加入 .gitignore** | pytest tmp_path 临时软链接 |
| 23 | `reports/V9-B3-mlx-unitcost/cpu-tests-pytest-r5/test_failure_preserves_completcurrent` | 目录 | 113 B (1 个) | 2026-10-22 19:28:11 | `ainerzero.V9.P28` · codex-0fqn | accepted | **加入 .gitignore** | pytest tmp_path 临时软链接 |
| 24 | `reports/V9-B3-mlx-unitcost/cpu-tests-pytest-r5/test_final_path_refused_beforecurrent` | 目录 | 113 B (1 个) | 2026-10-22 19:28:10 | `ainerzero.V9.P28` · codex-0fqn | accepted | **加入 .gitignore** | pytest tmp_path 临时软链接 |
| 25 | `reports/V9-B3-mlx-unitcost/cpu-tests-pytest-r5/test_final_symlink_target_refu0/` | 目录 | 0 B (0 个) | 2026-10-22 19:28:10 | `ainerzero.V9.P28` · codex-0fqn | accepted | **加入 .gitignore** | pytest tmp_path 测试夹具临时目录 |
| 26 | `reports/V9-B3-mlx-unitcost/cpu-tests-pytest-r5/test_final_symlink_target_refucurrent` | 目录 | 113 B (1 个) | 2026-10-22 19:28:10 | `ainerzero.V9.P28` · codex-0fqn | accepted | **加入 .gitignore** | pytest tmp_path 临时软链接 |
| 27 | `reports/V9-B3-mlx-unitcost/cpu-tests-pytest-r5/test_real_mode_requires_freezecurrent` | 目录 | 113 B (1 个) | 2026-10-22 19:28:11 | `ainerzero.V9.P28` · codex-0fqn | accepted | **加入 .gitignore** | pytest tmp_path 临时软链接 |
| 28 | `reports/V9-B3-mlx-unitcost/cpu-tests-pytest-r5/test_real_worker_lock_io_boundcurrent` | 目录 | 113 B (1 个) | 2026-10-22 19:28:13 | `ainerzero.V9.P28` · codex-0fqn | accepted | **加入 .gitignore** | pytest tmp_path 临时软链接 |
| 29 | `reports/V9-B3-mlx-unitcost/cpu-tests-pytest-r5/test_returned_pose_predictionscurrent` | 目录 | 113 B (1 个) | 2026-10-22 19:28:11 | `ainerzero.V9.P28` · codex-0fqn | accepted | **加入 .gitignore** | pytest tmp_path 临时软链接 |
| 30 | `reports/V9-B3-mlx-unitcost/cpu-tests-pytest-r5/test_unit_timer_waits_for_evalcurrent` | 目录 | 113 B (1 个) | 2026-10-22 19:28:11 | `ainerzero.V9.P28` · codex-0fqn | accepted | **加入 .gitignore** | pytest tmp_path 临时软链接 |
| 31 | `reports/V9-B3-mlx-unitcost/cpu-tests-pytest/test_failure_preserves_completcurrent` | 目录 | 110 B (1 个) | 2026-10-22 18:58:59 | `ainerzero.V9.P28` · codex-0fqn | accepted | **加入 .gitignore** | pytest tmp_path 临时软链接 |
| 32 | `reports/V9-B3-mlx-unitcost/cpu-tests-pytest/test_final_path_refused_beforecurrent` | 目录 | 110 B (1 个) | 2026-10-22 18:58:58 | `ainerzero.V9.P28` · codex-0fqn | accepted | **加入 .gitignore** | pytest tmp_path 临时软链接 |
| 33 | `reports/V9-B3-mlx-unitcost/cpu-tests-pytest/test_final_symlink_target_refu0/` | 目录 | 0 B (0 个) | 2026-10-22 18:58:58 | `ainerzero.V9.P28` · codex-0fqn | accepted | **加入 .gitignore** | pytest tmp_path 测试夹具临时目录 |
| 34 | `reports/V9-B3-mlx-unitcost/cpu-tests-pytest/test_final_symlink_target_refucurrent` | 目录 | 110 B (1 个) | 2026-10-22 18:58:58 | `ainerzero.V9.P28` · codex-0fqn | accepted | **加入 .gitignore** | pytest tmp_path 临时软链接 |
| 35 | `reports/V9-B3-mlx-unitcost/cpu-tests-pytest/test_unit_timer_waits_for_evalcurrent` | 目录 | 110 B (1 个) | 2026-10-22 18:58:59 | `ainerzero.V9.P28` · codex-0fqn | accepted | **加入 .gitignore** | pytest tmp_path 临时软链接 |
| 36 | `reports/V9-E1-A1/PRE-DATASETS.sha256` | 文件 | 1.02 MB | 2026-11-03 11:22:35 | `ainerzero.V9.P104 / ainerzero.V9.P105` · gemini-k8m2 / gemini-x3n8 | accepted | **提交** | 已被 RESEARCH_LOG.md、CARD-P105.md、REVIEW-P105.md 强引用 |
| 37 | `reports/V9-E1R2-RUN-D/gemini-k7x3/raw_logs/` | 目录 | 45.11 MB (26 个) | 2026-11-05 22:12:18 | `ainerzero.V9.P108` · gemini-k7x3 | accepted | **保留不提交** | dev 评测 26 格全量原始 stdout 日志（共 45.1 MB） |
| 38 | `reports/V9-E1R2-RUN-T/gemini-m9x1/raw_stdout_cell_10_arm6_S_seed42.txt` | 文件 | 1.56 MB | 2026-11-05 20:35:30 | `ainerzero.V9.P107` · gemini-m9x1 | accepted | **保留不提交** | 重训格子原始 stdout 输出（单文件 >1 MB） |
| 39 | `reports/V9-E1R2-RUN-T/gemini-m9x1/raw_stdout_cell_11_arm6_S_seed43.txt` | 文件 | 1.63 MB | 2026-11-05 20:54:09 | `ainerzero.V9.P107` · gemini-m9x1 | accepted | **保留不提交** | 重训格子原始 stdout 输出（单文件 >1 MB） |
| 40 | `reports/V9-E1R2-RUN-T/gemini-m9x1/raw_stdout_cell_4_arm6_P_seed42.txt` | 文件 | 1.22 MB | 2026-11-05 19:41:25 | `ainerzero.V9.P107` · gemini-m9x1 | accepted | **保留不提交** | 重训格子原始 stdout 输出（单文件 >1 MB） |
| 41 | `reports/V9-E1R2-RUN-T/gemini-m9x1/raw_stdout_cell_5_arm6_P_seed43.txt` | 文件 | 1.66 MB | 2026-11-05 19:54:55 | `ainerzero.V9.P107` · gemini-m9x1 | accepted | **保留不提交** | 重训格子原始 stdout 输出（单文件 >1 MB） |
| 42 | `reports/V9-E1R2-RUN-T/gemini-m9x1/raw_stdout_cell_8_arm3_S_seed43.txt` | 文件 | 1.30 MB | 2026-11-05 20:14:47 | `ainerzero.V9.P107` · gemini-m9x1 | accepted | **保留不提交** | 重训格子原始 stdout 输出（单文件 >1 MB） |
| 43 | `reports/V9-E1RUN-B-P/gemini-v9m3/progress.json` | 文件 | 10.92 MB | 2026-11-03 01:31:26 | `ainerzero.V9.P100` · gemini-v9m3 | accepted | **保留不提交** | 训练 P 族过程进度快照（1.77 MB） |
| 44 | `reports/V9-E1RUN-B-S/gemini-e8x1/progress.json` | 文件 | 11.02 MB | 2026-11-05 08:58:21 | `ainerzero.V9.P101` · gemini-e8x1 | accepted | **保留不提交** | 训练 S 族过程进度与原始 stdout 日志（单文件 >1.4 MB） |
| 45 | `reports/V9-E1RUN-B-S/gemini-e8x1/raw_output_arm2_seed42.txt` | 文件 | 1.18 MB | 2026-11-05 08:37:18 | `ainerzero.V9.P101` · gemini-e8x1 | accepted | **保留不提交** | 训练 S 族过程进度与原始 stdout 日志（单文件 >1.4 MB） |
| 46 | `reports/V9-E1RUN-B-S/gemini-e8x1/raw_output_arm2_seed44.txt` | 文件 | 1.37 MB | 2026-11-05 08:45:46 | `ainerzero.V9.P101` · gemini-e8x1 | accepted | **保留不提交** | 训练 S 族过程进度与原始 stdout 日志（单文件 >1.4 MB） |
| 47 | `reports/V9-E1RUN-B-S/gemini-e8x1/raw_output_arm3_seed44.txt` | 文件 | 1.23 MB | 2026-11-05 08:58:21 | `ainerzero.V9.P101` · gemini-e8x1 | accepted | **保留不提交** | 训练 S 族过程进度与原始 stdout 日志（单文件 >1.4 MB） |
| 48 | `reports/V9-P25/.tmp-r1/sabotage-host/artifacts` | 目录 | 44 B (1 个) | 2026-10-27 09:19:28 | `ainerzero.V9.P25` · composer-m7k2 | accepted | **候选删除** | 测试探针 r1_probe.py 运行残留软链接 |
| 49 | `reports/V9-P44/jobs-summary.json` | 文件 | 4.73 MB | 2026-10-26 06:40:22 | `ainerzero.V9.P44` · cpu-review-p43-20261025 | accepted | **保留不提交** | P43 证据修订原始日志与清单（单文件 1~5 MB） |
| 50 | `reports/V9-P44/raw/dataset_manifest.json` | 文件 | 988.3 KB | 2026-10-26 06:40:22 | `ainerzero.V9.P44` · cpu-review-p43-20261025 | accepted | **保留不提交** | P43 证据修订原始日志与清单（单文件 1~5 MB） |
| 51 | `reports/V9-P44/raw/db-runs.json` | 文件 | 2.04 MB | 2026-10-26 06:40:22 | `ainerzero.V9.P44` · cpu-review-p43-20261025 | accepted | **保留不提交** | P43 证据修订原始日志与清单（单文件 1~5 MB） |
| 52 | `reports/V9-P44/raw/log-arm2-seed0-stdout.log` | 文件 | 1.97 MB | 2026-10-26 06:40:21 | `ainerzero.V9.P44` · cpu-review-p43-20261025 | accepted | **保留不提交** | P43 证据修订原始日志与清单（单文件 1~5 MB） |
| 53 | `reports/V9-P44/raw/log-arm2-seed1-stdout.log` | 文件 | 1.97 MB | 2026-10-26 06:40:22 | `ainerzero.V9.P44` · cpu-review-p43-20261025 | accepted | **保留不提交** | P43 证据修订原始日志与清单（单文件 1~5 MB） |
| 54 | `reports/V9-P44/raw/log-arm2-seed2-stdout.log` | 文件 | 1.97 MB | 2026-10-26 06:40:22 | `ainerzero.V9.P44` · cpu-review-p43-20261025 | accepted | **保留不提交** | P43 证据修订原始日志与清单（单文件 1~5 MB） |
| 55 | `reports/V9-P44/raw/log-arm3-seed0-stdout.log` | 文件 | 1.97 MB | 2026-10-26 06:40:22 | `ainerzero.V9.P44` · cpu-review-p43-20261025 | accepted | **保留不提交** | P43 证据修订原始日志与清单（单文件 1~5 MB） |
| 56 | `reports/V9-P52/gemini-b4e7/isolated/phase1_copy/train_report.json` | 文件 | 1.76 MB | 2026-10-28 11:48:52 | `ainerzero.V9.P52` · gemini-b4e7 | accepted | **保留不提交** | 隔离副本训练报告快照（1.84 MB） |
| 57 | `reports/V9-P9/r1-archive/dataset/dataset_manifest.json` | 文件 | 988.3 KB | 2026-10-21 08:46:50 | `ainerzero.V9.P9` · deepseek-v41-p7k2 | accepted | **保留不提交** | S1 第一阶段归档数据集与真值 jsonl（1~8 MB） |
| 58 | `reports/V9-P9/r1-archive/dataset/export_meta.json` | 文件 | 1.21 MB | 2026-10-21 08:46:46 | `ainerzero.V9.P9` · deepseek-v41-p7k2 | accepted | **保留不提交** | S1 第一阶段归档数据集与真值 jsonl（1~8 MB） |
| 59 | `reports/V9-P9/r1-archive/dataset/packets/train.jsonl` | 文件 | 7.82 MB | 2026-10-21 08:46:46 | `ainerzero.V9.P9` · deepseek-v41-p7k2 | accepted | **保留不提交** | S1 第一阶段归档数据集与真值 jsonl（1~8 MB） |
| 60 | `reports/V9-P9/r1-archive/dataset/truth/train.jsonl` | 文件 | 5.27 MB | 2026-10-21 08:46:46 | `ainerzero.V9.P9` · deepseek-v41-p7k2 | accepted | **保留不提交** | S1 第一阶段归档数据集与真值 jsonl（1~8 MB） |
| 61 | `reports/V9-P9/r2/dataset_manifest.json` | 文件 | 988.3 KB | 2026-10-21 09:57:04 | `ainerzero.V9.P9` · deepseek-v41-p7k2 | accepted | **保留不提交** | S1 第一阶段归档数据集与真值 jsonl（1~8 MB） |
| 62 | `reports/V9-S1-final/final-eval-stdout.json` | 文件 | 2.26 MB | 2026-10-28 16:15:08 | `ainerzero.V9.P61 / ainerzero.V9.P62` · gemini-b4e7 | accepted | **保留不提交** | S1 最终评测原始标准输出（2.37 MB） |
| 63 | `reports/V9-S2-P118/artifacts_stat_after.json` | 文件 | 18.24 MB | 2026-11-06 12:15:24 | `ainerzero.V9.P118 / ainerzero.V9.P119` · gemini-f8a2 / gemini-w4x2 | accepted | **保留不提交** | 测试封闭性 artifacts 快照（19.1 MB） |
| 64 | `reports/V9-S2-P118/artifacts_stat_before.json` | 文件 | 18.24 MB | 2026-11-06 12:11:40 | `ainerzero.V9.P118 / ainerzero.V9.P119` · gemini-f8a2 / gemini-w4x2 | accepted | **保留不提交** | 测试封闭性 artifacts 快照（19.1 MB） |
| 65 | `reports/V9-S2-P122/artifacts_stat_after.json` | 文件 | 17.33 MB | 2026-11-06 13:31:28 | `ainerzero.V9.P122 / ainerzero.V9.P123` · gemini-m7k4 / gemini-k4p9 | accepted | **保留不提交** | 测试封闭性 artifacts 快照（18.2 MB） |
| 66 | `reports/V9-S2-P122/artifacts_stat_before.json` | 文件 | 17.33 MB | 2026-11-06 13:27:07 | `ainerzero.V9.P122 / ainerzero.V9.P123` · gemini-m7k4 / gemini-k4p9 | accepted | **保留不提交** | 测试封闭性 artifacts 快照（18.2 MB） |
| 67 | `reports/V9-S2-W10/review/` | 目录 | 44.25 MB (10 个) | 2026-11-08 11:54:29 | `ainerzero.V9.P185` · gemini-k8d4 | accepted | **提交** | 已验收复核卡交付物目录（含 REVIEW.md、metrics.json 等核心报告证据）；建议将其中的报告及轻量证据提交入库 |
| 68 | `reports/V9-S2-W11/review/` | 目录 | 44.34 MB (9 个) | 2026-11-08 13:04:28 | `ainerzero.V9.P190` · gemini-k8d4 | accepted | **提交** | 已验收复核卡交付物目录（含 REVIEW.md、metrics.json 等核心报告证据）；建议将其中的报告及轻量证据提交入库 |
| 69 | `reports/V9-S2-W12/review/` | 目录 | 52.74 MB (9 个) | 2026-11-09 08:10:23 | `ainerzero.V9.P195` · gemini-k8d4 | accepted | **提交** | 已验收复核卡交付物目录（含 REVIEW.md、metrics.json 等核心报告证据）；建议将其中的报告及轻量证据提交入库 |
| 70 | `reports/V9-S2-W4/review/artifacts_stat_after.json` | 文件 | 11.82 MB | 2026-11-07 09:32:36 | `ainerzero.V9.P169` · gemini-7k2q | accepted | **保留不提交** | W4 复核 artifacts 快照（12.4 MB） |
| 71 | `reports/V9-S2-W4/review/artifacts_stat_before.json` | 文件 | 11.82 MB | 2026-11-07 09:28:45 | `ainerzero.V9.P169` · gemini-7k2q | accepted | **保留不提交** | W4 复核 artifacts 快照（12.4 MB） |
| 72 | `reports/V9-S2-W6b/review/artifacts_stat_after.json` | 文件 | 19.90 MB | 2026-11-07 10:56:27 | `ainerzero.V9.P178` · composer-m8k4 | accepted | **保留不提交** | W6b 复核 artifacts 快照（20.9 MB） |
| 73 | `reports/V9-S2-W6b/review/artifacts_stat_before.json` | 文件 | 19.90 MB | 2026-11-07 10:46:34 | `ainerzero.V9.P178` · composer-m8k4 | accepted | **保留不提交** | W6b 复核 artifacts 快照（20.9 MB） |
| 74 | `reports/V9-S2-W7/review/artifacts_stat_after.json` | 文件 | 15.36 MB | 2026-11-07 11:01:21 | `ainerzero.V9.P176` · composer-de00 | accepted | **保留不提交** | W7 复核 artifacts 快照（16.1 MB） |
| 75 | `reports/V9-S2-W7/review/artifacts_stat_before.json` | 文件 | 15.36 MB | 2026-11-07 11:01:21 | `ainerzero.V9.P176` · composer-de00 | accepted | **保留不提交** | W7 复核 artifacts 快照（16.1 MB） |
| 76 | `reports/V9-S2-W8/review/artifacts_stat_after.json` | 文件 | 20.23 MB | 2026-11-08 01:32:26 | `ainerzero.V9.P181` · gemini-k7m2 | accepted | **保留不提交** | W8 复核 artifacts 快照（21.2 MB） |
| 77 | `reports/V9-S2-W8/review/artifacts_stat_before.json` | 文件 | 20.23 MB | 2026-11-08 01:14:16 | `ainerzero.V9.P181` · gemini-k7m2 | accepted | **保留不提交** | W8 复核 artifacts 快照（21.2 MB） |
| 78 | `reports/V9-S2-W9/review/` | 目录 | 44.25 MB (9 个) | 2026-11-08 10:41:43 | `ainerzero.V9.P183` · gemini-k8d4 | accepted | **提交** | 已验收复核卡交付物目录（含 REVIEW.md、metrics.json 等核心报告证据）；建议将其中的报告及轻量证据提交入库 |
| 79 | `reports/V9-S4-P2-DESIGN/r1-review/` | 目录 | 310.4 KB (15 个) | 2026-11-11 11:46:50 | `ainerzero.V9.P215` · claude-s4p2rev-1111a | accepted | **提交** | P215 第一阶段复核脚本与证据（总共 325 KB |
| 80 | `reports/V9-baseline/r4/baseline_manifest.json` | 文件 | 3.15 MB | 2026-11-06 09:20:50 | `ainerzero.V9.A15 / ainerzero.V9.A2` · gemini-f8a2 / deepseek-v4f-k2m9 | accepted | **保留不提交** | 基线冻结大件清单与快照（2.1~15.4 MB） |
| 81 | `reports/V9-baseline/r4/r2/stat_after.json` | 文件 | 14.68 MB | 2026-11-06 10:04:48 | `ainerzero.V9.A15 / ainerzero.V9.A2` · gemini-f8a2 / deepseek-v4f-k2m9 | accepted | **保留不提交** | 基线冻结大件清单与快照（2.1~15.4 MB） |
| 82 | `reports/V9-baseline/r4/r2/stat_before.json` | 文件 | 14.68 MB | 2026-11-06 09:59:03 | `ainerzero.V9.A15 / ainerzero.V9.A2` · gemini-f8a2 / deepseek-v4f-k2m9 | accepted | **保留不提交** | 基线冻结大件清单与快照（2.1~15.4 MB） |
| 83 | `reports/V9-baseline/r4/r3-verify-before.json` | 文件 | 2.04 MB | 2026-11-06 09:04:09 | `ainerzero.V9.A15 / ainerzero.V9.A2` · gemini-f8a2 / deepseek-v4f-k2m9 | accepted | **保留不提交** | 基线冻结大件清单与快照（2.1~15.4 MB） |
| 84 | `reports/V9-baseline/r4/stat_after.json` | 文件 | 13.93 MB | 2026-11-06 09:20:16 | `ainerzero.V9.A15 / ainerzero.V9.A2` · gemini-f8a2 / deepseek-v4f-k2m9 | accepted | **保留不提交** | 基线冻结大件清单与快照（2.1~15.4 MB） |
| 85 | `reports/V9-baseline/r4/stat_before.json` | 文件 | 13.93 MB | 2026-11-06 09:03:56 | `ainerzero.V9.A15 / ainerzero.V9.A2` · gemini-f8a2 / deepseek-v4f-k2m9 | accepted | **保留不提交** | 基线冻结大件清单与快照（2.1~15.4 MB） |
| 86 | `reports/coordination/gemini-loop-20261106/` | 目录 | 9.3 KB (1 个) | 2026-11-06 09:45:00 | `统筹任务（一级协同）` · claude (一级统筹) | accepted | **提交** | 一级统筹制备的 gemini 循环领活提示词模板（9.5 KB） |
| 87 | `reports/teachers-install-download-20261020/20261020T181817/pypi-numpy.json` | 文件 | 3.56 MB | 2026-10-20 15:20:34 | `ainerzero.V9.T21` · workbuddy-x9m2 | accepted | **保留不提交** | 教师离线环境 PyPI 元数据缓存 JSON（单文件 1~3.7 MB） |
| 88 | `reports/teachers-install-download-20261020/20261020T181817/pypi-opencv-python.json` | 文件 | 978.3 KB | 2026-10-20 15:20:37 | `ainerzero.V9.T21` · workbuddy-x9m2 | accepted | **保留不提交** | 教师离线环境 PyPI 元数据缓存 JSON（单文件 1~3.7 MB） |
| 89 | `reports/teachers-install-download-20261020/20261020T181817/pypi-pillow.json` | 文件 | 3.17 MB | 2026-10-20 15:20:45 | `ainerzero.V9.T21` · workbuddy-x9m2 | accepted | **保留不提交** | 教师离线环境 PyPI 元数据缓存 JSON（单文件 1~3.7 MB） |
| 90 | `reports/teachers-install-download-20261020/20261020T181817/pypi-protobuf.json` | 文件 | 2.36 MB | 2026-10-20 15:20:47 | `ainerzero.V9.T21` · workbuddy-x9m2 | accepted | **保留不提交** | 教师离线环境 PyPI 元数据缓存 JSON（单文件 1~3.7 MB） |
| 91 | `reports/teachers-install-download-20261020/20261020T181817/pypi-safetensors.json` | 文件 | 1.93 MB | 2026-10-20 15:20:36 | `ainerzero.V9.T21` · workbuddy-x9m2 | accepted | **保留不提交** | 教师离线环境 PyPI 元数据缓存 JSON（单文件 1~3.7 MB） |
| 92 | `reports/test-hermetic-20261106/artifacts_stat_before.json` | 文件 | 14.68 MB | 2026-11-06 09:47:56 | `ainerzero.V9.A17 / ainerzero.V9.A19 / ainerzero.V9.A21` · gemini-f8a2 / gemini-8f4b | accepted | **保留不提交** | 测试封闭性会话级 artifacts 快照（15.4~19.1 MB） |
| 93 | `reports/test-hermetic-20261106/r2/artifacts_stat_after.json` | 文件 | 14.68 MB | 2026-11-06 10:13:43 | `ainerzero.V9.A17 / ainerzero.V9.A19 / ainerzero.V9.A21` · gemini-f8a2 / gemini-8f4b | accepted | **保留不提交** | 测试封闭性会话级 artifacts 快照（15.4~19.1 MB） |
| 94 | `reports/test-hermetic-20261106/r2/artifacts_stat_before.json` | 文件 | 14.68 MB | 2026-11-06 10:08:52 | `ainerzero.V9.A17 / ainerzero.V9.A19 / ainerzero.V9.A21` · gemini-f8a2 / gemini-8f4b | accepted | **保留不提交** | 测试封闭性会话级 artifacts 快照（15.4~19.1 MB） |
| 95 | `reports/test-hermetic-20261106/r3/artifacts_stat_after.json` | 文件 | 18.24 MB | 2026-11-06 11:54:04 | `ainerzero.V9.A17 / ainerzero.V9.A19 / ainerzero.V9.A21` · gemini-f8a2 / gemini-8f4b | accepted | **保留不提交** | 测试封闭性会话级 artifacts 快照（15.4~19.1 MB） |
| 96 | `reports/test-hermetic-20261106/r3/artifacts_stat_before.json` | 文件 | 18.24 MB | 2026-11-06 11:49:43 | `ainerzero.V9.A17 / ainerzero.V9.A19 / ainerzero.V9.A21` · gemini-f8a2 / gemini-8f4b | accepted | **保留不提交** | 测试封闭性会话级 artifacts 快照（15.4~19.1 MB） |
| 97 | `reports/test-hermetic-20261106/r3b/artifacts_stat_after.json` | 文件 | 18.24 MB | 2026-11-06 12:02:28 | `ainerzero.V9.A17 / ainerzero.V9.A19 / ainerzero.V9.A21` · gemini-f8a2 / gemini-8f4b | accepted | **保留不提交** | 测试封闭性会话级 artifacts 快照（15.4~19.1 MB） |
| 98 | `reports/test-hermetic-20261106/r3b/artifacts_stat_before.json` | 文件 | 18.24 MB | 2026-11-06 12:00:12 | `ainerzero.V9.A17 / ainerzero.V9.A19 / ainerzero.V9.A21` · gemini-f8a2 / gemini-8f4b | accepted | **保留不提交** | 测试封闭性会话级 artifacts 快照（15.4~19.1 MB） |

---

## 五、一级统筹抽查核验建议（按规格指定 5 项深度核验）

按照任务验收标准要求「一级抽查至少五项」，特挑选涵盖 4 种建议分类的 5 个关键代表项供一级重点复验：

1. **抽查 1（建议提交）**：`reports/V9-E1-A1/PRE-DATASETS.sha256`

   - **出处**：卡号 `ainerzero.V9.P104`/`P105`，执行代理 `gemini-k8m2`，复核代理 `gemini-x3n8`，状态已验收。

   - **核验依据**：`git grep -n "PRE-DATASETS.sha256"` 显示被根目录 `RESEARCH_LOG.md`（第 2317 行）、`CARD-P105.md` 与 `REVIEW-P105.md` 强引用，是 5,400+ 个数据集文件的校验根。虽因 1.02 MB 略超原 1MB 批量限制，但属于关键指纹文本，极度建议提交。

2. **抽查 2（建议提交）**：`reports/V9-S4-P2-DESIGN/r1-review/`

   - **出处**：卡号 `ainerzero.V9.P215`，前任持有者 `claude-s4p2rev-1111a`，接手复核者 `claude-s4p2rev-b-1111`，状态已验收。

   - **核验依据**：`reports/V9-S4-P2-DESIGN/r1-review-b/REPORT.md` 第 9 行明确声明将其 `evidence/` 下脚本作为输入底据；全目录仅 15 个轻量文件（325 KB），应随同入库。

3. **抽查 3（建议加入 .gitignore）**：`reports/V9-B3-mlx-unitcost/cpu-tests-pytest-r5/test_entire_cpu_dryrun_importscurrent`

   - **出处**：卡号 `ainerzero.V9.P28`，执行代理 `codex-0fqn`，状态已验收。

   - **核验依据**：指向 `/Users/mac/.../test_entire_cpu_dryrun_imports0` 的 pytest 软链接，`readlink` 即见本机绝对路径；属测试夹具运行副产物，完全可再生。

4. **抽查 4（建议保留不提交）**：`reports/V9-S2-P118/artifacts_stat_after.json`

   - **出处**：卡号 `ainerzero.V9.P118`/`P119`，执行代理 `gemini-f8a2`，复核代理 `gemini-w4x2`，状态已验收。

   - **核验依据**：文件大小 19.1 MB，已记录于 `reports/git-batch-commit-20261105/excluded/post-intake-20261106.tsv`；系 hermetic 测试证明实盘无损的证据快照，不可删除，但不可提交。

5. **抽查 5（建议候选删除）**：`reports/V9-P25/.tmp-r1/sabotage-host/artifacts`

   - **出处**：卡号 `ainerzero.V9.P25`，执行代理 `composer-m7k2`，状态已验收。

   - **核验依据**：`reports/V9-P25/harness/r1_probe.py` 执行时创建的单条测试软链接（44 字节），指向实盘 `artifacts/`；无任何最终报告引用，运行探针会直接重建，适宜作为首要候选删除项。

---

## 六、交付文件与哈希

本任务所有交付文件均存放在 `reports/repo-hygiene-20261111/`，由脚本自动计算 SHA256 记录于 `SHA256SUMS.txt`。

- `REPORT.md`：本报告正文；

- `metrics.json`：结构化盘点指标数据（供 relay report 读取）；

- `SHA256SUMS.txt`：交付物校验和；

- `evidence/`：包含 git status、du、relay show、citations 扫描、sensitive 扫描及 inventory 完整 JSON。

