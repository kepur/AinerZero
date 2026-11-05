# P28 阶段1：申请一级冻结，尚未执行真实 MLX

依据：用户一次≤600秒授权；任务答复#425冻结arm1 N/A口径。
CPU最终脚本28项通过，0失败；完整无MLX导入干跑在 cpu-tests-pytest-r4/ 下。

脚本SHA256：6422764dd327313431bee19e8a2b73599dee119363e3b91c9f8c83f6ee5b1aea
测试SHA256：e5c60b4625d6e62e46a37e3b00fba6d7545ed355c5801075f33fced8822c0e0e
样本清单SHA256：6b27deb54c6fe8773d2ee0d52a8f56167806e339ee014d4ef231f733373fb026
清单内容摘要：b772eeb0806ff72ec16a5e8c52f6516d777c3000069435b8c90db66e2a389063

N=12，按scene_id/episode_id排序的前12个development episode，全是e3_identity；60帧/48转移。
arm2/3/4每项3次预热；正式forward48次、encode60次、probe_graph36次；warmup首条单独保留。
阶段1没有导入MLX，未创建优化器，未打开P1 RunStore/台账；未生成世界或训练数据。
按#429改用与P1相同的.venv/bin/python，env.txt记录mlx/mlx-metal/numpy元数据版本。
按#429补真实worker_lock的CPU正例与新目录/symlink/范围外写/SQLite/其他mkdir反例；旧未批准候选保留stage1-r1/。
预计墙钟未经实测，保守规划为完整600秒硬上限，不拿CPU假计时外推。

精确命令：

```text
python3 /Users/mac/AinerWorkFlow/AinerRelay/bin/relay exec ainerzero.V9.P28 --agent codex-0fqn -- /usr/bin/timeout -s KILL 600 /Users/mac/AinerWorkFlow/AinerZero/.venv/bin/python /Users/mac/AinerWorkFlow/AinerZero/reports/V9-B3-mlx-unitcost/measure_unit_cost.py --mode real --output /Users/mac/AinerWorkFlow/AinerZero/reports/V9-B3-mlx-unitcost/real-001 --freeze /Users/mac/AinerWorkFlow/AinerZero/reports/V9-B3-mlx-unitcost/freeze.json
```

资源实测：

```json
{
  "process_rss_gib": 0.07135009765625,
  "mlx_active_gib": 0.0,
  "mlx_peak_gib": 0.0,
  "mlx_available": false,
  "system_available_gib": 50.63189697265625,
  "swap_used_gib": 0.0,
  "swap_growth_gib": 0.0,
  "disk_free_gib": 3138.046527862549,
  "measured_at": 1792696548.5909681,
  "boot_epoch": 1792678827,
  "reasons": [],
  "swap_baseline_bytes": 0,
  "mlx_measurement": "not imported"
}
```

MLX尚未导入，allocator未测而非实测0；真实进程持既有共享锁后、建模前检查实际allocator，逐调用前后核资源，峰值逐次落盘。
模型不改变默认设备以保持产品路径；记录实际default_device和backend.name，不将backend字符串当设备实测。
已有失败保留：第一次CPU干跑因平台信息读取/dev/null被I/O守卫拒绝；r2/r3各22通过，未消费真实运行额度。
最终换算仅为三项核心耗时的median/p90算术区间；611序列调用已含1492个单步，不双乘。训练、checkpoint window batch、D前向及全端到端仍未知。
等待一级明确冻结通过及此处源码/argv绑定；freeze.json仅在收到答复后记录，不写APPROVED行。
