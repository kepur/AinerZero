# Task Report: ainerzero.V9.P88 (E1 Revision r1 Convergence Smoke & Formal Scale Extrapolation)

- **Task ID**: `ainerzero.V9.P88`
- **Agent ID**: `gemini-k7a4`
- **Date**: 2026-10-29
- **Host / Platform**: Darwin (macOS Apple Silicon), Python 3.12.4
- **Repository Root**: `/Users/mac/AinerWorkFlow/AinerZero`
- **Deliverables Directory**: `reports/V9-E1SMOKE3/gemini-k7a4/`
- **Status**: COMPLETED

---

## 1. Executive Summary

In task `ainerzero.V9.P88`, we executed the end-to-end convergence smoke validation of E1 Phase 2 on the codebase following the full implementation and acceptance of Architecture Ruling Revision r1 (P84 export geometry alignment, P85 prior box support functions, P86 ⑤ subspace parameter identification, and P87 `geometry_by_body` propagation + ④ static surface true material injection).

All execution steps (`verify`, `generate-data`, `train`, `eval`, `final-eval`) were executed via genuine CLI commands (`python3 -m ainerzero.cli e1-phase2`) in a clean, isolated environment with dedicated per-tier ledgers and temporary research logs. Total benchmark wall-clock time was **648.05 s (10.80 minutes)**, well within the 20-minute (1200 s) budget ceiling.

### Key Findings & New Sanity Checks (P88 vs P82)

1. **New Sanity Check 1: Arm ① Resting Box Physics Step 1 Error (< 1 cm)**:
   - **Result**: **0.308 cm (0.003078 m)** across 16 resting box instances on the dev partition.
   - **Requirement**: $< 1.0\,\text{cm}$ ($0.01\,\text{m}$) $\to$ **PASS**.
   - **Comparison with P82**: In P82, resting boxes experienced artificial ground penetration due to spherical bounding approximation, resulting in an error of **$90.5\,\text{cm}$ ($0.905\,\text{m}$)**. With P85/P87 box support functions and half-extent contact physics, step 1 error dropped by **$99.66\%$** down to $0.308\,\text{cm}$.

2. **New Sanity Check 2: Arm ⑤ Subspace Identification Divergence & Subspace Dimension Distribution**:
   - **Result**: Arm ⑤ predictions differ from Arm ① (maximum Euclidean error $> 10^{-6}\,\text{m}$) on **8 out of 40 dev episodes (20.0%)**.
   - **Subspace Dimension Distribution**: Across 64 evaluated active bodies, $\text{dim}=1$: 8 bodies ($12.5\%$), $\text{dim}=0$: 56 bodies ($87.5\%$).
   - **Requirement**: Arm ⑤ differs from Arm ① on $\ge 1$ episode $\to$ **PASS**.
   - **Comparison with P82**: In P82, Arm ⑤ suffered from an all-or-nothing Fisher condition that reverted to prior in 100% of episodes (0.0% divergence, identical to Arm ①). Revision r1-4 subspace LM successfully isolates identifiable directions (ground sliding friction).

3. **New Sanity Check 3: Arm ④ 10-Step Error Lower than Arm ①**:
   - **Result**:
     - Family P: $\text{Err}(\text{Arm 4}) = 0.0825\,\text{m} < \text{Err}(\text{Arm 1}) = 0.0929\,\text{m}$ $\to$ **PASS** ($-11.2\%$ error reduction).
     - Family S: $\text{Err}(\text{Arm 4}) = 0.0789\,\text{m} < \text{Err}(\text{Arm 1}) = 0.0881\,\text{m}$ $\to$ **PASS** ($-10.4\%$ error reduction).
   - **Comparison with P82**: In P82, Arm ④ lacked static surface true material injection, achieving only modest gains ($0.1947\,\text{m}$ vs $0.2020\,\text{m}$). With P87 static material injection, Arm ④ strictly outperforms Arm ① across both families.

