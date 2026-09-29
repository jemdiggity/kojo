"""Concurrent real-process scheduling and registry checks; no model calls."""
import contextlib
import io
import json
import multiprocessing
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import unittest

BASE=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(BASE/'src'))
from kojo.batch import commands, execute, load_plan
from kojo.registry import register_runs


def register_worker(base, n, barrier):
    barrier.wait()
    register_runs([{'run_id':str(n),'results':str(n)}],base)


class BatchTests(unittest.TestCase):
    def test_parallel_queue_failure_isolation_and_per_run_logs(self):
        with tempfile.TemporaryDirectory() as d:
            base=Path(d)
            plan={'batch_id':'test','runs':[{'run_id':n} for n in ['a','b','c']]}
            worker="import sys,time; print(sys.argv[1],flush=True); time.sleep(0.3); sys.exit(int(sys.argv[2]))"
            cmds=[(n,[sys.executable,'-c',worker,n,str(int(n=='a'))]) for n in ['a','b','c']]
            with contextlib.redirect_stdout(io.StringIO()):
                code=execute(plan,base/'batch',2,base=base,command_list=cmds)
            self.assertEqual(code,1)
            states=json.loads((base/'batch/status.json').read_text())['runs']
            self.assertEqual([states[n]['status'] for n in ['a','b','c']],['failed','complete','complete'])
            self.assertLess(max(states[n]['started_at'] for n in ['a','b']),min(states[n]['finished_at'] for n in ['a','b']))
            self.assertGreaterEqual(states['c']['started_at'],min(states[n]['finished_at'] for n in ['a','b']))
            for n in ['a','b','c']:
                root=base/'intermediate/runs'/n
                self.assertEqual((root/'controller.log').read_text().strip(),n)
                self.assertEqual(json.loads((root/'run-config.json').read_text())['run_id'],n)
            with self.assertRaisesRegex(RuntimeError,'already used'):
                execute(plan,base/'batch-again',2,base=base,command_list=cmds)

    def test_validation_happens_before_launch_and_audits_have_separate_ids(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'plan.json'
            plan={'batch_id':'test','runs':[{'run_id':'a','factory_args':['--no-review']}]}
            p.write_text(json.dumps(plan))
            valid=load_plan(p)
            self.assertEqual(commands(valid,'run')[0][0],'a')
            self.assertEqual(commands(valid,'audit')[0][0],'test-a-audit')
            for runs in [[{'run_id':'a'},{'run_id':'a'}],[{'run_id':'../bad'}],
                         [{'run_id':'a','factory_args':['--seconds-per-session','0']}],
                         [{'run_id':'a','factory_args':['--run-id=other']}],
                         [{'run_id':'a','factory_args':[],'model':'misspelled-field'}]]:
                p.write_text(json.dumps({**plan,'runs':runs}))
                with contextlib.redirect_stderr(io.StringIO()),self.assertRaises(ValueError):
                    load_plan(p)

    def test_registry_keeps_concurrent_updates_and_existing_metadata(self):
        with tempfile.TemporaryDirectory() as d:
            register_runs([{'run_id':'existing','report':'keep.md'}],d)
            ctx=multiprocessing.get_context('fork')
            barrier=ctx.Barrier(8)
            children=[ctx.Process(target=register_worker,args=(d,n,barrier)) for n in range(8)]
            for p in children:p.start()
            for p in children:
                p.join(10)
                self.assertEqual(p.exitcode,0)
            register_runs([{'run_id':'existing','batch_id':'new'}],d)
            items=json.loads((Path(d)/'results/runs/index.json').read_text())
            self.assertEqual(len(items),9)
            self.assertEqual(next(x for x in items if x['run_id']=='existing')['report'],'keep.md')

    def test_sigterm_cancels_active_controller_and_does_not_start_queue(self):
        with tempfile.TemporaryDirectory() as d:
            base=Path(d)
            worker=base/'worker.py'
            worker.write_text("import signal,time,sys\nfrom pathlib import Path\ndef stop(*args):\n Path(sys.argv[1]).write_text('cancelled')\n raise SystemExit(130)\nsignal.signal(signal.SIGINT,stop)\nPath(sys.argv[2]).write_text('ready')\ntime.sleep(30)\n")
            runner=base/'runner.py'
            runner.write_text("import sys\nfrom pathlib import Path\nsys.path.insert(0,"+repr(str(BASE/'src'))+")\nfrom kojo.batch import execute\nb=Path("+repr(str(base))+")\np={'batch_id':'cancel','runs':[{'run_id':'a'},{'run_id':'b'}]}\ncmds=[(n,[sys.executable,str(b/'worker.py'),str(b/(n+'-cancel')),str(b/(n+'-ready'))]) for n in ['a','b']]\nraise SystemExit(execute(p,b/'batch',1,base=b,command_list=cmds))\n")
            process=subprocess.Popen([sys.executable,str(runner)],stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
            try:
                deadline=time.monotonic()+5
                while not (base/'a-ready').exists() and time.monotonic()<deadline:
                    time.sleep(0.02)
                self.assertTrue((base/'a-ready').exists())
                process.send_signal(signal.SIGTERM)
                _,err=process.communicate(timeout=5)
                self.assertEqual(process.returncode,130,err.decode())
                self.assertTrue((base/'a-cancel').exists())
                self.assertFalse((base/'b-ready').exists())
                states=json.loads((base/'batch/status.json').read_text())['runs']
                self.assertEqual(states['a']['status'],'cancelled')
                self.assertEqual(states['b']['status'],'cancelled_before_start')
            finally:
                if process.poll() is None:process.kill();process.wait()
                if process.stderr:process.stderr.close()


if __name__=='__main__':unittest.main()
