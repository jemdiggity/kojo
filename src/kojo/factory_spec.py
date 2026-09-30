"""A small text language describing a factory: who does each stage and how stages flow.

    # luna builds, opus refactors, then opus reviews and luna fixes up to 5 times
    build    = luna6
    refactor = opus55:high
    review   = opus55:high
    fix      = luna6

    build -> refactor -> review
    review -[fail, max 5]-> fix -> review

Stages are `NAME = [KIND] MODEL[:EFFORT] [xN] [by CHECKER] [guard CHECKER] [prompt NAME]`, or
`NAME = check CHECKER [ARG]` for a deterministic stage without a model; KIND defaults to NAME. A
flow line chains stages with arrows, and an arrow may carry `[pass]`, `[fail]`, `[max N]` and
`[reset]` in any mix. See docs/factory-language.md.
"""
from dataclasses import dataclass, field
import hashlib
from pathlib import Path
import re

BASE = Path(__file__).resolve().parents[2]

MODELS = {
    'sonnet55': 'claude-sonnet-5-5',
    'opus55': 'claude-opus-5-5',
    'sol61': 'gpt-6.1-sol',
    'sol6': 'gpt-6-sol',
    'astra6': 'gpt-6-astra',
    'opus5': 'claude-opus-5',
    'sol56': 'gpt-5.6-sol',
    'fable51': 'claude-fable-5-1',
    'opus46': 'claude-opus-4-6',
    'sonnet46': 'claude-sonnet-4-6',
    'haiku45': 'claude-haiku-4-5-20251001',
    'luna6': 'gpt-6-luna',
}
EFFORTS = {'claude': ('low', 'medium', 'high'), 'codex': ('low', 'medium', 'high', 'xhigh', 'max')}
DEFAULT_EFFORT = 'medium'
EDIT = ('build', 'revise', 'refactor', 'fix', 'branch')  # Change code; all but a branch carry it forward.
READ = ('review', 'qa', 'plan')                           # Inspect a copy; the answer carries forward.
FILES = ('tester',)                                       # Writes the run-level test suite, never sees code.
KINDS = EDIT + READ + FILES
CHECK = 'check'                                           # Deterministic, no model.
VERDICT = ('review', 'qa', CHECK)                         # Stages whose result selects [pass]/[fail] arrows.
SCORING = ('smoke', 'examples', 'suite')                  # Checkers usable after `by` and `guard`.
CHECKERS = SCORING + ('repro', 'diff')
SUITE_CHECKERS = ('suite', 'diff')                        # Need a tester to have written the suite.
PROMPTLESS = ('build', 'branch')                          # Use the upstream prompt, not a role request.
DONE = 'done'
NAME = r'[a-z][a-z0-9_]*'
ATTRIBUTE = r'x\d+|by|guard|prompt'


def vendor(model):
    return 'claude' if model.startswith('claude-') else 'codex'


class FactoryError(ValueError):
    pass


@dataclass(frozen=True)
class Stage:
    name: str
    kind: str
    model: str
    effort: str
    attempts: int = 1      # `xN`: independent attempts of an edit stage
    by: str = None         # checker that scores attempts
    guard: str = None      # checker that vetoes a stage that lowers the score
    prompt: str = None     # configs/factory-prompts/NAME.md instead of KIND.md
    checker: str = None    # for kind `check`
    arg: str = None

    @property
    def edits(self):
        return self.kind in EDIT

    @property
    def carries(self):
        """Edits whose result becomes the main code; a branch is kept aside."""
        return self.kind in EDIT and self.kind != 'branch'

    @property
    def verdicts(self):
        return self.kind in VERDICT

    @property
    def role_file(self):
        """Name of the role request in configs/factory-prompts, or None when the stage has none."""
        return None if self.kind == CHECK else self.prompt or ('build' if self.kind == 'branch' else self.kind)


@dataclass(frozen=True)
class Edge:
    src: str
    dst: str
    when: str = None   # 'pass' or 'fail': the source stage's verdict; None means always
    limit: int = None  # Most times this edge may be taken per checkpoint; None means unlimited
    reset: bool = False  # Restart the destination from the code the checkpoint began with, without feedback


