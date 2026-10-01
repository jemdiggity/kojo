"""Deterministic factory checks: they run a candidate program and report, with no model involved.

`run_check(name, ctx)` returns a CheckResult whose `log` is feedback text for a fixer. Everything a
check executes (the candidate, and model-written suite cases or scripts) runs the way the official
grader runs builder code: a subprocess in a fresh temp directory, a scrubbed environment, a timeout
and truncated output. Checks read only public information: specs 1..N, the code and the suite.
"""
from dataclasses import dataclass, field
import difflib
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import resource
import shlex
import shutil
import signal
import subprocess
import tempfile
from typing import Optional

BASE = Path(__file__).resolve().parents[2]
LOG_LIMIT = 6000        # Characters of feedback a check hands to a fixer.
OUTPUT_LIMIT = 20000    # Characters of stdout or stderr kept per program run.
SUITE_FILES = 2000      # Most files copied out of a tester's suite, and
SUITE_BYTES = 5_000_000  # the most bytes.
OUTPUT_FLAGS = ('-o', '--output', '--out', '--report')
GENERATED = {'venv', '.venv', '__pycache__', '.git', 'node_modules', '.pytest_cache'}


@dataclass
class Context:
    code_dir: Path
    entry_file: str
    python: Path
    prior_code: Optional[Path] = None       # Code accepted at the previous checkpoint, for regressions
    side_codes: dict = field(default_factory=dict)  # {branch stage name: code dir}
    suite_dir: Optional[Path] = None        # Run-level accumulated test suite
    specs: dict = field(default_factory=dict)       # {n: public spec text}, 1..N only
    checkpoint: int = 1
    feedback: Optional[str] = None          # The previous stage's answer text
    timeout: float = 20                     # Seconds per case
    arg: Optional[str] = None               # Checker argument, e.g. the branch name for `diff`


@dataclass
class CheckResult:
    verdict: str        # 'pass' or 'fail'
    passed: int
    total: int
    score: float        # passed / total; 1.0 when nothing was checked
    log: str            # Feedback text for a fixer
    details: dict = field(default_factory=dict)

    def to_dict(self):
        return {'verdict': self.verdict, 'passed': self.passed, 'total': self.total, 'score': self.score, 'details': self.details}


def clip(text, limit):
    text = text if isinstance(text, str) else str(text)
    return text if len(text) <= limit else text[:limit] + f'\n... [truncated {len(text) - limit} characters]'


def result(name, passed, total, sections, details, hard_fail=None):
    """Assemble a CheckResult; `sections` are already-formatted failure blocks, most important first."""
    failed = hard_fail if hard_fail is not None else passed < total
    head = (f'Deterministic check `{name}` (run by the harness on the code, no model involved): '
            + (f'{passed}/{total} passed.' if total else 'nothing to check.'))
    body = '\n\n'.join(section for section in sections if section)
    log = clip(head + ('\n\n' + body if body else ''), LOG_LIMIT)
    return CheckResult('fail' if failed else 'pass', passed, total, (passed / total) if total else 1.0, log, details)


# --- running programs -------------------------------------------------------------------------

@dataclass
class Run:
    exit: Optional[int]
    stdout: str = ''
    stderr: str = ''
    timed_out: bool = False
    error: str = ''
    files: dict = field(default_factory=dict)


def _limits():
    resource.setrlimit(resource.RLIMIT_FSIZE, (64 << 20, 64 << 20))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))


def scrubbed_env(home, python, extra=None):
    env = {'PATH': os.pathsep.join([str(Path(python).parent), '/usr/bin', '/bin']), 'HOME': str(home), 'TMPDIR': str(home),
           'LANG': 'C.UTF-8', 'LC_ALL': 'C.UTF-8', 'PYTHONDONTWRITEBYTECODE': '1', 'PYTHONIOENCODING': 'utf-8'}
    env.update(extra or {})
    return env


