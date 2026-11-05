# E1 训练与 dev 阶段非作者复核报告（任务 ainerzero.V9.P103 · r2 重做版）

## 一、领卡自证与证据位置

**领卡独立性自证（严格自证）**：
> 本复核代理（ID: `gemini-q9w2`，二级执行 agent，模型类型：gemini）郑重自证：与历史任务执行代理 `gemini-v9m3`（P100）、`gemini-v9s1`、`gemini-e8x1`（P101）、`gemini-8f4b`（P102）以及一级统筹/验收代理（`claude`、`codex`）均不是同一会话，亦非其会话别名；本代理以独立会话领取并自主执行本次只读复核任务。

**被复核证据位置**：
1. **P 族训练报告（B-P，P100）**：`reports/V9-E1RUN-B-P/gemini-v9m3/`（包含 `REPORT.md`、`metrics.json`、`progress.json`）
2. **S 族训练报告（B-S，P101）**：`reports/V9-E1RUN-B-S/gemini-e8x1/`（包含 `REPORT.md`、`metrics.json`、`progress.json`）
3. **dev 评测报告与数据（C，P102）**：
   - 报告：`reports/V9-E1RUN-C/gemini-8f4b/report.md`
   - 指标：`reports/V9-E1RUN-C/gemini-8f4b/metrics.json`
   - 账本副本：`reports/V9-E1RUN-C/gemini-8f4b/control.sqlite3`
4. **dev 评测原始输出目录**：`artifacts/v9/e1/phase2/eval/`（26 个评测 JSON 文件）
5. **中央账本生产库与本复核副本**：生产位于 `artifacts/v9/e1/phase2/control.sqlite3`；按更正三要求，预先复制至 `reports/V9-E1RUN-C/review/control.sqlite3`，只读复核全程在副本上执行。
6. **上一轮打回报告保留存档**：旧版本已按指示完整更名为 `REPORT.md.r1-rejected`、`报告.md.r1-rejected`、`metrics.json.r1-rejected`、`指标.json.r1-rejected`，供回溯查验。

---

## 二、打回项整改与重做机制说明

针对一级统筹打回意见，本轮重做严格遵循六项整改要求：
1. **零人工抄录**：报告中的全部表格、64 位 SHA-256、精确至 18 位的 $e_{10}$ 指标均由脚本 `build_review_artifacts.py` 直接从对应文件中读取并生成至 `generated_tables.md` 与 `metrics.json`，杜绝任何人工手抄笔误。
2. **动态读取与判定**：抽样格、mtime 比对全部由脚本自动遍历文件系统计算，无任何硬编码常量。
3. **自主端到端指标重算**：不单纯信任或转抄 `eval_*.json` 的 `summary`，而是从 200 个 episode 的 `pred_positions` 轨迹数组与 `artifacts/v9/e1/phase2/datasets/student/<族>/development/<sid>.json` 的 `frames[19]['objects'][名]['position']` 真实三维坐标出发，自主计算欧式距离均值，实现从源头真值到评估指标的端到端亲验复算。
4. **补充分析模块核查**：在原先 (a)(b)(c) 源码核对基础上，补全 (d) 项关于 `analysis.load_cells` 是否按 partition 进行过滤的源码行号与逐字引用。

---

## 三、逐项亲验结果与数据表

### 1. 账本复核（中央账本副本 `control.sqlite3`）

- **核对原则**：
  - 谱系跨越两个实验阶段：`e1-phase2-20261029-r0`（数据生成 + P 族 9 格训练）和 `e1-phase2-20261029-r1`（S 族 9 格训练 + dev 26 格评测）；
  - `active_seconds` 记预留值、不退还。总预留上限 ≤ 18000 s；训练预留 12300 s（设计内预留）核实际墙钟 ≤ 3 h（~7600 s）；dev 评测核预留（1740 s ≤ 1800 s）与实际墙钟；
  - 严禁出现任何 `final-eval` 行。

- **亲验结果**：
  - **总运行行数**：45 行（r0: 10 行；r1: 35 行）
  - **出现模式**：`{'generate-data', 'train', 'eval'}`（`final-eval` 出现次数严格为 **0**）
  - **总预留 active_seconds**：`17640.0 s`（≤ 18000.0 s 上限）
  - **训练预留 active_seconds**：`12300.0 s`（P 族 6000 s + S 族 6300 s，设计内预留）
  - **训练实际总墙钟**：`7602.40 s`（约 2.11 小时，完全满足 ≤ 3 小时 / 10800 s 要求）
  - **dev 评测预留 active_seconds**：`1740.0 s`（≤ 1800.0 s 上限）
  - **dev 评测实际总墙钟**：`716.36 s`（约 11.9 分钟）

*(账本 45 行完整明细见文末第四节引用之自动生成数据表 1)*

---

### 2. Checkpoint 文件与元数据核对（18 格训练模型）

- **核对原则**：
  - 18 个 checkpoint 目录均存在 `model_weights.npz` 与 `checkpoint_meta.json`；
  - 18 个权重的 SHA-256 与 B-P、B-S 报告 100% 一致；
  - 随机抽 2 个读出 `best_step`、`stopped_step` 以及损失曲线最低点。

