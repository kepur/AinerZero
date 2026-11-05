# ainerzero.V9.G8 执行报告：非作者对抗复核 ainerzero.V9.G7（CMFL 原型）

角色：executor（复核方）；负责人：`deepseek-m8q4`；时间：2026-10-28
任务状态：reported；实验状态：**只读核对 + CPU 工程测试，零训练、零 MLX、零下载、零新包**
任务依据：Relay 卡 `ainerzero.V9.G8`（L3 强代理、非作者对抗复核）；被复核对象 `ainerzero.V9.G7`（reported，作者 `claude-az`）；ADR-0014 r3（`AnimeWorldZero/docs/adr/ADR-0014-constrained-mechanism-formation.md`）
修改文件：**`src/` 零改动**（7 个模块 SHA-256 与 `reports/V9-G7/evidence/SHA.txt` 逐条一致，见 `evidence/sha.txt`）。新增只在 `reports/V9-G8/`：`independent_gen.py`、`g8_checks.py`、`mutation_harness.py`、`test_g8_adversarial.py`、`run_g8.py`、`metrics.json`、`evidence/`。

## 0. 结论（先给判定）

**判定：request_changes。**

四条阻塞项（都在"声称成立的结论"与"实现"之间，不是风格问题）：

| # | 阻塞项 | 一句话证据 |
|---|---|---|
| **F1** | **正交投影（ADR §2 D2-7）在 `discover()` 的批量路径上不成立**，且它是 G7「精确支持恢复 20/20」的承重件 | 池化基秩只有 3/64；逐上下文残余能量比 `[1.856, 0.454, 2.587, 0.469, 1.785, 0.459]`——**两个上下文投影后能量反而增大 86%/159%**。结构世界精确支持从 20/20（不投影）掉到 13/20，出现系数 34.3 的错误项（真值 0.55） |
| **F2** | **e-LOND 总闸门没有接线** | `promotion_gate.py:524` 的 `admitted` 合取式不含 `e_lond_passed`/`e_pers`；`:517` 的 `... or sup_passed` 又让它在准入时恒为 True。坏控 M5（恒置 False）→ 准入结论**完全不变** |
| **F3** | **全环境交并 `E_pers = min_e E^e` 静默退化成 dev-only** | `:373` 用 `context_id`/`world_instance_id` 子串猜环境族，未打标签时全落到 `env_families[0]`；`:503` 对空族回落 `world_ids` → 三族 e-value 完全相同（唯一值个数 1）。这正是 ADR M2 警告的 0.621 失效模式 |
| **F4** | **「负对照准入率 = 0」只对"空候选"成立** | NC-A/NC-B 准入 0/6，但 6/6 都是 `0 active terms` 被前置拒绝；换成**非空但机制错误**的候选（coulomb_friction 0.45 顶替 quadratic_drag 0.55），准入 **6/6** |

## 1. 摘要（≤30 行）

- 自己写了独立玩具生成器（`independent_gen.py`，W=16、dt=0.015、σ=2.5e-3，自实现 RK4/Euler，不 import `toy_worlds` 的生成与积分）。80 个上下文上 8 路由准确率 **0.975**，逐路由召回除 PARAMETRIC 外全 1.0。
- 卡面要求的四项坏控：**三项照字面成立、一项不成立**。
  - 坏控 1「调换 PARAMETRIC 与 STRUCTURAL 判定顺序」：**字面版本是空操作**（M1a 路由序列逐条相同、召回不变）。实质版本（M1b：跳过参数再辨识直接判 STRUCTURAL）才有效 → PARAMETRIC 召回 0.867 → **0.000**，测试变红。
  - 坏控 2「去掉共形有限样本修正」：n_cal=18 时 k 从 19 变 18、证书从"作废"变"有效" → 测试变红。
  - 坏控 3「让发现与检验数据重叠」：两视图从"不同 + 交叉协方差 1.0e-7"变"完全相同"，空世界假发现 0.10 → **0.45** → 测试变红。
  - 坏控 4「去掉正交投影」：单上下文 `max|<r_perp,q>|` 从 1.9e-16 变 0.245、批量能量比从 0.738 变 1.000、ALDER 负对照准入从 0/6 变 **2/6** → 三条测试变红。
