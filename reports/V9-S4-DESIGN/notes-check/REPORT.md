# S4 第一阶段设计稿「实现补记」与代码逐条对照报告

- **任务 ID**：`ainerzero.V9.P210`
- **复核者**：`gemini-b8k2`（二级执行 agent，非作者独立核对）
- **核对对象**：`reports/V9-S4-DESIGN/DESIGN-r3.md` 末尾「实现补记（2026-11-10，冻结前声明）」（第 308–380 行）
- **依据代码**：提交 `c1a91fb`
  - `reports/V9-S4-PHASE1/run_s4p1.py`
  - `reports/V9-S4-PHASE1/make_prereg.py`
  - `reports/V9-S4-PHASE1/verify_replay.py`
  - `src/ainerzero/v9/experiments/s4/analysis.py`
  - `src/ainerzero/v9/experiments/s4/learned_mlx.py`
  - `src/ainerzero/v9/experiments/s4/metrics.py`
  - `src/ainerzero/v9/experiments/s4/world.py`
  - `reports/V9-S4-PHASE1/impl-review-r2-recheck/REPORT.md`
- **核对结论**：**建议通过（通过，0 项必修）**

---

## 一、结论摘要

1. **逐条对照吻合**：将设计稿「实现补记」拆解为 27 项明确陈述，与工程代码逐字逐行核对，**27 项全部一致（0 项不一致，0 项代码中找不到）**。
2. **r2-recheck 第 5 项文档要求全部落实**：上一轮复核者要求的「新预留规则」、「`complete` 合法性门」、「重放范围扩大」三项，均已完整、准确地写进补记对应章节中。
3. **无夸大 / 说过头之辞**：补记对运行时检查与离线测试边界的表述客观求实，例如明确指出「格数本身由运行器测试卡住，final 应核对 5 × 24 = 120 个格，独立复算时要核对这个数」，并主动声明近失份额只基于模拟器训练标签、确定性门依赖落盘权重等实际边界，不存在代码未强制却宣称强制的夸大保证。

---

## 二、逐条对照核验表

