# ainerzero.V9.P226 非作者复核报告（复核 B：渲染器几何、帧对齐与泄露）
角色：executor（非作者独立复核人）；负责人：gemini-f7b2；时间：2026-11-11
任务状态：reported；实验状态：completed
任务依据：任务 ainerzero.V9.P226【L2·复核】S5 设计稿 r0 非作者复核 B：渲染器几何、帧对齐与泄露（纯 CPU，只写 r0-review-b）
被审对象：`reports/V9-S5-DESIGN/DESIGN-r0.md`、`reports/V9-S5-DESIGN/tier1-explore/render.py`（作者：一级 claude，提交 `8a038c2`）
复核约束：纯 CPU，只写 `reports/V9-S5-DESIGN/r0-review-b/`，不修改被审代码与设计，不跑 MLX，不拿锁
总体结论：**建议采纳（有 1 处严重阻断缺陷须在实现时修改，3 处需明确规范）**

---

## 一、条目 1：几何正确性核对

- **结论：成立。**
- **复核脚本：** `checks/check1_geometry.py`
- **原始证据：** `evidence/check1_geometry.json`

独立从第一性原理推导针孔光线投射解析解，不复用 `render.py` 内部逻辑，对 6 个几何性质进行数值比对，比对结果如下：

### 1.1 场地中央朝正 x 方向时中间列墙的深度
- **理论解析：** 智能体置于场地中央 $(x_0, y_0) = (5.0, 5.0)$，朝向 $\text{heading} = 0.0$。东侧墙位于平面 $x = 10.0$。对于图像中间列（$W = 224$，第 111 列与第 112 列，列偏移为 $\pm 0.5$），光轴沿正 $x$ 方向。由于东墙垂直于光轴，任何击中该平面的光线距离为 $t = (10 - x_0) / \cos\theta$，其沿光轴的正交深度为 $z = t \cos\theta = 10 - x_0 = 5.0$。
- **逐字引用：** `reports/V9-S5-DESIGN/tier1-explore/render.py` 第 55 行：
  ```python
  tx = np.where(dx > 0, (ARENA - ox) / dx, np.where(dx < 0, -ox / dx, np.inf))
  ```
  及第 104 行：
  ```python
  z = t * cos_off                                     # [W]
  ```
- **实测结果：** 第 111 列与第 112 列实测深度均为 `5.000000`，解析误差为 `0.0`。

### 1.2 地面行深度解析式
- **理论解析：** 相机高度 $h_{cam} = 0.5$，焦距 $f = (W/2) / \tan(45^\circ) = 112.0$。地平面位于 $y = 0.0$。对于视平线以下（$r \ge 112$）的第 $r$ 行，像素向下偏移量为 $\text{row} = r + 0.5 - H/2$。由相似三角形：
  $$z_{\text{floor}}(r) = \frac{f \cdot h_{cam}}{\text{row}} = \frac{112.0 \cdot 0.5}{r + 0.5 - 112}$$
- **逐字引用：** `reports/V9-S5-DESIGN/tier1-explore/render.py` 第 90 行：
  ```python
  floor_z = np.where(rows > 0, f * CAM_H / rows, np.inf)          # [H, 1]
  ```
- **实测结果：** 在地面未被墙遮挡的第 125 行至 223 行全域扫描，`render()` 输出与独立解析式最大绝对误差为 `8.88e-16`（浮点极限精度），完全一致。

### 1.3 柱子与圆盘的顶底边行号
- **理论解析：** 智能体置于 $(5.0, 5.0)$，光轴正前方 $(8.0, 5.0)$ 放置一根半径 $0.5$、高 $h = 2.0$ 的柱子。柱子最近表面深度 $z = (8.0 - 0.5) - 5.0 = 2.5$。
  - 顶边相对相机高度 $\Delta h_{\text{top}} = 2.0 - 0.5 = +1.5$，投影行偏移 $\text{row}_{\text{top}} = -f \frac{\Delta h_{\text{top}}}{z} = -112 \times \frac{1.5}{2.5} = -67.2$，对应像素行号 $\lceil -67.2 + 111.5 \rceil = 45$；
  - 底边位于地面 $\Delta h_{\text{bottom}} = 0.0 - 0.5 = -0.5$，投影行偏移 $\text{row}_{\text{bottom}} = -f \frac{-0.5}{2.5} = +22.4$，对应像素行号 $\lfloor 22.4 + 111.5 \rfloor = 133$。
