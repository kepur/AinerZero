# S3-C2 Implementation and Evaluation Report

- **Task ID**: `ainerzero.V9.P206`
- **Title**: 【L2·gemini·代码】S3-C2 情景库、手工线索、多路候选池，实测探针 P-c/P-c2（纯 CPU，零训练）
- **Executor**: `gemini-k8d4` (Tier 2 execution agent)
- **Session Fingerprint**: `sess-c17b18b8ff80`
- **Repository**: `/Users/mac/AinerWorkFlow/AinerZero`
- **Status**: COMPLETED / RECOMMEND_ACCEPT

---

## 1. Executive Summary

This report delivers the complete implementation and empirical validation of GridLab-S3 Component 2 (S3-C2): Episodic Memory Store, Heuristic Cues, and Multi-Cue Candidate Pool, per `reports/V9-S3-DESIGN/DESIGN-r2.md` §3, §5, and Task P206 specification.

### Key Results Summary
- **Probe P-c (Hand-tuned combination precision@1)**:
  - Strict hit precision: **0.6734 (67.34%)** — squarely within the frozen target window $[0.50, 0.75]$ (**PASS**).
  - Loose hit precision: **0.7245 (72.45%)** — reported side-by-side.
  - Standalone pose cue: 0.2664; standalone view cue: 0.3485. Combination cue (+40.7% over pose, +32.5% over view) demonstrates successful multimodal disambiguation.
- **Probe P-c2 (Multi-cue candidate pool recall, $K \le 12$)**:
  - Strict hit recall: **0.8613 (86.13%)** — surpasses the frozen minimum $\ge 0.80$ (**PASS**).
  - Loose hit recall: **0.8814 (88.14%)** — reported side-by-side.
  - Average candidate pool size: **8.35 records** (Max: 12 records, strictly $\le 12$) (**PASS**).
- **Negative Control (Token Shuffling)**:
  - Token accuracy on long-interval return events drops to **0.0219 (2.19%)** ($\sim 1/45$, matching chance), proving memory readout relies on genuine association.
- **Contract Tests**:
  - 9 dedicated unit tests (`tests/v9/experiments/test_s3c2_*.py`) all pass.
  - All 20 S3 tests in repository pass in 11.90s.
  - Verified observation token alignment across 100 episodes, witnessing $>20$ swap transitions with 0 future leaks.
- **Mutation Audit**:
  - 5 mutations tested in isolated copy `/tmp/s3c2_mutations/workspace/`. All 5 turned RED on target tests and reverted cleanly to 100% SHA256 match and GREEN status.

---

## 2. File Scope & Implementation Details

All changes are strictly confined to authorized files:
- `src/ainerzero/v9/experiments/s3/store.py` (created)
- `src/ainerzero/v9/experiments/s3/cues.py` (created)
- `tests/v9/experiments/test_s3c2_*.py` (created, 8 test files)
- `reports/V9-S3-C2/` (deliverables)

### 2.1 Episodic Memory Store (`store.py`)
- **`EpisodicRecord`**: Immutable dataclass containing strictly student-visible fields:
  - `t: int`: Step index in episode.
  - `est_pose: tuple[float, float, int]`: Estimated odometry pose $(x_{est}, y_{est}, \theta_{est})$.
  - `world_terrain: np.ndarray`: $3 \times 3$ `int8` array of terrain classes rotated to world frame.
  - `observed_token: int`: Observed token at agent's center cell ($0$ if none).
  - *No ground truth coordinates, heading, or swap flags are read or stored.*
- **`align_ego_terrain_to_world`**: Uses `np.rot90(ego_terrain, k=(-heading) % 4)` to convert egocentric 3x3 terrain views to canonical world orientation.
- **`parse_student_step`**: Parses step dictionary into `EpisodicRecord`. Uses only `obs`, `est_pose`, and `t`. Never reads `step["truth"]`.
- **`EpisodicStore`**:
  - `add_step(step_data)`: Parses and records step.
  - `get_pool(query_t, gap=5)`: Returns records strictly satisfying $r.t \le query\_t - gap$.
  - `clear()`: Clears records at episode boundary; guarantees zero cross-episode state contamination.
  - `shuffle_tokens(rng)`: Permutes tokens across records while preserving poses, terrain, and timestamps for negative control.

