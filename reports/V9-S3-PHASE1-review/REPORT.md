# S3 Phase 1 Non-Author Review Report

- **Task ID**: `ainerzero.V9.P208`
- **Title**: 【L2·gemini·非作者复核】S3 第一阶段各臂、统计、运行器与预登记一致性（零训练）
- **Reviewer**: `gemini-b8k2` (Tier 2 execution agent, non-author)
- **Author of Reviewed Code**: `claude` (Tier 1 lead coordinator)
- **Session Fingerprint**: `sess-ccce69f2e292`
- **Repository**: `/Users/mac/AinerWorkFlow/AinerZero`
- **Reviewed Files**:
  - `src/ainerzero/v9/experiments/s3/batching.py`
  - `src/ainerzero/v9/experiments/s3/arms_mlx.py`
  - `src/ainerzero/v9/experiments/s3/analysis.py`
  - `reports/V9-S3-PHASE1/run_phase1.py`
  - `reports/V9-S3-PROBES/run_probes.py`
  - `reports/V9-S3-DESIGN/PREREG-r1.json`
- **Governing Specification**: `reports/V9-S3-DESIGN/DESIGN-r2.md`
- **Conclusion**: **RECOMMEND_ACCEPT** (建议通过)
- **Mandatory Fixes**: 0 (必修项：无)

---

## 1. Executive Summary

This independent, non-author review evaluated the implementation of GridLab-S3 Phase 1 components authored by Tier 1 (`claude`), covering model arms (`arms_mlx.py`), batching pipeline (`batching.py`), statistical evaluation and gates (`analysis.py`), phase 1 runner (`run_phase1.py`), probe suite (`run_probes.py`), and preregistration metadata (`PREREG-r1.json`).

All audits were conducted strictly on CPU without invoking unauthorized GPU or modifying frozen code. Based on the 6 mandatory audit pillars:
1. **Truth Isolation**: Verified 100%. Tampering or corrupting ground-truth coordinates produced $\Delta = 0.0$ across all evaluation arms (A0, A1, A2, A3, N). Only diagnostic arm O consumes `oracle`.
2. **Information Leakage**: Verified. GRU causality is strictly forward ($\Delta_{past} = 0.0$ when future steps are perturbed). Candidate pools enforce a minimum 5-step lag ($r.t \le query\_t - 5$). Evaluation metadata (`swapped`, `bucket`) are never accessed in `forward` or `loss_fn`.
3. **Statistical Soundness**: Verified. `paired_bootstrap_delta` resamples whole episodes as clusters. When pooling across 3 seeds, episodes are grouped jointly into clusters. All gates fail-closed on empty or missing data.
4. **Preregistration Consistency & Safeguards**: Verified. 12/12 code file hashes and `design_sha256` in `PREREG-r1.json` match disk exactly. Steps, data scales, learning rates, seeds, and gates are 100% consistent. Dev usage limit ($\le 2$) and final read-once guard with exact approval string are verified.
5. **Mutation Audit (Bad Controls)**: 5 distinct mutations tested in an isolated workspace `/tmp/s3_phase1_review/workspace/`. All 5 mutations turned RED on targeted tests and reverted cleanly to 100% SHA256 match and GREEN status.
6. **Probes & Dev1 Complete Verification**: Frozen probes P-d through P-g in `reports/V9-S3-PROBES/probes.json` are verified. The `dev1.json` run finished at 2033.4s; all primary metrics, H1, H2, H3, and legality gates were independently recalculated from raw cells and verified to match bit-for-bit.

---

## 2. Truth Isolation Audit

| Path / Component | Input Source | Usage in Model Arms | Truth Leakage Audit Result |
|---|---|---|---|
| Observation tensor `obs` | `tour.py` -> `parse_student_step` | Ego 3x3 crop, heading, last action, bump | **Zero ground-truth coordinates/heading**. Verified by direct code audit. |
| Heuristic cues / Candidate pool | `store.py` (`est_pose`, `world_terrain`) | Distance, view similarity, time lag | **Zero truth dependency**. Odometry drift intact. |
| Arm A0 (No memory) | `mx.zeros_like(z_q)` | Memory projection | **Zero memory, zero truth**. |
| Arm A1 (GRU) | `obs` sequence | Autoregressive hidden state | **Zero truth**. |
| Arm A2 (Hand cues) | `b["top1"]` index | Retrieved past record observation | **Zero truth**. |
| Arm A3 (Learned scorer) | `b["candidates"]`, `cand_feats` | Scored candidate observations | **Zero truth**. |
| Arm N (Negative control) | `b["shuffled"]` | Permuted past record observation | **Zero truth**. |
| Arm O (Diagnostic upper bound) | `b["oracle"]` (`prev_visit_t`) | Ground-truth past visit observation | **Authorized diagnostic use only**. |