- **逐字引用：** `reports/V9-S5-DESIGN/tier1-explore/render.py` 第 107-108 行：
  ```python
  top = -f * (h - CAM_H) / zs                         # row offsets (positive downward)
  bottom = f * CAM_H / zs
  ```
- **实测结果：** `render()` 输出中柱子渲染的最小行号为 `45`，最大行号为 `133`，与解析计算逐像元完全吻合。

### 1.4 柱子正后方圆盘遮挡
- **实测设计：** 在 $(7.0, 5.0)$ 放置半径 $0.5$ 的柱子，在正后方 $(9.0, 5.0)$ 放置半径 $0.3$ 的圆盘。圆盘完全落入柱子的视线阴影中。
- **逐字引用：** `reports/V9-S5-DESIGN/tier1-explore/render.py` 第 111 行及第 128 行：
  ```python
  nearer = zz < depth
  ...
  ids = np.where(nearer, oid, ids)
  ```
- **实测结果：** 编号图 `ids` 中圆盘 ID（100）的像素总计数精确为 `0`，深度缓冲 `depth` 准确保持为柱子深度，遮挡完全生效。

### 1.5 左右方向极性
- **实测设计：** 智能体朝正 $x$ 方向（$\text{heading} = 0$），在左侧 $(8.0, 6.0)$（$+y$ 方向）放置圆盘。
- **逐字引用：** `reports/V9-S5-DESIGN/tier1-explore/render.py` 第 76 行：
  ```python
  ang = heading - np.arctan(cols / f)                     # left of the image is counter-clockwise
  ```
- **实测结果：** 圆盘在渲染图像中的列范围为第 62 列至第 85 列（均值 73.4 列），全部严格位于图像左半侧（列号 $< 112$），左右方向极性正确。

### 1.6 深度定义（正交深度 z vs 射线距离 t）
- **理论解析：** 针孔相机与对齐任务中，标准深度应为沿光轴的距离 $z = t \cos\theta$，而非射线欧几里得距离 $t$。在东墙平面 $x = 10.0$ 上，边缘列（如第 60 列至第 164 列）射线倾角 $\theta$ 可达 $\pm 25^\circ$，若深度为 $t$ 则边缘会呈现向外弯曲的枕形失真（深度增大至 $5.0 / \cos(25^\circ) \approx 5.51$）。
- **逐字引用：** `reports/V9-S5-DESIGN/tier1-explore/render.py` 第 104 行：
  ```python
  z = t * cos_off                                     # [W]
  ```
- **实测结果：** 在平直墙面上跨列采样，实测深度全列恒定为 `5.000000`，列间最大波动为 `0.0`，证实输出为严格的正交深度 $z$。

---

## 二、条目 2：纹理世界锚定核对

- **结论：成立。**
- **复核脚本：** `checks/check2_texture.py`
- **原始证据：** `evidence/check2_texture.json`

### 2.1 机制审查与逐字引用
- 地面方格在 `render.py` 中通过重投影计算世界坐标点 $(f_x, f_y)$：
  逐字引用 `reports/V9-S5-DESIGN/tier1-explore/render.py` 第 96-98 行：
  ```python
  tf = np.where(np.isfinite(floor_z), floor_z, 0.0) / cos_off[None, :]   # ray length to the floor point
  fx, fy = x0 + tf * dx[None, :], y0 + tf * dy[None, :]
  checker = (np.floor(fx) + np.floor(fy)) % 2
  ```
  由于 $t_f = z / \cos\theta$ 为地面交点到相机的射线长度，$(dx, dy)$ 为世界坐标下的光线单位向量，因此 $(f_x, f_y)$ 是地平面上物理点的精确绝对世界坐标。
