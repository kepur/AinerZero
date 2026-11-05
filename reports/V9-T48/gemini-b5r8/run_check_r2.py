"""T28 r2 作者自检（claude-az）。复核人不得 import 或照抄本脚本作自证——请自建独立检查。

只读：不改任何文件、不加载模型、不碰锁与台账。用法：.venv/bin/python reports/V9-T28/r2/check_r2.py
"""
from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
T28 = REPO / "reports/V9-T28"
HERE = T28 / "r2"
DA3_SRC_PATH = REPO / "envs/teachers/t6/Depth-Anything-3/src/depth_anything_3"
p1 = json.loads((T28 / "proposal.json").read_text())
p2 = json.loads((HERE / "proposal.json").read_text())
diff = json.loads((HERE / "diff_r1_r2.json").read_text())["changed_paths"]
ok = True


def check(name, cond, detail=""):
    global ok
    ok = ok and bool(cond)
    print(("PASS " if cond else "FAIL ") + name + (f"  {detail}" if detail else ""))


# 1. 差异只落在被批准的范围内
allowed_prefixes = ("/amendment", "/author", "/budget/models", "/budget/total_planned", "/budget/unallocated_views", "/budget/view_accounting",
                    "/claims_forbidden", "/execution_prerequisites", "/negative_controls/intrinsics", "/negative_controls/real_forward_controls",
                    "/negative_controls/removed_controls", "/negative_controls/same_clean_profile", "/numerical_parity/reference", "/numerical_parity/retired_stages",
                    "/open_items", "/budget/cumulative_wall_seconds_max", "/budget/wall_accounting", "/numerical_parity/known_risks", "/negative_controls/frame_order_adverse_meaning", "/profile/assumption", "/profile/intrinsics_policy", "/profile/known_intrinsics", "/protocol_id",
                    "/residual_vector/raw_metrics", "/review_task", "/supersedes")
stray = [d["path"] for d in diff if not d["path"].startswith(allowed_prefixes)]
check("差异路径全部在枚举范围内", not stray, str(stray))

# 2. 未改动的口径与 r1 完全相等（用 canonical JSON 比较）
canon = lambda v: json.dumps(v, sort_keys=True, ensure_ascii=False)
same_keys = ["alignment", "estimation", "split", "failure_policy", "input_manifest_sha256", "lead_protocol_observed_sha256",
             "generator_sha256", "schema", "status", "execution_permitted", "task_id"]
for k in same_keys:
    check(f"未改动: {k}", canon(p1[k]) == canon(p2[k]))
check("未改动: residual_vector.order/depth_component/dimension",
      all(canon(p1["residual_vector"][k]) == canon(p2["residual_vector"][k]) for k in ("order", "depth_component", "dimension")))
check("未改动: numerical_parity 容差/字段/规则",
      all(canon(p1["numerical_parity"][k]) == canon(p2["numerical_parity"][k])
          for k in ("cpu_float32", "mps_float16", "fields", "require_same_shapes_and_finite", "rule")))
check("未改动: negative_controls score/required_red/frames/boundary/unrelated",
      all(canon(p1["negative_controls"][k]) == canon(p2["negative_controls"][k])
          for k in ("score", "required_red", "frames", "boundary_rejection", "unrelated_error", "require_real_forward")))
check("未改动: budget 墙钟/RSS/常驻/重试",
      all(canon(p1["budget"][k]) == canon(p2["budget"][k]) for k in
          ("single_run_wall_seconds_max", "reserve_before_model_import_seconds",
           "reserve_before_model_import_views", "rss_bytes_max", "max_resident_models", "retry_allowed",
           "include_loads_postprocess_and_all_controls_in_wall")))
check("未改动: profile 其余字段(process_res/尺寸/外参不提供)",
      all(p1["profile"][k] == p2["profile"][k] for k in ("process_res", "image_width", "image_height", "extrinsics_supplied_to_teacher",
                                                         "partition", "scene_layer")))

