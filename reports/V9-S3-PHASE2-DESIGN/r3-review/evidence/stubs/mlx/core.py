"""复核用桩：让运行器能原样执行启动序列，不加载真实 MLX。记账之后第一条 MLX 语句即退出。"""
__version__ = "0.32.2"
cpu = "cpu"
def set_default_device(d):
    raise SystemExit("REVIEW_STOP_AFTER_CONSUME")
