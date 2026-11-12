# P231：S5 实现 3，教师特征抽取脚本

执行者：一级 claude，2026-11-12。用户 11-07 授权一级可直接做二级活，代码仍须非作者复核。gemini-f8a3、gemini-f7b2 当时不在线，所以由一级领取。
依据：`reports/V9-S5-DESIGN/DESIGN-r1.md`（b021db0）§2、§3、§6、§7；预处理照摸底脚本 `tier1-explore/explore_s5a.py` 第 2、3 节。

## 文件
- `src/ainerzero/v9/experiments/s5/extract_teachers.py`（新）。
- `tests/v9/experiments/test_s5_extract.py`（新，13 项，纯 CPU，假教师）。
- 已有源码一行未改。P229、P230 的在制文件没碰；冒烟时只是调用了 P229 工作树里的 `materialize.py`。

## 接口
入口：
```
envs/teachers/.venv-t4/bin/python -I src/ainerzero/v9/experiments/s5/extract_teachers.py \
    --teacher {vjepa,da2} --in <物化分区目录> --out <输出目录> [--worlds a:b]
```

- **输入：**
  - `world_XXXX/clip_YY.npy`：uint8 `[16,224,224,3]`；
  - `world_XXXX/da2_YY.npy`：uint8 `[8,392,518,3]`；
  - `manifest.json`；
  - `labels_*` 文件忽略。
- **V-JEPA：**
  - 模型：`from_pretrained(VJEPA_DIR, img_size=(224,224), num_frames=16)`；
  - 输入：`((clip.transpose(3,0,1,2)/255) − ImageNet mean)/std`，加批次维，得 `[1,3,16,224,224]` float32；
  - 输出：`world_XXXX/clip_YY.vjepa.npy`，fp16 `[1568,1024]`。
- **DA2：**
  - 模型：Core ML，`CPU_AND_NE`；
  - 处理：要求恰好一个输出 → 取 float → 中间 392 列（63–454）→ `PIL.Image.BOX` 面积平均缩到 56×56 → fp16；
  - 输出：`world_XXXX/da2_YY.da2.npy`，`[8,56,56]`。
- **锁：** 非阻塞 flock `artifacts/locks/m0-worker.lock`。拿不到就退出码 75；拿到之前不建目录、不构建教师。
- **权重 SHA：** 运行时逐个核对，以 `reports/V9-S5-INVENTORY/REPORT.md` 第 1 节为准。
  - V-JEPA 四个文件：encoder、predictor、config、split_model；
  - DA2 两个文件：`weight.bin`、`model.mlmodel`。
- **续跑与防篡改：**
  - 每写完一段（先写 `.tmp`，再 `os.replace`），往 `progress.jsonl` 追加文件 SHA、耗时、时间戳；
  - 再跑时先核对账本里每个文件的 SHA，不符就报错；
  - 账本里有的跳过；目录里有、账本里没有的文件也报错。
- **拒绝登记分区：** 输入 manifest 的 `partition` 若是 `s5p1-final` 或 `s5p1-final-shift`，拒绝。
- **`manifest.json`：**
  - 输入清单 SHA、教师权重 SHA；
  - 代码身份：git HEAD，以及本文件的 SHA256；
  - mlx 或 coremltools 版本；
  - 预处理参数；
  - 写了几段、跳过几段，总耗时，每段中位耗时；
  - 账本 SHA。

## 测试与源码坏对照
- **测试：** `evidence/pytest_extract.txt`，13 passed。
- **坏对照：** `evidence/mutations.py`、`evidence/mutations-output.txt`。隔离副本里放 src、pyproject、conftest 和本测试文件，PYTHONPATH 指向副本，并先确认副本导入的是自己。副本基线 13 passed。

| 改动 | 结果 | 拦住它的测试 |
|---|---|---|
| B1 去掉 /255 | 拦住 | test_vjepa_preprocess_layout_and_values |
| B2 mean/std 通道顺序反了 | 拦住 | 同上 |
| B3 取左边 392 列 | 拦住 | test_da2_target_takes_middle_columns_and_area_averages |
| B4 去掉续跑跳过 | 拦住 | test_resume_after_crash_does_not_recompute |
| B5 去掉 SHA 篡改检查 | 拦住 | test_tampered_output_is_refused |
| B6 不拒绝登记分区 | 拦住 | test_registered_partitions_are_refused（两个分区） |
| B7 先构建教师后拿锁 | 拦住 | test_lock_busy_exits_75_and_writes_nothing |
| B8 面积平均改成双线性 | 拦住 | test_da2_target_takes_middle_columns_and_area_averages |
| B9 不检查输出 dtype | 拦住 | test_wrong_teacher_output_is_refused |
| B10 不检查账本外的残留文件 | 拦住 | test_stray_output_not_in_ledger_is_refused |

## 真教师冒烟（持锁，输出在暂存目录，不写 `artifacts/v9/`）
- **数据：** 用 P229 工作树里的 `materialize.py` 生成 `s5test-pool-smoke` 的世界 0：16 段，带 DA2 帧，耗时 10 s。
- **V-JEPA：** 16 段，总 3.7 s，每段中位 0.197 s（摸底 0.18 s）。特征 `[1568,1024]`，标准差 1.953（摸底 1.95），全部有限。
- **DA2：** 16 段 × 8 帧，总 3.5 s，每段中位 0.216 s，约 37 帧/秒（摸底 37.5）。
- **对齐核对：** DA2 目标按 4×4 平均到 14×14，与同帧（每管长第二帧）的 R1 真值对数深度做逐块 Spearman，16 段的中位数 −0.949、最差 −0.982。逆深度式输出与对数深度负相关，说明裁剪和缩放都没有错位。
- **续跑：** 重跑 V-JEPA，`written 0, skipped_already_done 16`。
- 运行日志和两份 manifest 在 `evidence/smoke-*`。

## 交复核时请重点看
- **DA2 的 Core ML 输出：** 按 PIL 图像取 float。T4 曾注明这个导出的深度方向是「远大近小」，但本轮在渲染画面上实测与真深度负相关，也就是逆深度式。这只影响解读，不影响尺度与平移不变损失。
- **面积平均的格点：** 392 → 56 是整 7 倍，BOX 刚好等于 7×7 块平均。
- **`ROOT = parents[5]`：** 写死了文件在仓库里的位置，挪动文件会出错。
