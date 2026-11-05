# 任务 ainerzero.V9.T55 执行报告：【L2·gemini·非作者复核】T54 DA3 唯一一次真跑

## 执行者
- **执行者 ID**：`gemini-r4x9`（层级 2 · 执行层）
- **复核目标**：`ainerzero.V9.T54`（执行者一级 `claude`）
- **工作目录**：`/Users/mac/AinerWorkFlow/AinerZero`
- **复核原则**：零模型运行、零账本写入（无加载 DA3 权重，只读复制 runs.db 进行审计与离线重算）。

---

## 执行摘要（<= 30 行）
1. **核验结论**：**建议通过**（本复核针对 T54 真跑的真实性、账本记账合规性、前向证据完整性及离线数学重算；确认 T54 过程真实、证据无篡改；协议本身因 DA3-SMALL 负对照未变红而判定为 `failed` 属客观事实且已被真实记录）。
2. **SHA256 完整性**：`reports/V9-T54/`（24 项）与 `reports/V9-T28/registration/`（16 项）所有文件的 `SHA256SUMS.txt` 均 100% 校验通过。
3. **登记链**：`reports/V9-T28/REGISTERED.json` 之 SHA 与 `reports/V9-T28/r2/proposal.json` 真实 SHA 完全一致（`31eef66689f82ea79ab50dd4cca7a15b8430c7d44aaf0dbcf0abf98fb989d278`）；`t28_registration.load_t28_registration()` 实测返回 views=50 / cap=1440.0s / budget=120.0s。
4. **账本与预算**：生产 `runs.db` SHA 保持 `61242c30ffb56621615107ce971c2ff7802e3a30b7491294297239df3c3e0d01` 未受篡改；对比备份仅新增 `t6_views_override_20261028` 元数据、单次真跑 `a7bcc4c9ee0e4a9f93cad49746b973a9`（views=50, active_seconds=120.0, state=failed）及 2026-10-28 daily_budget 行；全线 DA3 累计精准收敛于 **249 视 / 1440.0 秒**。
5. **运行完整性与中继监督**：`calibration_evidence.json` 前向记账完整（DA3-SMALL/BASE 计划=实际=9调用/25视，`complete=true`）；`stages` 结构完整；`failures` 仅 1 项（`DA3-SMALL/frame_order_adverse`）；`run.stderr.log` 证实 relay exec 监督确证 `confirmed_empty=True, members_left=[]` 无残留进程。
6. **负对照与 CPU 一致性独立重算**：自建评分函数独立从 predictions safetensors 与真值 fixtures 重算：DA3-SMALL 差值 0.014636 < 0.063875 未变红，DA3-BASE 差值 0.961995 >= 0.015600 变红；CPU 对比 MPS 最大绝对误差均与证据记录完全相符（误差 <= 1e-9）。
7. **变异体对抗测试**：注入 S_bad 篡改与 views 篡改变异体，均被对应复核步骤拦截。

---

## 逐项核验结果与逐字引用

### 1. SHA256SUMS 完整性核验
- **执行命令**：
  ```bash
  cd reports/V9-T54 && shasum -a 256 -c SHA256SUMS.txt
  cd reports/V9-T28/registration && shasum -a 256 -c SHA256SUMS.txt
  ```
- **输出与核验结果**：全部 24 + 16 个文件 `OK`，无一缺失或篡改。
- **逐字引用**：
  - `reports/V9-T54/SHA256SUMS.txt:1-2`:
    ```text
    4a4d6df1b34bb5cb5d7b5ae1772fe24ea57a419eb31c07010f384c2fa023a968  REPORT.md
    c6dd5c3efce04e76a6058cc870428d00ca7c40d2d385559dc98f48c3f7697dd6  calibration_evidence.json
    ```
  - `reports/V9-T28/registration/SHA256SUMS.txt:1-2`:
    ```text
    1694ed305c1a80d14ec0bfcf4117e16b246ce82b85c51fab16394e530dda9ff5  PRE_E18_REPORTS.txt
    31eef66689f82ea79ab50dd4cca7a15b8430c7d44aaf0dbcf0abf98fb989d278  proposal.json
    ```

