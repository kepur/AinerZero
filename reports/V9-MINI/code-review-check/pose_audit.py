"""一级核对 A27 的 F-03/F-04：地图智能体把错误位姿写进地图、把错误事件写进记忆的频率。

只读：用真值做事后比对，不改源码。主地图坐标系与真值只差一个平移（指南针朝向是绝对的），
平移量取前缀第一帧。每次 _advance 之后、不在迷路状态时，比对主地图位姿与真值；
回合结束时比对主地图上已知格与真值格、事件记忆与真值动力学。

用法：.venv/bin/python reports/V9-MINI/code-review-check/pose_audit.py --world m2 --seed 0 [--eval-seed0 N --eval-layouts 30]
"""
import argparse, collections, fcntl, json, sys
from pathlib import Path

import numpy as np

from ainerzero.v9.mini import data as D, evaluate as E, mapagent as MA, residual as R, world as W
from ainerzero.v9.mini.agents import Episode

ROOT = Path(__file__).resolve().parents[3]


class Audit(MA.MapAgent):
    def setup(self, offset):
        self.ox, self.oy = offset
        self.truth_q = collections.deque()
        self.st = collections.Counter()
        self._ok_prev = True

    def _ok(self, p, t):
        return (p[0] + self.ox, p[1] + self.oy, p[2]) == t

    def _advance(self, a, view, head):
        t = self.truth_q.popleft()
        was_lost = self.frag is not None
        known0 = None
        ok_before = None
        if not was_lost:
            before = self.main.pose
            ok_before = self._ok_prev
            pred = self._next(self.main, before, a, planning=False, use_memory=self.memory)
            known0, bad0, _ = self.main.check(view, pred)
            if bad0 == 0:
                src = "pred"
            elif a == W.FORWARD and self._ray_candidate(view, before) is not None:
                src = "ray"
            else:
                src = "open_frag"
        else:
            src = "lost"
        super()._advance(a, view, head)
        if self.frag is not None:
            self.st["lost_steps"] += 1
            if src == "open_frag":
                self.st["open_frag"] += 1
            return
        ok = self._ok(self.main.pose, t)
        if was_lost:
            src = "merge"
        self.st[f"src_{src}"] += 1
        if ok_before is not False and not ok:
            self.st[f"becomes_wrong_{src}"] += 1
        if ok_before is False and ok:
            self.st[f"becomes_right_{src}"] += 1
        self._ok_prev = ok
        self.st["tracked_steps"] += 1
        self.st["wrong_pose_steps"] += int(not ok)
        if not was_lost and known0 == 0 and bad0 == 0:
            self.st["accept_no_evidence"] += 1
            self.st["accept_no_evidence_wrong"] += int(not ok)
        if was_lost:
            self.st["merges"] += 1
            self.st["merges_wrong"] += int(not ok)


def audit_map(ag, layout):
    m = ag.main.map
    ys, xs = np.nonzero(m != -1)
    tx, ty = xs + ag.ox, ys + ag.oy
    s = layout.cfg.size
    inb = (tx >= 0) & (tx < s) & (ty >= 0) & (ty < s)
    wrong = int((m[ys[inb], xs[inb]] != layout.grid[ty[inb], tx[inb]]).sum()) + int((~inb).sum())
    mem_wrong = 0
    for p, q in ag.trans_mem.items():
        tp = (p[0] + ag.ox, p[1] + ag.oy, p[2])
        mem_wrong += int(not (0 <= tp[0] < s and 0 <= tp[1] < s) or W.step(layout, tp, W.FORWARD) != (q[0] + ag.ox, q[1] + ag.oy, q[2]))
    for c, d in ag.portal_mem.items():
        tc = (c[0] + ag.ox, c[1] + ag.oy)
        mem_wrong += int(layout.portal_to.get(tc) != (d[0] + ag.ox, d[1] + ag.oy))
    return {"known_cells": int(len(xs)), "wrong_cells": wrong, "mem_entries": len(ag.trans_mem) + len(ag.portal_mem),
            "mem_wrong": mem_wrong}