- 负对照准入率：**对 ALDER 型构造成立（0/6），对"非空错误机制"不成立（6/6）**。所以"负对照准入率必须为 0"这个不变量在 G7 里是被"空候选"这条前置条件满足的，不是被统计门满足的。
- G7 报告里最容易被当成"已通过"的两个数字都不宜引用：`OOD 召回 1.0` 由生成器塞进来的 `in_slow_domain=False` 布尔量承载（无包络时同为 6/6，去掉标签后 0/6）；`发现恢复 20/20` 只在 W=20/dt=0.01 这一组设定成立。
- 我认为 G7 的**结构**（8 路由瀑布、4a 下尾、留出复检、C_clean 剔除 4a、D/C/T 不相交、C2 出具者守卫、N3 重测记账、data thinning、共形有限样本修正）是对的，可继续用；**阻塞的是三处实现没有做到它自己声明的约束**（F1–F3）和一处验收不变量被弱化（F4）。

## 2. 实际执行

```
env -u PYTHONPATH -u HTTP_PROXY -u HTTPS_PROXY -u http_proxy -u https_proxy \
    NO_PROXY=127.0.0.1,localhost,::1 .venv/bin/python -m pytest \
    tests/v9/mechanism reports/V9-G8/test_g8_adversarial.py -q
# 28 passed in 8.06s   （9 = G7 原测试，19 = 本次对抗测试）→ evidence/pytest.txt

env -u PYTHONPATH ... .venv/bin/python reports/V9-G8/run_g8.py
# → metrics.json、evidence/numbers.txt、evidence/mutation_matrix.txt、evidence/sha.txt
```

- 坏控不是"复核者另写一份逻辑"：`mutation_harness.py` 把 `src/ainerzero/v9/mechanism/` **复制到 tempdir 做文本变异**（每处替换断言恰好命中 1 次），再以独立包名导入。仓库源码未被改动。
- 全部随机性由固定 seed 派生；真实路由标签只进 `TruthMeta`，不进 `ObservationContext`（§8.6）。

## 3. 逐条结论

### 3.1 可以确认成立的部分

| 项 | 复核结果 |
|---|---|
| 8 路由瀑布（含 4a 下尾） | 独立生成器 80 个上下文准确率 **0.975**；SUFFICIENT / OUT_OF_DOMAIN / NUMERICAL / COVARIANCE_INCONSISTENT / UNIDENTIFIABLE / STRUCTURAL / ABSTAIN 召回均 **1.0** |
| 4a 下尾拦截（M4/N4） | S 放大 12× 的 6 个上下文全部落 4a（NIS 3.8–6.5 ≪ χ²₆₄(0.025)=43.78） |
| 共形有限样本修正（D3-4） | n_cal=18、α_dom=0.05 → k=19>18 → 证书作废；n_cal=19 → k=19 有效。经验边际覆盖 **0.935**（名义 0.95，n_cal=39，200 次留出），偏差 1.5 pp，可接受 |
| data thinning（D2-8） | 两视图不同（最大差 1.79e-2），交叉协方差 **9.98e-8**（单视图方差 1.25e-5），比值 0.8%，符合 Cov(R+Z,R−Z)=0 |
| 单上下文正交投影 API | `max|<r_perp,q>| = 1.9e-16 / 1.0e-16`（single_step / k_step），分解恒等式 `r = r_perp + r_absorbed` 成立 |
| C2 出具者守卫 / N3 重测记账 / D-C-T 不相交 | 代码与测试都在；我的复核没有找到绕过路径（`N` 的口径问题见 F8） |
| 数值工具 | `chi2_ppf` 与解析值（dof=2 精确式）及自洽反演一致；纯 NumPy、无 MLX/torch/scipy 导入 |

