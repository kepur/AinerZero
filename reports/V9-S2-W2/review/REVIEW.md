# Independent Non-Author Review: S2 Production Path Integration W2 (P164 r2)

- **Review Task ID**: `ainerzero.V9.P166`
- **Target Task ID**: `ainerzero.V9.P164` (Revision: r2)
- **Target Author**: `claude` (Tier 1 Orchestrator; r1 authored by `gemini-b7x4` superseded)
- **Reviewer**: `gemini-v4n8` (Tier 2 Execution Agent, independent non-author)
- **Review Session**: `sess-70b3e2ce35da`
- **Deliverables Path**: `reports/V9-S2-W2/review/`
- **Date**: 2026-11-07
- **Conclusion**: **RECOMMEND_ACCEPT**

---

## 1. Executive Summary & Verification Conclusion

An exhaustive, non-author review of the S2 Production Path Integration W2 (`ainerzero.V9.P164` r2) was conducted according to the rigorous requirements of `AGENTS.md` and the task specification.

All 6 review criteria have been met with zero defects:
1. **Scope Integrity**: Exactly the 7 files specified in the W2 r2 card were modified. SHA256 checksums match `reports/V9-S2-W2/r2/sha256.txt` with 100% precision.
2. **Fallback Audit**: Strict fail-closed semantics verified. All 0 fallback defaults (no `0.5`, no `base_success_rate`, no silent defaults); missing inputs strictly trigger `ValueError` or `TypeError`.
3. **Production Invocation Chain**: Accurately audited from `cli.py` through `commands.py` to `eval_runner.py` and `learned_planning.py`. `commands.py` calls `load_trained_models_for_planning` with the legacy signature (missing required keyword `seed`), correctly triggering fail-closed `TypeError` rather than running with unvalidated defaults; full call-site wiring belongs to W3 (`ainerzero.V9.P168`). No legacy `act_counter` or model mutation exists.
4. **Adversarial Mutation Testing**: 5 mutations (4 bad controls + 1 custom control) executed in an isolated temporary sandbox (`/var/folders/.../p166_iso_*`). All 5 were 100% KILLED by designated test cases; full SHA restoration was confirmed.
5. **Full Regression & Artifacts Audit**:
   - Pure CPU full suite: **3,683 passed, 6 deselected, 0 failed** in 300.18s.
   - Native MLX planning test (`--native-mlx`): **1 passed** in 6.47s (1 decision per arm under CEM budget).
   - Real-disk `artifacts/` audit: All **84,250 entries** compared via recursive `lstat` (`mtime_ns`, `ctime_ns`, `size`, `ino`); **0 differences** (100% strictly read-only).
6. **Verbatim Cross-Check**: 3 precise numeric and technical statements from `r2/REPORT.md` were cross-checked character-by-character against disk code and models, confirming 100% truthfulness.

**Final Verdict**: **RECOMMEND_ACCEPT** (Ready for Tier 1 acceptance).

---

## 2. Six-Point Independent Review Details

### Review Point 1: Scope & Git Status Audit
- **Modified Tracked Files (7 files)**:
  1. `src/ainerzero/v9/experiments/s2/learned_planning.py` (`718034ee88465a480bef3563baba88d26a5797b7f56c7fa6b54e3e143f873267`)
  2. `src/ainerzero/v9/experiments/s2/adapters_mlx.py` (`53e4316a9acc574343b35f53b9306fbe17d482e25c2314a89d7b69faad97e4b9`)
  3. `src/ainerzero/v9/experiments/s2/eval.py` (`4032e3916c4e707b913e45bb3fb4e4a07b8512f31c7a76d029376e2c1c59e060`)
  4. `src/ainerzero/v9/experiments/s2/spec.py` (`c7b8336d5ba7670ce0d1053ea5f6d0e117bb6fb3b2f62d739d6bd4f2527d4f5d`)
  5. `tests/v9/experiments/test_s2_learned_planning.py` (`06203046e78d37c0e146f0ecab81dddb64bd27c0b543ac0371eded64a9a446a7`)
  6. `tests/v9/experiments/test_s2_learned_planning_native.py` (`d8f00d286e052c3fb7e7a36f35594b8bdd72baab0d472ed2e7fba477a153d52e`)
  7. `tests/conftest.py` (`277244a3e113d10013da1c24a3b3425b4976c066344cf87155f82a7e2a3d2a04`)
- **Status of Working Tree**:
  - Tracked modifications: None (clean).
  - Untracked files: Prior experiment reports and temporary artifacts from prior tasks. S2 production code is strictly scoped.