- **亲验结果**：
  - 18 个 checkpoint 文件完整存在，完整 64 位 SHA-256 经脚本逐字节比对，与 B 卡全量严格一致。
  - **动态抽样检视 1**：`arm6_P_seed42`
    - `best_step`: 25500，`stopped_step`: 30500，验证曲线第 25500 步 `val_loss`: 0.5361769 为全曲线极小值点，早停在耐受 5000 步后准确触发。
  - **动态抽样检视 2**：`arm2_S_seed44`
    - `best_step`: 47500，`stopped_step`: 52500，验证曲线第 47500 步 `val_loss`: 0.0974197 为全曲线极小值点，早停在耐受 5000 步后准确触发。
  - 18 格全量验证表明：全部满足 `stopped_step == best_step + 5000`，训练早停机制均在达到耐受步数后规范退出。

*(18 格 Checkpoint 完整 64 位 SHA 表见文末第四节引用之自动生成数据表 2)*

---

### 3. dev 指标抽查、端到端轨迹重算与宏平均复算

- **核对原则**：
  - 随机抽 3 格，直接从 episodes 里的 `pred_positions` 和 student 真值重算 $e_{10}$，再与 summary 比对；
  - 抽 1 格 F1 进行全量 episode 复算；
  - 复算 14 组 Arm × Family 宏平均汇总表。

#### (1) 端到端真实轨迹重算（抽样 3 格）
从 `artifacts/v9/e1/phase2/eval/` 读取评测单步预测数组 `pred_positions`，与 `artifacts/v9/e1/phase2/datasets/student/<族>/development/<sequence_id>.json` 中对应 frame 19（prefix 10 + k=10 - 1 = 19）的物体真值坐标计算欧氏距离均值，全量 200 个 episode 算术平均结果如下：
1. **抽样 1（`eval_arm2_P_42.json`）**：
   - 从底表真值轨迹端到端重算：`0.028728605242356493 m`
   - 原始 eval JSON `summary.k_step_errors['10']`：`0.028728605242356493 m`
   - 差值 Diff：`0.00e+00`（完全一致）
2. **抽样 2（`eval_arm6_S_43.json`）**：
   - 从底表真值轨迹端到端重算：`0.037239625669522235 m`
   - 原始 eval JSON `summary.k_step_errors['10']`：`0.037239625669522235 m`
   - 差值 Diff：`0.00e+00`（完全一致）
3. **抽样 3（`eval_arm3_S_42.json`）**：
   - 从底表真值轨迹端到端重算：`0.072315474770965296 m`
   - 原始 eval JSON `summary.k_step_errors['10']`：`0.072315474770965296 m`
   - 差值 Diff：`0.00e+00`（完全一致）

#### (2) 碰撞 F1 全量 Episode 复算（抽样 1 格）
针对 `eval_arm2_P_42.json` 中全部 200 个 episode 记录的 `collision_f1`：
- 精确率 Precision 均值：`0.4550`（summary 为 `0.4550`，Diff: `0.00e+00`）
- 召回率 Recall 均值：`0.5279166666666667`（summary 为 `0.5279166666666667`，Diff: `0.00e+00`）
- F1 均值：`0.4693333333333334`（summary 为 `0.4693333333333334`，Diff: `0.00e+00`）

*(26 格详细指标与 14 组宏平均汇总表见文末第四节引用之自动生成数据表 3、4、5)*

---

### 4. sealed_final 封存未读核验

- **核对原则**：
  - `artifacts/v9/e1/phase2/datasets/` 下绝无任何 `.read_once*` 标记；
  - 封存目录下全部文件修改时间不得晚于数据生成完成时间。

- **亲验结果**：
  - 经 `os.walk` 遍历，数据集目录下未检测到任何 `.read_once` 文件（`has_read_once_files = False`）。
  - 数据生成结束基准文件 `SHA256SUMS.txt` 修改时间为 `1793660880.0`（2026-11-03 00:08:00）。
  - 封存目录 `sealed_final/` 下共 8 个文件（P 与 S 族各 4 个），修改时间均为 `1793660771.0` - `1793660772.0`（2026-11-03 00:06:11-12），均早于数据生成完成时间，`is_before_gen_end` 全为 `True`。

---

### 5. 冻结文档与源码身份校验（Verify 回执）

- **核对原则**：
  - `prereg.json` 及其 `.sha256` 摘要一致；
  - `RESEARCH_LOG.md` 批准行在第 2108 行；
  - 源码与生成器 SHA-256 与冻结钉住摘要一致。

- **亲验结果**：
  - `prereg.json` SHA-256 为 `84f23f2ce3a6071f622613cfa4f43a8abb468b02e456da994917bc1db68fe9f6`，与 `prereg.json.sha256` 匹配。
  - `RESEARCH_LOG.md` 第 2108 行内容为：
    `APPROVED e1-phase2 prereg document_sha256=84f23f2ce3a6071f622613cfa4f43a8abb468b02e456da994917bc1db68fe9f6`
  - CLI `e1-phase2 --mode verify` 回执状态：`status: "verified"`, `approval.status: "approved"`, `identity.status: "passed"`。

---

### 6. final-eval 入口与 analysis 源码核查（只读代码，绝不运行）

