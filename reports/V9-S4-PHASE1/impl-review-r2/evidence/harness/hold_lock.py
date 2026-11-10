"""持有共享 MLX 锁（flock，非阻塞；不写锁文件内容）后运行给定命令；锁忙就退出码 75。用法：hold_lock.py <锁> <命令...>"""
import fcntl, os, subprocess, sys
fh = open(sys.argv[1], "a+")
try:
    fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
except BlockingIOError:
    print("lock busy", flush=True); sys.exit(75)
print("lock held by", os.getpid(), flush=True)
sys.exit(subprocess.run(sys.argv[2:]).returncode)
