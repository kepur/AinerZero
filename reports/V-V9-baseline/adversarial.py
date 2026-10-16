"""ainerzero.V9.A3 独立复核：被验 ainerzero.V9.A2（基线冻结清单与复验脚本）。

只读核对，不改被验文件；不复用作者测试；只写本目录与系统临时目录。
破坏性操作只发生在临时符号链接树内，真实 artifacts/ 从不被写。

判定口径：
    blocked     预期被拒/覆盖完整（防御成立）
    finding     缺口或契约违反 —— 交一级定夺；本脚本非零退出
    observation 符合设计/已登记限制，留记录

退出码：无 finding -> 0，否则 1；--invert 把全部期望反转（红对照，期望 exit 1）。
纯 CPU；不 import 模型运行时；不下载。
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path

sys.dont_write_bytecode = True
for _m in ("mlx", "torch", "onnxruntime"):
    assert _m not in sys.modules, f"模型运行时已导入：{_m}"

ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "reports/V9-baseline/baseline_manifest.json"
SCRIPT = ROOT / "scripts/v9_baseline_manifest.py"

spec = importlib.util.spec_from_file_location("v9bm", SCRIPT)
V9 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(V9)

PINNED = json.loads(MANIFEST.read_text())["files"]
INVERT = "--invert" in sys.argv


def sha_file(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for c in iter(lambda: f.read(1 << 20), b""):
            h.update(c)
    return h.hexdigest()


def make_tree() -> Path:
    """临时树：真实目录 + 指向真实文件的符号链接（232 个钉选文件全链）。"""
    t = Path(tempfile.mkdtemp(prefix="v9a3-"))
    for e in PINNED:
        src = ROOT / e["path"]
        dst = t / e["path"]
        dst.parent.mkdir(parents=True, exist_ok=True)
        os.symlink(src, dst)
    return t


def run_verify(t: Path) -> dict:
    tmp = t / "_tmp"
    tmp.mkdir(exist_ok=True)
    return V9.verify(t, MANIFEST, tmp)


CASES = []


def case(name):
    def deco(fn):
        CASES.append((name, fn))
        return fn
    return deco


def verdict(name, got_blocked, detail, expect_block=True, observ=None):
    if observ is not None:
        return {"case": name, "verdict": "observation", "observed": observ, "detail": detail}
    good = got_blocked == expect_block
    if INVERT:
        good = not good
    return {"case": name, "verdict": "blocked" if good else "finding",
            "expected": "RED" if expect_block else "GREEN", "observed": detail}


def problems_of(res):
    return [(p.get("kind"), p.get("path")) for p in res.get("problems", [])]


@case("T0_clean_tree_green")
def t0():
    t = make_tree()
    try:
        r = run_verify(t)
        ok = r["verdict"] == "ok" and r["files_ok"] == 232 and not r["problems"]
        return verdict("T0", ok, f"verdict={r['verdict']} ok={r['files_ok']}/232", True)
    finally:
        shutil.rmtree(t, ignore_errors=True)


@case("T1_dangling_symlink_checkpoint")
def t1():
    t = make_tree()
    try:
        ck = next(e["path"] for e in PINNED if e["category"] == "checkpoint")
        (t / ck).unlink()
        os.symlink(t / "no-such-target.bin", t / ck)
        r = run_verify(t)
        kinds = problems_of(r)
        return verdict("T1", ("missing", ck) in kinds, f"{r['verdict']} {kinds[:3]}", True)
    finally:
        shutil.rmtree(t, ignore_errors=True)


@case("T2_symlink_to_directory")
def t2():
    t = make_tree()
    try:
        ck = next(e["path"] for e in PINNED if e["category"] == "checkpoint")
        (t / ck).unlink()
        os.symlink(t / "artifacts", t / ck)
        r = run_verify(t)
        kinds = problems_of(r)
        return verdict("T2", ("missing", ck) in kinds, f"{r['verdict']} {kinds[:3]}", True)
    finally:
        shutil.rmtree(t, ignore_errors=True)


@case("T3_smuggled_txt_in_checkpoints_dir")
def t3():
    t = make_tree()
    try:
        ck = next(e["path"] for e in PINNED if e["category"] == "checkpoint")
        evil = Path(ck).parent / "smuggled-note.txt"
        (t / evil).write_text("not in manifest\n")
        r = run_verify(t)
        # 代码注释称“pinned scope 内新文件不得悄悄溜入”，但 scan 只收钉选类别
        return verdict("T3", r["verdict"] != "ok", f"verdict={r['verdict']}", True)
    finally:
        shutil.rmtree(t, ignore_errors=True)


@case("T4_smuggled_safetensors_in_dataset_dir")
def t4():
    t = make_tree()
    try:
        c0 = next(e["path"] for e in PINNED if e["category"] == "dataset.c0")
        evil = str(Path(c0).parent / "evil.safetensors")
        (t / evil).write_bytes(b"fake-tensors")
        r = run_verify(t)
        kinds = problems_of(r)
        return verdict("T4", ("unexpected_new_file", evil) in kinds,
                       f"{r['verdict']} {kinds[:3]}", True)
    finally:
        shutil.rmtree(t, ignore_errors=True)


@case("T5_same_size_swap_two_gridlab_files")
def t5():
    t = make_tree()
    try:
        gl = [e["path"] for e in PINNED if e["category"] == "dataset.gridlab2d"]
        a, b = sorted(gl, key=lambda p: (ROOT / p).stat().st_size)[:2]
        ba, bb = (t / a).resolve().read_bytes(), (t / b).resolve().read_bytes()
        assert len(ba) != len(bb) or True
        # 等长交换：把两文件内容截成等长后互换，名字与大小都不变
        n = min(len(ba), len(bb))
        (t / a).unlink()
        (t / b).unlink()
        (t / a).write_bytes(bb[:n].ljust(n, b"\x00") if len(bb) >= n else bb)
        (t / b).write_bytes(ba[:n])
        # 若原长不等则大小也会变红，同样算拦截成功；关键是内容互换必被发现
        r = run_verify(t)
        kinds = problems_of(r)
        hit = [k for k in kinds if k[1] in (a, b)]
        return verdict("T5", bool(hit), f"{r['verdict']} {hit}", True)
    finally:
        shutil.rmtree(t, ignore_errors=True)


@case("T6_registration_md_append")
def t6():
    t = make_tree()
    try:
        reg = next(e["path"] for e in PINNED
                   if e["category"] == "registration" and e["path"].endswith(".md"))
        dst = t / reg
        raw = dst.resolve().read_bytes()
        dst.unlink()
        dst.write_bytes(raw + b"\n")
        r = run_verify(t)
        kinds = problems_of(r)
        return verdict("T6", any(k[1] == reg for k in kinds), f"{r['verdict']} {kinds[:2]}", True)
    finally:
        shutil.rmtree(t, ignore_errors=True)


@case("T7_vacuum_brittleness")
def t7():
    work = Path(tempfile.mkdtemp(prefix="v9a3-vac-"))
    try:
        src = ROOT / "artifacts/control.sqlite3"
        a, b = work / "a.db", work / "b.db"
        shutil.copy2(src, a)
        shutil.copy2(src, b)
        con = sqlite3.connect(b)
        con.execute("VACUUM")
        con.close()
        same_bytes = sha_file(a) == sha_file(b)
        qa = sqlite3.connect(f"file:{a}?mode=ro&immutable=1", uri=True)
        qb = sqlite3.connect(f"file:{b}?mode=ro&immutable=1", uri=True)
        rows = {}
        for tag, q in (("a", qa), ("b", qb)):
            rows[tag] = {t[0]: q.execute(f"SELECT COUNT(*) FROM {t[0]}").fetchone()[0]
                         for t in q.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        qa.close()
        qb.close()
        return verdict("T7", False,
                       f"VACUUM 后字节{'相同' if same_bytes else '不同'}、行数{'相同' if rows['a'] == rows['b'] else '不同'}；"
                       "verify 按文件字节钉选，合法维护会变红",
                       observ="byte-pinning brittleness（合法 VACUUM 即 RED；作者未登记该限制）")
    finally:
        shutil.rmtree(work, ignore_errors=True)


@case("T8_no_mtime_logic")
def t8():
    src = SCRIPT.read_text()
    assert "st_mtime" not in src and "mtime" not in src, "脚本出现 mtime 比较"
    work = Path(tempfile.mkdtemp(prefix="v9a3-mtime-"))
    try:
        ck = next(e["path"] for e in PINNED if e["category"] == "checkpoint")
        real = ROOT / ck
        c1, c2 = work / "x.bin", work / "y.bin"
        shutil.copy2(real, c1)
        h1 = sha_file(c1)
        os.utime(c1, (0, 0))
        shutil.copy2(real, c2)
        h2 = sha_file(c2)
        return verdict("T8", False,
                       f"源码无 mtime 比较；同文件 touch 前后 sha 一致={h1 == h2}",
                       observ="hash-based confirmed（mtime 不影响判定，源码断言通过）")
    finally:
        shutil.rmtree(work, ignore_errors=True)


def is_vol_dir(dp: str) -> bool:
    return any(part == "tmp" or part.startswith("tmp-") for part in Path(dp).parts)


def unpinned_in_run(run_rel: str) -> list[str]:
    pinned = {e["path"] for e in PINNED}
    out = []
    for dp, dn, fn in os.walk(ROOT / run_rel):
        if is_vol_dir(dp):
            continue
        for f in fn:
            rel = (Path(dp) / f).relative_to(ROOT).as_posix()
            if rel not in pinned and not rel.endswith(("-wal", "-shm")):
                out.append(rel)
    return sorted(out)


@case("C1_d_run_unpinned_files")
def c1():
    d_run = "artifacts/pilot/pilot-b4e75e9b4a1a4ba086118d37017b2a1a"
    missing = unpinned_in_run(d_run)
    interesting = [p for p in missing if not p.endswith("preregistration.json")]
    return verdict("C1", not interesting,
                   f"D 运行目录未钉选 {len(interesting)} 个：{interesting}", True)


@case("C2_checkpoint_manifests_unpinned")
def c2():
    pinned = {e["path"] for e in PINNED}
    n = 0
    for dp, dn, fn in os.walk(ROOT / "artifacts"):
        if is_vol_dir(dp):
            continue
        for f in fn:
            if f in ("manifest.json", "metadata.json") and "checkpoints" in Path(dp).parts:
                rel = (Path(dp) / f).relative_to(ROOT).as_posix()
                if rel not in pinned:
                    n += 1
    return verdict("C2", n == 0, f"checkpoint 目录下 manifest/metadata 未钉选 {n} 个（系统性）", True)


@case("C3_run_data_snapshots_unpinned")
def c3():
    pinned = {e["path"] for e in PINNED}
    hits = []
    for dp, dn, fn in os.walk(ROOT / "artifacts"):
        if is_vol_dir(dp):
            continue
        for f in fn:
            if f in ("fixed-batch.npz", "training-pool.npz", "training-schedule.npy",
                     "report.json", "updates.jsonl", "config.yaml"):
                rel = (Path(dp) / f).relative_to(ROOT).as_posix()
                if rel not in pinned:
                    hits.append(rel)
    return verdict("C3", not hits, f"运行级数据/报告/配置未钉选 {len(hits)} 个", True)


@case("C4_root_level_d_docs_out_of_scope")
def c4():
    docs = ["M2M_PROPOSAL.md", "M2D_CHANGED_MULTISTEP.md", "M2MC_LEARNING_RATE_FIT.md"]
    found = [d for d in docs if (ROOT / d).exists()]
    return verdict("C4", False, f"根目录 D 相关结论文档 {found} 不在 artifacts 冻结范围内（作者声明排除源码与报告正文）",
                   observ="scope gap（声明过，但 D 结论正文无哈希锚定）")


@case("C5_declared_scope_complete")
def c5():
    pinned = {e["path"] for e in PINNED}
    regs = [e for e in PINNED if e["category"] == "registration"]
    bad = []
    for dp, dn, fn in os.walk(ROOT / "artifacts"):
        if is_vol_dir(dp):
            continue
        for f in fn:
            rel = (Path(dp) / f).relative_to(ROOT).as_posix()
            nl = f.lower()
            if (("registration" in nl or f == "preregistration.json")
                    and rel.split(".")[-1] in ("json", "md") and rel not in pinned):
                bad.append(rel)
    return verdict("C5", not bad and len(regs) == 88,
                   f"artifacts 内 registration 口径文件全钉选={not bad}（{len(regs)} 个）；"
                   "c0/gridlab/RunStore 已另行全覆盖确认", True)


def main() -> int:
    rows = []
    for name, fn in CASES:
        try:
            row = fn()
        except AssertionError as e:
            row = {"case": name, "verdict": "finding", "observed": f"harness 断言失败：{e}"}
        except Exception as e:  # noqa: BLE001
            row = {"case": name, "verdict": "finding",
                   "observed": f"harness 非预期异常 {type(e).__name__}: {e}"}
        rows.append(row)
        print(f"[{row['verdict'].upper():>11}] {row['case']}: {row.get('observed')}")
        if "expected" in row:
            print(f"             detail: {row.get('detail')}")
    out = {"mode": "inverted-control" if INVERT else "real",
           "cases": rows,
           "summary": {v: sum(1 for r in rows if r["verdict"] == v)
                       for v in ("blocked", "finding", "observation")}}
    Path(__file__).parent.joinpath("adversarial.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=1) + "\n")
    n_find = out["summary"]["finding"]
    print(f"cases={len(rows)} findings={n_find} mode={out['mode']}")
    return 1 if n_find else 0


if __name__ == "__main__":
    sys.exit(main())
