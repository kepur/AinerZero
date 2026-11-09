import sys
def pytest_sessionfinish(session, exitstatus):
    print("\nMLX_LOADED_IN_PYTEST_PROCESS", "mlx" in sys.modules or "mlx.core" in sys.modules)