### 2.2 Heuristic Cues & Multi-Cue Candidate Pool (`cues.py`)
- **Pose Distance**: Manhattan distance between query and candidate estimated poses: $|x_q - x_r| + |y_q - y_r|$.
- **View Similarity**: Fraction of matching cells between world-aligned 3x3 terrain grids. Strictly compares terrain classes (FREE, WALL, PILLAR, UNSEEN) and excludes token channels to prevent corruption across token swaps.
- **Combination Heuristic**:
  $$\text{score} = \text{view\_sim} \cdot \text{scale} \cdot \lambda - \text{pose\_dist} + 10^{-6} \cdot r.t$$
  where $\text{scale} = 49.0$ matches `tier1-probe/alias_probe.py:109`.
- **Multi-Cue Candidate Pool**:
  - Computes top 4 by pose distance, top 4 by view similarity, and top 4 by combined heuristic score.
  - Merges into a deduplicated candidate list ($K \le 12$) preserving combined score priority.
  - Strictly enforces recency exclusion ($r.t \le query\_t - 5$).
- **Strict vs Loose Hit Evaluation**:
  - `find_dwell_start(steps, prev_visit_t, target_cell)`: Traces backward from `prev_visit_t` to determine the start of the continuous dwell period at `target_cell`.
  - `check_hit(cand_t, event, steps)`:
    - `is_strict`: $cand\_t \in [t_{dwell\_start}, prev\_visit\_t]$ of the visit immediately preceding the departure.
    - `is_loose`: Candidate step visited `event["cell"]` at any time.

---

## 3. Parameter $\lambda$ Fitting on `s3p1-train`

Per protocol, $\lambda$ was grid-searched **strictly on `s3p1-train`** across $\{0.1, 0.25, 0.5, 1.0, 2.0\}$ using 50 worlds (264 long-interval return events, lag $\ge 80$).

| $\lambda$ Candidate | Strict Hits | Total Long Events | Strict Precision@1 | Loose Precision@1 |
|---|---|---|---|---|
| 0.10 | 119 | 264 | 0.4508 | 0.5189 |
| 0.25 | 145 | 264 | 0.5492 | 0.6174 |
| 0.50 | 151 | 264 | 0.5720 | 0.6364 |
| **1.00** | **156** | **264** | **0.5909** | **0.6477** |
| 2.00 | 156 | 264 | 0.5909 | 0.6477 |

**Fitted Best $\lambda$**: $\lambda = 1.00$ (achieving peak strict precision 0.5909 on training partition).

---

## 4. Empirical Evaluation on `s3p1-probe` ($\ge 100$ Worlds)

Evaluated across 100 worlds on `s3p1-probe` (100 episodes, 548 long-interval return events, lag $\ge 80$). Both strict hit and loose hit are reported; frozen gates evaluate strict hit.

### 4.1 Gate Evaluation

| Probe / Criterion | Strict Hit Metric | Loose Hit Metric | Frozen Gate Target | Gate Status |
|---|---|---|---|---|
| **Probe P-c** (Combination Cue Top-1) | **0.6734 (67.34%)** | 0.7245 (72.45%) | $[0.50, 0.75]$ | **PASS** |
| **Probe P-c2** (Candidate Pool Recall) | **0.8613 (86.13%)** | 0.8814 (88.14%) | $\ge 0.80$ | **PASS** |
| **Candidate Pool Size (Avg)** | 8.35 records | — | $\le 12$ | **PASS** |
| **Candidate Pool Size (Max)** | 12 records | — | $\le 12$ | **PASS** |

### 4.2 Standalone Cues vs Combination Cue
- Standalone Pose Precision (Strict): **0.2664 (26.64%)**
- Standalone View Precision (Strict): **0.3485 (34.85%)**
- Combined Cue Precision (Strict): **0.6734 (67.34%)**
- **Synergy Gain**: $+40.70\%$ over pose alone, $+32.49\%$ over view alone.

### 4.3 Negative Control (Token Shuffling)
- Invariant: Poses, terrain, and timestamps preserved; token assignments randomly permuted across episode steps.
- Token match accuracy on long-interval events: **0.0219 (2.19%)** ($\approx 1/45$), consistent with random selection from available tokens.

---

## 5. Unit Test Suite

