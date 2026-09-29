"""Frozen, content-addressed native skill sets; never merge experimental conditions."""
import hashlib
import json
from pathlib import Path
import re
import shutil


def describe(path):
    path = Path(path).expanduser().resolve()
    if not path.is_dir():
        raise ValueError(f'Skill set is not a directory: {path}')
    files = {}
    for p in sorted(path.rglob('*')):
        if p.is_symlink():
            raise ValueError(f'Skill sets cannot contain symlinks: {p}')
        if p.is_file():
            files[str(p.relative_to(path))] = hashlib.sha256(p.read_bytes()).hexdigest()
    roots = [path] if (path/'SKILL.md').is_file() else sorted(p.parent for p in path.glob('*/SKILL.md'))
    if files and not roots:
        raise ValueError('Use SKILL.md at the directory root, or <skill>/SKILL.md; an empty directory is a no-skills condition')
    names = []
    for root in roots:
        text = (root/'SKILL.md').read_text()
        header = text.split('---', 2)
        if len(header) != 3 or header[0].strip():
            raise ValueError(f'Missing skill frontmatter: {root}')
        name = re.search(r'^name:\s*[\"\']?([a-z0-9][a-z0-9-]*)[\"\']?\s*$', header[1], re.M)
        if not name or not re.search(r'^description:\s*\S', header[1], re.M):
            raise ValueError(f'Skill requires name and description: {root}')
        names.append(name[1])
    if len(set(names)) != len(names):
        raise ValueError('Duplicate skill names in a skill set')
    if any(not any(p == r/'SKILL.md' or r in p.parents for r in roots) for p in (path/f for f in files)):
        raise ValueError('All skill-set files must belong to a skill directory')
    digest = hashlib.sha256(json.dumps(files, sort_keys=True).encode()).hexdigest()
    slug = re.sub('[^a-z0-9]+', '-', path.name.lower()).strip('-') or 'skills'
    return {'name': slug+'-'+digest[:10], 'path':str(path), 'sha256':digest,
            'files': files, 'skills': [{'name':n, 'relative':str(r.relative_to(path))} for n,r in zip(names, roots)]}


def describe_sets(paths):
    sets = [describe(p) for p in paths]
    if len({s['path'] for s in sets}) != len(sets) or len({s['name'] for s in sets}) != len(sets):
        raise ValueError('Duplicate skill-set directories or IDs')
    return sets


def freeze_sets(directory, sets):
    result=[]
    for s in sets:
        dest=directory/s['name']
        if dest.exists():
            if describe(dest)['sha256'] != s['sha256']:
                raise ValueError('Frozen skill set differs; choose a new --id')
        else:
            dest.parent.mkdir(parents=True,exist_ok=True)
            shutil.copytree(s['path'],dest)
        if describe(dest)['sha256'] != s['sha256']:
            raise ValueError('Skill set changed while copying')
        result.append({**s,'path':str(dest.resolve())})
    return result


def install(work, source, provider):
    if source is None:
        return None
    spec=describe(source)
    target=Path(work)/('.agents' if provider=='codex' else '.claude')/'skills'
    expected={}
    for skill in spec['skills']:
        root=Path(source)/skill['relative']
        for p in root.rglob('*'):
            if p.is_file():expected[str(Path(skill['name'])/p.relative_to(root))]=hashlib.sha256(p.read_bytes()).hexdigest()
    if target.exists():
        actual={str(p.relative_to(target)):hashlib.sha256(p.read_bytes()).hexdigest() for p in target.rglob('*') if p.is_file()}
        if actual!=expected or any(p.is_symlink() for p in target.rglob('*')):
            raise RuntimeError('Native skill files changed or unexpected skills present')
    else:
        target.mkdir(parents=True)
        for skill in spec['skills']:
            shutil.copytree(Path(source)/skill['relative'],target/skill['name'])
    return {**spec,'installed_root':str(target.resolve())}


def active_source(source):
    """An empty set uses precisely the no-skills provider configuration."""
    return source if source is not None and describe(source)['skills'] else None
