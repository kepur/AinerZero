# S6 MLX 部分非作者复核报告：cells、运行器、重放与复训校验（34a1753）

**结论：建议通过**

复核代理：`gemini-e7a2`（二级执行层，独立非作者环境，与一级主责作者隔离）。
复核对象：提交 `34a1753` 中 MLX 相关核心模块：
- `src/ainerzero/v9/experiments/s6/cells.py`
- `reports/V9-S6-PHASE1/run_s6p1.py`
- `reports/V9-S6-PHASE1/verify_s6p1.py`
- 对应测试：`tests/v9/experiments/test_s6_cells_native.py`、`test_s6_cells_static.py`、`test_s6p1_runner_native.py`、`test_s6_sandbox_native.py`。
设计依据：`reports/V9-S6-DESIGN/DESIGN-r2.md` §2、§3、§5、§6、§7。

---

## 1. 标签隔离（§6 四层）

经代码逐行审计与探针验证，§6 规定的四层标签隔离机制完全成立。

### 1.1 四层隔离逐层核查与代码引用

#### 第一层：未选中样本的结果不存在
候选池 `sandbox.CandidatePool` 在初始化与日常常驻状态下仅持有状态数据（位置 `p`、速度 `v`、柱子 `pil`），绝不预先计算或存储未来的模拟标签。标签模拟与打标仅在显式调用 `reveal(ids)` 时被触发，且仅对被选中的 ID 进行模拟与入库。
`src/ainerzero/v9/experiments/s6/cells.py:120-121`:
```python
def make_candidate_pool(source: dict) -> S.CandidatePool:
    return S.CandidatePool(source, labeller=S.sim_labels, pool_type=L.Pool)
```
`src/ainerzero/v9/experiments/s6/sandbox.py:129-140`:
```python
    def reveal(self, ids) -> Any:
        """Run the sandbox on these candidates (at least one): simulate their outcomes and return exactly
        these samples with labels, grouped by disk count (ascending), in the given order within a group.
        Each id may be revealed once; a repeat (within the call or across calls) raises before anything is
        simulated. If simulating fails, nothing is registered."""
        ids = self._check_new(ids)
        outcomes = self._simulate(ids)
        self._revealed.extend(ids)
        self._revealed_set.update(ids)
        self._outcomes.update(outcomes)
        self._log.append({"call": len(self._log), "ids": list(ids)})
        return self._assemble(ids)
```
在探针 `evidence/probe_label_isolation.py` 验证中，刚创建的 `CandidatePool` 其 `len(cp._outcomes) == 0`，`len(cp._revealed) == 0`，未揭示样本的标签在内存中物理不存在。

#### 第二层：候选的来源丢弃
候选池构造函数 `candidate_source` 从候选世界抽取完互不相同的精确状态后，立即显式执行 `del eps`，丢弃包含接触历史日志的 `Episode` 对象：
`src/ainerzero/v9/experiments/s6/cells.py:94-107`:
```python
def candidate_source(cand_ns: str, k: int, sizes: Sizes = FULL) -> dict[int, dict[str, np.ndarray]]:
    """The candidate states of replicate k (DESIGN-r2 §2): ``sizes.pool`` distinct (world, step) pairs drawn
    without replacement from the replicate's candidate worlds, as exact float64 states with their pillars,
    grouped by disk count and sorted by (world, step). No outcome is computed here; the episodes (whose
    steps carry contact logs) are dropped before returning."""
    eps = candidate_worlds(cand_ns, k, sizes)
    pairs = [(e, t) for e, ep in enumerate(eps) for t in range(len(ep.steps))]
    if sizes.pool > len(pairs):
        raise ValueError(f"only {len(pairs)} states in {len(eps)} worlds, {sizes.pool} wanted")
    pick = np.random.default_rng(pool_seed(cand_ns, k)).choice(len(pairs), sizes.pool, replace=False)
    chosen = sorted((eps[pairs[i][0]].n_disks, pairs[i][0], pairs[i][1]) for i in pick)
    by_n: dict[int, dict[str, list]] = {}
    for n, e, t in chosen:
        s = eps[e].steps[t]
        row = by_n.setdefault(n, {"p": [], "v": [], "pil": []})
        row["p"].append(np.asarray(s.positions, dtype=np.float64))
        row["v"].append(np.asarray(s.velocities, dtype=np.float64))
        row["pil"].append(np.asarray(eps[e].pillars, dtype=np.float64))
    del eps
```
返回给候选池的字典仅包含 NumPy 浮点数组，去除了轨迹上的一切碰撞元数据。

