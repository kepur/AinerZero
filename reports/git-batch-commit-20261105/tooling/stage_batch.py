"""Stage exactly one batch into the index, after re-verifying every file against the verified manifest.

Usage: python3 stage_batch.py <batch_name>
- Refuses if the index already has staged changes.
- Every file must still match the sha256 recorded by the isolated `final` verification
  (logs/files_final.tsv); src/ainerzero/cli.py is staged from the batch's verified variant blob.
- After staging, the staged path set must equal the manifest set (plus cli.py where applicable).
Never touches the working tree; never commits.
"""
import hashlib, os, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from batches import CLI_VARIANT, REPO  # noqa: E402


def git(*args, inp=None):
    # --literal-pathspecs: report file names may contain glob characters such as [ ] *
    return subprocess.run(["git", "--literal-pathspecs", "-C", REPO, "-c", "core.quotepath=off", *args], input=inp,
                          capture_output=True, text=True, check=True).stdout


def sha(p):
    h = hashlib.sha256()
    with open(p, "rb") as fh:
        for c in iter(lambda: fh.read(1 << 20), b""):
            h.update(c)
    return h.hexdigest()


def main(name):
    if subprocess.run(["git", "-C", REPO, "diff", "--cached", "--quiet"]).returncode != 0:
        raise SystemExit("index already has staged changes; refusing")
    manifest = [l.rstrip("\n").split("\t") for l in open(os.path.join(HERE, "logs", "files_final.tsv"), encoding="utf-8")]
    files = [(size, digest, path) for b, size, digest, path in manifest if b == name]
    if not files:
        raise SystemExit(f"no manifest rows for {name}")
    drift = [p for s, d, p in files if not os.path.isfile(os.path.join(REPO, p)) or sha(os.path.join(REPO, p)) != d]
    if drift:
        raise SystemExit(f"{len(drift)} files changed since verification, e.g. {drift[:5]}")
    paths = [p for s, d, p in files]
    with tempfile.NamedTemporaryFile("w", delete=False, encoding="utf-8") as fh:
        fh.write("\0".join(paths) + "\0")
        listfile = fh.name
    git("add", f"--pathspec-from-file={listfile}", "--pathspec-file-nul", "--")
    os.unlink(listfile)
    expected = set(paths)
    if name in CLI_VARIANT:
        blob = git("hash-object", "-w", os.path.join(HERE, CLI_VARIANT[name])).strip()
        git("update-index", "--cacheinfo", f"100644,{blob},src/ainerzero/cli.py")
        expected.add("src/ainerzero/cli.py")
    staged = set(p for p in git("diff", "--cached", "--name-only", "-z").split("\0") if p)
    if staged != expected:
        raise SystemExit(f"staged set mismatch: extra={sorted(staged - expected)[:5]} missing={sorted(expected - staged)[:5]}")
    status = git("diff", "--cached", "--name-status")
    kinds = {}
    for line in status.splitlines():
        kinds[line.split("\t")[0]] = kinds.get(line.split("\t")[0], 0) + 1
    print(f"{name}: staged {len(staged)} paths, all sha256-verified; status kinds {kinds}")


if __name__ == "__main__":
    main(sys.argv[1])
