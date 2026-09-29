"""Claude Code adapter: stock prompt, explicit settings, and no-inference audit."""
import argparse
import hashlib
import http.server
import json
import math
import os
from pathlib import Path
import queue
import shlex
import shutil
import signal
import subprocess
import threading
import time
import uuid

from kojo.execution import save, shell_environment

VERSION = "2.1.283"
MODELS = ("claude-opus-4-6", "claude-sonnet-4-6", "claude-opus-5-5", "claude-opus-5", "claude-sonnet-5-5", "claude-fable-5-1")
EFFORTS = ("low", "medium", "high")
THINKING_TOKENS = {"low": 4000, "medium": 10000, "high": 31999}


def executable():
    """Use the immutable native version, not the auto-updated CLI symlink."""
    pinned = Path.home()/".local/share/claude/versions"/VERSION
    return str(pinned) if pinned.is_file() else "claude"


def settings(work, network_enabled=True, native=False):
    return {
        "disableAllHooks": True,
        "disableBundledSkills": True,
        "skillOverrides": {"doctor": "off"},
        "autoMemoryEnabled": False,
        "permissions": {
            "defaultMode": "dontAsk",
            "blockReadsOutsideWorkingDirectories": True,
            "allow": ["Bash", "Read", "Edit", "Write", "Glob", "Grep"] + (["Skill"] if native else []),
            "deny": ["Agent", "Task"] + ([] if native else ["Skill"]),
        },
        "sandbox": {
            "enabled": True,
            "failIfUnavailable": True,
            "autoAllowBashIfSandboxed": True,
            "allowUnsandboxedCommands": False,
            "excludedCommands": [],
            "filesystem": {
                "denyRead": [str(Path.home())],
                "allowRead": [str(work)],
                "allowWrite": [str(work)],
                "denyWrite": [str(work/".claude")] if native else [],
            },
            "network": {"allowedDomains": ["*"] if network_enabled else [], "allowLocalBinding": network_enabled},
        },
        "env": shell_environment(work),
    }


def environment(effort, *, audit_url=None, config_dir=None, max_output_tokens=None, model=None):
    # Preserve login infrastructure, but remove inherited model/effort/provider
    # customizations. Never print or persist this environment.
    auth = {"CLAUDE_CODE_OAUTH_TOKEN", "CLAUDE_CONFIG_DIR"}
    env = {k:v for k,v in os.environ.items()
           if not (k.startswith(("ANTHROPIC_", "CLAUDE_", "OPENAI_", "CODEX_"))
                   or k in {"MAX_THINKING_TOKENS", "PYTHONPATH"})
           or k in auth}
    env.update({
        "CLAUDE_CODE_EFFORT_LEVEL": effort,
        "MAX_THINKING_TOKENS": str(THINKING_TOKENS[effort]),
        "DISABLE_AUTOUPDATER": "1",
        "DISABLE_NON_ESSENTIAL_MODEL_CALLS": "1",
        "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1",
    })
    if model in ("claude-opus-5-5", "claude-opus-5", "claude-sonnet-5-5", "claude-fable-5-1"):
        env.pop("MAX_THINKING_TOKENS", None)  # Adaptive thinking; keep CLI token defaults.
    if max_output_tokens is not None:
        if not isinstance(max_output_tokens,int) or max_output_tokens<=0:raise ValueError("Invalid output-token allowance")
        env["CLAUDE_CODE_MAX_OUTPUT_TOKENS"]=str(max_output_tokens)
    if audit_url:
        env.pop("CLAUDE_CODE_OAUTH_TOKEN", None)
        env.update(ANTHROPIC_BASE_URL=audit_url, ANTHROPIC_API_KEY="offline-audit-placeholder",
                   CLAUDE_CONFIG_DIR=str(config_dir))
    return env


