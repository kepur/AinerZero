# P233 非作者复核报告：一级补测（P229/P230 R3 与 R1-obj 补充）

- **复核者**：gemini-r7b2（L2 执行层，非作者复核；非 claude 或其任何同会话别名）
- **复核对象**：
  - 一级 claude 于 P229 第 3 轮补充的物化端到端与登记守卫测试；
  - 一级 claude 于 P230 第 3 轮补充的层号语义与蒸馏 mask 损失测试；
  - 一级 claude 于 11-12 补充的 R1 物体占比 `obj` / `r1_obj` 标签与契约测试。
- **复核结论**：**需补**（核心物化端到端、层号与损失 mask 断言严密且击杀多处坏对照，但新补充的 `obj` 测试与现存 `disk_groups` 存在明确的断言盲区，自做 6 处新坏对照中有 2 处漏网）。

---

## 1. 结论与必须补测清单

总体上，一级在第 3 轮补充的物化端到端测试（`test_materialize_end_to_end_*`）和 MLX 层号与 mask 损失测试（`test_features_layer_index_*`、`test_distill_losses_average_only_inside_the_mask`）逻辑扎实，能够精确击杀真实的实现缺陷（如层号偏一位、忽略 mask、物化帧索引错误等）。

然而，针对一级 11-12 补充的 `obj` 标签以及既有的 `disk_groups` 遮挡比测试，复核发现其断言存在严重盲区，导致以下 2 处真实缺陷在全量测试下完全漏网：
1. **`obj` 统计漏掉柱子与圆盘（Mutant K1 漏网）**：`test_r1_object_share_geometry` 构造的场景为 `positions=zeros(0, 2), pillars=()`，场景内仅有一面墙体（编号 0），没有任何柱子和圆盘。当源码被篡改为仅统计墙体（`p_ids == 0`，忽略柱子和圆盘）时，全仓测试 89 项全部通过！
2. **`disk_groups` 遮挡比分母误用全局 ID（Mutant K2 漏网）**：单独渲染单圆盘无遮挡像素时，若误用全局 `disk_oid`（100+i）匹配单圆盘局部 ID（100），导致非 0 号圆盘无遮挡像素全算成 0、遮挡比全变为 0.0，但 `test_disk_groups_contract` 仅做宽泛的 `0 <= occ_ratio <= 1` 和 if-else 重复分类，且其 bad control 只是一个局部 mock lambda，导致该致命缺陷完全漏网！

### 必须补测清单（修复前不能宣告测试闭环）：
1. **补 `test_r1_object_share_with_pillars_and_disks`**：在 `tests/v9/experiments/test_s5_labels.py` 中增加包含柱子（`pillars`）和圆盘（`positions`）的近距离几何场景，断言落在柱子和圆盘上的 patch 其 `obj` 占比显著大于 0，且地面占比 `floor = 1 - sky - obj` 保持恒等。
2. **补 `test_disk_groups_unoccluded_positive_contract`**：在 `tests/v9/experiments/test_s5_labels.py` 中断言可见圆盘列表中存在 `unoccluded_pixels > 0` 且 `occlusion_ratio > 0.8` 的无遮挡圆盘（`occlusion_group == "full"`），并在坏对照中验证若单圆盘 ID 匹配错误（`single_ids == disk_oid`），测试必须抛出断言失败。

---

## 2. 一级补测逐条审核（行号与逐字摘录）

### 【P229 第 3 轮补测 · 物化与登记】（`tests/v9/experiments/test_s5_world.py`）

#### 1. `pool_e2e`（L279–L283，模块级夹具）
- **逐字摘录**：
  ```python
  @pytest.fixture(scope="module")
  def pool_e2e(tmp_path_factory):
      out = tmp_path_factory.mktemp("s5_pool_e2e") / "pool"
      materialize_partition("s5test-pool-e2e", out, world_range=(0, 1))
      return out
  ```