The test suite consists of 8 dedicated test files covering all contract and safety requirements:

1. `tests/v9/experiments/test_s3c2_obs_alignment.py`:
   - Step-by-step verification that student observation token equals `content_state.get_token(cell, t)` for every visible cell in 3x3 ego view.
   - Tested across 100 episodes; witnessed $>20$ swap transitions; asserted zero future token leak.
2. `tests/v9/experiments/test_s3c2_rotation.py`:
   - Verified that for 60 walkable cells across all 4 headings, egocentric views rotate via `align_ego_terrain_to_world` to identical world-aligned views.
3. `tests/v9/experiments/test_s3c2_strict_hit.py`:
   - Validated `find_dwell_start` and discriminated strict hits, loose hits, and misses on synthetic trajectory with known dwell intervals.
4. `tests/v9/experiments/test_s3c2_no_truth_leak.py`:
   - Corrupted and deleted `step["truth"]`; verified that store recording, cue scoring, and candidate pools match clean runs bit-for-bit.
5. `tests/v9/experiments/test_s3c2_candidate_pool.py`:
   - Validated pool size bound $K \le 12$, deduplication, and strict recency exclusion ($r.t \le query\_t - 5$).
6. `tests/v9/experiments/test_s3c2_clear.py`:
   - Validated that `store.clear()` completely resets store with zero state leakage across episodes.
7. `tests/v9/experiments/test_s3c2_negative_control.py`:
   - Validated that `shuffle_tokens` preserves token multiset, poses, terrain, and timestamps while permuting token sequence.
8. `tests/v9/experiments/test_s3c2_pure_cpu.py`:
   - Spawns a fresh subprocess importing `store` and `cues`, asserting zero `mlx` modules in `sys.modules`.

**Pytest Run Result**: 9 passed in 5.01s. All 20 S3 tests passed in 11.90s.

---

## 6. Mutation Audit (Bad Controls in Isolated Copy)

Mutations were executed in an isolated workspace `/tmp/s3c2_mutations/workspace/` with verified import resolution to the isolated copy.

| Mutation ID | File & Change | Target Test | Mutated Result | Reverted SHA256 | Reverted Result |
|---|---|---|---|---|---|
| `mut1_future_token_leak` | `tour.py`: `get_token_map_at_step(t + 1)` | `test_s3c2_obs_alignment.py` | **RED** (exit code 1) | **MATCH** | **GREEN** (exit code 0) |
| `mut2_truth_leak` | `store.py`: `parse_student_step` reads `truth` | `test_s3c2_no_truth_leak.py` | **RED** (exit code 1) | **MATCH** | **GREEN** (exit code 0) |
| `mut3_wrong_rotation` | `store.py`: `k=(heading)%4` instead of `(-heading)%4` | `test_s3c2_rotation.py` | **RED** (exit code 1) | **MATCH** | **GREEN** (exit code 0) |
| `mut4_no_gap_exclusion` | `store.py`: `max_t = query_t` (gap=0) | `test_s3c2_candidate_pool.py` | **RED** (exit code 1) | **MATCH** | **GREEN** (exit code 0) |
| `mut5_strict_hit_degraded` | `cues.py`: `is_strict = is_loose` | `test_s3c2_strict_hit.py` | **RED** (exit code 1) | **MATCH** | **GREEN** (exit code 0) |

Full red logs are archived in `reports/V9-S3-C2/mutations/`.

---

## 7. Compliance Checklist

- [x] Pure CPU, zero MLX imports, zero GPU used.
- [x] Strictly adhered to allowed file scope.
- [x] S2 files untouched; C1 files untouched.
- [x] `artifacts/` path untouched; sqlite live ledger untouched.
- [x] $\lambda$ fitted ONLY on `s3p1-train`.
- [x] Probes evaluated on `s3p1-probe` ($\ge 100$ worlds).
- [x] Both strict hit and loose hit reported; gate evaluates strict hit.
- [x] Parameter v1 mandatory test `test_s3c2_obs_alignment.py` witnesses $>20$ swap transitions.
- [x] 5 mutations executed in isolated copy; all turned red and reverted cleanly.
- [x] Deliverables complete: `REPORT.md`, `metrics.json`, `报告.md`, `指标.json`, `SHA256SUMS.txt`.