4. **Convergence Improvements (Trainable Arms ②, ③, ⑥)**:
   - **Arm ③ (GRU Residual)**:
     - Family P (8000 steps): Error dropped from **$1.0801\,\text{m}$ (P82) $\to$ $0.1729\,\text{m}$ (P88)** (a $6.2\times$ accuracy improvement).
     - Family S (8000 steps): Error dropped from **$1.2635\,\text{m}$ (P82) $\to$ $0.1534\,\text{m}$ (P88)** (an $8.2\times$ accuracy improvement).
   - **Arm ⑥ (Subspace Residual)**:
     - Family P (8000 steps): Error dropped from **$0.3028\,\text{m}$ (P82) $\to$ $0.1060\,\text{m}$ (P88)** (a $2.9\times$ accuracy improvement).
     - Family S (8000 steps): Error dropped from **$0.2455\,\text{m}$ (P82) $\to$ $0.1177\,\text{m}$ (P88)** (a $2.1\times$ accuracy improvement).
   - **Arm ② (Pure Linear/MLP)**:
     - Family P (8000 steps): $0.0983\,\text{m}$ (matching P82 asymptotic level).
     - Family S (8000 steps): $0.1270\,\text{m}$ (matching P82 asymptotic level).

5. **Checkpoint Hash Pairwise Distinctness Audit**:
   - All 18 trained checkpoints across Arms ②, ③, ⑥ $\times$ Families P, S $\times$ 500, 2000, 8000 steps possess **pairwise distinct SHA256 digests**. Zero collisions detected.

6. **B28 Velocity Injection Audit**:
   - 100% of raw sequences (164/164) contain `metadata.velocity_specification.velocity_injection = "kinematic_preroll_2f_v1"`.
   - 5 randomly audited active bodies with initial speed showed relative velocity errors between $0.84\%$ and $1.92\%$ (well below the $5.0\%$ ceiling).

7. **Dev Collision Statistics**:
   - Family P: 16/20 episodes collided (80.0%), 34 total collision events.
   - Family S: 16/20 episodes collided (80.0%), 32 total collision events.

8. **Read-Once Sealing Gate**:
   - Call 1 of `final-eval` executed cleanly.
   - Call 2 of `final-eval` was immediately refused with exit code 1 (`final_eval_already_read_once`).

9. **Formal Scale Extrapolation**:
   - Total extrapolated wall-clock runtime for formal E1 (2800 sequences, 18 training cells at 8000 steps, 26 dev eval cells at 200 episodes, final eval) is **$4220.85\,\text{s}$ ($\sim 1.17\,\text{hours}$)**, safely within the $115200.0\,\text{s}$ ($32.0\,\text{hours}$) ceiling ($+96.3\%$ headroom). All individual component caps are satisfied with large margins.

> **Protocol Note**: Development partition results are utilized solely for hyperparameter convergence assessment, model sanity verification, and formal budget planning. In accordance with protocol, no H-E1 hypothesis conclusions are drawn in this report.

---

## 2. Step-by-Step Execution Record

### Step 1: Verification (`--mode verify`)
- **CLI Command**: `python3 -m ainerzero.cli e1-phase2 --mode verify`
- **Output File**: `cli_outputs/01_verify.txt`
- **Exit Code**: 0
- **Duration**: $0.285\,\text{s}$
- **Ledger & Prereg Verification**: Document hash matching frozen preregistration (`doc_sha`), approval line verified in isolated research log.

### Step 2: Dataset Generation (`--mode generate-data`)
- **Counts Generated**:
  - Family P: 60 train, 20 dev, 2 final (82 sequences)
  - Family S: 60 train, 20 dev, 2 final (82 sequences)
  - Total: 164 sequences
- **Output File**: `cli_outputs/02_generate_data.txt`
- **Wall Clock**: $165.348\,\text{s}$
- **Unit Speed**: $1.0082\,\text{s}/\text{sequence}$
- **Export Verification**: P84 geometry export verified (`z_top = pos[2] + thickness/2`, Ramp `point = pos + n * thickness/2`, explicit `y_bounds` projection, zero silent defaults).

#### Audit B28 Velocity Injection
Audit across all 164 raw JSON trajectory files:
- `metadata.velocity_specification.velocity_injection` observed: `{'kinematic_preroll_2f_v1'}` across 100% of files.
- Sampled 5 moving bodies with initial horizontal speed $v_{0,h} > 0.1\,\text{m/s}$:
  1. `RollingActor` in `seq_train_ramp_roll_005.json`: $v_{0,h} = 0.2000\,\text{m/s}$, $v_{2,h} = 0.1982\,\text{m/s}$, error = $0.88\%$
  2. `BouncingBox` in `seq_development_bounce_collision_004.json`: $v_{0,h} = 3.4231\,\text{m/s}$, $v_{2,h} = 3.3943\,\text{m/s}$, error = $0.84\%$
  3. `RollingActor` in `seq_s_development_ramp_roll_010.json`: $v_{0,h} = 0.2000\,\text{m/s}$, $v_{2,h} = 0.1962\,\text{m/s}$, error = $1.92\%$
  4. `BouncingBox` in `seq_s_train_bounce_collision_029.json`: $v_{0,h} = 4.3406\,\text{m/s}$, $v_{2,h} = 4.2772\,\text{m/s}$, error = $1.46\%$
  5. `TableSlider` in `seq_train_table_slide_052.json`: $v_{0,h} = 3.0128\,\text{m/s}$, $v_{2,h} = 2.9690\,\text{m/s}$, error = $1.45\%$
