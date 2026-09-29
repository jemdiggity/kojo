"""Atomic, process-locked updates to the shared run index."""
import fcntl
import json
import os
from pathlib import Path
import tempfile

from kojo.catalog import DATA_ROOT


def register_runs(entries, base=DATA_ROOT):
    base = Path(base)
    index = base / 'results/runs/index.json'
    lock = base / 'intermediate/locks/run-index.lock'
    lock.parent.mkdir(parents=True, exist_ok=True)
    index.parent.mkdir(parents=True, exist_ok=True)
    with lock.open('a') as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        items = json.loads(index.read_text()) if index.exists() else []
        for entry in entries:
            current = next((x for x in items if x['run_id'] == entry['run_id']), None)
            if current is None:
                items.append(dict(entry))
            else:
                current.update(entry)
        with tempfile.NamedTemporaryFile(mode='w', dir=index.parent, delete=False) as out:
            temporary = Path(out.name)
            json.dump(items, out, indent=2)
            out.write('\n')
        try:
            os.replace(temporary, index)
        finally:
            temporary.unlink(missing_ok=True)
