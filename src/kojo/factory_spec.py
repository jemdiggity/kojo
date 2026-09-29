"""A small text language describing a factory: who does each stage and how stages flow.

    # luna builds, opus refactors, then opus reviews and luna fixes up to 5 times
    build    = luna6
    refactor = opus55:high
    review   = opus55:high
    fix      = luna6

    build -> refactor -> review
    review -[fail, max 5]-> fix -> review

Stages are `NAME = [KIND] MODEL[:EFFORT]`; KIND defaults to NAME. A flow line chains
stages with arrows, and an arrow may carry `[pass]`, `[fail]` and `[max N]` in any mix.
"""
from dataclasses import dataclass, field
import hashlib
from pathlib import Path
import re

BASE = Path(__file__).resolve().parents[2]

MODELS = {
    'sonnet55': 'claude-sonnet-5-5',
    'opus55': 'claude-opus-5-5',
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
EDIT = ('build', 'revise', 'refactor', 'fix')  # Change the code; the result carries forward.
READ = ('review', 'qa')                        # Inspect a copy; the answer and a verdict carry forward.
KINDS = EDIT + READ
DONE = 'done'
NAME = r'[a-z][a-z0-9_]*'


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

    @property
    def edits(self):
        return self.kind in EDIT


@dataclass(frozen=True)
class Edge:
    src: str
    dst: str
    when: str = None   # 'pass' or 'fail': the source stage's verdict; None means always
    limit: int = None  # Most times this edge may be taken per checkpoint; None means unlimited


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

    def max_sessions(self):
        """Worst-case sessions for one checkpoint, over every possible verdict sequence."""
        seen = {}

        def walk(stage, taken):
            key = (stage, taken)
            if key not in seen:
                best = 0
                for verdict in (('pass', 'fail') if self.stages[stage].kind in READ else (None,)):
                    found = self.pick(stage, verdict, taken)
                    if found and found[1].dst != DONE:
                        index, edge = found
                        best = max(best, walk(edge.dst, taken[:index] + (taken[index] + 1,) + taken[index + 1:]))
                seen[key] = 1 + best
            return seen[key]

        return walk(self.start, (0,) * len(self.edges))

    def to_dict(self):
        return {'name': self.name, 'sha256': self.sha256, 'start': self.start,
                'stages': {n: {'kind': s.kind, 'model': s.model, 'effort': s.effort} for n, s in self.stages.items()},
                'edges': [{'from': e.src, 'to': e.dst, 'when': e.when, 'max': e.limit} for e in self.edges]}


def verdict_of(answer):
    """'pass' or 'fail' from a final `VERDICT: PASS|FAIL` line; anything else counts as a fail."""
    lines = [line.strip() for line in answer.strip().splitlines() if line.strip()]
    found = re.fullmatch(r'\W*VERDICT:\s*(PASS|FAIL)\W*', lines[-1], re.I) if lines else None
    return found[1].lower() if found else 'fail'


def parse(text, name='factory'):
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
                for item in (option or '').split(','):
                    item = item.strip()
                    if item in ('pass', 'fail') and when is None:
                        when = item
                    elif (m := re.fullmatch(r'max[ =](\d+)', item)) and limit is None and int(m[1]) > 0:
                        limit = int(m[1])
                    elif item:
                        fail(f'unknown arrow option {item!r}; use pass, fail or max N')
                edges.append(Edge(src, dst, when, limit))
            order += nodes
            continue
        found = re.fullmatch(rf'({NAME})\s*=\s*(?:(\w+)\s+)?([\w.\-]+)(?::(\w+))?', line)
        if not found:
            fail('expected `stage = [kind] model[:effort]` or a flow like `a -> b`')
        stage, kind, model, effort = found[1], found[2] or found[1], found[3], found[4] or DEFAULT_EFFORT
        model = MODELS.get(model, model)
        if stage in stages or stage == DONE:
            fail(f'stage {stage!r} is defined twice' if stage != DONE else "'done' is reserved")
        if kind not in KINDS:
            fail(f'unknown kind {kind!r}; use one of {", ".join(KINDS)}')
        if model not in MODELS.values():
            fail(f'unknown model {found[3]!r}; use one of {", ".join(MODELS)}')
        if effort not in EFFORTS[vendor(model)]:
            fail(f'{model} supports efforts: {", ".join(EFFORTS[vendor(model)])}')
        stages[stage] = Stage(stage, kind, model, effort)
    if not edges and len(stages) == 1:
        order = list(stages)  # A lone stage needs no flow line.
    factory = Factory(name, stages, edges, order[0] if order else '', text)
    validate(factory, name)
    return factory


def validate(factory, name):
    stages, edges = factory.stages, factory.edges
    if factory.start not in stages:
        raise FactoryError(f'{name}: define at least one stage and a flow starting at it')
    if stages[factory.start].kind != 'build':
        raise FactoryError(f'{name}: the flow must start at a build stage, not {factory.start!r}')
    for edge in edges:
        for end in (edge.src, edge.dst):
            if end not in stages and end != DONE:
                raise FactoryError(f'{name}: flow uses undefined stage {end!r}')
        if edge.src == DONE:
            raise FactoryError(f"{name}: nothing follows 'done'")
        if edge.when and stages[edge.src].kind not in READ:
            raise FactoryError(f'{name}: [{edge.when}] needs a review or qa source; {edge.src!r} gives no verdict')
        if edge.dst != DONE and stages[edge.dst].kind == 'fix' and stages[edge.src].kind not in READ:
            raise FactoryError(f'{name}: fix {edge.dst!r} needs a review or qa before it; use revise for an unprompted pass')
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
