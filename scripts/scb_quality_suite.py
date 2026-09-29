"""Analyze all selected frozen suite snapshots with pinned scb-check; no inference.
Run with intermediate/quality-suite-venv/bin/python. Uses the analyzer API to retain
per-callable and per-file data that its CLI summary omits. Never executes submissions.
"""
import argparse,ast,concurrent.futures,hashlib,io,json,os,shutil,sys
from dataclasses import asdict
from pathlib import Path
from importlib.metadata import version
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from kojo.catalog import DATA_ROOT
from kojo.gauntlet import hashes
OUT=ROOT/'results/comparisons/20260928-dex-subset/quality-suite'
SCRATCH=ROOT/'intermediate/quality/quality-suite'

def test_file(p):
    return any(x.lower() in {'tests','test','testing'} for x in p.parts) or p.name.startswith('test_') or p.stem.endswith('_test') or p.name=='conftest.py' or p.stem.startswith('smoke_test')

class PhysicalLines(str):
    """Keep Python physical LF lines; Unicode separators remain string content."""
    def splitlines(self, keepends=False):
        lines=io.StringIO(self).readlines()
        return lines if keepends else [line.removesuffix("\n") for line in lines]

def analyze_job(job):
    from scb_check import pipeline
    from scb_check.analysis.parse import parse_file as original_parse
    def physical_parse(path):
        source,tree=original_parse(path)
        return PhysicalLines(source),tree
    pipeline.parse_file=physical_parse
    from scb_check.pipeline import analyze,analyze_files
    from scb_check.config import load_config
    from scb_check.reporting.score import compute_report
    rid,cp=job;source=DATA_ROOT/'results/runs'/rid/'build'/cp/'submission'
    expected=json.loads((source.parent/'snapshot.json').read_text());before=hashes(source)
    if expected!=before:raise RuntimeError('Source hash mismatch')
    key=hashlib.sha256(json.dumps(before,sort_keys=True).encode()).hexdigest()
    dest=SCRATCH/rid/cp;dest.mkdir(parents=True,exist_ok=True);cached=dest/'result.json'
    if cached.exists() and json.loads(cached.read_text()).get('analyzer_fix')=='physical-lines-v1':
        r=json.loads(cached.read_text())
        if r['source_sha256']!=key:raise RuntimeError('Cached source mismatch')
        return r
    manifest=json.loads((source.parents[2]/'manifest.json').read_text());entry=manifest['problem_metadata']['entry_file']
    work=dest/'source'
    if not work.exists():shutil.copytree(source,work)
    normalized=[];shell=[]
    entrypath=work/entry
    if not entrypath.exists() and entrypath.with_name(entrypath.name+'.py').exists():
        normalized.append({'from':entry,'to':entrypath.name+'.py'})
    if entrypath.is_file() and entrypath.suffix!='.py':
        body=entrypath.read_text()
        if body.startswith('#!') and any(x in body.split('\n')[0] for x in ['/sh','/bash','env sh','env bash']):shell.append(entry)
        else:
            ast.parse(body);target=entrypath.with_name(entrypath.name+'.py')
            if target.exists():raise RuntimeError('Normalization collision')
            entrypath.rename(target);normalized.append({'from':entry,'to':target.name})
    config=load_config(None,ROOT)
    result=analyze(work,config,include_all=True)
    def summarize(result):
        flags=result.flags;report=asdict(compute_report(flags));funcs=flags.all_functions
        files=[{'path':str(p.relative_to(work)),'sloc':loc,'category':'test' if test_file(p.relative_to(work)) else 'other'} for p,loc in flags.total_loc_by_file]
        report.update(cc_mean=sum(f.cyc_complexity for f in funcs)/len(funcs) if funcs else None,cc_max=max((f.cyc_complexity for f in funcs),default=None),clone_fraction=report['clone_loc']/report['total_loc'] if report['total_loc'] else None,single_use_functions=sum(len(f.usages)==1 for f in funcs),unused_functions=sum(len(f.usages)==0 for f in funcs))
        report['single_use_fraction']=report['single_use_functions']/len(funcs) if funcs else None
        report['test_sloc']=sum(f['sloc'] for f in files if f['category']=='test');report['other_sloc']=report['total_loc']-report['test_sloc']
        return {'metrics':report,'files':files,'functions':[dict(name=f.name,file=str(f.file.relative_to(work)),line=f.start_line,cc=f.cyc_complexity,sloc=f.sloc,static_usages=len(f.usages)) for f in funcs]}
    variants={'entrypoint-normalized':summarize(result)}
    native=tuple(p for p,_ in result.flags.total_loc_by_file if not any(p==work/n['to'] for n in normalized))
    prod=tuple(p for p,_ in result.flags.total_loc_by_file if not test_file(p.relative_to(work)))
    for name,files in [('upstream',native),('non-test-python',prod)]:
        if len(files)==len(result.flags.total_loc_by_file):variants[name]=variants['entrypoint-normalized']
        elif files:variants[name]=summarize(analyze_files(files,include_all=True))
        else:variants[name]={'metrics':{'files_scanned':0,'total_loc':0,'erosion':None,'verbosity':None},'files':[],'functions':[]}
    r=dict(analyzer_fix='physical-lines-v1',unicode_separator_files=[str(p.relative_to(work)) for p in work.rglob('*.py') if any(c in p.read_text() for c in ['\u2028','\u2029','\x85','\x0b','\x0c'])],run_id=rid,problem=manifest['problem'],checkpoint=int(cp.split('_')[-1]),source_sha256=key,normalization=normalized,shell_entrypoints_excluded=shell,variants=variants)
    if hashes(source)!=before:raise RuntimeError('Source changed during quality analysis')
    cached.write_text(json.dumps(r,indent=2)+'\n');return r

def main():
    assert version('scb-check')=='0.1.3'
    parser=argparse.ArgumentParser();parser.add_argument('--jobs',type=int,default=2);args=parser.parse_args()
    verify=json.loads((OUT.parent/'suite_verification.json').read_text());jobs=[(r['run_id'],f"checkpoint_{r['checkpoint']}") for r in verify['checkpoints']]
    OUT.mkdir(parents=True,exist_ok=True);rows=[]
    with concurrent.futures.ProcessPoolExecutor(max_workers=args.jobs) as pool:
        for job,r in zip(jobs,pool.map(analyze_job,jobs)):
            rows.append(r);print(f'{len(rows)}/{len(jobs)} {job}',flush=True)
    (OUT/'quality.json').write_text(json.dumps({'scb_check_version':version('scb-check'),'rows':rows,'coverage':'Python only; extensionless Python normalized in analysis copy; shell launchers excluded; native and non-test sensitivity variants retained.','test_classification':'tests/test/testing directories, test_*.py, *_test.py, conftest.py, smoke_test*.py; all other discovered Python is other, not guaranteed production-only.'},indent=2)+'\n')
if __name__=='__main__':main()
