# Task Report: ainerzero.V9.P90 (E1 Revision r2 Convergence Smoke & Formal Scale Extrapolation)

- **Task ID**: `ainerzero.V9.P90`
- **Agent ID**: `gemini-q8m2`
- **Date**: 2026-10-29
- **Host / Platform**: Darwin (macOS Apple Silicon), Python 3.12.4
- **Repository Root**: `/Users/mac/AinerWorkFlow/AinerZero`
- **Deliverables Directory**: `reports/V9-E1SMOKE4/gemini-q8m2/`
- **Status**: COMPLETED

---

## 1. Executive Summary

In task `ainerzero.V9.P90`, we executed the end-to-end convergence smoke validation of E1 Phase 2 following the acceptance of Architecture Ruling Revision r2 (P89, single-horizon evaluation window metrics). Data volume was scaled to **200 train, 40 development, 2 final sequences per family** (484 sequences total). Trainable Arms ②, ③, ⑥ were trained across families P and S with seed 42 at **2000, 8000, and 32000 steps** (18 training runs). All 26 evaluation runs were evaluated on the 40 dev episodes per family using the corrected single-horizon metrics.

Total benchmark wall-clock time was **2312.71 s (38.55 minutes)**, comfortably within the **50-minute (3000 s)** budget ceiling.

### Key Findings & Summary of Deliverables

1. **Recommended Step Count & Convergence Status**:
   - **Recommended Training Steps**: **32000 steps** (`suggest_32000_convergence_not_fully_confirmed`).
   - **Rationale**: 8000->32000 steps still yields > 5% improvement on at least one arm/family (or 8000 steps exceeds 5% error margin). Recommend 32000 steps, with convergence not fully confirmed.

2. **Sanity Check 1: Arm ① Resting Box Step 1 Error (< 1 cm)**:
   - **Result**: **0.254 cm (0.002541 m)** across 32 resting boxes.
   - **Requirement**: $< 1.0\,\text{cm}$ ($0.01\,\text{m}$) $\to$ **PASS**.

3. **Sanity Check 2: Arm ⑤ Subspace Identification Divergence & Distribution**:
   - **Result**: Arm ⑤ diverges from Arm ① on **16/80 episodes (20.0%)**.
   - **Subspace Dimension Distribution**: {'0': 112, '1': 16} (Total active bodies: 128).
   - **Requirement**: Differ on $\ge 1$ episode $\to$ **PASS**.

4. **Sanity Check 3: Arm ④ 10-Step Error Lower than Arm ①**:
   - **Family P**: Arm ④ (0.0530 m) vs Arm ① (0.0495 m) $\to$ **VIOLATION (FLAGGED)**.
   - **Family S**: Arm ④ (0.0495 m) vs Arm ① (0.0480 m) $\to$ **VIOLATION (FLAGGED)**.

5. **Checkpoint Hash Pairwise Distinctness**:
   - All 18 trained checkpoints across Arms ②, ③, ⑥ $\times$ Families P, S $\times$ 2000, 8000, 32000 steps possess **pairwise distinct SHA256 digests**. Zero collisions detected.

6. **B28 Velocity Injection Audit & Dev Collision Statistics**:
   - 100% of raw sequences contain `velocity_injection = 'kinematic_preroll_2f_v1'`.
   - 5 randomly audited moving bodies had relative velocity errors $< 5.0\%$.
   - Dev Collisions: Family P: 32/40 episodes collided (80.0%), 68 total events. Family S: 31/40 episodes collided (77.5%), 66 total events.

7. **Read-Once Sealing Gate**:
   - Call 1 succeeded; Call 2 was immediately refused with exit code 1 (`final_eval_already_read_once`).

8. **Formal Scale Extrapolation**:
   - Total extrapolated wall-clock runtime for formal E1 (2800 sequences, 18 training cells at 32000 steps, 26 dev eval cells at 200 episodes, final eval) is **6549.92\,\text{s} (1.82\,\text{hours})**, well within the 32.0-hour registered ceiling (30.18 h margin).