### Empirical Truth Corruption Test
In an independent Python verification run, all `truth` entries across episode steps were corrupted with arbitrary invalid values (`x: -999, y: -999, heading: 99, corrupt: True`).
- Max difference in output logits for A0, A1, A2, A3, N: **0.000000**
- Max difference in auxiliary loss for A3: **0.000000**
Truth isolation is complete and mathematically verified.

---

## 3. Information Leakage & Causality Audit

### 3.1 A1 GRU Temporal Causality
MLX's `nn.GRU` implementation was inspected: forward recurrence loop iterates strictly along sequence axis `idx in range(x.shape[-2])` from $t=0$ to $T-1$.
- **Empirical test**: Steps $50..359$ of the input tensor were corrupted with random noise.
  - Difference in hidden states $h[0..49]$: **0.000000**
  - Difference in hidden states $h[50..359]$: **0.563475**
  Strict forward causality is preserved; zero future leakage into past steps.

### 3.2 Candidate Pool Recency
In `batching.py:69` and `store.py:126`, `get_pool(query_t, gap=5)` enforces $r.t \le query\_t - 5$.
- Contract test `test_batching_records_precede_query` passed: all candidate indices satisfy $cand \le query\_t - 5$, and candidate time lag feature $(t - r.t)/T \ge 5/360 > 0$.

### 3.3 Metadata Channel Isolation
`b["swapped"]` and `b["bucket"]` were checked across `arms_mlx.py`:
- Neither key is referenced in `forward()` or `loss_fn()`.
- Both keys are used exclusively downstream in `analysis.py` / `summary()` for stratifying evaluation subsets.

---

## 4. Statistical Methodology Audit

### 4.1 Resampling Unit & Cluster Bootstrap
- `paired_bootstrap_delta(episode_ids, correct_a, correct_b)`:
  - Extracts unique `episode_ids` and groups event counts via `np.bincount`.
  - Resamples entire episodes with replacement (`resamples = 10000`, `seed = 20261109`).
  - Correctly treats the episode as the sampling unit, preserving within-trajectory correlation across return events.
- In `run_phase1.py:108-112`:
  - When concatenating across 3 random seeds (`s in SEEDS`), episode IDs are retained without seed-specific offsets (`0..n_ep-1` repeated 3 times).
  - Consequently, `np.bincount` aggregates all 3 seeds of each episode into the same cluster. The bootstrap resamples the episode across all 3 seeds jointly, preventing artificial shrinkage of variance due to repeated evaluations on the same world.

### 4.2 Fail-Closed Gate Behavior
- `accuracy()`: Raises `ValueError("no events selected...")` when `mask.sum() == 0`.
- `paired_bootstrap_delta()`: Raises `ValueError("no events...")` when `len(episode_ids) == 0`.
- `difference_gate()`: Requires `boot["delta"] >= min_delta and boot["ci_low"] > 0.0`.
- Legality checks fail on `NaN`: comparisons `NaN <= floor` or `NaN >= min` evaluate to `False` in Python. Empty or missing data cannot pass any gate.

---

## 5. Preregistration Consistency & Safeguards

### 5.1 Checksum Alignment (`PREREG-r1.json`)
All 12 files registered under `code_sha256` match disk hashes bit-for-bit:

