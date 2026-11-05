import sys
class NoModels:
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in ('mlx', 'torch', 'onnxruntime', 'transformers'):
            raise RuntimeError('B12 CPU-only import blocked: ' + fullname)
sys.meta_path.insert(0, NoModels())
