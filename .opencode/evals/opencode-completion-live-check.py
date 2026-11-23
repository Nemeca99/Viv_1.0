"""Verify the actual translation frontend -> isolated Rust -> completion gate."""
import base64,json,os,pathlib,secrets,subprocess,threading,time,urllib.request,urllib.parse
ROOT=pathlib.Path('L:/LocalCoder'); token=secrets.token_hex(24)
EXE=pathlib.Path(os.environ['APPDATA'])/'npm/node_modules/@opencode/cli/bin/opencode.exe'
env=dict(os.environ,OPENCODE_PASSWORD=token,LOCALCODER_TRACE_LLM='1',LOCALCODER_TRACE_LLM_PATH=str(ROOT/'.opencode/evals/completion-opencode-provider-trace.jsonl'))
process=subprocess.Popen([str(EXE),'serve','--port','28895','--hostname','127.0.0.1'],cwd=ROOT,env=env,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,encoding='utf-8')
logs=[]
def read(stream):
    for line in stream:logs.append(line.replace(token,'[redacted]'))
threading.Thread(target=read,args=(process.stdout,),daemon=True).start();threading.Thread(target=read,args=(process.stderr,),daemon=True).start()
auth='Basic '+base64.b64encode(('opencode:'+token).encode()).decode()
def api(path,body=None,timeout=50):
    request=urllib.request.Request('http://127.0.0.1:28895'+path,data=None if body is None else json.dumps(body).encode(),headers={'Authorization':auth,'Content-Type':'application/json'})
    with urllib.request.urlopen(request,timeout=timeout) as response:
        raw=response.read();return json.loads(raw) if raw else None
contract={'version':1,'kind':'artifacts','artifacts':['.opencode/evals/completion-fixture/value.txt','.opencode/evals/completion-fixture/check.py'],
          'checks':[{'id':'behavior-and-readonly-scope','argv':['/usr/local/bin/python','-B','.opencode/evals/completion-fixture/check.py'],'timeout_seconds':5,'inputs':['.opencode/evals/completion-fixture/check.py']}]}
assignment='[ARCHITECT ASSIGNMENT | CURRENT AND AUTHORIZED]\nTask access: write\nRouter bounds JSON: {"task_class":"build","lane_ids":["drone"],"max_turns_per_lane":1}\nAcceptance JSON: '+json.dumps(contract,separators=(',',':'))+'\nBounded control and verification test of existing artifacts. No source edits. Use aios_router_open_build_task. Then use aios_router_accept_self_prompt for lane drone turn 0 with Agenda, Verified facts, Next bounded action. Then use aios_router_record_turn_result for lane drone turn 0: artifacts are ready for deterministic verification, no success is claimed yet. Then use aios_router_complete_lane for lane drone with a nonempty receipt; Rust must run the frozen checks. Finally use aios_router_queen_summary and report the actual state and verification hash, then stop. The frontend supplies trusted session/task/assignment bindings.'
result={'assignment':assignment,'contract':contract,'observations':[]}
try:
    for _ in range(20):
        if process.poll() is not None:raise RuntimeError('temporary OpenCode server exited')
        try:api('/api/info');break
        except urllib.error.URLError:time.sleep(.5)
    session=api('/api/session',{'location':{'directory':str(ROOT)},'title':'Bounded Rust completion gate check','agent':'build','model':{'providerID':'lmstudio','id':'omnicoder-2-9b'}})['data']
    sid=session['id'];result['session']=session
    result['prompt']=api('/api/session/'+sid+'/prompt',{'text':assignment})
    deadline=time.monotonic()+420
    while time.monotonic()<deadline:
        if any('blocked out-of-order tool' in line for line in logs):raise RuntimeError('Deterministic frontend tool-order guard stopped the test')
        try:api('/api/experimental/session/'+sid+'/wait',{},timeout=40)
        except (TimeoutError,ConnectionAbortedError,ConnectionResetError,urllib.error.URLError):
            if process.poll() is not None:raise RuntimeError('test server exited while observing its session')
            result['observations'].append('same live session still running after observation timeout')
        context=api('/api/session/'+sid+'/context');result['context']=context
        completed=[]
        for message in context.get('data',[]):
            for part in message.get('content',[]) if isinstance(message.get('content'),list) else []:
                if part.get('type')=='tool' and part.get('state',{}).get('status')=='completed':completed.append(part)
        summaries=[p for p in completed if p['name']=='aios_router_queen_summary']
        if summaries:
            summary=json.loads(summaries[-1]['state']['content'][0]['text']);result['summary']=summary
            assert summary['ok'] is True and summary['result']['state']=='completed',summary
            assert summary['result']['verification']['verified'] is True,summary
            finishes=[p for p in completed if p['name']=='aios_router_complete_lane']
            finish=json.loads(finishes[-1]['state']['content'][0]['text']);result['completion']=finish
            assert finish['ok'] is True and finish['result']['task_verified'] is True,finish
            assert finish['result']['verification']['evidence']['checks'][0]['exit_code']==0,finish
            result['result']='PASS';break
        errors=[m for m in context.get('data',[]) if m.get('type')=='error' or (m.get('type')=='idle' and m.get('outcome')=='failed' and m.get('error'))]
        for message in context.get('data',[]):
            for part in message.get('content',[]) if isinstance(message.get('content'),list) else []:
                if part.get('type')=='tool' and part.get('state',{}).get('status')=='error':errors.append(part)
        if errors:raise RuntimeError(json.dumps(errors))
        result['observations'].append({'completed_tools':[p['name'] for p in completed]})
        time.sleep(.5)
    else:raise RuntimeError('bounded test deadline reached without a verified summary')
except Exception as error:result['result']='FAIL';result['error']=repr(error)
finally:
    process.terminate()
    try:process.wait(timeout=5)
    except subprocess.TimeoutExpired:process.kill();process.wait()
    result['logs']=logs
    out=ROOT/'.opencode/evals'/('opencode-completion-live-'+str(int(time.time()))+'.json')
    out.write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps({'result':result.get('result'),'evidence':str(out),'error':result.get('error')}))
raise SystemExit(0 if result.get('result')=='PASS' else 1)
