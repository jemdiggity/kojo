"""Run the approved three-problem comparison with a barrier between problems."""
import argparse
import json
import subprocess
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from kojo.catalog import BASE, protocol_digest
from kojo.batch import load_plan
from kojo.execution import save

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run',action='store_true')
    parser.add_argument('--tmux-session',default='scb-dex-comparison')
    args=parser.parse_args()
    paths=[BASE/f'configs/batches/20260928-dex-{name}.json' for name in
           ['circuit-eval','database-migration','dynamic-config-service-api']]
    plans=[load_plan(p) for p in paths]
    protocol=protocol_digest()
    root=BASE/'intermediate/series/20260928-dex-comparison'
    if not args.run:
        print(json.dumps(plans,indent=2));return 0
    root.mkdir(parents=True,exist_ok=False)
    save(root/'plan.json',{'problems_in_series':plans,'protocol_sha256':protocol,
         'timeout_policy':'Stop a timed-out model chain; a failed batch stops the series for diagnosis before next problem.'})
    for path,plan in zip(paths,plans):
        frozen=root/path.name
        save(frozen,plan)
    for path,plan in zip(paths,plans):
        path=root/path.name
        if protocol_digest()!=protocol:raise RuntimeError('Protocol changed before next problem')
        save(root/'status.json',{'status':'running','batch_id':plan['batch_id']})
        cmd=[sys.executable,str(BASE/'scripts/scb_batch.py'),str(path),'--run','--jobs','5','--tmux-session',args.tmux_session]
        result=subprocess.run(cmd,cwd=BASE)
        if result.returncode:
            save(root/'status.json',{'status':'stopped','batch_id':plan['batch_id'],'exit_code':result.returncode})
            return result.returncode
    save(root/'status.json',{'status':'complete'})
    return 0

if __name__=='__main__':raise SystemExit(main())