@dataclass
class Factory:
    name: str
    stages: dict
    edges: list = field(default_factory=list)
    start: str = 'build'
    text: str = ''

    @property
    def sha256(self):
        return hashlib.sha256(self.text.encode()).hexdigest()

    def pick(self, stage, verdict, taken):
        """The first outgoing edge whose condition holds and whose limit is unspent, as (index, edge)."""
        for index, edge in enumerate(self.edges):
            if edge.src != stage or (edge.when and edge.when != verdict):
                continue
            if edge.limit is None or taken[index] < edge.limit:
                return index, edge
        return None  # Nothing eligible: this checkpoint's factory is finished.

    def worst(self, cost):
        """Largest total `cost(stage)` over every possible verdict sequence for one checkpoint."""
        seen = {}

        def walk(stage, taken):
            key = (stage, taken)
            if key not in seen:
                best = 0
                for verdict in (('pass', 'fail') if self.stages[stage].verdicts else (None,)):
                    found = self.pick(stage, verdict, taken)
                    if found and found[1].dst != DONE:
                        index, edge = found
                        best = max(best, walk(edge.dst, taken[:index] + (taken[index] + 1,) + taken[index + 1:]))
                seen[key] = cost(self.stages[stage]) + best
            return seen[key]

        return walk(self.start, (0,) * len(self.edges))

    def max_sessions(self):
        """Worst-case model sessions for one checkpoint: checks are free, `xN` counts N."""
        return self.worst(lambda s: 0 if s.kind == CHECK else s.attempts)

    def max_checks(self):
        """Worst-case deterministic check runs for one checkpoint, scoring runs included."""
        return self.worst(lambda s: 1 if s.kind == CHECK else (s.attempts if s.by and s.attempts > 1 else 0) + (2 if s.guard else 0))

    def to_dict(self):
        def stage(s):
            row = {'kind': s.kind, 'model': s.model, 'effort': s.effort}
            row.update({k: v for k, v in (('attempts', s.attempts if s.attempts > 1 else None), ('by', s.by), ('guard', s.guard),
                                          ('prompt', s.prompt), ('checker', s.checker), ('arg', s.arg)) if v})
            return row
        return {'name': self.name, 'sha256': self.sha256, 'start': self.start,
                'stages': {n: stage(s) for n, s in self.stages.items()},
                'edges': [{'from': e.src, 'to': e.dst, 'when': e.when, 'max': e.limit, **({'reset': True} if e.reset else {})}
                          for e in self.edges]}


def verdict_of(answer):
    """'pass' or 'fail' from a final `VERDICT: PASS|FAIL` line; anything else counts as a fail."""
    lines = [line.strip() for line in answer.strip().splitlines() if line.strip()]
    found = re.fullmatch(r'\W*VERDICT:\s*(PASS|FAIL)\W*', lines[-1], re.I) if lines else None
    return found[1].lower() if found else 'fail'