# 3. 被批准的修改确实发生
check("known_intrinsics=false", p2["profile"]["known_intrinsics"] is False and p2["profile"]["intrinsics_policy"]["conditioning"] == "none")
check("内参逆向控制已移除", "intrinsics" not in p2["negative_controls"] and p2["negative_controls"]["removed_controls"][0]["name"] == "intrinsics_adverse")
check("逆序控制保留且为唯一真实前向控制", "frames" in p2["negative_controls"] and p2["negative_controls"]["real_forward_controls"] == ["frame_order_adverse"])
for m in p2["budget"]["models"]:
    names = [s["stage"] for s in m["stages"]]
    check(f"{m['variant']} 阶段=首帧/校准/逆序/CPU对拍（无内参逆向、无半精度）", names == ["first_frame", "calibration", "frame_order_adverse", "cpu_parity"], str(names))
    check(f"{m['variant']} 没有任何 float16 阶段", all(s["precision"] == "float32" for s in m["stages"]))
    calls = sum(s["calls"] for s in m["stages"])
    views = sum(s["calls"] * s["frames_per_call"] for s in m["stages"])
    check(f"{m['variant']} 算术 {calls} 次/{views} 视图 == 声明", (calls, views) == (m["forward_calls"], m["forward_views"]) == (9, 25))
b = p2["budget"]
check("合计 18 次/50 视图", (b["total_planned_forward_calls"], b["total_planned_forward_views"]) == (18, 50))
check("预留 64 不变，unallocated = 14", b["reserve_before_model_import_views"] == 64 and b["unallocated_views"] == 14)
check("unallocated = 预留 - 计划", b["unallocated_views"] == b["reserve_before_model_import_views"] - b["total_planned_forward_views"])
va = b["view_accounting"]
check("记账口径：用户已定前向视图、每次 50，数字待告知（不是配额批准）",
      va["status"] == "BASIS_DECIDED_NUMBERS_PENDING" and va["basis"] == "forward_views" and va["charge_per_complete_run"] == 50
      and "前向视图" in va["decided_by_user"]["verbatim"] and "不要动账本" in va["decided_by_user"]["verbatim"]
      and "Nothing here is a quota approval" in va["numbers_pending"] and "REGISTERED_CALIBRATION_VIEWS" in va["downstream_consequence"])
check("open_items 4 条且包含 REGISTERED_CALIBRATION_VIEWS 的后续", len(p2["open_items"]) == 4 and any("REGISTERED_CALIBRATION_VIEWS" in x for x in p2["open_items"]))
check("墙钟上限不再是不可满足的 1200：null + wall_accounting OPEN",
      b["cumulative_wall_seconds_max"] is None and b["wall_accounting"]["status"].startswith("OPEN")
      and b["wall_accounting"]["ledger_reserved_s"] == 1170 and b["wall_accounting"]["next_run_minimum_cap_s"] == 1230)
check("review_task=T39 且前提不再写 T29", p2["review_task"] == "ainerzero.V9.T39" and "T29" not in " ".join(p2["execution_prerequisites"]) and "T39" in p2["execution_prerequisites"][1])
check("K 块只比 fx/fy，主点单列排除", "principal_point_excluded" in p2["profile"]["intrinsics_policy"] and "cx" in p2["profile"]["intrinsics_policy"]["principal_point_excluded"]
      and "cx, cy" not in p2["profile"]["intrinsics_policy"]["predicted_vs_ground_truth_K"])
check("对拍风险仅披露（只剩 argmin 一条），容差/规则与 r1 相等", len(p2["numerical_parity"]["known_risks"]) == 1
      and "fp16" not in p2["numerical_parity"]["known_risks"][0])

# 3b. E15：half_parity 退役——只有阶段消失，别的什么都没动；证据与磁盘一致
import hashlib


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


rs = p2["numerical_parity"]["retired_stages"]
check("退役记录恰有一条 half_parity，容差键原值保留且标为未使用",
      len(rs) == 1 and rs[0]["stage"] == "half_parity" and rs[0]["tolerance_key"] == "mps_float16"
      and rs[0]["tolerance_kept_unchanged_and_unused"] is True and p2["numerical_parity"]["mps_float16"] == p1["numerical_parity"]["mps_float16"])
ev_cam, ev_pipe = rs[0]["evidence"]["cam_dec"], rs[0]["evidence"]["pipeline"]
check("退役证据：cam_dec 行号/文件 SHA 与磁盘一致",
      _sha(REPO / ev_cam["file"]) == ev_cam["sha256"] and "self.fc_t(feat.float())" in (REPO / ev_cam["file"]).read_text().splitlines()[ev_cam["line"] - 1])