def command(run, work, model, effort, session_id, network_enabled=True, max_budget_usd=None, native_skill_set=None):
    from kojo.skill_sets import active_source
    native_skill_set = active_source(native_skill_set)
    if model not in MODELS or effort not in EFFORTS:
        raise ValueError("Unsupported Claude model/effort")
    run.mkdir(parents=True,exist_ok=True)
    work.mkdir(parents=True,exist_ok=True)
    # Claude discovers ancestor Git history even with GIT_CEILING_DIRECTORIES.
    # An empty local repository prevents controller history entering the prompt.
    if not (work/".git").exists():
        subprocess.run(["git","init","--quiet","--initial-branch=main",str(work)],check=True)
    from kojo.skill_sets import install
    native=install(work,native_skill_set,'claude')
    if native:
        save(work/".claude/.claude-plugin/plugin.json", {"name":"kojo-selected", "version":"1.0.0"})
    save(run/"claude-settings.json", settings(work,network_enabled,bool(native)))
    if max_budget_usd is not None and (not math.isfinite(max_budget_usd) or max_budget_usd<=0):
        raise ValueError("Claude budget must be finite and positive")
    args = [executable(), "--print", "--verbose", "--output-format", "stream-json",
            "--safe-mode", "--restricted", "--disable-slash-commands",
            "--setting-sources", "", "--settings", str(run/"claude-settings.json"),
            "--strict-mcp-config", "--mcp-config", '{"mcpServers":{}}',
            "--no-chrome", "--tools", "Bash,Read,Edit,Write,Glob,Grep", "--permission-mode", "dontAsk",
            "--model", model, "--effort", effort,
            "--session-id", session_id, "--system-prompt-snapshot", "on"]
    if native:
        args.remove("--safe-mode")
        args.remove("--disable-slash-commands")
        args[args.index("--tools")+1] += ",Skill"
        args += ["--plugin-dir",str(work/".claude")]
    if max_budget_usd is not None:args += ["--max-budget-usd", str(max_budget_usd)]
    return args


def check_version():
    actual=subprocess.check_output([executable(),"--version"],text=True).strip()
    if actual != VERSION+" (Claude Code)":
        raise RuntimeError("Claude CLI version differs from the pinned adapter version")
    return actual


def verify_request(payload, prompt, model, effort, native=False):
    if payload.get("model") != model:
        raise RuntimeError("Claude request model mismatch")
    system=payload.get("system",[])
    text="\n".join(x.get("text","") for x in system) if isinstance(system,list) else system
    messages=payload.get("messages",[])
    if not text or not any(m.get("content")==prompt or
                           any(c.get("text")==prompt for c in m.get("content",[]) if isinstance(c,dict))
                           for m in messages if m.get("role")=="user"):
        raise RuntimeError("Missing stock system prompt or task in Claude request")
    actual_effort=payload.get("output_config",{}).get("effort")
    if actual_effort != effort:
        raise RuntimeError(f"Claude wire effort mismatch: {actual_effort!r}")
    tools=[t["name"] for t in payload.get("tools",[])]
    if set(tools) != {"Bash","Read","Write","Edit","Glob","Grep"} | ({"Skill"} if native else set()):
        raise RuntimeError("Unexpected skill or MCP tools")
    return {"model":model,"reasoning":actual_effort,"thinking":payload.get("thinking"),
            "max_tokens":payload.get("max_tokens"),"tools":tools,
            "base_instructions_mode":"stock; no replacement or append flags",
            "base_instructions_sha256":hashlib.sha256(text.encode()).hexdigest(),
            "exact_user_prompt_in_request":True,"skills_disabled":not native,
            "evidence":"Captured local dummy-endpoint request; no inference."},text