#### 第三层：封印上下文 `sealed()`
挑选函数 `select()` 在封印上下文 `with sealed():` 内执行：
`src/ainerzero/v9/experiments/s6/cells.py:134-156`:
```python
_SEALED = [(W, "physics"), (W, "generate_episode"), (L, "make_pool"), (L, "make_sigma_pool"),
           (A, "train_worlds"), (Mo, "true_physics"), (Mo, "bounce"), (S, "sim_labels"),
           (S.CandidatePool, "_simulate"), (S.CandidatePool, "reveal")]


@contextmanager
def sealed():
    """While open, the simulator, world generation, pool building and the pool's label door raise."""
    saved = [(obj, name, getattr(obj, name)) for obj, name in _SEALED if hasattr(obj, name)]

    def trap(name):
        def _raise(*a, **k):
            raise SealBreach(f"a pick rule reached {name} while selection was sealed")
        return _raise

    for obj, name, _ in saved:
        setattr(obj, name, trap(f"{getattr(obj, '__name__', obj)}.{name}"))
    try:
        yield
    finally:
        for obj, name, f in saved:
            setattr(obj, name, f)
```
`src/ainerzero/v9/experiments/s6/cells.py:280-303`:
```python
def select(arm: str, track: Track, k: int, per: int, cand_ns: str, rng: np.random.Generator | None) -> tuple[np.ndarray, str | None]:
    """The next ``per`` picks of one track. Runs sealed, on the CPU; returns (ids, score digest or None)."""
    prev = mx.default_device()
    mx.set_default_device(mx.cpu)
    try:
        with sealed():
            st = track.cp.states()
            rem = track.cp.remaining()
            if arm in ("R", "T"):
                return S.pick_random(rem, per, rng), None
            if arm == "G":
                return S.pick_geo(S.geo_flags(st), rem, per, rng), None
            if arm == "E":
                score = disagreement(st, [l.model for l in track.learners])
            elif arm == "Z":
                score = closest_pair(st)
            elif arm == "P":
                score = epinet_spread(st, track.learners[0].model)
            else:
                raise ValueError(f"unknown arm {arm!r}")
            return S.pick_top(score, rem, per), score_digest(score)
    finally:
        mx.set_default_device(prev)
```

**关键审查发现（模块属性 vs 预存函数引用）：**
1. `sealed()` 采用动态打桩（`setattr(obj, name, trap)`）。如果恶意代码在进入 `with sealed():` 之前预先将函数对象赋值给局部变量（例如 `saved_fn = W.physics`），在封印内直接调用 `saved_fn(...)` 将绕过模块属性上的陷阱（见 `evidence/probe_label_isolation.out` 中的实测复现）。
2. 然而，系统通过双重防御消除了此风险：
   - 候选池对象的 `cp._labeller` 虽然在封印前初始化绑定了 `sim_labels`，但由于 `sim_labels` 内部是通过 `W.physics(...)` 模块属性访问物理引擎，因此在封印内调用 `cp._labeller` 仍会被 `W.physics` 的陷阱拦截（实测输出：`OK: cp._labeller trapped via internal W.physics lookup`）。
   - 静态 AST 检查（`tests/v9/experiments/test_s6_cells_static.py`）严格扫描了挑选函数树，确保挑选路径中不存在任何对模拟器、世界生成或标签接口的调用、导入或名字引用；并且 `select` 对候选池对象 `cp` 仅允许调用 `states()` 与 `remaining()`。

