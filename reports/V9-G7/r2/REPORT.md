# V9.G7 r2 — CMFL 原型按 G8 复核意见返工

- 卡：`ainerzero.V9.G7`（r1 被 G8 `request_changes` 退回，见 [G8 报告](../../V9-G8/REPORT.md)）
- r2 作者：`claude`（一级接手执行）。**本轮需要非作者复核**，作者本人与同会话别名不能复核。
- 写入范围：`src/ainerzero/v9/mechanism/`、`tests/v9/mechanism/`、`reports/V9-G7/r2/`。r1 原样归档在 `reports/V9-G7/r1-archive/`（15 个文件，附 `SHA256SUMS.txt`）。
- 未提交、未推送；没有训练、下载或付费调用。

## 1. 结论（≤10 行）

1. F1–F4 和 OOD 真值泄漏都已修复。每处修复都有对应的坏控：把 r1 行为改回源码副本后，相应场景都会变红（6/6）。
2. F1 的修法和 G8 的建议不完全一样。G8 建议逐上下文硬投影，但在 G8 自己的设定下，硬投影会把 99.6% 的阻力信号吸走，再把剩下的部分错配给位置项：20 次里 9 次报出 `altered_inv_r≈35 + cubic_spring`。r2 的默认推荐是逐上下文 GLS：给每窗参数偏差加一个高斯先验 δφ_c ~ N(0, Σ_φ)，硬投影是 Σ→∞ 的极限。硬投影保留为 `nuisance_cov=None` 模式。
3. 在 G8 生成器上，GLS 的纯参数世界假发现是 1/10，结构世界精确恢复 20/20。对照：不投影是 10/10 和 20/20；r1 合并投影是 9/10 和 13/20；硬投影是 0/10 和 6/20。
4. e-LOND 现在是准入合取项。代价是测试世界要多：第 1 步、N=2 时 1/α≈66，每族约 15 个世界块。正对照的测试集因此从 12 扩到 45。
5. FactTest（D3-8）已接线，零假设类不足 29 个时失败关闭。G8 F4 的错误候选（coulomb 0.45 顶替 drag 0.55）在 120 个世界下通过了其余所有检查，**只被 FactTest 拒绝**（得分 0.00，阈值 0.80 或 1.00）。

## 2. 改动

| 文件 | 改动 |
|---|---|
| `toy_worlds.py` | `ObservationContext` 删去 `in_slow_domain`，新增显式 `env_family`；`in_slow_domain` 移进 `GroundTruthMeta`（只供评测），并加进 `FORBIDDEN_OBSERVATION_FIELDS`；`simulate_window(env_family=)`；OOD 世界的真值标签移到 meta |
| `sufficiency_gate.py` | OUT_OF_DOMAIN 只由冻结的协变量包络判定，包络检查覆盖 states、next_states 和 actions；**没有包络时失败关闭**；新增 `DomainEnvelope.from_contexts/symmetric_box`、`TOY_SLOW_D_VALID_LIMITS`（\|p\|≤8，\|v\|≤12，\|u\|≤12，是 D_permit 的真子集）；新增共享的 4a 判据 `nis_acceptance_bounds / is_covariance_inconsistent / strip_covariance_inconsistent_windows`；`verify_same_observation_different_future(domain_envelope=)` |
| `discovery.py` | F1：合并基改为逐上下文算子 `x ↦ x − B_c B_cᵀ x`，每块断言能量不增；`discover(nuisance_cov=)` 选择 GLS 或硬投影 |
| `promotion_gate.py` | F2：`e_lond_passed = E_pers ≥ 1/α_t`（去掉 `or sup_passed`），并纳入 `admitted`；F3：环境族只读 `ctx.env_family`，标签缺失、未登记或同一世界内冲突都拒绝，空族不再回落到全部世界；F4：FactTest 接线（`facttest_candidate_score`、`facttest_required_null_count`、冻结配方 `build_facttest_null_controls`），阈值无法达到时返回 `+inf`；C_clean 改用共享的 4a 判据，不再依赖某个门控带的包络；`PromotionDecision` 新增 5 个 facttest 字段 |
| `__init__.py` | 导出上述新接口 |
| `tests/v9/mechanism/test_cmfl_prototype.py` | r1 的 9 项测试适配 r2 接口：包络、显式族标签、零假设对照、T=45；D_permit 消融改为两段，先是落到 OOD，再在宽松包络下落到 SUFFICIENT 或 4a；新增「无包络时失败关闭」断言 |
| `tests/v9/mechanism/test_cmfl_r2_adversarial.py` | 新增 21 项：6 个场景在真包上成立，6 个变异体各被抓到（源码副本放在 `tmp_path`，并断言仓库树字节不变），另有泄漏、协变量判定 OOD、4a 判据一致、F1 能量/纯度/恢复、已知限制特征化、F3/F4 直接检查 |

**破坏性接口变化**：

- `ObservationContext(in_slow_domain=…)` 现在会报 TypeError。
- `MechanismSufficiencyGate(reg)` 不带包络时，越过 D_permit 的窗口一律判 OOD。
- 不传 `facttest_null_candidates` 时永不准入。
- `_compute_pooled_orthogonal_basis` 已删除。

因此 G8 的 r1 复核脚本（`reports/V9-G8/g8_checks.py`、`independent_gen.py`）不能原样跑在 r2 上；复核者需要在自己的目录里适配，不要改 G8 的交付文件。

## 3. 设计裁决（一级）

