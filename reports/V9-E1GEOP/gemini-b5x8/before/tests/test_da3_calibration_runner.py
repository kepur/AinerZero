"""V9.T37：DA3 标定 runner 与数学模块的测试。纯 CPU，不加载任何模型，不碰锁与台账。

背景：T35 r2 的唯一一次授权真跑崩在 `paired depth shapes must agree`，而全仓库当时没有任何测试引用
da3_calibration_runner。复核发现除尺寸外还有：w2c 被当成 c2w、用绝对位姿比较、写死的结论字段、
未执行却写 verified 的逆向控制、T28 的内参控制在该 DA3 上不可满足。本文件每一类都有会失败的回归用例。
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import re
import shutil
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

REPO = Path(__file__).resolve().parents[1]
FIX = REPO / "reports/V9-T6/r2-calib-fixtures"
T28 = REPO / "reports/V9-T28/proposal.json"
pytestmark = pytest.mark.skipif(not (FIX / "manifest.json").is_file() or not T28.is_file(),
                                reason="frozen T6/T28 fixtures not present")


def _load(name):
    path = REPO / "src/ainerzero/v9/teachers" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    import sys
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


M = _load("da3_calibration_math")
R = _load("da3_calibration_runner")


# ───────────────────────────── 假 teacher ─────────────────────────────
def _rot(axis, ang):
    c, s = np.cos(ang), np.sin(ang)
    return {"x": np.array([[1, 0, 0], [0, c, -s], [0, s, c]]), "y": np.array([[c, 0, s], [0, 1, 0], [-s, 0, c]]),
            "z": np.array([[c, -s, 0], [s, c, 0], [0, 0, 1]])}[axis]


class FakeTeacher:
    """从夹具 GT 出发的 teacher：全局相似变换 + 未知尺度（=真实 DA3 的坐标系性质）+ 受控扰动。"""

    def __init__(self, f, variant, device, dtype):
        self.f, self.variant, self.device, self.dtype = f, variant, device, dtype
        self.Q, self.t0, self.scale = _rot("x", 0.7) @ _rot("y", -0.4), np.array([3.0, -1.0, 2.0]), 0.37

    def process_keyframes(self, images, timestamps_s=None, world_key=None, partition="development",
                          output_dir=None, process_res=504, intrinsics=None):
        n = len(images)
        if timestamps_s is None or len(timestamps_s) != n:
            raise ValueError("one explicit timestamp per frame is required")
        if output_dir is not None:
            d = Path(output_dir)
            if d.exists():
                raise ValueError("output must be a new directory; never overwrite prior evidence")
            d.mkdir(parents=True)
            (d / "prediction.safetensors").write_bytes(b"fake" + bytes([n]))
        self.f.calls.append((self.variant, self.device, self.dtype, n, process_res, intrinsics is not None))
        views = self.f.data[world_key]
        idx = ([self.f.lookup[hashlib.sha256(im.tobytes()).hexdigest()] for im in images]
               if self.f.by_content else [(world_key, i) for i in range(n)])
        extra = 0.0
        if intrinsics is not None and self.f.k_effect:
            gt_k = views[0]["K"]
            extra = 0.2 * (intrinsics[0, 0, 0] / gt_k[0, 0] - 1) + 0.2 * (1 - intrinsics[0, 1, 1] / gt_k[1, 1])
        c2w, depth = [], []
        for k, (_, v) in enumerate(idx):
            g = views[v]["c2w"]
            # pose_noise>0：每个世界、每个位置给不同的绕 z 小转角，使 7 维残差在各世界之间真的不同（否则协方差恒≈0，
            # 无法区分分母 N 与 N-1、也看不出 holdout 是否混入 fit）。
            wnoise = self.f.pose_noise * (int(str(world_key)[-1]) + 1) * k
            r = self.Q @ g[:3, :3] @ _rot("y", k * extra) @ _rot("z", wnoise)
            c2w.append(np.vstack([np.hstack([r, (self.scale * (self.Q @ g[:3, 3]) + self.t0)[:, None]]), [0, 0, 0, 1]]))
            depth.append(views[v]["depth"] * self.scale)
        depth = np.stack(depth).astype(np.float32)
        hw = self.f.out_hw
        if hw is not None and tuple(hw) != depth.shape[1:]:
            depth = np.stack([np.array(Image.fromarray(d).resize((hw[1], hw[0]))) for d in depth])
        w2c = np.linalg.inv(np.stack(c2w))[:, :3, :4].astype(np.float32)
        out = {"depth": depth, "confidence": np.full(depth.shape, 0.9, np.float32), "extrinsics": w2c,
               "intrinsics": np.stack([views[v]["K"] for _, v in idx]).astype(np.float32)}
        eps = {("cpu", "float32"): self.f.cpu_eps, ("mps", "float16"): self.f.half_eps}.get((self.device, self.dtype), 0.0)
        if eps:
            only = self.f.eps_only_field          # None=全部字段；否则只扰动该字段（T38 NEW-5：对拍不能退化成只比 depth）
            out = {k2: (v2 * (1 + eps) if only in (None, k2) else v2) for k2, v2 in out.items()}
        out["pose_3x4"] = out["extrinsics"]
        return out


class FakeFactory:
    def __init__(self, data, capable=True, by_content=True, k_effect=True, cpu_eps=5e-4, half_eps=5e-3, out_hw=None,
                 eps_only_field=None, pose_noise=0.0):
        self.eps_only_field, self.pose_noise = eps_only_field, pose_noise
        self.data, self.conditions_on_intrinsics_only = data, capable
        self.by_content, self.k_effect, self.cpu_eps, self.half_eps, self.out_hw = by_content, k_effect, cpu_eps, half_eps, out_hw
        self.calls, self.made, self.live, self.max_live = [], [], 0, 0
        self.lookup = {hashlib.sha256(v["image"].tobytes()).hexdigest(): (w, i)
                       for w, vs in data.items() for i, v in enumerate(vs)}

    def make(self, variant, device, dtype):
        self.made.append((variant, device, dtype))
        self.live += 1
        self.max_live = max(self.max_live, self.live)
        return FakeTeacher(self, variant, device, dtype)

    def release(self, teacher):
        self.live -= 1


@pytest.fixture(scope="module")
def plan():
    return R.load_plan(T28, verify_hashes=False)


@pytest.fixture(scope="module")
def data(plan):
    return R.load_fixtures(FIX, plan)


def _run(tmp_path, factory, **kw):
    return R.run_full_calibration(tmp_path / "ev.json", tmp_path / "preds", "ainerzero.V9.T37-test",
                                  teacher_factory=factory, proposal_path=kw.pop("proposal_path", T28),
                                  verify_hashes=kw.pop("verify_hashes", False), **kw)


# ───────────────────────────── 数学：每个已知缺陷一条 ─────────────────────────────
def test_original_crash_shape_mismatch_is_loud_not_resampled():
    """T35 r2 的原始崩溃：DA3 504 分辨率输出 378x504，真值 210x280。必须报错，且不得静默缩放。"""
    g = np.ones((210, 280))
    poses = [np.eye(4)] * 3
    poses = [np.eye(4), np.vstack([np.hstack([np.eye(3), [[1.0], [0], [0]]]), [0, 0, 0, 1]]),
             np.vstack([np.hstack([np.eye(3), [[2.0], [0], [0]]]), [0, 0, 0, 1]])]
    with pytest.raises(ValueError, match="paired depth shapes must agree"):
        M.anchored_residual(poses, poses, [g, g], [np.ones((378, 504)), np.ones((378, 504))])


def test_w2c_must_be_inverted_before_use(data):
    """r1 把 world_to_camera 当 camera_to_world 用。完美 teacher 在正确约定下残差≈0，在错误约定下必须明显非零。"""
    v = data["t6-analytic-room-00"]
    gt = [x["c2w"] for x in v]
    d = [x["depth"] for x in v]
    # 真实 DA3 的位姿在它自己的任意参考系里（朝向/原点/尺度都与 GT 房间系不同），用 GT 自己当预测放不大约定错误。
    q, s, t0 = _rot("x", 0.7) @ _rot("y", -0.4), 0.37, np.array([3.0, -1.0, 2.0])
    pred_c2w = [np.vstack([np.hstack([q @ g[:3, :3], (s * (q @ g[:3, 3]) + t0)[:, None]]), [0, 0, 0, 1]]) for g in gt]
    w2c = np.stack([np.linalg.inv(p) for p in pred_c2w])
    good = M.anchored_residual(gt, list(M.w2c_to_c2w(w2c[:, :3, :4])), d, d)
    assert np.abs(good["residual_7d"][:6]).max() < 1e-9
    bad = M.anchored_residual(gt, [x for x in w2c], d, d)       # 约定用错：把 w2c 当 c2w
    assert good["translation_residual_norm"] < 1e-9
    assert bad["translation_residual_norm"] > 0.2, "错误约定必须产生明显偏差，否则这个测试抓不到那类缺陷"


def test_residual_invariant_to_pose_frame_and_scale(data):
    """DA3 位姿在自己的参考系且尺度未知：锚点相对残差对全局刚体变换与尺度必须不变。"""
    v = data["t6-analytic-room-01"]
    gt = [x["c2w"] for x in v]
    d = [x["depth"] for x in v]
    q, s, t0 = _rot("x", 1.1) @ _rot("z", 0.3), 4.2, np.array([9.0, 8.0, -7.0])
    pred = [np.vstack([np.hstack([q @ g[:3, :3], (s * (q @ g[:3, 3]) + t0)[:, None]]), [0, 0, 0, 1]]) for g in gt]
    r = M.anchored_residual(gt, pred, d, [x * 0.2 for x in d])
    assert np.abs(r["residual_7d"][:6]).max() < 1e-9
    assert abs(r["depth_abs_rel"]) < 1e-6          # 夹具深度是 float32，乘 0.2 的舍入在 1e-8 量级


def test_no_target_view_depth_refit(data):
    """T28：用锚点视图的 s_depth 评分，不得对目标视图再拟合。目标视图深度整体偏 1.5 倍时 abs_rel 不能被拟合成 0。"""
    v = data["t6-analytic-room-00"]
    gt = [x["c2w"] for x in v]
    d = [x["depth"] for x in v]
    r = M.anchored_residual(gt, gt, d, [d[0], d[1] * 1.5])
    assert r["depth_abs_rel"] == pytest.approx(0.5, rel=1e-6)
    assert r["residual_7d"][6] == pytest.approx(np.log(1.5), rel=1e-6)


def test_pi_branch_refused():
    a = np.eye(4)
    b = np.eye(4)
    b[:3, :3] = _rot("z", np.pi)
    c = np.eye(4)
    c[0, 3] = 1.0
    g = np.eye(4)
    g[0, 3] = 1.0
    with pytest.raises(ValueError, match="pi"):
        M.anchored_residual([a, a, g], [a, b, c], [np.ones((2, 2))] * 2, [np.ones((2, 2))] * 2)


def test_parity_rule_is_elementwise_with_reference_scaled_rtol():
    ref = {"depth": np.array([1.0, 100.0])}
    ok = M.parity_compare(ref, {"depth": np.array([1.0009, 100.09])}, ["depth"], 1e-3, 1e-3)
    assert ok["pass"] and ok["fields"]["depth"]["failed_elements"] == 0
    bad = M.parity_compare(ref, {"depth": np.array([1.0, 100.5])}, ["depth"], 1e-3, 1e-3)
    assert not bad["pass"] and bad["fields"]["depth"]["failed_elements"] == 1
    assert not M.parity_compare(ref, {"depth": np.array([1.0])}, ["depth"], 1, 1)["pass"]
    assert not M.parity_compare(ref, {"depth": np.array([np.nan, 1.0])}, ["depth"], 1, 1)["pass"]
    assert not M.parity_compare(ref, {}, ["depth"], 1, 1)["pass"]


def test_required_red_boundary():
    assert M.required_red(1.0, 1.1) and not M.required_red(1.0, 1.0999)
    assert M.required_red(0.0, 1e-4) and not M.required_red(0.0, 9e-5)


def test_fit_statistics_rank_ceiling_comes_from_sample_count_not_a_constant():
    rng = np.random.default_rng(0)
    s3 = M.fit_statistics(list(rng.normal(size=(3, 7))))
    s5 = M.fit_statistics(list(rng.normal(size=(5, 7))))
    assert s3["rank"] == s3["rank_ceiling"] == 2 and s5["rank"] == s5["rank_ceiling"] == 4
    assert s3["regularization"] == "none"


# ───────────────────────────── 预检：不可满足就不动模型 ─────────────────────────────
def test_real_da3_cannot_satisfy_t28_and_runner_refuses_before_any_model_work(tmp_path, data):
    f = FakeFactory(data, capable=False)               # 与真实 DA3 同样的能力位
    with pytest.raises(R.ProtocolUnsatisfiable):
        _run(tmp_path, f)
    assert f.made == [] and f.calls == [], "不可满足时不得创建任何 teacher"
    assert not (tmp_path / "preds").exists() and not (tmp_path / "ev.json").exists()


def test_real_factory_declares_it_cannot_condition_on_intrinsics():
    assert R.RealTeacherFactory.conditions_on_intrinsics_only is False


def test_upstream_da3_still_gates_intrinsics_behind_extrinsics():
    """漂移探测：上游若改成能只靠内参条件化，这条会失败，提醒重新评估 REAL_DA3_CONDITIONS_ON_INTRINSICS_ONLY。"""
    src = (REPO / "envs/teachers/t6/Depth-Anything-3/src/depth_anything_3/model/da3.py").read_text()
    m = re.search(r"if extrinsics is not None:\s*\n(?:.*\n){0,3}?.*self\.cam_enc\(extrinsics, intrinsics", src)
    assert m, "da3.py forward no longer gates cam_enc on extrinsics; re-evaluate K conditioning"
    api = (REPO / "envs/teachers/t6/Depth-Anything-3/src/depth_anything_3/api.py").read_text()
    assert re.search(r"if extrinsics is None:\s*\n\s*return prediction", api)


def test_preflight_rejects_existing_outputs(tmp_path, data, plan):
    (tmp_path / "preds").mkdir()
    (tmp_path / "preds" / "x").write_text("prior evidence")
    with pytest.raises(R.PreflightError, match="non-empty"):
        R.preflight(plan, FakeFactory(data), tmp_path / "preds", tmp_path / "ev.json")
    (tmp_path / "ev.json").write_text("{}")
    with pytest.raises(R.PreflightError):
        R.preflight(plan, FakeFactory(data), tmp_path / "other", tmp_path / "ev.json")


def test_default_output_dirs_must_not_be_the_delivered_t35_folder():
    """r1 默认写进已交付的 reports/V9-T35/predictions，而管线拒绝已存在目录，下一枪会在第一个世界就崩。"""
    src = (REPO / "src/ainerzero/v9/teachers/da3_worker.py").read_text()
    assert 'reports/V9-T35/predictions"' not in src.replace("\\", ""), "worker 不得默认写入已交付的 T35 证据目录"


def test_tampered_proposal_is_rejected(tmp_path, monkeypatch):
    from ainerzero.v9.teachers import t28_registration
    monkeypatch.setattr(t28_registration, "REPO_ROOT", tmp_path)
    for n in ("proposal.json", "proposal.sha256"):
        shutil.copy(REPO / "reports/V9-T28" / n, tmp_path / n)
    p = json.loads((tmp_path / "proposal.json").read_text())
    p["numerical_parity"]["cpu_float32"]["atol"] = 0.5            # 事后放宽容差
    (tmp_path / "proposal.json").write_text(json.dumps(p))
    with pytest.raises(R.PreflightError, match="proposal.sha256"):
        R.load_plan(tmp_path / "proposal.json")


def test_plan_comes_from_t28_not_constants(plan):
    assert plan.process_res == 280 and (plan.anchor_view, plan.scored_view, plan.scale_view) == (0, 1, 2)
    assert plan.calls_per_variant == 11 and plan.views_per_variant == 31
    assert plan.parity_cpu == (1e-3, 1e-3) and plan.parity_half == (1e-2, 1e-2)
    assert plan.focal_scale == (1.5, 0.75) and (plan.red_floor, plan.red_rel) == (1e-4, 0.1)
    assert [s["stage"] for s in plan.stages] == ["first_frame", "calibration", "frame_order_adverse",
                                                 "intrinsics_adverse", "cpu_parity", "half_parity"]


# ───────────────────────────── 整条流程（假 teacher） ─────────────────────────────
def test_full_run_with_capable_teacher_follows_t28_and_reports_only_measured_values(tmp_path, data, plan):
    f = FakeFactory(data)
    ev, code = _run(tmp_path, f)
    assert code == 0 and ev["status"] == plan.output_status and ev["failures"] == []
    assert f.max_live == 1, "T28 max_resident_models=1"
    for v in plan.variants:
        acc = ev["forward_accounting"][v]
        assert (acc["calls_actual"], acc["views_actual"]) == (11, 31) == (acc["calls_planned"], acc["views_planned"])
        cal = ev["calibration"][v]
        assert set(cal["per_world"]) == set(plan.fit_worlds) | set(plan.holdout_worlds)
        assert max(abs(x) for w in cal["per_world"].values() for x in w["residual_7d"]) < 1e-3
        assert cal["fit"]["n_fit"] == 3 and cal["fit"]["rank_ceiling"] == 2 and cal["fit"]["rank"] <= 2
        for adv in ("frame_order_adverse", "intrinsics_adverse"):
            s = ev["stages"][v][adv]
            assert s["turned_red"] and s["S_bad"] >= s["S_clean"] + s["required_margin"]
        assert all(p["pass"] for p in ev["numerical_parity"][v].values())
    assert all(g["rejected"] for g in ev["negative_controls"]["boundary_guards"])
    assert ev["predictions_manifest"]["total_files"] > 0
    # 全部 positive 调用都按预登记用 process_res=280 并带已知 K
    assert {c[4] for c in f.calls} == {280} and all(c[5] for c in f.calls)
    # 不得再出现任何写死的结论字段
    text = json.dumps(ev)
    for banned in ("rotation_offset_deg", "full_calibration_completed", "reason_rank_deficient", "views_consumed"):
        assert banned not in text
    # 同一目录再跑必须被预检拒绝，且不动已有证据
    before = (tmp_path / "ev.json").read_bytes()
    with pytest.raises(R.PreflightError):
        _run(tmp_path, FakeFactory(data))
    assert (tmp_path / "ev.json").read_bytes() == before


def test_parity_failure_exits_nonzero_retains_outputs_and_does_not_relax(tmp_path, data):
    ev, code = _run(tmp_path, FakeFactory(data, cpu_eps=0.05))
    assert code == R.EXIT_STAGE_FAILED and ev["status"] == "failed"
    assert any("cpu_parity" in x for x in ev["failures"])
    assert (tmp_path / "ev.json").is_file() and ev["predictions_manifest"]["total_files"] > 0


def test_adverse_control_that_does_not_turn_red_is_a_failure_not_a_pass(tmp_path, data):
    """逆序控制：若 teacher 对 RGB 顺序不敏感（按位置而非内容出结果），S_bad==S_clean，必须判失败。"""
    ev, code = _run(tmp_path, FakeFactory(data, by_content=False))
    assert code == R.EXIT_STAGE_FAILED
    assert any("frame_order_adverse" in x for x in ev["failures"])
    assert not ev["stages"]["DA3-SMALL"]["frame_order_adverse"]["turned_red"]


def test_k_insensitive_teacher_fails_the_intrinsics_control(tmp_path, data):
    """即便声称能被 K 条件化，只要输出不随 K 变，内参逆向控制就必须判失败。"""
    ev, code = _run(tmp_path, FakeFactory(data, k_effect=False))
    assert code == R.EXIT_STAGE_FAILED and any("intrinsics_adverse" in x for x in ev["failures"])


def test_wrong_output_resolution_fails_loudly_and_keeps_evidence(tmp_path, data):
    """原始崩溃场景：teacher 输出 378x504，必须报 'resampling is not allowed'，而不是被悄悄缩放。"""
    ev, code = _run(tmp_path, FakeFactory(data, out_hw=(378, 504)))
    assert code == R.EXIT_ERROR and (tmp_path / "ev.json").is_file()
    assert any("resampling is not allowed" in x for x in ev["failures"])


def test_runner_source_has_no_unexecuted_verified_flags():
    """静态护栏：r1 的 `"verified": True` / `rotation_offset_deg` / `full_calibration_completed` 不得复活。"""
    for name in ("da3_calibration_runner.py", "da3_calibration_math.py"):
        src = (REPO / "src/ainerzero/v9/teachers" / name).read_text()
        code = re.sub(r'"""(?:.|\n)*?"""|#.*', "", src)
        for banned in ('"verified": True', "rotation_offset_deg", "full_calibration_completed", "views_consumed",
                       "reason_rank_deficient"):
            assert banned not in code, f"{name} contains hard-coded claim {banned!r}"


# ───────────────────────────── 真实数据冒烟（只读；文件不在就跳过） ─────────────────────────────
@pytest.mark.skipif(not (REPO / "reports/V9-T35/predictions/da3_small/t6-analytic-room-00/view_0.safetensors").is_file(),
                    reason="T35 r2 saved real DA3 predictions not present")
def test_real_da3_world0_smoke_with_correct_convention(data):
    """T35 r2 真跑留下的 world-0 真实 DA3-SMALL 输出（process_res=504，378x504）：只用于验证约定，不是标定结论。"""
    from safetensors.numpy import load_file
    base = REPO / "reports/V9-T35/predictions/da3_small/t6-analytic-room-00"
    p = [load_file(str(base / f"view_{i}.safetensors")) for i in range(3)]
    v = data["t6-analytic-room-00"]
    gt, gd = [x["c2w"] for x in v], [x["depth"] for x in v]
    pred_c2w = list(M.w2c_to_c2w(np.stack([x["camera_pose"] for x in p])))
    pd = [np.array(Image.fromarray(x["depth"].astype(np.float32)).resize((280, 210), Image.BILINEAR)) for x in p]
    good = M.anchored_residual(gt, pred_c2w, gd, pd)             # 缩放仅用于这份 504 的历史原件
    wrong = M.anchored_residual(gt, [np.vstack([x["camera_pose"], [0, 0, 0, 1]]) for x in p], gd, pd)
    assert good["rotation_deg"] < 3.0 and good["translation_residual_norm"] < 0.3
    assert wrong["translation_residual_norm"] > 3 * good["translation_residual_norm"]


# ───────────────────────────── 修订协议后的可运行性 ─────────────────────────────
def test_runner_is_ready_for_an_amended_protocol_without_known_k(tmp_path, data):
    """T28 的"已知 K + 内参逆向控制"在这版 DA3 上不可满足。若协议被修订为"模型自估内参、去掉内参控制"，
    runner 不需要再改：用与真实 DA3 相同的能力位（不能用 K 条件化）整条跑通，且前向账目与修订后的计划一致。
    这里的修订版只是测试夹具，不是已登记的协议。"""
    p = json.loads(T28.read_text())
    p["profile"]["known_intrinsics"] = False
    del p["negative_controls"]["intrinsics"]      # r2 真的删了这个键；漏删正是 T40 之前 load_plan 在 r2 上 KeyError 却没被抓到的原因
    for m in p["budget"]["models"]:
        m["stages"] = [s for s in m["stages"] if s["stage"] != "intrinsics_adverse"]
        m["forward_calls"], m["forward_views"] = 10, 28          # 1+6 次校准+逆序+CPU+半精度；1+18+3+3+3
    amended = tmp_path / "amended_proposal.json"
    amended.write_text(json.dumps(p))
    f = FakeFactory(data, capable=False)                          # 真实 DA3 的能力位
    ev, code = R.run_full_calibration(tmp_path / "ev.json", tmp_path / "preds", "amended-test", teacher_factory=f,
                                      proposal_path=amended, verify_hashes=False)
    assert code == 0 and ev["failures"] == []
    for v in ("DA3-SMALL", "DA3-BASE"):
        acc = ev["forward_accounting"][v]
        assert (acc["calls_actual"], acc["views_actual"]) == (10, 28)
        assert "intrinsics_adverse" not in ev["stages"][v]
    assert all(c[5] is False for c in f.calls), "未知 K 的协议下不得传入 intrinsics"


# ═════════════════════════ V9.T40：r2 驱动、证据落盘、统计口径、CLI 参数 ═════════════════════════
import subprocess  # noqa: E402
import sys  # noqa: E402

R2_PROPOSAL = REPO / "reports/V9-T28/r2/proposal.json"
needs_r2 = pytest.mark.skipif(not R2_PROPOSAL.is_file(), reason="T28 r2 draft not present")


@needs_r2
def test_real_r2_proposal_drives_the_runner_end_to_end(tmp_path, data):
    """用磁盘上真实的 r2 proposal.json（而不是测试里拼出来的）整条跑通。T38 之前这里 load_plan 抛 KeyError('intrinsics')。"""
    plan2 = R.load_plan(R2_PROPOSAL)
    assert plan2.known_intrinsics is False and "intrinsics_adverse" not in [s["stage"] for s in plan2.stages]
    f = FakeFactory(data, capable=False)                       # 与真实 DA3 相同的能力位
    ev, code = R.run_full_calibration(tmp_path / "ev.json", tmp_path / "preds", "t40-r2", teacher_factory=f, proposal_path=R2_PROPOSAL)
    assert code == 0 and ev["failures"] == []
    for v in plan2.variants:
        acc = ev["forward_accounting"][v]
        assert acc["complete"] is True
        assert (acc["calls_actual"], acc["views_actual"]) == (plan2.calls_per_variant, plan2.views_per_variant)
    assert ev["protocol"]["proposal_path"].endswith("reports/V9-T28/r2/proposal.json")
    assert ev["protocol"]["proposal_sha256"] == plan2.shas["proposal"]
    assert all(c[5] is False for c in f.calls), "r2 不给 teacher 任何内参"


@needs_r2
def test_proposal_selection_by_flag_and_env_and_preflight_exit_codes(tmp_path, monkeypatch):
    """有登记时默认用登记的 r2（预检通过 → 0）；
    若提案 SHA 与登记不一致（如显式传入 r1 或通过环境变量传入 r1）则被拒绝（EXIT_PREFLIGHT == 2）；
    无登记时默认保持 r1（不可满足 → 6）。
    """
    args = ["--preflight-only", "--output", str(tmp_path / "e.json"), "--predictions-dir", str(tmp_path / "p")]

    # 1. 有登记时：默认用登记里的 proposal_path (r2)，预检通过 (0)
    assert R.main(args) == R.EXIT_OK

    # 2. 有登记时：--proposal 显式传入非登记的 r1 提案，SHA 不一致，退出码非 0 拒绝 (EXIT_PREFLIGHT == 2)
    assert R.main(args + ["--proposal", str(T28)]) == R.EXIT_PREFLIGHT

    # 3. 有登记时：环境变量 T6_PROPOSAL_PATH 传入非登记的 r1 提案，SHA 不一致，拒绝 (EXIT_PREFLIGHT == 2)
    monkeypatch.setenv("T6_PROPOSAL_PATH", str(T28))
    assert R.main(args) == R.EXIT_PREFLIGHT
    monkeypatch.delenv("T6_PROPOSAL_PATH", raising=False)

    # 4. 有登记时：环境变量 T6_PROPOSAL_PATH 传入匹配的 r2 提案，预检通过 (0)
    monkeypatch.setenv("T6_PROPOSAL_PATH", str(R2_PROPOSAL))
    assert R.main(args) == R.EXIT_OK
    monkeypatch.delenv("T6_PROPOSAL_PATH", raising=False)

    # 5. 无登记时：隔离 repo_root，默认保持 r1（不可满足 → 6）
    from ainerzero.v9.teachers import t28_registration
    fake_empty_repo = tmp_path / "empty_repo"
    fake_empty_repo.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(t28_registration, "REPO_ROOT", fake_empty_repo)

    assert R.main(args) == R.EXIT_UNSATISFIABLE
    # 无登记时通过 --proposal 指向 r2 依然可通过 (0)
    assert R.main(args + ["--proposal", str(R2_PROPOSAL)]) == R.EXIT_OK
    monkeypatch.undo()

    code = ("import importlib.util,sys;"
            f"s=importlib.util.spec_from_file_location('r',{str(REPO / 'src/ainerzero/v9/teachers/da3_calibration_runner.py')!r});"
            "m=importlib.util.module_from_spec(s);sys.modules['r']=m;s.loader.exec_module(m);print(m.PROPOSAL_PATH)")
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                         env={**__import__("os").environ, "T6_PROPOSAL_PATH": str(R2_PROPOSAL)})
    assert out.stdout.strip() == str(R2_PROPOSAL), out.stderr[-300:]


def _run_with_hard_abort(tmp_path, abort_at):
    """子进程里跑 runner；在第一次或最后一个阶段的 make() 里 os._exit(134)，复现 Metal 断言的 SIGABRT（无异常、进程直接消失）。"""
    plan2 = R.load_plan(R2_PROPOSAL)
    last = plan2.stages[-1]
    cond = "True" if abort_at == "first" else f"(device, dtype) == ({last['device']!r}, {last['precision']!r})"
    script = tmp_path / "abort_run.py"
    script.write_text(f"""
