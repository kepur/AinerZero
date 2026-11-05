# E1 先验 F_prior 盒体接触改用支撑函数交付报告（ainerzero.V9.P85）

- **执行代理**：gemini-9a2k（二级执行 agent，纯 CPU / NumPy）
- **任务 ID**：`ainerzero.V9.P85`
- **对应阶段**：AinerZero V9 落地 · 轨道 P S1–S2 实验 · 第 85 步
- **依据协议**：`reports/V9-P48/E1_IMPLEMENTATION_PLAN.md` 架构裁定修订 r1 第 1、2 条
- **修改文件范围**：
  - `src/ainerzero/v9/experiments/e1/prior.py`
  - `tests/test_e1_prior_box.py`（新建解析验证集）
  - `reports/V9-E1BOX/gemini-9a2k/`（交付报告、前置基线与坏对照）

---

## 1. 背景与缺陷归因

在修订 r1 之前，`prior.py` 将所有活动刚体均近似为包围球（原登记结构偏差 #1）。对于尺寸为 $1.2 \times 1.2 \times 1.0$ 的长方体盒体，其实际半高 $e_z = 0.5\text{ m}$，但包围球半径 $R = \sqrt{0.6^2 + 0.6^2 + 0.5^2} \approx 0.985\text{ m}$。这导致盒体在地面、桌面或叠放时，第 1 物理步即被法向穿透修正强制抬升 $0.485\text{ m}$（在 P82 smoke 中 `box_stack` 初始误差高达 $0.905\text{ m}$），引发自回归滚动剧烈发散。

---

## 2. 数学建模与实现

### 2.1 几何与支撑函数
`ActiveBody` 新增属性 `half_extents: np.ndarray | None`（默认 None 表示球体，形状为 $(3,)$ 表示盒体半边长 $[e_x, e_y, e_z]$）。盒体同时保留 $R$（用于计算各向同性惯量）。

针对任意单位接触法向 $\vec{n}$（指向刚体内部），世界系下本体主轴为姿态四元数 $q$ 导出的旋转矩阵 $R(q)$ 的列向量 $\vec{a}_i$。凸盒体支撑函数为：
$$h(\vec{n}) = \sum_{i=0}^2 e_i |\vec{n} \cdot \vec{a}_i| = \sum_{i=0}^2 e_i |(R(q)^T \vec{n})_i|$$
当刚体为球体（`half_extents is None`）时，严格退化为 $h(\vec{n}) = R$。

`make_active_body_from_state` 支持新增可选参数 `half_extents=None`，不传时保持逐位相同的球体行为。

### 2.2 接触间隙与穿透修正
所有接触模型中的半径 $R$ 统一替换为支撑距离 $h(\vec{n})$：
1. **地面平面（GroundPlane）**：法向 $\vec{n} = (0, 0, 1)$，间隙 $d = z - z_{\text{surf}} - h(\vec{n})$。
2. **斜面（InclinedRamp）**：斜面单位外法向 $\vec{n}$，间隙 $d = (\vec{c} - \vec{p}) \cdot \vec{n} - h(\vec{n})$。
3. **静态盒与桌面（StaticBox & TableTop）**：
   - 盒外接触：$\vec{n} = (\vec{c} - \text{closest}) / \|\vec{c} - \text{closest}\|$，穿透量 $\text{pen} = h(\vec{n}) - \text{dist}$。
   - 深度穿透：沿用最小出口面法向 $\vec{n}_{\text{exit}}$，$\text{pen} = h(\vec{n}_{\text{exit}}) + d_{\text{min}}$。
4. **两物体间接触**：中心连线单位向量 $\vec{n} = (\vec{c}_2 - \vec{c}_1) / \|\vec{c}_2 - \vec{c}_1\|$，法向间隙为：
   $$\text{gap} = \|\vec{c}_2 - \vec{c}_1\| - h_1(\vec{n}) - h_2(-\vec{n})$$
   穿透重叠量 $\text{overlap} = -\text{gap}$。

