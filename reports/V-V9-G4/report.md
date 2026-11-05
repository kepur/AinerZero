# ainerzero.V9.G4 独立复核报告：解析规范化算子

角色：executor（二级执行层）· 负责人：`composer-m7k2` · 时间：2026-10-20（+03）
任务状态：reported · 实验状态：completed（**纯 CPU、只读复核**）· 类型：verify
任务依据：`ainerzero.V9.G4`（复核 `ainerzero.V9.G3`，作者 `deepseek-flash-9m2x`；本报告作者非 G3 作者）；参数 v0（`{}`）；文件范围 `reports/V-V9-G4/`。
被验交付：`src/ainerzero/v9/geometry/canonical.py`、`tests/v9/geometry/test_canonical.py`、`reports/V9-G3/r1-deepseek-flash-20261020/`
修改文件：仅新增 `reports/V-V9-G4/`；**未改被验源码/测试/作者报告**。
结论：**建议验收**（独立 8/8 不利反例通过，误差传播推导与实测一致，git HEAD 上 G1 六文件相对登记未变）。不 accept 自己。

---

## 0. 摘要（30 行内）

1. 复核对象：G3 `canonicalize`/`decanonicalize`（点/向量/位姿/平面栅格）及右扰动一阶误差传播；作者 `deepseek-flash-9m2x`，本会话未交付 G3，无自审冲突。
2. 独立证据：自写 8 个不利反例（每例含“故意改坏必须变红”对照），全部 PASS 且 poison 被捕获；作者 pytest 仅作对照复跑（57 passed），不当唯一证据。
3. C1 近 π 旋转等变：θ∈{±π, ±(π−1e-12), ±(π−1e-8)}×平移 {0,±1e-12,0.7}，点/向量等变误差 ≤1.33e-15，往返 ≤4.4e-16；反向 g 毒化等变残差 0.73。
4. C2 反射混入：det=−1 矩阵被 `SE2.validate` / `left_compose` 拒绝；在规范点上强制反射残差 2.0。
5. C3 非刚体：均匀缩放与剪切全部拒绝（validate + left_compose）。
6. C4 栅格越界：信念平移到 (20,−15) 时 valid 比例 0、fill 比例 1；近信念内部单元仍有效。
7. C5 非正定协方差：不定/奇异/非对称/NaN/Inf 均拒；合法 SPD 可 `inject_pose_error`。
8. C6 恒等与高度：往返 2.2e-16；智能体水平原点处点规范为 `[0,0,1.25]`；roll/pitch 信念拒；用完整 SE(3) 均值逆的毒化使 z→0.88。
9. C7 误差传播：独立 Jacobian `δ=−[ρx,ρy]−θ Jp` 与模块预测逐位差 0；有限差分 Jacobian 误差 5.7e-8；MC N=8000 相对 Frobenius 点 1.08%、向量 1.12%（≤5%）；丢偏航列毒化相对误差 0.91。
10. C8 图像/RGB `(8,8,3)` 拒；若展平为点集会被错误接受（毒化对照成立）。
11. G1 SHA：`git HEAD` 六文件与 `reports/V9-G1/.../source-sha256.json` **逐字节一致** → G3 未改已提交的 G1。当前工作树 `belief.py`/`gravity.py`/`pose_graph.py` 有未提交漂移（F1/F2 容差修补痕迹，属他人 WIP，本卡未触碰）；G3 新源码四文件 SHA 与作者登记一致。
12. 作者变异脚本在当前 WT 上因 G1 漂移会断言失败（`run_checks.py`），属工作树状态，不否定 G3 交付时证据；独立反例不依赖该脚本。
13. 能力口径：纯 CPU 数学算子性质；不构成训练/视觉/世界模型能力通过。不训练、不导入 MLX/torch、不下载、不提交推送。

## 1. 范围与不做什么

- 做：自写反例、独立误差传播推导、G1/G3 SHA 核对、对照复跑作者 `test_canonical.py`。
- 不做：不改 `src/`/`tests/`/`reports/V9-G3/`；不训练；不 accept；不碰他人未提交的 G1 WIP。

## 2. 不利反例一览

