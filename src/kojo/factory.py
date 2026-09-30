"""Bounded checkpoint factories with one independent review/follow-up per checkpoint."""
import argparse
from pathlib import Path

import collections
import fcntl
import hashlib
import math
import re
import shutil
import time

from kojo.catalog import BASE, DATA_ROOT, protocol_digest, harness_digest, factory_instruction_hashes, metadata
from kojo.execution import audit, run_session, save, session_paths
from kojo.external_access import audit_external_sources
from kojo.gauntlet import Experiment, copy_code, hashes, preflight, read, split_counts, pass_diff, sync_workspace
from kojo.run_chain import ChainBackend, compose_prompt
from kojo import checks, claude_execution, factory_spec
from kojo.quality import analyze_snapshot, headline


def adapter(model):
    if model in claude_execution.MODELS:
        return claude_execution.audit, claude_execution.run_session
    return audit, run_session


def instructions(backend, role, prompt=None):
    # User-level role requests only; the model's stock base prompt stays intact.
    if role not in factory_spec.KINDS:
        raise ValueError('Unknown factory role: ' + role)
    name = prompt or ('build' if role == 'branch' else role)
    if not re.fullmatch(r'[a-z][a-z0-9_\-]*', name):
        raise ValueError('Bad role prompt name: ' + name)
    return (BASE/'configs/factory-prompts'/f'{name}.md').read_text().strip()


VERDICT_REQUEST = ('\n\n# Verdict\nEnd your final response with exactly one line: `VERDICT: PASS` if the code needs '
                   'no further changes, or `VERDICT: FAIL` if it does.')


def label(checkpoint, visit=1, variant=None):
    """Directory name of one session: later visits to a stage get `-N`, and xN attempts `-attemptK`."""
    return f'checkpoint_{checkpoint}' + (f'-{visit}' if visit > 1 else '') + (f'-attempt{variant}' if variant else '')


def stage_prompt(experiment, role, checkpoint=5, feedback=None, problem="code_search", verdict=False, notes=None, prompt=None, origin=None):
    from kojo.scb_prompt import render_checkpoint
    if role in ('build', 'branch'):
        text = render_checkpoint(experiment.spec(problem,checkpoint),checkpoint,experiment.b.python, **({'entry_file':experiment.manifest['problems'][problem]['entry_file']} if problem != 'code_search' else {}))
        if role == 'branch':
            return text  # An independent build from the checkpoint's start: the stock prompt, nothing else.
        if notes:
            text += '\n\n# Planning notes for this checkpoint\n' + notes
        # Only a loop re-entry carries feedback; a first build is exactly the stock prompt.
        heading = '# Deterministic check results' if origin == 'check' else '# Feedback from the previous review stage'
        return text + '\n\n' + heading + '\n' + feedback if feedback else text
    # Review/fix are explicitly experimental roles, not native SCB checkpoints.
    # Only public specs through this checkpoint; future specs never reach these roles.
    specs = instructions(None,role,prompt) + "\n\n" + "\n\n".join(
        f"# Public checkpoint {n} specification\n"+experiment.spec(problem,n) for n in range(1,checkpoint+1))
    if role == 'fix' and not (feedback and feedback.strip()):
        raise ValueError('A completed review is required before follow-up')
    if feedback and role in factory_spec.EDIT:
        specs += ('\n\n# Deterministic check results\n' if origin == 'check' else '\n\n# Feedback from the independent reviewer\n') + feedback
    return specs + VERDICT_REQUEST if verdict and role in ('review', 'qa') else specs


def quality_note(score):
    quality = score.get('quality')
    if not quality:
        return ''
    if 'error' in quality:
        return f"; quality unavailable ({quality['error']})"
    return f"; erosion {quality['erosion']:.3f}, verbosity {quality['verbosity']:.3f}" if quality['erosion'] is not None else '; quality: no Python found'