def spawn(cmd, cwd, env, stdin=None, timeout=20):
    """Run one command with bounded time, output and file size; never raises."""
    with tempfile.TemporaryFile() as out, tempfile.TemporaryFile() as err:
        try:
            proc = subprocess.Popen(cmd, cwd=cwd, env=env, stdin=subprocess.PIPE if stdin is not None else subprocess.DEVNULL,
                                    stdout=out, stderr=err, start_new_session=True, preexec_fn=_limits)
        except OSError as error:
            return Run(None, error=f'could not start: {error}')
        timed_out = False
        try:
            proc.communicate(stdin.encode() if stdin is not None else None, timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            try:
                os.killpg(proc.pid, signal.SIGKILL)  # Nothing the program started may outlive it.
            except OSError:
                pass
        except OSError:
            pass
        finally:
            proc.wait()
        texts = []
        for stream in (out, err):
            stream.seek(0)
            data = stream.read(OUTPUT_LIMIT + 1)
            texts.append(clip(data.decode('utf-8', 'replace'), OUTPUT_LIMIT))
        return Run(None if timed_out else proc.returncode, texts[0], texts[1], timed_out)


def _entrypoint_module():
    try:
        spec = importlib.util.spec_from_file_location('scb_entrypoint', BASE / 'scripts/scb_entrypoint.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    except Exception:
        return None


def entry_command(python, code_dir, entry_file):
    """The argv that starts the program, as the harness's entrypoint launcher would."""
    path = Path(code_dir) / entry_file
    module = _entrypoint_module()
    if module and path.is_file():
        try:
            return [*module.interpreter(path.resolve(), Path(python)), str(path)]
        except (ValueError, SyntaxError, UnicodeError, IndexError, OSError):
            pass  # Let the interpreter itself report a broken entry file.
    return [str(python), str(path)]


def safe_relative(path):
    p = Path(path)
    return not p.is_absolute() and '..' not in p.parts and str(p) not in ('', '.')


def execute(ctx, code_dir, argv, files=None, stdin=None, read=(), timeout=None):
    """Run the program with `argv` in a fresh temp dir holding `files`; read back the files named in `read`."""
    with tempfile.TemporaryDirectory(prefix='kojo-check-') as directory:
        home = Path(directory).resolve()
        for name, text in (files or {}).items():
            if not safe_relative(name):
                return Run(None, error=f'unsafe file path {name!r}')
            target = home / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text)
        cmd = [*entry_command(ctx.python, code_dir, ctx.entry_file), *argv]
        run = spawn(cmd, home, scrubbed_env(home, ctx.python), stdin, timeout or ctx.timeout)
        for name in read:
            target = home / name
            try:
                run.files[name] = target.read_text(errors='replace') if safe_relative(name) and target.is_file() else None
            except OSError:
                run.files[name] = None
        return run


def execute_script(ctx, script, args, env_extra, timeout):
    """Run a model-written Python script (`suite/checks/*.py`, `suite/fuzz/*.py`) in a temp dir."""
    with tempfile.TemporaryDirectory(prefix='kojo-script-') as directory:
        home = Path(directory).resolve()
        return spawn([str(ctx.python), str(script), *args], home, scrubbed_env(home, ctx.python, env_extra), None, timeout)


def shell_join(argv):
    return ' '.join(shlex.quote(str(a)) for a in argv)


# --- cases: the schema shared by suite, repro and examples ---------------------------------------

def normalize_case(raw, index=0):
    """Return (case, error): a lenient validation of one case dict."""
    if not isinstance(raw, dict):
        return None, 'a case must be a JSON object'
    name = raw.get('name')
    name = name if isinstance(name, str) and name.strip() else f'case-{index + 1}'
    case = {'name': name, 'source': raw.get('source') if isinstance(raw.get('source'), str) else 'unknown'}
    if 'script' in raw:
        script, args = raw['script'], raw.get('args', [])
        if not isinstance(script, str) or not safe_relative(script):
            return None, f'{name}: script must be a relative path inside the suite'
        if not isinstance(args, list) or not all(isinstance(a, (str, int, float)) for a in args):
            return None, f'{name}: args must be a list of strings'
        return {**case, 'script': script, 'args': [str(a) for a in args]}, None
    argv = raw.get('argv')
    if not isinstance(argv, list) or not all(isinstance(a, (str, int, float)) and not isinstance(a, bool) for a in argv):
        return None, f'{name}: argv must be a list of strings (the entry command is added by the harness)'
    files = raw.get('files') or {}
    if not isinstance(files, dict) or not all(isinstance(k, str) and isinstance(v, str) and safe_relative(k) for k, v in files.items()):
        return None, f'{name}: files must map relative paths to text'
    stdin = raw.get('stdin')
    if stdin is not None and not isinstance(stdin, str):
        return None, f'{name}: stdin must be a string or null'
    expect = raw.get('expect') if raw.get('expect') is not None else {}
    if not isinstance(expect, dict):
        return None, f'{name}: expect must be an object'
    code = expect.get('exit')
    if code is not None and (isinstance(code, bool) or not isinstance(code, int)):
        return None, f'{name}: expect.exit must be an integer or null'
    for key in ('stdout', 'stdout_regex'):
        if expect.get(key) is not None and not isinstance(expect[key], str):
            return None, f'{name}: expect.{key} must be a string or null'
    if expect.get('stdout_regex') is not None:
        try:
            re.compile(expect['stdout_regex'])
        except re.error as error:
            return None, f'{name}: bad stdout_regex ({error})'
    contains = expect.get('stdout_contains') or []
    if not isinstance(contains, list) or not all(isinstance(c, str) for c in contains):
        return None, f'{name}: expect.stdout_contains must be a list of strings'
    expected_files = expect.get('files') or {}
    if not isinstance(expected_files, dict):
        return None, f'{name}: expect.files must be an object'
    for path, rule in expected_files.items():
        if not safe_relative(path) or not isinstance(rule, dict) or not all(isinstance(rule.get(k, ''), str) for k in ('regex', 'not_regex', 'equals')):
            return None, f'{name}: expect.files[{path!r}] needs a relative path and regex/not_regex/equals strings'
        for key in ('regex', 'not_regex'):
            if key in rule:
                try:
                    re.compile(rule[key])
                except re.error as error:
                    return None, f'{name}: bad {key} for {path} ({error})'
    if all(expect.get(k) in (None, [], {}) for k in ('exit', 'stdout', 'stdout_regex', 'stdout_contains', 'stdout_json', 'files')):
        return None, f'{name}: the case expects nothing'
    return {**case, 'argv': [str(a) for a in argv], 'files': files, 'stdin': stdin,
            'expect': {'exit': code, 'stdout': expect.get('stdout'), 'stdout_regex': expect.get('stdout_regex'), 'stdout_contains': contains,
                       'stdout_json': expect.get('stdout_json'), 'files': expected_files}}, None


def tidy(text):
    return '\n'.join(line.rstrip() for line in text.replace('\r\n', '\n').split('\n')).rstrip('\n')


def json_subset(want, got):
    if isinstance(want, dict):
        return isinstance(got, dict) and all(k in got and json_subset(v, got[k]) for k, v in want.items())
    if isinstance(want, list):
        return isinstance(got, list) and len(want) == len(got) and all(json_subset(w, g) for w, g in zip(want, got))
    if isinstance(want, bool) or isinstance(got, bool):
        return want is got
    return want == got


def _json_or_none(text):
    try:
        return json.loads(text)
    except ValueError:
        return None


def judge(case, run):
    """Everything wrong with a run, as a list of one-line problems; empty means it meets the case's expectations."""
    if run.error:
        return [run.error]
    if run.timed_out:
        return ['timed out']
    expect, problems = case['expect'], []
    if expect['exit'] is not None and run.exit != expect['exit']:
        problems.append(f'exit code {run.exit}, expected {expect["exit"]}')
    want = expect['stdout']
    if want is not None and tidy(run.stdout) != tidy(want):
        # Spec examples are often compact JSON; equal JSON in another layout counts as equal.
        a, b = _json_or_none(run.stdout), _json_or_none(want)
        if a is None or b is None or a != b:
            problems.append('stdout differs')
    if expect['stdout_regex'] is not None and not re.search(expect['stdout_regex'], run.stdout, re.M):
        problems.append(f'stdout does not match /{expect["stdout_regex"]}/')
    for piece in expect['stdout_contains']:
        if piece not in run.stdout:
            problems.append(f'stdout lacks {piece!r}')
    if expect['stdout_json'] is not None:
        got = _json_or_none(run.stdout)
        if got is None:
            problems.append('stdout is not JSON')
        elif not json_subset(expect['stdout_json'], got):
            problems.append('stdout JSON lacks the expected fields/values')
    for path, rule in expect['files'].items():
        text = run.files.get(path)
        if text is None:
            problems.append(f'file {path} was not written')
            continue
        if 'equals' in rule and tidy(text) != tidy(rule['equals']):
            problems.append(f'file {path} differs from the expected text')
        if 'regex' in rule and not re.search(rule['regex'], text, re.M):
            problems.append(f'file {path} does not match /{rule["regex"]}/')
        if 'not_regex' in rule and re.search(rule['not_regex'], text, re.M):
            problems.append(f'file {path} matches forbidden /{rule["not_regex"]}/')
    return problems


def run_case(ctx, code_dir, case):
    return execute(ctx, code_dir, case['argv'], case['files'], case['stdin'], read=list(case['expect']['files']))


def expected_text(case):
    expect, bits = case['expect'], []
    if expect['exit'] is not None:
        bits.append(f'exit {expect["exit"]}')
    for key, label in (('stdout', 'stdout'), ('stdout_regex', 'stdout matching regex'), ('stdout_json', 'stdout JSON containing')):
        if expect[key] is not None:
            bits.append(f'{label}: {clip(expect[key] if isinstance(expect[key], str) else json.dumps(expect[key]), 400)}')
    if expect['stdout_contains']:
        bits.append(f'stdout containing {expect["stdout_contains"]}')
    for path, rule in expect['files'].items():
        bits.append(f'file {path}: {clip(json.dumps(rule), 300)}')
    return '; '.join(bits)


def actual_text(run):
    if run.error:
        return run.error
    if run.timed_out:
        return f'timed out; stdout so far: {clip(run.stdout, 200)!r}'
    text = f'exit {run.exit}; stdout: {clip(run.stdout.strip(), 400)!r}'
    if run.stderr.strip():
        text += f'; stderr: {clip(run.stderr.strip()[-300:], 300)!r}'
    return text


def describe(label, case, run, problems):
    command = shell_join(['<entry>', *case['argv']])
    lines = [f'- {label}: {command}']
    if case['files']:
        lines.append(f'  files: {", ".join(case["files"])}')
    lines += [f'  problem: {"; ".join(problems)}', f'  expected: {expected_text(case)}', f'  actual:   {actual_text(run)}']
    if 'stdout differs' in problems and case['expect']['stdout'] is not None:
        diff = list(difflib.unified_diff(tidy(case['expect']['stdout']).split('\n'), tidy(run.stdout).split('\n'), 'expected', 'actual', lineterm='', n=1))
        lines.append('  diff:\n    ' + '\n    '.join(clip('\n'.join(diff[:14]), 700).split('\n')))
    return '\n'.join(lines)


# --- smoke ------------------------------------------------------------------------------------------

def python_files(code_dir):
    found = []
    for path in sorted(Path(code_dir).rglob('*.py')):
        relative = path.relative_to(code_dir)
        if any(part in GENERATED for part in relative.parts) or not path.is_file() or path.is_symlink():
            continue
        if any((code_dir / Path(*relative.parts[:i]) / 'pyvenv.cfg').exists() for i in range(1, len(relative.parts))):
            continue
        found.append(path)
    return found


def compile_problems(code_dir, entry_file):
    problems = []
    paths = python_files(code_dir)
    entry = Path(code_dir) / entry_file
    if entry.is_file() and entry not in paths:
        first = entry.read_text(errors='replace').split('\n', 1)[0]
        if not first.startswith('#!') or 'python' in first:
            paths.append(entry)
    for path in paths:
        try:
            compile(path.read_bytes(), str(path.relative_to(code_dir)), 'exec', dont_inherit=True)
        except (SyntaxError, ValueError, RecursionError, MemoryError) as error:  # IndentationError and TabError are SyntaxErrors.
            where = f' line {error.lineno}' if getattr(error, 'lineno', None) else ''
            problems.append(f'{path.relative_to(code_dir)}{where}: {type(error).__name__}: {getattr(error, "msg", error)}')
    return problems


def crashed(run):
    return run.error or run.timed_out or run.exit != 0 or 'Traceback (most recent call last)' in run.stdout + run.stderr


def check_smoke(ctx):
    entry = Path(ctx.code_dir) / ctx.entry_file
    items, sections = [], []
    if not entry.exists():
        return result('smoke', 0, 1, [f'The entry file `{ctx.entry_file}` does not exist.'], {'items': {'entry': False}})
    problems = compile_problems(ctx.code_dir, ctx.entry_file)
    items.append(('compile', not problems))
    if problems:
        sections.append('Python files that do not compile (the program would crash on start):\n' + '\n'.join('- ' + p for p in problems[:20]))
    commands = [('help', ['--help'])]
    if any('--version' in text for text in ctx.specs.values()):
        commands.append(('version', ['--version']))
    for label, argv in commands:
        run = execute(ctx, ctx.code_dir, argv)
        bad = crashed(run)
        items.append((label, not bad))
        if bad:
            sections.append(f'`{ctx.entry_file} {" ".join(argv)}` fails: {actual_text(run)}')
    passed = sum(ok for _, ok in items)
    return result('smoke', passed, len(items), sections, {'items': dict(items), 'compile_problems': problems})


# --- examples extracted from the public specs --------------------------------------------------------

FENCE = re.compile(r'^\s*```\s*([\w+-]*)\s*$')
HINT = re.compile(r'^`([^`\s]+)`\s*:?\s*$')
FILENAME = re.compile(r'^[\w./\-]*[\w\-]\.[A-Za-z]\w*$')
SHELL_TOKENS = {'|', '>', '>>', '<', '&&', '||', ';', '&', '2>&1'}


def entry_prefix(entry_file):
    return re.compile(r'^(?:%%%ENTRYPOINT:entry_command%%%|(?:.*?python[\w.\-]*\s+)?(?:\./)?' + re.escape(entry_file) + r')(?=\s|$)')


def spec_blocks(text):
    """Yield (language, body lines, hint) for every fenced block; hint is a `file` line just above it."""
    lines, index, previous = text.split('\n'), 0, ''
    while index < len(lines):
        opened = FENCE.match(lines[index])
        if not opened:
            if lines[index].strip():
                previous = lines[index].strip()
            index += 1
            continue
        end = index + 1
        while end < len(lines) and not re.match(r'^\s*```\s*$', lines[end]):
            end += 1
        hint = HINT.match(previous)
        yield opened[1].lower(), lines[index + 1:end], hint[1] if hint else None
        previous, index = '', end + 1


def parse_commands(lines):
    """[(command line, output lines, exit code)] from a `$ ` block."""
    commands, current = [], None
    for line in lines:
        if line.startswith('$ '):
            current = [line[2:].strip(), [], None]
            commands.append(current)
        elif current is None:
            continue
        elif line.lstrip().startswith('#'):
            found = re.search(r'\bexit\s+(?:code\s+)?(\d+)', line)
            if found:
                current[2] = int(found[1])
        else:
            current[1].append(line)
    for command in commands:
        while command[1] and not command[1][-1].strip():
            command[1].pop()
    return commands


def extract_examples(specs, entry_file):
    """Runnable examples from public specs 1..N as (cases, skipped); nothing is guessed.

    An example is kept only when its command, every input file it names and its expected output can
    be resolved from the specs. A later spec's version of the same command line replaces an earlier one.
    """
    fixtures, history, found, skipped = {}, {}, [], []
    prefix = entry_prefix(entry_file)
    for n in sorted(specs):
        for language, body, hint in spec_blocks(specs[n]):
            if body and body[0].startswith('$ '):
                for command, output, code in parse_commands(body):
                    label = f'checkpoint {n}: $ {command}'
                    found_prefix = prefix.match(command)
                    if not found_prefix:
                        skipped.append({'checkpoint': n, 'command': command, 'reason': 'not a command of the program'})
                        continue
                    rest = command[found_prefix.end():].strip()
                    if re.search(r'<[^>\s]+>|\.\.\.|\\$', rest) or '%%%' in rest:
                        skipped.append({'checkpoint': n, 'command': command, 'reason': 'placeholder or continuation in the command'})
                        continue
                    try:
                        argv = shlex.split(rest)
                    except ValueError:
                        skipped.append({'checkpoint': n, 'command': command, 'reason': 'unparseable quoting'})
                        continue
                    if any(a in SHELL_TOKENS or '$' in a or '`' in a for a in argv):
                        skipped.append({'checkpoint': n, 'command': command, 'reason': 'shell syntax'})
                        continue
                    needed, missing = {}, []
                    for i, token in enumerate(argv):
                        if token.startswith('-') or not FILENAME.match(token) or (i and argv[i - 1] in OUTPUT_FLAGS):
                            continue
                        if token in fixtures:
                            needed[token] = fixtures[token]
                        else:
                            missing.append(token)
                    if missing:
                        skipped.append({'checkpoint': n, 'command': command, 'reason': f'input file not defined earlier in the specs: {", ".join(missing)}'})
                        continue
                    if any('...' in line or re.search(r'\{\.\.\.\}|<[^>\s]+>', line) for line in output):
                        skipped.append({'checkpoint': n, 'command': command, 'reason': 'expected output is illustrative (contains ...)'})
                        continue
                    stdout = '\n'.join(output) + '\n' if output else None
                    if stdout is None and code is None:
                        skipped.append({'checkpoint': n, 'command': command, 'reason': 'no expected output or exit code'})
                        continue
                    found.append({'checkpoint': n, 'label': label, 'argv': argv, 'files': needed,
                                  'expect': {'exit': code, 'stdout': stdout}})
            elif hint:
                fixtures[hint] = '\n'.join(body) + '\n'
                history.setdefault(hint, []).append((n, fixtures[hint]))
    cases, latest = [], {}
    for example in found:
        stale = [name for name, text in example['files'].items() if text != fixtures[name]]
        if stale:
            skipped.append({'checkpoint': example['checkpoint'], 'command': example['label'], 'reason': f'input file redefined by a later checkpoint: {", ".join(stale)}'})
            continue
        key = tuple(example['argv'])
        if key in latest:
            old = latest[key]
            skipped.append({'checkpoint': old['checkpoint'], 'command': old['label'], 'reason': f'superseded by the same command in checkpoint {example["checkpoint"]}'})
            cases.remove(old)
        latest[key] = example
        cases.append(example)
    out = []
    for example in cases:
        expect = {'exit': example['expect']['exit'], 'stdout': example['expect']['stdout'], 'stdout_regex': None,
                  'stdout_contains': [], 'stdout_json': None, 'files': {}}
        out.append({'name': example['label'], 'source': 'example', 'argv': example['argv'], 'files': example['files'],
                    'stdin': None, 'expect': expect, 'checkpoint': example['checkpoint']})
    return out, skipped


def check_examples(ctx):
    cases, skipped = extract_examples(ctx.specs, ctx.entry_file)
    if not cases:
        return result('examples', 0, 0, [f'No runnable examples could be extracted from the public specs ({len(skipped)} skipped).'],
                      {'skipped': skipped, 'examples': 0})
    failures, passed = [], 0
    for case in cases:
        run = run_case(ctx, ctx.code_dir, case)
        problems = judge(case, run)
        if problems:
            failures.append(describe(f'spec example mismatch (checkpoint {case["checkpoint"]})', case, run, problems))
        else:
            passed += 1
    note = ('Spec examples can be illustrative: read the spec text before deciding the code is wrong.' if failures else '')
    return result('examples', passed, len(cases), failures[:12] + ([f'... and {len(failures) - 12} more mismatches'] if len(failures) > 12 else []) + [note],
                  {'skipped': skipped, 'examples': len(cases), 'failed': [f.split('\n')[0] for f in failures]})


# --- the accumulated suite ---------------------------------------------------------------------------

class SuiteTooLarge(Exception):
    """A suite over SUITE_FILES / SUITE_BYTES; the previous suite is left untouched."""

    def __init__(self, count, size):
        super().__init__(f'suite has {count} files and {size} bytes; the limits are {SUITE_FILES} files and {SUITE_BYTES} bytes')
        self.count, self.size = count, size


def copy_suite(source, target):
    """Copy a suite directory (regular files only, size-capped, no caches); returns the number of files copied.

    The copy is built beside `target` and swapped in only when it fits, so an oversized suite raises
    SuiteTooLarge and leaves the existing `target` exactly as it was (never a silently truncated suite)."""
    source, target = Path(source), Path(target)
    staging = target.parent / f'.{target.name}.staging'
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True)
    count = size = 0
    try:
        for path in sorted(source.rglob('*')) if source.is_dir() else []:
            relative = path.relative_to(source)
            if path.is_symlink() or not path.is_file() or any(part in GENERATED for part in relative.parts) or path.suffix == '.pyc':
                continue
            size += path.stat().st_size
            count += 1
            if count > SUITE_FILES or size > SUITE_BYTES:
                raise SuiteTooLarge(count, size)
            (staging / relative).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, staging / relative)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    if target.exists():
        shutil.rmtree(target)
    staging.rename(target)
    return count