### 3.2 F1（阻塞）正交投影在批量路径上不成立，且它让发现变差

`discovery.py:287-300` 的 `_project_views_orthogonal` 把 6 个上下文各自 (W,4) 的视图**拼成一个 384 维向量**再对 `q_pool`（形状 (384,3)）做一次投影。池化基秩上限就是参数维数 3，而每个上下文的残差活在自己那 3 维子空间里（由该上下文的 v_k、p_k 决定），所以：

- 逐上下文残余能量比 `[1.856, 0.454, 2.587, 0.469, 1.785, 0.459]`——整批能量确实下降到 0.738，但**单块能量可以上升**（2.587 意味着投影后能量是原来的 2.6 倍）。
- 单上下文自投影（正确的做法）应为 **0.0227**（纯参数世界）/ **0.0043**（结构世界）。
- 后果一：纯参数世界（无结构项）上 `discover()` 仍报出结构项 **9/10**（作者生成器同口径是 1/20）。
- 后果二：结构世界精确支持恢复 **13/20**（关掉投影反而 **20/20**，系数中位 0.523 vs 真值 0.55）；投影开启时出现 `altered_inv_r_gravity` 系数 **34.3** 这类病态解。

也就是说，G7 §1 的「quadratic_drag 20/20、altered_inv_r 20/20」是**设定特异**的；换一组独立但相邻的 (W, dt, σ) 就不成立。这不是"结论错"，而是"结论被写成了一般性能"。

另有一条 ADR 层面的问题：结构世界残差被投掉 **99.6%**（0.0043），说明二次阻力与 `c_lin` 灵敏度方向几乎共线（两者都沿 −v）。ADR §2 D2-7 只写了"φ̂ 是 L² 投影参数"，没写"与参数方向共线的结构机制在此投影下几乎不可检出"——这是该硬投影的固有代价，应当写进已知限制，而不是靠 20/20 掩盖。

### 3.3 F2（阻塞）e-LOND 总闸门未接线

```python
# promotion_gate.py:517
e_lond_passed = bool(e_pers >= (1.0 / max(alpha_per_cand, 1e-15)) or sup_passed)
# promotion_gate.py:524
admitted = (len(reasons) == 0 and sup_passed and old_passed and zero_reg_passed
            and stable_ok and cert.certificate_valid)
```

- `e_lond_passed` / `e_pers` 不在 `admitted` 里，ADR §2 D3 统一错误预算表第一行"e-LOND 序列预算 α_t —— 第 t 次晋升决策（**总闸门**）"在实现中不存在。
- `or sup_passed` 让 `e_lond_passed` 在准入时恒为 True，所以这个字段是装饰。ADR N2 明确说 e-process 路径与固定样本 p 值路径"是不同检验构造，不作双向代数等价"，这里的 `or` 恰好是把两条构造混在一起。
- 坏控 M5（`e_lond_passed = False` 恒置）→ `admitted` 仍为 True，**没有任何测试变红**（`test_bad_control_M5_elond_gate_removal_changes_nothing`）。
- 实测：`e_pers=66.4`、`1/α=65.8`，只差 1%，说明 e-process 路径本身是"擦边"运行的，不是一个有裕度的门。

### 3.4 F3（阻塞）全环境交并退化为 dev-only

`:373` `fam = self.registration.env_families[0]`，然后按 `f_name.lower() in wid.lower()` 猜族；`:503-505` 某族没有世界块时回落 `fam_worlds = world_ids`。测试集未打族标签时（G7 自己的 `run_report.py` 和 `test_cmpl_prototype.py` 都是这种）三个族都回落到全部世界块 → `e_by_family` 三值完全相同（唯一值个数 **1**）→ `E_pers = min_e E^e` 等于 dev-only e-value。

这正是 ADR M2 用 0.621 警示的失效模式，而且它是**静默**发生的：没有任何断言要求"三个族的世界块集合互不相同"。G7 §1 的 M2 数字（dev-only FDP 0.75 / 全环境 0.0）来自 `simulate_elond_dev_only_vs_all_env` 这个**独立仿真函数**，不是来自 `evaluate_and_promote` 的实际路径——两条路径的行为没有一致性检查。