> **Protocol Note**: Development partition results are utilized solely for hyperparameter convergence assessment, model sanity verification, and formal budget planning. In accordance with protocol, no H-E1 hypothesis conclusions are drawn in this report.

---

## 2. Step-by-Step Execution Record

### Step 1: Verification (`--mode verify`)
- **CLI Command**: `python3 -m ainerzero.cli e1-phase2 --mode verify`
- **Output File**: `cli_outputs/01_verify.txt`
- **Exit Code**: 0
- **Duration**: 0.292 s
- **Document Hash**: `2e41342cc2eba72bddd945db3aabfbc92fc5df13eb90297df522d2c3ea668c01` verified against preregistration.

### Step 2: Dataset Generation (`--mode generate-data`)
- **CLI Command**: `python3 -m ainerzero.cli e1-phase2 --mode generate-data`
- **Counts Generated**: Family P (200 train, 40 dev, 2 final), Family S (200 train, 40 dev, 2 final). Total: 484 sequences.
- **Output File**: `cli_outputs/02_generate_data.txt`
- **Duration**: 490.799 s (1.014 s/sequence)

#### B28 Velocity Injection Audit
| Body Name | Trajectory File | $v_{0,h}$ (m/s) | $v_{2,h}$ (m/s) | Relative Error (%) | Ceiling | Status |
|---|---|---|---|---|---|---|
| `BouncingSphere` | `seq_train_bounce_collision_099.json` | 3.1139 | 3.1045 | 0.30% | < 5.0% | PASS |
| `RollingActor` | `seq_s_train_ramp_roll_155.json` | 0.2000 | 0.1952 | 2.41% | < 5.0% | PASS |
| `TableSlider` | `seq_s_train_table_slide_092.json` | 3.8967 | 3.8328 | 1.64% | < 5.0% | PASS |
| `TableSlider` | `seq_s_train_table_slide_127.json` | 3.3471 | 3.1874 | 4.77% | < 5.0% | PASS |
| `BouncingBox` | `seq_train_bounce_collision_044.json` | 3.4834 | 3.4607 | 0.65% | < 5.0% | PASS |

#### Dev Collision Statistics
| Family | Total Episodes | Colliding Episodes | Collision Ratio (%) | Total Collision Events | Mean Events / Episode |
|---|---|---|---|---|---|
| **P** | 40 | 32 | 80.0% | 68 | 1.70 |
| **S** | 40 | 31 | 77.5% | 66 | 1.65 |

### Step 3: Training Arms ②, ③, ⑥ across P, S at 2000, 8000, 32000 Steps (18 Runs)

