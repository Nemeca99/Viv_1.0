"""Bounded temporary local OpenCode server; keep diagnostics and data on L:."""
import base64,json,os,pathlib,secrets,subprocess,threading,time,urllib.request,urllib.parse
ROOT=pathlib.Path('L:/LocalCoder')
EXE=pathlib.Path(os.environ['APPDATA'])/'npm/node_modules/@opencode/cli/bin/opencode.exe'
token=secrets.token_hex(24)
env=dict(os.environ,OPENCODE_PASSWORD=token)
env['LOCALCODER_TRACE_LLM']='1'
env['LOCALCODER_TRACE_LLM_PATH']=str(ROOT/'.opencode/evals/continuity-api-provider-tools.jsonl')
p=subprocess.Popen([str(EXE),'serve','--port','28895','--hostname','127.0.0.1'],cwd=ROOT,env=env,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,encoding='utf-8')
logs=[]
def read(stream):
    for line in stream:logs.append(line.replace(token,'[redacted]'))
threading.Thread(target=read,args=(p.stdout,),daemon=True).start()
threading.Thread(target=read,args=(p.stderr,),daemon=True).start()
auth='Basic '+base64.b64encode(('opencode:'+token).encode()).decode()
def api(path,body=None):
    req=urllib.request.Request('http://127.0.0.1:28895'+path,data=None if body is None else json.dumps(body).encode(),headers={'Authorization':auth,'Content-Type':'application/json'})
    with urllib.request.urlopen(req,timeout=50) as r:
        raw=r.read();return json.loads(raw) if raw else None
def wait_session(session_id):
    for observation in range(6):
        try:return api('/api/experimental/session/'+session_id+'/wait',{})
        except TimeoutError:
            if p.poll() is not None:raise RuntimeError('test server exited while observing session')
    raise RuntimeError('bounded test deadline exceeded while session was still running')
result={}
try:
    for _ in range(20):
        if p.poll() is not None:raise RuntimeError('temporary server exited')
        try: result['info']=api('/api/info');break
        except urllib.error.URLError:time.sleep(.5)
    location=urllib.parse.urlencode({'location[directory]':str(ROOT)})
    result['mcp']=api('/api/mcp?'+location)
    session_id='ses_e124de4e7ffepxEOYPcW9qv0L4'
    result['session']=api('/api/session/'+session_id)
    result['context_before']=api('/api/session/'+session_id+'/context')
    result['prompt']=api('/api/session/'+session_id+'/prompt',{'text':'[ARCHITECT ASSIGNMENT | CURRENT AND AUTHORIZED]\nTask access: read\nUse the aios_router_memory_retrieve tool with session_id current-session, query ContinuityProbe20261118T075059Z, limit 1. Report its actual returned source and hash, then stop.'})
    result['prompt_wait']=wait_session(session_id)
    result['context_after_prompt']=api('/api/session/'+session_id+'/context')
    completed=[]
    for message in result['context_after_prompt'].get('data',[]):
        for part in message.get('content',[]) if isinstance(message.get('content'),list) else []:
            if part.get('type')=='tool' and part.get('name')=='aios_router_memory_retrieve' and part.get('state',{}).get('status')=='completed':completed.append(part)
    result['completed_memory_retrievals']=completed
    if not completed:raise AssertionError('No completed memory_retrieve call; model prose does not prove execution')
    result['compact']=api('/api/session/'+session_id+'/compact',{})
    result['wait']=wait_session(session_id)
    result['context_after']=api('/api/session/'+session_id+'/context')
    result['mcp_after']=api('/api/mcp?'+location)
    result['plugins']=api('/api/plugin?'+location)
    result['result']='OBSERVED'
except Exception as e: result['error']=repr(e)
finally:
    p.terminate()
    try:p.wait(timeout=5)
    except subprocess.TimeoutExpired:p.kill();p.wait()
    result['logs']=logs
    out=ROOT/'.opencode/evals'/('opencode-live-api-probe-'+str(int(time.time()))+'.json')
    out.write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps({'evidence':str(out),'mcp':result.get('mcp_after',result.get('mcp')),'plugin_ids':[x.get('id') for x in result.get('plugins',{}).get('data',[])],'error':result.get('error')}))