check("退役证据：pipeline 行号/文件 SHA 与磁盘一致（pipeline.py 未被本次修订改动）",
      _sha(REPO / ev_pipe["file"]) == ev_pipe["sha256"] and "ExplicitPrecisionDA3" in (REPO / ev_pipe["file"]).read_text().splitlines()[ev_pipe["line"] - 1])
check("未引入替代 fp16 控制", "no substitute" in rs[0]["not_replaced"] and p2["negative_controls"]["real_forward_controls"] == ["frame_order_adverse"])
sealed = HERE / "pre-half-parity-removal-76f4c9fb"
prev = {r["sha256"][:8]: r for r in p2["amendment"]["previous_revisions"]}
check("上一版 76f4c9fb 原样封存且 SHA 对得上",
      "76f4c9fb" in prev and _sha(sealed / "proposal.json") == prev["76f4c9fb"]["sha256"]
      and json.loads((sealed / "proposal.json").read_text())["budget"]["total_planned_forward_views"] == 56)
check("T39 复核版 0e15033a 仍在", "0e15033a" in prev and _sha(HERE / "reviewed-0e15033a" / "proposal.json") == prev["0e15033a"]["sha256"])
sec = p2["amendment"]["approved_by_user_second"]
sealed16 = HERE / "pre-E16-86f5ece6"
check("E16 之前的 86f5ece6 原样封存且 SHA 对得上", "86f5ece6" in prev and _sha(sealed16 / "proposal.json") == prev["86f5ece6"]["sha256"])
old16 = json.loads((sealed16 / "proposal.json").read_text())
ch16 = sorted(k for k in set(old16) | set(p2) if canon(old16.get(k)) != canon(p2.get(k)))
check("相对 86f5ece6（T46 复核对象）只动了 amendment/budget/numerical_parity/open_items", ch16 == ["amendment", "budget", "numerical_parity", "open_items"], str(ch16))
chb = sorted(k for k in set(old16["budget"]) | set(p2["budget"]) if canon(old16["budget"].get(k)) != canon(p2["budget"].get(k)))
chn = sorted(k for k in set(old16["numerical_parity"]) | set(p2["numerical_parity"]) if canon(old16["numerical_parity"].get(k)) != canon(p2["numerical_parity"].get(k)))
check("E16：budget 只动了 view_accounting，numerical_parity 只动了 retired_stages", chb == ["view_accounting"] and chn == ["retired_stages"], f"{chb} {chn}")
rs0 = p2["numerical_parity"]["retired_stages"][0]
check("E16：MPS 结论标为作者报告、CPU 复现署名、autocast 说法限定在 .venv-t6 且指向 da3.py:139",
      "report, not an independently reproduced fact" in rs0["reason"] and "V9.T46" in rs0["reason"] and ".venv-t6" in rs0["reason"]
      and "model/da3.py:139" in rs0["not_replaced"] and "no-op" not in rs0["not_replaced"])
check("E16：T46 必改项记录在 review_history，未照单全收的一条写明原因",
      p2["amendment"]["review_history"][-1]["review_task"] == "ainerzero.V9.T46" and p2["amendment"]["review_history"][-1]["not_applied_as_written"][0]["why"].startswith("checked in envs/teachers/.venv-t6"))
check("da3.py:139 确是 depth head+相机估计的 autocast(enabled=False) 段",
      "autocast(device_type=x.device.type, enabled=False)" in (DA3_SRC_PATH / "model/da3.py").read_text().splitlines()[138]
      and "_process_depth_head" in (DA3_SRC_PATH / "model/da3.py").read_text().splitlines()[139])
third = p2["amendment"]["approved_by_user_third"]
check("第三次决定逐字记录", "前向视图" in third["verbatim"] and "每次记 50" in third["verbatim"])
check("第二次批准逐字记录：删除 half_parity、cpu_parity 保持现状、配额未定",
      "half_parity" in sec["verbatim"] and "cpu_parity 保持现状" in sec["verbatim"] and any("quota" in d for d in sec["decisions"]))