def run_flow(flow, session, checkpoint, source, trace=None, check=None, sync=None):
    """Walk one checkpoint through a factory's stages; return the code that carries forward.

    `session(stage, n, source, feedback, visit, **extra)` runs a model stage and returns its run dir;
    `check(stage, n, code, feedback, visit, ctx)` runs a deterministic check and returns a CheckResult;
    `sync(code)` makes the shared builder workspace equal `code`. Extra session arguments are given only
    when they apply: notes (plan text for a build), variant (xN attempt number), origin ('check').
    """
    stage, code, feedback, origin, notes = flow.start, source, None, None, None
    held = source  # What the shared builder workspace holds.
    reset, side = False, {}
    visits = collections.Counter()
    taken = [0] * len(flow.edges)

    def measure(spec, target, visit, text, role, phase, variant=None):
        if check is None:
            raise RuntimeError('This factory has check stages; no checker was provided')
        return check(spec, checkpoint, target, text, visit, {'prior_code': source, 'side_codes': dict(side), 'role': role, 'phase': phase, 'variant': variant})

    def score_of(name, target, visit, role, phase, variant=None):
        return measure(factory_spec.Stage(role, factory_spec.CHECK, '', '', checker=name), target, visit, None, role, phase, variant)

    while True:
        visits[stage] += 1
        visit, spec = visits[stage], flow.stages[stage]
        verdict, extra = None, {}
        if spec.kind == factory_spec.CHECK:
            found = measure(spec, code, visit, feedback, stage, 'gate')
            verdict, feedback, origin = found.verdict, found.log, 'check'
            extra = {'kind': 'check', 'checker': spec.checker, 'score': found.score, 'passed': found.passed, 'total': found.total}
        elif spec.kind == 'tester':
            session(stage, checkpoint, None, None, visit)  # A tester never sees code, and its answer is not forwarded.
            extra = {'kind': 'tester'}
        elif spec.kind == 'plan':
            answer = session(stage, checkpoint, code, feedback, visit)/'answer.txt'
            notes = answer.read_text() if answer.exists() else ''
            extra = {'kind': 'plan'}
        elif spec.kind == 'branch':
            side[stage] = session(stage, checkpoint, source, None, visit)/'submission'  # Built from the checkpoint's start.
            extra = {'kind': 'branch'}
        elif spec.edits:
            if reset:
                code, feedback, origin = source, None, None
            options = {}
            if notes and spec.kind == 'build':
                options['notes'] = notes
            if feedback and origin == 'check':
                options['origin'] = 'check'
            if spec.attempts > 1:
                runs = [session(stage, checkpoint, code, feedback, visit, variant=k, **options) for k in range(1, spec.attempts + 1)]
                scores = [score_of(spec.by, run/'submission', visit, stage, 'score', k) for k, run in enumerate(runs, 1)]
                winner = max(range(len(runs)), key=lambda i: (scores[i].score, -i))  # Ties go to the earliest attempt.
                new = runs[winner]/'submission'
                extra = {'attempts': [{'variant': k, 'score': f.score, 'passed': f.passed, 'total': f.total} for k, f in enumerate(scores, 1)],
                         'winner': winner + 1}
            else:
                if sync and held != code:
                    sync(code)
                new = held = session(stage, checkpoint, code, feedback, visit, **options)/'submission'
            if spec.guard:
                before = score_of(spec.guard, code, visit, stage, 'guard-before') if code is not None else None
                after = score_of(spec.guard, new, visit, stage, 'guard-after')
                rolled = before is not None and after.score < before.score
                extra['guard'] = {'checker': spec.guard, 'before': before.score if before else None, 'after': after.score, 'rolled_back': rolled}
                if rolled:
                    new = code
            code, feedback, origin = new, None, None
        else:
            answer = session(stage, checkpoint, code, feedback, visit)/'answer.txt'
            feedback = answer.read_text() if answer.exists() else ''
            verdict, origin = factory_spec.verdict_of(feedback), spec.kind
        picked = flow.pick(stage, verdict, taken)
        if trace is not None:
            trace.append({'checkpoint':checkpoint,'stage':stage,'attempt':visit,'verdict':verdict,
                          'next':picked[1].dst if picked else factory_spec.DONE, **extra,
                          **({'reset': True} if picked and picked[1].reset else {})})
        if picked is None or picked[1].dst == factory_spec.DONE:
            break
        taken[picked[0]] += 1
        stage, reset = picked[1].dst, picked[1].reset
    if sync and held != code:
        sync(code)  # The next checkpoint's builder starts from what carries forward.
    return code


def review_and_fix(session, checkpoint, source):
    """One review/fix loop for this checkpoint; never inspect official grades."""
    review = session('review', checkpoint, source)
    if read(review/'run.json')['status'] != 'complete':
        raise RuntimeError('Reviewer did not complete; refusing partial review follow-up')
    return session('fix', checkpoint, source, (review/'answer.txt').read_text())/'submission'


def run_checkpoint(session, checkpoint, source, *, review=True):
    """Carry this checkpoint's final factory output into the next build."""
    built = session('build', checkpoint, source)/'submission'
    return review_and_fix(session, checkpoint, built) if review else built


