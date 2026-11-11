# P214 证据

都在仓库根 `/Users/mac/AinerWorkFlow/AinerZero` 下运行。凡是导入 MLX 的都在共享锁内前台运行，包括门控测试、运行器测试、真实权重核对、门控与运行器变异、运行器补充测试。锁包装是 `reports/V9-S4-PHASE1/impl-review-r2-recheck/evidence/harness/hold_lock.py artifacts/locks/m0-worker.lock`，下面简写作 `<锁>`。锁忙（退出码 75）就稍后重试，不绕锁。

被审对象是 `c5387d8`。作者 11:12 起改了实盘工作树，11:43 提交为 `50f9edf`。所以凡是作为证据的运行，都用 `git archive c5387d8` 解出的副本：变异、基线、补充测试由脚本自己解出；独立核对用 `PYTHONPATH=<干净副本>/src`。干净副本的做法：

```
C=<任一新目录>; mkdir -p $C && git archive --format=tar c5387d8 src tests pyproject.toml reports/V9-S4-PHASE2 | tar -x -C $C
```

## 脚本与输出

**引文**
- `make_citations.sh` → `citations.txt`。报告里每处引文都是 `git show c5387d8:文件 | grep -n '' | sed -n 'X,Yp'` 的原始输出，与工作树无关。开头的 `git diff --stat c5387d8 HEAD` 记录的是生成时的 HEAD。
- 复跑：`sh reports/V9-S4-PHASE2/impl-review/evidence/make_citations.sh`

**变异**（`mutate_p214.py`）
- 复核者独立编写：19 个变异，外加 `unmutated_cpu`、`unmutated_gated`、`unmutated_runner` 三个基线。
- 每个变异解出一份全新的 `c5387d8` 副本，逐字替换前断言原文恰好 1 处，`PYTHONPATH` 指向副本的 src，并用 `find_spec` 确认被测模块来自副本。
- 判定：退出码 1 为 killed，0 为 SURVIVED，其他为 ERROR。
- 输出：
  - `mutants-cpu-batch1.txt`：M03–M07b
  - `mutants-cpu-batch2.txt`：X01–X05
  - `mutants-cpu-baseline.txt`：`unmutated_cpu`
  - `mutants-mlx-gated.txt`：M01、M02、X09
  - `mutants-mlx-runner-batchA.txt`：`unmutated_runner`、M08b
  - `mutants-mlx-runner-batchB.txt`：M08a、X06、X07、X08、`unmutated_gated`
- 复跑（每次换一个新的空目录）：
  - 纯 CPU 变异：`.venv/bin/python reports/V9-S4-PHASE2/impl-review/evidence/mutate_p214.py <空目录> M03_onestep_contacts_of_step_t ...`
  - MLX 变异：`.venv/bin/python <锁> .venv/bin/python reports/V9-S4-PHASE2/impl-review/evidence/mutate_p214.py [--jobs N] <空目录> <变异名...>`
  - `--jobs N`：线程池里并发 `subprocess.run`，不用 shell 的 `&`。
- 纯 CPU 的两批是加 `--jobs` 之前的版本跑的；副本、替换、pytest 命令都相同。

**补充测试**（证明存活变异不等价；`proposed_tests/test_p214_analysis_gaps.py`、`proposed_tests/test_p214_runner_gaps.py`，由 `run_proposed_tests.py` 复制进新副本运行）
- 输出：`proposed-tests-analysis.txt`（干净副本、X01–X04）、`proposed-tests-runner.txt`（干净副本、M08b、X06，锁内）。
- 复跑：
  - 分析组：`.venv/bin/python reports/V9-S4-PHASE2/impl-review/evidence/run_proposed_tests.py --jobs 5 <空目录> analysis clean X01_GC_uses_95_not_bonferroni X02_GD_D_bonferroni_m1 X03_GX_C_from_main_records X04_seed_average_seed1_only`
  - 运行器组：`.venv/bin/python <锁> .venv/bin/python reports/V9-S4-PHASE2/impl-review/evidence/run_proposed_tests.py --jobs 3 <空目录> runner clean M08b_weight_files_checked_after_marker_in_final X06_reserve_check_removed`

**独立核对**
- `indep_coverage_check.py` → `indep_coverage_check.txt`：一步覆盖率、重新出现覆盖率、对错、分配摘要的独立重算。纯 CPU，干净副本。
  - 复跑：`PYTHONPATH=$C/src .venv/bin/python reports/V9-S4-PHASE2/impl-review/evidence/indep_coverage_check.py 3`
- `indep_bonferroni_check.py` → `indep_bonferroni_check.txt`：每个门统计的 m、种子，以及 GC 的分位重算。纯 CPU，干净副本。
  - 复跑：`PYTHONPATH=$C/src:$C/tests/v9/experiments .venv/bin/python reports/V9-S4-PHASE2/impl-review/evidence/indep_bonferroni_check.py`
- `indep_gate_realweights.py` → `indep_gate_realweights.txt`：一期真实权重下，两种门与门控输出逐位核对。MLX，锁内，干净副本。
  - 复跑：`PYTHONPATH=$C/src .venv/bin/python <锁> .venv/bin/python reports/V9-S4-PHASE2/impl-review/evidence/indep_gate_realweights.py artifacts/v9/s4/phase1/final-final/weights`
- `*-live-1048.txt`、`*-live-1050.txt`、`*-live-1105.txt`：同样的核对在实盘工作树上的早先运行。那时工作树还等于 `c5387d8`。脚本当时还没有打印 `sources:` 那一行，结果与干净副本相同。

**实盘复跑（只作参照）**
- `tests-cpu-live.txt`：10:35，纯 CPU，94 项。开头记录了当时 `git diff --stat c5387d8 HEAD` 为空。
- `tests-mlx-live-gated.txt`：11:05，门控测试，8 项。
- `tests-mlx-live-runner.txt`：11:06–11:13。与作者改动时间重叠，**不计入**。

**其他**
- `weights-sha.txt`：盘上 6 个权重文件、`c5387d8` 运行器常量、一期 `final.json` 的三方比对。
- `worktree-changes-during-review.txt`：评审期间工作树的并行改动，以及后来的 `50f9edf` 提交。
- `artifacts-s4-before.txt`、`artifacts-s4-after.txt`、`artifacts-check.txt`、`stamp-start.txt`：开工（10:26:46 UTC）与收尾时实盘 `artifacts/v9/s4/` 的文件清单与比对。

变异与补充测试的副本放在会话临时目录 `$TMPDIR/.../scratchpad/{mut,mut-mlx,proposed,clean-c5387d8}` 下，不在仓库里。每个副本里留有完整的 pytest 输出：变异是 `pytest-output.txt`，补充测试是 `proposed-output.txt`。