- **审核判断**：
  - **是否检查声称内容**：该夹具仅负责物化一个标准的 pool 测试分区世界供后续测试消费。
  - **状态泄漏分析**：**不泄漏**。其消费者 `test_materialize_end_to_end_matches_direct_calls` 参数化跑 `clip_idx=0` 和 `15`，两者均使用 `np.load` 和只读解析，未对目录进行任何写操作、追加或删除；`tmp_path_factory` 保证在测试会话内生命周期独立，不会污染其他测试。
  - **性能价值**：单次物化耗时约 13.9 秒。提升为 `module` 级别后，避免了对 `clip_idx=0` 与 `clip_idx=15` 重复渲染，直接为该测试文件节省了约 14 秒。

#### 2. `test_materialize_end_to_end_matches_direct_calls`（L286–L305）
- **逐字摘录**：
  - 行 294: `np.testing.assert_array_equal(np.load(wd / f"clip_{clip_idx:02d}.npy"), student_clip(ep, clip_idx))`
  - 行 295: `np.testing.assert_array_equal(np.load(wd / f"da2_{clip_idx:02d}.npy"), da2_frames(ep, clip_idx))`
  - 行 298–300:
    ```python
    np.testing.assert_array_equal(lab["r1_logd"], r1["logd"])          # nan positions compare equal
    np.testing.assert_array_equal(lab["r1_sky"], r1["sky"])
    np.testing.assert_array_equal(lab["r1_obj"], r1["obj"])
    ```
  - 行 301–304:
    ```python
    np.testing.assert_array_equal(lab["r2"], labels.r2(ep, clip_idx))
    np.testing.assert_array_equal(lab["r3"], labels.r3(ep, clip_idx))
    assert _npz_json(lab, "disk_groups_json") == _roundtrip(labels.disk_groups(ep, clip_idx))
    assert _npz_json(lab, "ordering_pairs_json") == _roundtrip(labels.ordering_pairs(ep, clip_idx))
    ```
- **审核判断**：
  - **有效性**：生产代码 `materialize.py` 为避免重复渲染，采用了单帧渲染并传入 `precomputed_frames` 的复用机制。本测试直接调用未传预渲染帧的 `student_clip`、`da2_frames`、`labels.*`，对磁盘文件进行全字段逐元素比对。成功击杀了 `P2`、`P3`、`P5` 以及本复核自做的坏对照 `K4`（R3 误写入 R2 网格）。
  - **局限与盲区**：在 `s5test-pool-e2e` 的第 0 与第 15 段中，第 14 帧与第 15 帧的占据网格碰巧相同，因此此测试单独无法捕获 `materialize.py` 误用第 14 帧计算 R2（该漏洞由下面的换域测试拦截）。

#### 3. `test_materialize_end_to_end_clips_cover_disjoint_steps`（L307–L315）
- **逐字摘录**：
  - 行 312–313:
    ```python
    for c in (1, 7):
        np.testing.assert_array_equal(np.load(out / "world_0000" / f"clip_{c:02d}.npy"), student_clip(ep, c))
    ```
  - 行 314: `assert not list((out / "world_0000").glob("da2_*.npy"))           # only pool partitions get DA2 frames`
- **审核判断**：
  - **有效性**：验证了普通非 pool 测试分区的 clip 同样是互不重叠的 16 步窗口，且非 pool 分区绝对不写 DA2 帧。直接击杀了 `P4`（`base_t = c * 15`，各段帧重叠）。
  - **局限**：仅抽检了第 1 段和第 7 段，但搭配 `pool_e2e` 的第 0 和 15 段，覆盖了头、中间与尾部。

#### 4. `test_materialize_end_to_end_shift_appearances`（L317–L334）
- **逐字摘录**：
  - 行 327–331:
    ```python
    bg = np.load(wd / f"clip_{c:02d}_shift_bg.npy")
    al = np.load(wd / f"clip_{c:02d}_shift_all.npy")
    np.testing.assert_array_equal(bg, student_clip(ep, c, appearance=SHIFT_BG))
    np.testing.assert_array_equal(al, student_clip(ep, c, appearance=SHIFT_ALL))
    assert not np.array_equal(bg, al)
    ```