def parse_args(argv=None):
    """Validate a run before a batch starts any inference."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['audit', 'run'])
    parser.add_argument('--run-id', required=True)
    parser.add_argument('--problem', choices=['code_search','circuit_eval','database_migration','dynamic_config_service_api'], default='code_search')
    model_choices=['gpt-6-luna','gpt-6-astra','gpt-5.6-sol','gpt-6-sol','gpt-6.1-sol',*claude_execution.MODELS]
    parser.add_argument('--factory', help='Factory description (configs/factories/NAME.factory or a .factory path); replaces the model, effort and review options')
    parser.add_argument('--build-model', choices=model_choices)
    parser.add_argument('--review-model', choices=model_choices)
    parser.add_argument('--claude-effort', choices=claude_execution.EFFORTS, help='Explicit Claude effort (default: low)')
    parser.add_argument('--codex-effort', choices=['low','medium','high','xhigh','max'], help='Explicit Codex effort (default: low)')
    parser.add_argument('--claude-max-budget-usd', type=float, help='Optional per-session Claude CLI budget; omitted means report usage only')
    parser.add_argument('--claude-max-output-tokens', type=int, help='Optional response-token allowance, verified against the emitted request')
    parser.add_argument('--no-review', action='store_true')
    parser.add_argument('--no-quality', action='store_true', help='Skip the static quality analysis of each stage output (needs uvx and network)')
    parser.add_argument('--no-network', action='store_true', help='Historical restricted-network diagnostic; default permits network access')
    parser.add_argument('--review-scope', choices=['checkpoint','final'], help='One review/fix loop per checkpoint (default); final preserves historical runs')
    parser.add_argument('--seconds-per-session', type=int, default=600, help='Time limit for each builder, reviewer, and fixer session (default: 600)')
    parser.add_argument('--source-run', help='Reuse only this run’s frozen final builder source for a paired review')
    parser.add_argument('--resume-run', help='Explicit baseline restart from a completed checkpoint in this run')
    parser.add_argument('--resume-checkpoint', type=int)
    parser.add_argument('--monitor-only', action='store_true', help='Explicit user-authorized waiver of the weekly floor for this bounded run')
    parser.add_argument('--skill-set', type=Path)
    parser.add_argument('--skill-set-sha256')
    parser.add_argument('--base-instructions', type=Path, help='Replace the Codex base instructions with this file\'s text (a deliberate departure from stock protocol; Codex models only)')
    args = parser.parse_args(argv)
    args.base_text = None
    if args.base_instructions:
        try:
            args.base_text = args.base_instructions.read_text()
        except OSError as error:
            parser.error(f'Cannot read --base-instructions: {error}')
        if not args.base_text.strip():
            parser.error('--base-instructions file is empty')
    if args.factory:
        used = [flag for flag, value in [('--build-model', args.build_model), ('--review-model', args.review_model), ('--claude-effort', args.claude_effort),
                ('--codex-effort', args.codex_effort), ('--no-review', args.no_review), ('--review-scope', args.review_scope),
                ('--source-run', args.source_run), ('--resume-run', args.resume_run), ('--resume-checkpoint', args.resume_checkpoint)] if value]
        if used:
            parser.error('--factory defines models, efforts and review flow; remove ' + ', '.join(used))
        try:
            args.flow = factory_spec.load(args.factory)
        except factory_spec.FactoryError as error:
            parser.error(str(error))
    args.build_model = args.build_model or 'gpt-6-luna'
    args.review_model = args.review_model or 'gpt-6-luna'
    args.claude_effort = args.claude_effort or 'low'
    args.codex_effort = args.codex_effort or 'low'
    args.review_scope = args.review_scope or 'checkpoint'
    from kojo.skill_sets import describe
    try:
        args.skill_manifest = describe(args.skill_set) if args.skill_set else None
    except ValueError as error:
        parser.error(str(error))
    if args.skill_set_sha256 and (not args.skill_manifest or args.skill_manifest['sha256'] != args.skill_set_sha256):
        parser.error('Skill-set contents differ from frozen plan')
    count=len(metadata(args.problem)['checkpoints'])
    if args.resume_checkpoint is not None and not 1 <= args.resume_checkpoint < count:
        parser.error('Resume checkpoint must precede the final checkpoint')
    if (args.resume_checkpoint is not None and not args.resume_run) or (args.resume_run and (not args.no_review or args.source_run)):
        parser.error('Checkpoint restart requires --resume-run, --no-review, and no --source-run; checkpoint defaults to last completed')
    if args.resume_run and any(c not in 'abcdefghijklmnopqrstuvwxyz0123456789-' for c in args.resume_run):
        parser.error('Invalid resume run ID')
    if args.seconds_per_session <= 0:
        parser.error('seconds-per-session must be positive')
    if args.source_run and (args.no_review or any(c not in 'abcdefghijklmnopqrstuvwxyz0123456789-' for c in args.source_run)):
        parser.error('source-run needs a review and a valid run ID')
    if args.source_run and args.review_scope != 'final':
        parser.error('source-run reuses final code only and requires --review-scope final')
    if args.factory:
        models={name:stage.model for name,stage in args.flow.stages.items() if stage.kind != factory_spec.CHECK}
        adapter_options={name:{'effort':stage.effort} for name,stage in args.flow.stages.items() if stage.kind != factory_spec.CHECK}
        args.roles=tuple(models)
    else:
        models={'build':args.build_model,'review':args.review_model,'fix':args.build_model}
        adapter_options={role:({'effort':args.claude_effort} if model in claude_execution.MODELS else {'effort':args.codex_effort}) for role,model in models.items()}
        args.roles=('build',) if args.no_review else ('build','review','fix')
        args.flow=factory_spec.Factory('review-fix',{role:factory_spec.Stage(role,role,models[role],adapter_options[role]['effort']) for role in models})
    if args.claude_max_output_tokens is not None:
        if args.claude_max_output_tokens<=0:parser.error('Output-token allowance must be positive')
        for role,options in adapter_options.items():
            if models[role] in claude_execution.MODELS:options['max_output_tokens']=args.claude_max_output_tokens
    if args.claude_max_budget_usd is not None:
        if not math.isfinite(args.claude_max_budget_usd) or args.claude_max_budget_usd<=0:
            parser.error('Claude budget must be finite and positive')
        for role,options in adapter_options.items():
            if models[role] in claude_execution.MODELS:options['max_budget_usd']=args.claude_max_budget_usd
    if not args.run_id or any(c not in 'abcdefghijklmnopqrstuvwxyz0123456789-' for c in args.run_id):
        parser.error('Use lowercase letters, digits and hyphens')
    return args, models, adapter_options


def last_completed_checkpoint(output, model, effort, count):
    """Find a contiguous prefix of verified, frozen completed builds."""
    last = 0
    for n in range(1, count + 1):
        checkpoint = output / 'build' / f'checkpoint_{n}'
        receipt = checkpoint / 'run.json'
        if not receipt.exists() or read(receipt).get('status') != 'complete':
            break
        row = read(receipt)
        if row.get('model') != model or row.get('reasoning') != effort:
            raise RuntimeError('Resume model/effort mismatch')
        if row.get('transcript_error') or not (checkpoint/'transcript-verification.json').exists():
            raise RuntimeError('Resume transcript verification missing or failed')
        if not (checkpoint/'submission').is_dir() or hashes(checkpoint/'submission') != read(checkpoint/'snapshot.json'):
            raise RuntimeError('Resume snapshot mismatch')
        last = n
    return last


def main(argv=None):
    args, models, adapter_options = parse_args(argv)
    active_models=[models[role] for role in args.roles]
    if args.base_text is not None and any(m in claude_execution.MODELS for m in active_models):
        raise SystemExit('--base-instructions applies to Codex models only; this factory uses a Claude model')
    base_for = lambda model: None if model in claude_execution.MODELS else args.base_text
    cfg, manifest = preflight(check_codex=False) if all(m in claude_execution.MODELS for m in active_models) else preflight()
    manifest['problems'][args.problem]=metadata(args.problem)
    checkpoint_count=len(manifest['problems'][args.problem]['checkpoints'])
    if args.resume_run:
        old_output = DATA_ROOT/'results/runs'/args.resume_run
        old_manifest = read(old_output/'manifest.json')
        if old_manifest.get('skills') != args.skill_manifest:
            raise RuntimeError('Resume skill set differs')
        if old_manifest['problem'] != args.problem:
            raise RuntimeError('Resume problem mismatch')
        if old_manifest.get('network_enabled') != (not args.no_network) or old_manifest.get('claude_max_output_tokens_override') != args.claude_max_output_tokens or old_manifest.get('review_loops') != 0:
            raise RuntimeError('Resume protocol settings differ')
        detected = last_completed_checkpoint(old_output, args.build_model, adapter_options['build']['effort'], checkpoint_count)
        if args.resume_checkpoint is None:
            args.resume_checkpoint = detected
        if not 0 < args.resume_checkpoint <= detected or args.resume_checkpoint >= checkpoint_count:
            raise RuntimeError('No unfinished trajectory with a verified completed restart checkpoint')
        print(f'Resuming {args.resume_run} after checkpoint {args.resume_checkpoint}', flush=True)
    root = DATA_ROOT/'intermediate/runs' / args.run_id
    data = root / 'gauntlet'
    output = DATA_ROOT/'results/runs' / args.run_id
    backend = ChainBackend(cfg, manifest, data, output)
    backend.install_dependencies=not args.no_network
    experiment = Experiment(backend)
    if args.action == 'audit':
        for role in args.roles:
            stage = args.flow.stages[role]
            kind = stage.kind
            first = kind in ('build', 'branch')
            probe = root / 'offline-audit' / role
            adapter(models[role])[0](probe, base_for(models[role]), backend.runtime, None, True,
                  stage_prompt(experiment, kind, 1 if first else checkpoint_count, None if first else 'Offline review placeholder.', problem=args.problem, verdict=bool(args.factory), **({'prompt':stage.prompt} if stage.prompt else {})), persist=True, model=models[role], network_enabled=not args.no_network, native_skill_set=args.skill_set, **adapter_options[role])
        print('Selected role requests and native isolation verified without inference.', flush=True)
        return
    data.mkdir(parents=True, exist_ok=True)
    with (data / 'execution.lock').open('w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if output.exists() or (data / 'ledger.json').exists():
            raise RuntimeError('Run ID already used; no implicit resume or retry')
        output.mkdir(parents=True)
        record = {
            'run_id':args.run_id, 'problem':args.problem, 'problem_metadata':manifest['problems'][args.problem], 'condition':'checkpoint-review-factory' if args.review_scope == 'checkpoint' else 'single-review-factory',
            'pins':cfg, 'protocol_sha256':backend.protocol, 'harness_sha256':harness_digest(), 'role_instruction_sha256':factory_instruction_hashes(), 'quota':read(BASE / 'configs/quota.json'),
            'max_sessions':(0 if args.source_run else checkpoint_count)+(0 if args.no_review else (2*checkpoint_count if args.review_scope == 'checkpoint' else 2)), 'seconds_per_session':args.seconds_per_session, 'review_loops':0 if args.no_review else (checkpoint_count if args.review_scope == 'checkpoint' else 1), 'review_scope':args.review_scope, 'review_loops_per_checkpoint':0 if args.no_review else (1 if args.review_scope == 'checkpoint' else None), 'skills':args.skill_manifest,
            'prompt_protocol':'stock-cli-scb-just-solve-v1','builder_specs':'current checkpoint only','base_instructions':('stock provider CLI; no override' if args.base_text is None else 'CUSTOM override for Codex roles: '+str(args.base_instructions)), 'base_instructions_sha256':(None if args.base_text is None else hashlib.sha256(args.base_text.encode()).hexdigest()),'checkpoint_workspace':'persistent directory including virtualenv; fresh CLI conversation','review_specs':'public specs through current checkpoint; custom review intervention','models':models,'reasoning':('per role; see effort_by_role' if any(adapter_options.values()) else 'low'),'source_run':args.source_run,'quota_monitor_only':args.monitor_only,'network_enabled':not args.no_network,'dependency_policy':'requirements.txt rebuilt in a fresh grading venv; install report and freeze recorded' if not args.no_network else 'historical pinned runtime only','external_access_policy':'report-only native transcript audit after every session; validity judged by the user',
            'sequence':('reused frozen builder' if args.source_run else f'{checkpoint_count} incremental build checkpoints') + ('' if args.no_review else (', each followed by one review and one fix; fixed code carries forward' if args.review_scope == 'checkpoint' else ', one final review, one follow-up')),
            'grading':'All calls finish or stop before grading; reviewer and fixer never receive official results.',
            'provider_by_role':{role:'claude' if model in claude_execution.MODELS else 'codex' for role,model in models.items()},
            'effort_by_role':{role:adapter_options[role].get('effort','low') for role in models},
            'claude_cli_version':claude_execution.VERSION if any(m in claude_execution.MODELS for m in models.values()) else None,
            'claude_max_budget_usd_per_session':args.claude_max_budget_usd,
            'claude_max_output_tokens_override':args.claude_max_output_tokens,
            'resumed_from':{'run_id':args.resume_run,'checkpoint':args.resume_checkpoint} if args.resume_run else None,
            'timeout_policy':'Stop the chain; incomplete source never carries forward',
            'scope':'Exploratory same-task workflow test, not held-out learning or a compute-matched comparison.',
        }
        if args.factory:
            record.update({'condition':'custom-factory','factory':args.flow.to_dict(),
                'role_instruction_sha256':factory_instruction_hashes(sorted({stage.role_file for stage in args.flow.stages.values() if stage.role_file})),
                'max_sessions':args.flow.max_sessions()*checkpoint_count,'max_checks':args.flow.max_checks()*checkpoint_count,'review_loops':None,'review_loops_per_checkpoint':None,
                'sequence':f'{checkpoint_count} incremental checkpoints, each run through factory {args.flow.name}; review and qa verdicts steer loops, each arrow limit applies per checkpoint',
                'grading':'All calls finish or stop before grading; no stage receives official results.'})
            (output/'factory.txt').write_text(args.flow.text)
        save(output / 'manifest.json', record)
        if args.skill_set:
            shutil.copytree(args.skill_set, output/'skill-set')
        ledger=[]; frozen=[]; trace=[]; previous=None; failure=None
        first_checkpoint=1
        if args.resume_run:
            old_output=DATA_ROOT/'results/runs'/args.resume_run
            if read(old_output/'manifest.json')['problem'] != args.problem:
                raise RuntimeError('Resume problem mismatch')
            old_data=DATA_ROOT/'intermediate/runs'/args.resume_run/'gauntlet'
            for n in range(1,args.resume_checkpoint+1):
                old=old_output/'build'/f'checkpoint_{n}'
                row=read(old/'run.json')
                if row['status']!='complete' or row['model']!=args.build_model or row['reasoning']!=adapter_options['build']['effort']:
                    raise RuntimeError('Restart source is not a completed matching-model checkpoint')
                if hashes(old/'submission')!=read(old/'snapshot.json'):
                    raise RuntimeError('Restart source snapshot mismatch')
                run=data/f'training-build/{args.problem}'/f'checkpoint_{n}'
                shutil.copytree(old_data/f'training-build/{args.problem}'/f'checkpoint_{n}',run)
                shutil.copytree(old,output/'build'/f'checkpoint_{n}')
                frozen.append({'name':args.problem,'checkpoint':n,'run':run,'role':'build'})
            previous=output/'build'/f'checkpoint_{args.resume_checkpoint}'/'submission'
            work=data/'builder-workspace/src'
            copy_code(previous,work)
            # No previous environment snapshot exists: restore dependencies from
            # the successful checkpoint's requirements, not the failed workspace.
            import subprocess
            subprocess.run([str(backend.python),'-m','venv',str(work/'venv')],check=True)
            requirements=work/'requirements.txt'
            if requirements.exists() and any(line.strip() and not line.lstrip().startswith('#') for line in requirements.read_text().splitlines()):
                subprocess.run([str(work/'venv/bin/python'),'-m','pip','install','--disable-pip-version-check','-r',str(requirements)],check=True,cwd=work)
            save(output/'restart.json',{'run_id':args.resume_run,'checkpoint':args.resume_checkpoint,
                'environment':'Rebuilt venv from successful requirements.txt; failed workspace not reused',
                'reused_checkpoints':list(range(1,args.resume_checkpoint+1))})
            first_checkpoint=args.resume_checkpoint+1

        suite_dir = data/'suite'

        def session(role, n, source, feedback=None, attempt=1, *, notes=None, variant=None, origin=None):
            stage = args.flow.stages[role]
            kind, edits = stage.kind, stage.edits
            name = label(n, attempt, variant)  # Later visits in a loop, and xN attempts, get their own directory.
            from kojo.skill_sets import describe
            if args.skill_set and describe(args.skill_set)['sha256'] != args.skill_manifest['sha256']:
                raise RuntimeError('Skill set changed during experiment')
            if protocol_digest() != backend.protocol:
                raise RuntimeError('Protocol changed during run')
            run = data / f'training-{role}/{args.problem}/{name}'
            dest = output / role / name
            # Native SCB keeps one workspace/environment across checkpoints.
            # The process/conversation is fresh; its filesystem is not reset.
            shared_work = stage.carries and variant is None and (kind != 'fix' or args.review_scope == 'checkpoint')
            work = data/'builder-workspace/src' if shared_work else run/'src'
            if shared_work:
                work.mkdir(parents=True,exist_ok=True)
                if source is None and hashes(work, exclude_generated=True):
                    raise RuntimeError('First builder workspace must be empty')
                if source is not None and hashes(work, exclude_generated=True) != hashes(source):
                    raise RuntimeError('Shared workspace does not match the preceding frozen source')
            elif kind == 'tester':
                work.mkdir(parents=True)  # Only the suite so far: a tester never sees builder code.
                checks.copy_suite(suite_dir, work/'suite')
            else:
                copy_code(source,work)
            dest.mkdir(parents=True)
            save(dest / 'initial-src.json', hashes(work) if kind == 'tester' else hashes(source) if source else {})
            options = {key:value for key,value in (('notes',notes),('prompt',stage.prompt),('origin',origin)) if value}
            prompt = stage_prompt(experiment, kind, n, feedback, problem=args.problem, verdict=bool(args.factory), **options)
            (dest / 'prompt.md').write_text(prompt)
            (dest / 'instructions.md').write_text(instructions(backend, kind, stage.prompt))
            ledger.append({'role':role, 'kind':kind, 'checkpoint':n, 'attempt':attempt, **({'variant':variant} if variant else {}), 'reserved_at':time.time()})
            save(data / 'ledger.json', ledger)
            prior=[sample for p in session_paths(data) if (p.parent/'quota.json').exists() for sample in read(p.parent/'quota.json')]
            print(f'Starting {role} checkpoint {n}' + (f' (visit {attempt})' if attempt > 1 else '') + (f' (attempt {variant})' if variant else ''), flush=True)
            adapter(models[role])[1](run, base_for(models[role]), prompt, args.seconds_per_session, backend.runtime,
                        None, prior, isolated_src=True, model=models[role], monitor_only=args.monitor_only, work_path=work, network_enabled=not args.no_network, native_skill_set=args.skill_set, **adapter_options[role])
            for filename in ['run.json','quota.json','verification.json','transcript-verification.json','answer.txt','stock-instructions.md']:
                if filename == 'answer.txt' and not (run/filename).exists():
                    continue  # A timed-out session may have no final answer; preserve its code/receipts.
                if filename == 'stock-instructions.md' and not (run/filename).exists():
                    continue  # Only stock-base sessions record the model's own base text.
                shutil.copy2(run/filename, dest/filename)
            if args.base_text is not None and models[role] not in claude_execution.MODELS:
                (dest/'base-instructions.md').write_text(args.base_text)  # the override this session actually ran with
            from kojo.skill_sets import install
            install(work, args.skill_set, 'claude' if models[role] in claude_execution.MODELS else 'codex')
            state=read(run/'run.json')
            if state['status']!='complete':
                print(f"Stopped {role} checkpoint {n}: {state['status']}; usage={state.get('usage')}; API-equivalent USD={state.get('api_price_equivalent_usd')}",flush=True)
                copy_code(work,run/'interrupted-source')
                raise RuntimeError('Incomplete checkpoint; chain stopped without carrying its source forward')
            if edits:
                copy_code(work,run/'submission')
                shutil.copytree(run/'submission',dest/'submission')
                save(dest/'snapshot.json',hashes(run/'submission'))
                frozen.append({'name':args.problem,'checkpoint':n,'run':run,'role':role,'label':name})
            elif kind == 'tester':
                copy = checks.copy_suite(work/'suite', suite_dir)  # The suite accumulates across checkpoints.
                checks.copy_suite(suite_dir, dest/'suite')
                print(f'Suite now has {copy} files', flush=True)
            else:
                save(dest/'source-changes.json',{'before':hashes(source) if source else {},'after':hashes(work, exclude_generated=True),
                                               'carry_forward':'Only answer.txt; no reviewer workspace changes.'})
            try:
                external=audit_external_sources(run/'transcript.jsonl')
            except Exception as error:
                external={'status':'audit_error','review_suggested':True,'events':[],
                          'error_type':type(error).__name__,
                          'limitations':['External-source audit failed; inspect the raw transcript.']}
            save(run/'external-access.json',external)
            save(dest/'external-access.json',external)
            print(f'Finished {role} checkpoint {n}', flush=True)
            amount=read(run/'run.json').get('api_price_equivalent_usd')
            usage=read(run/'run.json').get('usage')
            print(f'Usage checkpoint {n}: {usage}; API-equivalent USD: {amount}', flush=True)
            if models[role] in claude_execution.MODELS and args.claude_max_budget_usd is not None and (amount is None or amount>args.claude_max_budget_usd):
                raise RuntimeError('Claude cost unknown or session budget exceeded; stopping before another call')
            return run

        def sync(code):
            sync_workspace(data/'builder-workspace/src', code)

        def check(spec, n, code, feedback, visit, ctx):
            """One deterministic check on frozen code; receipts land beside the stage's own session directories."""
            entry = manifest['problems'][args.problem]['entry_file']
            context = checks.Context(code_dir=code, entry_file=entry, python=backend.python, prior_code=ctx['prior_code'], side_codes=ctx['side_codes'],
                                     suite_dir=suite_dir if suite_dir.is_dir() else None, specs={k:experiment.spec(args.problem,k) for k in range(1,n+1)},
                                     checkpoint=n, feedback=feedback, arg=spec.arg)
            found = checks.run_check(spec.checker, context)
            phase = ctx['phase']
            folder = output/ctx['role']/label(n, visit, ctx['variant'] if phase == 'score' else None)/('' if phase == 'gate' else phase)
            folder.mkdir(parents=True, exist_ok=True)
            save(folder/'result.json', {**found.to_dict(), 'checker':spec.checker, 'arg':spec.arg, 'checkpoint':n})
            (folder/'log.txt').write_text(found.log)
            print(f"Check {spec.checker} ({ctx['role']}{'' if phase == 'gate' else ' ' + phase}) checkpoint {n}: {found.verdict} {found.passed}/{found.total}", flush=True)
            return found

        try:
            if args.source_run:
                original=DATA_ROOT/'results/runs'/args.source_run/f'build/checkpoint_{checkpoint_count}'
                if hashes(original/'submission') != read(original/'snapshot.json'):
                    raise RuntimeError('Reused builder snapshot mismatch')
                previous=original/'submission'
                save(output/'reused-builder.json',{'run_id':args.source_run,'files':hashes(previous)})
            else:
                for n in range(first_checkpoint,checkpoint_count+1):
                    if args.factory:
                        previous=run_flow(args.flow,session,n,previous,trace,check,sync)
                    else:
                        previous=run_checkpoint(session,n,previous,review=not args.no_review and args.review_scope == 'checkpoint')
            if not args.no_review and args.review_scope == 'final':
                previous=review_and_fix(session,checkpoint_count,previous)
        except BaseException as error:
            failure=error
            save(output/'STOPPED.json',{'reason':str(error),'time':time.time()})
        finally:
            if args.factory:
                save(output/'flow-trace.json',trace)
            sessions=[read(p) for p in session_paths(data)]
            save(output/'accounting.json',{'sessions':sessions,'sessions_reserved':len(ledger),
                'elapsed_seconds':sum(r.get('elapsed_seconds',0) for r in sessions),
                'known_api_equivalent_usd':sum(r.get('api_price_equivalent_usd') or 0 for r in sessions),
                'unmetered_sessions':sum(r.get('usage') is None for r in sessions),
                'actual_subscription_cash_cost_usd':None})
        # Scoring is exclusively controller-side, after no more model calls can occur.
        scores=[]
        passing=set()
        # Sessions that did not become the main code (branches, losing attempts, rolled-back stages) do not move the
        # baseline the next graded session is compared against.
        aside={(t['stage'],label(t['checkpoint'],t['attempt'],v)) for t in trace for v in range(1,len(t.get('attempts',()))+1) if v!=t.get('winner')}
        aside|={(t['stage'],label(t['checkpoint'],t['attempt'],t.get('winner'))) for t in trace if t.get('guard',{}).get('rolled_back')}
        aside|={(t['stage'],label(t['checkpoint'],t['attempt'])) for t in trace if t.get('kind')=='branch'}
        for row in frozen:
            where=row.get('label',f"checkpoint_{row['checkpoint']}")
            score=experiment.score([row])[0]; score['role']=row['role']; score['label']=where; scores.append(score)
            shutil.copy2(row['run']/'grading/evaluation.json',output/row['role']/where/'evaluation.json')
            report=read(row['run']/'grading/evaluation.json')
            score.update(split_counts(report,row['checkpoint']))
            now,broken,gained=pass_diff(report,passing)  # Against the previous graded session of this run.
            score.update({'broken':len(broken),'gained':len(gained)})
            if (row['role'],where) in aside:
                score['aside']=True
            else:
                passing=now
            if not args.no_quality:
                # Report-only: a failed analysis is recorded, never allowed to lose the run's grades.
                try:
                    rows=analyze_snapshot(row['run']/'submission',manifest['problems'][args.problem]['entry_file'],
                                          DATA_ROOT/'intermediate/runs'/args.run_id/'quality'/row['role']/where,read(output/row['role']/where/'snapshot.json'))
                    save(output/row['role']/where/'quality.json',rows)
                    score['quality']=headline(rows)
                except Exception as error:
                    score['quality']={'error':f'{type(error).__name__}: {error}'}
            for filename in ['dependency-install.json','dependency-freeze.txt']:
                receipt=row['run']/filename
                if receipt.exists():
                    shutil.copy2(receipt,output/row['role']/where/filename)
            save(output/'scores.json',scores)
            print(f"Graded {row['role']} {where}: {score['passed']}/{score['total']} (-{score['broken']} / +{score['gained']}){quality_note(score)}",flush=True)
        if failure:
            raise failure


if __name__ == '__main__':
    main()