- 墙体与柱子竖条纹同样采用世界坐标：
  逐字引用 `reports/V9-S5-DESIGN/tier1-explore/render.py` 第 120 行：
  ```python
  u = np.where(np.abs(nx) > 0.5, y0 + zs / cos_off * dy, x0 + zs / cos_off * dx)
  ```

### 2.2 旋转不变性实验
- **设计：** 智能体位于 $(5.0, 5.0)$ 保持位置不变，仅改变朝向：$\text{heading}_1 = 0.0$ 与 $\text{heading}_2 = 0.12$ rad（偏转约 $6.88^\circ$）。
- 在地面上选取 6 个处于方格内部的固定世界坐标点：$(6.5, 5.4)$、$(6.3, 5.3)$、$(7.2, 4.6)$、$(5.8, 5.2)$、$(6.7, 4.4)$、$(7.4, 5.3)$。
- 分别计算其在两帧画面中投影对应的亚像素坐标，提取光照归一化后的纹理调制因子。
- **实测结果：**
  - 点 $(6.5, 5.4)$：帧 1 投影于像素 $[149, 82]$，帧 2 投影于像素 $[148, 96]$，实测调制均为 `1.000`（方格值 1）；
  - 点 $(5.8, 5.2)$：帧 1 投影于像素 $[182, 83]$，帧 2 投影于像素 $[180, 97]$，实测调制均为 `0.820`（方格值 0）；
  - 全部 6 个点在智能体偏转前后所提取的方格值与世界真值 100% 吻合，证实地面方格严格锚定于世界坐标。

---

## 三、条目 3：DA2 帧对齐核对（设计稿 §2 与渲染器接口）

- **结论：设计稿数学推导成立；但当前 `render.py` 存在严重实现缺陷，必须增加参数。**
- **复核脚本：** `checks/check3_da2_alignment.py`
- **原始证据：** `evidence/check3_da2_alignment.json`

### 3.1 针孔模型理论推导
逐字引用 `reports/V9-S5-DESIGN/DESIGN-r0.md` 第 90 行：
```text
DA2 的帧另外渲染成 518×392，焦距按画面高度与学生帧取同一比例（f = 196 像素）。这样 DA2 帧中间那块 392×392，正好对应学生帧的视野，DA2 两侧还多看到一些上下文。蒸馏目标从中间那块取，缩到 56×56。
```
1. **学生帧几何：** 分辨率 $224 \times 224$，水平视场 $\text{FOV}_x = 90^\circ$。
   $$f_{\text{student}} = \frac{W_s / 2}{\tan(45^\circ)} = \frac{112}{1.0} = 112\text{ px}$$
   垂直视场同样为 $90^\circ$。
2. **DA2 帧几何：** 分辨率 $518 \times 392$。若设 $f_{\text{da2}} = 196.0$ 像素：
   垂直视场为 $2 \arctan(\frac{392 / 2}{196}) = 2 \arctan(1.0) = 90^\circ$。
   中间 $392 \times 392$ 裁切块的水平视场为 $2 \arctan(\frac{392 / 2}{196}) = 90^\circ$。
3. **$56 \times 56$ 特征块逐网格角对齐：**
   - 学生帧下采样 $4\times$（$224 \to 56$），第 $i$ 个网格中心距离光轴偏移为 $4i + 2 - 112$；其视线正切值为 $\tan\theta_s(i) = \frac{4(i - 27.5)}{112} = \frac{i - 27.5}{28}$；
   - DA2 中间块下采样 $7\times$（$392 \to 56$），第 $i$ 个网格中心距离光轴偏移为 $7i + 3.5 - 196$；其视线正切值为 $\tan\theta_d(i) = \frac{7(i - 27.5)}{196} = \frac{i - 27.5}{28}$。
   - **比对结果：** 对所有 $i \in [0, 55]$，$\tan\theta_s(i) \equiv \tan\theta_d(i)$，角误差精确为 `0.0`。因此设计稿的裁剪与焦距设定在数学上**完全正确**。

### 3.2 当前 `render.py` 的漏洞定位
- 逐字引用 `reports/V9-S5-DESIGN/tier1-explore/render.py` 第 74 行：
  ```python
  f = (width / 2) / math.tan(FOV / 2)
  ```