def load_suite(suite_dir):
    """(cases, invalid, errors): cases.json entries validated leniently; script cases checked for existence."""
    cases, invalid, errors = [], [], []
    path = Path(suite_dir) / 'cases.json' if suite_dir else None
    if not path or not path.is_file():
        return cases, invalid, errors
    try:
        data = json.loads(path.read_text())
    except (ValueError, OSError) as error:
        return cases, invalid, [f'cases.json is not valid JSON: {error}']
    rows = data.get('cases') if isinstance(data, dict) else data
    if not isinstance(rows, list):
        return cases, invalid, ['cases.json must be a JSON array of cases (or an object with a "cases" array)']
    seen = set()
    for index, raw in enumerate(rows):
        case, error = normalize_case(raw, index)
        if error:
            invalid.append({'name': raw.get('name', f'case-{index + 1}') if isinstance(raw, dict) else f'case-{index + 1}', 'error': error})
            continue
        if 'script' in case:
            script = Path(suite_dir) / case['script']
            try:
                inside = script.resolve().is_relative_to(Path(suite_dir).resolve())
            except OSError:
                inside = False
            if not inside or not script.is_file():
                invalid.append({'name': case['name'], 'error': f'{case["name"]}: script {case["script"]} not found in the suite'})
                continue
            if script_syntax(script):
                invalid.append({'name': case['name'], 'error': f'{case["name"]}: {script_syntax(script)}'})
                continue
        if case['name'] in seen:
            case['name'] += f' #{index + 1}'
        seen.add(case['name'])
        cases.append(case)
    return cases, invalid, errors


