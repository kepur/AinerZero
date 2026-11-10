"""以默认 SIGINT 处理启动 pytest（后台运行时避免 SIGINT 被忽略导致的假失败）。用法：pyt.py <cwd> <pytest 参数...>"""
import os, signal, sys
signal.signal(signal.SIGINT, signal.SIG_DFL)
os.chdir(sys.argv[1])
os.execv(sys.executable, [sys.executable, "-m", "pytest", *sys.argv[2:]])