- **审核判断**：
  - **有效性**：验证了换域测试分区 `s5test-final-shift-e2e` 确实物化生成了 `shift_bg` 与 `shift_all` 两套独立画面，且断言两套画面内容确实不同（`assert not np.array_equal(bg, al)`）。并且该测试在 clip 0/15 上成功击杀了 `P1`（`materialize.py` 中 R2 误取第 14 帧）。

#### 5. `test_episode_registered_needs_both_flag_and_run_id`（L336–L359）
- **逐字摘录**：
  - 行 347–349:
    ```python
    for partition in sorted(REGISTERED):
        with pytest.raises(PermissionError):
            episode(partition, 0, registered_run_id="run-x")
    ```
  - 行 353–359:
    ```python
    flag = True
    with pytest.raises(PermissionError):
        W.episode(ns, 0, registered_run_id="run-x")                       # run id without the flag
    with pytest.raises(PermissionError):
        W.episode(ns, 0, allow_registered=flag)                           # flag without a run id
    with pytest.raises(PermissionError):
        W.episode(ns, 0, allow_registered=flag, registered_run_id="  ")   # blank run id
    ```
- **审核判断**：
  - **有效性**：真实预登记分区（`s5p1-final` 和 `s5p1-final-shift`）严格只测拒绝，绝不生成数据；双条件逻辑在替身命名空间上完整覆盖了缺少 flag、缺少 run_id、run_id 纯空白三种拒绝情形。直接击杀了 `M1`（去掉首道守卫检查）。

---

### 【P230 第 3 轮补测 · 层号与蒸馏 Mask】（`tests/v9/experiments/test_s5_student_mlx.py`）

#### 6. `test_features_layer_index_matches_manual_blocks`（L532–L547）
- **逐字摘录**：
  - 行 539–542:
    ```python
    for k in (1, 3, 6):
        feat, _ = model.features(patches, layer=k)
        diff = float(mx.max(mx.abs(feat - manual[k - 1])).item())
        assert diff < 1e-4, f"layer={k} does not match the first {k} blocks (diff={diff})"
    ```
  - 行 546: `assert float(mx.max(mx.abs(manual[2] - manual[3])).item()) > 1e-2`
- **审核判断**：
  - **有效性**：通过独立的手动前向计算图（`_manual_layers`）严格校验了 `layer=k` 对应前 k 个 block 输出的 1-based 语义。行 546 专门断言相邻两层特征绝对差大于 0.01，彻底防范了层号偏一位（off-by-one）巧合相等的假阳性。直接击杀 `E1`。

#### 7. `test_features_layer_index_with_partial_keep`（L549–L564）
- **逐字摘录**：
  - 行 558–563:
    ```python
    for k in (1, 3, 6):
        feat, mask = model.features(patches, keep=mx.array(keep_np), layer=k)
        got = feat[0, mx.array(idx)]
        diff = float(mx.max(mx.abs(got - manual[k - 1][0])).item())
        assert diff < 1e-4, f"partial keep, layer={k}: diff={diff}"
        assert bool(mx.all(mask[0] == mx.array(keep_np[0])).item())
    ```
- **审核判断**：
  - **有效性**：验证了在稀疏保留情况下，保留位置的特征与只计算保留 token 的手动前向一致。成功击杀本复核自做的坏对照 `K5`（`compact_x` 忽略保留索引直接截取前 k 个 token）。
  - **局限**：测试用例使用了 `batch_size = 1`，未测试批内不同保留长度时的 padding 掩码隔离（这一项由前置单测 `test_student_sparse_batch_padding_isolation` 覆盖）；且未断言未保留位置在 `feat` 中是否严格置零。

