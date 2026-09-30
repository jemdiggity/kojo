"""Launch a Python or POSIX/Bash entrypoint without assuming its language."""
import ast
import os
from pathlib import Path
import shlex
import sys


def interpreter(path, python):
    if path.is_dir():
        if not (path/'__main__.py').is_file():
            raise ValueError('Directory entrypoint requires __main__.py')
        return [str(python)]
    text=path.read_text(encoding='utf-8-sig')
    first=text.splitlines()[0] if text else ''
    if first.startswith('#!'):
        words=shlex.split(first[2:].strip())
        if not words:raise ValueError('Empty shebang')
        name=Path(words[0]).name
        if name=='env':
            words=words[1:]
            if words and words[0]=='-S':words=words[1:]
            if not words:raise ValueError('Empty env shebang')
            name=Path(words[0]).name
        flags=words[1:]
        if name.startswith('python'):
            return [str(python),*flags]
        if name in ('sh','bash'):
            return ['/bin/'+name,*flags]
        raise ValueError(f'Unsupported entrypoint interpreter: {name}')
    if path.suffix in ('.sh','.bash'):
        return ['/bin/bash' if path.suffix=='.bash' else '/bin/sh']
    # Legacy extensionless Python without a shebang remains supported.
    ast.parse(text,filename=str(path))
    return [str(python)]


def main():
    if len(sys.argv)<2:raise SystemExit('Usage: scb_entrypoint.py ENTRYPOINT [ARGS...]')
    path=Path(sys.argv[1])
    root=os.environ.get('SCB_SUBMISSION_ROOT')
    # Some problems' tests start the program from a temporary directory, so a relative entry file
    # must be resolved against the submission rather than the current directory.
    if root and not path.is_absolute() and (Path(root)/path).exists() and not path.exists():path=Path(root)/path
    path=path.resolve()
    python=Path('.venv/bin/python').absolute()
    if not python.exists():python=Path(sys.executable)
    try:argv=interpreter(path,python)
    except (ValueError,SyntaxError,UnicodeError) as error:raise SystemExit(f'Cannot determine entrypoint language: {error}')
    target=str(path)
    if path.is_dir():
        try:parts=path.relative_to(Path.cwd()).parts
        except ValueError:
            # Tests that start the program from another directory: import the package from its parent instead.
            parts=(path.name,)
            os.environ['PYTHONPATH']=os.pathsep.join(filter(None,[str(path.parent),os.environ.get('PYTHONPATH')]))
        if not parts or not all(part.isidentifier() for part in parts):
            raise SystemExit("Directory entrypoint must have a valid Python module name")
        argv.append("-m");target=".".join(parts)
    os.execv(argv[0],[*argv,target,*sys.argv[2:]])

if __name__=='__main__':main()
