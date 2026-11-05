import subprocess, sys
import animeworld.render_backend.blender_npr as b
real = subprocess.run
def fake(cmd, *a, **k):
    if cmd[:3] == ["pmset", "-g", "ps"]:
        return subprocess.CompletedProcess(cmd, 0, stdout="Now drawing from 'Battery Power'\n -InternalBattery-0 (id=1)\t80%; discharging;\n", stderr="")
    return real(cmd, *a, **k)
b.subprocess.run = fake
try:
    print(b.__file__, "->", b.check_power_and_blender_guards())
except RuntimeError as e:
    print(b.__file__, "-> RAISED", e); sys.exit(7)