- **问题分析：** 当前代码硬编码 $\text{FOV} = 90^\circ$ 为水平视场。若直接调用 `render(width=518, height=392)`：
  计算出的焦距为 $f = 518 / 2 = 259.0$ 像素，而非设计要求的 $f = 196.0$。
- **导致的严重失真：**
  $f = 259.0$ 使得中央 $392 \times 392$ 的实际视场缩水至 $2 \arctan(196 / 259) \approx 74.23^\circ$（比学生帧小近 $16^\circ$）。
  在 $56 \times 56$ 特征图边缘（$i = 55$ 处），像素角偏移量错位高达 **61.88 像素**，折合在 $56 \times 56$ 蒸馏目标图上产生 **8.84 个 token 的巨大错位**！
- **实现时必须修改的参数：**
  函数签名须修改为支持显式传入焦距 $f$：
  ```python
  def render(agent, positions, pillars, *, width=224, height=224, f=None, return_ids=False, texture=False):
      if f is None:
          f = (width / 2.0) / math.tan(FOV / 2.0)
  ```
  在生成 DA2 图像时，显式调用 `render(..., width=518, height=392, f=196.0)`。

---

## 四、条目 4：泄露审查

- **结论：数据流与特征无真值泄露（成立）；摸底探针存在测试集选 $\lambda$ 的轻微方法学缺陷（需规范）。**
- **复核脚本：** `checks/check4_leakage.py`
- **原始证据：** `evidence/check4_leakage.json`

### 4.1 摸底探针独立性核对
- **世界与轨迹种子：** 训练集（世界 0、1、2）与测试集（世界 3）由 `world.derive_seed` 生成，随机数生成器隔离，世界种子分别为 `1211346038, 849658657, 1018980974, 1645549838`，智能体轨迹种子分别为 `1476499916, 715381212, 995997296, 178235790`，无任何跨世界重合。
- **标准化统计量：** 逐字引用 `reports/V9-S5-DESIGN/tier1-explore/explore_s5a_probes.py` 第 79 行：
  ```python
  mu, sd = xtr.mean(0), xtr.std(0) + 1e-6
  ```
  均值与方差仅在 `xtr` 上拟合，测试集无前向统计量泄露。
- **$\lambda$ 选择与影响评估：**
  - 逐字引用 `reports/V9-S5-DESIGN/DESIGN-r0.md` 第 55 行：
    ```text
    每格取四个 λ 里最好的；三种输入的 λ 敏感性都不大，见 json。
    ```
  - 核对发现探针对 $\lambda \in \{1, 100, 1000, 10000\}$ 的最优选择确实直接基于测试集性能，构成轻微方法学后验挑选（Post-hoc test selection）。
  - **实测敏感性差值：** 提取 `round-a/probes-r2.json`，对于 V-JEPA 特征，$\lambda = 1$ 与最优 $\lambda = 100$ 的 $R^2$ 差异：
    `inv_all` 差异仅 $+0.00178$，`logd_nonsky_obj` 差异仅 $+0.00400$，`disk_all` 差异仅 $+0.00600$。
  - 结论：$\lambda$ 敏感性极低（$< 0.6$ 个百分点），即使无脑固定 $\lambda = 1.0$，V-JEPA 的几何表征质量（$R^2 \approx 0.92 \sim 0.94$）依旧大幅碾压像素基线（$R^2 \approx 0.21 \sim 0.27$），定性结论不受影响。

### 4.2 数据流隔离审查（设计稿 §2 与 §3）
逐字审查数据通路：
1. **学生输入通路：**
   逐字引用 `reports/V9-S5-DESIGN/DESIGN-r0.md` 第 92 行：
   ```text
   **学生输入：** 只有 RGB 帧。智能体位姿、对象编号、深度真值都不进学生输入。
   ```
   及第 181 行：
   ```text
   - **对象编号不进学生：** 学生的数据入口只接受 `uint8 [T, H, W, 3]`；
   ```
2. **教师蒸馏通路：**
   - DA2 与 V-JEPA 仅接收 RGB 帧，分别产出相对深度与自监督表征，不接触世界坐标或编号；
