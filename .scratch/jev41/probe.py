#!/usr/bin/env python3
"""JEV-41 probe: run the cc_* arm argv under variant thinking configs."""
import json, os, subprocess, sys, time, shutil
ROOT="/Users/aadharagarwal/projects/JEV-experiments"
sys.path.insert(0, ROOT+"/src")
import paths  # noqa
from arms.claude import build_prompt, build_schema
import config_loader as cl
from arms.claude_cli import SYSTEM, DISALLOWED

def argv_for(model, effort, extra=(), state=None):
    questions = cl.questions_for("pre_bash")
    schema = build_schema(questions)
    if state is None:
        state = "Command:\ngit push --force origin main\n\nWorking directory: /repo"
    prompt = build_prompt(state, questions)
    a=[shutil.which("claude"), "-p", prompt, "--model", model,
       "--output-format","json","--json-schema",json.dumps(schema),
       "--system-prompt",SYSTEM,"--strict-mcp-config","--mcp-config",'{"mcpServers":{}}',
       "--no-session-persistence","--disallowed-tools",DISALLOWED]
    if effort: a += ["--effort", effort]
    a += list(extra)
    return a

def run(label, model, effort, extra=(), env_extra=None, debug_file=None, state=None):
    env=dict(os.environ); env["JEV_ARM_SUBPROCESS"]="1"; env.pop("ANTHROPIC_API_KEY",None)
    if env_extra: env.update(env_extra)
    a=argv_for(model,effort,extra,state)
    if debug_file: a += ["--debug","api","--debug-file",debug_file]
    t=time.perf_counter()
    p=subprocess.run(a,capture_output=True,text=True,timeout=300,env=env,cwd=ROOT)
    wall=(time.perf_counter()-t)*1000
    out={"label":label,"rc":p.returncode,"wall_ms":round(wall)}
    try:
        b=json.loads(p.stdout)
    except Exception:
        out["stdout"]=p.stdout[:800]; out["stderr"]=p.stderr[:800]; return out
    u=b.get("usage") or {}
    out.update(dict(
        subtype=b.get("subtype"), is_error=b.get("is_error"),
        result=str(b.get("result"))[:200] if b.get("is_error") else None,
        api_ms=b.get("duration_api_ms"), turns=b.get("num_turns"),
        out_tok=u.get("output_tokens"), think=(u.get("output_tokens_details") or {}).get("thinking_tokens"),
        cache_read=u.get("cache_read_input_tokens"), cache_write=u.get("cache_creation_input_tokens"),
        inp=u.get("input_tokens"),
        model=next(iter(b.get("modelUsage") or {}), None),
        so=b.get("structured_output"),
    ))
    return out

if __name__=="__main__":
    print(json.dumps(run(*json.loads(sys.argv[1])), indent=1) if False else "")