| Cell Key | Family | Arm | Steps | Wall Time (s) | Active / Step (s) | Total / Step (s) | Initial Loss | Final Loss | Checkpoint SHA256 (prefix) |
|---|---|---|---|---|---|---|---|---|---|
| `arm2_P_step2000` | P | 2 | 2000 | 8.56 | 0.00070 | 0.00282 | 0.0216 | 0.000510 | `ccb0afb736a1...` |
| `arm3_P_step2000` | P | 3 | 2000 | 13.22 | 0.00072 | 0.00287 | 0.0222 | 0.003235 | `82b6ff168087...` |
| `arm6_P_step2000` | P | 6 | 2000 | 112.64 | 0.00080 | 0.00319 | 0.0117 | 0.000228 | `7b048c439b85...` |
| `arm2_S_step2000` | S | 2 | 2000 | 8.16 | 0.00066 | 0.00265 | 0.0151 | 0.013172 | `eec6abe6c34d...` |
| `arm3_S_step2000` | S | 3 | 2000 | 12.93 | 0.00070 | 0.00279 | 0.0132 | 0.031619 | `74876ead541d...` |
| `arm6_S_step2000` | S | 6 | 2000 | 117.99 | 0.00061 | 0.00244 | 0.0129 | 0.001570 | `1905101c2400...` |
| `arm2_P_step8000` | P | 2 | 8000 | 30.50 | 0.00066 | 0.00265 | 0.0216 | 0.001024 | `fa57290b58a3...` |
| `arm3_P_step8000` | P | 3 | 8000 | 34.78 | 0.00066 | 0.00263 | 0.0222 | 0.018889 | `48085e34cbf5...` |
| `arm6_P_step8000` | P | 6 | 8000 | 143.46 | 0.00069 | 0.00275 | 0.0117 | 0.000393 | `3ce3e73e8427...` |
| `arm2_S_step8000` | S | 2 | 8000 | 29.67 | 0.00064 | 0.00257 | 0.0151 | 0.006193 | `a0ebb6c0365d...` |
| `arm3_S_step8000` | S | 3 | 8000 | 34.55 | 0.00065 | 0.00261 | 0.0132 | 0.009146 | `5be11f8785dd...` |
| `arm6_S_step8000` | S | 6 | 8000 | 136.40 | 0.00064 | 0.00255 | 0.0129 | 0.001068 | `af4c298886d4...` |
| `arm2_P_step32000` | P | 2 | 32000 | 104.79 | 0.00064 | 0.00256 | 0.0216 | 0.000148 | `d3abb80c470d...` |
| `arm3_P_step32000` | P | 3 | 32000 | 118.49 | 0.00070 | 0.00280 | 0.0222 | 0.002873 | `cd8b8652e4b3...` |
| `arm6_P_step32000` | P | 6 | 32000 | 246.60 | 0.00075 | 0.00299 | 0.0117 | 0.000008 | `10a1bec69596...` |
| `arm2_S_step32000` | S | 2 | 32000 | 140.63 | 0.00077 | 0.00309 | 0.0151 | 0.001778 | `6e6c09bf6e8d...` |
| `arm3_S_step32000` | S | 3 | 32000 | 138.13 | 0.00073 | 0.00293 | 0.0132 | 0.006116 | `a5a74467951a...` |
| `arm6_S_step32000` | S | 6 | 32000 | 236.44 | 0.00074 | 0.00295 | 0.0129 | 0.000134 | `06b995c5b12e...` |

#### Checkpoint SHA Pairwise Distinctness Audit
| Step Tier | Family | Arm 2 SHA256 (prefix) | Arm 3 SHA256 (prefix) | Arm 6 SHA256 (prefix) | Pairwise Distinct? |
|---|---|---|---|---|---|
| 2000 steps | Family P | `ccb0afb736a1...` | `82b6ff168087...` | `7b048c439b85...` | **YES (PASS)** |
| 2000 steps | Family S | `eec6abe6c34d...` | `74876ead541d...` | `1905101c2400...` | **YES (PASS)** |
| 8000 steps | Family P | `fa57290b58a3...` | `48085e34cbf5...` | `3ce3e73e8427...` | **YES (PASS)** |
| 8000 steps | Family S | `a0ebb6c0365d...` | `5be11f8785dd...` | `af4c298886d4...` | **YES (PASS)** |
| 32000 steps | Family P | `d3abb80c470d...` | `cd8b8652e4b3...` | `10a1bec69596...` | **YES (PASS)** |
| 32000 steps | Family S | `6e6c09bf6e8d...` | `a5a74467951a...` | `06b995c5b12e...` | **YES (PASS)** |

### Step 4: Development Evaluation (26 Runs)

#### Baseline Non-Trainable Arms (①, ④, ⑤, ⑦)
| Arm | Family | $e_{10}$ (m) | $e_1$ (m) | $e_5$ (m) | $e_{30}$ (m) | Collision F1 | Energy Drift | Latency / step (s) | Wall (s) |
|---|---|---|---|---|---|---|---|---|---|
| Arm 1 | P | 0.0495 | 0.0005 | 0.0155 | 0.2715 | 0.3433 | 0.062634787656483 | 0.00054 | 1.03 |
| Arm 4 | P | 0.0530 | 0.0006 | 0.0141 | 0.2548 | 0.4267 | 0.05760173471995838 | 0.00058 | 1.10 |
| Arm 5 | P | 0.0435 | 0.0005 | 0.0139 | 0.2330 | 0.3433 | 0.062634787656483 | 0.00409 | 5.28 |
| Arm 7 | P | 0.0430 | 0.0005 | 0.0138 | 0.2364 | 0.3533 | 0.06731382277037896 | 0.00425 | 5.49 |
| Arm 1 | S | 0.0480 | 0.0005 | 0.0150 | 0.2459 | 0.3733 | 0.053710296337475344 | 0.00058 | 1.09 |
| Arm 4 | S | 0.0495 | 0.0006 | 0.0136 | 0.2308 | 0.4267 | 0.04627599067306624 | 0.00059 | 1.10 |
| Arm 5 | S | 0.0441 | 0.0005 | 0.0140 | 0.2240 | 0.3733 | 0.053710296337475344 | 0.00224 | 3.05 |
| Arm 7 | S | 0.0424 | 0.0005 | 0.0135 | 0.2221 | 0.3633 | 0.07005755031411207 | 0.00242 | 3.27 |