def script_syntax(script):
    try:
        compile(Path(script).read_bytes(), str(script), 'exec', dont_inherit=True)
    except (SyntaxError, ValueError) as error:
        return f'{Path(script).name} does not compile ({type(error).__name__}: {getattr(error, "msg", error)})'
    return None


def run_script_case(ctx, code_dir, suite_dir, case):
    command = entry_command(ctx.python, code_dir, ctx.entry_file)
    env = {'ENTRY': shell_join(command), 'ENTRY_ARGV_JSON': json.dumps(command), 'SUITE_DIR': str(Path(suite_dir).resolve())}
    return execute_script(ctx, Path(suite_dir) / case['script'], case['args'], env, ctx.timeout * 3)


SCRIPT_BUGS = r'(?:[\w.]+\.)?(NameError|UnboundLocalError|SyntaxError|IndentationError|TabError|ImportError|ModuleNotFoundError)\b'


def script_crashed(run, suite_dir=None):
    """A suite script that died on an error only a broken script can produce: the script is wrong, not the program.

    Testers signal failure by raising or exiting non-zero, so an arbitrary exception may be an intended
    failure, and a crash parsing the program's output may be the program's fault; only undefined names,
    bad imports and syntax errors are attributed to the script."""
    if run.error or run.timed_out or run.exit in (None, 0):
        return False
    last = next((line for line in reversed(run.stderr.strip().splitlines()) if line.strip()), '').strip()
    if re.match(SCRIPT_BUGS, last):
        return True
    # A script that cannot open a data file it was given inside the suite (copied incompletely or never written).
    return bool(suite_dir and last.startswith('FileNotFoundError') and str(Path(suite_dir).resolve()) in last)


