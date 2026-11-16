"""GridLab-S3 phase 3: MID items, SLOW promotion by rule R2, versions and their recovery.

Per reports/V9-S3-PHASE3-DESIGN/DESIGN-r1.md §3. Pure CPU, NumPy / standard library only.
Zero MLX imports. Writing memory never changes network parameters (there are none here).

- A dwell observation is the first step of each run of steps with the same estimated
  position and the same non-zero centre token; a step without a centre token ends the run.
- Places are matched with the frozen phase 2 hand-cue score
  ``view_similarity * 49 * LAM - pose_distance`` (``cues.compute_combined_score``), restricted
  to pose distance <= D_MAX and identical terrain (similarity >= SIM_MIN). Ties go to the
  lowest item id (the oldest item). Anchors are fixed when an item is created.
- An item records one vote per episode: the most common token among its observations in
  that episode; ties go to the token observed first in that episode.
- Rule R2: an unpromoted item promotes a token once it has >= 2 votes; a promoted token k is
  replaced by k' once k' has >= 2 votes after the latest vote for k. With rollback=False a
  promoted token is never replaced. Ties go to more votes, then to the most recent vote.
  At least two different episodes give the same token: the later one tests the earlier
  one's candidate. One of the two votes may come from the episode that created the item.
- A version is recorded whenever the promoted tokens change. It holds the parent hash, the
  episode, and every promoted item with its anchor, terrain, token and votes (the promotion
  evidence). Its hash is the SHA-256 of the canonical JSON of everything but the hash.
"""

from __future__ import annotations

import collections
import copy
import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Sequence

import numpy as np

from ainerzero.v9.experiments.s3.cues import DEFAULT_SCALE

D_MAX = 5.0
SIM_MIN = 1.0
LAM = 1.0
MIN_VOTES = 2