---

## 3. Convergence Table & Step Selection Rule (P90)

### (a) Convergence Table: Primary 10-Step Position Error ($e_{10}$)

| Family | Arm | 2000 Steps | 8000 Steps | 32000 Steps | $\Delta\%$ (2000 vs 32000) | $\Delta\%$ (8000 vs 32000) |
|---|---|---|---|---|---|---|
| **P** | **Arm 2** | 0.2708 m | 0.1202 m | **0.0675 m** | +301.2% | +78.2% |
| **P** | **Arm 3** | 0.1180 m | 0.0982 m | **0.1179 m** | +0.1% | -16.7% |
| **P** | **Arm 6** | 0.0800 m | 0.0769 m | **0.0818 m** | -2.1% | -6.0% |
| **S** | **Arm 2** | 0.1825 m | 0.0978 m | **0.0815 m** | +123.9% | +20.0% |
| **S** | **Arm 3** | 0.1651 m | 0.1857 m | **0.1442 m** | +14.5% | +28.8% |
| **S** | **Arm 6** | 0.0760 m | 0.0747 m | **0.0683 m** | +11.4% | +9.4% |

### (b) Horizon Errors ($e_1, e_5, e_{10}, e_{30}$) & Available Episodes Count

| Family | Arm | Step Tier | $e_1$ (m) [$N$] | $e_5$ (m) [$N$] | $e_{10}$ (m) [$N$] | $e_{30}$ (m) [$N$] |
|---|---|---|---|---|---|---|
| P | Arm 2 | 2000 steps | 0.0505 [40] | 0.1397 [40] | 0.2708 [40] | 0.7488 [32] |
| P | Arm 2 | 8000 steps | 0.0505 [40] | 0.0706 [40] | 0.1202 [40] | 0.2998 [32] |
| P | Arm 2 | 32000 steps | 0.0505 [40] | 0.0480 [40] | 0.0675 [40] | 0.2168 [32] |
| P | Arm 3 | 2000 steps | 0.0505 [40] | 0.0547 [40] | 0.1180 [40] | 0.4596 [32] |
| P | Arm 3 | 8000 steps | 0.0505 [40] | 0.0608 [40] | 0.0982 [40] | 0.3933 [32] |
| P | Arm 3 | 32000 steps | 0.0505 [40] | 0.0674 [40] | 0.1179 [40] | 0.4070 [32] |
| P | Arm 6 | 2000 steps | 0.0505 [40] | 0.0555 [40] | 0.0800 [40] | 0.2652 [32] |
| P | Arm 6 | 8000 steps | 0.0505 [40] | 0.0527 [40] | 0.0769 [40] | 0.2408 [32] |
| P | Arm 6 | 32000 steps | 0.0505 [40] | 0.0573 [40] | 0.0818 [40] | 0.2496 [32] |
| S | Arm 2 | 2000 steps | 0.0491 [40] | 0.1034 [40] | 0.1825 [40] | 0.3614 [32] |
| S | Arm 2 | 8000 steps | 0.0491 [40] | 0.0566 [40] | 0.0978 [40] | 0.1930 [32] |
| S | Arm 2 | 32000 steps | 0.0491 [40] | 0.0557 [40] | 0.0815 [40] | 0.2387 [32] |
| S | Arm 3 | 2000 steps | 0.0491 [40] | 0.0665 [40] | 0.1651 [40] | 0.3930 [32] |
| S | Arm 3 | 8000 steps | 0.0491 [40] | 0.0543 [40] | 0.1857 [40] | 0.3551 [32] |
| S | Arm 3 | 32000 steps | 0.0491 [40] | 0.0614 [40] | 0.1442 [40] | 0.7587 [32] |
| S | Arm 6 | 2000 steps | 0.0491 [40] | 0.0530 [40] | 0.0760 [40] | 0.2450 [32] |
| S | Arm 6 | 8000 steps | 0.0491 [40] | 0.0528 [40] | 0.0747 [40] | 0.2268 [32] |
| S | Arm 6 | 32000 steps | 0.0491 [40] | 0.0511 [40] | 0.0683 [40] | 0.2282 [32] |

