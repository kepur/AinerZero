"""确认段的留出图：每个训练种子一套，互不重叠，且不与训练图重叠；默认值保持探索段的那一套。"""
import pytest

from ainerzero.v9.mini import data as D
from ainerzero.v9.mini import evaluate as E
from ainerzero.v9.mini import run as RUN
from ainerzero.v9.mini import world as W

CFG = W.Config(ice_rooms=2, portals=2)


def test_default_is_exploration_set():
    a = E.make_tasks(CFG, 2, 200, 1, 1)
    b = E.make_tasks(CFG, 2, 200, 1, 1, eval_seed0=D.EVAL_SEED0)
    assert [(t["layout_seed"], t["start"], t["goal"], t["d_star"]) for t in a] == \
           [(t["layout_seed"], t["start"], t["goal"], t["d_star"]) for t in b]
    assert {t["layout_seed"] for t in a} <= {D.EVAL_SEED0, D.EVAL_SEED0 + 1}


def test_per_seed_sets_disjoint():
    sets = []
    for s in range(5):
        ts = E.make_tasks(CFG, 3, 200, 1, 1, eval_seed0=8_000_000 + 1000 * s)
        sets.append({t["layout_seed"] for t in ts})
        assert all(8_000_000 + 1000 * s <= x < 8_000_000 + 1000 * s + 3 for x in sets[-1])
    for i in range(5):
        for j in range(i + 1, 5):
            assert not (sets[i] & sets[j])


def test_run_rejects_eval_overlapping_train(tmp_path):
    with pytest.raises(SystemExit) as e:
        RUN.main(["--quick", "--seed", "2", "--eval-seed0", str(D.TRAIN_SEED0 + 2000 + 10), "--out", str(tmp_path / "x")])
    assert "重叠" in str(e.value)
    assert not (tmp_path / "x").exists()