### 3.5 F4（阻塞）「负对照准入率 = 0」被弱化成"空候选不能晋升"

| 负对照 | 非空候选 | 准入 |
|---|---|---|
| NC-A 候选库缺 `quadratic_drag`（ALDER） | 0/6 | **0/6** |
| NC-B 候选库缺 `altered_inv_r_gravity` | 0/6 | **0/6** |
| NC-C **非空但机制错误**（coulomb_friction 0.45 顶替 quadratic_drag 0.55） | 6/6 | **6/6** |

NC-A/NC-B 的拒绝理由是 `candidate has 0 active terms (empty discovery)` 与 `bootstrap upper bound U=0.0 >= -delta_gain`。前者不是统计判定，后者只说明"空候选不改善损失"。门的判据只有"比现任好 δ_gain 以上"，没有"候选是否解释了残差"这一条；D3-4 的共形证书只校验 `k ≤ n_cal`，不设残差包络宽度上限，因此也不构成拟合优度门。

于是 NC-C 被准入：coulomb_friction 方向正确（沿 −v）但机制错误，损失确实下降，于是一路通过 superiority、逐例零回归、稳定过滤器、共形证书。

ADR §2 D1 评测条款要求"负对照：候选库故意缺项或缺状态时，晋升准入率应为 0"。按字面，G7 满足；按意图（控制错误接受），不满足。**这一条必须改写成能挡住非空错误候选的形式，否则 SLOW 会被"方向对、机制错"的条目污染。**

### 3.6 F5（阻塞"结论"，不阻塞"代码"）OOD 召回由调用方布尔量承载

`sufficiency_gate.py:161-166` 的 `_check_in_domain` 第一句是 `if not context.in_slow_domain: return "..."`。`in_slow_domain` 是 `ObservationContext` 的普通字段，不在 `FORBIDDEN_OBSERVATION_FIELDS` 里；`build_benchmark_suite` 恰好在 OOD 族把它置 `False`。G7 的混淆矩阵用的是 `MechanismSufficiencyGate(reg)`（**没有包络**），所以 OOD 召回 1.0 完全来自这个标签。

三配置对照（`msg_ood_leak_probe`）：

| 配置 | OOD 命中 |
|---|---|
| 只有 `in_slow_domain=False` 标签、无包络 | **6/6** |
| 只有共形包络、标签恒 True | **6/6** |
| 两者都没有 | **0/6** |

包络本身是有效的（n_cal=24、OOD 6/6、域内 6/6 保留），所以修法很简单：G7 的混淆矩阵必须用**带包络**的 gate，且 OOD 上下文不得携带真值标签。附带一个数字：`DomainEnvelope` 用 D∪C 的 min/max 盒，对新的同分布上下文只保留 **0.60**（40% 误判 OOD）——盒式包络在小样本高维协变量上覆盖很差，建议在报告里如实写明或改包络构造。

### 3.7 非阻塞但应修

- **F6 PARAMETRIC 召回不是 0.975。** 独立设定下 26/30 = **0.867**（W=16）/ 28/30 = 0.933（W=20）。漏判流向 4a 下尾：留出 NIS 系统性偏低（`NIS_hold/dof` 均值 0.95，最小 0.48），因为预测协方差用的是**先验主导**的后验 Σ（拟合窗只有 8–10 步），Σ 偏宽 → 留出 NIS 偏小 → 撞 4a 下界（dof=32 时下界 18.29，实测 15.7/17.9）。建议：拟合窗过短时不要把 `JΣJᵀ` 全量加进预测协方差，或在 4a 判定前对 `param_cov` 做一次标定。
- **F7 路由顺序偏离 ADR 表。** ADR 表序是 5 PARAMETRIC → 6 UNIDENTIFIABLE；`sufficiency_gate.py:281` 把 UNIDENTIFIABLE 判在 PARAMETRIC 之前（`:298`）。后果：一个留出复检本可通过的上下文，只要 λ_min < τ_id 就永远进不了 PARAMETRIC。这是"更保守"，但属于未声明的偏离，要么改代码要么改 ADR。
- **F8 `N` 的口径错了。** `:428` 的 `n_total_attempts` 取 `candidate.total_candidates_attempted`，而后者在 `discovery.py` 里是 **STLSQ 内层迭代次数**（实测 2），不是"本次送检候选数"。于是 `α_t/N` 被无谓压小（0.0304 → 0.0152）。ADR 定义 N 是"同一发现作业向 T 送检的候选数"。
- **F9 坏控 1 的字面版是空操作。** 见 §4。
- **F10 空世界假发现 0.10（2/20）**，G7 报 0.05（1/20）；两者都在 20 次样本的宽区间内，不应互相引用为常数。

