# P253 S6 沙盒候选池与挑选函数：非作者复核

> 本文件由一级 claude 代为落盘：子代理受 harness 限制不能写报告文件；正文取自子代理最终回复中的 markdown 块原文，仅把 HTML 转义还原为字符。一级抽查：`evidence/e09-tie-order-probe.txt` 第 2、4、5 行与正文一致；`SHA256SUMS.txt` 全部 OK。


**结论：打回（小修）。代码本身没有发现缺陷，只需补测试、重出交付文件。**

- **代码层面**
  - 「挑之前拿不到标签」经公开接口成立，没有构造出泄漏。
  - 与原型、`gated.geo_gate` 的等价性在原型的真实规模（60000 个候选）上逐位成立。
  - 迟到的修补（`reveal` 先读标签再登记）正确，有测试守住。
- **打回原因**：有 4 个非等价变异存活，其中 2 个直接对应卡片点名的要求：
  - 「有测试证明公开接口拿不到」；
  - 「`pick_top` 的同分规则」。
- **交付文件过期**：迟到修补之后，作者的 REPORT、日志和 SHA256SUMS 都没有更新。

复核对象是最终版本：`sandbox.py` sha256 `200e212e…`，`test_s6_sandbox.py` sha256 `9e0a1ca7…`，HEAD `15c676b`。第一版（`6565f2c2…`）上的结果另存为 `e03a/e05a/e08a`，供对照。

复核者与作者同为 claude，但我没有作者上下文。这次复核由一级作者会话派出（见 RESEARCH_LOG 的工作区改动），不是另一个会话。

## 必修

1. **堵住「双下划线方法绕过 `reveal`」的测试缺口**（变异 N1 存活）。
   - 变异：给类加 `__getitem__`，直接调 `self._take([g])`。这样可以拿到任意未揭示样本的标签，不查重、不记日志。现有 25 项全过。
   - 原因有三：
     - 白名单测试只看不以 `_` 开头的名字（`test_s6_sandbox.py:105`）；
     - Poison 测试跳过以 `_` 开头的名字（`:92-94`）；
     - AST 测试只查谁读 `_sealed_labels`（`:115`），不查谁调 `_take`。
   - 建议补两条，补完后复跑 N1 应被杀死：
     - AST 断言 `_take` 只被 `reveal`、`revealed_pool` 引用；
     - 类自身定义的 dunder 只有 `__init__`、`__len__`。
2. **同分规则的测试分辨不出原型写法**（变异 N3 存活）。
   - 把 `np.lexsort((rem, -sr))` 换回原型的 `np.argsort(-sr)`，测试全过。原因是现有用例只有 7 个元素。NumPy 2.5.3 在 16 个元素以内的结果恰好与「按编号升序」相同，17 个起就不同（`e09`）。
   - 建议：用例规模大于 16（例如 200 个、三档分数），断言结果等于按 `(−分数, 编号)` 排序的前 k 个。
3. **重出交付文件**，按最终版本重跑：
   - `REPORT.md` 仍写「纯 NumPy，19 项」，实为 20 项；
   - 第 39 行「先全部检查再登记，失败时不留半截状态」在修补前并不成立，报告没有提到这次修补；
   - `mutate.log`、`numpy-tests.log`、`native-tests.log` 都是修补前的；
   - `SHA256SUMS.txt` 里 `sandbox.py`、`test_s6_sandbox.py` 两项已 FAILED（`e01b`）。

## 应修

4. **N2 存活**：`reveal` 返回「迄今全部已揭示」而不只是本次的 id，测试不报错。
   - 所有测试都只检查第一次 `reveal` 的返回值；第二次的返回值只被丢弃（`test_s6_sandbox_native.py:67`）。
   - 这不算泄漏（返回的都是已揭示样本），但调用方若累积 `reveal` 的返回值，训练样本会重复。
   - 建议断言第二次 `reveal` 只返回本次的 id。