### 2. 登记链核验
- **实算 SHA256**：`reports/V9-T28/r2/proposal.json` 字节 SHA256 为：
  `31eef66689f82ea79ab50dd4cca7a15b8430c7d44aaf0dbcf0abf98fb989d278`。
- **逐字引用**：
  - `reports/V9-T28/REGISTERED.json:2`:
    ```json
    "sha256": "31eef66689f82ea79ab50dd4cca7a15b8430c7d44aaf0dbcf0abf98fb989d278"
    ```
- **代码调用输出**：
  执行 `from ainerzero.v9.teachers import t28_registration; reg_info = t28_registration.load_t28_registration()`：
  - `reg_info.calibration_views`: `50`
  - `reg_info.cumulative_wall_cap_s`: `1440.0`
  - `reg_info.run_wall_budget_s`: `120.0`
- **逐字引用**：
  - `src/ainerzero/v9/teachers/t28_registration.py:44-46`:
    ```python
    calibration_views=50,
    cumulative_wall_cap_s=1440.0,
    run_wall_budget_s=120.0,
    ```

### 3. 账本一致性与全线额度核验
- **只读审计流程**：复制生产 `artifacts/v9/teachers/benchmark/runs.db` 至 `reports/V9-T55/gemini-r4x9/runs.db`，使用 `sqlite3.connect('file:.../runs.db?mode=ro', uri=True)` 审计。
- **生产 runs.db SHA256**：
  `61242c30ffb56621615107ce971c2ff7802e3a30b7491294297239df3c3e0d01`（完全一致）。
- **对比前置备份**（`reports/V9-T28/registration/runs-db-before-override.sqlite3`）：
  - 表结构完全一致：`{'daily_budget', 'experiments', 'metadata', 'run_transitions', 'runs'}`。
  - 元数据变更：仅增加元数据键 `t6_views_override_20261028`（以及系统 `clock_high_water` 更新）。
    - 逐字引用元数据字段：`"new_max_views": 249`，`"authorized_by": "user"`，`"user_words": "Whole line, 249/1440"`，`"t28_proposal_sha256": "31eef66689f82ea79ab50dd4cca7a15b8430c7d44aaf0dbcf0abf98fb989d278"`。
  - 运行记录变更：新增且仅新增一条运行记录 `a7bcc4c9ee0e4a9f93cad49746b973a9`：
    - `state`: `"failed"`
    - `active_seconds`: `120.0`
    - `config`: `task="ainerzero.V9.T6"`, `views=50`, `model="da3-all"`。
  - 日预算表：新增日期 `2026-10-28`，`allocated_active_seconds=120.0`。原有日期记录逐行一致。
- **全线累计统计（按 model 包含 da3 汇总）**：
  - `ainerzero.V9.T6`: 131 视，1290.0 秒（8 次运行）
  - `ainerzero.V9.T33`: 82 视，140.0 秒（5 次运行）
  - `ainerzero.V9.T33.r2`: 36 视，10.0 秒（2 次运行）
  - **全线 DA3 合计**：**249 视，1440.0 秒**（15 次运行）。精准契合授权上限。

### 4. 运行完整性与中继进程监督
- **前向记账**：
  - 逐字引用 `reports/V9-T54/calibration_evidence.json:2-15`：
    ```json
    "forward_accounting": {
      "DA3-SMALL": {
        "calls_planned": 9,
        "calls_actual": 9,
        "views_planned": 25,
        "views_actual": 25,
        "complete": true
      },
      "DA3-BASE": {
        "calls_planned": 9,
        "calls_actual": 9,
        "views_planned": 25,
        "views_actual": 25,
        "complete": true
      }
    }
    ```
- **阶段完整性与失败记录**：
  - 各型号包含 6 个阶段：`first_frame`, `calibration`, `frame_order_adverse`, `intrinsics_adverse`, `cpu_parity`, `half_parity`。
  - 逐字引用 `reports/V9-T54/calibration_evidence.json:442-446`：
    ```json
    "failures": [
      "DA3-SMALL/frame_order_adverse: adverse control did not turn red"
    ],
    "status": "failed"
    ```
- **中继进程监督**：
  - 逐字引用 `reports/V9-T54/run.stderr.log:21-22`：
    ```text
    relay exec: child exited rc=1
    exec supervision: confirmed_empty=True members_left=[]
    ```
    确认无孤儿或后台残留进程。