| 序号 | 主题 / 模块 | 补记原文（逐字复制） | 代码依据（文件路径与行号，逐字复制那一行） | 对照结论 | 核查说明 |
|:---:|:---|:---|:---|:---:|:---|
| 1 | 训练设备 | `训练在本机 MLX 的 GPU（Metal）上依次进行，评测、校验和重放都在 CPU 上。§7 写的「本机 MLX CPU」按此更正：仍是本机、不付费、不用云。` | `reports/V9-S4-PHASE1/run_s4p1.py:141`<br>`    mx.set_default_device(mx.gpu)`<br>`reports/V9-S4-PHASE1/run_s4p1.py:173`<br>`    mx.set_default_device(mx.cpu)`<br>`reports/V9-S4-PHASE1/verify_replay.py:31`<br>`    mx.set_default_device(mx.cpu)`<br>`reports/V9-S4-PHASE1/make_prereg.py:80`<br>`                    "device": "local MLX GPU for training, CPU for evaluation", "cloud": False, "paid": False},` | 一致 | `train_all` 显式设为 GPU，训练完成后切换为 CPU，评测进程与重放脚本均显式限定在 CPU。 |
| 2 | 可复现性与重放 | `第九轮按第六轮的写法重训，D、HF 与第六轮在四位小数上相同。确定性门只从落盘权重重放跟踪，不依赖训练能否逐位复现。` | `reports/V9-S4-PHASE1/verify_replay.py:37`<br>`        net = L.load(base_arm(name), str(run / rel))` | 一致 | `verify_replay.py` 严格从落盘的 `.safetensors` 文件加载权重并进行重放推断，确定性检验独立于训练过程的位级复现。 |
| 3 | 训练步数与批大小 | `步数 20000、批 256 由探针确认，写进预登记` | `reports/V9-S4-PHASE1/run_s4p1.py:135`<br>`    return int(pre["training"]["steps"]), int(pre["training"]["batch"])`<br>`reports/V9-S4-PHASE1/make_prereg.py:64`<br>`        "training": {"steps": pr["steps"], "batch": pr["batch"], "lr": 1e-3, "seeds": list(A.SEEDS), "pool": pr["training"]["pools"],` | 一致 | 预登记生成脚本直接读取探针输出的 `steps` 与 `batch`，final 阶段拒绝命令行输入并强制从预登记载入。 |
| 4 | 训练批构成 | `每批一半（COLL_SHARE = 0.5）取自第 1 步有盘—盘接触的样本，其余从同一盘数的样本里均匀取` | `src/ainerzero/v9/experiments/s4/learned_mlx.py:45`<br>`COLL_SHARE = 0.5                # share of each mean-arm batch drawn from samples with a disk contact at step 1`<br>`src/ainerzero/v9/experiments/s4/learned_mlx.py:293`<br>`    k, q = int(round(batch * coll_share)), int(round(batch * near_share))`<br>`src/ainerzero/v9/experiments/s4/learned_mlx.py:304`<br>`        parts.append(rng.integers(0, int(sizes[j]), batch - sum(len(x) for x in parts)))` | 一致 | 采样逻辑中计算 `k = round(batch * 0.5)`，接触样本取 `k` 个，其余槽位从该盘数桶中均匀抽取。 |
| 5 | 近失份额 | `0（第七轮试过 0.25、0.33，没有帮助）`，`近失的距离与 HF 的擦边定义相同（2R + 0.3）。只读训练池的模拟器标签，不读评测数据；但它是照着评测指标的定义配训练分布，在此声明` | `src/ainerzero/v9/experiments/s4/learned_mlx.py:46`<br>`NEAR_SHARE = 0.0                # share drawn from near misses: no disk contact at step 1, a pair ending it within NEAR_GAP`<br>`src/ainerzero/v9/experiments/s4/learned_mlx.py:47`<br>`NEAR_GAP = 2 * RADIUS + 0.3     # centre distance after step 1 that counts as a near miss` | 一致 | `NEAR_SHARE` 明确设为 0.0，`NEAR_GAP` 取值与 `metrics.py:23` 的 `GRAZE_MARGIN = 0.3`（间距 `2R + 0.3`）定义完全吻合。 |
| 6 | 损失各项权重 | `一步、五步、十步三项为 10、1、1（ROLLOUT_WEIGHTS）；接触头的交叉熵权重 0.1` | `src/ainerzero/v9/experiments/s4/learned_mlx.py:42`<br>`ROLLOUT = (1, 5, 10)`<br>`src/ainerzero/v9/experiments/s4/learned_mlx.py:43`<br>`ROLLOUT_WEIGHTS = (10.0, 1.0, 1.0)  # 1-, 5-, 10-step terms; the 1-step term is weighted up (exploration round 9)`<br>`src/ainerzero/v9/experiments/s4/learned_mlx.py:44`<br>`CONTACT_WEIGHT = 0.1`<br>`src/ainerzero/v9/experiments/s4/learned_mlx.py:255`<br>`            loss = loss + CONTACT_WEIGHT * (bce * off).sum() / mx.maximum(off.sum() * p.shape[0], 1)` | 一致 | 滚动损失加权矩阵与接触分类头权重定义与计算完全一致。 |
| 7 | 梯度裁剪 | `全局范数 10` | `src/ainerzero/v9/experiments/s4/learned_mlx.py:48`<br>`CLIP = 10.0                     # global gradient-norm clip`<br>`src/ainerzero/v9/experiments/s4/learned_mlx.py:346`<br>`        grads, norm = optim.clip_grad_norm(grads, max_norm=CLIP)` | 一致 | 全局范数裁剪常数定为 10.0，每步梯度更新前调用 `clip_grad_norm`。 |
| 8 | 学习率 | `1e-3，恒定，不衰减（第八轮的余弦衰减没有帮助）` | `src/ainerzero/v9/experiments/s4/learned_mlx.py:49`<br>`LR_END = None                   # None: constant learning rate; a number: cosine decay to it over the training steps`<br>`src/ainerzero/v9/experiments/s4/learned_mlx.py:308`<br>`def train(arm: str, pool: Pool, *, steps: int, batch: int, seed: int, lr: float = 1e-3,`<br>`src/ainerzero/v9/experiments/s4/learned_mlx.py:339`<br>`    opt = optim.Adam(learning_rate=lr if LR_END is None else optim.cosine_decay(lr, steps, LR_END))` | 一致 | `LR_END` 为 `None`，默认学习率 1e-3 恒定生效。 |
| 9 | 消息宽度 | `64（第八轮的 128 略好，但第九轮的一步加权已够过门槛，不再加宽）` | `src/ainerzero/v9/experiments/s4/learned_mlx.py:37`<br>`MSG = 64`<br>`src/ainerzero/v9/experiments/s4/learned_mlx.py:99`<br>`            self.msg1 = nn.Linear(pin, MSG)`<br>`src/ainerzero/v9/experiments/s4/learned_mlx.py:100`<br>`            self.msg2 = nn.Linear(MSG, MSG)` | 一致 | 图网络对间交互消息层宽度严格设为 64。 |
| 10 | 方向软化 | `dp / √(|dp|² + 0.01²)`，`接触距离处模长仍大于 0.999` | `src/ainerzero/v9/experiments/s4/learned_mlx.py:50`<br>`EPS_DIR = 0.01                  # softening of the pair direction in L-int-c: bounded at coincident disks`<br>`src/ainerzero/v9/experiments/s4/learned_mlx.py:118`<br>`            e = dp / mx.sqrt((dp ** 2).sum(-1, keepdims=True) + EPS_DIR ** 2)` | 一致 | 软化因子为 0.01；两盘接触时中心距离为 0.6，模长为 0.6/√(0.36+0.0001) ≈ 0.99986 > 0.999。 |
| 11 | 非有限即停 | `损失或梯度非有限时，在更新参数之前停下并报错`，`不跳过、不悄悄改写` | `src/ainerzero/v9/experiments/s4/learned_mlx.py:348-350`<br>`        if not (np.isfinite(float(loss)) and np.isfinite(float(norm))):`<br>`            raise FloatingPointError(f"{arm} seed {seed}: non-finite loss or gradient at step {t}")`<br>`        opt.update(model, grads)` | 一致 | 在调用 `opt.update` 之前立即执行 `np.isfinite` 断言，出现非有限值立即抛出 `FloatingPointError` 中断。 |
| 12 | 单格时限 | `600 秒，在训练循环里检查，超时即失败`，`§7 的「每格 ≤ 10 分钟」由此强制` | `reports/V9-S4-PHASE1/run_s4p1.py:52`<br>`CELL_LIMIT_S = 600`<br>`src/ainerzero/v9/experiments/s4/learned_mlx.py:352-353`<br>`        if time_limit is not None and time.monotonic() - started > time_limit:`<br>`            raise TimeoutError(f"{arm} seed {seed}: over the {time_limit:g} s cell limit at step {t} of {steps}")`<br>`reports/V9-S4-PHASE1/run_s4p1.py:164-165`<br>`            except TimeoutError as exc:`<br>`                raise GD.GuardError(f"training cell over its limit: {exc}") from exc` | 一致 | 单格上限 600 秒由循环内 step 级时间戳核查，超时抛出 `TimeoutError` 并被运行器转为 `GuardError` 拒绝后续执行。 |
| 13 | 扰动细节 | `扰动后位置裁剪进场地；丢盘后至少保留两个盘` | `src/ainerzero/v9/experiments/s4/learned_mlx.py:180-181`<br>`    if keep.sum() < 2:`<br>`        keep[:2] = True`<br>`src/ainerzero/v9/experiments/s4/learned_mlx.py:187`<br>`    pos = np.clip(pos, RADIUS, ARENA - RADIUS)` | 一致 | 丢盘过滤后保底至少保留前两个盘；位置用 `np.clip` 截断在 `[RADIUS, ARENA - RADIUS]`。 |
| 14 | 1/8 数据格 | `train 的前 50 个世界，样本数为全量的 1/8，步数相同` | `reports/V9-S4-PHASE1/run_s4p1.py:51`<br>`EIGHTH = 8`<br>`reports/V9-S4-PHASE1/run_s4p1.py:144`<br>`    eighth = L.make_pool(train_eps[: max(1, len(train_eps) // EIGHTH)], cfg["pool"] // EIGHTH, np.random.default_rng(W.derive_seed(ns, "pool-e8")), W.physics)`<br>`reports/V9-S4-PHASE1/run_s4p1.py:162`<br>`net, log = L.train(WK.base_arm(name), eighth if arm.endswith("-e8") else pool, steps=steps, batch=batch, seed=s,` | 一致 | 400 个世界的前 1/8 即 50 个世界，池容量缩小为 1/8（30000），训练步数 `steps` 保持不变。 |
| 15 | L-int-σ 模型 | `均值取同种子训练好的 L-int 并冻结，只训方差头；样本是加了可见轨迹噪声的真值对下一步真值；步数与均值臂相同` | `reports/V9-S4-PHASE1/run_s4p1.py:160`<br>`                    net, log = L.train("L-int-s", sigma, steps=steps, batch=batch, seed=s, mean_model=nets[f"L-int#{s}"], time_limit=CELL_LIMIT_S)`<br>`src/ainerzero/v9/experiments/s4/learned_mlx.py:328-331`<br>`        model.load_weights(list(tree_flatten(mean_model.parameters())), strict=False)`<br>`        model.freeze()`<br>`        model.var1.unfreeze()`<br>`        model.var2.unfreeze()`<br>`src/ainerzero/v9/experiments/s4/learned_mlx.py:236-240`<br>`        pos = np.clip(s.positions + rng.normal(0, VISIBLE_SIGMA[0], s.positions.shape), RADIUS, ARENA - RADIUS)`<br>`        vel = s.velocities + rng.normal(0, VISIBLE_SIGMA[1], s.velocities.shape)`<br>`        d["tp"].append(nxt.positions); d["tv"].append(nxt.velocities)` | 一致 | 均值权重严格继承并冻结，方差头解冻训练；样本为真值加 `VISIBLE_SIGMA` 对应下一步真值标签。 |
| 16 | 运行器计时起止点 | `运行分两段计时，都写进运行报告：`<br>`- pre_eval_seconds：从脚本启动到标记位置之前，含启动检查、生成训练世界、样本池、18 个训练格、校准参照；`<br>`- post_marker_seconds：从标记之后到冻结清单复查之后，含生成评测世界、跟踪评测、写文件、学生视图检查、标签与重放校验、门的判定。` | `reports/V9-S4-PHASE1/run_s4p1.py:261`<br>`    t0 = time.monotonic()`<br>`reports/V9-S4-PHASE1/run_s4p1.py:298`<br>`        R["pre_eval_seconds"] = round(time.monotonic() - t0, 1)       # start-up, train worlds, pools, training, references`<br>`reports/V9-S4-PHASE1/run_s4p1.py:310`<br>`        t_post = time.monotonic()                                          # everything from here on is what the reserve must cover`<br>`reports/V9-S4-PHASE1/run_s4p1.py:358`<br>`        R["post_marker_seconds"] = round(time.monotonic() - t_post, 1)    # evaluation worlds, evaluation, files, checks, gates` | 一致 | `pre_eval_seconds` 起自脚本入口 `t0` 止于标记写入前；`post_marker_seconds` 起自标记写入后 `t_post`，止于末次清单复核与判定全部完成。两段覆盖内容完全吻合。 |
| 17 | 评测预留公式 | `评测预留 = ⌈探针的 post_marker_seconds × 4 × 1.5⌉。4 是 final 与探针的世界数之比（300 对 75），1.5 是余量。只按评测本身的耗时算会漏掉世界生成、写文件和校验。` | `reports/V9-S4-PHASE1/make_prereg.py:44`<br>`    scale = sum(A.SIZES["final"]) / sum(A.SIZES["probe"])`<br>`reports/V9-S4-PHASE1/make_prereg.py:45`<br>`    eval_reserve = math.ceil(1.5 * scale * pr["post_marker_seconds"])`<br>`src/ainerzero/v9/experiments/s4/analysis.py:53`<br>`SIZES = {"probe": (50, 25), "final": (200, 100)}` | 一致 | `scale = (200+100)/(50+25) = 300/75 = 4.0`，`math.ceil(1.5 * scale * pr["post_marker_seconds"])` 精确计算并落入预登记。 |
| 18 | 标记前墙钟检查 | `写下 final 只读一次标记之前，剩余墙钟必须不少于评测预留，否则在标记之前失败，这一次读取不算用掉。` | `reports/V9-S4-PHASE1/run_s4p1.py:303-305`<br>`            reserve = float(pre["budget"]["eval_reserve_s"])`<br>`            if deadline.left() < reserve:`<br>`                raise GD.GuardError(f"only {deadline.left():.0f} s left, the evaluation needs {reserve:.0f} s: the final read is not spent")`<br>`reports/V9-S4-PHASE1/run_s4p1.py:307`<br>`            GD.consume_final_read(lock, FINAL_MARKER, a.approval, pre["final_approval_line"], prereg_sha256=pre_sha, expected_lock=LOCK)` | 一致 | 墙钟余量检查在第 304 行执行，先于第 307 行的 `consume_final_read` 标记写入。时间不足直接报错退出，不消耗 final 标记。 |
| 19 | 预登记超时拦截 | `探针的 pre_eval_seconds × 1.2 加评测预留超过 4 小时（14400 秒），make_prereg.py 拒绝冻结。` | `reports/V9-S4-PHASE1/make_prereg.py:23`<br>`HARD_LIMIT_S = 4 * 3600`<br>`reports/V9-S4-PHASE1/make_prereg.py:46-48`<br>`    train_s = pr["pre_eval_seconds"]                     # start-up, train worlds, pools, training, references`<br>`    if 1.2 * train_s + eval_reserve > HARD_LIMIT_S:`<br>`        raise SystemExit(f"预计超出硬上限：训练约 {train_s:.0f} 秒，评测预留 {eval_reserve} 秒")` | 一致 | 硬上限设为 14400 秒，若 `1.2 * train_s + eval_reserve > 14400` 则立即拦截拒绝冻结。 |
| 20 | 逐世界追加落盘 | `评测每完成一个世界就追加落盘，超时后已算完的部分可以复算。` | `reports/V9-S4-PHASE1/run_s4p1.py:227`<br>`    fh = partial.open("x", encoding="utf-8")`<br>`reports/V9-S4-PHASE1/run_s4p1.py:241-242`<br>`                fh.write(json.dumps({"index": i, "record": results[i]}, ensure_ascii=False, sort_keys=True) + "\n")`<br>`                fh.flush()` | 一致 | `evaluate_parallel` 每完成一个任务立即将序列化行写入 `worlds.partial.jsonl` 并调用 `flush()`。 |
| 21 | 记录完整性门 | `- **记录完整**（complete）：主评测与外推落盘的记录条数必须分别等于登记的世界数（final 为 200、100，探针为 50、25）。少一条就整个实验无效，全部门作废。` | `src/ainerzero/v9/experiments/s4/analysis.py:250-251`<br>`        "complete": {"passed": len(main) == n_main and len(extrap) == n_extrap, "main": len(main), "extrap": len(extrap),`<br>`                     "registered": [n_main, n_extrap]},`<br>`src/ainerzero/v9/experiments/s4/analysis.py:263`<br>`    valid = all(v["passed"] for v in lg.values())`<br>`src/ainerzero/v9/experiments/s4/analysis.py:288-290`<br>`    if not valid:`<br>`        for k in g:`<br>`            g[k] = dict(g[k], passed=False, void="legality failed")` | 一致 | 记录条数少于登记值时，`complete` 项判定为 `False`，导致 `valid` 为 `False`，后续所有门均被标记为 `passed=False, void="legality failed"`。 |
| 22 | 地板门无定义 | `- **地板门**：E-CV、E-B、E-P 任何一个在有碰撞事件上的准确率无定义（没有有碰撞事件）时，地板门判不过，不报错。` | `src/ainerzero/v9/experiments/s4/analysis.py:239-241`<br>`    acc = {a: acc_of(main, a)["value"] for a in ("E-CV", "E-B", "E-P")}`<br>`    missing = [a for a, v in acc.items() if v is None]`<br>`    floor = not missing and acc["E-CV"] < acc["E-B"] < acc["E-P"]`<br>`src/ainerzero/v9/experiments/s4/analysis.py:249`<br>`        "floor": {"passed": bool(floor), "acc": acc, **({"undefined": missing} if missing else {})},` | 一致 | 若无事件导致 `acc` 返回 `None`，`missing` 非空，`floor` 判定为 `False` 并记录 `undefined` 字段，不抛异常。 |
| 23 | 确定性重放范围 | `- **确定性门的范围**：`<br>`  - 重放主评测的前 3 个世界和外推的前 2 个世界；`<br>`  - 每个世界重放 24 个格：全部 18 个学习格，加 E-B、E-P 各 3 个种子（它们是 C 的分母）；`<br>`  - 每个格比对轨迹分配的摘要，并用重放得到的分配和真值编号重算每个事件的对错，与落盘的逐个比对；`<br>`  - 一个格都没核对时判不过；`<br>`  - 真值编号只写进 replay.json 供校验进程用，学生跟踪器读不到；`<br>`  - 校验脚本按 replay.json 里的世界和权重计数，格数本身由运行器测试卡住。final 应核对 5 × 24 = 120 个格，独立复算时要核对这个数。` | `reports/V9-S4-PHASE1/run_s4p1.py:55`<br>`REPLAY_WORLDS = {"main": 3, "extrap": 2}`<br>`reports/V9-S4-PHASE1/verify_replay.py:22`<br>`HAND = ("E-B", "E-P")`<br>`reports/V9-S4-PHASE1/verify_replay.py:36-41`<br>`    for name, rel in rep["weights"].items():`<br>`        net = L.load(base_arm(name), str(run / rel))`<br>`        models[name] = L.as_process_model(net, with_variance=base_arm(name) == "L-int-s")`<br>`    for arm in HAND:                       # E-B and E-P are the denominator of C: replay them too`<br>`        for s in A.SEEDS:`<br>`            models[f"{arm}#{s}"] = Mo.HAND_MODELS[arm]`<br>`reports/V9-S4-PHASE1/verify_replay.py:53`<br>`            if A.ids_digest(ids) != rec["ids_sha256"][cell.key]:`<br>`reports/V9-S4-PHASE1/verify_replay.py:56-58`<br>`            at = [dict(zip(t, np.asarray(i).tolist())) for t, i in zip(w["truth_ids"], ids)]`<br>`            correct = [int(at[a][k] == at[b][k]) for k, a, b, _ in rec["events"]]`<br>`            if correct != rec["reid"][cell.key]:`<br>`reports/V9-S4-PHASE1/verify_replay.py:60-61`<br>`    expected = len(rep["worlds"]) * len(models)`<br>`    print(json.dumps({"passed": expected > 0 and checked == expected and not bad, "checked": checked, "mismatches": bad[:20]}))` | 一致 | 世界选取为 3+2=5 个；模型为 18+6=24 个，总比对格数 5×24=120 格；摘要与逐事件对错双重核对；未核对或不全时判不过。 |
| 24 | 统计与无定义传播 | `- 比值（D、HF、C）和差值只要分母不为正就是无定义。点估计无定义时没有值；任何一次重采样无定义时不给区间。需要值或区间的门一律按不过算。`<br>`- 这比 §5 更保守：§5 没有说重采样无定义时怎么办。` | `src/ainerzero/v9/experiments/s4/metrics.py:107`<br>`        return np.where(den > 0, num / np.where(den > 0, den, 1.0), np.nan)`<br>`src/ainerzero/v9/experiments/s4/metrics.py:87-92`<br>`    if not np.isfinite(point) or len(boot) < n_boot:`<br>`        return {"value": float(point) if np.isfinite(point) else None, "ci_low": None, "ci_high": None,`<br>`                "bonf_low": None, "bonf_high": None, "n_worlds": int(n_w), "n_boot_finite": int(len(boot))}`<br>`src/ainerzero/v9/experiments/s4/analysis.py:270-272`<br>`    def ok(*conds):`<br>`        return bool(all(x is not None for x in conds[::2]) and all(conds[1::2]))` | 一致 | `_ratio` 遇 `den <= 0` 返回 NaN，`bootstrap` 在任一重采样非有限时拒绝给出置信区间（`ci_low: None`），`analysis.py` 中 `ok()` 判定直接为 `False`。 |
| 25 | 学生视图白名单 | `- 全部学生跟踪器经 W.student_view 读检测，返回字段超出白名单 {t, agent, detections} 就报错。` | `src/ainerzero/v9/experiments/s4/world.py:217`<br>`STUDENT_KEYS = frozenset({"t", "agent", "detections"})`<br>`src/ainerzero/v9/experiments/s4/analysis.py:124-125`<br>`    if any(set(v) != W.STUDENT_KEYS for v in views):`<br>`        raise RuntimeError("the student view has fields outside the whitelist")`<br>`reports/V9-S4-PHASE1/run_s4p1.py:195`<br>`    keys_ok = W.STUDENT_KEYS == {"t", "agent", "detections"} and all(set(W.student_view(s)) == W.STUDENT_KEYS for ep in eps for s in ep.steps)` | 一致 | 白名单定义为 `{"t", "agent", "detections"}`，数据读取入口与运行器启动检查两道关卡均强制断言此集合。 |
| 26 | 未来帧变异条件 | `合法性门的未来帧变异：截点之后每步丢掉最后一个检测、其余平移 0.5。三个条件都要满足：`<br>`- 截点之前的分配不变；`<br>`- 截点之后跟踪器消费的是变异后的列表：返回的步数和每步的编号数都与变异后的列表一致；`<br>`- 截点之后的编号确有变化：在两次运行共有的检测上比较（对齐前缀，analysis.mutation_row）。只读列表长度的跟踪器凭长度差过不了这一条。` | `src/ainerzero/v9/experiments/s4/analysis.py:132`<br>`    return [d if t <= cut else d[:-1] + 0.5 for t, d in enumerate(dets)]`<br>`src/ainerzero/v9/experiments/s4/analysis.py:142-144`<br>`    return {"prefix_equal": all(np.array_equal(x, y) for x, y in zip(a[: cut + 1], b[: cut + 1])),`<br>`            "consumed": len(b) == len(mut) and all(len(y) == len(d) for y, d in zip(b, mut)),`<br>`            "suffix_changed": any(not np.array_equal(np.asarray(x)[: len(y)], y) for x, y in zip(a[cut + 1:], b[cut + 1:]))}`<br>`reports/V9-S4-PHASE1/run_s4p1.py:205`<br>`    ok = keys_ok and rows and all(r["prefix_equal"] and r["consumed"] and r["suffix_changed"] for r in rows)` | 一致 | 变异规则严格为丢弃末尾并平移 0.5；判定同时要求 `prefix_equal`、`consumed` 与对齐共有前缀比较的 `suffix_changed`。 |
| 27 | 未来帧变异范围 | `检查用 E-P 和 L-int 种子 1 两个跟踪器，各跑主评测的前 2 个世界，截点在第 150 步。` | `reports/V9-S4-PHASE1/run_s4p1.py:56`<br>`STUDENT_WORLDS, STUDENT_CUT = 2, 150`<br>`reports/V9-S4-PHASE1/run_s4p1.py:196`<br>`    models = {"E-P": Mo.true_physics, "L-int#1": L.as_process_model(nets["L-int#1"])}`<br>`reports/V9-S4-PHASE1/run_s4p1.py:198`<br>`    for ep in eps[:STUDENT_WORLDS]:`<br>`reports/V9-S4-PHASE1/run_s4p1.py:340`<br>`        st = student_check([ep for kind, ep in eval_eps if kind == "main"], nets)` | 一致 | 明确指定 E-P 与 L-int#1 两个模型，截点固定在第 150 步，在主评测前 2 个世界上执行变异。 |