按统筹指示与打回补充要求，逐字引用行号回答以下 4 个问题：

#### (a) 不写新代码、只用 CLI 跑 --mode final-eval，会评测哪些臂？
- **回答**：仅评测 **臂 1（Arm 1 / PriorArm）**，不会评测可训练臂（②③⑥）或其他基线臂（④⑤⑦）。
- **逐字引用源码**：
  - `src/ainerzero/v9/experiments/e1/worker.py` 第 686–690 行：
```python
        arm_factory = kwargs.get("arm_factory")
        if arm_factory is None:
            # Build default final evaluation arms (PriorArm and any available checkpoints)
            arm_factory = {"arm1_prior": arms_nonnet.PriorArm()}
```
  - 说明：当仅通过 CLI 运行 `--mode final-eval` 时，CLI 并未传入 `arm_factory` 参数（见 `commands.py` 第 396–408 行与 `worker.py` 第 824–834 行），`kwargs.get("arm_factory")` 必为 `None`，因此进入 fallback 分支，只构建包含 `arm1_prior` 的单臂字典。

#### (b) read_once 标记在什么时候写，写在 execute_work_cell 之前还是之后？
- **回答**：磁盘 secondary safeguard 标记写在 `execute_work_cell` **之前**。
- **逐字引用源码**：
  - `src/ainerzero/v9/experiments/e1/commands.py` 第 387–396 行：
```python
            if mode == "final-eval":
                # Mark legacy marker on disk as secondary safeguard
                final_dir = paths["data_dir"] / "final"
                final_dir.mkdir(parents=True, exist_ok=True)
                (final_dir / f".read_once_{family}").write_text("READ_ONCE\n", encoding="utf-8")
                (final_dir / ".read_once").write_text("READ_ONCE\n", encoding="utf-8")

            ledger = worker.E1Ledger(paths["ledger"], clock=clock_fn)
            try:
                result = worker.execute_work_cell(
```
  - 说明：在获得全局 worker 锁后，第 387–392 行先向磁盘写入了 `f".read_once_{family}"` 与 `".read_once"` 标记，随后在第 396 行才调用 `worker.execute_work_cell` 开始执行工作单元。

#### (c) 先跑 S 族之后，P 族还能不能跑？
- **回答**：**不能跑，会被拒绝（Refused）**。
- **逐字引用源码**：
  - `src/ainerzero/v9/experiments/e1/commands.py` 第 391–392 行：
```python
                (final_dir / f".read_once_{family}").write_text("READ_ONCE\n", encoding="utf-8")
                (final_dir / ".read_once").write_text("READ_ONCE\n", encoding="utf-8")
```
  - `src/ainerzero/v9/experiments/e1/commands.py` 第 320–328 行：
```python
        legacy_marker = paths["data_dir"] / "final" / f".read_once_{family}"
        global_legacy_marker = paths["data_dir"] / "final" / ".read_once"
        if has_marker or legacy_marker.is_file() or (family == "P" and global_legacy_marker.is_file()):
            return {
                "status": "refused",
                "mode": mode,
                "stage": "final_eval_already_read_once",
                "message": f"Final partition for family {family} has already been read once; further access is permanently forbidden",
            }, EXIT_FAILED
```
  - 说明：当先跑 S 族 final-eval 时，第 392 行无差别写入了全局文件 `paths["data_dir"] / "final" / ".read_once"`。若后续尝试运行 P 族 final-eval，预检逻辑在第 322 行判断 `(family == "P" and global_legacy_marker.is_file())`，此时 `global_legacy_marker.is_file()` 为 `True`，导致条件成立，第 323–328 行直接返回拒绝 `status: "refused", stage: "final_eval_already_read_once"`，因此 P 族无法再运行。

#### (d) analysis.load_cells 是否按 partition 过滤？
- **回答**：**没有按 partition 过滤（未做 partition 过滤）**。
- **逐字引用源码**：
  - `src/ainerzero/v9/experiments/e1/analysis.py` 第 186–217 行：
```python
    for jf in json_files:
        try:
            data = json.loads(jf.read_text(encoding="utf-8"))
        except Exception:
            continue

        if not isinstance(data, dict):
            continue

        arm = data.get("arm")
        family = data.get("family")
        seed = data.get("seed")
        part = data.get("partition", partition)

        # Normalize seed
        if seed == "none" or seed == "" or seed is None:
            norm_seed = None
        else:
            try:
                norm_seed = int(seed)
            except (ValueError, TypeError):
                norm_seed = None

        if arm is not None and family is not None:
            try:
                norm_arm = int(arm)
            except (ValueError, TypeError):
                continue
            norm_fam = str(family).upper()
            cell_key = (norm_fam, norm_arm, norm_seed)
            loaded_cells[cell_key] = data
```
  - 说明：在第 198 行虽读取了 `part = data.get("partition", partition)`，但后续在第 199–217 行中**没有任何与 `part` 或 `partition` 相关的判断、比较或过滤逻辑**。只要 JSON 中存在有效的 `arm` 与 `family`，就会直接以 `(norm_fam, norm_arm, norm_seed)` 为键写入 `loaded_cells` 字典。

---