## 4. 坏控证据（`evidence/mutation_matrix.txt`）

| 坏控 | 路由序列相同 | PARAMETRIC召回 | 共形k(n=18) | 共形有效 | 视图相同 | 交叉协方差 | 空世界假发现 | 投影max_ip | 批量能量比 | 结构精确支持 | NC-A | NC-B | NC-C | 准入 | e_lond |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| baseline | — | 0.867 | 19 | False | False | 9.98e-08 | 0.10 | 1.94e-16 | 0.738 | 13/20 | 0.00 | 0.00 | 1.00 | True | True |
| M1a 字面调换 | **True** | **0.867** | 19 | False | False | 9.98e-08 | 0.10 | 1.94e-16 | 0.738 | 13/20 | 0.00 | 0.00 | 1.00 | True | True |
| M1b STRUCTURAL 提前 | False | **0.000** | 19 | False | False | 9.98e-08 | 0.10 | 1.94e-16 | 0.738 | 13/20 | 0.00 | 0.00 | 1.00 | True | True |
| M2 去共形有限样本修正 | True | 0.867 | **18** | **True** | False | 9.98e-08 | 0.10 | 1.94e-16 | 0.738 | 13/20 | 0.00 | 0.00 | 1.00 | True | True |
| M3 发现/检验重叠 | True | 0.867 | 19 | False | **True** | **1.25e-05** | **0.45** | 1.94e-16 | 0.738 | 11/20 | 0.00 | 0.00 | 1.00 | True | True |
| M4 去正交投影 | True | 0.867 | 19 | False | False | 9.98e-08 | 0.00 | **2.45e-01** | **1.000** | **20/20** | 0.00 | **0.33** | 1.00 | True | True |
| M5 e-LOND 恒 False | True | 0.867 | 19 | False | False | 9.98e-08 | 0.10 | 1.94e-16 | 0.738 | 13/20 | 0.00 | 0.00 | 1.00 | **True** | **False** |
| M6 放开空候选 | True | 0.867 | 19 | False | False | 9.98e-08 | 0.10 | 1.94e-16 | 0.738 | 13/20 | 0.00 | 0.00 | 1.00 | True | True |

读法：

1. **M1a 全行与 baseline 相同** → 卡面写的「调换 PARAMETRIC 与 STRUCTURAL 的判定顺序」若照字面实现，**任何测试都不可能变红**。原因：两块的判据互补（`nis_hold <= q_hold_high` vs 其补集），且都在同一处留出复检之后求值。坏控必须写成 M1b（跳过参数再辨识直接判 STRUCTURAL）才有牙齿——这一条我按要求做到了，但**卡面的坏控清单本身需要修正**。
2. **M2 只动两处**（`k` 去掉 `+1`、去掉 `k>n_cal` 作废），就把 n_cal=18 的证书从"作废"翻成"有效" → 有限样本修正确实是承重件。
3. **M3**：视图完全相同、交叉协方差从 1.0e-7 涨到 1.25e-5（= 单视图方差，即完全相关），空世界假发现 0.10 → 0.45。这条坏控改变 4 项测量（视图相同、交叉协方差、空世界假发现、结构精确支持 13→11）；本文件对"视图相同"与"假发现率上升 >0.15"有断言。
4. **M4**：单上下文 `max_ip` 1.9e-16 → 0.245；批量能量比 0.738 → 1.000（恒等）；**NC-B 漏放 2/6**。注意同时它让结构精确支持 13/20 → **20/20**——即当前的正交投影是在**损害**发现，而不是在保护它（F1）。
5. **M5 只把 `e_lond_passed` 翻成 False，准入不变** → 总闸门是装饰（F2）。
6. **M6 放开空候选**，NC-A/NC-B 仍 0/6（因为 superiority 也挡住了），说明空候选不是唯一防线；但 NC-C 依旧 6/6 —— 真正的缺口是"没有拟合优度门"（F4）。