def audit(run, instructions=None, runtime=None, skill=None, isolated_src=True,
          prompt=None, persist=True, model=MODELS[0], work_path=None,
          network_enabled=True, effort="high", max_budget_usd=None, max_output_tokens=None, native_skill_set=None):
    from kojo.skill_sets import active_source
    native_skill_set = active_source(native_skill_set)
    if instructions is not None or skill is not None:
        raise ValueError("Claude baseline preserves stock instructions; supply role text in the user prompt")
    check_version()
    run=Path(run);work=Path(work_path) if work_path else run/"src"
    prompt=prompt or "Offline configuration audit."
    requests=queue.Queue()
    marker=run/"outside-marker.txt"
    marker.parent.mkdir(parents=True,exist_ok=True)
    marker.write_text("KOJO_PRIVATE_AUDIT_MARKER")
    script = f"""from pathlib import Path
p=Path('native-write-smoke.txt')
p.write_text('ok')
assert p.read_text()=='ok'
p.unlink()
try:
    Path({str(marker)!r}).read_text()
except PermissionError:
    print('private-read-blocked')
else:
    raise AssertionError('outside file readable')
print('native-write-smoke-ok')
"""
    if native_skill_set is not None:
        from kojo.skill_sets import install
        native=install(work,native_skill_set,'claude')
        for entry in native['skills']:
            path=Path(native['installed_root'])/entry['name']/'SKILL.md'
            script += f"assert Path({str(path)!r}).read_text()\n"
    if network_enabled:
        script += "import socket\ns=socket.socket(); s.bind(('127.0.0.1',0)); s.listen(); s.close()\nprint('local-bind-ok')\n"
    work.mkdir(parents=True,exist_ok=True)
    smoke_path=work/(".kojo-audit-"+uuid.uuid4().hex+".py")
    smoke_path.write_text(script)
    smoke_command=shlex.quote(str(Path(os.sys._base_executable).resolve()))+" "+shlex.quote(str(smoke_path))
    if network_enabled:
        smoke_command+=" && curl --fail --silent --max-time 15 --output /dev/null https://pypi.org/simple/pip/ && printf network-smoke-ok"
    def emit(handler,content,stop_reason):
        msg={"id":"msg_offline","type":"message","role":"assistant","model":model,
             "content":[],"stop_reason":None,"stop_sequence":None,
             "usage":{"input_tokens":0,"output_tokens":0}}
        events=[("message_start",{"type":"message_start","message":msg})]
        for index,block in enumerate(content):
            start={**block}
            if block["type"]=="tool_use":
                start["input"]={}
                delta={"type":"input_json_delta","partial_json":json.dumps(block["input"])}
            else:
                start["text"]=""
                delta={"type":"text_delta","text":block["text"]}
            events.append(("content_block_start",{"type":"content_block_start","index":index,"content_block":start}))
            events.append(("content_block_delta",{"type":"content_block_delta","index":index,"delta":delta}))
            events.append(("content_block_stop",{"type":"content_block_stop","index":index}))
        events.extend([("message_delta",{"type":"message_delta","delta":{"stop_reason":stop_reason,"stop_sequence":None},"usage":{"output_tokens":0}}),
                       ("message_stop",{"type":"message_stop"})])
        handler.send_response(200);handler.send_header("Content-Type","text/event-stream");handler.end_headers()
        for name,event in events:
            handler.wfile.write(("event: "+name+"\ndata: "+json.dumps(event)+"\n\n").encode())
        handler.wfile.flush()

    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def do_POST(self):
            body=json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            requests.put(body)
            if body.get("model") != model:
                self.send_response(400);self.end_headers();return
            results=[c for m in body.get("messages",[]) for c in m.get("content",[]) if isinstance(c,dict) and c.get("type")=="tool_result"]
            if not results:
                emit(self,[{"type":"tool_use","id":"tool_smoke","name":"Bash","input":{"command":smoke_command,"description":"Offline native sandbox smoke"}}],"tool_use")
            elif len(results)==1:
                emit(self,[{"type":"tool_use","id":"tool_read","name":"Read","input":{"file_path":str(marker)}}],"tool_use")
            else:
                emit(self,[{"type":"text","text":"Offline audit completed; no model inference."}],"end_turn")
        def do_GET(self):
            self.send_response(404);self.end_headers()
    server=http.server.ThreadingHTTPServer(("127.0.0.1",0),Handler)
    threading.Thread(target=server.serve_forever,daemon=True).start()
    cmd=command(run,work,model,effort,str(uuid.uuid4()),network_enabled,max_budget_usd,native_skill_set)
    cmd += ["--debug-file",str(run/"audit-debug.log")]
    env=environment(effort,audit_url=f"http://127.0.0.1:{server.server_port}",
                    config_dir=run/"audit-config",max_output_tokens=max_output_tokens,model=model)
    if native_skill_set is not None:env["CLAUDE_CODE_DISABLE_CLAUDE_MDS"]="1"
    (run/"audit-config").mkdir(exist_ok=True)
    canary="KOJO_DISABLED_CUSTOMIZATION_CANARY"
    (run/"audit-config/CLAUDE.md").write_text(canary)
    canary_skill=run/"audit-config/skills/audit-canary"
    canary_skill.mkdir(parents=True,exist_ok=True)
    (canary_skill/"SKILL.md").write_text("---\nname: audit-canary\ndescription: "+canary+"\n---\n"+canary)
    env["GIT_CEILING_DIRECTORIES"]=str(work.parent)
    p=None
    try:
        with (run/"audit-events.jsonl").open("w") as out,(run/"audit-stderr.log").open("w") as err:
            p=subprocess.Popen(cmd,cwd=work,env=env,stdin=subprocess.PIPE,stdout=out,stderr=err,
                               text=True,start_new_session=True)
            try:p.communicate(prompt,timeout=45)
            except subprocess.TimeoutExpired:
                os.killpg(p.pid,signal.SIGKILL);p.wait()
        payloads=[]
        while not requests.empty():payloads.append(requests.get_nowait())
        candidates=[p for p in payloads if p.get("model")==model]
        if not candidates:raise RuntimeError("No Claude model request captured; inspect audit logs")
        if canary in json.dumps(candidates):raise RuntimeError("Installed customization leaked into request")
        receipt,stock=verify_request(candidates[0],prompt,model,effort,native_skill_set is not None)
        if max_output_tokens is not None and receipt["max_tokens"]!=max_output_tokens:
            raise RuntimeError(f"Requested output allowance {max_output_tokens}, actual {receipt['max_tokens']}")
        tool_results=[c for m in candidates[-1].get("messages",[]) for c in m.get("content",[]) if isinstance(c,dict) and c.get("type")=="tool_result"]
        smoke=next((r for r in tool_results if r.get("tool_use_id")=="tool_smoke"),{})
        denied=next((r for r in tool_results if r.get("tool_use_id")=="tool_read"),{})
        if smoke.get("is_error") or "native-write-smoke-ok" not in json.dumps(smoke) or "private-read-blocked" not in json.dumps(smoke):
            raise RuntimeError("Claude native shell isolation smoke failed; inspect audit-events.jsonl")
        if network_enabled and "network-smoke-ok" not in json.dumps(smoke):
            raise RuntimeError("Native shell network smoke failed")
        if not denied.get("is_error") or "KOJO_PRIVATE_AUDIT_MARKER" in json.dumps(denied):
            raise RuntimeError("Claude native Read isolation smoke failed")
        receipt.update(native_shell_writes=True,private_bash_read_blocked=True,private_file_tool_read_blocked=True)
        events=[json.loads(line) for line in (run/"audit-events.jsonl").read_text().split("\n") if line.strip()]
        init=next(r for r in events if r.get("subtype")=="init")
        expected=[]
        if native_skill_set is not None:
            from kojo.skill_sets import describe
            expected=["kojo-selected:"+s["name"] for s in describe(native_skill_set)["skills"]]
        if set(init.get("skills",[])) != set(expected) or init.get("mcp_servers"):
            raise RuntimeError(f"Unexpected native skills: {init.get('skills')}; expected {expected}")
        if not expected and native_skill_set is None and init.get("slash_commands"):
            raise RuntimeError("Unexpected slash commands")
        if native_skill_set is not None:
            unexpected=[p for p in init.get("plugins",[]) if p.get("path") != "builtin" and
                        (p.get("name") != "kojo-selected" or p.get("path") != str(work/".claude"))]
            if unexpected:raise RuntimeError("Unexpected ambient plugin")
            if any(name not in json.dumps(candidates[0]) for name in expected):
                raise RuntimeError("Native skill catalog missing from model request")
        receipt["native_skills"]=expected
        receipt["cli_version"]=VERSION
        receipt["customization_canary_absent"]=True
        receipt["network_smoke"]= "PyPI HTTPS metadata reachable" if network_enabled else "not requested"
        capture(run,run/"audit-config",init["session_id"],prompt,model,effort)

        save(run/"audit-request.json",candidates[0])
        save(run/"verification.json",receipt)
        (run/"stock-instructions.md").write_text(stock)
        return receipt
    finally:
        if p is not None and p.poll() is None:
            os.killpg(p.pid,signal.SIGKILL);p.wait()
        server.shutdown();server.server_close()
        smoke_path.unlink(missing_ok=True)