## 四、自动生成数据表全文嵌入（源自 generated_tables.md）

# 脚本自动生成的数据表汇总（自动校验无手抄）

## 1. 账本 45 行全量运行记录表

| 序号 | 实验谱系 ID | run_id (前8位) | 模式 | 臂 | 族 | 种子 | 状态 | 预留 active_s | 实际墙钟 (s) |
| :---: | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| 1 | `e1-phase2-20261029-r0` | `d12e6ac7...` | `generate-data` | - | - | - | completed | 3600.0 | 3364.3 |
| 2 | `e1-phase2-20261029-r0` | `b32b21a8...` | `train` | 6 | P | 42 | completed | 1100.0 | 841.7 |
| 3 | `e1-phase2-20261029-r0` | `249854a5...` | `train` | 6 | P | 43 | completed | 1100.0 | 964.8 |
| 4 | `e1-phase2-20261029-r0` | `f5a2977c...` | `train` | 6 | P | 44 | completed | 1100.0 | 961.5 |
| 5 | `e1-phase2-20261029-r0` | `45842889...` | `train` | 2 | P | 42 | completed | 450.0 | 190.2 |
| 6 | `e1-phase2-20261029-r0` | `8a955e03...` | `train` | 2 | P | 43 | completed | 450.0 | 303.8 |
| 7 | `e1-phase2-20261029-r0` | `0c975ab1...` | `train` | 2 | P | 44 | completed | 450.0 | 205.9 |
| 8 | `e1-phase2-20261029-r0` | `5baaa702...` | `train` | 3 | P | 42 | completed | 450.0 | 136.3 |
| 9 | `e1-phase2-20261029-r0` | `8c9aa881...` | `train` | 3 | P | 43 | completed | 450.0 | 209.8 |
| 10 | `e1-phase2-20261029-r0` | `0d660578...` | `train` | 3 | P | 44 | completed | 450.0 | 205.2 |
| 11 | `e1-phase2-20261029-r1` | `be16ef74...` | `train` | 6 | S | 42 | completed | 1200.0 | 691.7 |
| 12 | `e1-phase2-20261029-r1` | `39bec45e...` | `train` | 6 | S | 43 | completed | 1200.0 | 693.8 |
| 13 | `e1-phase2-20261029-r1` | `a8fff6f8...` | `train` | 6 | S | 44 | completed | 1200.0 | 673.4 |
| 14 | `e1-phase2-20261029-r1` | `1cbec699...` | `train` | 2 | S | 42 | completed | 450.0 | 276.8 |
| 15 | `e1-phase2-20261029-r1` | `e14bb245...` | `train` | 2 | S | 43 | completed | 450.0 | 191.2 |
| 16 | `e1-phase2-20261029-r1` | `600601ae...` | `train` | 2 | S | 44 | completed | 450.0 | 310.8 |
| 17 | `e1-phase2-20261029-r1` | `e8014904...` | `train` | 3 | S | 42 | completed | 450.0 | 223.5 |
| 18 | `e1-phase2-20261029-r1` | `e0b4c830...` | `train` | 3 | S | 43 | completed | 450.0 | 224.1 |
| 19 | `e1-phase2-20261029-r1` | `48668674...` | `train` | 3 | S | 44 | completed | 450.0 | 298.2 |
| 20 | `e1-phase2-20261029-r1` | `72786a8d...` | `eval` | 6 | P | 42 | completed | 150.0 | 101.5 |
| 21 | `e1-phase2-20261029-r1` | `c2323c7f...` | `eval` | 6 | P | 43 | completed | 150.0 | 101.2 |
| 22 | `e1-phase2-20261029-r1` | `bddbc143...` | `eval` | 6 | P | 44 | completed | 150.0 | 100.7 |
| 23 | `e1-phase2-20261029-r1` | `aad5f9e6...` | `eval` | 2 | P | 42 | completed | 40.0 | 0.7 |
| 24 | `e1-phase2-20261029-r1` | `831933d6...` | `eval` | 2 | P | 43 | completed | 40.0 | 0.7 |
| 25 | `e1-phase2-20261029-r1` | `ed1d08cf...` | `eval` | 2 | P | 44 | completed | 40.0 | 0.7 |
| 26 | `e1-phase2-20261029-r1` | `6b30800e...` | `eval` | 3 | P | 42 | completed | 40.0 | 3.4 |
| 27 | `e1-phase2-20261029-r1` | `7057c72b...` | `eval` | 3 | P | 43 | completed | 40.0 | 3.8 |
| 28 | `e1-phase2-20261029-r1` | `547a6362...` | `eval` | 3 | P | 44 | completed | 40.0 | 3.4 |
| 29 | `e1-phase2-20261029-r1` | `7862046d...` | `eval` | 6 | S | 42 | completed | 150.0 | 90.3 |
| 30 | `e1-phase2-20261029-r1` | `28871543...` | `eval` | 6 | S | 43 | completed | 150.0 | 88.4 |
| 31 | `e1-phase2-20261029-r1` | `565be18a...` | `eval` | 6 | S | 44 | completed | 150.0 | 90.5 |
| 32 | `e1-phase2-20261029-r1` | `641063bb...` | `eval` | 2 | S | 42 | completed | 40.0 | 0.7 |
| 33 | `e1-phase2-20261029-r1` | `2742d553...` | `eval` | 2 | S | 43 | completed | 40.0 | 0.7 |
| 34 | `e1-phase2-20261029-r1` | `50251129...` | `eval` | 2 | S | 44 | completed | 40.0 | 0.7 |
| 35 | `e1-phase2-20261029-r1` | `5abe9cfd...` | `eval` | 3 | S | 42 | completed | 40.0 | 3.3 |
| 36 | `e1-phase2-20261029-r1` | `70cb9c21...` | `eval` | 3 | S | 43 | completed | 40.0 | 3.7 |
| 37 | `e1-phase2-20261029-r1` | `ba3fd67c...` | `eval` | 3 | S | 44 | completed | 40.0 | 3.9 |
| 38 | `e1-phase2-20261029-r1` | `1ee76eb4...` | `eval` | 1 | P | - | completed | 45.0 | 3.4 |
| 39 | `e1-phase2-20261029-r1` | `a55a0fe7...` | `eval` | 4 | P | - | completed | 45.0 | 3.5 |
| 40 | `e1-phase2-20261029-r1` | `20ee2b84...` | `eval` | 5 | P | - | completed | 45.0 | 30.6 |
| 41 | `e1-phase2-20261029-r1` | `0d372838...` | `eval` | 7 | P | - | completed | 45.0 | 31.4 |
| 42 | `e1-phase2-20261029-r1` | `4ed2beb5...` | `eval` | 1 | S | - | completed | 45.0 | 3.3 |
| 43 | `e1-phase2-20261029-r1` | `351e0c0a...` | `eval` | 4 | S | - | completed | 45.0 | 3.5 |
| 44 | `e1-phase2-20261029-r1` | `a4bb1211...` | `eval` | 5 | S | - | completed | 45.0 | 20.6 |
| 45 | `e1-phase2-20261029-r1` | `4c71c4ca...` | `eval` | 7 | S | - | completed | 45.0 | 21.8 |