5. **N5 存活**：`states()` 改成返回内部数组的只读视图，测试不报错。
   - 调用方可以把视图的 `writeable` 改回 True，改写内部状态；之后揭示出来的是被改过的状态配上真标签。
   - 现有「拷贝不是视图」测试只改了源池（`:69-75`），没改返回的数组。
   - 建议断言返回数组 `owndata`，或者改写返回数组后检查内部不变。
6. `SHA256SUMS.txt` 的路径基准混用：前 6 行相对交付目录，后 6 行相对仓库根。在任一目录下 `shasum -c` 都有 6 项打不开（`e01`）。
7. 小问题，不影响正确性，只需写明或顺手改：
   - `reveal([])` 也会占一个 call 编号并写进日志（`e04` P5）；
   - `_canon` 不查编号范围，负编号会在 `score[rem]`、`f[rem]` 里回绕（P8）。之后 `reveal` 会报 IndexError，不会静默；
   - 揭示出来的池按字母序排字段，与 `make_pool` 的字段顺序不同（`e14`）。现在没有东西依赖这个顺序。

## 卡外发现，交一级判断，不阻塞本卡

8. **候选池约一半是重复状态。**
   - 规模：在原型候选池上（`s6x-cand`、120 个世界、60000 个、`exact_frac=1.0`），只有 **29245** 个不同状态；17906 个重复组覆盖 48661 行。重复组内标签逐位相同。
   - 原因：`make_pool` 是有放回抽样（`learned_mlx.py:198-199`），每个世界只有 300 步（`world.py:37`）。
   - 后果：取分数最大者会整组挑走重复。用一期 L-int#1–3 的分歧分数跑 4 轮×3000，**12000 个标签里只有 7080 个不同状态**；随机臂 10224 个，几何臂 9789 个（`e05`）。
   - 影响：DESIGN-r0 §2 写「60000 个精确状态」（`DESIGN-r0.md:104`），实际不同状态不到一半；E、O 臂的有效标签预算比 R 少约三成。是否去重或在设计稿里写明，由一级定。
9. **封存只在接口层面成立，有三点要知道。**
   - 标签可以由公开状态加模拟器重算：`W.physics` 重算的 p1/v1 与揭示值最大相差 8.7e-7（`e05` X）。
   - `copy.deepcopy(pool).reveal([i])` 能拿到原对象日志里没有的 i（`e04` P6）。`pickle` 会带上封存的标签。
   - 未审的 `cells.py:106-107` 在挑选期封住了 `W.physics` 和 `CandidatePool._take`（类级封住，深拷贝也被拦住）。运行器复核时应确认这两条确实在挑选路径上生效。

---

## 1. 核心约束「挑之前拿不到标签」

**结论：经公开接口和常见用法都拿不到，迟到的修补正确。** 只有通用 Python 复制（见卡外第 9 条）和调用方自己留着的源池（P7）例外，这两者都不在模块能管的范围内。

探针 `evidence/leak_probe.py`，原始输出 `evidence/e04-leak-probe.txt`。探针把标签存储包一层计数器，统计每次调用读了几次标签。命令：

    $ PYTHONDONTWRITEBYTECODE=1 .venv/bin/python reports/V9-S6-DESIGN/sandbox-module-review/evidence/leak_probe.py

