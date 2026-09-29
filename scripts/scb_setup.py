"""Cache expensive benchmark installs; retain local source and solver isolation."""
import contextlib
import fcntl
import hashlib
import os
from pathlib import Path
import platform
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
INPUTS = ('scripts/scb_install.sh', 'scripts/scb_setup.py', 'pyproject.toml',
          'uv.lock', '.python-version', 'configs/solver.lock')
VENDORS = ('slop-code-bench', 'scb-problems')
SHARED = ('scb-runner-venv', 'provider-cli')


def run(*args, **kwargs):
    subprocess.run(args, check=True, **kwargs)


def cache_key(root):
    digest = hashlib.sha256()
    digest.update(f'{platform.system()}:{platform.machine()}'.encode())
    for name in INPUTS:
        digest.update(name.encode() + b'\0' + (root / name).read_bytes())
    return digest.hexdigest()[:24]


def data_root(root):
    override = os.environ.get('KOJO_DATA_DIR')
    if override:
        return Path(override).expanduser().resolve()
    result = subprocess.run(['git', '-C', str(root), 'rev-parse',
                             '--path-format=absolute', '--git-common-dir'],
                            capture_output=True, text=True)
    common = result.stdout.strip()
    if result.returncode == 0 and common.endswith('/.git'):
        return Path(common).parent
    return root


@contextlib.contextmanager
def run_locks(root):
    # Hold existing run locks through setup, including while waiting for cache fill.
    with contextlib.ExitStack() as stack:
        for pattern in ('intermediate/runs/*/launcher.lock',
                        'intermediate/runs/*/gauntlet/execution.lock'):
            for path in data_root(root).glob(pattern):
                lock = stack.enter_context(path.open('r'))
                try:
                    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    raise RuntimeError(f'Active run: {path}. Finish or stop it before setup.')
        yield


def prepare_cache(root, cache, env):
    """Build at the final path: virtualenv scripts and editable imports embed it."""
    with cache.with_suffix('.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if (cache / 'ready').is_file():
            for relative in ('intermediate/scb-runner-venv/bin/python',
                             'intermediate/scb-runner-venv/bin/slop-code',
                             'intermediate/provider-cli/node_modules/.bin/codex',
                             'intermediate/provider-cli/node_modules/.bin/claude'):
                if not (cache / relative).is_file():
                    raise RuntimeError(f'Incomplete setup cache: {cache}; missing {relative}')
            return
        # No consumer is linked until ready exists. A failed fill is retryable.
        if cache.exists():
            shutil.rmtree(cache)
        cache.mkdir()
        for name in INPUTS:
            dest = cache / name
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(root / name, dest)
        run('sh', str(cache / 'scripts/scb_install.sh'), cwd=cache, env=env)
        (cache / 'ready').touch()


def attach(root, cache, env):
    local = root / 'intermediate'
    vendor = local / 'vendor'
    vendor.mkdir(parents=True, exist_ok=True)
    for name in VENDORS:
        source, dest = cache / 'intermediate/vendor' / name, vendor / name
        if dest.exists():
            actual = subprocess.check_output(['git', '-C', str(dest), 'rev-parse', 'HEAD'])
            expected = subprocess.check_output(['git', '-C', str(source), 'rev-parse', 'HEAD'])
            if actual != expected:
                raise RuntimeError(f'Wrong revision in {dest}; preserve it and use a fresh checkout.')
            if subprocess.check_output(['git', '-C', str(dest), 'status', '--porcelain']).strip():
                raise RuntimeError(f'Local edits in {dest}; refusing to overwrite.')
        else:
            # Clone files without copying their data blocks. Publish only complete trees.
            with tempfile.TemporaryDirectory(prefix=f'.{name}-', dir=vendor) as staging:
                run('cp', '-cR', str(source), str(Path(staging) / name))
                (Path(staging) / name).rename(dest)
    for name in SHARED:
        dest = local / name
        target = cache / 'intermediate' / name
        if dest.is_symlink():
            if dest.resolve() != target:
                raise RuntimeError(f'Setup inputs changed: preserve {dest} and use a fresh worktree.')
        elif dest.exists():
            raise RuntimeError(f'Existing local installation at {dest}; refusing to overwrite.')
        else:
            dest.symlink_to(target, target_is_directory=True)
    # Solver packages stay local: sandbox access and package installs cannot alter
    # another worktree's runtime. uv reuses the wheels populated by the cold fill.
    solver = local / 'solver-venv'
    if not solver.exists():
        run('uv', 'venv', '--python', '3.12.8', str(solver), env=env)
    run('uv', 'pip', 'install', '--python', str(solver / 'bin/python'),
        '--require-hashes', '-r', str(root / 'configs/solver.lock'), env=env)


def linked_worktree(root):
    result = subprocess.run(['git', '-C', str(root), 'rev-parse',
                             '--path-format=absolute', '--git-dir', '--git-common-dir'],
                            capture_output=True, text=True)
    paths = result.stdout.splitlines()
    return result.returncode == 0 and len(paths) == 2 and Path(paths[0]) != Path(paths[1])


def main():
    if platform.system() != 'Darwin':
        raise RuntimeError('Kojo currently requires macOS sandboxing.')
    if not linked_worktree(ROOT):
        run('sh', str(ROOT / 'scripts/scb_install.sh'), cwd=ROOT)
        return
    # Preserve pre-cache setups rather than replacing user-owned installations.
    if any((ROOT / 'intermediate' / name).exists() and
           not (ROOT / 'intermediate' / name).is_symlink() for name in SHARED):
        if any((ROOT / 'intermediate' / name).is_symlink() for name in SHARED):
            raise RuntimeError('Mixed cached and local installations; use a fresh worktree.')
        run('sh', str(ROOT / 'scripts/scb_install.sh'), cwd=ROOT)
        return
    with run_locks(ROOT):
        cache_root = Path(os.environ.get('KOJO_SETUP_CACHE',
                          str(Path.home() / 'Library/Caches/kojo/setup'))).expanduser().resolve()
        cache_root.mkdir(parents=True, exist_ok=True)
        env = dict(os.environ, UV_CACHE_DIR=str(cache_root / 'uv'),
                   npm_config_cache=str(cache_root / 'npm'))
        env.pop('UV_PROJECT_ENVIRONMENT', None)
        cache = cache_root / cache_key(ROOT)
        prepare_cache(ROOT, cache, env)
        run('uv', 'sync', '--frozen', cwd=ROOT, env=env)
        attach(ROOT, cache, env)
        print(f'Setup complete (cache {cache.name}).')


if __name__ == '__main__':
    try:
        main()
    except (RuntimeError, subprocess.CalledProcessError) as error:
        raise SystemExit(str(error))