#### 8. `test_distill_losses_average_only_inside_the_mask`（L566–L579）
- **逐字摘录**：
  - 行 574–579:
    ```python
    student = mx.where(mask[..., None], teacher, -teacher)
    for fn in (cosine_distill_loss, align_loss):
        with_mask = float(fn(student, teacher, mask=mask).item())
        without = float(fn(student, teacher).item())
        assert abs(with_mask) < 1e-5, f"{fn.__name__}: masked-out tokens leaked into the loss ({with_mask})"
        assert without > 0.5, f"{fn.__name__}: control without mask should be large ({without})"
    ```
- **审核判断**：
  - **有效性**：构造了「mask 内完全相同（cos=1，loss=0）、mask 外完全反向（cos=-1，loss=2）」的极致对抗张量。循环测试了 `cosine_distill_loss` 和 `align_loss`，成功击杀 `E3` 以及自做坏对照 `K6`（`align_loss` 丢弃 mask 参数）。

---

## 3. 一级 11-12 补充 `obj` 与 `materialize.py` 写入 `r1_obj` 复核

### 1. 规范核对（`DESIGN-r1.md` §4）
- `DESIGN-r1.md` §4 第 183 行明确规定：「`R1：非天空块对数深度的 RMSE，另按物体块与地面块分开报。`」
- 在渲染器 `render.py`（L136）中，ID 约定严格如下：
  - `-2`：天空
  - `-1`：地面
  - `0`：外围墙体
  - `1..P`：柱子
  - `100+i`：圆盘
- `labels.py` 中新加逻辑：
  `obj_arr[k, r, c] = float(np.sum(p_ids >= 0)) / (PATCH_SIZE * PATCH_SIZE)`
  地面占比定义为 `floor = 1.0 - sky - obj`。
- **核对结论**：物体块像素编号严格为 `p_ids >= 0`（涵盖墙体、柱子、圆盘），地面像素为 `p_ids == -1`，天空为 `p_ids == -2`。数学定义完全符合设计规范。

### 2. 测试缺陷与严重盲区（`test_r1_object_share_geometry`，L336–L359）
- 逐字摘录：
  - 行 337: `"""obj counts wall, pillar and disk pixels; sky + obj + floor shares add up to one (tier-1, 11-12)."""`
  - 行 341–343:
    ```python
    agent = (8.0, 5.0, 0.0)                         # facing the east wall 2 m away
    st = SimpleNamespace(agent=agent, positions=np.zeros((0, 2)))
    ep = SimpleNamespace(steps=[st] * 16, pillars=())
    ```
- **盲区分析**：
  该测试用例注释明确声称测试目标是「obj counts wall, pillar and disk pixels」，但在场景构造时传入了 `positions=np.zeros((0, 2))`（0 个圆盘）和 `pillars=()`（0 根柱子）！
  场景中**只存在一面墙体（id=0），完全没有任何柱子和圆盘**。
  在复核坏对照实验中，我们将统计逻辑篡改为仅统计墙体：
  `obj_arr[k, r, c] = float(np.sum(p_ids == 0)) / (PATCH_SIZE * PATCH_SIZE)`（漏掉所有柱子和圆盘）
  **`test_r1_object_share_geometry` 完全通过！全仓 89 项 CPU 测试 0 失败全部通过！**
  这证明该测试根本没有覆盖柱子和圆盘，是一处重大断言盲区。

---

## 4. 自做 6 处源码坏对照实验（隔离副本内执行）

所有坏对照实验均在 `/tmp` 隔离副本中进行，PYTHONPATH 严格指向副本，原生 MLX 测试严格经 `hold_lock.py` 持共享锁运行。全量坏对照均与历史变异脚本（`mutations.py`、`mutations-materialize.py`、`mutations-obj.py`、`mutations-extra.py`）无任何重叠。

### 实验结果汇总表