| Path | Expected SHA256 (Prefix) | Actual SHA256 (Prefix) | Match |
|---|---|---|---|
| `src/ainerzero/v9/experiments/s3/__init__.py` | `fb0d4422` | `fb0d4422` | **YES** |
| `src/ainerzero/v9/experiments/s3/spec.py` | `9250427f` | `9250427f` | **YES** |
| `src/ainerzero/v9/experiments/s3/world.py` | `fc70d464` | `fc70d464` | **YES** |
| `src/ainerzero/v9/experiments/s3/content.py` | `66370cd4` | `66370cd4` | **YES** |
| `src/ainerzero/v9/experiments/s3/tour.py` | `949a5ec2` | `949a5ec2` | **YES** |
| `src/ainerzero/v9/experiments/s3/data.py` | `f8936e0f` | `f8936e0f` | **YES** |
| `src/ainerzero/v9/experiments/s3/store.py` | `8cc9429c` | `8cc9429c` | **YES** |
| `src/ainerzero/v9/experiments/s3/cues.py` | `de21ff49` | `de21ff49` | **YES** |
| `src/ainerzero/v9/experiments/s3/batching.py` | `b40540c7` | `b40540c7` | **YES** |
| `src/ainerzero/v9/experiments/s3/arms_mlx.py` | `3e3fcf85` | `3e3fcf85` | **YES** |
| `src/ainerzero/v9/experiments/s3/analysis.py` | `85e01b43` | `85e01b43` | **YES** |
| `reports/V9-S3-PHASE1/run_phase1.py` | `30744ac3` | `30744ac3` | **YES** |
| `reports/V9-S3-DESIGN/DESIGN-r2.md` | `7952e828` | `7952e828` | **YES** |

### 5.2 Protocol Consistency
- **Steps**: F1: 2000, F2: 1000, aux: 1500 (Matches `PREREG-r1.json` §steps and `run_phase1.py:24`).
- **Seeds**: `(1, 2, 3)` (Matches `PREREG-r1.json` §seeds and `run_phase1.py:20`).
- **Data Scale**: Train: 400 worlds $\times$ 4 episodes; Dev: 50 worlds $\times$ 2 episodes; Final: 100 worlds $\times$ 2 episodes.
- **Optimization**: Batch size 16, Adam lr 0.001, gradient clip norm 1.0.
- **Lambda**: $\lambda = 1.0$ (matching S3-C2 empirical fit on `s3p1-train`).

### 5.3 Runner Safeguards
- **Dev Limit Safeguard** (`run_phase1.py:72-75`): Tracks executions in `artifacts/v9/s3/phase1/dev_uses.json`. Refuses execution if `len(u) >= 2`, if `use_id` is missing, or if `use_id` was already recorded.
- **Final Read-Once Safeguard** (`run_phase1.py:76-80`): Refuses execution if `FINAL_READ_ONCE.json` exists. Requires exact approval line: `"S3-P1-FINAL-READ-APPROVED-TIER1-20261109"`.

---

## 6. Mutation Audit (Bad Controls in Isolated Workspace)

All mutations were executed in an isolated workspace `/tmp/s3_phase1_review/workspace/` with verified import resolution. Each mutation was asserted to turn RED on targeted pytest assertions, then reverted and verified against baseline SHA256 and re-evaluated GREEN.

| Mutation ID | Component & File | Injected Fault | Targeted Test | Mutated Exit Code | Reverted SHA256 | Reverted Exit Code |
|---|---|---|---|---|---|---|
| `mut1_a3_scorer_stopgrad_leak` | `arms_mlx.py` | Removed `stop_gradient` on $z_q, z_c$ in A3 `score()` | `test_scorer_loss_does_not_reach_encoder` | **1 (RED)** | **MATCH** | **0 (GREEN)** |
| `mut2_difference_gate_ci_high` | `analysis.py` | Changed `ci_low > 0` to `ci_high > 0` in `difference_gate` | `test_difference_gate_needs_both_size_and_interval` | **1 (RED)** | **MATCH** | **0 (GREEN)** |
| `mut3_empty_data_silent_pass` | `analysis.py` | Changed `accuracy` to return `1.0` on empty mask | `test_empty_data_raises_instead_of_passing` | **1 (RED)** | **MATCH** | **0 (GREEN)** |
| `mut4_candidate_recency_leak` | `batching.py` | Assigned `idx[i] = t` instead of `r.t` | `test_batching_records_precede_query` | **1 (RED)** | **MATCH** | **0 (GREEN)** |
| `mut5_a3_utility_target_stopgrad_leak` | `arms_mlx.py` | Removed `stop_gradient` on utility target `util` | `test_scorer_loss_does_not_reach_encoder` | **1 (RED)** | **MATCH** | **0 (GREEN)** |