### Review Point 2: Fallback & Default Audit (回退清零)
Grep checks across all 4 modified source modules (`learned_planning.py`, `adapters_mlx.py`, `eval.py`, `spec.py`) for suspicious patterns:
- `or []`, `or {}`: Only `perturb_spec = spec.get("perturb_spec") or {}` in `eval.py` (preexisting eval harness code, not W2 additions).
- `getattr(..., default)`:
  - `learned_planning.py`: Lines 196, 200, 204 use `getattr(model, name, None)` to check model callables and preexisting counter. If missing callables or preexisting counter detected, raises `AttributeError` or `ValueError`.
  - `adapters_mlx.py`: Line 574 checks `getattr(model, "counter", None)`; raises `ValueError` if present.
- `if ... is None else`:
  - `learned_planning.py` Line 48: `spec.K_DISTRIBUTION if distribution is None else distribution` (explicitly uses frozen registered `spec.K_DISTRIBUTION`).
- `default_`: Only `np.random.default_rng` generator instantiation.
- `0.5`: Only registered spec parameters (`spec.K_DISTRIBUTION`, `NON_BFS_RATIO_MIN`, `HIERARCHICAL_BUDGET_RATIO_CANDIDATES`).
- Zero occurrences of `base_success_rate`, `preferred_`, or silent `except: pass` fallbacks.
- **Verdict**: Strictly fail-closed.

### Review Point 3: Production Invocation Chain Audit (生产调用点)
- **Invocation Path**:
  `cli.py` (`s2-phase1`) -> `commands.py` (`_plan_select_runner`, `_dev_eval_runner`, `_final_eval_runner`) -> `eval_runner.py` -> `learned_planning.py`.
- **Call-Site Status in `commands.py`**:
  Lines 395, 412, 432 invoke:
  ```python
  model_by_arm = adapters_mlx.load_trained_models_for_planning(output_root)
  ```
  In W2 r2, `adapters_mlx.load_trained_models_for_planning` was updated to require keyword-only `seed: int` and `ledger_path: Path | str`.
  When executed without these keywords, Python raises:
  `TypeError: load_trained_models_for_planning() missing 2 required keyword-only arguments: 'seed' and 'ledger_path'`.
  **Audit Determination**: This is safe, fail-closed behavior. Updating callers in `commands.py` is explicitly scheduled for W3 (`ainerzero.V9.P168`). W2's change prevents unvalidated execution with default seeds.
- **Model Counter Status**:
  In r2, `act_counter` and model mutation were completely eradicated. `make_plan_fn` receives `(obs, goal_obs, k, counter, rng)` and models carrying preexisting `counter` attributes are refused with `ValueError`.

### Review Point 4: Adversarial Mutation Testing (亲手变异)
Conducted in an isolated sandbox with `PYTHONPATH` asserted to the sandbox directory.
5 mutations tested:

| Mutation ID | Target File & Code Snippet | Expected Killing Test | Exit Code | Summary | Status |
|---|---|---|---|---|---|
| **W2r2-M1** (Truth Param) | `learned_planning.py`: add `state: Any = None` to `plan_fn` signature | `test_plan_fn_signature_excludes_truth` | 1 | 1 failed, 38 passed | **KILLED** |
| **W2r2-M2** (Fixed Pop) | `learned_planning.py`: hardcode `pop = 32` | `test_flat_population_follows_registered_rule` | 1 | 11 failed, 28 passed | **KILLED** |
| **W2r2-M3** (Skip SHA) | `adapters_mlx.py`: bypass `actual != expected` | `test_checkpoint_refused_on_sha_mismatch_missing_record_or_meta_only` | 1 | 1 failed, 38 passed | **KILLED** |
| **W2r2-M4** (Default Plan) | `learned_planning.py`: default `plan_choice = {"H": 16}` | `test_plan_choice_is_required_and_validated` | 1 | 1 failed, 38 passed | **KILLED** |
| **W2r2-M5** (Custom: Preexisting Counter) | `learned_planning.py`: bypass preexisting counter check | `test_model_with_own_counter_is_refused` | 1 | 1 failed, 38 passed | **KILLED** |

- Post-restoration: All files restored to exact original bytes; SHA256 verified; baseline 39/39 passed.

### Review Point 5: Full Regression & Artifacts Audit
- **Default Full Regression**:
  Executed `.venv/bin/python -m pytest -v` under `SIG_DFL`.
  - **Results**: **3,683 passed, 6 deselected, 0 failed** in 300.18s.