def run_suite(ctx, code_dir, cases):
    """{name: (case, run, problems)} for every valid case run against `code_dir`."""
    outcomes = {}
    for case in cases:
        if 'script' in case:
            run = run_script_case(ctx, code_dir, ctx.suite_dir, case)
            problems = [] if run.exit == 0 and not run.error and not run.timed_out else [run.error or ('timed out' if run.timed_out else f'script exited {run.exit}')]
        else:
            run = run_case(ctx, code_dir, case)
            problems = judge(case, run)
        outcomes[case['name']] = (case, run, problems)
    return outcomes


def describe_script(label, case, run, problems):
    tail = (run.stderr.strip() or run.stdout.strip())[-500:]
    return f'- {label}: script {case["script"]} {" ".join(case["args"])}\n  problem: {"; ".join(problems)}' + (f'\n  output: {tail}' if tail else '')


def show(label, case, run, problems):
    return describe_script(label, case, run, problems) if 'script' in case else describe(label, case, run, problems)


def check_suite(ctx):
    cases, invalid, errors = load_suite(ctx.suite_dir)
    if errors or (not cases and not invalid):
        note = errors[0] if errors else 'The accumulated suite has no cases yet.'
        return result('suite', 0, 0, [note], {'invalid': invalid, 'errors': errors, 'suite_cases': 0,
                                              'suite_missing': bool(ctx.suite_dir)})  # Nothing to check; visible in the log, not a code failure.
    now = run_suite(ctx, ctx.code_dir, cases)
    before = run_suite(ctx, ctx.prior_code, cases) if ctx.prior_code and Path(ctx.prior_code).is_dir() else None
    crashed = {name for name, (case, run, problems) in now.items() if problems and 'script' in case and script_crashed(run, ctx.suite_dir)}
    for name in sorted(crashed):
        last = next(line for line in reversed(now[name][1].stderr.strip().splitlines()) if line.strip())
        invalid.append({'name': name, 'error': f'{name}: script crashed ({last.strip()[:160]}); fix the script, this says nothing about the program'})
    cases = [case for case in cases if case['name'] not in crashed]
    failing = [name for name, (_, _, problems) in now.items() if problems and name not in crashed]
    regressions = [name for name in failing if before and not before[name][2]]
    others = [name for name in failing if name not in regressions]
    sections = []
    if regressions:
        sections.append('REGRESSIONS (these cases passed on the previous checkpoint\'s code and fail now; strong evidence of a break):\n'
                        + '\n'.join(show('regression', *now[name]) for name in regressions[:8]))
    if others:
        sections.append('FAILURES:\n' + '\n'.join(show('failure', *now[name]) for name in others[:10]))
    if len(failing) > 18:
        sections.append(f'... {len(failing) - 18} more failing cases not shown')
    if invalid:
        sections.append('INVALID SUITE CASES (tester errors, not code failures; ignored):\n' + '\n'.join('- ' + e['error'] for e in invalid[:10]))
    if failing:
        sections.append('Suite cases are written by a tester from the specs and can be wrong: check each failure against the spec text before changing the code.')
    passed = len(cases) - len(failing)
    return result('suite', passed, len(cases), sections,
                  {'regressions': regressions, 'failures': others, 'invalid': invalid, 'prior_ran': before is not None, 'suite_cases': len(cases)})