### (c) Step Selection Rule Evaluation

- **Candidate Steps Evaluated**: `[2000, 8000, 32000]`
- **Step Tiers where all ②③⑥ are within $\le 5\%$ of 32000**: `[32000]`
- **Improvement from 8000 to 32000 Steps**:
  - `P_arm2`: +43.87%
  - `P_arm3`: -19.99%
  - `P_arm6`: -6.43%
  - `S_arm2`: +16.67%
  - `S_arm3`: +22.35%
  - `S_arm6`: +8.58%
- **Recommendation**: **32000 steps** (`suggest_32000_convergence_not_fully_confirmed`)
- **Rationale**: 8000->32000 steps still yields > 5% improvement on at least one arm/family (or 8000 steps exceeds 5% error margin). Recommend 32000 steps, with convergence not fully confirmed.

---

## 4. Residual Diagnostics (P90)

### (a) Single-Step Error ($e_1$) Comparison: Arm ③ vs Arm ①, and Arm ⑥ vs Arm ⑤

| Family | Comparison | Step Tier | Prior / Identification $e_1$ (m) | Residual Arm $e_1$ (m) | $\Delta$ (Residual - Baseline) | Residual Better? |
|---|---|---|---|---|---|---|
| P | Arm ③ vs ① | 2000 steps | 0.0005 | 0.0505 | +0.0499 | NO |
| P | Arm ③ vs ① | 8000 steps | 0.0005 | 0.0505 | +0.0499 | NO |
| P | Arm ③ vs ① | 32000 steps | 0.0005 | 0.0505 | +0.0499 | NO |
| P | Arm ⑥ vs ⑤ | 2000 steps | 0.0005 | 0.0505 | +0.0500 | NO |
| P | Arm ⑥ vs ⑤ | 8000 steps | 0.0005 | 0.0505 | +0.0500 | NO |
| P | Arm ⑥ vs ⑤ | 32000 steps | 0.0005 | 0.0505 | +0.0500 | NO |
| S | Arm ③ vs ① | 2000 steps | 0.0005 | 0.0491 | +0.0486 | NO |
| S | Arm ③ vs ① | 8000 steps | 0.0005 | 0.0491 | +0.0486 | NO |
| S | Arm ③ vs ① | 32000 steps | 0.0005 | 0.0491 | +0.0486 | NO |
| S | Arm ⑥ vs ⑤ | 2000 steps | 0.0005 | 0.0491 | +0.0486 | NO |
| S | Arm ⑥ vs ⑤ | 8000 steps | 0.0005 | 0.0491 | +0.0486 | NO |
| S | Arm ⑥ vs ⑤ | 32000 steps | 0.0005 | 0.0491 | +0.0486 | NO |

### (b) Error Growth across Horizons ($e_k$)