## 2. 18 格 Checkpoint 完整 SHA-256 与 Best Step 检验表

| 序号 | 单元名 | 臂 | 族 | 种子 | 权重文件完整 SHA-256 | best_step | stopped_step | 曲线最低 val_loss | 与 B 卡比对结果 |
| :---: | :--- | :---: | :---: | :---: | :--- | :---: | :---: | :---: | :---: |
| 1 | `arm6_P_seed42` | 6 | P | 42 | `7f3a0bd12df18443b4ba8fa36ebc9f87007930c4b62549cfe4a82efbcb73b925` | 25500 | 30500 | 0.5361769 | 全等通过 |
| 2 | `arm6_P_seed43` | 6 | P | 43 | `de7b4f1b5bd9ed5f2b125cc5a75d93eb1a02da3d61226c35e5a956c7b698f391` | 43000 | 48000 | 0.5052853 | 全等通过 |
| 3 | `arm6_P_seed44` | 6 | P | 44 | `9af47cebdd4d9f6e11172849e5b7bfbbfa4c4f8eff8d2c871dd72535944632ef` | 38500 | 43500 | 0.5138564 | 全等通过 |
| 4 | `arm2_P_seed42` | 2 | P | 42 | `54b91b53af2197cd977ea70eb1ee8677c2d5e6fbb3d232996dbb2f606a71e287` | 30500 | 35500 | 0.0812779 | 全等通过 |
| 5 | `arm2_P_seed43` | 2 | P | 43 | `3377c451d2589fee2ae5bb3ba46f5d34846751d3843bab0a55a016bceaf66dc6` | 51000 | 56000 | 0.0706997 | 全等通过 |
| 6 | `arm2_P_seed44` | 2 | P | 44 | `fa3190b28a2654677192358b0eedabc15fb7f486c8219c464b9dcaebee4b5ddb` | 36500 | 41500 | 0.0758830 | 全等通过 |
| 7 | `arm3_P_seed42` | 3 | P | 42 | `828bab7db46828e483169b56408596f052264f6a77592fb0152adc97ab964dde` | 18500 | 23500 | 0.4022941 | 全等通过 |
| 8 | `arm3_P_seed43` | 3 | P | 43 | `554c9b7d53580d0bb34806a6a7bf6049e868f231a1fcd34b527eeb5b28c886dc` | 28500 | 33500 | 0.3669056 | 全等通过 |
| 9 | `arm3_P_seed44` | 3 | P | 44 | `08100626793098185ea9f95448fce87a04bee573a6a31e82be0cf43ad88a8d8b` | 28500 | 33500 | 0.3626216 | 全等通过 |
| 10 | `arm6_S_seed42` | 6 | S | 42 | `d23647a5bccbae280377e4308ccfa3f1ef753bea7260fbc5061f923e86b55e56` | 31000 | 36000 | 0.8878515 | 全等通过 |
| 11 | `arm6_S_seed43` | 6 | S | 43 | `61e5b8535ac4a837faa55632461a94f71e56abdb2605c6b1073bc646be18bf64` | 31000 | 36000 | 0.9129212 | 全等通过 |
| 12 | `arm6_S_seed44` | 6 | S | 44 | `31a09b65d9064e6f04fce6da569f712e9b6b2a997f38f228f9f8e1d8f4a45a62` | 25000 | 30000 | 0.9086446 | 全等通过 |
| 13 | `arm2_S_seed42` | 2 | S | 42 | `f49a9c52e47ccdd4c3de85587e388808fcce6414544f5ce97e138d738715ffd6` | 40000 | 45000 | 0.1019258 | 全等通过 |
| 14 | `arm2_S_seed43` | 2 | S | 43 | `4f61d0a964fbc2313f6acb3a2d3ef50b76523f88d415882145a788a1a9f8b373` | 28500 | 33500 | 0.1122518 | 全等通过 |
| 15 | `arm2_S_seed44` | 2 | S | 44 | `45d9adedf0277c8395b43d8baac5170e8a9477589a21559de78afc826beb1441` | 47500 | 52500 | 0.0974197 | 全等通过 |
| 16 | `arm3_S_seed42` | 3 | S | 42 | `2b9362f407ed9c073e9c0e2b866fde760b0f9114023d1447071e884304066a5e` | 26500 | 31500 | 0.5280742 | 全等通过 |
| 17 | `arm3_S_seed43` | 3 | S | 43 | `1d3006bcf19aa0a4b7082bed395ee27f4f44722919fe0d575b1c1d883a41ee81` | 31000 | 36000 | 0.5112638 | 全等通过 |
| 18 | `arm3_S_seed44` | 3 | S | 44 | `dab98adef1aef347d067215cf516f82d36d870c91f422d68eb73fee5f1caa412` | 43500 | 48500 | 0.5000964 | 全等通过 |