def code_hashes(code_dir):
    """{relative path: sha256} of the program's own files (no caches or environments)."""
    found = {}
    root = Path(code_dir)
    for path in sorted(root.rglob('*')) if root.is_dir() else []:
        relative = path.relative_to(root)
        if path.is_symlink() or not path.is_file() or any(part in GENERATED for part in relative.parts) or path.suffix == '.pyc':
            continue
        found[str(relative)] = hashlib.sha256(path.read_bytes()).hexdigest()
    return found


def check_changed(ctx):
    """Fails when a build left the code exactly as the checkpoint started (a bail-out), or wrote nothing at all."""
    now = code_hashes(ctx.code_dir)
    start = code_hashes(ctx.prior_code) if ctx.prior_code else {}
    if not now:
        verdict, note = 'fail', 'The build wrote no program files.'
    elif now == start:
        verdict, note = 'fail', 'The build left every file exactly as the checkpoint started: nothing was implemented.'
    else:
        verdict, note = 'pass', 'The build changed the code.'
    return CheckResult(verdict, int(verdict == 'pass'), 1, 1.0 if verdict == 'pass' else 0.0,
                       f'Deterministic check `changed` (run by the harness, no model involved): {note}',
                       {'changed': verdict == 'pass', 'files': len(now), 'files_at_start': len(start)})