原始输出节选（逐字）：

    P1 states fields {4: ['id', 'p', 'pil', 'v'], 6: ['id', 'p', 'pil', 'v'], 8: ['id', 'p', 'pil', 'v']} | shares memory with internal stores: False | own data: True | internal p after caller write: 7.517390727996826
    P2 dunders the class itself defines: ['__dict__', '__doc__', '__init__', '__len__', '__module__', '__weakref__']
    P2 __len__(): label reads 0
    P2 log(): label reads 0
    P2 remaining(): label reads 0
    P2 revealed_ids(): label reads 0
    P2 revealed_pool(): label reads 0
    P2 states(): label reads 0
    P3 reveal([10, 1]) buckets {4: 1, 6: 1} | revealed_pool rows {4: 1, 6: 1} | shares memory with label store: False
    P4 reveal(dup across calls): ValueError: ids already revealed: [3] | label reads 0 | revealed [2, 3] | log calls 1
    P4 reveal(valid then bad): IndexError: id out of range | label reads 0 | revealed [2, 3] | log calls 1
    P6 deepcopy(pool).reveal([9]) -> labels of id 9 obtained: ['contact', 'p', 'p1', 'p10', 'p5', 'pil', 'v', 'v1', 'v10', 'v5'] | original pool revealed ids [0] | original log [{'call': 0, 'ids': [0]}] -> LEAK relative to the original's log
    P6 pickle round-trip carries the sealed store: True | bytes 9995
    P9 functions referencing _take: ['reveal', 'revealed_pool']
    P10 reveal with a failing label read: label door blocked | revealed [] | log [] | remaining has 3 and 4: True
    P10 after unblocking, reveal([3, 4]) works: [4] | log [{'call': 0, 'ids': [3, 4]}]

P4 一共试了 10 种坏输入：跨次重复、同次重复、越界、负数、bool、float、二维、object、uint64 超大、先合法后越界。每一种都在读标签之前报错，揭示状态和日志不变。

**最终版 `reveal`**（`src/ainerzero/v9/experiments/s6/sandbox.py:99-104`）：

            ids = self._check_new(ids)
            out = self._take(ids)              # read first: if this fails, nothing is registered
            self._revealed.extend(ids)
            self._revealed_set.update(ids)
            self._log.append({"call": len(self._log), "ids": list(ids)})
            return out

验证迟到的修补：
- P10 让读标签抛错，结果什么都没登记；解封后同样的 id 可以正常揭示。
- 我的变异 N9 把修补撤回（先登记、后读），新测试 `test_failed_label_read_registers_nothing` 杀死了它（`e08`）。
- 第一版上，我的 N6（失败的揭示仍把 id 写进查重集合）是存活的（`e08a`）；最终版上它被同一条新测试杀死。

`revealed_pool` 只用已揭示的编号（`sandbox.py:109`）：

            return self._take(list(self._revealed))

`_take` 只被 `reveal`、`revealed_pool` 引用（P9）。所以从代码看，公开路径都拿不到未揭示标签。缺的是**测试**：没有测试守住「`_take` 只有这两个调用者」，见必修 1。

## 2. 与原型、权威实现的等价性

脚本 `evidence/equiv_realscale.py` 导入了 MLX，经锁运行。原始输出 `evidence/e05-equiv-realscale.txt`（最终版本）和 `e05a-…`（第一版，结果相同）。

- **候选池**：与 `explore_s6c`、`explore_s6f` 完全相同，即 `make_pool(train_worlds("s6x-cand", 120), 60000, rng 11, exact_frac=1.0)`。
- **只读权重**：`artifacts/v9/s4/phase1/final-final/weights/L-int#1-3`，用来生成真实的分歧分数。没有写入。

### 2a. `geo_flags` 与 `gated.geo_gate`

- **算式逐行相同**：`sandbox.py:205-214` 与 `gated.py:43-52` 去掉缩进和行尾注释后机械 diff，结果 `IDENTICAL`（`e13-geo-line-diff.txt`）。两边的 `W.RADIUS`、`W.DT` 都来自同一个 `s4.world`。
- **dtype**：`sandbox.py:203-204` 是 `P = np.asarray(e["p"], dtype=np.float64)` 和 `V = np.asarray(e["v"], dtype=np.float64)`。原型 `explore_s6f.py:29` 是：

      return {n: G.geo_gate(e["p"].astype(np.float64), e["v"].astype(np.float64)).any(-1) for n, e in pool.by_n.items()}

  两边都是从 float32 转成 float64，值相同。
