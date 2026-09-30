"""Regrade immutable snapshots with language-aware invocation; preserve old scores."""
import argparse
import concurrent.futures
import json
from pathlib import Path
import shlex
import sys
BASE=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(BASE/'src'))
from kojo.catalog import DATA_ROOT
from kojo import gauntlet
from kojo.catalog import metadata
from kojo.run_chain import ChainBackend


def launcher_environment(python,dependency_report=None,venv=None):
    """The shared grading environment, with the base interpreter starting the language-aware launcher."""
    config=ORIGINAL_ENVIRONMENT(python,dependency_report,venv)
    config['commands']['command']=shlex.join([str(python),str(BASE/'scripts/scb_entrypoint.py')])
    return config


ORIGINAL_ENVIRONMENT=gauntlet.evaluation_environment


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('run_id');parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--jobs',type=int,default=gauntlet.DEFAULT_GRADING_JOBS,help=f'Checkpoints graded at the same time (default: {gauntlet.DEFAULT_GRADING_JOBS})')
    args=parser.parse_args()
    if args.jobs<1:parser.error('jobs must be positive')
    out=args.output.resolve();out.mkdir(parents=True,exist_ok=False)
    run=DATA_ROOT/'results/runs'/args.run_id
    manifest=json.loads((run/'manifest.json').read_text());problem=manifest['problem']
    gauntlet.evaluation_environment=launcher_environment
    cfg,catalog=gauntlet.preflight(check_codex=False);catalog['problems'][problem]=metadata(problem)
    data=BASE/'intermediate/regrading'/out.name;data.mkdir(parents=True,exist_ok=False)
    backend=ChainBackend(cfg,catalog,data,out);backend.install_dependencies=True
    checkpoints=[cp for cp in sorted((run/'build').glob('checkpoint_*')) if (cp/'snapshot.json').exists()]
    before={}
    for cp in checkpoints:
        before[cp.name]=gauntlet.hashes(cp/'submission')
        if before[cp.name]!=json.loads((cp/'snapshot.json').read_text()):raise RuntimeError('Source hash mismatch')
        (data/cp.name).mkdir()
    def grade(cp):
        return backend.grade(cp/'submission',problem,int(cp.name.split('_')[-1]),data/cp.name/'grading')
    rows=[]
    # Checkpoints are independent snapshots, so several are graded at once; the record keeps checkpoint order.
    pool=concurrent.futures.ThreadPoolExecutor(max_workers=args.jobs)
    try:
        futures=[(cp,pool.submit(grade,cp)) for cp in checkpoints]
        for cp,future in futures:
            score=future.result()
            if gauntlet.hashes(cp/'submission')!=before[cp.name]:raise RuntimeError('Original source changed')
            row={'checkpoint':cp.name,'score':score,'evaluation':json.loads((data/cp.name/'grading/evaluation.json').read_text())};rows.append(row)
            (out/'regrading.json').write_text(json.dumps({'run_id':args.run_id,'invocation':'language-aware-v1','original_results_preserved':True,'checkpoints':rows},indent=2)+'\n')
            print(cp.name,score,flush=True)
    except BaseException:
        backend.stop();raise
    finally:
        pool.shutdown(wait=True,cancel_futures=True)

if __name__=='__main__':main()
