
import json, os, sys
LOG = os.environ["A39_SENTINEL_LOG"]
class _Block:
    def find_spec(self, name, path=None, target=None):
        if name == "mlx" or name.startswith("mlx."):
            with open(LOG, "a") as h:
                h.write(json.dumps({"pid": os.getpid(), "module": name}) + "\n")
            raise RuntimeError("A39 sentinel: real MLX import blocked: " + name)
sys.meta_path.insert(0, _Block())