import importlib.util, os, sys
spec = importlib.util.spec_from_file_location("t_mod", {str(REPO / 'tests/test_da3_calibration_runner.py')!r})
T = importlib.util.module_from_spec(spec); sys.modules["t_mod"] = T; spec.loader.exec_module(T)
R = T.R
plan = R.load_plan({str(R2_PROPOSAL)!r})
data = R.load_fixtures(R.FIXTURES_DIR, plan)
f = T.FakeFactory(data, capable=False)
real_make = f.make
def make(variant, device, dtype):
    if {cond}:
        os._exit(134)
    return real_make(variant, device, dtype)
f.make = make
R.run_full_calibration({str(tmp_path / 'ev.json')!r}, {str(tmp_path / 'preds')!r}, "abort-test", teacher_factory=f, proposal_path={str(R2_PROPOSAL)!r})
""")
    r = subprocess.run([sys.executable, str(script)], capture_output=True, text=True)
    assert r.returncode == 134, (r.returncode, r.stderr[-500:])
    return plan2, json.loads((tmp_path / "ev.json").read_text())


@needs_r2
def test_hard_abort_in_the_last_stage_keeps_every_finished_stage(tmp_path):
    """MPS fp16 的 dtype 错误是 SIGABRT(134)。旧实现只在最后写证据，会什么都不留。"""
    plan2 = R.load_plan(R2_PROPOSAL)
    assert (plan2.stages[-1]["device"], plan2.stages[-1]["precision"]) != (plan2.stages[-2]["device"], plan2.stages[-2]["precision"]), \
        "最后一个阶段必须触发一次新的 make()"
    plan2, ev = _run_with_hard_abort(tmp_path, "last")
    assert ev["status"] == "in_progress"
    assert list(ev["stages"][plan2.variants[0]]) == [s["stage"] for s in plan2.stages[:-1]]
    assert plan2.variants[1] not in ev["stages"], "中止发生在第一个型号的最后阶段，第二个型号还没开始"
    assert ev["calibration"][plan2.variants[0]]["per_world"], "已完成阶段的结果必须已经在盘上"
    assert ev["forward_accounting"][plan2.variants[0]]["complete"] is False
    assert not (tmp_path / "ev.json.tmp").exists()


@needs_r2
def test_hard_abort_before_the_first_stage_still_leaves_an_in_progress_record(tmp_path):
    """第一次加载模型就中止（例如 MPS 初始化失败）：此时没有任何阶段完成，开始时写的那份 in_progress 是唯一的痕迹。"""
    plan2, ev = _run_with_hard_abort(tmp_path, "first")
    assert ev["status"] == "in_progress" and ev["stages"] == {} and ev["failures"] == []
    assert ev["protocol"]["proposal_sha256"] == plan2.shas["proposal"]


def test_atomic_evidence_write_never_leaves_a_partial_file(tmp_path):
    out = tmp_path / "sub" / "ev.json"
    R._write_atomic(out, {"a": 1})
    R._write_atomic(out, {"a": 2, "b": [1, 2]})
    assert json.loads(out.read_text()) == {"a": 2, "b": [1, 2]} and not list(out.parent.glob("*.tmp"))


# ── T38 NEW-5：对拍不能退化成只比 depth ──
@pytest.mark.parametrize("field", ["depth", "confidence", "extrinsics", "intrinsics"])
def test_cpu_parity_catches_a_violation_in_each_single_field(tmp_path, data, field):
    ev, code = _run(tmp_path, FakeFactory(data, cpu_eps=0.05, eps_only_field=field))
    assert code == R.EXIT_STAGE_FAILED, f"只有 {field} 越界时对拍必须失败"
    fields = ev["numerical_parity"]["DA3-SMALL"]["cpu_parity"]["fields"]
    assert fields[field]["pass"] is False and fields[field]["failed_elements"] > 0
    assert all(fields[f]["pass"] for f in fields if f != field), "未被扰动的字段不应失败"


# ── T38 NEW-6 / NEW-8：fit 统计只来自 fit 世界，且协方差用 ddof=1 ──
def test_fit_statistics_use_only_fit_worlds_and_unbiased_covariance(tmp_path, data, plan):
    ev, code = _run(tmp_path, FakeFactory(data, pose_noise=0.01))
    assert code == 0, ev["failures"]
    for v in plan.variants:
        cal = ev["calibration"][v]
        fit = np.array([cal["per_world"][w]["residual_7d"] for w in plan.fit_worlds])
        hold = np.array([cal["per_world"][w]["residual_7d"] for w in plan.holdout_worlds])
        assert np.abs(fit).max() > 1e-3, "噪声必须真的进入残差，否则这条测试什么也区分不了"
        assert cal["fit"]["n_fit"] == 3
        np.testing.assert_allclose(cal["fit"]["mean"], fit.mean(axis=0), atol=1e-12)
        np.testing.assert_allclose(cal["fit"]["covariance"], np.cov(fit.T, ddof=1), atol=1e-12, rtol=1e-9)
        np.testing.assert_allclose(cal["holdout_residual_mean"], hold.mean(axis=0), atol=1e-12)
        assert not np.allclose(cal["fit"]["mean"], np.vstack([fit, hold]).mean(axis=0), atol=1e-6), "holdout 混入 fit 会让均值变化"


def test_fit_statistics_unit_matches_numpy_ddof1():
    x = np.random.default_rng(3).normal(size=(5, 7))
    st = M.fit_statistics(list(x))
    np.testing.assert_allclose(st["covariance"], np.cov(x.T, ddof=1), atol=1e-12)
    np.testing.assert_allclose(st["mean"], x.mean(axis=0), atol=1e-12)
    assert st["n_fit"] == 5 and st["rank_ceiling"] == 4


def test_preflight_rejects_existing_in_progress_evidence_and_ignores_tmp_residue(tmp_path, data, plan):
    """V9.T42 (2): 补测 in_progress 覆盖拒绝 (抓出变异 T41-4)。
    已存在 status='in_progress' 的证据文件必须被拒绝，绝不放行覆盖；残留 .tmp 不得被当成证据已存在。"""
    # 1. 存在 in_progress 状态证据：必须抛 PreflightError 拒绝
    ev_in_progress = tmp_path / "in_progress_ev.json"
    ev_in_progress.write_text(json.dumps({"status": "in_progress", "task": "ainerzero.V9.T35"}))
    with pytest.raises(R.PreflightError, match="already exists"):
        R.preflight(plan, FakeFactory(data), tmp_path / "fresh_preds_1", ev_in_progress)

    # 2. 残留 .tmp 文件存在（旧版固定 .tmp 或新版带 pid/随机后缀 .tmp），但目标 JSON 不存在时：必须放行
    ev_target = tmp_path / "fresh_ev.json"
    legacy_tmp = tmp_path / "fresh_ev.json.tmp"
    unique_tmp = tmp_path / f"fresh_ev.json.tmp.{os.getpid()}.deadbeef1234"
    legacy_tmp.write_text("residual tmp data")
    unique_tmp.write_text("residual tmp data")
    assert not ev_target.exists()
    checks = R.preflight(plan, FakeFactory(data), tmp_path / "fresh_preds_2", ev_target)
    assert "outputs_are_fresh" in checks


def test_write_atomic_uses_unique_tmp_and_concurrent_writers_do_not_clobber(tmp_path, monkeypatch):
    """V9.T42 (4): 临时文件名唯一（含 pid 与随机后缀），并发两写者不互踩，残留 .tmp 不泄露。"""
    import concurrent.futures

    # 1. 验证临时文件名格式包含 pid 与随机后缀，同目录原子替换
    observed_tmps = []
    real_replace = os.replace

    def spy_replace(src, dst):
        observed_tmps.append(Path(src).name)
        real_replace(src, dst)

    monkeypatch.setattr(os, "replace", spy_replace)

    target_probe = tmp_path / "probe_atomic.json"
    R._write_atomic(target_probe, {"test": "probe"})
    assert len(observed_tmps) == 1
    tmp_name = observed_tmps[0]
    expected_pattern = rf"^probe_atomic\.json\.tmp\.{os.getpid()}\.[0-9a-f]{{32}}$"
    assert re.match(expected_pattern, tmp_name), f"临时文件名必须包含 pid 和随机十六进制后缀，实际为: {tmp_name}"

    # 2. 并发两写者同时高频写入同一文件，验证不互踩、最终可被正常解析
    target = tmp_path / "concurrent_ev.json"
    payload1 = {"writer": 1, "items": list(range(200))}
    payload2 = {"writer": 2, "items": list(range(200))}

    def worker(payload):
        for _ in range(15):
            R._write_atomic(target, payload)

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        f1 = pool.submit(worker, payload1)
        f2 = pool.submit(worker, payload2)
        f1.result()
        f2.result()

    assert target.exists()
    data = json.loads(target.read_text(encoding="utf-8"))
    assert data["writer"] in (1, 2)
    assert len(data["items"]) == 200

    # 验证未遗留任何 .tmp 临时文件
    tmp_files = list(tmp_path.glob("*.tmp*"))
    assert tmp_files == []





def test_write_atomic_keeps_the_temp_file_in_the_target_directory(tmp_path, monkeypatch):
    """V9.T44 (F-2)：`_write_atomic` 的临时文件必须与目标**同目录**。

    `os.replace` 只在同一文件系统内是原子的；把临时文件写到系统临时目录会让 rename 变成
    跨设备拷贝（或直接 EXDEV），"任何时刻读到的都是完整 JSON"的保证就没了。

    靶子：T43 变异 **M-C**（把临时文件写到系统 /tmp）。若临时文件不在目标目录，父目录断言变红。
    """
    # 走正常 import（而不是本文件顶部的 _load 直接指仓库路径），这样变异副本/换树运行时
    # 测到的就是 sys.path 上那份实现，M-C 这类"临时文件写到别处"的变异才抓得到。
    from ainerzero.v9.teachers import da3_calibration_runner as runner

    calls: list = []
    real_replace = os.replace  # 必须在打桩之前取到真函数

    def spy_replace(src, dst):
        calls.append((Path(src), Path(dst)))
        return real_replace(src, dst)

    monkeypatch.setattr(os, "replace", spy_replace)

    target = tmp_path / "nested" / "dir" / "evidence.json"
    runner._write_atomic(target, {"t_ticks": 120, "value": 1.5})

    assert len(calls) == 1, f"os.replace 必须被调用一次，实际 {len(calls)} 次"
    src, dst = calls[0]
    assert dst == target
    assert src.parent == target.parent, (
        f"临时文件必须与目标同目录（同文件系统）才能原子 rename；got src.parent={src.parent}, dst.parent={dst.parent}"
    )
    assert src.name != dst.name and ".tmp." in src.name
    assert json.loads(target.read_text(encoding="utf-8")) == {"t_ticks": 120, "value": 1.5}
    assert not src.exists(), "rename 之后临时文件不应残留"
