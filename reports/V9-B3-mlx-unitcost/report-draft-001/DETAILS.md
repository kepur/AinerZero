# P28 测量明细

生成时间：2026-10-22T22:36:09+03:00

依据用户一次≤600秒授权与一级答复#425/#429/#431/#433。唯一真实命令已完成，没有重跑。

## 精确命令

```text
python3 /Users/mac/AinerWorkFlow/AinerRelay/bin/relay exec ainerzero.V9.P28 --agent codex-0fqn -- /usr/bin/timeout -s KILL 600 /Users/mac/AinerWorkFlow/AinerZero/.venv/bin/python /Users/mac/AinerWorkFlow/AinerZero/reports/V9-B3-mlx-unitcost/measure_unit_cost.py --mode real --output /Users/mac/AinerWorkFlow/AinerZero/reports/V9-B3-mlx-unitcost/real-001 --freeze /Users/mac/AinerWorkFlow/AinerZero/reports/V9-B3-mlx-unitcost/freeze.json
```

## 设备、同步与样本边界

实际设备 Device(gpu, 0)；产品后端名字是 mlx-cpu。没有更改默认设备；后端名字不作为设备证据。
每个单步都调用产品 forward_terms(burn_in=0, batch=1, 两帧切片)，并在计时结束前 eval(loss,parts)、物化pose/predictions、遍历原memory对象并eval其中MLX叶子。类型保持产品原样。
计时不含样本切片、资源采样与落盘；它们在计时区之外。另对每个样本完整调用一次产品MlxBackend.step_sequence，整段/转移数包含其原生切片/转换/循环开销，两种结果并列。
首3次预热丢弃，首条单独记录；first_call是首次调用总开销，不是独立测得的纯编译耗时。三臂在同一进程按arm2→arm3→arm4运行，后臂可能复用已热内核/缓存，首调用不代表独立冷启动。
N=12，固定development清单按scene_id/episode_id排序，全是e3_identity，60帧/48转移；不能代表其他family或训练后更复杂的memory。
arm1按#425只做既有stdlib身份校验，三项N/A，未加载D到MLX或用C0批做推理；身份检查会按既有校验器核验其钉扎文件字节。D真实前向的2秒截止仍未测。

## 单位耗时（毫秒；median / p90 / max，首调用另列）

| 臂 | 参数数 | 操作 | 正式样本 | median ms | p90 ms | max ms | 首调用 ms |
| --- | ---: | --- | ---: | ---: | ---: | ---: | ---: |
| arm2 | 207519 | forward | 48 | 2.577104 | 3.691629 | 9.593791 | 107.989417 |
| arm2 | 207519 | encode | 60 | 0.604458 | 0.689675 | 1.604958 | 1.066250 |
| arm2 | 207519 | probe_graph | 36 | 0.076688 | 0.102959 | 0.143208 | 0.148959 |
| arm2 | 207519 | step_sequence_per_transition | 12 | 2.434672 | 3.233208 | 3.322156 | 非单独冷启动 |
| arm3 | 159455 | forward | 48 | 2.495104 | 3.280488 | 11.604167 | 2.694084 |
| arm3 | 159455 | encode | 60 | 0.543313 | 0.576137 | 0.860708 | 0.667125 |
| arm3 | 159455 | probe_graph | 36 | 0.011812 | 0.017271 | 0.029000 | 0.030584 |
| arm3 | 159455 | step_sequence_per_transition | 12 | 1.839599 | 1.950196 | 3.789021 | 非单独冷启动 |
| arm4 | 274031 | forward | 48 | 2.513896 | 2.801779 | 3.175708 | 2.870583 |
| arm4 | 274031 | encode | 60 | 0.561959 | 0.679479 | 1.731708 | 0.380958 |
| arm4 | 274031 | probe_graph | 36 | 0.012605 | 0.016313 | 0.019792 | 0.031625 |
| arm4 | 274031 | step_sequence_per_transition | 12 | 2.567990 | 2.770156 | 3.408010 | 非单独冷启动 |

## 原生交叉核对差异

| 臂 | 原生median / 逐步median | 差值 ms |
| --- | ---: | ---: |
| arm2 | 0.944732 | -0.142432 |
| arm3 | 0.737283 | -0.655505 |
| arm4 | 1.021518 | 0.054094 |

arm3原生平均单步比逐步median低约26%；本次没有独立实验分离差距原因。完整原生调用节奏和逐步测量的封装/间隔不同，保留两种数据，不能把差距归因写成已验证事实。主换算仍按本卡逐步单位数据计算。

## 第8步：调用量乘单位耗时

P18 r4的已实测调用量按每臂每种子：1492单步forward、3500外部encode、800 probe_graph。611 step_sequence已包含1492步，平均1492/611步/调用，不再双乘611。
T(q)=1492×forward(q)+3500×encode(q)+800×probe_graph(q)，q分别取各项median、p90。三个种子与三臂的9次评测只是seed0初始结构的算术情景，不是实测9次训练后评测。

| 臂/种子 | median情景秒 | p90情景秒 | 占1200s范围 |
| --- | ---: | ---: | --- |
| arm2 / seed0投射 | 6.021992 | 8.004138 | 0.5018%–0.6670% |
| arm3 / seed0投射 | 5.633739 | 6.924785 | 0.4695%–0.5771% |
| arm4 / seed0投射 | 5.727673 | 6.571481 | 0.4773%–0.5476% |

9次核心评测情景合计：52.150212–64.501212s，占14400s的0.3622%–0.4479%。
这个区间不是置信区间或联合p90。尚不含175个独立window-forward_loss批、D的2秒前向、checkpoint加载、完整I/O/序列记账、训练时间与其他family/训练后memory规模；不能据此确认P1完整20分钟/4小时预算或写批准行。

