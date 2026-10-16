#!/usr/bin/env python
"""T18 独立复核驱动（非作者）。

对 ainerzero.V9.T1 r3（作者 catjam-m9v2）做只读复核：

1. 记录受保护文件（文档/schema/作者 checker/r3 夹具/r2 归档/T17 报告）运行前后 SHA-256。
2. 在隔离沙箱副本里重跑作者 `reports/V9-T1/r3/check_teacher_cache_v2.py --suite`，
   核对作者自述计数（3 正 / 41 负 / 29 对照 / 11 破坏）与 all_ok。
3. 用**本目录独立 oracle** `t18_oracle.py`（不 import 作者任何函数）交叉核对作者全部
   夹具（valid/invalid + contexts + expected-context-identities 的 pin）。
4. 复现 T17 五个隔离语义探针（B1–B4）。
5. 新增 ≥10 个对抗性反例（独立构造）。
6. 单规则隔离：关闭某条规则后其专用反例必须漏检（真子进程）。
7. 独立资格 oracle：基线四条目资格 + 五项交集单锁。

全部判据在**真实子进程**里执行，拒绝=非零退出、通过=零退出。
只读：不改受保护文件；只写本报告目录 `reports/V-V9-T1-r3/big-pickle-d98w-20261016/`。
"""
from __future__ import annotations

import copy
import hashlib
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

AUTHOR_ROOT = Path("/Users/mac/AinerWorkFlow/AinerZero")
OUT = Path(__file__).resolve().parent
ORACLE = OUT / "t18_oracle.py"
PY = "/Users/mac/AinerWorkFlow/AnimeWorldZero/.venv/bin/python"
SCHEMA = AUTHOR_ROOT / "contracts/v9/teacher_cache.v2.schema.json"
DOCS = AUTHOR_ROOT / "docs/v9/TEACHERS_AND_CACHE.md"
AUTHOR_CHECKER = AUTHOR_ROOT / "reports/V9-T1/r3/check_teacher_cache_v2.py"
EXAMPLES = AUTHOR_ROOT / "contracts/v9/examples/teacher_cache_v2"
R2_ARCHIVE = AUTHOR_ROOT / "reports/V9-T1/r2-archive"
T17 = AUTHOR_ROOT / "reports/V-V9-T1-r2/codex-v101-20261016"
PINS = EXAMPLES / "expected-context-identities.json"