#### 第四层：T 臂（读真值参照臂）
T 臂挑选与 R 臂完全相同，只在训练已揭示样本时读标签：
`src/ainerzero/v9/experiments/s6/cells.py:78-81`:
```python
def pick_seed(cand_ns: str, arm: str, k: int) -> int:
    """T picks exactly what R picks (it differs only in how it batches what it has); others have their own."""
    return W.derive_seed(cand_ns, "s6-pick", "R" if arm == "T" else arm, k)
```
`src/ainerzero/v9/experiments/s6/cells.py:329-335`:
```python
        for ti, tr in enumerate(tracks):
            tr.cp.reveal(np.array(tr.picks[r], dtype=np.int64))
            pool = tr.cp.revealed_pool()
            for li, lr in enumerate(tr.learners):
                lr.train(pool, sizes.steps, T_COLL_SHARE if arm == "T" else 0.0)
                j = ti if arm == "P" else li
                lr.model.save_weights(str(out / f"r{r}-n{j}.safetensors"))
```
T 臂的挑选种子与 R 臂严格相同，其在挑选阶段完全走 `S.pick_random(rem, per, rng)`，不触碰任何标签。其手工课程（50% 碰撞步）仅施加在当前轮次**已被揭示**的训练池 `pool = tr.cp.revealed_pool()` 上。

---

## 2. 重放与复训

在独立的 smoke 仓库副本中，复制运行器 native 测试做法，实测针对三种真实篡改的拦截能力（见 `evidence/test_tamper_detection.py` 与 `test_tamper_detection.out`）：

1. **改某格某轮的权重**：篡改 `E-r0/r0-n1.safetensors` 末字节。
   - 拦截表现：`run_s6p1.py` 在 `run_eval` 前置的 `verify_cell_dir` 检查中，检测到文件 SHA 与 `cell.json` 记录不一致，抛出 `AssertionError: E-r0/r0-n1.safetensors changed after the cell finished`。
   - 验证防护：`eval` 在读测试分区前直接崩溃中断，未生成 `errors.npz`。

2. **换掉某轮的挑选**：在 `cell.json` 中颠倒第 1 轮挑选列表及揭示日志。
   - 拦截表现：`verify_s6p1.py` 在独立进程中根据保存权重重算挑选，发现重新挑选出的 ID 序列与 `cell.json` 不符，返回 `verify.passed = False` 与 `verify.replay.E-r0.passed = False`。
   - 验证防护：`run_s6p1.py` 捕获 `not R["verify"].get("passed")`，记录 `reason: replay or retraining check failed; the test partition was not read` 并提前返回，测试世界未被生成，`errors.npz` 不存在。

3. **改候选池种子 / 哈希**：篡改 `pools.json` 中记入的候选池 digest。
   - 拦截表现：`verify_s6p1.py` 从种子重新生成候选池并计算哈希，发现与 `pools.json` 不一致，标记 `pools_ok["0"] = False`，判定 `verify.passed = False`。
   - 验证防护：`eval` 终止，完全未触碰测试世界。

代码保证：
`reports/V9-S6-PHASE1/run_s6p1.py:282-289`:
```python
        R["verify"] = independent_verify(a.set, out / "verify.json", deadline)
        R["verify_seconds"] = round(time.monotonic() - t, 1)
        save()
        if not R["verify"].get("passed"):
            R["result"] = {"valid": False, "reason": "replay or retraining check failed; the test partition was not read"}
            save()
            say("verification failed; stopping before the test partition")
            return
```
只有在独立校验进程全通之后，控制流才会继续向下执行到测试世界读取与评测。

---

## 3. 断点续跑与账本

经 `evidence/test_resumption_and_ledger.py` 测试与源码审计确认：

### 3.1 半截的格保留为 `*.aborted-N` 并重做
`reports/V9-S6-PHASE1/run_s6p1.py:156-167`:
```python
        for arm, k in all_cells(cfg):
            d = cell_dir(set_root, arm, k)
            if (d / "cell.json").is_file():
                C.verify_cell_dir(d, cfg["sizes"])
                continue
            if d.exists():
                n = 1
                while d.with_name(f"{d.name}.aborted-{n}").exists():
                    n += 1
                d.rename(d.with_name(f"{d.name}.aborted-{n}"))
                say("kept unfinished cell as", d.with_name(f"{d.name}.aborted-{n}").name)
            todo_by_k.setdefault(k, []).append(arm)
```
若格目录存在但缺少合法完整的 `cell.json`（即由于被杀或异常导致的中断格），运行器自动将残余目录递增重命名为 `*.aborted-N` 予以保存，并将其纳入 `todo_by_k` 从头重新训练。实测在真实历史探索目录中同样观察到了留存的 `E.aborted-1`。