- **取 any 的方式**：模块是 `hit.any(-1).any(-1)`（`sandbox.py:216`），原型是 `geo_gate(...)` 返回的 `hit.any(-1)` 再 `.any(-1)`（`gated.py:53`，`explore_s6f.py:29`），等价。
- **边界**：作者对 M5 的分析成立。相接分支去掉 `b < 0` 后，只在 b = 0 且 c = 0 时与原式不同：b > 0 时 tau < 0；b = 0 且 c ≠ 0 时，不是 disc < 0 就是 tau < 0。
- **全规模实测**：

      G geo_flags == explore_s6f.geo_flags on all 60000: True; flagged 1603 (0.0267)
      G geo_gate on float32 states (no cast) differs from float64 on 0 of 60000 samples

  第二行说明：去掉 float64 转换（我的 N4）在实际数据上与原式没有区别，属于实践上等价的变异。

### 2b. 随机数流

- 原型第 0 轮 `rng.choice(len(allp), per, replace=False)`，之后各轮 `rng.choice(rest, …)` 和 geo 的 take/fill（`explore_s6c.py:75`、`:91`，`explore_s6f.py:71-75`）。
- 模块对应 `sandbox.py:162`、`:187`、`:189`。
- 在 60000×4 轮×3000 上跑完整的挑选循环：

      random: ids identical True; sets identical True; positions differing 0 (...); revealed_pool vs subset(cand, prototype chosen): identical; each round's reveal() vs subset(cand, ids): ['identical', 'identical', 'identical', 'identical']; distinct states among the 12000 picks: 10224
      geo: ids identical True; sets identical True; positions differing 0 (...); revealed_pool vs subset(cand, prototype chosen): identical; each round's reveal() vs subset(cand, ids): ['identical', 'identical', 'identical', 'identical']; distinct states among the 12000 picks: 9789

  所以 `rng.choice(整数)` 与 `rng.choice(升序数组)` 在这个规模上逐位一致。随机、几何两种挑法与原型逐位一致。

### 2c. `pick_top` 同分规则

原型 `explore_s6c.py:95` 是：

                    new = rest[np.argsort(-score[rest])[:per]]

模块 `sandbox.py:175` 是：

        order = np.lexsort((rem, -sr))

真实分歧分数下的实测：

    T samples sharing their exact score with another sample: 48661; score values shared by distinct states: 0
    T duplicate groups whose members got different scores: 0
    top: ids identical False; sets identical False; positions differing 4398 (of which same state, i.e. duplicate swapped: 4398); revealed_pool vs subset(cand, prototype chosen): identical; ...

结论：
- **同分全部来自重复状态**，不同状态之间没有一例同分。
- 两种同分规则挑出的编号在 4398 个位置上不同，但每一处都是同一状态的两个副本互换。
- 揭示出的训练池**按行序逐位相同**，所以对训练没有影响。不同的只是日志里的编号。

人为造出不同状态之间的同分（分数取两位小数，只剩 70 个取值）时，两者挑出的内容才会不同：

    top-coarse: ... revealed_pool vs subset(cand, prototype chosen): n=4 field p differs (float32(1394, 4, 2) vs float32(1385, 4, 2))

模块的规则有明确定义，更利于「重放」门；原型的结果则取决于 NumPy 的排序实现。规模大于 16 时两者确实不同（`e09-tie-order-probe.txt`）：

    author case: prototype [1, 2, 4, 6, 5] pick_top [1, 2, 4, 6, 5]
    n=    16 k=     8: same order True; same set True
    n=    17 k=     8: same order False; same set False
    n= 60000 k= 30000: same order False; same set False

第一行说明作者的同分用例分辨不出原型写法，即必修 2。

### 2d. `reveal`、`revealed_pool` 的行序

原型 `explore_s6a.py:46-50`：

    def subset(pool, picks):
        by = {}
        for n, i in picks:
            by.setdefault(n, []).append(i)
        return L.Pool({n: {k: v[np.array(idx)] for k, v in pool.by_n[n].items()} for n, idx in sorted(by.items())})