def run(ag, layout, task, budget):
    poses = task["prefix_poses"]
    views = [W.ego_view(layout, p) for p in poses]
    c = layout.cfg.size
    ag.setup((poses[0][0] - c, poses[0][1] - c))
    ag.truth_q.extend(poses[1:])
    g = task["goal"]
    ag.reset(Episode(None, views, [p[2] for p in poses], task["prefix_acts"], None, W.ego_view(layout, g), g[2]))
    pre = dict(ag.st)
    pose, succ, steps = task["start"], 0, budget
    for t in range(budget):
        if (pose[0], pose[1]) == (g[0], g[1]):
            succ, steps = 1, t
            break
        if ag.last is not None:
            ag.truth_q.append(pose)
        v = W.ego_view(layout, pose)
        a = ag.act(None, v, pose[2])
        pose = W.step(layout, pose, a)
    else:
        succ = int((pose[0], pose[1]) == (g[0], g[1]))
    return {"success": succ, "steps": steps, "kind": task["kind"], "layout_seed": task["layout_seed"],
            "prefix": pre, "all": dict(ag.st), **audit_map(ag, layout)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--world", default="m2")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--eval-seed0", type=int, default=D.EVAL_SEED0)
    ap.add_argument("--eval-layouts", type=int, default=30)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--min-overlap", type=int)
    args = ap.parse_args()
    if args.min_overlap is not None:
        MA.MERGE_MIN_OVERLAP = args.min_overlap
    cfg = W.Config() if args.world == "m1" else W.Config(ice_rooms=2, portals=2)
    fh = open(ROOT / "artifacts/locks/m0-worker.lock", "a+")
    fcntl.flock(fh, fcntl.LOCK_EX)
    seed0 = D.TRAIN_SEED0 + 1000 * args.seed
    rx, ry = R.collect(cfg, 200, 4, 200, seed0, seed=args.seed)
    fms = {"analytic": R.fit("analytic", rx, ry), "gated": R.fit("gated", rx, ry, seed=args.seed)}
    fcntl.flock(fh, fcntl.LOCK_UN)
    tasks = E.make_tasks(cfg, args.eval_layouts, 400, 2, 4, eval_seed0=args.eval_seed0)
    out = {}
    for arm, fm, mem in (("map_analytic", "analytic", False), ("map_hybrid", "gated", True)):
        rows = []
        for ti, task in enumerate(tasks):
            layout = W.make_layout(task["layout_seed"], cfg)
            ag = Audit(cfg, fms[fm], memory=mem, seed=args.seed * 100003 + ti)
            rows.append(run(ag, layout, task, 2 * task["d_star"] + 20))
        tot = collections.Counter()
        for r in rows:
            tot.update(r["all"])
        long = [r for r in rows if r["kind"] == "long"]
        out[arm] = {"totals": dict(tot),
                    "episodes_with_wrong_pose": sum(r["all"].get("wrong_pose_steps", 0) > 0 for r in rows),
                    "episodes_with_wrong_cells": sum(r["wrong_cells"] > 0 for r in rows),
                    "episodes_with_wrong_mem": sum(r["mem_wrong"] > 0 for r in rows),
                    "n": len(rows),
                    "long_success": float(np.mean([r["success"] for r in long])),
                    "long_success_clean": float(np.mean([r["success"] for r in long if r["wrong_cells"] == 0 and r["mem_wrong"] == 0] or [np.nan])),
                    "long_success_corrupt": float(np.mean([r["success"] for r in long if r["wrong_cells"] > 0 or r["mem_wrong"] > 0] or [np.nan])),
                    "n_long_corrupt": sum(1 for r in long if r["wrong_cells"] > 0 or r["mem_wrong"] > 0)}
        print(arm, json.dumps(out[arm], ensure_ascii=False))
        (args.out / f"episodes_{arm}.json").write_text(json.dumps(rows))
    (args.out / "summary.json").write_text(json.dumps(out, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