Raw failure logs are archived in `reports/V9-S3-PHASE1-review/mutations/`.

---

## 7. Probe & Dev1 Results Audit

### 7.1 Probes Suite Audit (`reports/V9-S3-PROBES/probes.json`)
- **P-d** (Arm O upper bound): $1.0000 \ge 0.90$ — **PASS**
- **P-e** (Arm A0 floor): $0.0000 \le 0.1729$ — **PASS**
- **P-f** (Arm N negative control): $0.0554 \le 0.1729$ — **PASS**
- **P-g** (Step execution times): A0: 1.9 ms, A1: 194.6 ms, A2: 3.7 ms, A3: 6.8 ms — **PASS**
- Model parameter counts: Range [63,889, 65,074], max difference ratio $1.85\% \le 10\%$ — **PASS**

### 7.2 Dev1 Full Audit (`reports/V9-S3-PHASE1/dev1.json`)
The `dev1` run completed in 2033.4 seconds (33.9 minutes) across 100 evaluation episodes ($321 \times 3 = 963$ long-interval swapped primary events; 98 episodes containing primary events):

| Arm | Primary Accuracy (Swapped) | Unswapped Accuracy | F1 Drop after F2 Training | Observations |
|---|---|---|---|---|
| **A0** (No memory) | **0.0000 (0/963)** | 1.0000 | 0.0000 | Purely copies center cell. Floor $\le 0.1729$ holds. |
| **A1** (GRU) | **0.1090 (105/963)** | 0.9410 | 0.1090 | Fails on long-lag return events due to limited memory retention. |
| **A2** (Hand cues) | **0.8858 (853/963)** | 0.9000 | 0.7653 | Strong performance on F1. Suffers forgetting when encoder shifts to F2. |
| **A3** (Learned scorer) | **0.8339 (803/963)** | 0.9705 | 0.6968 | High recall, but learned scoring underperformed hand-tuned cue on dev1. |
| **O** (Oracle) | **1.0000 (963/963)** | 1.0000 | — | Perfect ceiling ($\ge 0.90$ holds). |
| **N** (Negative control) | **0.0010 (1/963)** | 0.9923 | — | Degrades to zero ($\le 0.1729$ holds). |

### 7.3 Hypothesis Gates Evaluation on Dev1
- **H1 (A2 - A1 $\ge 0.10$ and 95% CI lower bound $> 0$)**:
  - $\Delta = +0.7767$ (95% CI: $[+0.7333, +0.8177]$).
  - **Status: PASS**. External episodic store massively outperforms recurrent GRU on long-lag return memory.
- **H2 (A3 - A2 $\ge 0.05$ and 95% CI lower bound $> 0$)**:
  - $\Delta = -0.0519$ (95% CI: $[-0.0884, -0.0158]$).
  - **Status: FAIL**. Learned scorer did not surpass hand-tuned combination cue. (Honest empirical reporting as anticipated in DESIGN-r2 §9).
- **H3 (Old family performance drop $\le 0.05$)**:
  - A0: 0.0000 (PASS, trivial floor).
  - A1: 0.1090 (FAIL).
  - A2: 0.7653 (FAIL).
  - A3: 0.6968 (FAIL).
  - Catastrophic forgetting observed across all memory models when fine-tuned on disjoint token family F2 without memory consolidation.
- **Legality Gates**:
  - All 5 validity gates (`floor_A0`, `upper_O`, `negative_N`, `unswapped_A2`, `unswapped_A3`) evaluated to `True`. Experiment is fully valid.

Independent verification confirms that all summarized figures in `result` match the raw event calculations in `cells` bit-for-bit.

---

## 8. Final Recommendation

- **Verdict**: **RECOMMEND_ACCEPT** (建议通过)
- **Justification**:
  - Truth isolation and causal forwardness are verified mathematically and empirically.
  - Statistical clustering at the episode level correctly prevents artificial inflation of confidence.
  - Preregistration consistency is 100% verified across all 12 code files and protocol parameters.
  - All 5 bad controls in the isolated workspace turned RED and reverted GREEN cleanly.
  - Runner safeguards (dev usage limit $\le 2$, final read-once) are securely in place.
  - `dev1.json` results faithfully and transparently report empirical outcomes without tampering.