- 原型按盘数升序分组，组内保持 picks 的顺序；`_take`（`sandbox.py:128-139`）与之相同。
- 跨轮累积时，原型用 `subset(cand, chosen)`，其中 `chosen` 按揭示顺序拼接（`explore_s6c.py:96`）。模块的 `revealed_pool` 用 `self._revealed`，也是揭示顺序。
- 实测：随机、几何两臂的 `revealed_pool` 与原型的 `subset(cand, chosen)` 逐字段、按行序逐位相同；每一轮 `reveal()` 的返回值与 `subset(cand, ids)` 逐位相同（2b 的输出）。
- 行序有意义，因为 `batches` 按行号抽样（`learned_mlx.py:304`：`parts.append(rng.integers(0, int(sizes[j]), batch - sum(len(x) for x in parts)))`）。
- 唯一的差别是字段顺序（`e14`）：

      source order  : ['p', 'v', 'pil', 'contact', 'p1', 'v1', 'p5', 'v5', 'p10', 'v10']
      reveal order  : ['p', 'v', 'pil', 'contact', 'p1', 'p10', 'p5', 'v1', 'v10', 'v5']

  `rollout_loss` 按键名取字段，不受影响（应修 7）。

## 3. 测试能不能抓错

### 3a. 独立复跑

纯 NumPy 部分（`e02-numpy-tests.txt`，逐项 PASSED）：

    $ .venv/bin/python -m pytest -q -p no:cacheprovider -rA tests/v9/experiments/test_s6_sandbox.py
    20 passed in 1.38s

Native 部分经锁运行（`e03-native-tests.txt`，逐项 PASSED，含 P252 的 epinet 回归）：

    $ hold_lock.py artifacts/locks/m0-worker.lock .venv/bin/python -m pytest -q -p no:cacheprovider --native-mlx -rA tests/v9/experiments/test_s6_sandbox_native.py tests/v9/experiments/test_s6_epinet_mlx.py tests/v9/experiments/test_s6_sandbox.py
    32 passed in 2.49s

32 = 4（沙盒 native）+ 8（epinet）+ 20（纯 NumPy）。

### 3b. 我的变异

- **脚本**：`evidence/mutate_review.sh`，经锁运行（`lock_batch.sh`），原始输出 `e08-mutations.txt`。
- **隔离副本**：用 `git archive HEAD src tests pyproject.toml examples reports/V9-S5-PHASE1` 导出，再拷入 P253 的 4 个新增或改动文件，以及迟到修补后的 `sandbox.py`、`test_s6_sandbox.py`。副本与实盘的 sha256 一致（`200e212e…`）。
- **确认从副本加载**：`PYTHONPATH=<副本>/src`，并额外加了一项测试 `test_zz_review_origin.py`，在 pytest 进程内断言 `sandbox.__file__` 位于副本。所以基线是 25 项（20+4+1）。

| 变异 | 结果 | 判定 |
|---|---|---|
| N1 加 `__getitem__` 直接调 `_take`，绕过查重和日志 | **存活**（25 passed） | 测试缺口，必修 1 |
| N2 `reveal` 返回迄今全部已揭示的样本 | **存活** | 测试缺口，应修 4 |
| N3 `pick_top` 改回原型的 `np.argsort(-sr)` | **存活** | 测试缺口，必修 2（规模大于 16 时行为不同，见 `e09`） |
| N4 `geo_flags` 不转 float64 | 存活 | 实践上等价：60000 个样本 0 处不同（`e05`） |
| N5 `states()` 返回只读视图 | **存活** | 测试缺口，应修 5 |
| N6 失败的揭示仍把新 id 写进查重集合 | 杀死（`test_failed_label_read_registers_nothing`） | 第一版上存活（`e08a`），迟到修补后的新测试杀死了它 |
| N7 `revealed_pool` 混入最后一个编号 | 存活 | 我的变异设计偏弱：两个测试场景里末号都恰好已揭示（`e11`：`last id revealed after the two rounds: True`） |
| N7b `revealed_pool` 混入最小的未揭示编号 | 杀死（2 项） | 有效 |
| N8 `revealed_pool` 按编号排序，而非揭示顺序 | 杀死 | 有效 |
| N9 撤回迟到的修补 | 杀死（新测试） | 修补有守 |