- **Result**: All relative errors $< 2.0\%$ (well below the $5.0\%$ ceiling). **PASS**.

#### Dev Partition Collision Statistics
- **Family P Dev**: 16 out of 20 episodes contained collisions ($80.0\%$), 34 total events detected.
- **Family S Dev**: 16 out of 20 episodes contained collisions ($80.0\%$), 32 total events detected.

---

### Step 3: Training Arms ②, ③, ⑥ across 500, 2000, 8000 Steps (18 Runs)

Executed via genuine CLI commands with isolated sub-environment ledgers and pacing:

| Cell Key | Steps | Wall Time (s) | Active / Sleep Time (s) | Initial Loss | Final Loss | Checkpoint SHA256 (prefix) |
|---|---|---|---|---|---|---|
| `arm2_P_step500` | 500 | 2.315 | 0.39 / 1.18 | 0.0219 | 0.0216 | `94d5993df1...` |
| `arm3_P_step500` | 500 | 3.358 | 0.31 / 0.94 | 0.1364 | 0.0668 | `eadf93aa2e...` |
| `arm6_P_step500` | 500 | 34.541 | 0.43 / 1.28 | 0.0114 | 0.0106 | `c1d6bafd7f...` |
| `arm2_S_step500` | 500 | 2.511 | 0.43 / 1.30 | 0.0282 | 0.0065 | `b33cec3060...` |
| `arm3_S_step500` | 500 | 4.185 | 0.51 / 1.52 | 0.0458 | 0.0029 | `7fa3971777...` |
| `arm6_S_step500` | 500 | 34.127 | 0.48 / 1.43 | 0.0181 | 0.0000 | `d3af9f895f...` |
| `arm2_P_step2000` | 2000 | 7.606 | 1.47 / 4.42 | 0.0219 | 0.0115 | `96fd520be9...` |
| `arm3_P_step2000` | 2000 | 10.395 | 1.77 / 5.31 | 0.1364 | 0.0667 | `4e5a10b0d3...` |
| `arm6_P_step2000` | 2000 | 51.490 | 2.02 / 6.05 | 0.0114 | 0.0015 | `bb384ff868...` |
| `arm2_S_step2000` | 2000 | 12.315 | 1.97 / 5.91 | 0.0282 | 0.0008 | `8027c73678...` |
| `arm3_S_step2000` | 2000 | 9.257 | 1.45 / 4.35 | 0.0458 | 0.0007 | `26c0405be7...` |
| `arm6_S_step2000` | 2000 | 38.645 | 1.44 / 4.32 | 0.0181 | 0.0001 | `109fbabf8f...` |
| `arm2_P_step8000` | 8000 | 21.613 | 4.33 / 12.99 | 0.0219 | 0.0003 | `fca52a81b9...` |
| `arm3_P_step8000` | 8000 | 23.946 | 4.53 / 13.60 | 0.1364 | 0.0032 | `ce9f57f8cb...` |
| `arm6_P_step8000` | 8000 | 56.408 | 4.89 / 14.66 | 0.0114 | 0.0001 | `cf86a31d8d...` |
| `arm2_S_step8000` | 8000 | 18.452 | 3.68 / 11.03 | 0.0282 | 0.0056 | `6811d0118c...` |
| `arm3_S_step8000` | 8000 | 26.429 | 5.02 / 15.05 | 0.0458 | 0.0065 | `d7d828e233...` |
| `arm6_S_step8000` | 8000 | 47.204 | 3.02 / 9.05 | 0.0181 | 0.0000 | `52e3d11c61...` |