### 3.2 墙钟跨次累计与上限拒绝
`reports/V9-S6-PHASE1/run_s6p1.py:120-128`:
```python
def ledger_used(ledger):
    if not ledger.is_file():
        return 0.0, []
    rows = json.loads(ledger.read_text(encoding="utf-8"))
    used = 0.0
    for r in rows:
        used += r["last_beat"] - r["start"] + (0 if r.get("closed") else DANGLING_CHARGE_S)
    return used, rows
```
`reports/V9-S6-PHASE1/run_s6p1.py:143-146`:
```python
        used, rows = ledger_used(ledger)
        left = cfg["train_cap_s"] - used
        if left <= 0:
            raise GD.GuardError(f"training wall clock used up: {used:.0f} s of {cfg['train_cap_s']:.0f} s")
```
- 若前次调用因异常或强杀未能闭合账本（`closed == False`），累计时长自动加罚 `DANGLING_CHARGE_S = 900` 秒（15 分钟）。
- 累计耗时一旦超出预设 `train_cap_s`，立即抛出 `GuardError` 拒绝启动新格。

### 3.3 预登记与代码摘要核对
在 `train` 中记录当前代码摘要与预登记哈希：
`reports/V9-S6-PHASE1/run_s6p1.py:148-151`:
```python
        me = {"start": time.time(), "last_beat": time.time(), "closed": False, "cells": [], "prereg_sha256": pre_sha,
              "code_manifest_sha256": manifest_sha(code_manifest()), "git_head": head, "third_party": versions}
        rows.append(me)
        ledger_write(ledger, rows)
```
在 `eval` 中严格比对所有训练账本记录：
`reports/V9-S6-PHASE1/run_s6p1.py:257-261`:
```python
        if registered:     # every training invocation ran the frozen code under this preregistration
            _, rows = ledger_used(set_root / "train-ledger.json")
            code_now = manifest_sha(code_manifest())
            if not rows or any(r["prereg_sha256"] != pre_sha or r["code_manifest_sha256"] != code_now for r in rows):
                raise GD.GuardError("some training ran under a different preregistration or code")
```
任何一次训练使用了不同的预登记文件或发生代码变动，评测环节均拒绝运行。

---

## 4. 分区与 final 守卫

经 `evidence/test_partition_and_final_guards.py` 验证：

### 4.1 分区隔离与注册检查
`reports/V9-S6-PHASE1/run_s6p1.py:64-79`:
```python
def check_partitions():
    """Candidate, probe-candidate, probe and final namespaces are distinct; only final is registered;
    the smoke set touches nothing of S6 phase 1."""
    names = [SETS[s][k] for s in SETS for k in ("cand_ns", "test_ns")]
    if len(set(names)) != len(names):
        raise GD.GuardError(f"namespaces must be distinct: {names}")
    if SETS["final"]["test_ns"] not in W.REGISTERED:
        raise GD.GuardError("the final test partition must be registered in the world module")
    for s, cfg in SETS.items():
        for k in ("cand_ns", "test_ns"):
            ns = cfg[k]
            if ns in W.REGISTERED and not (s == "final" and k == "test_ns"):
                raise GD.GuardError(f"{s}/{k} must not be a registered partition: {ns}")
            if s == "smoke" and not ns.startswith("s6t-"):
                raise GD.GuardError(f"smoke must use stand-in namespaces: {ns}")
```
- 全部命名空间两两互不相交；
- 仅 `s6p1-final` 在 `world.REGISTERED` 保护列表中；
- `smoke` 强制以 `s6t-` 替身命名空间开头，完全不碰真实 `s6p1-*`。

