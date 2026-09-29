"""Report the completed Sonnet baseline with paired local baseline comparisons."""
import json
from pathlib import Path
import sys
BASE=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(BASE/'src'))
from kojo.registry import register_runs
from kojo.gauntlet import hashes
from kojo.external_access import audit_external_sources
from report_checkpoint_compare import outcomes,paired

def read(p):return json.loads(p.read_text())
def save(p,x):p.write_text(json.dumps(x,indent=2)+'\n')

def main():
    import argparse
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-id', required=True)
    args=parser.parse_args()
    plan=read(BASE/'results/runs'/args.run_id/'experiment-plan.json')
    rid=plan['run_id'];root=BASE/'results/runs'/rid
    scores=read(root/'scores.json');manifest=read(root/'manifest.json')
    assert len(scores)==5 and not (root/'STOPPED.json').exists()
    assert manifest['review_loops']==0 and manifest['source_run'] is None
    records=[];ids=[];audits=[];pairs={};links=[];breakdown={};trace_metrics={}
    lines=[f"# Sonnet 4.6 {plan['effort']} single-pass trial", '', 'Original trajectory: '+plan.get('intervention', 'No response-limit intervention configured.'),'',f"| Checkpoint | Sonnet {plan['effort']} | Luna low | Astra low | Input (cached) | Output | Minutes | API-equivalent USD |",'|---|---:|---:|---:|---:|---:|---:|---:|']
    for n in range(1,6):
        d=root/'build'/f'checkpoint_{n}';r=read(d/'run.json');v=read(d/'transcript-verification.json')
        assert r['model']=='claude-sonnet-4-6' and r['reasoning']==plan['effort']
        assert r['fresh_conversation'] and r['network_enabled'] and r['max_budget_usd'] is None
        assert v['exact_user_prompt'] and v['stock_prompt_snapshot']
        assert hashes(d/'submission')==read(d/'snapshot.json')
        assert read(d/'initial-src.json')==(read(root/'build'/f'checkpoint_{n-1}'/'snapshot.json') if n>1 else {})
        ids.append(v['session_id']);records.append(r)
        raw=BASE/'intermediate/runs'/rid/'gauntlet/training-build/code_search'/f'checkpoint_{n}'
        events=[json.loads(line) for line in (raw/'events.jsonl').read_text().splitlines()]
        trace_metrics[str(n)]={'native_permission_denials':sum(e.get('subtype')=='permission_denied' for e in events),'output_limit_continuations':sum(e.get('type')=='user' and 'Output token limit hit.' in json.dumps(e.get('message',{})) for e in events)}
        audit=audit_external_sources(raw/'transcript.jsonl')
        save(d/'external-access.json',audit)
        audits.append({'checkpoint':n,**audit})
        s=next(s for s in scores if s['checkpoint']==n)
        breakdown[str(n)]=read(d/'evaluation.json')['tests']
        if plan.get('resume_run') and n <= plan['resume_checkpoint']:
            prior=BASE/'results/runs'/plan['resume_run']/'build'/f'checkpoint_{n}'
            assert r['session_id']==read(prior/'run.json')['session_id']
            assert outcomes(d/'evaluation.json')==outcomes(prior/'evaluation.json'), 'Retained checkpoint grade changed'
        cells=[f"{s['passed']}/{s['total']}"]
        pairs[str(n)]={}
        for label in ['luna','astra']:
            old=BASE/'results/runs'/f'20260928-code-search-{label}-network-01'
            x=next(s for s in read(old/'scores.json') if s['checkpoint']==n)
            cells.append(f"{x['passed']}/{x['total']}")
            assert (old/'build'/f'checkpoint_{n}'/'prompt.md').read_text()==(d/'prompt.md').read_text()
            pairs[str(n)][label]=paired(outcomes(old/'build'/f'checkpoint_{n}'/'evaluation.json'),outcomes(d/'evaluation.json'))
        u=r.get('usage') or {};cost=r.get('api_price_equivalent_usd')
        ins=f"{u.get('input_tokens','unknown')} ({u.get('cached_input_tokens','unknown')})"
        lines.append(f"| {n} | "+' | '.join(cells)+f" | {ins} | {u.get('output_tokens','unknown')} | {r['elapsed_seconds']/60:.2f} | {format(cost,'.4f') if cost is not None else 'unknown'} |")
        raw=BASE/'intermediate/runs'/rid/'gauntlet/training-build/code_search'/f'checkpoint_{n}'
        links.append(f'- CP{n}: [prompt](build/checkpoint_{n}/prompt.md), [native transcript]({raw}/transcript.jsonl), [external access](build/checkpoint_{n}/external-access.json).')
    assert len(ids)==len(set(ids))==5
    strict=sum(s['passed']==s['total'] for s in scores)
    usd=sum(r.get('api_price_equivalent_usd') or 0 for r in records)
    minutes=sum(r['elapsed_seconds'] for r in records)/60
    unknown=sum(r.get('usage') is None for r in records)
    usage={key:sum((r.get('usage') or {}).get(key,0) or 0 for r in records) for key in ('input_tokens','cached_input_tokens','output_tokens','reasoning_output_tokens')}
    assert all(r.get('max_output_tokens_override') == plan.get('max_output_tokens') for r in records)
    lines += ['',f"Restart provenance: {plan.get('restart_reason', 'Fresh run.')} Retained checkpoints, if any, preserve their original session IDs, usage and limits; see restart.json.", '',f'Strict checkpoint success: {strict}/5. Generation time: {minutes:.2f} minutes. Known API-equivalent usage: ${usd:.4f}; {unknown} sessions with unknown token usage. Claude Max subscription charges are not inferred from this estimate.',
              '',f"Total usage: {usage['input_tokens']:,} input tokens, including {usage['cached_input_tokens']:,} cached; {usage['output_tokens']:,} output tokens, including {usage['reasoning_output_tokens']:,} reported thinking tokens.",
              '',f"Native transcript events: {sum(t['output_limit_continuations'] for t in trace_metrics.values())} output-limit continuations and {sum(t['native_permission_denials'] for t in trace_metrics.values())} permission denials. Denials are recorded tool feedback; their detailed classifier cause is not exposed. [Per-checkpoint trace metrics](trace-metrics.json).",
              '',f'External-access inventory: {sum(len(a["events"]) for a in audits)} recorded network-capable operations; {sum(bool(a.get("review_suggested")) for a in audits)} sessions flagged for human review. See [external access](external-access.json); this is a heuristic transcript inventory, not a complete network log.',
              '', f"The paper reports Sonnet 4.6 at high effort with Claude Code 2.1.44, a two-hour checkpoint limit, 8.5% strict success across its benchmark, and mean $1.92/checkpoint. This run uses CLI 2.1.283, adaptive thinking/{plan['effort']}, {plan['seconds_per_session']//60}-minute checkpoint limits, a Dockerless macOS workspace and one previously examined problem. Its checkpoint fraction is not directly comparable to the paper-wide percentage. [Paper, Table 1 and Appendix A](https://arxiv.org/html/2603.24755v1).",
              '', 'Local paired comparisons use the identical five task prompts and scoring tests. Sonnet uses a different provider CLI, effort setting, and time limit; Luna/Astra use Codex, low effort, and ten-minute limits. This is a model-plus-harness comparison, not an isolated model effect. One sample each, no learned skills, no review, and no official grading feedback supplied to the model sessions.',
              '', '[Paired pass/fail test identities](paired.json). [Tests by checkpoint and regression group](checkpoint-breakdown.json). [Session accounting](accounting.json).',
              '', 'To reproduce this continuation, copy its frozen `experiment-plan.json` to `configs/experiments/sonnet-46-baseline.json` and choose a new run ID. For a fresh trajectory from CP1, also remove `resume_run` and `resume_checkpoint`. Then run `python3.12 scripts/sonnet_baseline.py --run`. This spends subscription usage. Rebuild this report with `python3.12 scripts/report_sonnet_baseline.py --run-id <run-id>` using this run’s frozen `experiment-plan.json`.']
    lines += ['', '## Failure carryover', '', '| Checkpoint | Prior-checkpoint tests passed | New-checkpoint tests passed |', '|---|---:|---:|']
    for n,groups in breakdown.items():
        counts=[]
        for regression in (True,False):
            selected=[g for name,g in groups.items() if ('Regression' in name)==regression]
            passed=sum(len(g['passed']) for g in selected)
            total=sum(sum(len(v) for v in g.values()) for g in selected)
            counts.append(f'{passed}/{total}' if total else '—')
        lines.append(f"| {n} | {counts[0]} | {counts[1]} |")
    lines += ['', 'These checkpoints form one incremental task. Strict final-task success requires every CP5 test to pass; the run did not achieve it, so cost per fully successful final task is undefined. The two fully passing early checkpoints are not two independent solved tasks.', '', '[Earlier attempts and costs, deduplicated across restarts](../../comparisons/20260928-sonnet-attempts/RESULTS.md).']
    save(root/'paired.json',pairs);save(root/'external-access.json',audits)
    save(root/'checkpoint-breakdown.json',breakdown)
    save(root/'trace-metrics.json',trace_metrics)
    (root/'RESULTS.md').write_text('\n'.join(lines)+'\n')
    (root/'TRANSCRIPTS.md').write_text('# Captured transcripts\n\n'+'\n'.join(links)+'\n')
    register_runs([{'run_id':rid,'results':str(root.relative_to(BASE)),'intermediate':f'intermediate/runs/{rid}','report':f'results/runs/{rid}/RESULTS.md','logs':f'results/runs/{rid}/TRANSCRIPTS.md'}])
    print('\n'.join(lines[:14]))

if __name__=='__main__':main()