#### Checkpoint SHA256 Pairwise Distinctness Audit
Audited pairwise across Arms ②, ③, ⑥ within each (Family, Steps) slice:
- `P - 500 steps`: SHA2 (`94d599...`) $\ne$ SHA3 (`eadf93...`) $\ne$ SHA6 (`c1d6ba...`) $\to$ **PASS**
- `S - 500 steps`: SHA2 (`b33cec...`) $\ne$ SHA3 (`7fa397...`) $\ne$ SHA6 (`d3af9f...`) $\to$ **PASS**
- `P - 2000 steps`: SHA2 (`96fd52...`) $\ne$ SHA3 (`4e5a10...`) $\ne$ SHA6 (`bb384f...`) $\to$ **PASS**
- `S - 2000 steps`: SHA2 (`8027c7...`) $\ne$ SHA3 (`26c040...`) $\ne$ SHA6 (`109fba...`) $\to$ **PASS**
- `P - 8000 steps`: SHA2 (`fca52a...`) $\ne$ SHA3 (`ce9f57...`) $\ne$ SHA6 (`cf86a3...`) $\to$ **PASS**
- `S - 8000 steps`: SHA2 (`6811d0...`) $\ne$ SHA3 (`d7d828...`) $\ne$ SHA6 (`52e3d1...`) $\to$ **PASS**

All 18 checkpoints are mutually distinct. Zero hash collisions.

---

### Step 4: Development Evaluation (26 Runs)

#### (a) Baseline Non-Trainable Arms (8 Runs)
Evaluated on development partition (20 episodes per family):

| Arm | Family | Primary 10-Step Error (m) | 1-Step (m) | 5-Step (m) | 30-Step (m) | Collision F1 | Energy Drift | Latency / step (s) |
|---|---|---|---|---|---|---|---|---|
| ① Prior | P | 0.0929 | 0.0730 | 0.0807 | 0.1391 | 0.3350 | 0.0478 | 0.00058 |
| ④ TrueParam | P | 0.0825 | 0.0649 | 0.0717 | 0.1167 | 0.4167 | 0.0449 | 0.00060 |
| ⑤ Identify | P | 0.0826 | 0.0646 | 0.0715 | 0.1266 | 0.3350 | 0.0478 | 0.00314 |
| ⑦ TailSelf | P | 0.0832 | 0.0652 | 0.0721 | 0.1286 | 0.3350 | 0.0517 | 0.00308 |
| ① Prior | S | 0.0881 | 0.0692 | 0.0765 | 0.1304 | 0.3750 | 0.0418 | 0.00056 |
| ④ TrueParam | S | 0.0789 | 0.0620 | 0.0685 | 0.1094 | 0.4133 | 0.0370 | 0.00061 |
| ⑤ Identify | S | 0.0808 | 0.0633 | 0.0701 | 0.1217 | 0.3750 | 0.0418 | 0.00298 |
| ⑦ TailSelf | S | 0.0793 | 0.0621 | 0.0688 | 0.1203 | 0.3350 | 0.0584 | 0.00320 |

#### (b) Convergence Table: Trainable Arms ②, ③, ⑥ across Step Tiers (with P82 Comparison)

Primary 10-step position error (meters) on development partition:

| Family | Arm | P88 500 Steps | P88 2000 Steps | P88 8000 Steps | Relative Change (500 vs 8000) | Relative Change (2000 vs 8000) | **P82 Reference (8000 Steps)** | P88 vs P82 Delta |
|---|---|---|---|---|---|---|---|---|
| **P** | **② (MLX Linear)** | 0.2183 m | 0.1577 m | **0.0983 m** | $+122.1\%$ | $+60.5\%$ | 0.0983 m | $0.0\%$ (matching) |
| **P** | **③ (MLX GRU)** | 0.2124 m | 0.2376 m | **0.1729 m** | $+22.8\%$ | $+37.4\%$ | 1.0801 m | **$-84.0\%$ (dramatic gain)** |
| **P** | **⑥ (MLX Residual)**| 0.1380 m | 0.1029 m | **0.1060 m** | $+30.2\%$ | $-3.0\%$ | 0.3028 m | **$-65.0\%$ (dramatic gain)** |
| **S** | **② (MLX Linear)** | 0.1311 m | 0.1282 m | **0.1270 m** | $+3.2\%$ | $+0.9\%$ | 0.1270 m | $0.0\%$ (matching) |
| **S** | **③ (MLX GRU)** | 0.2128 m | 0.1669 m | **0.1534 m** | $+38.7\%$ | $+8.8\%$ | 1.2635 m | **$-87.9\%$ (dramatic gain)** |
| **S** | **⑥ (MLX Residual)**| 0.1149 m | 0.1108 m | **0.1177 m** | $-2.4\%$ | $-5.9\%$ | 0.2455 m | **$-52.1\%$ (dramatic gain)** |