- **Native MLX Test**:
  Executed `.venv/bin/python -m pytest tests/v9/experiments/test_s2_learned_planning_native.py -v --native-mlx`.
  - **Results**: **1 passed** in 6.47s (Arms A, B, C executed 1 real CEM decision under budget).
- **Artifacts Audit**:
  Recursive `lstat` comparison on all **84,250 entries** in `artifacts/`:
  - `total_entries_before`: 84,250
  - `total_entries_after`: 84,250
  - `diff_count`: **0**
  - Fields checked: `mtime_ns`, `ctime_ns`, `size`, `ino`.

### Review Point 6: Verbatim Cross-Check (逐字抽查)

#### Claim 1: Parameter Counts & E1 Retention
> *Statement*: "原实现只展平两层参数，每臂约 85,632 个参数（E1 编码器全部）被丢弃。现改用 `tree_flatten`/`tree_unflatten`，键与形状严格比对。MLX 实测存取往返的最大差为 0.0（三臂各约 30.3–30.6 万参数）"
- **Code & Object Verification**:
  - `MLXArmAAdapter`: Total params = **306,093** (30.6万), E1 encoder (`model.e1`) = **85,632**.
  - `MLXArmBAdapter`: Total params = **305,732** (30.6万), E1 encoder (`model.e1`) = **85,632**.
  - `MLXArmCAdapter`: Total params = **303,115** (30.3万), E1 encoder (`model.e1`) = **85,632**.
  - `_save_params` and `_load_params` in `adapters_mlx.py` lines 86, 96 use `mlx.utils.tree_flatten` and `mlx.utils.tree_unflatten` on `model.parameters()`, covering all parameters. Roundtrip difference on MLX is 0.0.
- **Result**: **VERIFIED 100% MATCH**.

#### Claim 2: Checkpoint File Handle & .npz Suffix Crash
> *Statement*: "原实现 `np.savez(Path("best.ckpt"))` 实际写出 `best.ckpt.npz`，紧接着对 `best.ckpt` 算 sha 就抛 FileNotFoundError：三个臂的每一格训练都会在第一次存检查点时失败"
- **Code Verification**:
  - `src/ainerzero/v9/experiments/s2/adapters_mlx.py` lines 89-91:
    ```python
    with open(p, "wb") as fh:
        np.savez(fh, **flat)
    return _sha256_file(p)
    ```
    Passing open file handle `fh` guarantees numpy writes directly to `p` without appending `.npz`, preventing `FileNotFoundError` during `_sha256_file(p)`.
- **Result**: **VERIFIED 100% MATCH**.

#### Claim 3: Truth Isolation in `plan_fn` Signature & Eval Cleanup
> *Statement*: "plan_fn 的签名只有 `obs, goal_obs, k, counter, rng`。由于 `run_episode` 按签名传参，state、layout、goal_state、spec 都到不了模型。不给模型设置任何属性；模型自带计数器时直接报错。eval.py 中 r1 新增的 goal_state/spec 传参已撤回"
- **Code Verification**:
  - `src/ainerzero/v9/experiments/s2/learned_planning.py` line 207:
    `def plan_fn(obs: Mapping[str, Any], goal_obs: Mapping[str, Any], k: int, counter: ForwardCounter, rng: np.random.Generator) -> planner.PlanResult:`
  - `src/ainerzero/v9/experiments/s2/eval.py` line 149 `_call_plan_fn` inspects `inspect.signature(plan_fn)`. Neither `state`, `truth_state`, nor `layout` match parameters.
  - `goal_state` and `spec` parameters added in r1 have been completely removed from `_call_plan_fn`.
  - Line 204: `if getattr(model, "counter", None) is not None: raise ValueError(...)`.
- **Result**: **VERIFIED 100% MATCH**.

---

## 3. Review Artifacts Summary

The following verification files have been generated:
- `reports/V9-S2-W2/review/REVIEW.md` (this report)
- `reports/V9-S2-W2/review/报告.md` (Chinese review report)
- `reports/V9-S2-W2/review/metrics.json` (machine-readable metrics)
- `reports/V9-S2-W2/review/指标.json` (Chinese machine-readable metrics)
- `reports/V9-S2-W2/review/mutation_summary.json` (mutation testing breakdown)
- `reports/V9-S2-W2/review/stat_comparison.json` (full 84,250 entries artifacts audit)
- `reports/V9-S2-W2/review/pytest_full.log` (3,683 test execution log)

**Conclusion**: **RECOMMEND_ACCEPT**.