## 5. 产物

- `reports/V9-G8/REPORT.md`（本文件）
- `reports/V9-G8/metrics.json`（全部数字，`mutation_matrix` 字段含 8 行坏控对照）
- `reports/V9-G8/evidence/numbers.txt`、`mutation_matrix.txt`、`sha.txt`、`pytest.txt`
- `reports/V9-G8/independent_gen.py`（自写生成器）、`g8_checks.py`（测量）、`mutation_harness.py`（文本变异）、`test_g8_adversarial.py`（19 条）、`run_g8.py`（复跑入口）

## 6. 失败与限制

- 我**没有**复核 ADR 正文与 `cmfl_registration.json` 字段的逐条一致性（G7 自己列了这条待办）。我核对的是 7 个模块 SHA 与 ADR 的路由表/判据/预算表。
- 我**没有**跑 AWZ 真实数据、没有接 S1、没有触碰 `runs.db`/锁/预算；本卡不授权训练与 MLX，我没有启动任何模型工作。
- `conformal_coverage` 的 0.935 是单次 200 样本估计（二项标准误约 0.017），与名义 0.95 相差 1.5 pp，**不能据此宣称覆盖不达标**，只能说不矛盾。
- F1 的机制诊断（"池化基秩 3、逐块能量可增"）来自对 `_project_views_orthogonal` 的读码 + 实测，我没有提出替代实现（不在本卡文件范围）。
- 我的生成器与作者生成器物理函数同族（否则无法与 `F_prior` 对话），差异在积分器实现、参数抽样、W/dt/σ 与世界命名。因此"设定特异"的结论只对**同一物理族内的设定变化**成立，不外推到别的物理族。
- `NIS_hold/dof` 的 0.95 均值是 30 个上下文×4 个 W 各一组的均值，样本量小；F6 应作为"需要再测"的疑点，而不是定论。

## 7. 交回统筹（需要决定的问题）

1. **F1**：正交投影是要（a）改成逐上下文投影并重跑发现指标，还是（b）保留现状但把"20/20"改写成"设定特异，且投影使恢复率下降"？我建议 (a)+(b) 同时做。
2. **F2/F3**：e-LOND 总闸门与全环境交并要不要真接线？如果接，`evaluate_and_promote` 需要环境族标签作为必需输入（不能靠子串猜），并且 `simulate_elond_dev_only_vs_all_env` 与实际路径要有一条一致性测试。
3. **F4**：负对照的验收口径要不要从"缺项 → 空候选"改成"非空但机制错误必须被拒"？如果是，需要新增一条拟合优度判据（例如候选在 `C_clean` 上的残差分位数不得超过现任的某个倍数），这属于 ADR 条款变更，需统筹决定，不在复核卡权限内。
4. **F5**：G7 的混淆矩阵是否重跑（带包络、不带标签）？重跑不得覆盖 `reports/V9-G7/`（COORDINATION 规则 8），建议在 G9 或 G7-r2 下新建目录。
5. **F7/F8**：路由顺序与 `N` 口径是改代码还是改 ADR 正文？两者都需要新登记 SHA。

**我没有、也不会**自行改 `src/`、改 ADR、重跑 G7 的数字、或把本复核写成 accept。