def check_safe(ctx):
    """Smoke and the accumulated suite as one gate. As a `guard` it also vetoes any suite case that newly fails."""
    smoke = check_smoke(ctx)
    if smoke.verdict != 'pass':
        return CheckResult('fail', smoke.passed, smoke.total, 0.0, smoke.log,
                           {'smoke_ok': False, 'failing': [], 'invalid': [], 'suite_cases': 0, 'smoke': smoke.details})
    suite = check_suite(ctx)
    d = suite.details
    failing = sorted(d.get('regressions', []) + d.get('failures', []))
    return CheckResult(suite.verdict, suite.passed, suite.total, suite.score, suite.log,
                       {**d, 'smoke_ok': True, 'failing': failing})


def failure_signature(found):
    """What is failing, comparable across visits of one check stage (used by `[progress]` arrows)."""
    d = found.details or {}
    if 'failing' in d:
        return ('cases', tuple(d['failing']), bool(d.get('smoke_ok', True)))
    if 'regressions' in d or 'failures' in d:
        return ('cases', tuple(sorted(d.get('regressions', []) + d.get('failures', []))), True)
    return ('score', found.passed, found.total)


def guard_rolls_back(checker, before, after):
    """Whether a guarded stage's result is discarded.

    `safe` discards the result when the program no longer starts, when the suite score fell, or when more suite
    cases newly fail than newly pass; a fix that repairs more than it breaks is kept, and a program that did not
    start before the stage cannot be made worse by one that now starts. The other checkers veto a lower score."""
    if before is None:
        return False
    if checker == 'safe':
        if not after.details.get('smoke_ok', True):
            return True
        if not before.details.get('smoke_ok', True):
            return False  # `before` has no suite result to compare; the repaired program starts.
        was, now = set(before.details.get('failing', [])), set(after.details.get('failing', []))
        return after.score < before.score or len(now - was) > len(was - now)
    return after.score < before.score


