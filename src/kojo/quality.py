"""Static code quality of one frozen snapshot with the pinned scb-check; never executes the code or calls a model."""
import ast
import hashlib
import json
from pathlib import Path
import shutil
import subprocess

from kojo.catalog import BASE
from kojo.gauntlet import hashes

VERSION = '0.1.3'


def prepare(source, dest, entrypoint, normalize):
    shutil.copytree(source, dest, symlinks=True)
    mapping = {}
    entry = dest/entrypoint
    if normalize and entry.is_file() and not entry.is_symlink() and entry.suffix != '.py':
        ast.parse(entry.read_text())
        target = entry.with_name(entry.name + '.py')
        if target.exists():
            raise RuntimeError('Normalized entrypoint collision')
        entry.rename(target)
        mapping[entrypoint] = target.name
    return mapping


def analyze_snapshot(source, entry, scratch, expected=None):
    """One row per variant: `upstream` (native discovery) and `entrypoint-normalized` (extensionless
    entrypoint renamed to .py in an analysis copy). Raw reports and stderr stay under `scratch`."""
    source, scratch = Path(source), Path(scratch)
    before = hashes(source)
    if expected is not None and before != expected:
        raise RuntimeError('Snapshot mismatch')
    rows = []
    for variant in ['upstream', 'entrypoint-normalized']:
        work = scratch/variant
        if work.exists():
            mapping = {entry: entry + '.py'} if variant == 'entrypoint-normalized' and (source/entry).is_file() and not entry.endswith('.py') else {}
        else:
            mapping = prepare(source, work, entry, variant == 'entrypoint-normalized')
        cmd = ['uvx', '--python', '3.12.8', '--constraints', str(BASE/'scripts/quality-requirements.lock'),
               f'scb-check=={VERSION}', 'check', '--report', '--include-all', str(work)]
        cached = scratch/(variant + '.json')
        if cached.exists() and cached.read_text().strip():
            result = subprocess.CompletedProcess(cmd, 0, cached.read_text(), (scratch/(variant + '.stderr.log')).read_text())
        else:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
        (scratch/(variant + '.stderr.log')).write_text(result.stderr)
        cached.write_text(result.stdout)
        if result.returncode and 'no Python files found at' not in result.stderr:
            raise RuntimeError(f'Analyzer failed: {work}')
        report = json.loads(result.stdout) if result.stdout.strip() else {'files_scanned': 0, 'total_loc': 0, 'erosion': None, 'verbosity': None, 'status': 'no_python_files'}
        rows.append({'variant': variant, 'renamed_files': mapping, 'metrics': report, 'stderr_present': bool(result.stderr.strip()),
                     'source_sha256': hashlib.sha256(json.dumps(before, sort_keys=True).encode()).hexdigest()})
    if hashes(source) != before:
        raise RuntimeError('Source changed during analysis')
    return rows


def headline(rows):
    """The entrypoint-normalized metrics, which cover the real implementation."""
    metrics = next(r for r in rows if r['variant'] == 'entrypoint-normalized')['metrics']
    return {key: metrics.get(key) for key in ('files_scanned', 'total_loc', 'erosion', 'verbosity')}