## 资源、完整性与失败保留

```json
{
  "process_peak_rss_gib": 0.105224609375,
  "mlx_peak_gib": 0.0010523833334445953,
  "system_available_min_gib": 48.56829833984375,
  "same_boot_swap_growth_max_gib": 0.0,
  "boot_epoch": 1792678827,
  "samples": 995,
  "resource_refusals": []
}
```

参数SHA三臂前后完全相同，详见指标.json。全部23项冻结源码/数据绑定在运行后仍相同，样本清单逐字相同。495条原始计时region在real-001/*-raw.jsonl，逐次warmup/正式计时及交叉核对JSON全部保留。
CPU证据：初版21过/1败（/dev/null的环境元数据读取被拒绝），其余r2/r3各22过；修订锁边界r4为28过；最终r5为29过。旧候选stage1-r1/、stage1-r2/与所有失败日志均保留。
新目录、symlink锁父目录、范围外写与SQLite正反例；final路径/最终分区symlink守卫；优化器毒桩/禁调用；同步时钟与原生交叉流程，都在最终CPU测试中通过。
真实运行只执行一次，硬链接ONCE标记已存在，600s KILL未触发；真实exec原始退出码0、进程组确认空。未训练/反向/优化器/生成世界/final/保存checkpoint/写P1账本/批准/启动P1。

## 脚本直接生成的身份

生成命令：`.venv/bin/python reports/V9-B3-mlx-unitcost/generate_report.py`；完整文件级SHA256见SHA256SUMS.txt。

```text
b406eb96528e5e2bd40cc2c66004cc67ad7ab18c7fe718b7b9ac8acb5aa3d273  src/ainerzero/v9/experiments/s1/__init__.py
dfee798e41143857be811e7d9b1e70839f4c44c026890740da4a79d204cca62d  src/ainerzero/v9/experiments/s1/arms.py
9870af961551ef35357688ee52e35fa5bbd672863764458c85519c7404563492  src/ainerzero/v9/experiments/s1/awz_export.py
aca140c49245b4d3c13f00d84e306aacb57fba158f4e7ed6f62484295e3583b7  src/ainerzero/v9/experiments/s1/commands.py
3dee3291a99a26484acd2ec3a05cf23902bf9eb404c0a4916f361313025333c2  src/ainerzero/v9/experiments/s1/completion.py
c354fdd5bacf054f02cc601c9362c334d7a732e6ba4aa1c8b1a310aff13958fc  src/ainerzero/v9/experiments/s1/data.py
90e174c0a739a106d1e2137e14fc27bb4a95516513762a4a34deadd34738fb92  src/ainerzero/v9/experiments/s1/evaluation.py
5673103449ffcabc6666baf6e7e8a869a10d29c3a7ba5fc1a00553b04c816903  src/ainerzero/v9/experiments/s1/identity.py
577210abaacca6559e30bf1c901e906d774ab68ea9a97524424ddeb3aa9f58d4  src/ainerzero/v9/experiments/s1/metrics.py
a6cc1cbfabe16cb72f4c4e86758ed7359deadae7e5b648cb8b8b2fce7f184e6c  src/ainerzero/v9/experiments/s1/prereg.py
7171a83282abdfdb31892a3b24d82251b813f3623102148b9ddcc0710e5d578f  src/ainerzero/v9/experiments/s1/resource_gate.py
d5417b188126754e73e9b43c579235b062926b765e3be584759f8e5b1f0e60df  src/ainerzero/v9/experiments/s1/runtime.py
90c71f538fbb7d4b068f595333558988e73ea76bb0f903d0c8cf9a1bea3c00b8  src/ainerzero/v9/experiments/s1/smoke.py
d7cd6dc9d2fb7ac9fe2f1a466abba288298e3341346016344c58f033d007ea31  src/ainerzero/v9/experiments/s1/spec.py
f271ef609a23c4388338e2d6c95636c034c2a57e35469bd74a1869fd1425268d  src/ainerzero/v9/experiments/s1/worker.py
6e7bc8def57fdf26297f00a0a4d38a740f1ef5308a5a6f1ce8e41b8554417f82  src/ainerzero/learning/pilot_model.py
816531f32a50d52c29963aee403e26b900a421372a135f14f19f7fdcfd99c9fa  src/ainerzero/cli.py
9fb0fb3ea57fe82dbfe13de01dfa003ce78f0cff1e16aeb7761ff659da6ac9a8  src/ainerzero/runtime/checkpoints.py
bf5dad13687e1515a99cb1c487e5da6ddabffb22a97f96770c249883792666f9  reports/V9-B3-mlx-unitcost/measure_unit_cost.py
a385436c0c475cd2372eccce7d046f9a704e99f75c221ddee273af883666a913  reports/V9-B3-mlx-unitcost/test_measure_unit_cost.py
5cbd65225c84d50b50e65f31d79b8ddeb8ca5272a085d8f8c5cc1f116b4ed594  artifacts/v9/s1/datasets/8234f2f382281f355b662f05f0bb576d5efac4853f732ddf2e1cdfeee083ad26/dataset_manifest.json
b9420ef5e26a00a29f022f75390cf39ffd36fac1be8b723767fa71250d7a4aa7  artifacts/v9/s1/datasets/8234f2f382281f355b662f05f0bb576d5efac4853f732ddf2e1cdfeee083ad26/packets/development.jsonl
ef53e69af5d4c2b47dfe3196504d8b27c88d2819566ba0fcf4c0bf07850ce9b4  reports/V9-P18/r4/products/metrics.json
```