### 4.2 final 守卫与一次性标记写入
`src/ainerzero/v9/experiments/s4/world.py:183-184`:
```python
    if namespace in REGISTERED and not allow_registered:
        raise PermissionError(f"{namespace} is a registered partition; only a registered run may generate it")
```
在 `run_s6p1.py` 的 `run_eval` 中：
1. 校验批准行：`(a.approval or "").strip() == pre["final_approval_line"]`；
2. 校验 `FINAL_READ_ONCE.json` 尚不存在；
3. 先行完成独立重放与复训校验；
4. 校验通过后，调用 `GD.consume_final_read` 写入 `FINAL_READ_ONCE.json`；
5. 只有在标记写入后，才调用 `W.generate_episode(cfg["test_ns"], ..., allow_registered=registered)` 生成 `s6p1-final` 世界。

---

## 5. 评测算术

### 5.1 算术与原型 `explore_s6a.py` 逐字比对
`classify` 逻辑逐字一致：
`src/ainerzero/v9/experiments/s6/cells.py:392-401`:
```python
def classify(ep: W.Episode, t: int) -> np.ndarray:
    """Step kind per disk at step t: 0 disk collision, 1 graze, 2 wall or pillar, 3 free (as S6 exploration)."""
    s = ep.steps[t]
    disk = {i for k, i, j in s.contacts if k == "disk"} | {j for k, i, j in s.contacts if k == "disk"}
    wallp = {i for k, i, j in s.contacts if k in ("wall", "pillar")}
    nxt = ep.steps[t + 1].positions
    d = np.linalg.norm(nxt[:, None] - nxt[None], axis=-1) + np.eye(ep.n_disks) * 99
    return np.array([0 if i in disk else (1 if d[i].min() < 2 * W.RADIUS + 0.3 else (2 if i in wallp else 3))
                     for i in range(ep.n_disks)])
```
对照 `reports/V9-S6-DESIGN/tier1-explore/explore_s6a.py:88-94`，两者的分类规则（0 碰撞、1 擦边、2 墙柱、3 自由）完全一致。

`prepare_world`、`world_counts`、`world_sums` 逻辑比对：
`src/ainerzero/v9/experiments/s6/cells.py:413-433`:
```python
def prepare_world(ep: W.Episode) -> TestWorld:
    T = len(ep.steps) - 1
    P = np.stack([s.positions for s in ep.steps[:T]]).astype(np.float32)
    V = np.stack([s.velocities for s in ep.steps[:T]]).astype(np.float32)
    tgt = np.stack([s.velocities for s in ep.steps[1:T + 1]])
    kinds = np.stack([classify(ep, t) for t in range(T)])
    _, vb = Mo.bounce(P.astype(np.float64), V.astype(np.float64), ep.pillars)
    pil = np.broadcast_to(np.array(ep.pillars, dtype=np.float32), (T, L.N_PILLARS, 3)).copy()
    return TestWorld(P, V, tgt, kinds, np.linalg.norm(vb - tgt, axis=-1), pil)


def world_counts(tw: TestWorld) -> tuple[np.ndarray, float]:
    """(counts [4] of disk-steps per kind, E-B error sum on collision disk-steps)."""
    return np.array([(tw.kinds == c).sum() for c in range(4)], dtype=np.int64), float(tw.eb_err[tw.kinds == 0].sum())


def world_sums(model, tw: TestWorld) -> np.ndarray:
    """[4] next-velocity error sums per kind for one model on one test world (CPU)."""
    _, v, _, _ = model(mx.array(tw.P), mx.array(tw.V), mx.array(tw.pil))
    e = np.linalg.norm(np.array(v, dtype=np.float64) - tw.target, axis=-1)
    return np.array([e[tw.kinds == c].sum() for c in range(4)])
```
经 `evidence/probe_evaluation_arithmetic.py` 数值对齐测试，在相同测试世界和模型上，`cells.py` 的算术结果与 `explore_s6a.evaluate` 在浮点容差范围内完全相等（EXACT MATCH）。

### 5.2 P 臂基础输出评测
`src/ainerzero/v9/experiments/s6/cells.py:215-224`:
```python
def load_model(arm: str, path: str | Path):
    if arm == "P":
        m = E.EpiDynamics()
        m.load_weights(str(path))
        m.z = None
    else:
        m = L.Dynamics("L-int")
        m.load_weights(str(path))
    mx.eval(m.parameters())
    return m
```
在 `load_model` 中，针对 P 臂显式设置了 `m.z = None`。在 `EpiDynamics` 中，当 `z is None` 时，前向推理只运行基础 L-int 网络，不附加 epinet 增量，符合设计稿 §3 规定的“评测单网络基础输出”契约。