- **D_valid 包络**：玩具基准用一个与生成器规格一起声明的冻结盒子，不在基准窗口上拟合。它包住 NUMERICAL（y≤6.64，vy≤7.55）和 UNIDENTIFIABLE（uy≤11.31），排除 OOD（\|x\|≥9.5）。实际系统中的包络应来自 `calibrate_conformal_domain` 的证书（D∪C_clean 的协变量凸盒）。
- **FactTest 打分**：取 C_clean 上「加候选后 NIS 落在 MSG 4a/4b 双侧 χ² 接受区间」的窗口比例。分数越高越好，候选必须严格高于阈值，平分算拒绝。打分只用 C，T 留给 D3-1 和 D3-3。
- **零假设类配方（冻结）**：
  - 候选系数乘以 [0.5, 2] 带外的 29 个因子，其中 0 代表空律；
  - 其余每个先验有效的库项，在 D 上单项最小二乘拟合。
  第二类在候选是错的时可能恰好包含真律，这只会抬高阈值，也就是往拒绝那边偏。F4 里错误候选得分为 0，不论零假设类里有没有真律都过不了。
- **失败关闭清单**：
  - 无包络时判 OOD；
  - 零假设对照少于 29 个时拒绝；
  - 阈值无法达到时取 +inf；
  - 族标签缺失、未登记或冲突时拒绝；
  - 空族记为 E=1，并写进拒绝理由。

## 4. 证据（`metrics.json`，严格 JSON，无 Infinity/NaN）

| 项 | r2 结果 |
|---|---|
| pytest `tests/v9/mechanism` | **30 passed**（`evidence/pytest.txt`） |
| 本仓库 64 窗 8 路由，冻结包络、无标签 | 8 路由召回全部为 1.0 |
| 同上、不带包络 | ABSTAIN 8，OUT_OF_DOMAIN 56，其余 0（失败关闭） |
| G8 生成器 48 窗，去标签副本 + 冻结包络 | OOD 6/6，PARAMETRIC 5/6（与 r1 相同，G8 已记录），其余 6/6 |
| 逐块能量比最大值（G8 参数+结构 12 窗） | r1 合并投影 **17.87** → r2 硬投影 0.052，r2 GLS 0.054（都 ≤1） |
| G8 纯参数世界假发现 | 不投影 10/10，r2 硬投影 0/10，**r2 GLS 1/10** |
| G8 结构世界恢复（20 次） | 不投影 20/20，r2 硬投影 6/20（9 次错配），**r2 GLS 20/20** |
| F2：真机制、每族 4 个世界 | bootstrap 通过，E_pers=3.26 < 65.8 → **拒绝**（r1 会准入） |
| F3/F4：真机制、每族 15 个世界 | 准入；三族 e 值 309 / 504 / 497，互不相同；FactTest 0.85 > 0.20（k=32，n_null=32） |
| F4：coulomb 0.45 对 drag 0.55，120 个世界，seed 15 和 16 | 其余检查全部通过（E_pers 75.9 和 84.5）；**只被 FactTest 拒绝** |

坏控矩阵（`evidence/mutation_matrix.json`）：每个变异把一处 r1 行为写回源码副本。

| 变异 | 写回的 r1 行为 | 结果 |
|---|---|---|
| f2 | `or sup_passed` | 被抓到 |
| f3 | 按 id 子串猜族、不检查标签 | 被抓到 |
| f4 | `facttest_passed = True` | 被抓到 |
| envelope | 无包络时放行 | 被抓到 |
| f1 | 过投影 2.5×，能量断言触发 | 被抓到 |
| facttest_inf | 阈值取 `max+1e-6` | 被抓到 |

真包上 6 个场景全部成立，6 个变异体上各自的场景全部失败。

## 5. 已知限制（不阻塞，但不能被引用为能力）

1. **硬投影的共线代价**（ADR D2-7 没写到）。在 G8 设定下，二次阻力和本窗 c_lin 的灵敏度几乎共线，硬投影只保留 0.44% 的能量（测试 `test_hard_projection_absorbs_collinear_drag_known_limitation` 做了特征化）。GLS 缓解了这个问题，但它依赖 Σ_φ 的取值，而且纯度从 0/10 退到 1/10。Σ_φ 应由 ParamBelief 的协方差给出，不能事后调。
2. GLS 用各向同性近似 S_c≈σ_c²I，取对角均值。非各向同性的创新协方差还没有精确白化。
3. 这些数字只覆盖玩具设定：本仓库 W=20、dt=0.01，以及 G8 的 W=16、dt=0.015、σ=2.5e-3。「20/20」不是一般性能。
4. D3-6 的「可复现过滤」仍然只是比较两次完全相同的调用，几乎不可能失败。r2 没有改，留作后续。
5. FactTest 打分是窗口比例，粒度为 1/n_cal，平分算拒绝。零假设类的配方已冻结，但 `evaluate_and_promote` 接受调用方传入的任意列表，配方是否被照用要靠审计。
6. 玩具 D_valid 盒子是声明的常量，不是从数据拟合的。

## 6. 复跑

```
env -u PYTHONPATH .venv/bin/python -m pytest tests/v9/mechanism -q
env -u PYTHONPATH .venv/bin/python reports/V9-G7/r2/run_r2.py --out <你的目录>   # 默认写本目录；变异体在 TemporaryDirectory
```

`run_r2.py` 只读 `reports/V9-G8/independent_gen.py`，在内存里去掉 `in_slow_domain` 实参后再执行，并记录它的 SHA。运行前后，G8 交付文件的 SHA 已复核未变。