def parse(text, name='factory', base=BASE):
    stages, edges, order = {}, [], []
    for number, raw in enumerate(text.splitlines(), 1):
        line = raw.split('#', 1)[0].strip()
        if not line:
            continue

        def fail(message):
            raise FactoryError(f'{name}:{number}: {message}')

        if '->' in line:
            parts = re.split(r'\s*-(?:\[([^\]]*)\]-)?>\s*', line)
            nodes, options = parts[0::2], parts[1::2]
            for node in nodes:
                if not re.fullmatch(NAME, node):
                    fail(f'expected a stage name, got {node!r}')
            for src, dst, option in zip(nodes, nodes[1:], options):
                when = limit = None
                reset = False
                for item in (option or '').split(','):
                    item = item.strip()
                    if item in ('pass', 'fail') and when is None:
                        when = item
                    elif item == 'reset' and not reset:
                        reset = True
                    elif (m := re.fullmatch(r'max[ =](\d+)', item)) and limit is None and int(m[1]) > 0:
                        limit = int(m[1])
                    elif item:
                        fail(f'unknown arrow option {item!r}; use pass, fail, max N or reset')
                edges.append(Edge(src, dst, when, limit, reset))
            order += nodes
            continue
        found = re.fullmatch(rf'({NAME})\s*=\s*(.+)', line)
        if not found:
            fail('expected `stage = [kind] model[:effort]`, `stage = check CHECKER` or a flow like `a -> b`')
        stage, rest = found[1], found[2].split()
        if stage in stages or stage == DONE:
            fail(f'stage {stage!r} is defined twice' if stage != DONE else "'done' is reserved")
        if rest[0] == CHECK:
            if not 2 <= len(rest) <= 3 or not all(re.fullmatch(r'[\w\-]+', word) for word in rest[1:]):
                fail('expected `stage = check CHECKER [ARG]`')
            if rest[1] not in CHECKERS:
                fail(f'unknown checker {rest[1]!r}; use one of {", ".join(CHECKERS)}')
            if (rest[1] == 'diff') != (len(rest) == 3):
                fail('`check diff` takes exactly one argument (a branch stage name); other checkers take none')
            stages[stage] = Stage(stage, CHECK, '', '', checker=rest[1], arg=rest[2] if len(rest) == 3 else None)
            continue
        kind = stage
        if len(rest) > 1 and not re.fullmatch(ATTRIBUTE, rest[1]):
            kind, rest = rest[0], rest[1:]
        model = re.fullmatch(r'([\w.\-]+)(?::(\w+))?', rest[0])
        if not model:
            fail('expected `stage = [kind] model[:effort]`, `stage = check CHECKER` or a flow like `a -> b`')
        raw, effort = model[1], model[2] or DEFAULT_EFFORT
        model = MODELS.get(raw, raw)
        if kind not in KINDS:
            fail(f'unknown kind {kind!r}; use one of {", ".join(KINDS)}, check')
        if model not in MODELS.values():
            fail(f'unknown model {raw!r}; use one of {", ".join(MODELS)}')
        if effort not in EFFORTS[vendor(model)]:
            fail(f'{model} supports efforts: {", ".join(EFFORTS[vendor(model)])}')
        attrs, words = {}, rest[1:]
        while words:
            word = words.pop(0)
            if (m := re.fullmatch(r'x(\d+)', word)):
                key, value = 'attempts', int(m[1])
                if not 2 <= value <= 10:
                    fail('xN takes 2 to 10 attempts')
            elif word in ('by', 'guard', 'prompt') and words:
                key, value = word, words.pop(0)
                if word == 'prompt':
                    if not re.fullmatch(r'[a-z][a-z0-9_\-]*', value) or not (base / 'configs/factory-prompts' / f'{value}.md').is_file():
                        fail(f'unknown prompt {value!r}; expected configs/factory-prompts/NAME.md')
                elif value not in SCORING:
                    fail(f'{word} needs a scoring checker ({", ".join(SCORING)}), got {value!r}')
            else:
                fail(f'unexpected {word!r}; attributes are xN, by CHECKER, guard CHECKER, prompt NAME')
            if key in attrs:
                fail(f'{key} is given twice')
            attrs[key] = value
        if kind not in EDIT and set(attrs) & {'attempts', 'by', 'guard'}:
            fail('xN, by and guard apply to code-changing stages only')
        if kind == 'branch' and set(attrs) & {'attempts', 'by', 'guard'}:
            fail('a branch stage takes no xN, by or guard')
        if kind in PROMPTLESS and 'prompt' in attrs:
            fail(f'a {kind} stage uses the upstream prompt; prompt NAME is not allowed')
        if ('attempts' in attrs) != ('by' in attrs):
            fail('xN needs `by CHECKER` to pick the best attempt, and `by` needs xN')
        stages[stage] = Stage(stage, kind, model, effort, **attrs)
    if not edges and len(stages) == 1:
        order = list(stages)  # A lone stage needs no flow line.
    factory = Factory(name, stages, edges, order[0] if order else '', text)
    validate(factory, name)
    return factory


