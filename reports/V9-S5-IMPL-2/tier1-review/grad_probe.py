import mlx.core as mx, mlx.nn as nn, numpy as np
from ainerzero.v9.experiments.s5.student import Student
from ainerzero.v9.experiments.s5.heads import GridHead
mx.random.seed(0)
st, gh = Student(), GridHead()
x = mx.random.normal((2, 8, 14, 14, 1536))
y = (mx.random.uniform(shape=(2, 12, 7)) > 0.8)
l = gh.loss(gh(st(x)[0]), y)
print("GridHead.loss shape:", l.shape)
keep = mx.array(np.random.default_rng(0).random((2, 8, 14, 14)) > 0.5); keep[:, 0] = True
rl = mx.ones((2, 8, 14, 14), dtype=mx.int32)
class M(nn.Module):
    def __init__(s): super().__init__(); s.st, s.gh = st, gh
def f(m):
    tok, mask = m.st(x, keep=keep, run_len=rl)
    return mx.mean(gh.loss(m.gh(tok, mask), y))
m = M()
val, g = nn.value_and_grad(m, f)(m)
ge = g["st"]["embed"]["weight"]; gp = g["st"]["pos"]; gr = g["st"]["run_len_embed"]
print("loss", float(val), "embed grad |max|", float(mx.abs(ge).max()), "pos grad nonzero rows", int((mx.abs(gp).sum(-1) > 0).sum()), "of 1568", "runlen grad |max|", float(mx.abs(gr).max()))