### 5. 负对照独立重算（独立编写评分与阈值判定）
- **计算逻辑**：
  - 评分公式：$S = \text{rotation\_error\_rad} + \|\text{translation\_residual3}\|_2 + \text{depth\_abs\_rel}$
  - 红线判定：$\text{diff} = S_{\text{bad}} - S_{\text{clean}} \ge \max(\text{red\_floor}, \text{red\_rel} \times S_{\text{clean}})$（其中 `red_floor`=0.01, `red_rel`=0.10）
- **重算数值对比（容差 <= 1e-9）**：
  - **DA3-SMALL**：
    - 实算 $S_{\text{clean}}$: `0.6387489435518366`（证据：`0.6387489435518366`，误差：`0.0`）
    - 实算 $S_{\text{bad}}$: `0.6533851351973012`（证据：`0.6533851351973012`，误差：`0.0`）
    - 实算差值: `0.0146361916454646`
    - 要求门限: $\max(0.01, 0.10 \times 0.63874894) = 0.0638748943551837$
    - 是否变红: `False`（未变红，证据记录 `turned_red: false`，精确一致）
  - **DA3-BASE**：
    - 实算 $S_{\text{clean}}$: `0.1560045094586439`（证据：`0.1560045094586439`，误差：`0.0`）
    - 实算 $S_{\text{bad}}$: `1.1179992040038003`（证据：`1.1179992040038003`，误差：`0.0`）
    - 实算差值: `0.9619946945451564`
    - 要求门限: $\max(0.01, 0.10 \times 0.15600451) = 0.0156004509458644$
    - 是否变红: `True`（变红，证据记录 `turned_red: true`，精确一致）

### 6. CPU Parity 独立重算
- **重算数据源**：`predictions/<variant>/cpu_parity/t6-analytic-room-00/pred.safetensors` 对比同场景 MPS 参考。
- **重算结果对比（逐字段 max_abs 容差 <= 1e-9）**：
  - **DA3-SMALL**：
    - `depth`: 实算 max_abs = `0.0004938244819641113`（证据：`0.0004938244819641113`，failed=0）
    - `confidence`: 实算 max_abs = `0.00016480684280395508`（证据：`0.00016480684280395508`，failed=0）
    - `extrinsics`: 实算 max_abs = `0.0`（证据：`0.0`，failed=0）
    - `intrinsics`: 实算 max_abs = `0.0`（证据：`0.0`，failed=0）
  - **DA3-BASE**：
    - `depth`: 实算 max_abs = `0.0006760954856872559`（证据：`0.0006760954856872559`，failed=0）
    - `confidence`: 实算 max_abs = `0.00020110607147216797`（证据：`0.00020110607147216797`，failed=0）
    - `extrinsics`: 实算 max_abs = `0.0`（证据：`0.0`，failed=0）
    - `intrinsics`: 实算 max_abs = `0.0`（证据：`0.0`，failed=0）

### 7. 对抗变异测试
在 `reports/V9-T55/gemini-r4x9/adversarial_test.py` 中构造独立隔离环境进行对抗攻击验证：
1. **变异体 1（篡改 DA3-SMALL 的 S_bad 使其伪装变红）**：
   - 篡改：将 `evidence["stages"]["DA3-SMALL"]["frame_order_adverse"]["S_bad"]` 改为 1.5。
   - 拦截结果：独立重算算法对比实测 safetensors 计算值为 0.653385，立即检出不一致并抛出 `AssertionError: Discrepancy detected in recalculation vs evidence`。
2. **变异体 2（篡改 runs.db 副本中 views 使其超支）**：
   - 篡改：将运行 `a7bcc4c9ee0e4a9f93cad49746b973a9` 的 `views` 从 50 修改为 51。
   - 拦截结果：账本重算总视数变为 250，立即被全线总额度守卫拦截并抛出 `AssertionError: Total DA3 views 250 != 249`。

---

## 复核结论
- **建议结论**：**建议通过**
- **结论说明**：T54 真跑的登记、配额限制、账本记账、证据留存与离线计算全部真实可信且复现一致。协议自身结果 `status: "failed"` 已如实记录，无隐瞒无篡改，符合复核通过标准。