`e08` 原始输出节选：

    == baseline:
    25 passed in 1.53s
    == N1 a dunder (__getitem__) hands out any sample through _take, bypassing reveal's check and log:
    25 passed in 1.49s
    == N2 reveal returns every sample revealed so far, not just these ids:
    25 passed in 1.48s
    == N3 pick_top uses the prototype argsort (unstable, ties not by id):
    25 passed in 1.69s
    == N4 geo_flags evaluates on the float32 state (no float64 cast):
    25 passed in 1.75s
    == N5 states() returns read-only views of the internal arrays, not copies:
    25 passed in 1.67s
    == N6 a failed reveal (repeat) still marks its new ids as revealed in the lookup set:
    1 failed, 24 passed in 1.49s
    == N7b revealed_pool smuggles in the smallest unrevealed sample once anything was revealed:
    2 failed, 23 passed in 1.52s
    == N9 the late fix reverted: reveal registers ids and log before reading labels:
    1 failed, 24 passed in 1.52s
    == N8 revealed_pool lists samples in id order instead of reveal order:
    1 failed, 24 passed in 1.63s
    == restored:
    25 passed in 1.50s

### 3c. 作者的 10 个变异在最终版本上复跑

作者的 `mutate.sh` 原样运行，没有改动（`e10-author-mutations-rerun.txt`）：基线 24 passed，M1–M10 全部被杀死，还原后 24 passed。作者的结论在最终版本上依然成立。

## 4. 作者报告是否属实

- **SHA256SUMS**：在修补之前，12 项全部与盘上一致（`e01`），但要分别在交付目录和仓库根下核对，见应修 6。修补之后 `sandbox.py`、`test_s6_sandbox.py` 两项 FAILED（`e01b`）。
- **测试数**：修补前 19、4、12 都属实（`e03a`）。最终版本的纯 NumPy 是 20 项，报告已过期（必修 3）。
- **变异**：M1–M10 在第一版上的结果我没有复跑；在最终版本上复跑，全部被杀死（3c）。M5 的分析成立（2a）。
- **卡外两行修补**：理由属实，且两行缺一不可。在隔离副本里跑 `tests/test_cpu_collection.py`，摘要见 `e06-cpu-collection.txt`，完整输出见 `e06-cpu-collection-raw-cp-*.txt`：

  | 副本 | 结果 |
  |---|---|
  | HEAD 原样 | **2 failed, 1 passed** |
  | HEAD 加卡内改动（`sandbox.py`、两个新测试、conftest 一行），不含两行卡外修补 | **2 failed, 1 passed**，同样两项 |
  | 再加两行卡外修补 | **3 passed** |
  | 实盘工作区（最终版） | **3 passed** |

  两项失败的原始断言：

      E       AssertionError: {'unregistered': [], 'registered_but_cpu': ['v9/experiments/test_s5_final_native.py']}
      E           AssertionError: test_s6_epinet_mlx.py
      E           assert 'pytestmark = pytest.mark.native_mlx' in '"""Tests for S6 epinet MLX module (s6/epinet_mlx.py).\n\n...

  - 第一项是 `test_native_module_inventory_is_complete`（`tests/test_cpu_collection.py:109-110` 的 `registered_but_cpu`）；
  - 第二项是 `test_native_modules_carry_native_mark`（`:117`）。
  - 副本要额外包含 `examples/` 和 `reports/V9-S5-PHASE1/`，否则全树收集会因副本不完整多出无关的错误。第一次只导出了 `src tests pyproject.toml`，出现过这种错误，已改正后重跑。
- **小出入**：报告说 epinet「加 1 行」，diff 实为 `+pytestmark = pytest.mark.native_mlx` 加一个空行（`citations.txt` C22）。无实质影响。

## 5. 卡外改动是否合理、有无副作用