---

## 三、r2-recheck 第 5 项文档要求专项核查

在上一轮非作者复核报告 `reports/V9-S4-PHASE1/impl-review-r2-recheck/REPORT.md` 第 5 项中，复核者明确提出了如下文档修改要求：
> **文档要求：** `DESIGN-r3.md` 的「实现补记」仍然写着旧规则（「评测与校验耗时 × 4 × 1.5」），也没有声明新的 `complete` 合法性项和重放范围的扩大。冻结之前要改。

对照当前 `DESIGN-r3.md` 末尾补记核查结果如下：

1. **新预留规则（两段计时与预留计算）**：
   - 补记已在「运行器的墙钟规则」小节中重写，明确界定 `pre_eval_seconds` 与 `post_marker_seconds` 的起止与包含操作，并将评测预留公式更新为 `⌈探针的 post_marker_seconds × 4 × 1.5⌉`。
   - 判定：**已落实**。
2. **`complete` 记录完整性门**：
   - 补记已在「合法性门的补充」小节中明确声明：`记录完整（complete）：主评测与外推落盘的记录条数必须分别等于登记的世界数（final 为 200、100，探针为 50、25）。少一条就整个实验无效，全部门作废。`
   - 判定：**已落实**。
3. **确定性重放范围扩大**：
   - 补记已在「合法性门的补充」小节中全面声明：不仅重放 18 个学习格，还加入作为 C 分母的 E-B、E-P 各 3 个种子（共 24 格/世界），重放世界扩大为主评测 3 个加外推 2 个（共 5 个世界，合计 120 格），并用真值编号重新逐个校验事件对错。
   - 判定：**已落实**。

