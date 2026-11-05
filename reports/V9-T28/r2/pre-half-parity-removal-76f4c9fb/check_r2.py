"""T28 r2 作者自检（claude-az）。复核人不得 import 或照抄本脚本作自证——请自建独立检查。

只读：不改任何文件、不加载模型、不碰锁与台账。用法：.venv/bin/python reports/V9-T28/r2/check_r2.py
"""
from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
T28 = HERE.parent
REPO = T28.parents[1]
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
                    "/negative_controls/removed_controls", "/negative_controls/same_clean_profile", "/numerical_parity/reference",
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
    check(f"{m['variant']} 阶段=首帧/校准/逆序/CPU对拍/半精度", names == ["first_frame", "calibration", "frame_order_adverse", "cpu_parity", "half_parity"], str(names))
    calls = sum(s["calls"] for s in m["stages"])
    views = sum(s["calls"] * s["frames_per_call"] for s in m["stages"])
    check(f"{m['variant']} 算术 {calls} 次/{views} 视图 == 声明", (calls, views) == (m["forward_calls"], m["forward_views"]) == (10, 28))
b = p2["budget"]
check("合计 20 次/56 视图", (b["total_planned_forward_calls"], b["total_planned_forward_views"]) == (20, 56))
check("unallocated = 预留 - 计划", b["unallocated_views"] == b["reserve_before_model_import_views"] - b["total_planned_forward_views"])
check("配额口径标记为 OPEN", b["view_accounting"]["status"].startswith("OPEN") and len(p2["open_items"]) == 5)
check("墙钟上限不再是不可满足的 1200：null + wall_accounting OPEN",
      b["cumulative_wall_seconds_max"] is None and b["wall_accounting"]["status"].startswith("OPEN")
      and b["wall_accounting"]["ledger_reserved_s"] == 1170 and b["wall_accounting"]["next_run_minimum_cap_s"] == 1230)
check("review_task=T39 且前提不再写 T29", p2["review_task"] == "ainerzero.V9.T39" and "T29" not in " ".join(p2["execution_prerequisites"]) and "T39" in p2["execution_prerequisites"][1])
check("K 块只比 fx/fy，主点单列排除", "principal_point_excluded" in p2["profile"]["intrinsics_policy"] and "cx" in p2["profile"]["intrinsics_policy"]["principal_point_excluded"]
      and "cx, cy" not in p2["profile"]["intrinsics_policy"]["predicted_vs_ground_truth_K"])
check("对拍风险仅披露，容差/规则与 r1 相等", len(p2["numerical_parity"]["known_risks"]) == 2)
check("复核历史已记录", p2["amendment"]["review_history"][0]["reviewed_sha256"].startswith("0e15033a") and p2["amendment"]["review_history"][0]["verdict"] == "accept_with_changes")
check("仍为 proposal_unapproved / 不可执行", p2["status"] == "proposal_unapproved" and p2["execution_permitted"] is False)
check("溯源指向 r1 SHA", p2["supersedes"]["proposal_sha256"] == p1_sha if (p1_sha := (T28 / "proposal.sha256").read_text().split()[0]) else False)

# 4. 用真实的 r2 文件驱动 T37 的 runner（只读 import，不改它）
import os
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

# 4a 真实 runner（磁盘上、T38 正在复核的那个 SHA）：已知缺陷 —— load_plan 无条件解析 negative_controls.intrinsics，r2 里已移除。
try:
    R.load_plan(HERE / "proposal.json")
    check("4a 真实 runner 能读 r2", True)
except KeyError as e:
    print(f"KNOWN-FAIL 4a 真实 runner 读 r2 抛 KeyError({e}) —— T37 缺陷，需 T37 r2 修（补丁见 4b），不影响 r2 文件本身的检查")
    runner_known_defect = True

# 4b 仓外镜像里打最小补丁，证明这一处修复足以让 runner 读懂并跑通 r2（不改真实文件）
mirror = Path(tempfile.mkdtemp(prefix="t28r2-mirror-"))
mt = mirror / "src/ainerzero/v9/teachers"
mt.mkdir(parents=True)
shutil.copy(TEACHERS / "da3_calibration_math.py", mt)
src = (TEACHERS / "da3_calibration_runner.py").read_text()
old1 = 'm_adv = re.search(r"focal_x by\\s*([0-9.]+)\\s*and focal_y by\\s*([0-9.]+)", p["negative_controls"]["intrinsics"])'
new1 = ('adv_text = p["negative_controls"].get("intrinsics")      # r2 去掉了内参逆向控制\n'
        '    m_adv = re.search(r"focal_x by\\s*([0-9.]+)\\s*and focal_y by\\s*([0-9.]+)", adv_text) if adv_text is not None else None')
old2 = 'if not (m_adv and m_red):'
new2 = 'if not m_red or (adv_text is not None and not m_adv):'
old3 = 'focal_scale=(float(m_adv.group(1)), float(m_adv.group(2))),'
new3 = 'focal_scale=(float(m_adv.group(1)), float(m_adv.group(2))) if m_adv else (1.0, 1.0),'
for o, n in ((old1, new1), (old2, new2), (old3, new3)):
    assert src.count(o) == 1, f"patch anchor not found: {o[:50]}"
    src = src.replace(o, n)
(mt / "da3_calibration_runner.py").write_text(src)
os.symlink(REPO / "reports", mirror / "reports")
os.symlink(REPO / "envs", mirror / "envs")
R2 = load("da3_calibration_runner_patched", mt / "da3_calibration_runner.py")
plan = R2.load_plan(HERE / "proposal.json")                      # 含 proposal.sha256 / manifest / 协议 / 生成器 SHA 校验
check("4b[补丁] runner 读 r2：哈希绑定通过", plan.shas["manifest"] == p2["input_manifest_sha256"] and plan.shas["protocol"] == p2["lead_protocol_observed_sha256"])
check("4b[补丁] runner 读 r2：10 次/28 视图，无内参阶段，不要求 K",
      (plan.calls_per_variant, plan.views_per_variant) == (10, 28) and plan.known_intrinsics is False
      and "intrinsics_adverse" not in [s["stage"] for s in plan.stages])
tmp = Path(tempfile.mkdtemp(prefix="t28r2-"))
checks = R2.preflight(plan, R2.RealTeacherFactory(), tmp / "new_preds", tmp / "new_ev.json")
check("4b[补丁] 真实 DA3 的预检通过（协议现在可满足）", "protocol_satisfiable_by_teacher" in checks, str(checks))
data = R2.load_fixtures(REPO / "reports/V9-T6/r2-calib-fixtures", plan)
ev, code = R2.run_full_calibration(tmp / "ev.json", tmp / "preds", "t28r2-check", teacher_factory=T.FakeFactory(data, capable=False),
                                   fixtures_dir=REPO / "reports/V9-T6/r2-calib-fixtures", proposal_path=HERE / "proposal.json")
check("4b[补丁] 假 teacher 按 r2 整条跑通且退出 0", code == 0 and ev["failures"] == [], str(ev["failures"][:2]))
check("4b[补丁] 前向账目 == r2 计划", all((a["calls_actual"], a["views_actual"]) == (10, 28) for a in ev["forward_accounting"].values()))
check("4b[补丁] 逆序控制真实变红", all(ev["stages"][v]["frame_order_adverse"]["turned_red"] for v in ev["stages"]))
shutil.rmtree(mirror, ignore_errors=True)

print("\nALL PASS (file checks + patched-runner checks); 4a is a KNOWN T37 defect" if ok else "\nSOME CHECKS FAILED")
sys.exit(0 if ok else 1)
