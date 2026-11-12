# P229 一级对抗验收（第 2 轮）：打回

验收人：一级 claude，2026-11-12。

## 方法
- 新建隔离副本：src、pyproject、conftest、`_hermetic_site`、三个 S5 测试文件，再加摸底版 `render.py`。PYTHONPATH 指向副本。
- 副本基线：43 项全过。
- 先重跑第 1 轮的 `mutations.py`（11 处），再跑新写的 `mutations-materialize.py`（5 处），两者都改源码。

## 结果

### 第 1 轮的 11 处：拦住 10 处
M2–M11 都被调用生产函数的测试拦住，这一轮的测试补得对。

M1（去掉 `episode` 里 `not allow_registered` 那道检查）这次漏网。原因是 r1 加了第二道检查（`world.py` 第 74 行，要求非空 `registered_run_id`）。现有测试只测「两样都没给」，第二道照样挡得住，所以测不出第一道被去掉。

### 物化脚本的 5 处：全部漏网

| 改动（`materialize.py`） | 结果 |
|---|---|
| P1 R2 用 `rendered_frames[14]` | 漏网 |
| P2 R3 用 `ep.steps[base_t + 15 + 7]` | 漏网 |
| P3 `disk_groups` 用 `rendered_frames[0]` | 漏网 |
| P4 段起点 `base_t = c * 15`（各段帧重叠） | 漏网 |
| P5 `ordering_pairs` 用 `rendered_frames[14]` | 漏网 |

`test_labels_precomputed_frames_parity` 只比较「`labels.*` 的预渲染路径」与「按需渲染路径」，用的帧是测试自己按正确下标渲染的。`materialize.py` 自己取第几帧、第几步，没有任何测试检查。物化是生成全部训练、评测数据的唯一入口，这里错了，整个实验的数据就错了。

## 必须改
1. **加物化端到端测试：**
   - 用 `s5test-*` 物化 1 个世界到临时目录；
   - 至少对第 0 段和第 15 段逐项断言：
     - `clip_YY.npy` 与 `world.student_clip(ep, c)` 逐字节相等；
     - `labels_YY.npz` 里的 `r1_logd`、`r1_sky`、`r2`、`r3` 与不传预渲染帧的 `labels.r1/r2/r3(ep, c)` 逐元素相等（nan 视为相等）；
     - `disk_groups_json`、`ordering_pairs_json` 与 `labels.disk_groups(ep, c)`、`labels.ordering_pairs(ep, c)` 相等。
   - 名字里带 pool 的测试分区，还要断言 `da2_YY.npy` 与 `world.da2_frames(ep, c)` 相等。
   - final-shift 两套外观的段，也要各自与 `student_clip(ep, c, appearance=SHIFT_BG/SHIFT_ALL)` 相等。这条用一个允许的测试命名空间模拟，不要真去生成 REGISTERED 分区：例如把外观选择抽成一个函数单独测，或在测试里 monkeypatch。
2. **补登记分区的测试：** 只给 `registered_run_id`、不给 `allow_registered=True`，也要抛 `PermissionError`。反过来，只给允许标志、不给 run id，也要抛。
3. 修完后用 `mutations.py` 和 `mutations-materialize.py` 两份脚本复验，16 处全部拦住，原始输出放进报告。

## 认可的部分
- 第 1 轮补的 7 条测试都调用生产函数，确实把各自的改动拦住了。
- 代码身份、CLI 拒绝 REGISTERED 分区、分区名与世界范围检查、每帧只渲染一次，这几项都按第 1 轮的要求做到了。
- 单个世界的物化从 8 s 降到 3.5 s。