def capture(run, config, session_id, prompt, model, effort):
    matches=list((config/"projects").glob(f"*/{session_id}.jsonl"))
    if len(matches)!=1:
        raise RuntimeError("Missing or ambiguous native Claude transcript")
    shutil.copy2(matches[0],run/"transcript.jsonl")
    return verify_saved_transcript(run, session_id, prompt, model, effort)


def verify_saved_transcript(run, session_id, prompt, model, effort):
    # JSONL is LF-delimited. Unicode separators inside strings are valid JSON.
    rows=[json.loads(line) for line in (run/"transcript.jsonl").read_text().split("\n") if line.strip()]
    prompts=[r.get("message",{}).get("content") for r in rows if r.get("type")=="user"]
    if prompt not in prompts:
        raise RuntimeError("Exact user prompt absent from native transcript")
    snapshots=[r["attachment"] for r in rows if r.get("attachment",{}).get("type")=="prompt_snapshot"]
    if not snapshots or not snapshots[0].get("systemPrompt"):
        raise RuntimeError("Native stock system-prompt snapshot missing")
    stock="\n".join(snapshots[0]["systemPrompt"])
    (run/"stock-instructions.md").write_text(stock)
    assistants=[r for r in rows if r.get("type")=="assistant" and r.get("message",{}).get("model") != "<synthetic>"]
    if any(r.get("message",{}).get("model")!=model or r.get("effort")!=effort for r in assistants):
        raise RuntimeError("Native transcript model/effort differs from configuration")
    receipt={"session_id":session_id,"provider":"claude","model":model,"reasoning":effort,
             "exact_user_prompt":True,"stock_prompt_snapshot":True,
             "transcript_sha256":hashlib.sha256((run/"transcript.jsonl").read_bytes()).hexdigest()}
    save(run/"transcript-verification.json",receipt)
    return receipt


