"""Regrade immutable snapshots with language-aware invocation; preserve old scores."""
import argparse
import json
from pathlib import Path
import shlex
import sys
BASE=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(BASE/'src'))
from kojo import gauntlet
from kojo.catalog import metadata
from kojo.run_chain import ChainBackend


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('run_id');parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();out=args.output.resolve();out.mkdir(parents=True,exist_ok=False)
    run=BASE/'results/runs'/args.run_id
    manifest=json.loads((run/'manifest.json').read_text());problem=manifest['problem']
    original=gauntlet.evaluation_environment
    def environment(python,dependency_report=None):
        config=original(python,dependency_report)
        config['commands']['command']=shlex.join([str(python),str(BASE/'scripts/scb_entrypoint.py')])
        return config
    gauntlet.evaluation_environment=environment
    cfg,catalog=gauntlet.preflight(check_codex=False);catalog['problems'][problem]=metadata(problem)
    data=BASE/'intermediate/regrading'/out.name;data.mkdir(parents=True,exist_ok=False)
    backend=ChainBackend(cfg,catalog,data,out);backend.install_dependencies=True
    rows=[]
    for cp in sorted((run/'build').glob('checkpoint_*')):
        if not (cp/'snapshot.json').exists():continue
        source=cp/'submission';before=gauntlet.hashes(source)
        if before!=json.loads((cp/'snapshot.json').read_text()):raise RuntimeError('Source hash mismatch')
        dest=data/cp.name;dest.mkdir()
        score=backend.grade(source,problem,int(cp.name.split('_')[-1]),dest/'grading')
        if gauntlet.hashes(source)!=before:raise RuntimeError('Original source changed')
        row={'checkpoint':cp.name,'score':score,'evaluation':json.loads((dest/'grading/evaluation.json').read_text())};rows.append(row)
        (out/'regrading.json').write_text(json.dumps({'run_id':args.run_id,'invocation':'language-aware-v1','original_results_preserved':True,'checkpoints':rows},indent=2)+'\n')
        print(cp.name,score,flush=True)

if __name__=='__main__':main()