### 2.3 冲量力学一般化
惯量模型遵循结构偏差 #2（$I = \frac{2}{5} m R^2$），接触点力臂取支撑投影 $\vec{r}_c = -h(\vec{n}) \vec{n}$：
1. **接触点线速度**：
   $$\vec{v}_c = \vec{v} + \vec{\omega} \times \vec{r}_c = \vec{v} - h(\vec{n}) (\vec{\omega} \times \vec{n})$$
2. **切向相对速度**：
   $$\vec{v}_{ct} = \vec{v}_c - (\vec{v}_c \cdot \vec{n}) \vec{n}$$
3. **切向粘滞冲量（Generalised Sticking Impulse）**：
   $$\Delta \vec{v}_c = \left(\frac{1}{m} + \frac{h^2}{I}\right) \vec{J}_t \implies J_{\text{stick}} = \frac{\|\vec{v}_{ct}\|}{\frac{1}{m} + \frac{h^2}{I}}$$
   对于两体碰撞，分母推广为 $(\frac{1}{m_1} + \frac{h_1^2}{I_1}) + (\frac{1}{m_2} + \frac{h_2^2}{I_2})$。
   当 $h = R$ 时，分母严格为 $\frac{7}{2 m}$，切向冲量严格退化为 $\frac{2}{7} m \|\vec{v}_{ct}\|$。
4. **力矩耦合与角速度增量**：
   $$\Delta \vec{\omega} = I^{-1} (\vec{r}_c \times \vec{J}_t) = -\frac{h(\vec{n})}{I} (\vec{n} \times \vec{J}_t)$$
   球体时 $-\frac{h}{I} = -\frac{R}{\frac{2}{5} m R^2} = -\frac{5}{2 m R}$，完全一致。

### 2.4 登记结构偏差清单更新
`REGISTERED_STRUCTURAL_BIASES["collision_geometry"]` 已按修订 r1 更新登记：
`"support_function: box contact uses support distance h(n)=sum(e_i*|n.a_i|), contact point at support projection r_c=-h(n)*n, inter-body normal uses center line, single-point contact"`。

---

## 3. 解析与回归测试实测数值

测试脚本位于 `tests/test_e1_prior_box.py`，全部实测数据对比如下：

| 测试用例 | 理论标准 / 阈值 | 实测数值 | 误差 / 相对误差 | 结论 |
|---|---|---|---|---|
| **球体落地回弹回归** | 与修改前副本逐位相同 | 793 元素逐位匹配 | $\text{diff} = 0.0$ | **PASS** |
| **球体斜面滚动回归** | 与修改前副本逐位相同 | 793 元素逐位匹配 | $\text{diff} = 0.0$ | **PASS** |
| **两球对撞回归** | 与修改前副本逐位相同 | 两球共 1586 元素逐位匹配 | $\text{diff} = 0.0$ | **PASS** |
| **静止盒（地面水平）** | 600 帧（10 s），$|\Delta z| < 1\times 10^{-4}$，水平漂移 $< 1\times 10^{-4}$ | $\max|\Delta z| = 0.0$，$\max \Delta_{xy} = 0.0$ | $0.0$ | **PASS** |
| **静止盒（Z 轴旋转 45°）** | 600 帧，$|\Delta z| < 1\times 10^{-4}$，水平漂移 $< 1\times 10^{-4}$ | $\max|\Delta z| = 0.0$，$\max \Delta_{xy} = 0.0$ | $0.0$ | **PASS** |
| **桌面静止盒（z_top=1.7）** | 600 帧，中心 $z=2.0$，误差 $< 1\times 10^{-4}$ | $\max|\Delta z| = 0.0$，$\max \Delta_{xy} = 0.0$ | $0.0$ | **PASS** |
| **双盒叠放（z=0.5, 1.5）** | 120 帧（2 s），两盒 $|\Delta z| < 1\times 10^{-3}$ | 下盒 $5.45\times 10^{-5}$，上盒 $5.45\times 10^{-5}$ | $< 0.055\text{ mm}$ | **PASS** |
| **滑动减速** | $v_0 = 2.0\text{ m/s}$，$a = -\mu_{\text{eff}} g$，相对误差 $< 2\%$ | $a = 4.90500\text{ m/s}^2$（理论 $4.905$） | 相对误差 $3.62\times 10^{-15}$ | **PASS** |
| **滑动至停止** | 一直测到完全停止 | 停止帧第 25 帧，$v_{\text{final}} = 3.899\times 10^{-5}\text{ m/s}$ | 严格维持停止 | **PASS** |
| **斜面下滑** | 倾角 $30^\circ$，$a = g(\sin\theta - \mu_{\text{eff}}\cos\theta)$，相对误差 $< 3\%$ | $a = 4.0721\text{ m/s}^2$（理论 $4.0554$） | 相对误差 $0.41\%$ | **PASS** |
| **切向粘滞冲量推广式** | $J_{\text{stick}} = \|v_{ct}\| / (1/m + h^2/I)$ vs 遗留式 $\frac{2}{7}m\|v_{ct}\|$ | $\Delta v_{\text{actual}} = -6.0815\times 10^{-4}\text{ m/s}$（遗留式 $-2.8571\times 10^{-4}$） | 吻合理论，与遗留式偏差 $> 100\%$ | **PASS** |

