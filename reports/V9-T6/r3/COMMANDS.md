# 原始命令

工作目录 `/Users/mac/AinerWorkFlow/AinerZero`。CPU渲染及验证不导入Torch/DA3/MLX。

生成：`python3 /Users/mac/AinerWorkFlow/AinerRelay/bin/relay exec ainerzero.V9.T6 --agent codex -- env OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1 /Users/mac/AinerWorkFlow/AinerZero/envs/teachers/.venv-t6/bin/python -I -B /Users/mac/AinerWorkFlow/AinerZero/envs/teachers/t6/prepare_calibration_fixtures.py --output /Users/mac/AinerWorkFlow/AinerZero/reports/V9-T6/r2-calib-fixtures`。合流日志 fixture-generation.log，exec rc0，elapsed1.434s，confirmed_empty=true。

验证：同 relay exec/env/Python 前缀，脚本 `/Users/mac/AinerWorkFlow/AinerZero/reports/V9-T6/r3/verify_fixture.py`。合流日志 fixture-verification.log，exec rc0，elapsed1.346s，confirmed_empty=true。脚本和唯一replay目录全部保留；verify的原始JSON为fixture-verification.json。

这两个Supervisor的wall_s/cap_s=null对应CPU执行，没有正式模型预算预留或模型运行。真实标定须另由T26/T27完成受控入口并登记，不使用当前脚本直接加载模型。
