# 命令与证据边界

项目目录：`/Users/mac/AinerWorkFlow/AinerZero`。实际 CLI 前缀为 `python3 /Users/mac/AinerWorkFlow/AinerRelay/bin/relay exec ainerzero.V9.T6 --agent codex --`。

最终 CPU 套件：`env OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1 /Users/mac/AinerWorkFlow/AinerZero/envs/teachers/.venv-t6/bin/python -I -B /Users/mac/AinerWorkFlow/AinerZero/envs/teachers/t6/tests/test_r2.py`。stdout/stderr 合流至 `cpu-tests-2.log`；套件 rc0，exec leader rc0、confirmed_empty=true，监督 elapsed=3.162s。

最终源码变异：同环境前缀，`/Users/mac/AinerWorkFlow/AinerZero/envs/teachers/.venv-t6/bin/python -I -B /Users/mac/AinerWorkFlow/AinerZero/envs/teachers/t6/tests/run_mutations_r2.py`；合流日志 `source-controls-final.log`；rc0、整组空，监督 elapsed=1.838s。4 个 guard × 2 版本 × 3 方向，共 24 独立子进程。结果和每个精确 argv/rc 由对照目录记录；仅在隔离文件中变异，产品源码无变异。

归档/身份/拒绝 CLI：`/Users/mac/AinerWorkFlow/AinerZero/envs/teachers/.venv-t6/bin/python -I -B /Users/mac/AinerWorkFlow/AinerZero/reports/V9-T6/r2/collect_closeout.py`；合流 `closeout.log`；rc0、整组空，监督 elapsed=0.442s。子进程的真实 standalone run 为 rc3；没有将它改写为成功推理，父脚本仅断言它应拒绝。

另一次只读 inspect 使用 `/usr/bin/time -l` 经 relay exec，工具输出观察为 real=0.60s、user=0.47s、sys=0.10s、maximum resident set size=27,820,032B。此数值仅是配置/文件核对进程，**不是 DA3 加载或推理峰值**；当时无独立原 stdout 文件，因此最终机器证据采用 closeout 对四文件的再次核对，不借此声称模型基准。

`source-controls-2.log` 空文件保留；未将其算作通过，最终有效对照以 source-controls-final.log 和 d9lwoldd/results.json 为准。首次对照 p5w6s8vz 和首次 CPU 测试亦保留，其 SHA 不能替代最终源码身份。

`closeout-evidence.json` 的模型预算 0 是本轮零模型操作事实；Relay CPU supervisor 的 wall_s/cap_s=null，不构成模型运行授权。source_identity 使用 importlib.metadata 读取包版本，不 import torch/DA3/MLX；记录 cpu_imports 均 false。测试内显式 stubs/fakes 只验证边界路径，未执行真实网络。

源码真实 strict load、上游推理精度、真实相机输出尺度与姿态/深度准确度仍需冻结输入上的受控运行验证。配对工具保留 prealigned 声明及 evidence_ref，但不认证其真实性，不登记 covariance/NEES；T6 完整验收仍红/未完成。
