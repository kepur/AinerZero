#!/usr/bin/env python3
"""T46 独立复核：只用 CPU、不加载任何 DA3 权重，复现「整网转 fp16 + 上游写死 .float()」的 dtype 冲突。

复现的不是 DA3 本身，而是 pipeline.py:268-291 与 cam_dec.py:37-40 所规定的
**算术契约**：
  1) 模型参数被 .to(dtype=float16)（pipeline.py:291）
  2) 前向时 autocast 被显式关掉（pipeline.py:274, enabled=False）
  3) 上游对中间张量调 .float() 再喂给 Linear（cam_dec.py:37 `self.fc_t(feat.float())`）

若 (1)(2)(3) 同时成立，CPU 上必然抛 dtype 错误；这与 DA3 的权重、层数、维度无关。
反之，若 autocast 打开（选项 B 的做法），同一段算术不会抛错 —— 用来区分
"fp16 本身不可行" 与 "禁用 autocast 的整网 fp16 不可行"。

全程 device=cpu，不触碰 MPS（作者主张 MPS 会 Metal 断言中止进程，本卡不复现、也不评价其可复现性，
只评价其证据强度）。
"""
import sys
import traceback

import torch
import torch.nn as nn

RESULTS = []


def record(name, ok, detail):
    RESULTS.append((name, ok, detail))
    print(f"[{'PASS' if ok else 'FAIL'}] {name}")
    for line in detail.splitlines():
        print("       " + line)


def case_a_cpu_fp16_linear_with_float_input():
    """cam_dec.py:37 的等价算术：fp16 Linear 收到 .float() 输入。"""
    torch.manual_seed(0)
    lin = nn.Linear(64, 3).half()          # 等价于 model.to(dtype=float16)
    feat = torch.randn(2, 3, 64)           # 等价于 backbone 在 fp16 下产出的 feat
    try:
        with torch.autocast(device_type="cpu", enabled=False):   # pipeline.py:274
            _ = lin(feat.float())                                # cam_dec.py:37
    except RuntimeError as exc:
        msg = str(exc)
        hit = "mat1 and mat2 must have the same dtype" in msg
        record("A. CPU / autocast=off / fp16 Linear + .float() 输入",
               hit, f"RuntimeError: {msg}\n命中作者所述错误串: {hit}")
        return hit
    record("A. CPU / autocast=off / fp16 Linear + .float() 输入", False,
           "未抛错 —— 与作者主张不符")
    return False


def case_b_control_half_input_works():
    """对照：同一 fp16 Linear 收到 .half() 输入就能跑，说明错因就是 .float() 这一句。"""
    torch.manual_seed(0)
    lin = nn.Linear(64, 3).half()
    feat = torch.randn(2, 3, 64)
    with torch.autocast(device_type="cpu", enabled=False):
        out = lin(feat.half())
    ok = out.dtype == torch.float16 and torch.isfinite(out).all().item()
    record("B. 对照：同一 fp16 Linear + .half() 输入", ok,
           f"out.dtype={out.dtype} finite={bool(torch.isfinite(out).all())}")
    return ok


def case_c_autocast_on_works():
    """选项 B 的做法：autocast 打开时 fp16 Linear 收 fp32 输入不会抛错。"""
    torch.manual_seed(0)
    lin = nn.Linear(64, 3).half()
    feat = torch.randn(2, 3, 64)
    try:
        with torch.autocast(device_type="cpu", enabled=True, dtype=torch.float16):
            out = lin(feat.float())
    except RuntimeError as exc:
        record("C. 对照：autocast 打开时同段算术", False, f"仍抛错: {exc}")
        return False
    record("C. 对照：autocast 打开时同段算术（选项 B 的做法）", True,
           f"不抛错，out.dtype={out.dtype}（autocast 自行处理 dtype 提升）")
    return True


def case_d_three_hardcoded_float_calls():
    """cam_dec 的三处 .float()（fc_t/fc_qvec/fc_fov）各自都能触发同一错误。"""
    torch.manual_seed(0)
    dim = 32
    submodules = {
        "fc_t": nn.Linear(dim, 3).half(),
        "fc_qvec": nn.Linear(dim, 4).half(),
        "fc_fov": nn.Sequential(nn.Linear(dim, 2), nn.ReLU()).half(),
    }
    feat = torch.randn(1, 3, dim)
    hits = {}
    for name, mod in submodules.items():
        try:
            with torch.autocast(device_type="cpu", enabled=False):
                mod(feat.float())
            hits[name] = "no-error"
        except RuntimeError as exc:
            hits[name] = "dtype-error" if "same dtype" in str(exc) else str(exc)
    ok = all(v == "dtype-error" for v in hits.values())
    record("D. cam_dec.py:37/39/40 三处 .float() 均可独立触发", ok,
           "\n".join(f"{k}: {v}" for k, v in hits.items()))
    return ok


def case_e_pos_embed_hardcode():
    """head_utils.py:146 `return emb.float()`（以及 dinov2 pos_embed.float()）是**另一类**写法：
    逐元素 add 会做 dtype 提升而不是抛错，所以它是"静默上溢到 fp32"，
    再把这个 fp32 激活喂给后面的 fp16 Linear 才炸。
    我第一版断言"相加就抛错"是错的（add 会 promote），这里按实测结果改写。"""
    torch.manual_seed(0)
    act = torch.randn(1, 8, 32).half()      # fp16 激活
    emb = torch.randn(1, 8, 32).float()     # head_utils.py:146 的返回值
    promoted = act + emb
    silent_upcast = promoted.dtype == torch.float32   # 不报错，但悄悄变成 fp32

    lin = nn.Linear(32, 8).half()
    try:
        with torch.autocast(device_type="cpu", enabled=False):
            lin(promoted)
        downstream = "no-error"
    except RuntimeError as exc:
        downstream = "dtype-error" if "same dtype" in str(exc) else str(exc)

    ok = silent_upcast and downstream == "dtype-error"
    record("E. 位置编码 fp32 写死：静默上溢为 fp32，再撞下游 fp16 Linear", ok,
           f"add 后 dtype={promoted.dtype}（不抛错，静默提升）\n"
           f"把该张量喂 fp16 Linear: {downstream}")
    return ok


def case_f_fp32_path_is_clean():
    """fp32 阶段（first_frame / calibration / frame_order_adverse / cpu_parity）走同一段代码：
    .float() 在 fp32 下是 no-op，故不会出现 dtype 冲突。"""
    torch.manual_seed(0)
    lin = nn.Linear(64, 3)                  # 不转 half，等价于 precision=float32
    feat = torch.randn(2, 3, 64)
    with torch.autocast(device_type="cpu", enabled=False):
        out = lin(feat.float())
    ok = out.dtype == torch.float32 and torch.isfinite(out).all().item()
    record("F. fp32 阶段同一段算术（.float() 是 no-op）", ok,
           f"out.dtype={out.dtype} finite={bool(torch.isfinite(out).all())}")
    return ok


def main():
    print("torch", torch.__version__, "| device=cpu（不使用 MPS）| 未加载任何 DA3 权重")
    print("-" * 78)
    checks = [
        case_a_cpu_fp16_linear_with_float_input(),
        case_b_control_half_input_works(),
        case_c_autocast_on_works(),
        case_d_three_hardcoded_float_calls(),
        case_e_pos_embed_hardcode(),
        case_f_fp32_path_is_clean(),
    ]
    print("-" * 78)
    print(f"通过 {sum(checks)}/{len(checks)}")
    return 0 if all(checks) else 1


if __name__ == "__main__":
    sys.exit(main())