| Family | Arm Configuration | $e_1$ (m) | $e_5$ (m) | $e_{10}$ (m) | $e_{30}$ (m) | $e_{10} / e_1$ Ratio | $e_{30} / e_1$ Ratio |
|---|---|---|---|---|---|---|---|
| P | `arm_1_baseline` | 0.0005 | 0.0155 | 0.0495 | 0.2715 | 92.31x | 505.84x |
| P | `arm_2_step2000` | 0.0505 | 0.1397 | 0.2708 | 0.7488 | 5.37x | 14.84x |
| P | `arm_2_step32000` | 0.0505 | 0.0480 | 0.0675 | 0.2168 | 1.34x | 4.30x |
| P | `arm_2_step8000` | 0.0505 | 0.0706 | 0.1202 | 0.2998 | 2.38x | 5.94x |
| P | `arm_3_step2000` | 0.0505 | 0.0547 | 0.1180 | 0.4596 | 2.34x | 9.11x |
| P | `arm_3_step32000` | 0.0505 | 0.0674 | 0.1179 | 0.4070 | 2.34x | 8.07x |
| P | `arm_3_step8000` | 0.0505 | 0.0608 | 0.0982 | 0.3933 | 1.95x | 7.80x |
| P | `arm_4_baseline` | 0.0006 | 0.0141 | 0.0530 | 0.2548 | 93.80x | 451.14x |
| P | `arm_5_baseline` | 0.0005 | 0.0139 | 0.0435 | 0.2330 | 92.25x | 493.79x |
| P | `arm_6_step2000` | 0.0505 | 0.0555 | 0.0800 | 0.2652 | 1.59x | 5.26x |
| P | `arm_6_step32000` | 0.0505 | 0.0573 | 0.0818 | 0.2496 | 1.62x | 4.95x |
| P | `arm_6_step8000` | 0.0505 | 0.0527 | 0.0769 | 0.2408 | 1.52x | 4.77x |
| P | `arm_7_baseline` | 0.0005 | 0.0138 | 0.0430 | 0.2364 | 92.82x | 510.47x |
| S | `arm_1_baseline` | 0.0005 | 0.0150 | 0.0480 | 0.2459 | 88.01x | 450.88x |
| S | `arm_2_step2000` | 0.0491 | 0.1034 | 0.1825 | 0.3614 | 3.72x | 7.36x |
| S | `arm_2_step32000` | 0.0491 | 0.0557 | 0.0815 | 0.2387 | 1.66x | 4.86x |
| S | `arm_2_step8000` | 0.0491 | 0.0566 | 0.0978 | 0.1930 | 1.99x | 3.93x |
| S | `arm_3_step2000` | 0.0491 | 0.0665 | 0.1651 | 0.3930 | 3.36x | 8.00x |
| S | `arm_3_step32000` | 0.0491 | 0.0614 | 0.1442 | 0.7587 | 2.94x | 15.45x |
| S | `arm_3_step8000` | 0.0491 | 0.0543 | 0.1857 | 0.3551 | 3.78x | 7.23x |
| S | `arm_4_baseline` | 0.0006 | 0.0136 | 0.0495 | 0.2308 | 86.85x | 405.16x |
| S | `arm_5_baseline` | 0.0005 | 0.0140 | 0.0441 | 0.2240 | 87.64x | 445.03x |
| S | `arm_6_step2000` | 0.0491 | 0.0530 | 0.0760 | 0.2450 | 1.55x | 4.99x |
| S | `arm_6_step32000` | 0.0491 | 0.0511 | 0.0683 | 0.2282 | 1.39x | 4.65x |
| S | `arm_6_step8000` | 0.0491 | 0.0528 | 0.0747 | 0.2268 | 1.52x | 4.62x |
| S | `arm_7_baseline` | 0.0005 | 0.0135 | 0.0424 | 0.2221 | 91.62x | 480.18x |

---

## 5. Sanity Checks Audit

### Check 1: Arm ① Resting Box Physics Step 1 Error (< 1 cm)
- **Sample size**: 32 initially resting boxes audited across development partitions.
- **Mean Step 1 Position Error**: **0.254 cm (0.002541 m)**.
- **P82 Reference**: 0.905 m.
- **Threshold**: < 1.0 cm (0.01 m).
- **Status**: **PASS**.

### Check 2: Arm ⑤ Subspace Identification Divergence & Distribution
- **Total Development Episodes Compared**: 80
- **Episodes Differing (> 1e-6 m)**: **16 (20.0%)**.
- **Identified Subspace Dim Distribution**: `{'0': 112, '1': 16}` (across 128 active bodies).
- **Requirement**: Differ on $\ge 1$ episode $\to$ **PASS**.

