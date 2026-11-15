# Simulates an environment without MLX: any import of mlx / mlx.* raises ModuleNotFoundError.
import sys
class _NoMLX:
    def find_spec(self, name, path=None, target=None):
        if name == "mlx" or name.startswith("mlx."):
            raise ModuleNotFoundError(f"No module named {name!r} (simulated: MLX not installed)", name=name)
sys.meta_path.insert(0, _NoMLX())
