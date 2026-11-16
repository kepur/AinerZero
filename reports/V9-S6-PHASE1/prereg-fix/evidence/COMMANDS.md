# P261 实际命令与原始输出

cwd: /Users/mac/AinerWorkFlow/AinerZero（Relay 命令的 cwd 为 /Users/mac/AinerWorkFlow/AinerRelay）。

注册/领取/完整卡面：
- python3 bin/relay register --agent codex-s6preregfix-1115 --tier 2 --kind codex --skills code,math
- python3 bin/relay claim ainerzero.V9.P261 --agent codex-s6preregfix-1115
- python3 bin/relay prompt ainerzero.V9.P261 --agent codex-s6preregfix-1115

测试（CPU 驱动打印完整 pytest argv，内置 MLX import blocker）：
- `.venv-ainerzero/bin/python -B reports/V9-S6-PHASE1/prereg-fix/evidence/run_cpu.py /Users/mac/AinerWorkFlow/AinerZero` → tests-first.log（首次；保留失败）、tests-r2.log（77通过）、tests-final.log（80通过）、tests-delivery.log（最终版）。
- `.venv-ainerzero/bin/python -B reports/V9-S6-PHASE1/prereg-fix/evidence/mutate.py` → mutations.log / mutations/results.json。
- `.venv-ainerzero/bin/python -B reports/V9-S6-PHASE1/prereg-fix/evidence/mutate.py mutations-delivery` → mutations-delivery.log / mutations-delivery/results.json（最终源码）。
- `.venv-ainerzero/bin/ruff check --no-cache reports/V9-S6-PHASE1/make_prereg.py reports/V9-S6-PHASE1/prereg_evidence.py tests/v9/experiments/test_s6_prereg.py` → lint.log。
- `.venv-ainerzero/bin/python -B reports/V9-S6-PHASE1/prereg-fix/evidence/check_live.py` → live-state.log（只读入口检查，无正式输出）。

CPU fixture 在 pytest 的临时目录生成；每个测试使用独立复制的合成仓库。为测试真实Git提交身份检查，fixture仅在临时合成仓库中执行 git init/add/commit，绝不在工作仓库暂存或提交。原始变异源码/日志保存在 mutations*/M*/snapshot 与 pytest.log；可用 mutate.py + 新输出目录名复现，不覆盖旧证据。