### Check 3: Arm ④ 10-Step Error Lower than Arm ①
- **Family P**: Arm ④ (0.0530 m) vs Arm ① (0.0495 m) $\to$ **VIOLATION (FLAGGED)**.
- **Family S**: Arm ④ (0.0495 m) vs Arm ① (0.0480 m) $\to$ **VIOLATION (FLAGGED)**.
- **Status**: **VIOLATION (FLAGGED)**.

### Step 5: Final Evaluation Read-Once Verification
- **Call 1**: Exit Code 0, Duration 0.416 s (`status: completed`).
- **Call 2**: Exit Code 1, Duration 0.333 s (`status: refused`, read-once enforced).
- **Status**: **PASS**.

---

## 6. Formal Scale Budget Extrapolation vs `spec.BUDGET_CAPS`

Using empirical measurements from this smoke run and recommended training steps = **32000 steps**:
- **Data Generation**: 2800 sequences ($1000 \times 2$ train, $200 \times 2$ dev, $200 \times 2$ final).
- **Training**: 18 cells (3 arms $\times$ 2 families $\times$ 3 seeds) at 32000 steps each.
- **Dev Eval**: 26 cells at 200 episodes per cell ($5\times$ smoke count).
- **Final Eval**: 200 episodes ($100\times$ smoke count).

| Component | Empirical Unit Speed | Extrapolated Workload | Formal Wall Extrapolation | Budget Cap (`spec.BUDGET_CAPS`) | Margin (Headroom) | Exceeds Cap? |
|---|---|---|---|---|---|---|
| **Data Generation** | 1.0140 s/seq | 2800 sequences | **2839.34 s (47.32 min)** | 7200.0 s (120 min) | +4360.66 s (+60.6%) | **NO** |
| **Training (per cell)** | 164.18 s/cell | 32000 steps | **164.18 s** | 4800.0 s (80 min) | +4635.82 s | **NO** |
| **Training (18 cells)** | 164.18 s/cell | 18 cells | **2955.24 s (49.25 min)** | 86400.0 s (24.0 h) | +83444.76 s (+96.6%) | **NO** |
| **Dev Eval (Non-train cell)** | 0.0669 s/ep | 200 episodes | **13.38 s** | 300.0 s (5 min) | +286.62 s | **NO** |
| **Dev Eval (Train cell)** | 0.1685 s/ep | 200 episodes | **33.71 s** | 600.0 s (10 min) | +566.29 s | **NO** |
| **Dev Eval (Total 26 cells)** | — | 8 nontrain + 18 train | **713.71 s (11.90 min)** | 14400.0 s (4.0 h) | +13686.29 s (+95.0%) | **NO** |
| **Final Eval** | 0.2082 s/ep | 200 episodes | **41.64 s** | 1800.0 s (30 min) | +1758.36 s (+97.7%) | **NO** |
| **Phase Total Wall Clock** | — | Full Formal Run | **6549.92 s (1.82 hours)** | **115200.0 s (32.0 hours)** | **+108650.08 s (+94.3%)** | **NO** |

**Conclusion on Formal Budgets**: Extrapolated formal phase total runtime is **6549.92 s (1.82 hours)**, well within the registered 32.0-hour ceiling (+94.3% margin). All component caps are satisfied with large safety buffers.

---

## 7. Deliverables Index

All deliverables are stored in `reports/V9-E1SMOKE4/gemini-q8m2/`:
1. `REPORT.md`: This comprehensive report.
2. `timings.json`: Structured benchmark metrics, per-run timings, sanity check results, convergence tables, and formal budget extrapolations.
3. `metrics.json`: Raw development evaluation summaries and episode records.
4. `cli_outputs/`: Raw stdout and stderr logs for all 47 CLI executions.
5. `control_snapshot_*.sqlite3`: Snapshots of temporary SQLite control ledgers.
6. `SHA256SUMS.txt`: Checksums of all deliverables.