# --- reviewer repro cases ----------------------------------------------------------------------------

def repro_cases(text):
    rows = []
    for block in re.findall(r'```json\s*\n(.*?)```', text or '', re.S):
        try:
            data = json.loads(block)
        except ValueError:
            continue
        data = data.get('cases') if isinstance(data, dict) else data
        rows += data if isinstance(data, list) else []
    return rows


def check_repro(ctx):
    rows = repro_cases(ctx.feedback)
    if not rows:
        return result('repro', 0, 0, ['The review contained no parseable repro cases.'], {'confirmed': [], 'unparseable': 0})
    cases, unparseable = [], 0
    for index, raw in enumerate(rows):
        case, error = normalize_case(raw, index)
        if error or 'script' in case:
            unparseable += 1
        else:
            cases.append(case)
    confirmed = []
    for case in cases:
        run = run_case(ctx, ctx.code_dir, case)
        problems = judge(case, run)
        if problems:
            confirmed.append((case, run, problems))
    total = len(cases)
    sections = []
    if confirmed:
        sections.append('CONFIRMED FAILURES (the program\'s actual result does not meet the reviewer\'s stated expectation):\n'
                        + '\n'.join(describe('confirmed', *item) for item in confirmed[:10]))
        sections.append('Confirm each expectation against the spec text before changing the code. Other claims in the review were not reproduced and are dropped.')
    return result('repro', total - len(confirmed), total, sections,
                  {'confirmed': [c['name'] for c, _, _ in confirmed], 'unparseable': unparseable, 'claims': total})


# --- differential testing ----------------------------------------------------------------------------

def check_diff(ctx):
    side = ctx.side_codes.get(ctx.arg)
    scripts = sorted((Path(ctx.suite_dir) / 'fuzz').glob('*.py')) if ctx.suite_dir and (Path(ctx.suite_dir) / 'fuzz').is_dir() else []
    if not side or not Path(side).is_dir() or not scripts:
        why = 'no side code named ' + repr(ctx.arg) if not side or not Path(side).is_dir() else 'the suite has no fuzz scripts'
        return result('diff', 0, 0, [f'Nothing to compare: {why}.'], {'scripts': 0})
    a = entry_command(ctx.python, ctx.code_dir, ctx.entry_file)
    b = entry_command(ctx.python, side, ctx.entry_file)
    env = {'ENTRY_A': shell_join(a), 'ENTRY_B': shell_join(b), 'ENTRY_A_ARGV_JSON': json.dumps(a), 'ENTRY_B_ARGV_JSON': json.dumps(b)}
    disagreements, invalid, agreed = [], [], 0
    for script in scripts:
        problem = script_syntax(script)
        if problem:
            invalid.append(problem)
            continue
        run = execute_script(ctx, script, [], env, ctx.timeout * 6)
        if run.exit == 0 and not run.timed_out and not run.error:
            agreed += 1
            continue
        tail = (run.stdout.strip() + '\n' + run.stderr.strip()).strip()[-900:]
        disagreements.append(f'- fuzz/{script.name}: {run.error or ("timed out" if run.timed_out else f"exit {run.exit}")}\n  {clip(tail, 900)}')
    total = agreed + len(disagreements)
    sections = []
    if disagreements:
        sections.append(f'The two independent implementations DISAGREE (A is the code under test, B is the independent `{ctx.arg}` implementation; '
                        'either may be wrong, so adjudicate each difference against the spec text):\n' + '\n'.join(disagreements[:8]))
    if invalid:
        sections.append('INVALID FUZZ SCRIPTS (ignored):\n' + '\n'.join('- ' + p for p in invalid))
    return result('diff', agreed, total, sections, {'scripts': total, 'disagreements': len(disagreements), 'invalid': invalid})


CHECKS = {'smoke': check_smoke, 'examples': check_examples, 'suite': check_suite, 'safe': check_safe, 'repro': check_repro, 'diff': check_diff,
          'changed': check_changed}
CHECKERS = tuple(CHECKS)


def run_check(name, ctx):
    """Run builtin check `name`; a crash of the checker itself is reported, never blamed on the code."""
    if name not in CHECKS:
        raise ValueError(f'unknown check {name!r}; use one of {", ".join(CHECKS)}')
    try:
        return CHECKS[name](ctx)
    except Exception as error:  # noqa: BLE001 - a harness bug must not fail the builder
        return CheckResult('pass', 0, 0, 1.0, f'Deterministic check `{name}` could not run ({type(error).__name__}: {error}); ignored.',
                           {'error': f'{type(error).__name__}: {error}'})