## 3. dev 评测 26 格原始 JSON 详细指标记录表

| 序号 | 文件名 | 臂 | 族 | 种子 | 完整 SHA-256 | e_1 (m) | e_5 (m) | e_10 (主指标, m) | e_30 (m) | 碰撞 P / R / F1 | 能量漂移 | 单步延迟 (s) |
| :---: | :--- | :---: | :---: | :---: | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| 1 | `eval_arm6_P_42.json` | 6 | P | 42 | `06670fa3dcd840dcd92adc1475e937dc9abb3b0cd69af0cbc9d0591652921b2f` | 0.004084 | 0.009510 | 0.035067166777541459 | 0.210362 | 0.440/0.565/0.476 | 0.054052 | 0.016877 |
| 2 | `eval_arm6_P_43.json` | 6 | P | 43 | `90b8b9434f5999f640beae42e91f7f917445637fd431ba67f68502163025dbdd` | 0.001388 | 0.008555 | 0.035184525147163068 | 0.210808 | 0.405/0.568/0.435 | 0.052783 | 0.016834 |
| 3 | `eval_arm6_P_44.json` | 6 | P | 44 | `d01616a481974b27bab13a088b9e1c32610a493218b05b814c0269c226e175ba` | 0.001731 | 0.008803 | 0.034956560845995563 | 0.212876 | 0.402/0.574/0.437 | 0.052943 | 0.016756 |
| 4 | `eval_arm2_P_42.json` | 2 | P | 42 | `f4f0fcdc1d2a44a02071103c1f9aa361a4417c3ba2f7f9efe9c08728aaaaece0` | 0.001486 | 0.009491 | 0.028728605242356493 | 0.164852 | 0.455/0.528/0.469 | 0.072462 | 0.000090 |
| 5 | `eval_arm2_P_43.json` | 2 | P | 43 | `cc7bfe68edd72d35444f82cca14d8176431a0ff9d3077f8f69b0f837ecc5fd8b` | 0.001079 | 0.009489 | 0.028233408954973272 | 0.162513 | 0.521/0.604/0.541 | 0.082253 | 0.000088 |
| 6 | `eval_arm2_P_44.json` | 2 | P | 44 | `9c23f0468ea6c498da59b62dce416578e14a2cb9623e0dfeef61b0b4adcf3a03` | 0.001673 | 0.010978 | 0.030868159540019435 | 0.143453 | 0.512/0.580/0.523 | 0.075064 | 0.000090 |
| 7 | `eval_arm3_P_42.json` | 3 | P | 42 | `7e71fe5be2079e39b273f36334b0990e818fd4916bc77cbe0697f4bc2b41c821` | 0.005702 | 0.024097 | 0.077945727332548481 | 0.391127 | 0.293/0.310/0.300 | 0.092775 | 0.000533 |
| 8 | `eval_arm3_P_43.json` | 3 | P | 43 | `70d4b3fc35db2d26ec4ebf698ad483120ad1ba8e770a784c0d14b837a33e3adc` | 0.001442 | 0.015219 | 0.053529258915386929 | 0.332106 | 0.357/0.468/0.381 | 0.101028 | 0.000595 |
| 9 | `eval_arm3_P_44.json` | 3 | P | 44 | `3170a3822a1c20890ab2d53e47eeea122ae0e0d41faee8e0ffa72724367241f0` | 0.003165 | 0.021243 | 0.101765474486280927 | 0.410637 | 0.414/0.545/0.458 | 0.092754 | 0.000539 |
| 10 | `eval_arm6_S_42.json` | 6 | S | 42 | `d02f4d89255d8e86d4d236b21d630d60b166daaa36342c799b30d6876441566a` | 0.004343 | 0.010345 | 0.035285280673801614 | 0.216954 | 0.412/0.570/0.441 | 0.053985 | 0.015008 |
| 11 | `eval_arm6_S_43.json` | 6 | S | 43 | `4cb0d0771e95b79426a930e2506c28c013afa787667bbe4a0849fe5baff63d16` | 0.004595 | 0.010577 | 0.037239625669522235 | 0.211111 | 0.422/0.571/0.445 | 0.053848 | 0.014692 |
| 12 | `eval_arm6_S_44.json` | 6 | S | 44 | `eb1cee52d2e9a1f489b0e97edf602d3b417ca22ea227c511b7d1c28fb76a8671` | 0.003662 | 0.009644 | 0.037561121903719713 | 0.218485 | 0.422/0.588/0.453 | 0.054786 | 0.015042 |
| 13 | `eval_arm2_S_42.json` | 2 | S | 42 | `a37262b90a8c2d482ea2db6b7e5e70b434075ec28fdd719d3e0af915e3c6d664` | 0.001423 | 0.008900 | 0.031855058776256405 | 0.163888 | 0.419/0.514/0.440 | 0.073408 | 0.000084 |
| 14 | `eval_arm2_S_43.json` | 2 | S | 43 | `d9482983fffb26c7b6218259573d19e7ea267097270562aa6bfb81e4c9a06750` | 0.001689 | 0.010401 | 0.034066564648616147 | 0.177989 | 0.440/0.507/0.451 | 0.089485 | 0.000089 |
| 15 | `eval_arm2_S_44.json` | 2 | S | 44 | `443df6f1914e671762d4e49a03966a83d247ec9a85be8024178ac6b84729f097` | 0.001395 | 0.015005 | 0.044951202828171395 | 0.240843 | 0.397/0.392/0.385 | 0.084855 | 0.000086 |
| 16 | `eval_arm3_S_42.json` | 3 | S | 42 | `ef10a3b7658c484a3d4aac908278f3625ba5d10a61973743207e02f40b5ad3c6` | 0.002569 | 0.017315 | 0.072315474770965296 | 0.437447 | 0.329/0.349/0.335 | 0.100547 | 0.000524 |
| 17 | `eval_arm3_S_43.json` | 3 | S | 43 | `ccfbca1bc58104183b44bc274533ffda0de8332d576a0a13e1eb735e55d9bed4` | 0.001278 | 0.014217 | 0.060057293612409815 | 0.364606 | 0.348/0.475/0.373 | 0.070680 | 0.000585 |
| 18 | `eval_arm3_S_44.json` | 3 | S | 44 | `a8545baffb1b085f47a6c4db2f25e09e876a50ab585dbbbcac9ae9c5e54bc8ce` | 0.001687 | 0.012025 | 0.061666712293234817 | 0.458681 | 0.412/0.523/0.449 | 0.095905 | 0.000614 |
| 19 | `eval_arm1_P_none.json` | 1 | P | - | `63327860b70c22dcb84d679b21afa07ab4bdaf9203e449b66e7b5344caa989b3` | 0.000531 | 0.013580 | 0.045554200055594657 | 0.256834 | 0.341/0.388/0.348 | 0.055331 | 0.000528 |
| 20 | `eval_arm4_P_none.json` | 4 | P | - | `a8d6a86758a05f3c6162cb899c25cfa34bfeed186d07a6c998109e2716793271` | 0.000547 | 0.013484 | 0.048861858816230723 | 0.236451 | 0.405/0.470/0.418 | 0.053466 | 0.000548 |
| 21 | `eval_arm5_P_none.json` | 5 | P | - | `d1cc815c2f4e4e3816e16ecebac57e15f27a29ca0cb1c33786efb42b562709db` | 0.000461 | 0.011902 | 0.038987222088746491 | 0.211198 | 0.341/0.388/0.348 | 0.055331 | 0.005074 |
| 22 | `eval_arm7_P_none.json` | 7 | P | - | `0a60976e4da017f9bc7bbd1fe42cbdc5ffba579d9dae1a6031778b0140dea58b` | 0.000452 | 0.011789 | 0.038801432865321332 | 0.215444 | 0.343/0.394/0.349 | 0.060351 | 0.005209 |
| 23 | `eval_arm1_S_none.json` | 1 | S | - | `877ab55fa4719e9a40b7708d3a6dedab5b4890ddca3add68e4dccc11f083081e` | 0.000539 | 0.013248 | 0.044393647056230938 | 0.242419 | 0.374/0.479/0.386 | 0.056535 | 0.000518 |
| 24 | `eval_arm4_S_none.json` | 4 | S | - | `7f92fb39c77748072f5d49d03352b9cee5a8afbc7318312afd74d65a86c273d8` | 0.000554 | 0.013166 | 0.047959105385425735 | 0.223861 | 0.420/0.497/0.434 | 0.054103 | 0.000546 |
| 25 | `eval_arm5_S_none.json` | 5 | S | - | `18580fb64acccd507c231d2ffcbe6b4bf89ade55e2bcd380ff56944cea5fe4a5` | 0.000482 | 0.011888 | 0.039076484607198328 | 0.206909 | 0.374/0.479/0.386 | 0.056535 | 0.003401 |
| 26 | `eval_arm7_S_none.json` | 7 | S | - | `797ca22af1d58c13787748be5a59bf8a37d999ff868aea48cc2d6e09c9c907c3` | 0.000436 | 0.011425 | 0.037459171199564469 | 0.206491 | 0.371/0.488/0.389 | 0.072802 | 0.003595 |

