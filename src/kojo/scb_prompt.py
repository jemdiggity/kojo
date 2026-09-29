"""Use the pinned upstream SCB renderer and just-solve template unchanged."""
import json
import subprocess
from kojo.catalog import BASE, load_config, check_repositories


def render_checkpoint(spec, checkpoint, python, entry_file="code_search"):
    cfg=load_config()
    check_repositories(cfg)
    payload={'spec_text':spec,'context':{'is_continuation':checkpoint != 1,
             'agent_type':'codex','agent_version':cfg['codex_version'],'model_name':cfg['model']},
             'entry_file':entry_file,'entry_command':str(python)+' '+entry_file,
             'prompt_template':(BASE/'intermediate/vendor/slop-code-bench/configs/prompts/just-solve.jinja').read_text()}
    script='import json,sys; from slop_code.common.render import render_prompt; sys.stdout.write(render_prompt(**json.load(sys.stdin)))'
    return subprocess.check_output([str(BASE/'intermediate/scb-runner-venv/bin/python'),'-c',script],input=json.dumps(payload),text=True)