**专项结论**：复核者要求的 3 项文档补修全部高质量落实，表述与现行代码实现严丝合缝。

---

## 四、「说过头 / 夸大承诺」审计

经全面推敲补记中的所有自然语言定性陈述与边界断言，未发现任何夸大或未经代码强制的保证：

1. **测试卡住 vs 运行时检查区分清晰**：
   - 补记原文明确写道：`校验脚本按 replay.json 里的世界和权重计数，格数本身由运行器测试卡住。final 应核对 5 × 24 = 120 个格，独立复算时要核对这个数。`
   - 代码中 `verify_replay.py:60` 确实按载入的模型与世界乘积计算期望值，而在测试中则强制断言 120 格。补记不仅没有掩盖这一机制，反而主动将其归为「由测试卡住，复算时核对」，体现了诚实严谨的科学态度。
2. **训练分布与评测指标的真实关系坦承说明**：
   - 补记在近失份额为 0 的说明中，主动澄清：`近失的距离与 HF 的擦边定义相同（2R + 0.3）。只读训练池的模拟器标签，不读评测数据；但它是照着评测指标的定义配训练分布，在此声明`。主动揭示归纳偏置来源，无任何信息隐瞒。
3. **统计保守性主动说明**：
   - 补记明确指出：`这比 §5 更保守：§5 没有说重采样无定义时怎么办`。代码实现中的无定义传播机制（任何一次重采样无定义即拒绝给出区间）确实严格收紧，杜绝了宽松放行。
4. **单格超时与非有限检查真实落地**：
   - 补记所称的「每格 ≤ 10 分钟在训练循环里检查」、「非有限即停在更新参数之前停下报错」，在 `learned_mlx.py` 中均有对应的即时断言与抛错代码，不存在伪装的摆设守卫。

---

## 五、复核裁定

- **裁定结论**：**建议通过（RECOMMEND_ACCEPT）**
- **必修项**：0 项
- **应修项 / 建议**：无。设计稿补记与提交 `c1a91fb` 的代码实现逐字逐行高度一致，符合冻结前非作者核对的所有要求。
