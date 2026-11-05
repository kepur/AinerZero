"""Continue T4 stage1: download the T4 teacher model weights only.

Mirrors the model-download loop of run_stage1_20261020.py exactly (same
revision/license/file whitelist, same SHA verification, same 2MiB/s cap,
same budget/disk guards, same network ledger), but is idempotent and resumes
if interrupted. Downloads only into artifacts/teachers/t4-approved/<revision>/.
Does NOT load models, run inference, train, or write RunStore.
"""
import json, subprocess, hashlib, shutil, time, importlib.util, os
from pathlib import Path

ROOT = Path('/Users/mac/AinerWorkFlow/AinerZero')
s = importlib.util.spec_from_file_location('prep', ROOT / 'envs/teachers/t4/prepare_20261020.py')
m = importlib.util.module_from_spec(s); s.loader.exec_module(m)
p = m.REPORT

def sha(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda: f.read(8 * 1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()

# Budget guard before any transfer
assert m.spent() + 1_459_675_816 + 5_000_000 <= m.BUDGET, ('projected over budget', m.spent())

selected = []
repos = [('vjepa-hf', 'dgrauet/vjepa-2.1-vitl-mlx'), ('da2-hf', 'apple/coreml-depth-anything-v2-small')]
base = ROOT / 'artifacts/teachers/t4-approved'
base.mkdir(parents=True, exist_ok=True)

for key, repo in repos:
    d = json.loads((p / (key + '.json')).read_text())
    revision = d['sha']
    target = base / revision
    target.mkdir(parents=True, exist_ok=True)
    for f in d['siblings']:
        rel = f['rfilename']
        allowed = (rel in ('README.md', 'config.json', 'split_model.json', 'encoder.safetensors', 'predictor.safetensors')) if key == 'vjepa-hf' else (rel == 'README.md' or rel.startswith(('DepthAnythingV2SmallF16.mlpackage/', 'DepthAnythingV2SmallF32.mlpackage/')))
        if not allowed:
            continue
        dest = target / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        partial = dest.with_name(dest.name + '.part')
        # Idempotency: skip already-present and verified files
        if dest.is_file() and dest.stat().st_size == f['size']:
            digest = sha(dest)
            ok = (digest == f['lfs']['sha256']) if f.get('lfs') else (hashlib.sha1(b'blob ' + str(f['size']).encode() + b'\0' + dest.read_bytes()).hexdigest() == f['blobId'])
            if ok:
                selected.append({'repository': repo, 'revision': revision, 'file': rel, 'path': str(dest), 'bytes': f['size'], 'sha256': digest, 'expected_lfs_sha256': f.get('lfs', {}).get('sha256')})
                print('skip already verified', rel, flush=True)
                continue
        if partial.exists():
            partial.unlink()
        assert m.spent() + f['size'] <= m.BUDGET, ('budget', rel)
        assert shutil.disk_usage(ROOT).free >= 50 * 1024 ** 3, ('disk guard', rel)
        url = f'https://huggingface.co/{repo}/resolve/{revision}/{rel}'
        argv = ['curl', '--fail', '--location', '--silent', '--show-error', '--max-time', '1800',
                '--limit-rate', '2M', '--max-filesize', str(f['size']), '-o', str(partial), '-w', '%{size_download}', url]
        start = time.time()
        r = subprocess.run(argv, capture_output=True, text=True)
        n = int(r.stdout or 0)
        row = {'url': url, 'path': str(partial), 'category': 'weights-and-model-metadata',
               'bytes': n, 'returncode': r.returncode, 'stderr': r.stderr, 'elapsed_s': time.time() - start, 'argv': argv}
        with m.JOURNAL.open('a') as log:
            log.write(json.dumps(row) + '\n'); log.flush()
        assert r.returncode == 0, row
        assert n == f['size'] == partial.stat().st_size
        digest = sha(partial)
        if f.get('lfs'):
            assert digest == f['lfs']['sha256']
        else:
            data = partial.read_bytes()
            assert hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest() == f['blobId']
        partial.rename(dest)
        selected.append({'repository': repo, 'revision': revision, 'file': rel, 'path': str(dest), 'bytes': n, 'sha256': digest, 'expected_lfs_sha256': f.get('lfs', {}).get('sha256')})
        (p / 'downloads-progress.json').write_text(json.dumps(selected, indent=2))
        print('model file', rel, n, 'total transferred', m.spent(), flush=True)

(p / 'downloads.json').write_text(json.dumps(selected, indent=2))
(p / 'stage1-complete.json').write_text(json.dumps({
    'at': time.time(), 'payload_bytes': m.spent(),
    'free_bytes': shutil.disk_usage(ROOT).free,
    'models_loaded': 0, 'inference_calls': 0, 'training_updates': 0,
}, indent=2))
print('COMPLETE', m.spent(), 'files', len(selected), flush=True)