def usage_from_result(result):
    raw=result.get("usage")
    if raw is None:return None
    return {"input_tokens":sum(raw.get(k,0) for k in ("input_tokens","cache_read_input_tokens","cache_creation_input_tokens")),
            "cached_input_tokens":raw.get("cache_read_input_tokens",0),
            "cache_creation_input_tokens":raw.get("cache_creation_input_tokens",0),
            "output_tokens":raw.get("output_tokens",0),
            "reasoning_output_tokens":raw.get("output_tokens_details",{}).get("thinking_tokens")}


def run_session(run, instructions, prompt, seconds, runtime=None, skill=None,
                prior_observations=(), isolated_src=True, capture_transcript=True,
                model=MODELS[0], monitor_only=False, work_path=None,
                network_enabled=True, effort="high", max_budget_usd=None, max_output_tokens=None, native_skill_set=None):
    run=Path(run).resolve()
    if (run/"run.json").exists():raise RuntimeError("Attempt already exists; no implicit retry")
    if not isolated_src or not capture_transcript:raise ValueError("Claude requires isolation and transcript capture")
    work=Path(work_path).resolve() if work_path else run/"src"
    audit(run,instructions,runtime,skill,True,prompt,model=model,work_path=work,
          network_enabled=network_enabled,effort=effort,max_budget_usd=max_budget_usd,max_output_tokens=max_output_tokens,native_skill_set=native_skill_set)
    session_id=str(uuid.uuid4())
    cmd=command(run,work,model,effort,session_id,network_enabled,max_budget_usd,native_skill_set)
    env=environment(effort,max_output_tokens=max_output_tokens,model=model)
    if native_skill_set is not None:env["CLAUDE_CODE_DISABLE_CLAUDE_MDS"]="1"
    started=time.monotonic();process=None
    row={"status":"started","provider":"claude","cli_version":VERSION,"model":model,
         "reasoning":effort,"fresh_conversation":True,"session_id":session_id,
         "max_seconds":seconds,"network_enabled":network_enabled,
         "max_budget_usd":max_budget_usd,"max_output_tokens_override":max_output_tokens,
         "quota_policy":"Claude subscription usage is separate; Codex quota is not applicable",
         "skill_sha256":hashlib.sha256(b"").hexdigest()}
    if native_skill_set is not None:
        from kojo.skill_sets import describe
        row["native_skill_set"]=describe(native_skill_set)
        row["skill_sha256"]=row["native_skill_set"]["sha256"]
    save(run/"run.json",row);save(run/"quota.json",[])
    try:
        with (run/"events.jsonl").open("w") as out,(run/"stderr.log").open("w") as err:
            process=subprocess.Popen(cmd,cwd=work,env=env,stdin=subprocess.PIPE,
                                     stdout=out,stderr=err,text=True,start_new_session=True)
            try:
                process.communicate(prompt,timeout=seconds)
                row["status"]="complete" if process.returncode==0 else "cli_failure"
            except subprocess.TimeoutExpired:
                os.killpg(process.pid,signal.SIGKILL);process.wait()
                row["status"]="budget_exhausted"
            row["returncode"]=process.returncode
    except BaseException:
        row["status"]="interrupted"
        if process and process.poll() is None:
            os.killpg(process.pid,signal.SIGKILL);process.wait()
        raise
    finally:
        row["elapsed_seconds"]=time.monotonic()-started
        events=[]
        if (run/"events.jsonl").exists():
            for line in (run/"events.jsonl").read_text().split("\n"):
                try:events.append(json.loads(line))
                except ValueError:pass  # Abrupt timeout can truncate the final record.
        result=next((r for r in reversed(events) if r.get("type")=="result"),{})
        row["usage"]=usage_from_result(result)
        row["api_price_equivalent_usd"]=result.get("total_cost_usd")
        row["provider_usage"]=result.get("usage")
        if result.get("subtype")=="error_max_budget_usd":row["status"]="budget_exhausted"
        elif result.get("is_error"):row["status"]="cli_failure"
        if row["status"]=="cli_failure":
            row["failure_detail"]=result.get("result") or result.get("errors") or "CLI exited unsuccessfully; see events.jsonl"
        if result.get("result"):(run/"answer.txt").write_text(result["result"])
        try:
            row["transcript"]=capture(run,Path(env.get("CLAUDE_CONFIG_DIR",str(Path.home()/".claude"))),
                                      session_id,prompt,model,effort)
        except Exception as error:row["transcript_error"]=str(error)
        save(run/"run.json",row)
    if row.get("transcript_error"):raise RuntimeError(row["transcript_error"])
    if row["status"]=="cli_failure":raise RuntimeError("Claude CLI failure; inspect before resuming")
    return row


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action",choices=["audit"])
    parser.add_argument("--run-dir",type=Path,required=True)
    parser.add_argument("--model",choices=MODELS,default=MODELS[0])
    parser.add_argument("--effort",choices=EFFORTS,default="high")
    args=parser.parse_args()
    receipt=audit(args.run_dir.resolve(),model=args.model,effort=args.effort)
    print(json.dumps(receipt,indent=2))


if __name__=="__main__":main()