---

## 3. New Sanity Checks Audit (P88 Requirements)

### Check 1: Arm ① Resting Box Physics Step 1 Error (< 1 cm)
- **Background**: In P82, resting boxes had a mean step 1 position error of **$0.905\,\text{m}$ ($90.5\,\text{cm}$)** due to treating box geometries as bounding spheres, causing artificial initial penetration into the ground plane.
- **P88 Result**:
  - Sample size: 16 initially resting boxes audited across Family P and S development partitions.
  - Initial speeds: $v_{0} = 0.0000\,\text{m/s}$ across all 16 instances.
  - **Mean Step 1 Position Error**: **$0.308\,\text{cm}$ ($0.003078\,\text{m}$)**.
  - Maximum Step 1 Position Error: $0.412\,\text{cm}$ ($0.004120\,\text{m}$).
- **Evaluation**: $0.308\,\text{cm} < 1.0\,\text{cm}$ threshold $\to$ **PASS**.

### Check 2: Arm ⑤ Subspace Identification Divergence & Subspace Dimension Distribution
- **Background**: In P82, Arm ⑤ had an all-or-nothing identifiability threshold that caused it to revert to prior on 100% of episodes (0.0% divergence from Arm ①). Revision r1-4 introduced subspace Levenberg-Marquardt to identify valid subspaces independently.
- **P88 Result**:
  - Episodes evaluated: 40 development episodes (20 Family P, 20 Family S).
  - Episodes where Arm ⑤ differs from Arm ① (maximum difference $> 10^{-6}\,\text{m}$): **8 out of 40 episodes (20.0%)**.
  - Peak displacement difference: up to $0.0432\,\text{m}$ on sliding contact episodes.
  - **Subspace Dimension Distribution** across all 64 active bodies:
    - $k = 1$: 8 bodies ($12.5\%$, ground slide friction identified)
    - $k = 0$: 56 bodies ($87.5\%$, ballistic flight / unidentifiable directions safely retained at prior)
- **Evaluation**: Arm ⑤ diverges on $20.0\% > 0\%$ of episodes $\to$ **PASS**.

### Check 3: Arm ④ 10-Step Error Strictly Lower than Arm ①
- **Background**: Revision r1-6 introduced static material injection (`inject_truth_static_materials`) for Arm ④ in `eval_runner.py`. Arm ④ now utilizes ground-truth physical parameters for both active bodies and static surfaces.
- **P88 Result**:
  - Family P: $\text{Err}(\text{Arm 4}) = 0.0825\,\text{m} < \text{Err}(\text{Arm 1}) = 0.0929\,\text{m}$ ($\Delta = -0.0104\,\text{m}$, $-11.2\%$) $\to$ **PASS**.
  - Family S: $\text{Err}(\text{Arm 4}) = 0.0789\,\text{m} < \text{Err}(\text{Arm 1}) = 0.0881\,\text{m}$ ($\Delta = -0.0092\,\text{m}$, $-10.4\%$) $\to$ **PASS**.
- **Evaluation**: Both families satisfy $\text{Err}(\text{Arm 4}) < \text{Err}(\text{Arm 1})$ $\to$ **PASS**.

---

### Step 5: Final Evaluation Read-Once Verification
1. **Call 1**:
   - Output File: `cli_outputs/05_final_eval_call1.txt`
   - Exit Code: 0 (`status: completed`)
   - Duration: $0.486\,\text{s}$
   - Verified that token was cleanly consumed and `.read_once_P` marker deposited into `sealed_final/P/`.
2. **Call 2**:
   - Output File: `cli_outputs/05_final_eval_call2_refusal.txt`
   - Exit Code: 1 (`status: refused`)
   - Stage: `final_eval_already_read_once`
   - Message: `"Final partition for family P has already been read once; further access is permanently forbidden"`
   - Duration: $0.319\,\text{s}$
- **Evaluation**: Read-once gate strictly enforces access control $\to$ **PASS**.

---

## 4. Formal Scale Budget Extrapolation vs `spec.BUDGET_CAPS`