def validate(factory, name):
    stages, edges = factory.stages, factory.edges
    if factory.start not in stages:
        raise FactoryError(f'{name}: define at least one stage and a flow starting at it')
    if stages[factory.start].kind not in ('build', 'tester', 'plan'):
        raise FactoryError(f'{name}: the flow must start at a build stage (or a tester or plan ahead of it), not {factory.start!r}')
    for edge in edges:
        for end in (edge.src, edge.dst):
            if end not in stages and end != DONE:
                raise FactoryError(f'{name}: flow uses undefined stage {end!r}')
        if edge.src == DONE:
            raise FactoryError(f"{name}: nothing follows 'done'")
        if edge.when and not stages[edge.src].verdicts:
            raise FactoryError(f'{name}: [{edge.when}] needs a review, qa or check source; {edge.src!r} gives no verdict')
        if edge.dst != DONE and stages[edge.dst].kind == 'fix' and not stages[edge.src].verdicts:
            raise FactoryError(f'{name}: fix {edge.dst!r} needs a review or qa (or a check) before it; use revise for an unprompted pass')
        if edge.reset and (edge.dst == DONE or not stages[edge.dst].carries):
            raise FactoryError(f'{name}: [reset] must lead to a build, revise, refactor or fix stage, not {edge.dst!r}')
    # Ahead of the first code-changing stage there is no code: only tester and plan stages may run, and it must be a build.
    todo, seen, built = [factory.start], set(), False
    while todo:
        stage = todo.pop()
        if stage in seen or stage == DONE:
            continue
        seen.add(stage)
        kind = stages[stage].kind
        if kind == 'build':
            built = True
            continue
        if kind in EDIT:
            raise FactoryError(f'{name}: the first code-changing stage reached must be a build, not {stage!r}')
        if kind in VERDICT:
            raise FactoryError(f'{name}: {stage!r} runs before any code exists; put it after a build')
        todo += [e.dst for e in edges if e.src == stage]
    if not built:
        raise FactoryError(f'{name}: no build stage is reachable from {factory.start!r}')
    for stage in stages.values():
        used = [stage.checker, stage.by, stage.guard]
        if any(c in SUITE_CHECKERS for c in used) and not any(s.kind == 'tester' for s in stages.values()):
            raise FactoryError(f'{name}: {stage.name!r} uses the test suite, but no tester stage writes one')
        if stage.checker == 'diff' and (stage.arg not in stages or stages[stage.arg].kind != 'branch'):
            raise FactoryError(f'{name}: check diff {stage.arg} needs {stage.arg!r} to be a branch stage')
    reached, todo = set(), [factory.start]
    while todo:
        stage = todo.pop()
        if stage in reached or stage == DONE:
            continue
        reached.add(stage)
        todo += [e.dst for e in edges if e.src == stage]
    if reached != set(stages):
        raise FactoryError(f'{name}: unreachable stages: {", ".join(sorted(set(stages) - reached))}')
    # Every cycle needs a capped edge, so a factory always terminates.
    free, state = {}, {}
    for edge in edges:
        if edge.limit is None and edge.dst != DONE:
            free.setdefault(edge.src, []).append(edge.dst)

    def cyclic(stage):
        if state.get(stage) == 'open':
            return True
        if state.get(stage) == 'done':
            return False
        state[stage] = 'open'
        looped = any(cyclic(nxt) for nxt in free.get(stage, []))
        state[stage] = 'done'
        return looped

    if any(cyclic(stage) for stage in stages):
        raise FactoryError(f'{name}: a loop has no [max N] limit on any of its arrows')


def load(ref, base=BASE):
    """A factory by name (configs/factories/NAME.factory) or by file path."""
    path = Path(ref)
    if path.suffix != '.factory':
        if not re.fullmatch(r'[a-z0-9][a-z0-9-]*', ref):
            raise FactoryError(f'Factory names use lowercase letters, digits and hyphens: {ref!r}')
        path = base / 'configs/factories' / f'{ref}.factory'
    if not path.is_file():
        raise FactoryError(f'No such factory: {path}')
    return parse(path.read_text(), path.stem)