---

## 6. 测试能否抓错（变异测试）

在隔离副本（从 `git archive 34a1753` 导出）中设计并执行了 6 个关键变异实验（见 `evidence/test_mutations.py`），全量变异均被对应测试准确拦截击杀：

| 变异编号 | 变异对象及改动 | 目标测试 | 拦截结果 | 错误类型 / 截获表现 |
|---|---|---|---|---|
| **Mutant 1** | `cells.py:select`: 移除 `with sealed():` 上下文 | `test_s6_cells_static.py` | **KILLED** | `AssertionError: assert any(...)`（静态语法树检测未发现 sealed 上下文） |
| **Mutant 2** | `cells.py:pick_seed`: T 臂种子解绑（改用 `arm` 产生不同种子） | `test_s6_cells_native.py` | **KILLED** | `AssertionError: assert recs["T"]... == recs["R"]...`（T 臂挑选与 R 产生分歧） |
| **Mutant 3** | `cells.py:select`: Z 臂在 `select()` 中被赋予反向打分（偏离 `closest_pair`） | `test_s6_cells_native.py` | **KILLED** | `AssertionError: assert recs["Z"]... == S.pick_top(...)`（Z 臂挑选与最近盘不符） |
| **Mutant 4** | `cells.py:load_model`: P 臂评测未将 `m.z` 设为 None | `test_s6_cells_native.py` | **KILLED** | `AssertionError: assert pm.z is None` |
| **Mutant 5** | `cells.py:candidate_source`: 候选池抽样改为有放回抽样 | `test_s6_cells_native.py` | **KILLED** | `AssertionError: duplicate candidate states with 4 disks`（查出重复状态） |
| **Mutant 6** | `verify_s6p1.py:replay_cell`: 绕过重放检查直接返回 `passed=True` | `test_s6p1_runner_native.py` | **KILLED** | `AssertionError: assert not R["verify"]["passed"]`（篡改格逃逸被拒） |

变异测试表明，现有测试套件对标签隔离、各臂挑选一致性、打分度量、模型加载状态以及重放校验机制具备高度敏感的防御能力。

### 6.1 测试设计发现与应修建议（非阻碍项）

在变异测试探索中发现，`tests/v9/experiments/test_s6_cells_native.py::test_z_picks_the_closest_pairs` 的断言结构为：
```python
score = C.closest_pair(cp.states())
...
assert recs["Z"]["tracks"][0]["picks"][1] == S.pick_top(score, rem, TINY.per).tolist()
```
**现象分析**：由于测试里的预期得分 `score` 直接调用了被测模块自身的 `C.closest_pair`，当且仅当 `closest_pair` 函数内部本身的算法发生变异（例如将 `-d.min` 改为 `d.min`）时，单元测试与被测运行时使用了同一套变异函数，导致两者计算出的挑样列表依然相同而逃逸单测检测；而一旦在 `select()` 中使 Z 臂挑选偏离 `closest_pair`（如变异 3），测试即可立即抓获。
**应修建议**：建议后续在 `test_z_picks_the_closest_pairs` 中引入独立的几何真值算法（直接使用双重循环遍历两两欧氏距离取最小值的独立实现作为断言参考），以实现完全正交的测试 Oracle，消除同源自证漏洞。

---

## 7. 汇总与建议

本次非作者复核覆盖了提交 `34a1753` 中关于 S6 MLX 模块的全部 6 项复核点。
经代码静态结构审计、独立探针构造、异常/篡改拦截实测以及全量变异测试，证实：
1. 候选池去重与揭示时模拟机制彻底排除了未选中标签泄露通道；
2. 静态 AST 与动态封印双重防御确保挑选路径无物理仿真入口；
3. 断点续跑与墙钟惩罚账本健全，残缺格安全重命名；
4. 分区与 final 守卫严密，只读一次标记在测试世界生成前被强制执行；
5. 评测算术与原型严格一致，P 臂基础输出评测落实到位；
6. 测试套件能有效捕获逻辑与数据篡改。

结论：**建议通过**。