def place_scores(anchor_xy: np.ndarray, anchor_ter: np.ndarray, xy: np.ndarray, ter: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """(score, eligible) of one query against many anchors, vectorised hand-cue score."""
    d = np.abs(np.asarray(anchor_xy, dtype=np.float64) - np.asarray(xy, dtype=np.float64)).sum(-1)
    sim = (np.asarray(anchor_ter) == np.asarray(ter)).mean(-1)
    score = sim * DEFAULT_SCALE * LAM - d
    return score, (d <= D_MAX) & (sim >= SIM_MIN)


def best_match_tied(anchor_xy: np.ndarray, anchor_ter: np.ndarray, xy: np.ndarray, ter: np.ndarray) -> tuple[int | None, bool]:
    """(index of the best eligible anchor, whether another eligible anchor has the same score)."""
    if len(anchor_xy) == 0:
        return None, False
    score, ok = place_scores(anchor_xy, anchor_ter, xy, ter)
    if not ok.any():
        return None, False
    s = np.where(ok, score, -np.inf)
    j = int(np.argmax(s))
    return j, bool((s == s[j]).sum() > 1)


def best_match(anchor_xy: np.ndarray, anchor_ter: np.ndarray, xy: np.ndarray, ter: np.ndarray) -> int | None:
    """Index of the best eligible anchor (highest score, then lowest index), or None."""
    return best_match_tied(anchor_xy, anchor_ter, xy, ter)[0]


def dwell_starts(xy: np.ndarray, token: np.ndarray) -> list[int]:
    """Indices (into the given arrays, one episode in time order) of dwell observations."""
    out: list[int] = []
    prev = None
    for i in range(len(token)):
        if token[i] > 0:
            key = (float(xy[i][0]), float(xy[i][1]), int(token[i]))
            if key != prev:
                out.append(i)
            prev = key
        else:
            prev = None
    return out


def _pick(candidates: Sequence[int], counts: collections.Counter, votes: Sequence[int]) -> int:
    last = {k: max(i for i, x in enumerate(votes) if x == k) for k in candidates}
    return max(candidates, key=lambda k: (counts[k], last[k]))


def r2_update(votes: Sequence[int], slow: int | None, *, rollback: bool) -> int | None:
    """SLOW value of one item after its latest vote."""
    votes = list(votes)
    if slow is None:
        cnt = collections.Counter(votes)
        best = [k for k, n in cnt.items() if n >= MIN_VOTES]
        return _pick(best, cnt, votes) if best else None
    if not rollback:
        return slow
    last = max((i for i, x in enumerate(votes) if x == slow), default=-1)
    after = collections.Counter(votes[last + 1 :])  # holds no vote for slow by construction
    best = [k for k, n in after.items() if n >= MIN_VOTES]
    return _pick(best, after, votes) if best else slow


def mode_vote(votes: Sequence[int]) -> int:
    """Most common vote, ties to the most recent (the MODE control)."""
    cnt = collections.Counter(votes)
    return _pick(list(cnt), cnt, list(votes))


def _canonical(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def version_hash(parent: str | None, episode: int, items: Sequence[Sequence[Any]]) -> str:
    return hashlib.sha256(_canonical({"parent": parent, "episode": episode, "items": [list(x) for x in items]}).encode()).hexdigest()


@dataclass
class Item:
    id: int
    anchor_xy: tuple[float, float]
    anchor_ter: tuple[int, ...]
    votes: list[tuple[int, int]] = field(default_factory=list)  # (episode, token)
    slow: int | None = None
    tag: Any = None  # caller's label of the creating observation; diagnostics only, never matched on
    members: list[Any] = field(default_factory=list)  # caller's labels of every observation; diagnostics only


class PromotionStore:
    """MID items plus the promoted (SLOW) subset, with a hash-chained version log."""

    def __init__(self, *, rollback: bool):
        self.rollback = rollback
        self.items: list[Item] = []
        self.versions: list[dict[str, Any]] = [{"hash": version_hash(None, -1, []), "parent": None, "episode": -1, "items": []}]
        self.absorbed = -1
        self.diag = collections.Counter()  # diagnostics only

    # --- queries -----------------------------------------------------------------
    def _anchors(self, ids: Sequence[int]) -> tuple[np.ndarray, np.ndarray]:
        xy = np.array([self.items[i].anchor_xy for i in ids], dtype=np.float64).reshape(-1, 2)
        ter = np.array([self.items[i].anchor_ter for i in ids], dtype=np.int8).reshape(len(ids), -1)
        return xy, ter

    def match_tied(self, xy: np.ndarray, ter: np.ndarray, *, slow_only: bool) -> tuple[int | None, bool]:
        ids = [it.id for it in self.items if (it.slow is not None or not slow_only)]
        if not ids:
            return None, False
        axy, ater = self._anchors(ids)
        j, tied = best_match_tied(axy, ater, xy, ter)
        return (None, False) if j is None else (ids[j], tied)

    def match(self, xy: np.ndarray, ter: np.ndarray, *, slow_only: bool) -> int | None:
        return self.match_tied(xy, ter, slow_only=slow_only)[0]

    def answer(self, xy: np.ndarray, ter: np.ndarray) -> tuple[int | None, int | None]:
        """(item id, SLOW token) of the best-matching promoted item, or (None, None)."""
        j = self.match(xy, ter, slow_only=True)
        return (None, None) if j is None else (j, self.items[j].slow)

    @property
    def head(self) -> str:
        return self.versions[-1]["hash"]

    # --- writes ------------------------------------------------------------------
    def absorb(self, episode: int, xy: np.ndarray, ter: np.ndarray, token: np.ndarray, tags: Sequence[Any] | None = None) -> bool:
        """Write one episode's dwell observations (time order). Returns whether SLOW changed."""
        if episode != self.absorbed + 1:
            raise ValueError(f"episodes must be absorbed in order: got {episode}, expected {self.absorbed + 1}")
        per: dict[int, collections.Counter] = {}
        for i in range(len(token)):
            tag = None if tags is None else tags[i]
            j, tied = self.match_tied(xy[i], ter[i], slow_only=False)
            if j is None:
                j = len(self.items)
                self.items.append(Item(j, (float(xy[i][0]), float(xy[i][1])), tuple(int(v) for v in ter[i]), tag=tag))
            else:
                self.diag["writes_matched"] += 1
                self.diag["write_ties"] += int(tied)
            self.items[j].members.append(tag)
            per.setdefault(j, collections.Counter())[int(token[i])] += 1
        changed = False
        for j in sorted(per):
            item = self.items[j]
            top = per[j].most_common(2)
            self.diag["votes"] += 1
            self.diag["vote_ties"] += int(len(top) > 1 and top[0][1] == top[1][1])
            item.votes.append((episode, top[0][0]))
            new = r2_update([k for _, k in item.votes], item.slow, rollback=self.rollback)
            if new != item.slow:
                item.slow = new
                changed = True
        if changed:
            items = self.version_items()
            self.versions.append({"hash": version_hash(self.head, episode, items), "parent": self.head, "episode": episode, "items": items})
        self.absorbed = episode
        return changed

    # --- versions ----------------------------------------------------------------
    def version_items(self) -> list[list[Any]]:
        """Promoted items with anchors, terrain, token and votes, in id order."""
        return [[it.id, it.slow, list(it.anchor_xy), list(it.anchor_ter), [list(v) for v in it.votes]] for it in self.items if it.slow is not None]

    def snapshot(self) -> dict[str, Any]:
        """The current version record: enough to answer a SLOW query without the store."""
        return copy.deepcopy(self.versions[-1])

    def state(self) -> dict[str, Any]:
        """Full serialisable state (MID and SLOW), for restore-and-replay."""
        return {
            "rollback": self.rollback,
            "absorbed": self.absorbed,
            "items": [[it.id, list(it.anchor_xy), list(it.anchor_ter), [list(v) for v in it.votes], it.slow] for it in self.items],
            "versions": copy.deepcopy(self.versions),
        }

    @classmethod
    def restore(cls, state: dict[str, Any]) -> "PromotionStore":
        s = cls(rollback=bool(state["rollback"]))
        s.absorbed = int(state["absorbed"])
        s.items = [Item(int(i), (float(a[0]), float(a[1])), tuple(int(v) for v in ter), [(int(e), int(k)) for e, k in votes], None if slow is None else int(slow)) for i, a, ter, votes, slow in state["items"]]
        s.versions = copy.deepcopy(state["versions"])
        return s


def answer_from_snapshot(version: dict[str, Any], xy: Sequence[float], ter: Sequence[int]) -> int | None:
    """Re-answer a SLOW query from a version record only (plain Python, no store)."""
    best, best_score = None, None
    for item_id, tok, axy, ater, _votes in sorted(version["items"], key=lambda r: r[0]):
        d = abs(float(axy[0]) - float(xy[0])) + abs(float(axy[1]) - float(xy[1]))
        sim = sum(int(a) == int(b) for a, b in zip(ater, ter)) / len(ater)
        if d > D_MAX or sim < SIM_MIN:
            continue
        score = sim * DEFAULT_SCALE * LAM - d
        if best_score is None or score > best_score:
            best, best_score = tok, score
    return best


def verify_chain(versions: Sequence[dict[str, Any]]) -> list[str]:
    """Problems with a version log: broken parent links or hashes that do not recompute."""
    bad = []
    for i, v in enumerate(versions):
        parent = versions[i - 1]["hash"] if i else None
        if v["parent"] != parent:
            bad.append(f"version {i}: parent link broken")
        if v["hash"] != version_hash(v["parent"], v["episode"], v["items"]):
            bad.append(f"version {i}: hash does not recompute")
    return bad


class TruthKeyedStore:
    """Diagnostic only: the same rule R2 with places keyed by the true cell."""

    def __init__(self, *, rollback: bool):
        self.rollback = rollback
        self.votes: dict[tuple[int, int], list[int]] = {}
        self.slow: dict[tuple[int, int], int | None] = {}

    def absorb(self, cells: Sequence[tuple[int, int]], token: Sequence[int]) -> None:
        per: dict[tuple[int, int], collections.Counter] = {}
        for c, k in zip(cells, token):
            per.setdefault(tuple(int(v) for v in c), collections.Counter())[int(k)] += 1
        for c in sorted(per):
            self.votes.setdefault(c, []).append(per[c].most_common(1)[0][0])
            self.slow[c] = r2_update(self.votes[c], self.slow.get(c), rollback=self.rollback)

    def answer(self, cell: tuple[int, int]) -> int | None:
        return self.slow.get(tuple(int(v) for v in cell))