- **`tests/conftest.py`**：+1 行，登记新的 native 测试。这是卡内要求。
- **`test_s6_epinet_mlx.py`**：+`pytestmark`。该模块早已登记在 `NATIVE_MODULES`，`_native_reason` 本来就会给它加标记。所以这一行只是满足静态检查，**没有行为变化**。
- **`test_s5_final_native.py:22`** +`pytest.importorskip("mlx.core")`，有行为变化，但可以接受。在模拟「没装 MLX」的环境下只做收集（不加载 MLX），结果见 `e07-s5-native-without-mlx.txt`：

      ===== cp-head, pytest --collect-only -q -rs --native-mlx tests/v9/experiments/test_s5_final_native.py
      3 tests collected in 0.07s
      ===== cp-patch-full, pytest --collect-only -q -rs --native-mlx tests/v9/experiments/test_s5_final_native.py
      SKIPPED [1] tests/v9/experiments/test_s5_final_native.py:22: could not import 'mlx.core': No module named 'mlx' (simulated: MLX not installed)

  分三种情形：
  - **没有 MLX，加 `--native-mlx`**：原来会收集 3 项，再在子进程里失败；现在整个模块跳过。这与其他 native 模块的惯例一致。
  - **默认入口**：
    - 整树收集时，`pytest_ignore_collect` 照旧忽略该文件（`conftest.py:348-350`），`test_default_collection_imports_no_mlx` 通过，没有变化。
    - 只有在默认入口里**显式点名这个文件**时，模块会被导入；导入时第 22 行会在 CPU 入口进程里导入 `mlx.core`（上面无 MLX 模拟中，默认运行也出现了 `SKIPPED ... :22`）。其他在模块顶层导入 MLX 的 native 模块（如 epinet）本来就是这样，不算新问题。
  - **装了 MLX，加 `--native-mlx`**：父进程现在会导入 `mlx.core`，conftest 里自动使用的 `_restore_default_mlx_device_after_test` 会对这 3 项生效（只设默认设备）。子进程以 `-I` 启动、去掉了 `PYTHON*` 环境变量，不受影响。

---

## 证据清单（`evidence/`）

| 文件 | 内容 |
|---|---|
| `citations.txt` | 本报告每处引文对应的 `grep -n`、`sed -n` 原始输出（C1–C28） |
| `e01`、`e01b` | 作者 SHA256SUMS 的核对：修补前、修补后 |
| `e02`、`e03`（`e03a` 为第一版） | 纯 NumPy 测试、native 测试的复跑 |
| `e04` + `leak_probe.py` | 泄漏探针 P1–P10 |
| `e05`（`e05a` 为第一版）+ `equiv_realscale.py` | 全规模等价性、重复状态、物理重算 |
| `e06` 及 3 个 raw 文件 | `test_cpu_collection` 在 HEAD 和各补丁副本上的结果 |
| `e07` + `nomlx_sitecustomize.py` | 无 MLX 环境下 S5 native 测试的收集 |
| `e08`（`e08a` 为第一版）+ `mutate_review.sh` | 我的变异 |
| `e09` + `tie_order_probe.py` | `argsort` 与 `lexsort` 同分顺序的规模阈值 |
| `e10` | 作者变异在最终版本上的复跑 |
| `e11` + `n7_probe.py` | N7 存活原因 |
| `e12` + `lock_batch.sh` | 经锁批次的外壳输出（开始、结束时 `sandbox.py` 的 SHA 一致） |
| `e13` | `geo_flags` 与 `geo_gate` 的逐行机械 diff |
| `e14` + `key_order_probe.py` | 字段顺序 |

## 遵守的运行规则

- 所有导入 MLX 的运行都经 `hold_lock.py artifacts/locks/m0-worker.lock`：两次 native 测试、两次全规模脚本、变异、作者变异复跑、N7 探针。没有遇到锁忙（75）。
- 没有改源码、测试和已有报告。没有写 `artifacts/`，只读了一期权重。
- 没有 stash、checkout、reset，没有提交。
- 隔离副本在会话 scratchpad 下（`cp-head`、`cp-patch-min`、`cp-patch-full`、`cp-mut`），作者脚本自建的副本在 `$TMPDIR`。
- 候选世界只用了探索命名空间 `s6x-cand`，以及我自己的 `s6r-review-leak`，没有碰 `s6p1-*`。