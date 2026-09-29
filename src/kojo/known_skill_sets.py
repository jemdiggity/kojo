"""Well-known public skill sets, pinned to exact commits; other sets are passed as paths."""
from pathlib import Path
import shutil
import subprocess
import tempfile

# Bumping a revision is a deliberate experiment change: it yields a new cache path and set ID.
KNOWN = {
    'karpathy': ('https://github.com/forrestchang/andrej-karpathy-skills.git',
                 '2c606141936f1eeef17fa3043a72095b4765b9c2', 'skills'),
    'superpowers': ('https://github.com/obra/superpowers.git',
                    '8ca22dba9a94f28898bbce59f2537ff4d87c747d', 'skills'),
}


def resolve(spec, cache):
    """Return a local directory for a known name; treat anything else as a path."""
    if spec not in KNOWN:
        return Path(spec)
    url, revision, subpath = KNOWN[spec]
    dest = Path(cache) / revision[:12] / spec
    if dest.is_dir():
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=dest.parent) as tmp:
        repo, out = Path(tmp) / 'repo', Path(tmp) / spec
        out.mkdir()
        subprocess.run(['git', 'clone', '--quiet', '--no-checkout', url, str(repo)], check=True)
        archive = subprocess.run(['git', '-C', str(repo), 'archive', revision, subpath],
                                 check=True, stdout=subprocess.PIPE).stdout
        subprocess.run(['tar', '-x', '--strip-components=' + str(len(Path(subpath).parts)), '-C', str(out)],
                       input=archive, check=True)
        out.rename(dest)
    return dest