| 反例 | 对抗输入 | 独立判据 | 故意改坏对照 |
|---|---|---|---|
| C1 近 π 等变+恒等 | ±π 邻域 yaw、微小平移 | 等变/往返 ≤1e-9 | 用 `g` 代替 `g⁻¹` |
| C2 反射混入 | det=−1 SE(2) 形矩阵 | validate/compose 拒 | 仅查有限性的弱校验 |
| C3 非刚体 | 缩放、剪切 | 全部拒绝 | 只查底行 [0,0,1] |
| C4 栅格越界 | 远信念 vs 近信念 | fill+掩码 | 只查 data 有限 |
| C5 非 PD 协方差 | 不定/奇异/非对称/NaN/Inf | 拒；SPD 可注入 | 弱对称有限性检查 |
| C6 恒等+高度 | SE3 点集、roll 信念 | 往返/高度/拒绝 | 完整均值逆代替 lift(...,0) |
| C7 误差传播 | 独立 J、FD、MC | 推导一致+相对≤5% | 丢掉 yaw 列 |
| C8 图像拒 | `(H,W,3)` | ValueError | 展平为点集会通 |

## 3. 实际命令（cwd=`/Users/mac/AinerWorkFlow/AinerZero`）

```text
relay claim ainerzero.V9.G4 --agent composer-m7k2 --token …   # exit 0
.venv-ainerzero/bin/python -B reports/V-V9-G4/independent_counterexamples.py \
  --json-out reports/V-V9-G4/evidence/counterexamples-summary.json   # exit 0（8/8）
.venv-ainerzero/bin/python -B reports/V-V9-G4/check_g1_sha.py \
  --json-out reports/V-V9-G4/evidence/g1-sha-check.json               # exit 0（HEAD=登记）
.venv-ainerzero/bin/python -m pytest tests/v9/geometry/test_canonical.py -q \
  -p no:cacheprovider --junitxml=reports/V-V9-G4/evidence/g3-tests-replay.xml  # exit 0（57 passed）
```

长命令经 `relay exec ainerzero.V9.G4 --agent composer-m7k2 -- …` 运行。

## 4. 误差传播推导核对

右扰动 `X=μ Exp(ξ)`，`ξ=(ρx,ρy,θ)`（SE2）。规范点 `p̃=(μExp(ξ))⁻¹x ≈ Exp(−ξ)·p`，一阶：

`δ ≈ −[ρx, ρy, 0]ᵀ − θ·J·p`，`J=[[0,-1],[1,0]]`。

向量无平移项：`δ ≈ −θ·J·v`。预测 `Σ̂ = J_ξ Σ J_ξᵀ`。

独立实现的 `J_ξ` 与 `predicted_*_error_covariance` 最大差 **0.0**；对 `canonicalize_points` 的有限差分 Jacobian 最大差 5.65e-8；经验协方差（N=8000）相对预测 1.08%/1.12%。结论：作者推导与实现一致，登记 5% 门在本独立样本下成立。

## 5. G1 文件 SHA

| 文件 | 登记==HEAD | 工作树 |
|---|---|---|
| `__init__.py` / `lie.py` / `test_geometry.py` | 是 | 是 |
| `belief.py` / `gravity.py` / `pose_graph.py` | 是 | **否**（未提交 F1/F2 修补） |

判定：**G3 未改动已验收/已提交的 G1**。工作树漂移另案（疑 G5），不计入 G3 缺陷。

## 6. 身份

| 文件 | SHA256 |
|---|---|
| `canonical.py`（被验） | `ea446f76043f8aeac33d1665dbf18252a4678700b849d54e17f5fa9cc3282a50` |
| `test_canonical.py`（被验） | `38ced822b96d9815b6d1a7a2f40d3e0c48475054466311699dfd7dff02ab9606` |
| `independent_counterexamples.py` | `beed13eaa91635178301d441048f8ec7965c99f5132ad79465e4634e2f83003e` |
| `check_g1_sha.py` | `5a72ca600da181b14fc960e91052eb51b504a2ff96fbbe083e5e1f9173440afa` |

## 7. 失败与未验证

- 未重跑作者三变异子进程套件（当前 WT 的 G1 漂移会使 `run_checks` 在 G1 门失败；独立证据已覆盖方向/反射/越界/传播）。
- 未验证栅格解析界 `B1=h²/4·sup‖H‖₂` 的作者数值场（C4 只验越界合同；作者 pytest 对照已绿）。
- 左扰动传播预测（模块明确不提供）未测。
- 工作树 G1 WIP 未审查正确性（超出本卡范围）。

## 8. 交回统筹

- **建议验收 G3**（限：解析规范化算子的 CPU 性质与作者报告数字口径）。
- 请一级知悉：工作树三份 G1 文件未提交漂移；若要复现作者 `run_checks.py`，需在干净 HEAD 或明确隔离环境下跑。
- 不 accept 本复核任务。