# ---------------------------------------------------------------- helpers
def sha_file(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def canon_sha(obj) -> str:
    return hashlib.sha256(
        json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()


def entry_id(e: dict) -> str:
    return canon_sha({
        "cache_key": e["cache_key"],
        "world_key": e["source"]["world_key"],
        "partition": e["source"]["partition"],
        "input_sha256": e["provenance"]["upstream"]["input_ref"]["sha256"],
        "use": e["provenance"]["derivation"]["use"],
    })


def blob_of(records, cache_key):
    return next(r for r in records if r.get("record_type") == "teacher_blob" and r["cache_key"] == cache_key)


def entries(records):
    return [r for r in records if r.get("record_type") == "teacher_entry"]


def context_for(records, cutoff_ticks=None):
    """与作者同形的 trusted context 构造（仅用于我的新反例；不 import 作者代码）。"""
    srcs = []
    for e in entries(records):
        srcs.append({
            "source_id": e["source"]["manifest_ref"]["source_id"],
            "world_key": e["source"]["world_key"],
            "partition": e["source"]["partition"],
            "upstream": copy.deepcopy(e["provenance"]["upstream"]),
            "time_domain": copy.deepcopy(e["source"]["time_domain"]),
        })
    domain = copy.deepcopy(entries(records)[0]["source"]["time_domain"])
    ct = cutoff_ticks if cutoff_ticks is not None else entries(records)[0]["as_of_t_ticks"]
    return {
        "schema_version": "az.v9.teacher_cache.context.v1",
        "context_id": "t18-independent-context",
        "synthetic": True,
        "source_manifest": {"manifest_id": "synthetic-original-sources-r3", "sources": srcs},
        "observation": {
            "packet_ref": {"uri": "synthetic://observation/current", "sha256": canon_sha({"synthetic": "current-packet"})},
            "time_domain": domain, "t_ticks": ct, "t_s": ct / 120,
        },
        "approval_registry": {"registry_id": "adr-0005-current-approved-empty-20261016", "entries": []},
    }


def protected_files():
    files = [SCHEMA, DOCS, AUTHOR_CHECKER, PINS,
             AUTHOR_ROOT / "reports/V9-T1/r3/REPORT.md",
             AUTHOR_ROOT / "reports/V9-T1/r3/COORDINATOR_DECISIONS.md",
             AUTHOR_ROOT / "reports/V9-T1/r3/check_result_v2.json",
             AUTHOR_ROOT / "reports/V9-T1/r3/metrics.json"]
    files += sorted(EXAMPLES.rglob("*.json"))
    files += sorted(R2_ARCHIVE.rglob("*"))
    files += sorted(T17.rglob("*"))
    return [p for p in files if p.is_file()]


def snapshot():
    return {str(p): sha_file(p) for p in protected_files()}


def run(cmd, cwd=None):
    r = subprocess.run(cmd, capture_output=True, text=True, cwd=cwd)
    return r.returncode, r.stdout, r.stderr


# ---------------------------------------------------------------- oracle runner
class Runner:
    def __init__(self, workdir: Path):
        self.workdir = workdir
        self.workdir.mkdir(parents=True, exist_ok=True)
        self.n = 0

    def oracle(self, records, context, pin, mode="validate", disable=()):
        self.n += 1
        d = self.workdir / f"case-{self.n:03d}"
        d.mkdir(parents=True, exist_ok=True)
        rp = d / "records.json"
        rp.write_text(json.dumps(records, ensure_ascii=False, indent=2) + "\n")
        argv = [PY, "-I", str(ORACLE), mode, "--records", str(rp)]
        if pin is not None:
            argv += ["--expected-context-sha256", pin]
        if context is not None:
            cp = d / "context.json"
            cp.write_text(json.dumps(context, ensure_ascii=False, indent=2) + "\n")
            argv += ["--context", str(cp)]
        for t in disable:
            argv += ["--disable", t]
        rc, out, err = run(argv)
        try:
            payload = json.loads(out)
        except json.JSONDecodeError:
            payload = {"exception": True, "stdout": out, "stderr": err}
        return {"argv": argv, "returncode": rc, "payload": payload, "errors": payload.get("errors", [])}


# ---------------------------------------------------------------- steps
def author_suite(run_dir: Path):
    sandbox = run_dir / "author-sandbox"
    if sandbox.exists():
        shutil.rmtree(sandbox)
    (sandbox / "contracts/v9").mkdir(parents=True)
    shutil.copyfile(SCHEMA, sandbox / "contracts/v9/teacher_cache.v2.schema.json")
    (sandbox / "contracts/v9/examples/teacher_cache_v2").mkdir(parents=True)
    shutil.copytree(R2_ARCHIVE, sandbox / "reports/V9-T1/r2-archive")
    (sandbox / "reports/V9-T1/r3").mkdir(parents=True)
    shutil.copyfile(AUTHOR_CHECKER, sandbox / "reports/V9-T1/r3/check_teacher_cache_v2.py")
    (sandbox / "docs/v9").mkdir(parents=True)
    shutil.copyfile(DOCS, sandbox / "docs/v9/TEACHERS_AND_CACHE.md")
    script = sandbox / "reports/V9-T1/r3/check_teacher_cache_v2.py"
    rc, out, err = run([PY, "-I", str(script), "--suite"])
    result = {"sandbox": str(sandbox), "argv": [PY, "-I", str(script), "--suite"],
              "returncode": rc, "stdout": out, "stderr": err}
    resjs = sandbox / "reports/V9-T1/r3/check_result_v2.json"
    result["result_exists"] = resjs.exists()
    if resjs.exists():
        data = json.loads(resjs.read_text())
        result["all_ok"] = data.get("all_ok")
        result["counts"] = data.get("counts")
        result["failures"] = data.get("failures")
        result["control_failures"] = data.get("control_failures")
        result["nonisolated"] = data.get("nonisolated_regression_controls")
        result["archives_ok"] = all(x["ok"] for x in data.get("archives", []))
        result["archives_count"] = len(data.get("archives", []))
        result["legacy_r2_ok"] = data.get("legacy_r2", {}).get("ok")
        result["legacy_r2_returncode"] = data.get("legacy_r2", {}).get("returncode")
        result["legacy_counts"] = data.get("legacy_counts")
        result["author_eligibility"] = data.get("eligibility")
        result["author_intersection_gates"] = data.get("intersection_gates")
        # compare regenerated fixtures to committed ones
        diff, same = [], 0
        gen = sandbox / "contracts/v9/examples/teacher_cache_v2"
        committed = {str(p.relative_to(EXAMPLES)) for p in EXAMPLES.rglob("*.json")}
        produced = {str(p.relative_to(gen)) for p in gen.rglob("*.json")}
        for rel in sorted(committed | produced):
            a, b = EXAMPLES / rel, gen / rel
            if not a.exists() or not b.exists():
                diff.append({"file": rel, "why": "missing", "committed": a.exists(), "produced": b.exists()})
            elif sha_file(a) != sha_file(b):
                diff.append({"file": rel, "why": "bytes", "committed_sha": sha_file(a), "produced_sha": sha_file(b)})
            else:
                same += 1
        result["fixtures_same"] = same
        result["fixtures_diff"] = diff
        result["fixtures_reproduced"] = not diff
    return result


def crosscheck_fixtures(r: Runner):
    pins = json.loads(PINS.read_text())["pins"]
    rows = []
    names = sorted(p.stem for p in (EXAMPLES / "invalid").glob("*.json"))
    names += sorted(p.stem for p in (EXAMPLES / "valid").glob("*.json"))
    for name in names:
        want = (EXAMPLES / "valid" / f"{name}.json").exists()
        records = json.loads(((EXAMPLES / ("valid" if want else "invalid")) / f"{name}.json").read_text())
        if name == "store":  # base store fixture pairs with the baseline context
            ctx = json.loads((EXAMPLES / "contexts/baseline.json").read_text())
            res = r.oracle(records, ctx, canon_sha(ctx))
            rows.append({"name": name, "want": "accept", "returncode": res["returncode"],
                         "errors": res["errors"], "ok": res["returncode"] == 0})
            continue
        pin = pins[name]
        mode = "eligible" if name in ("direct_admission_validates_fingerprints",
                                      "intersection_entry_license_denied") else "validate"
        if name == "missing_trusted_context":
            res = r.oracle(records, None, pin, mode)
        else:
            ctx = json.loads((EXAMPLES / "contexts" / f"{name}.json").read_text())
            res = r.oracle(records, ctx, pin, mode)
        rows.append({"name": name, "want": "accept" if want else "reject",
                     "returncode": res["returncode"], "errors": res["errors"],
                     "ok": (res["returncode"] == 0) == want})
    return rows


def isolation_map_fixtures(r: Runner):
    """作者 isolate_* 夹具在我的 oracle 下：开规则拒、关规则收。"""
    pins = json.loads(PINS.read_text())["pins"]
    mapping = {
        "isolate_awz_origin_combination": "awz_schema",
        "isolate_original_source_binding": "binding",
        "isolate_source_blob_times": "source_times",
        "isolate_unapproved_revision": "approval",
        "isolate_derivation_weights": "weights",
        "isolate_derivation_preprocess": "preprocess",
    }
    rows = []
    for name, token in mapping.items():
        records = json.loads((EXAMPLES / "invalid" / f"{name}.json").read_text())
        ctx = json.loads((EXAMPLES / "contexts" / f"{name}.json").read_text())
        pin = pins[name]
        on = r.oracle(records, ctx, pin)
        off = r.oracle(records, ctx, pin, disable=[token])
        rows.append({"name": name, "token": token,
                     "on_rc": on["returncode"], "on_errors": on["errors"],
                     "off_rc": off["returncode"], "off_errors": off["errors"],
                     "ok": on["returncode"] == 1 and off["returncode"] == 0})
    return rows


def build_base():
    base = json.loads((EXAMPLES / "valid" / "store.json").read_text())
    ctx = json.loads((EXAMPLES / "contexts" / "baseline.json").read_text())
    pin = canon_sha(ctx)
    b = {r["cache_key"]: r for r in base if r["record_type"] == "teacher_blob"}
    es = entries(base)
    return base, ctx, pin, b, es


def t17_probes(r: Runner):
    base, ctx, pin, b, es = build_base()
    w1, w2 = es[0], es[1]  # awz:w1 (external_derived), gridlab:w2 (observed)
    blob0 = blob_of(base, w2["cache_key"])

    def mut(fn):
        d = copy.deepcopy(base)
        fn(d)
        return d

    cases = []
    d = mut(lambda d: (d[3]["provenance"]["upstream"].update(origin="observed"),
                       d[3]["provenance"]["upstream"].update(eligibility=copy.deepcopy(d[4]["provenance"]["upstream"]["eligibility"]))))
    cases.append(("T17_awz_mislabeled_observed_train", d, ctx, pin))
    d = mut(lambda d: d[3]["provenance"]["upstream"]["eligibility"].update(
        train=True, basis="adr_0005_revision", revision_ref="not-an-approved-adr"))
    cases.append(("T17_fake_nonempty_adr_revision", d, ctx, pin))
    d = mut(lambda d: (d[4]["source"].update(timestamps_s=[0.0, 0.1]), d[4].update(as_of_t_s=0.2)))
    cases.append(("T17_unkeyed_source_timestamps_backdated", d, ctx, pin))
    d = mut(lambda d: d[4]["provenance"]["derivation"].update(weights_sha256=["b" * 64]))
    cases.append(("T17_derivation_weights_mismatch", d, ctx, pin))
    d = mut(lambda d: d[4]["provenance"]["derivation"].update(preprocess_spec_sha256="c" * 64))
    cases.append(("T17_derivation_preprocess_mismatch", d, ctx, pin))

    rows = []
    for name, records, c, p in cases:
        res = r.oracle(records, c, p)
        rows.append({"name": name, "returncode": res["returncode"], "errors": res["errors"],
                     "ok": res["returncode"] == 1, "kind": "T17_probe"})
    return rows


def new_adverse(r: Runner):
    base, ctx, pin, b, es = build_base()
    w1, w2 = es[0], es[1]
    blob0 = blob_of(base, w2["cache_key"])

    def mut(fn):
        d = copy.deepcopy(base)
        fn(d)
        return d

    cases = []  # (name, records, context or None, pin, mode, disable, want_accept)

    # 1. AWZ origin relabeled to observed and claims training (schema-forced combination).
    def c1(d):
        d[3]["provenance"]["upstream"].update(origin="observed")
        d[3]["provenance"]["upstream"]["eligibility"] = {"train": True, "basis": "admit_training", "revision_ref": None}
    cases.append(("awz_origin_relabeled_train", mut(c1), ctx, pin, "validate", [], False))

    # 2. AWZ entry inherits the other source's eligibility from a trusted-looking context.
    def c2(d):
        d[3]["provenance"]["upstream"]["eligibility"] = copy.deepcopy(d[4]["provenance"]["upstream"]["eligibility"])
        d[3]["entry_id"] = entry_id(d[3])
    cases.append(("awz_external_derived_claims_train", mut(c2), ctx, pin, "validate", [], False))

    # 3. source timestamps not bound to the referenced blob (backdated copy).
    def c3(d):
        d[4]["source"]["timestamps_s"] = [0.0, 0.1]
        d[4]["source"]["timestamps_ticks"] = [0, 12]
    cases.append(("source_timestamps_unbound", mut(c3), ctx, pin, "validate", [], False))

    # 4. derivation weights forged.
    def c4(d):
        d[4]["provenance"]["derivation"]["weights_sha256"] = ["b" * 64]
    cases.append(("derivation_weights_forged", mut(c4), ctx, pin, "validate", [], False))

    # 5. derivation preprocess forged.
    def c5(d):
        d[4]["provenance"]["derivation"]["preprocess_spec_sha256"] = "c" * 64
    cases.append(("derivation_preprocess_forged", mut(c5), ctx, pin, "validate", [], False))

    # 6. entry self-advances the cutoff.
    def c6(d):
        d[4].update(as_of_t_ticks=999, as_of_t_s=999 / 120)
    cases.append(("self_advanced_cutoff", mut(c6), ctx, pin, "validate", [], False))

    # 7/8. cross observation time domain (episode / epoch).
    def c7(d):
        d[4]["source"]["time_domain"]["episode_id"] = "other-episode"
    cases.append(("cross_episode_id", mut(c7), ctx, pin, "validate", [], False))

    def c8(d):
        d[4]["source"]["time_domain"]["epoch_id"] = "other-epoch"
    cases.append(("cross_epoch_id", mut(c8), ctx, pin, "validate", [], False))

    # 9/10. approval registry replaced / non-empty pending.
    c9ctx = copy.deepcopy(ctx); c9ctx["approval_registry"]["registry_id"] = "adr-evil-current-20261016"
    cases.append(("registry_identity_replaced", mut(lambda d: None), c9ctx, canon_sha(c9ctx), "validate", [], False))
    c10ctx = copy.deepcopy(ctx)
    c10ctx["approval_registry"]["entries"] = [{"revision_ref": "synthetic-pending", "user_decision_ref": "x",
                                               "status": "pending", "source_scopes": []}]
    cases.append(("registry_pending_entry_fail_closed", mut(lambda d: None), c10ctx, canon_sha(c10ctx), "validate", [], False))

    # 11. feature teacher entry carries a noise model.
    def c11(d):
        d[3]["noise_model_ref"] = "nc-feature@1.0"
    cases.append(("feature_entry_with_noise", mut(c11), ctx, pin, "validate", [], False))

    # 12. blob tick/seconds drift with cache_key/copy consistently re-derived.
    def c12(d):
        blob = blob_of(d, w2["cache_key"])
        blob["key_material"]["input"]["timestamps_s"][1] += 0.001
        nk = canon_sha(blob["key_material"])
        blob["cache_key"] = nk
        for e in entries(d):
            if e["cache_key"] == w2["cache_key"] or (e["source"]["world_key"] == "awz:w1"):
                e["cache_key"] = nk
                e["source"]["timestamps_s"] = list(blob["key_material"]["input"]["timestamps_s"])
                e["entry_id"] = entry_id(e)
        d[3]["source"]["timestamps_s"] = list(blob["key_material"]["input"]["timestamps_s"])
    cases.append(("blob_tick_seconds_drift", mut(c12), context_for(mut(c12)), None, "validate", [], False))
    # pin: context_for produced above; recompute explicitly below to keep pin == context.

    # 13. entry_id forged.
    def c13(d):
        d[4]["entry_id"] = "a" * 64
    cases.append(("entry_id_forged", mut(c13), ctx, pin, "validate", [], False))

    # 14. derivation teacher forged.
    def c14(d):
        d[4]["provenance"]["derivation"]["teacher_id"] = "other-teacher"
    cases.append(("derivation_teacher_forged", mut(c14), ctx, pin, "validate", [], False))

    # 15. upstream input digest forged (entry rehashed).
    def c15(d):
        d[4]["provenance"]["upstream"]["input_ref"]["sha256"] = "b" * 64
        d[4]["entry_id"] = entry_id(d[4])
    cases.append(("upstream_input_forged", mut(c15), ctx, pin, "validate", [], False))

    # 16. orphan entry references an unknown blob.
    def c16(d):
        d[4]["cache_key"] = "f" * 64
        d[4]["entry_id"] = entry_id(d[4])
    cases.append(("orphan_entry", mut(c16), ctx, pin, "validate", [], False))

    # 17. same blob reused across partitions.
    def c17(d):
        e = copy.deepcopy(d[4])
        e["source"].update(world_key="gridlab:dev", partition="development")
        e["source"]["manifest_ref"]["source_id"] = "synthetic-source-dev"
        e["provenance"]["upstream"]["eligibility"] = {"train": False, "basis": "not_train_partition", "revision_ref": None}
        e["entry_id"] = entry_id(e)
        d.append(e)
    rec17 = mut(c17)
    cases.append(("cross_partition_blob", rec17, context_for(rec17), None, "validate", [], False))

    # 18. input entry reaches past the trusted observation cutoff.
    def c18(d):
        d[4].update(as_of_t_ticks=24, as_of_t_s=0.2)
    rec18 = [blob0, w2]
    r18 = mut(lambda d: None)
    r18 = copy.deepcopy([base[0], base[4]])
    r18[1].update(as_of_t_ticks=24, as_of_t_s=0.2)
    cases.append(("input_after_observation_cutoff", r18, context_for(r18, 24), None, "validate", [], False))

    # 19. cache_key forged but entries consistently reference it.
    def c19(d):
        blob = blob_of(d, w2["cache_key"])
        blob["cache_key"] = "0" * 64
        for e in entries(d):
            if e["source"]["world_key"] in ("awz:w1", "gridlab:w2"):
                e["cache_key"] = "0" * 64
                e["entry_id"] = entry_id(e)
    cases.append(("cache_key_forged_consistent", mut(c19), ctx, pin, "validate", [], False))

    # 20. unapproved ADR revision basis (future exception path).
    def c20(d):
        d[3]["provenance"]["upstream"]["eligibility"] = {"train": False, "basis": "adr_0005_revision",
                                                         "revision_ref": "not-an-approved-adr"}
    rec20 = mut(c20)
    cases.append(("unapproved_adr_revision", rec20, context_for(rec20), None, "validate", [], False))

    rows = []
    for name, records, c, p, mode, dis, want in cases:
        # fill pin for context-derived cases
        if p is None:
            p = canon_sha(c)
        res = r.oracle(records, c, p, mode, dis)
        rows.append({"name": name, "returncode": res["returncode"], "errors": res["errors"],
                     "want": "accept" if want else "reject",
                     "ok": (res["returncode"] == 0) == want, "kind": "new_adverse"})
    return rows


def positives(r: Runner):
    base, ctx, pin, b, es = build_base()
    rows = []
    # valid_store
    res = r.oracle(base, ctx, pin)
    rows.append({"name": "valid_store", "returncode": res["returncode"], "errors": res["errors"],
                 "ok": res["returncode"] == 0, "kind": "positive"})
    # cutoff_equals_last_frame
    rec = [base[0], base[4]]
    c = context_for(rec, 75)
    res = r.oracle(rec, c, canon_sha(c))
    rows.append({"name": "cutoff_equals_last_frame", "returncode": res["returncode"], "errors": res["errors"],
                 "ok": res["returncode"] == 0, "kind": "positive"})
    # future_target_isolated
    rec = [copy.deepcopy(base[0]), copy.deepcopy(base[4])]
    rec[1]["provenance"]["derivation"]["use"] = "target"
    rec[1]["entry_id"] = entry_id(rec[1])
    rec[1].update(as_of_t_ticks=24, as_of_t_s=0.2)
    c = context_for(rec, 24)
    res = r.oracle(rec, c, canon_sha(c))
    rows.append({"name": "future_target_isolated", "returncode": res["returncode"], "errors": res["errors"],
                 "ok": res["returncode"] == 0, "kind": "positive"})
    return rows


def isolation_new(r: Runner):
    """我的新反例：开规则拒、关规则收（真子进程）。"""
    cases = []
    base, ctx, pin, b, es = build_base()
    w1, w2 = es[0], es[1]

    def mk(fn):
        d = copy.deepcopy(base)
        fn(d)
        return d

    # (name, records, context, pin, mode, token)
    cases.append(("source_timestamps_unbound", mk(lambda d: (d[4]["source"].update(timestamps_s=[0.0, 0.1]),
                                                              d[4]["source"].update(timestamps_ticks=[0, 12]))),
                  ctx, pin, "validate", "source_times"))
    cases.append(("derivation_weights_forged", mk(lambda d: d[4]["provenance"]["derivation"].update(weights_sha256=["b" * 64])),
                  ctx, pin, "validate", "weights"))
    cases.append(("derivation_preprocess_forged", mk(lambda d: d[4]["provenance"]["derivation"].update(preprocess_spec_sha256="c" * 64)),
                  ctx, pin, "validate", "preprocess"))
    cases.append(("self_advanced_cutoff", mk(lambda d: d[4].update(as_of_t_ticks=999, as_of_t_s=999 / 120)),
                  ctx, pin, "validate", "cutoff"))
    cases.append(("cross_episode_id", mk(lambda d: d[4]["source"]["time_domain"].update(episode_id="other-episode")),
                  ctx, pin, "validate", "domain"))
    cases.append(("entry_id_forged", mk(lambda d: d[4].update(entry_id="a" * 64)), ctx, pin, "validate", "eid"))
    cases.append(("derivation_teacher_forged", mk(lambda d: d[4]["provenance"]["derivation"].update(teacher_id="other")),
                  ctx, pin, "validate", "teacher"))
    cases.append(("feature_entry_with_noise", mk(lambda d: d[3].update(noise_model_ref="nc-feature@1.0")),
                  ctx, pin, "validate", "noise"))
    cases.append(("source_binding_actor_forged",
                  mk(lambda d: d[3]["provenance"]["upstream"]["actor"].update(actor_id="copied-other-actor")),
                  ctx, pin, "validate", "binding"))

    # input digest forged, with context re-derived so only the input rule fires.
    d15 = mk(lambda d: (d[4]["provenance"]["upstream"]["input_ref"].update(sha256="b" * 64),
                        d[4].update(entry_id=entry_id(d[4]))))
    c15 = context_for(d15)
    cases.append(("upstream_input_forged", d15, c15, canon_sha(c15), "validate", "input"))

    # cache_key forged but every reference consistently updated.
    def kf(d):
        blob_of(d, w2["cache_key"])["cache_key"] = "0" * 64
        for e in entries(d):
            if e["source"]["world_key"] in ("awz:w1", "gridlab:w2"):
                e["cache_key"] = "0" * 64
                e["entry_id"] = entry_id(e)
        return d
    cases.append(("cache_key_forged_consistent", mk(kf), ctx, pin, "validate", "key"))
    c9 = copy.deepcopy(ctx); c9["approval_registry"]["registry_id"] = "adr-evil"
    cases.append(("registry_identity_replaced", base, c9, canon_sha(c9), "validate", "registry"))
    rec17 = mk(lambda d: d.append({**copy.deepcopy(d[4]), "entry_id": "x",
                                   "source": {**copy.deepcopy(d[4]["source"]), "world_key": "gridlab:dev",
                                              "partition": "development",
                                              "manifest_ref": {"manifest_id": "synthetic-original-sources-r3",
                                                               "source_id": "synthetic-source-dev"}}}))
    for e in entries(rec17)[1:]:
        if e["source"]["world_key"] == "gridlab:dev":
            e["provenance"]["upstream"]["eligibility"] = {"train": False, "basis": "not_train_partition", "revision_ref": None}
            e["entry_id"] = entry_id(e)
    cases.append(("cross_partition_blob", rec17, context_for(rec17), None, "validate", "cross"))
    r18 = copy.deepcopy([base[0], base[4]])
    r18[1].update(as_of_t_ticks=24, as_of_t_s=0.2)
    cases.append(("input_after_observation_cutoff", r18, context_for(r18, 24), None, "validate", "asof"))
    c19 = copy.deepcopy(ctx)
    c19["context_id"] = "synthetic-replaced-context"
    cases.append(("replaced_context_with_self_recomputed_hash", [base[0], base[4]], c19, pin, "validate", "context_identity"))

    # blob tick/seconds drift (only blob_tick_seconds_mismatch)
    d = copy.deepcopy(base)
    blob = blob_of(d, w2["cache_key"])
    blob["key_material"]["input"]["timestamps_s"][1] += 0.001
    nk = canon_sha(blob["key_material"])
    old = blob["cache_key"]
    blob["cache_key"] = nk
    for e in entries(d):
        if e["cache_key"] == old:
            e["cache_key"] = nk
            e["source"]["timestamps_s"] = list(blob["key_material"]["input"]["timestamps_s"])
            e["entry_id"] = entry_id(e)
    ctx12 = context_for(d)
    cases.append(("blob_tick_seconds_mismatch", d, ctx12, canon_sha(ctx12), "validate", "tick_seconds"))

    rows = []
    for name, records, c, p, mode, token in cases:
        if p is None:
            p = canon_sha(c)
        on = r.oracle(records, c, p, mode)
        off = r.oracle(records, c, p, mode, [token])
        rows.append({"name": name, "token": token,
                     "on_rc": on["returncode"], "on_errors": on["errors"],
                     "off_rc": off["returncode"], "off_errors": off["errors"],
                     "ok": on["returncode"] == 1 and off["returncode"] == 0, "kind": "isolation_new"})
    return rows


def qualification(r: Runner):
    base, ctx, pin, b, es = build_base()
    expected = {"awz:w1": False, "gridlab:w2": True, "gridlab:w3": True, "gridlab:w4": False}
    rows = []
    for e in es:
        blob = blob_of(base, e["cache_key"])
        rec = [blob, e]
        res = r.oracle(rec, ctx, pin, mode="eligible")
        want = expected[e["source"]["world_key"]]
        rows.append({"world_key": e["source"]["world_key"], "returncode": res["returncode"],
                     "eligible": res["returncode"] == 0, "expected": want,
                     "ok": (res["returncode"] == 0) == want})
    gates = []
    w2 = es[1]
    for gate in ("upstream", "teacher_license", "entry_license", "reproducibility", "partition"):
        rec = copy.deepcopy([base[0], w2])
        bl, en = rec
        if gate == "upstream":
            en["provenance"]["upstream"]["eligibility"]["train"] = False
        elif gate == "teacher_license":
            bl["teacher_license"]["scope"]["train"] = False
        elif gate == "entry_license":
            en["license"]["scope"]["train"] = False
        elif gate == "reproducibility":
            bl["reproducibility"] = "unverified"
        else:
            en["source"]["partition"] = "development"
            en["entry_id"] = entry_id(en)
        c = context_for(rec)
        val = r.oracle(rec, c, canon_sha(c), "validate")
        eli = r.oracle(rec, c, canon_sha(c), "eligible")
        gates.append({"gate": gate, "validate_rc": val["returncode"], "validate_errors": val["errors"],
                      "eligible_rc": eli["returncode"],
                      "ok": val["returncode"] == 0 and eli["returncode"] == 1})
    return rows, gates


def advisor(r: Runner):
    """资格入口不得只看交集：结构不合法的记录即使交集为真也必须拒。"""
    base, ctx, pin, b, es = build_base()
    w2 = es[1]
    rec = copy.deepcopy([base[0], w2])
    rec[1]["provenance"]["derivation"]["weights_sha256"] = ["b" * 64]  # fingerprint broken
    res_broken = r.oracle(rec, ctx, pin, "eligible")
    rec_ok = copy.deepcopy([base[0], w2])
    res_ok = r.oracle(rec_ok, ctx, pin, "eligible")
    return {"broken_rc": res_broken["returncode"], "broken_errors": res_broken["errors"],
            "clean_rc": res_ok["returncode"],
            "ok": res_broken["returncode"] == 1 and res_ok["returncode"] == 0}


def archive_check():
    """独立核对 r2 归档 SHA256SUMS（不调用作者脚本）。"""
    sums = R2_ARCHIVE / "SHA256SUMS"
    rows = []
    for line in sums.read_text().splitlines():
        if not line.strip():
            continue
        digest, path = line.split(None, 1)
        p = R2_ARCHIVE / path.strip()
        ok = p.exists() and sha_file(p) == digest
        rows.append({"path": path.strip(), "expected": digest, "ok": ok})
    return {"count": len(rows), "ok": sum(x["ok"] for x in rows), "all_ok": all(x["ok"] for x in rows), "rows": rows}


def main():
    ts = time.strftime("%Y%m%dT%H%M%S")
    run_dir = OUT / "runtime" / ts
    run_dir.mkdir(parents=True, exist_ok=True)
    workdir = run_dir / "cases"
    r = Runner(workdir)

    before = snapshot()

    author = author_suite(run_dir)
    archive = archive_check()
    fixtures = crosscheck_fixtures(r)
    iso_fixtures = isolation_map_fixtures(r)
    t17 = t17_probes(r)
    adverse = new_adverse(r)
    pos = positives(r)
    iso_new = isolation_new(r)
    qual, gates = qualification(r)
    adv = advisor(r)

    after = snapshot()
    changed = sorted(k for k in before if before.get(k) != after.get(k))
    added = sorted(k for k in after if k not in before)

    claims = {"positive_cases": 3, "negative_cases": 41, "r3_controls": 29,
              "r3_isolated_controls": 29, "r2_sabotage": 11}
    author_ok = (author["returncode"] == 0 and author.get("all_ok") is True
                 and author.get("counts") == claims and author.get("failures") == []
                 and author.get("control_failures") == []
                 and author.get("nonisolated") == []
                 and author.get("archives_ok") is True
                 and author.get("legacy_r2_ok") is True
                 and author.get("fixtures_reproduced") is True)

    summary = {
        "author_suite_ok": author_ok,
        "r2_archive_sums": {"count": archive["count"], "ok": archive["ok"]},
        "fixtures_crosscheck": {"count": len(fixtures), "ok": sum(x["ok"] for x in fixtures)},
        "isolation_author_fixtures": {"count": len(iso_fixtures), "ok": sum(x["ok"] for x in iso_fixtures)},
        "t17_probes": {"count": len(t17), "ok": sum(x["ok"] for x in t17)},
        "new_adverse": {"count": len(adverse), "ok": sum(x["ok"] for x in adverse)},
        "positives": {"count": len(pos), "ok": sum(x["ok"] for x in pos)},
        "isolation_new": {"count": len(iso_new), "ok": sum(x["ok"] for x in iso_new)},
        "qualification": {"count": len(qual), "ok": sum(x["ok"] for x in qual)},
        "intersection_gates": {"count": len(gates), "ok": sum(x["ok"] for x in gates)},
        "advisor": adv["ok"],
        "protected_unchanged": not changed and not added,
    }
    summary["all_ok"] = all([
        summary["author_suite_ok"],
        archive["all_ok"],
        summary["fixtures_crosscheck"]["ok"] == summary["fixtures_crosscheck"]["count"],
        summary["isolation_author_fixtures"]["ok"] == summary["isolation_author_fixtures"]["count"],
        summary["t17_probes"]["ok"] == summary["t17_probes"]["count"],
        summary["new_adverse"]["ok"] == summary["new_adverse"]["count"],
        summary["positives"]["ok"] == summary["positives"]["count"],
        summary["isolation_new"]["ok"] == summary["isolation_new"]["count"],
        summary["qualification"]["ok"] == summary["qualification"]["count"],
        summary["intersection_gates"]["ok"] == summary["intersection_gates"]["count"],
        summary["advisor"],
        summary["protected_unchanged"],
    ])

    metrics = {
        "task_id": "ainerzero.V9.T18",
        "agent": "big-pickle-d98w",
        "revision_under_review": "ainerzero.V9.T1 r3 (author catjam-m9v2)",
        "timestamp": ts,
        "python": PY,
        "inputs": {
            "schema": {"path": str(SCHEMA), "sha256": sha_file(SCHEMA)},
            "docs": {"path": str(DOCS), "sha256": sha_file(DOCS)},
            "author_checker": {"path": str(AUTHOR_CHECKER), "sha256": sha_file(AUTHOR_CHECKER)},
            "oracle": {"path": str(ORACLE), "sha256": sha_file(ORACLE)},
            "driver": {"path": str(Path(__file__)), "sha256": sha_file(Path(__file__))},
        },
        "author_claims": claims,
        "author_suite": author,
        "r2_archive": archive,
        "fixtures_crosscheck": fixtures,
        "isolation_author_fixtures": iso_fixtures,
        "t17_probes": t17,
        "new_adverse": adverse,
        "positives": pos,
        "isolation_new": iso_new,
        "qualification": qual,
        "intersection_gates": gates,
        "advisor": adv,
        "protected_before": before,
        "protected_changed": changed,
        "protected_added": added,
        "summary": summary,
    }
    (OUT / "metrics.json").write_text(json.dumps(metrics, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if summary["all_ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