## 4. 臂 × 族 算术宏平均汇总表（由 26 格原始指标实时计算）

| 臂 | 族 | 格数 | e_1 均值 (m) | e_5 均值 (m) | e_10 均值 (m) | e_30 均值 (m) | 碰撞 Precision | 碰撞 Recall | 碰撞 F1 | 平均能量漂移 | 平均单步延迟 (s) |
| :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| 1 | P | 1 | 0.000531 | 0.013580 | 0.045554200055594657 | 0.256834 | 0.3408 | 0.3879 | 0.3476 | 0.055331 | 0.000528 |
| 1 | S | 1 | 0.000539 | 0.013248 | 0.044393647056230938 | 0.242419 | 0.3741 | 0.4788 | 0.3857 | 0.056535 | 0.000518 |
| 2 | P | 3 | 0.001413 | 0.009986 | 0.029276724579116401 | 0.156939 | 0.4958 | 0.5706 | 0.5114 | 0.076593 | 0.000089 |
| 2 | S | 3 | 0.001502 | 0.011435 | 0.036957608751014649 | 0.194240 | 0.4187 | 0.4712 | 0.4251 | 0.082583 | 0.000086 |
| 3 | P | 3 | 0.003437 | 0.020186 | 0.077746820244738779 | 0.377957 | 0.3549 | 0.4410 | 0.3794 | 0.095519 | 0.000556 |
| 3 | S | 3 | 0.001844 | 0.014519 | 0.064679826892203307 | 0.420245 | 0.3631 | 0.4489 | 0.3855 | 0.089044 | 0.000575 |
| 4 | P | 1 | 0.000547 | 0.013484 | 0.048861858816230723 | 0.236451 | 0.4054 | 0.4696 | 0.4181 | 0.053466 | 0.000548 |
| 4 | S | 1 | 0.000554 | 0.013166 | 0.047959105385425735 | 0.223861 | 0.4204 | 0.4967 | 0.4340 | 0.054103 | 0.000546 |
| 5 | P | 1 | 0.000461 | 0.011902 | 0.038987222088746491 | 0.211198 | 0.3408 | 0.3879 | 0.3476 | 0.055331 | 0.005074 |
| 5 | S | 1 | 0.000482 | 0.011888 | 0.039076484607198328 | 0.206909 | 0.3741 | 0.4788 | 0.3857 | 0.056535 | 0.003401 |
| 6 | P | 3 | 0.002401 | 0.008956 | 0.035069417590233361 | 0.211349 | 0.4155 | 0.5689 | 0.4492 | 0.053259 | 0.016823 |
| 6 | S | 3 | 0.004200 | 0.010189 | 0.036695342749014516 | 0.215516 | 0.4189 | 0.5762 | 0.4464 | 0.054206 | 0.014914 |
| 7 | P | 1 | 0.000452 | 0.011789 | 0.038801432865321332 | 0.215444 | 0.3433 | 0.3942 | 0.3493 | 0.060351 | 0.005209 |
| 7 | S | 1 | 0.000436 | 0.011425 | 0.037459171199564469 | 0.206491 | 0.3708 | 0.4879 | 0.3891 | 0.072802 | 0.003595 |