# 与上一版（76f4c9fb）相比，只有预算/对拍风险/开放事项/修订记录发生变化
old = json.loads((sealed / "proposal.json").read_text())
changed_vs_prev = sorted(k for k in set(old) | set(p2) if canon(old.get(k)) != canon(p2.get(k)))
check("相对上一版只动了 amendment/budget/numerical_parity/open_items", changed_vs_prev == ["amendment", "budget", "numerical_parity", "open_items"], str(changed_vs_prev))
sub_changed = sorted(k for k in set(old["numerical_parity"]) | set(p2["numerical_parity"]) if canon(old["numerical_parity"].get(k)) != canon(p2["numerical_parity"].get(k)))
check("numerical_parity 内只动了 known_risks 与 retired_stages", sub_changed == ["known_risks", "retired_stages"], str(sub_changed))
bud_changed = sorted(k for k in set(old["budget"]) | set(p2["budget"]) if canon(old["budget"].get(k)) != canon(p2["budget"].get(k)))
check("budget 内只动了 models/总数/unallocated/view_accounting", bud_changed == ["models", "total_planned_forward_calls", "total_planned_forward_views", "unallocated_views", "view_accounting"], str(bud_changed))
for mo, mn in zip(old["budget"]["models"], p2["budget"]["models"]):
    check(f"{mn['variant']}：除删掉 half_parity 外，其余阶段逐字未变", mo["variant"] == mn["variant"] and [s for s in mo["stages"] if s["stage"] != "half_parity"] == mn["stages"])
check("复核历史已记录", p2["amendment"]["review_history"][0]["reviewed_sha256"].startswith("0e15033a") and p2["amendment"]["review_history"][0]["verdict"] == "accept_with_changes")
check("仍为 proposal_unapproved / 不可执行", p2["status"] == "proposal_unapproved" and p2["execution_permitted"] is False)
check("溯源指向 r1 SHA", p2["supersedes"]["proposal_sha256"] == p1_sha if (p1_sha := (T28 / "proposal.sha256").read_text().split()[0]) else False)

# 4. 用真实的 r2 文件驱动当前 runner（T40 已能读 r2；只读 import，不改它；零模型，假 teacher）
import shutil


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


TEACHERS = REPO / "src/ainerzero/v9/teachers"
R = load("da3_calibration_runner", TEACHERS / "da3_calibration_runner.py")
T = load("t37_tests", REPO / "tests/test_da3_calibration_runner.py")

plan = R.load_plan(HERE / "proposal.json")                      # 含 proposal.sha256 / manifest / 协议 / 生成器 SHA 校验
check("4 runner 读 r2：哈希绑定通过", plan.shas["manifest"] == p2["input_manifest_sha256"] and plan.shas["protocol"] == p2["lead_protocol_observed_sha256"])
check("4 runner 读 r2：9 次/25 视图，阶段为首帧/校准/逆序/CPU对拍，不要求 K",
      (plan.calls_per_variant, plan.views_per_variant) == (9, 25) and plan.known_intrinsics is False
      and [s["stage"] for s in plan.stages] == ["first_frame", "calibration", "frame_order_adverse", "cpu_parity"])
tmp = Path(tempfile.mkdtemp(prefix="t28r2-"))
checks = R.preflight(plan, R.RealTeacherFactory(), tmp / "new_preds", tmp / "new_ev.json")
check("4 真实 DA3 的预检通过（协议现在可满足）", "protocol_satisfiable_by_teacher" in checks, str(checks))
data = R.load_fixtures(REPO / "reports/V9-T6/r2-calib-fixtures", plan)
factory = T.FakeFactory(data, capable=False)
ev, code = R.run_full_calibration(tmp / "ev.json", tmp / "preds", "t28r2-check", teacher_factory=factory,
                                  fixtures_dir=REPO / "reports/V9-T6/r2-calib-fixtures", proposal_path=HERE / "proposal.json")
check("4 假 teacher 按 r2 整条跑通且退出 0", code == 0 and ev["failures"] == [], str(ev["failures"][:2]))
check("4 前向账目 == r2 计划（9 次/25 视图）", all((a["calls_actual"], a["views_actual"]) == (9, 25) for a in ev["forward_accounting"].values()))
check("4 逆序控制真实变红", all(ev["stages"][v]["frame_order_adverse"]["turned_red"] for v in ev["stages"]))
check("4 没有任何 float16 的 make()，每型号只加载 2 次（MPS/F32 一次 + CPU/F32 一次）",
      all(c[2] == "float32" for c in factory.made) and len(factory.made) == 4, str(factory.made))
shutil.rmtree(tmp, ignore_errors=True)

print("\nALL PASS" if ok else "\nSOME CHECKS FAILED")
sys.exit(0 if ok else 1)