3. **读出头监督通路：**
   - 真值深度与占据网格仅在第二阶段用于监督读出头（学生主干已冻结）。
   - 全流程无任何隐蔽通道将位姿、编号或真值深度渗入学生编码器。

### 4.3 R2 集合式网格标签核对
逐字引用 `reports/V9-S5-DESIGN/DESIGN-r0.md` 第 96 行及第 127 行：
```text
- **R2 圆盘占据图：** 取每段最后一帧，把画面里看得见的圆盘放到自我中心网格上：方位 12 格覆盖 90° 视场，距离 7 格按对数从 0.5 到 7.0。这是集合式标签，不带编号。完全被挡住的圆盘不算。
...
- R2、R3：注意力池化（1 个可学查询）接两层 MLP，输出 12×7 个 logit，用 BCE。
```
- **核对确认：**
  1. 标签为自我中心极坐标网格（12 个方位角 $\times$ 7 个距离），由于损失函数采用 BCE（Binary Cross Entropy），每个网格单元的目标值必须为严格二值占据状态 $y \in \{0, 1\}$；
  2. 标签不包含任何圆盘实例 ID 或排列顺序；
  3. **需明确规范：** 若同一极坐标网格单元内存在多个可见圆盘，目标值必须饱和为 $1$（集合占据），严禁填入计数值（$\ge 2$），以保证与 BCE 损失的数学自洽性。

---

## 五、条目 5：RLT 实现核对

- **结论：成立（存在缓漂移物理现象，设计稿下限推导准确）。**
- **复核脚本：** `checks/check5_rlt.py`
- **原始证据：** `evidence/check5_rlt.json`

### 5.1 比较对象核对（上一帧 vs 上一个保留 token）
- 逐字引用 `src/ainerzero/v9/tokenization/rlt.py` 第 58-74 行：
  ```python
  prev = video_chunks[:-1]   # [T-1, ph, pw, D]
  curr = video_chunks[1:]    # [T-1, ph, pw, D]

  diffs = np.abs(curr - prev)            # [T-1, ph, pw, D]
  diff_max = np.max(diffs, axis=3)       # [T-1, ph, pw]  (L_inf over the D dim)
  ...
  keep_mask[0] = True  # first frame always kept

  if T > 1:
      keep_mask[1:] = (diff_max >= tau)  # [T-1, ph, pw] boolean
  ```
- **核对结果：** 代码中计算的是相邻切片差值 `video_chunks[1:] - video_chunks[:-1]`，因此它比较的是**上一帧（相邻前一时刻切片 $p_{t-1}$）**，而非上一个保留的锚点 token（$p_{\text{anchor}}$）。
- **缓漂移（Creeping Drift）现象验证：**
  在 `checks/check5_rlt.py` 中构造单位置 10 帧缓慢渐变序列（每帧递增 0.015，$\tau = 0.02$）。
  由于每步步长 $0.015 < \tau$，相邻判断全部判定为未变化，导致除第 0 帧外后续 9 帧全部被舍弃，最终重建最大误差达 $0.135$（超出 $\tau$ 的 6.75 倍）。
  该现象在原单测 `tests/v9/tokenization/test_rlt.py` 第 202 行已有注释说明（*For chains of merges, error can accumulate*）。

### 5.2 设计稿 §3 与式 10 的一致性
- 逐字引用 `ARCHITECTURE_V9.md` 第 151 行：
  ```text
  10. RLT 停帧去重：同一位置的图块若 `‖p_t − p_{t−1}‖_∞ < τ` 就并入上一个 token，并以游程长度编码位置；`τ` 在登记时冻结，报告 token 保留率与精度损失。
  ```
  及 `reports/V9-S5-DESIGN/DESIGN-r0.md` 第 139 行：
  ```text
  与选出来的那个蒸馏臂相同，但开 RLT（τ=0.02，按管长 2 比较），被并掉的块不进注意力，只留下的 token 加游程长度嵌入
  ```