## 5. 抽样 3 格从 Episode 预测点与 Student 真实轨迹重算 e_10 结果

| 单元文件名 | 臂 | 族 | 种子 | 评测 Episode 数 | 从真值与预测点重算的 e_10 (m) | 原始 JSON summary e_10 (m) | 差异 (Diff) | 校验状态 |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| `eval_arm2_P_42.json` | 2 | P | 42 | 200 | 0.028728605242356493 | 0.028728605242356493 | 0.00e+00 | 严格全等 |
| `eval_arm6_S_43.json` | 6 | S | 43 | 200 | 0.037239625669522235 | 0.037239625669522235 | 0.00e+00 | 严格全等 |
| `eval_arm3_S_42.json` | 3 | S | 42 | 200 | 0.072315474770965296 | 0.072315474770965296 | 0.00e+00 | 严格全等 |


---

## 五、复核结论与验收建议

经全面整改与重做亲验：
1. 生产账本无违规记录，总预留 17640 s 未超 18000 s，实际训练墙钟 7602.40 s 严守 ≤ 3 h 约束，零 final-eval 运行；
2. 18 个训练 checkpoint 全量就位，64 位完整 SHA-256 与 best_step 严密吻合；
3. dev 评测 26 格原始结果、算术宏平均以及端到端真值轨迹重算指标差值全量为 `0.00e+00`；
4. sealed_final 封存未受任何污染或读取；
5. 冻结文档与代码身份验证完全通过；
6. final-eval 入口与 analysis 源码机制特征核查明确无误。

**复核结论**：**建议通过**。
