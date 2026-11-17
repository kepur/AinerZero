"""地图智能体的并图校验（A27 F-04）与不用训练的小规模端到端运行。"""
import numpy as np

from ainerzero.v9.mini import evaluate as E
from ainerzero.v9.mini import mapagent as MA
from ainerzero.v9.mini import residual as R
from ainerzero.v9.mini import world as W

CFG = W.Config(ice_rooms=2, portals=2)


def _agent():
    ag = MA.MapAgent(CFG, R.ForwardModel(kind="analytic"), memory=True)
    c = CFG.size
    ag.main = MA.Frame(ag.n, CFG, ag.fm, (c, c, 0))
    ag.trans_mem, ag.portal_mem = {}, {}
    return ag


def test_overlap_counts_and_conflicts():
    ag = _agent()
    fr = MA.Frame(ag.n, CFG, ag.fm, (5, 5, 0))
    ag.main.map[10:13, 10:13] = W.FLOOR0
    fr.map[0:3, 0:3] = W.FLOOR0
    assert ag._overlap(fr, 10, 10) == (9, 0)
    fr.map[1, 1] = W.WALL
    assert ag._overlap(fr, 10, 10) == (9, 1)
    assert ag._overlap(fr, 11, 11) == (4, 1)        # 只重叠右下 2×2，其中 (1,1) 平移后落在 (12,12) 冲突
    assert ag._overlap(fr, -1, 0)[1] == 1            # 平移后出了主地图：不可能对


def _near_view(h):
    """只有自己和前后左右四格可见（地板），其余视野外。"""
    view = np.full((CFG.view, CFG.view), W.OOB, dtype=np.int16)
    for row, col, dx, dy in W.ego_offsets(CFG.view_radius, h):
        if abs(dx) + abs(dy) <= 1:
            view[row, col] = W.FLOOR0
    return view


def _lost_agent(block: bool, wall: bool):
    """主地图 [5,30) 全是地板；迷路中，碎片位姿在中心，唯一候选在主地图 (15,15)。"""
    ag = _agent()
    ag.main.map[5:30, 5:30] = W.FLOOR0
    c = CFG.size
    fr = MA.Frame(ag.n, CFG, ag.fm, (c, c, 0))
    if block:   # 碎片里已有一块 5×5 地板：平移到候选处与主地图重叠 25 格
        fr.map[c - 2:c + 3, c - 2:c + 3] = W.FLOOR0
    if wall:    # 这块里放一格墙（不在当前可见范围内），与主地图冲突
        fr.map[c + 2, c + 2] = W.WALL
    ag.frag, ag.frag_origin, ag.rejected = fr, fr.pose, set()
    ag.cands = {(15, 15, 0): fr.pose}
    ag.lost_from, ag.lost_action, ag.steps = (c, c, 0), W.FORWARD, 0
    return ag


def test_merge_rejects_conflicting_offset():
    ag = _lost_agent(block=True, wall=True)
    ag._lost_step(W.LEFT, _near_view(3), 3)
    assert ag.frag is not None, "碎片与主地图冲突时不能并图"
    assert (15 - CFG.size, 15 - CFG.size) in ag.rejected
    assert ag.main.map[15 + 2, 15 + 2] == W.FLOOR0, "主地图不能被碎片改写"


def test_merge_waits_for_enough_overlap():
    ag = _lost_agent(block=False, wall=False)
    ag._lost_step(W.LEFT, _near_view(3), 3)
    assert ag.frag is not None, "重叠只有可见的 5 格，不够门槛，继续跟踪"
    assert list(ag.cands) == [(15, 15, 3)]


def test_merge_when_consistent_and_enough_overlap():
    ag = _lost_agent(block=True, wall=False)
    ag._lost_step(W.LEFT, _near_view(3), 3)
    assert ag.frag is None and ag.main.pose == (15, 15, 3)


def test_end_to_end_map_arms_and_oracle_without_training():
    tasks = E.make_tasks(CFG, 2, 200, 1, 1)
    fms = {"analytic": R.ForwardModel(kind="analytic")}
    fms["gated"] = fms["gated_self"] = fms["ungated"] = fms["ungated_aug"] = fms["analytic"]
    ev = E.evaluate_tasks(None, CFG, tasks, fms, arms=("map_analytic", "map_memory", "map_hybrid", "oracle"),
                          log=lambda *_: None)
    assert all(r["success"] == 1 for r in ev["episodes"]["oracle"])
    for arm in ("map_analytic", "map_memory", "map_hybrid"):
        assert len(ev["episodes"][arm]) == len(tasks)
        assert all("layout_seed" in r for r in ev["episodes"][arm])