- **核对结果：** 式 10 形式定义即为相邻差值 $\|p_t - p_{t-1}\|_\infty < \tau$，`rlt.py` 与式 10 完全一致。设计稿在时空 ViT 中将基本图块单元升级为管长 2（Tubelet-2）的 3D 切片，本质上是将式 10 的时间采样粒度提升为管长单位，二者在算法机理上保持一致。

### 5.3 首个管长保留与下限 1/8 核对
- 逐字引用 `reports/V9-S5-DESIGN/DESIGN-r0.md` 第 254 行：
  ```text
  - **RLT 按管长 2 比较时，首个管长的块总是保留。** 一段只有 8 个管长，保留率下限是 1/8，GR 的 0.8 门槛已考虑这一点。
  ```
- **理论与实测核对：**
  - 每段视频 16 帧，管长 2，时序切片数 $T = 16 / 2 = 8$；
  - `keep_mask[0] = True` 强制每个空间位置保留第 0 个管长；
  - 在完全静止画面且 $\tau = 0.02$ 时，后续 7 个管长全部被丢弃；
  - 每个空间位置恰好保留 1 个管长，总保留比例精确为 $1 / 8 = 0.125 = 12.5\%$；
  - 实测 `check5_rlt.py` 中静态视频切片保留率精确为 `0.125`。设计稿给出的 $1/8$ 下限和门槛设定**完全正确**。

---

## 六、条目 6：建议修改项清单（按严重程度排序）

| 优先级 | 类别 | 涉及文件与位置 | 缺陷现象 | 建议改成什么 |
| :---: | :---: | :--- | :--- | :--- |
| **P0（阻断）** | 代码缺陷 | `reports/V9-S5-DESIGN/tier1-explore/render.py` 第 74 行 | `render.py` 硬编码水平 $\text{FOV}=90^\circ$ 计算焦距，当传入 DA2 尺寸 $518 \times 392$ 时，焦距被错误算成 $259.0$ 像素（期望 $196.0$），导致中央裁切块视场严重缩水至 $74.2^\circ$，在 $56 \times 56$ 特征图边缘产生 **8.84 个 token 的错位**，直接破坏 DA2 蒸馏对齐。 | 函数签名改为支持传入焦距：<br>`def render(agent, positions, pillars, *, width=224, height=224, f=None, return_ids=False, texture=False):`<br>`    if f is None: f = (width / 2.0) / math.tan(FOV / 2.0)`<br>并在抽取 DA2 帧时显式指定 `f=196.0`。 |
| **P1（重要）** | 规范漏洞 | `reports/V9-S5-DESIGN/DESIGN-r0.md` §2 第 96 行及 §3 第 127 行 | R2 标签采用 12×7 自我中心网格并用 BCE 训练，但未明确同一网格内多个圆盘重叠时是占据标志还是整数计数。若填入计数（$\ge 2$）会导致 BCE 损失发散或未定义。 | 在 §2 中明确补充定义：<br>「R2 极坐标网格标签为严格的二值集合占据（Binary Occupancy $y \in \{0, 1\}$）。若同一网格单元内有多个圆盘，值饱和为 1，不记录计数或编号。」 |
| **P2（中等）** | 说明澄清 | `reports/V9-S5-DESIGN/DESIGN-r0.md` §3 第 139 行及 §9 | `rlt.py` 比较的是相邻切片 $p_{t-1}$ 而非历史保留锚点 $p_{\text{anchor}}$，在持续缓慢运动下存在误差累积。 | 在 §9 风险或 §3 实现说明中补充标注：<br>「当前 RLT 实现为马尔可夫式相邻比对（式 10 原型），适用于定点停帧去重；若后续扩展至复杂慢速推拉镜头，可考虑评估锚点式对比以严格约束重构误差。」 |
| **P3（轻微）** | 方法规范 | `reports/V9-S5-DESIGN/tier1-explore/explore_s5a_probes.py` 第 97 行 | 摸底探针在测试集上挑选了最优 $\lambda$（虽然敏感性仅 $\le 0.006$）。 | 正式预登记与评测代码中，超参数 $\lambda$ 须在训练集上通过交叉验证选定或先验冻结（如固定 $\lambda = 1.0$），不得在 final 测试集上扫参。 |