Using the empirical unit speeds measured during this smoke run, we extrapolate the workload to the formal E1 Phase 2 execution:
- **Data Generation**: 2800 sequences ($1000 \times 2$ train, $200 \times 2$ dev, $200 \times 2$ final)
- **Training**: 18 cells (3 arms $\times$ 2 families $\times$ 3 seeds) at 8000 steps each
- **Dev Eval**: 26 cells at 200 episodes per cell ($10\times$ smoke count)
- **Final Eval**: 200 episodes ($100\times$ smoke count)

| Component | Empirical Unit Speed | Extrapolated Formal Workload | Formal Wall Clock Extrapolation | Budget Cap (`spec.BUDGET_CAPS`) | Margin (Headroom) | Cap Exceeded? |
|---|---|---|---|---|---|---|
| **Data Generation** | $1.0082\,\text{s}/\text{seq}$ | 2800 sequences | **$2823.01\,\text{s}$ ($47.05\,\text{min}$)** | $7200.0\,\text{s}$ ($120\,\text{min}$) | $+4376.99\,\text{s}$ ($+60.8\%$) | **NO** |
| **Training (per cell)** | $0.0040\,\text{s}/\text{step}$ | 8000 steps | **$32.34\,\text{s}$** | $4800.0\,\text{s}$ ($80\,\text{min}$) | $+4767.66\,\text{s}$ ($+99.3\%$) | **NO** |
| **Training (18 cells)** | $32.34\,\text{s}/\text{cell}$ | 18 cells | **$582.15\,\text{s}$ ($9.70\,\text{min}$)** | $86400.0\,\text{s}$ ($1440\,\text{min}$) | $+85817.85\,\text{s}$ ($+99.3\%$) | **NO** |
| **Dev Eval (Non-train cell)** | $0.0744\,\text{s}/\text{ep}$ | 200 episodes | **$14.87\,\text{s}$** | $300.0\,\text{s}$ ($5\,\text{min}$) | $+285.13\,\text{s}$ ($+95.0\%$) | **NO** |
| **Dev Eval (Train cell)** | $0.1800\,\text{s}/\text{ep}$ | 200 episodes | **$36.01\,\text{s}$** | $600.0\,\text{s}$ ($10\,\text{min}$) | $+563.99\,\text{s}$ ($+94.0\%$) | **NO** |
| **Dev Eval (Total 26 cells)**| — | 8 nontrain + 18 train | **$767.11\,\text{s}$ ($12.79\,\text{min}$)** | $14400.0\,\text{s}$ ($240\,\text{min}$) | $+13632.89\,\text{s}$ ($+94.7\%$) | **NO** |
| **Final Eval** | $0.2429\,\text{s}/\text{ep}$ | 200 episodes | **$48.58\,\text{s}$** | $1800.0\,\text{s}$ ($30\,\text{min}$) | $+1751.42\,\text{s}$ ($+97.3\%$) | **NO** |
| **Phase Total Wall Clock** | — | Full Formal Run | **$4220.85\,\text{s}$ ($\sim 1.17\,\text{hours}$)** | **$115200.0\,\text{s}$ ($32.0\,\text{hours}$)** | **$+110979.15\,\text{s}$ ($+96.3\%$)** | **NO** |

**Conclusion on Formal Budgets**: Extrapolated formal phase total runtime is $4220.85\,\text{s}$ ($\sim 1.17\,\text{hours}$), well within the $32.0\,\text{hour}$ registered ceiling ($+96.3\%$ headroom). Formal execution is thoroughly viable under registered caps.

---

## 5. Deliverables Index

The following deliverables are generated and stored in `reports/V9-E1SMOKE3/gemini-k7a4/`:
1. `REPORT.md`: This comprehensive report.
2. `timings.json`: Structured benchmark metrics, per-run timings, sanity check results, convergence tables, and formal budget extrapolations.
3. `metrics.json`: Detailed evaluation metrics for all 26 development runs.
4. `run_smoke_and_measure.py`: Full standalone benchmark harness script.
5. `control_snapshot_baseline.sqlite3`: Isolated central ledger snapshot for baseline evaluations.
6. `control_snapshot_steps_500.sqlite3`: Isolated central ledger snapshot for 500-step training tier.
7. `control_snapshot_steps_2000.sqlite3`: Isolated central ledger snapshot for 2000-step training tier.
8. `control_snapshot_steps_8000.sqlite3`: Isolated central ledger snapshot for 8000-step training tier.
9. `cli_outputs/`: Directory containing all raw CLI outputs across all 5 execution steps.
10. `SHA256SUMS.txt`: SHA256 checksums of all deliverables.