| 编号 | 改动位置 | 变异内容 | 预期作用 | 实际结果 | 拦截/漏网分析 |
|---|---|---|---|---|---|
| **K1** | `labels.py` L93 | `p_ids >= 0` → `p_ids == 0` | obj 仅统计墙体，漏掉柱子与圆盘 | **SURVIVED (漏网)** | `test_r1_object_share_geometry` 场景仅含墙体无柱子无圆盘；全仓无其他测试断言物体类别完整性 |
| **K2** | `labels.py` L214 | `single_ids == 100` → `single_ids == disk_oid` | 单圆盘局部渲染 ID(100) 误用全局 disk_oid(100+i) 匹配，导致非 0 号圆盘遮挡比全归 0 | **SURVIVED (漏网)** | `test_disk_groups_contract` 仅重复 if-else 分类且无非零断言，其 bad control 为假 mock 函数 |
| **K3** | `labels.py` L309 | `closer = "a" if za < zb...` → `closer = "b" if za < zb...` | 颠倒 `ordering_pairs` 中谁更近的真值判定 | **KILLED** | 被 `test_ordering_pairs_contract` 成功拦截（1 failed, 14 passed） |
| **K4** | `materialize.py` L187 | `lbl_r3 = r3(...)` → `lbl_r3 = r2(...)` | 物化时 R3 标签误用 R2 占据网格写入 | **KILLED** | 被 `test_materialize_end_to_end_matches_direct_calls[0, 15]` 成功拦截（2 failed） |
| **K5** | `student.py` L131 | `compact_x = x[b, indices]` → `compact_x = x[b, :k]` | Student 稀疏分支未按保留索引 gather，直接截取前 k 个 token | **KILLED** | 持锁被 `test_features_layer_index_with_partial_keep` 成功拦截（1 failed） |
| **K6** | `losses.py` L118 | `mask=mask` → `mask=None` | `align_loss` 调用底层损失时丢弃 mask 参数 | **KILLED** | 持锁被 `test_distill_losses_average_only_inside_the_mask` 成功拦截（1 failed） |

完整运行日志见 `evidence/mutations-output.txt`。

---

## 5. 夹具与性能分析

### 1. `pool_e2e` 状态泄漏排查
- 夹具声明为 `@pytest.fixture(scope="module")`。
- 测试用例 `test_materialize_end_to_end_matches_direct_calls` 仅通过 `np.load`、`_npz_json` 读取产物做 assert 校验，未修改、重写或删除该目录下的任何文件。
- **结论**：**不存在测试间状态泄漏**。

### 2. `test_s5_world.py` 执行耗时排查（实测 43.19 秒）
慢测试耗时分布（见 `evidence/test_durations.txt`）：
- `13.90s` setup `test_materialize_end_to_end_matches_direct_calls[0]`（即 `pool_e2e` 夹具生成 256 帧学生画面 + 16 帧 DA2）
- `10.55s` call `test_materialize_end_to_end_shift_appearances`（生成 `shift_bg` 与 `shift_all` 两套外观共 512 帧）
- `6.13s` call `test_materialize_end_to_end_clips_cover_disjoint_steps`（独立物化 256 帧）
- `5.07s` call `test_materialize_cli_test_partition`（CLI 物化 256 帧）

### 3. 不损失覆盖的提速建议（只提建议，不改动源码与测试）
1. **合并非 pool 物化校验**：`test_materialize_end_to_end_clips_cover_disjoint_steps` 核心检验的是各段是否覆盖互不重叠的 16 步窗口，这一断言可直接在现有的 `pool_e2e` 夹具上抽检（如直接断言 `pool_e2e` 的 clip 1 和 7）；而针对「非 pool 分区不生成 DA2 帧」的断言，可由耗时仅需物化 1 段的微型测试或由既有的 CLI 物化测试顺带检验，可直接省去 6 秒全世界物化。
2. **测试命名空间支持轻量段数**：目前 `materialize_partition` 固定渲染全部 16 段（256 步）。在 `s5test-*` 命名空间中，可允许仅物化指定的段范围（例如 `clip_range=(0, 2)`），使得 `test_materialize_end_to_end_shift_appearances` 只需渲染 2 段而非 16 段（64 帧 vs 512 帧），可直接将该用例从 10.5 秒降至 1.5 秒，整体文件运行时间可从 43 秒压缩至 20 秒以内。