---

## 4. 隔离副本坏对照验证（Mutation / Negative Controls）

在隔离临时目录中注入以下 3 种变异，运行 `test_e1_prior_box.py` 验证变红敏感性：

1. **坏对照 (a)：地面接触将 $h(\vec{n})$ 换回包围球半径 `radius`**
   - 结果：**RED（2 项用例失败）**
   - 失败日志：`AssertionError: Flat box vertical error 4.8486e-01 >= 1e-4`
   - 原因：$1.2\times 1.2\times 1.0$ 的盒子被包围球半径强制抬起 $0.485\text{ m}$，精准捕获原结构缺陷。

2. **坏对照 (b)：支撑函数漏掉绝对值（`projections = R.T @ n`）**
   - 结果：**RED（2 项用例失败）**
   - 失败日志：`AssertionError: Top box vertical error 1.0000e+00 >= 1e-3` 及 `test_support_distance_analytical` 失败。
   - 原因：负向投影变为负支撑距离，盒体反向穿透下陷。

3. **坏对照 (c)：切向冲量用回 `(2/7) * m * |v_ct|`**
   - 结果：**RED（2 项用例失败；球体回归保持 GREEN）**
   - 失败日志：`AssertionError: Frame 25 speed error 2.2623% exceeds 2%` 及 `test_box_sticking_tangential_impulse` 失败。
   - 独立验证：运行球体回归 `test_sphere_regression_bitwise_identical` 依然为 **GREEN (exit code 0)**，证明变异只对盒体生效，对球体等价。

---

## 5. E1 全量测试回归结果

运行整个测试目录 `tests/test_e1_*.py`：
```bash
=== tests/test_e1_analysis.py === 11 passed
=== tests/test_e1_arms_net.py === 18 passed
=== tests/test_e1_arms_nonnet.py === 14 passed
=== tests/test_e1_data_runner.py === 10 passed
=== tests/test_e1_entry.py === 11 passed
=== tests/test_e1_eval_runner.py === 16 passed
=== tests/test_e1_export.py === 10 passed
=== tests/test_e1_identity.py === 7 passed
=== tests/test_e1_metrics.py === 16 passed
=== tests/test_e1_prereg.py === 18 passed
=== tests/test_e1_prior.py === 13 passed
=== tests/test_e1_prior_box.py === 9 passed
=== tests/test_e1_train_runner.py === 9 passed
=== tests/test_e1_wiring.py === 8 passed
============================= 170 passed in 14.1s =============================
```
**总通过数：170 / 170 全部通过，0 失败**。没有测试依赖原包围球盒体抬升行为。

---

## 6. 交付文件清单与校验和

交付目录位于 `reports/V9-E1BOX/gemini-9a2k/`：
- `before/prior.py`：修改前先验积分器副本
- `before/sphere_regression_fixtures.npz`：修改前纯球体场景金标轨迹
- `REPORT.md`：本报告
- `metrics.json`：实测数值指标汇总
- `SHA256SUMS.txt`：交付物完整性校验和
