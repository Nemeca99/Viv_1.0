"""Relay actual isolated Rust verification results; never manufacture a verdict."""
import json,sys,subprocess,threading,queue,uuid,os
from pathlib import Path
from datetime import datetime,timezone

ROOT=Path('L:/LocalCoder'); WORKSPACE=ROOT/'workspace'; PYTHON='L:/.venv/Scripts/python.exe'
sys.path.insert(0,str(WORKSPACE));sys.path.insert(0,str(WORKSPACE/'autonomy'))
from privacy_core_router_db_gate_queen_v1_candidate import router_db_decision
from aios_rebuild.privacy_core.privacy_core import PrivacyCore

class Mcp:
    def __init__(self,command):
        self.p=subprocess.Popen(command,cwd=ROOT,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,encoding='utf-8')
        self.q=queue.Queue();self.errors=[];self.counter=0
        def read():
            for line in self.p.stdout:self.q.put(line)
            self.q.put(None)
        def error():
            for line in self.p.stderr:self.errors.append(line)
        threading.Thread(target=read,daemon=True).start();threading.Thread(target=error,daemon=True).start()
        self.request('initialize',{'protocolVersion':'2024-11-05','capabilities':{},'clientInfo':{'name':'completion-authority','version':'1'}})
        self.send({'jsonrpc':'2.0','method':'notifications/initialized'})
    def send(self,v):self.p.stdin.write(json.dumps(v)+'\n');self.p.stdin.flush()
    def request(self,method,params):
        self.counter+=1; wanted=self.counter;self.send({'jsonrpc':'2.0','id':wanted,'method':method,'params':params})
        while True:
            line=self.q.get(timeout=110)
            if line is None:raise RuntimeError('MCP exited: '+''.join(self.errors)[-1500:])
            data=json.loads(line)
            if data.get('id')==wanted:
                if 'error' in data:raise RuntimeError(json.dumps(data['error']))
                return data['result']
    def call(self,name,args):
        r=self.request('tools/call',{'name':name,'arguments':args})
        if r.get('isError'):raise RuntimeError(json.dumps(r))
        data=json.loads(r['content'][0]['text'])
        if data.get('ok') is not True:raise RuntimeError(json.dumps(data))
        return data['result']
    def close(self):
        self.p.stdin.close()
        try:self.p.wait(timeout=5)
        except subprocess.TimeoutExpired:self.p.terminate();self.p.wait(timeout=5)

def execute(contract,image):
    name='completion-check-'+uuid.uuid4().hex
    command=['wsl.exe','--distribution','Ubuntu','--exec','docker','--context','default','run','--rm','--interactive','--name',name,
             '--pull=never','--network=none','--read-only','--cap-drop=ALL','--security-opt=no-new-privileges:true','--user=10001:10001',
             '--memory=512m','--memory-swap=512m','--cpus=1','--pids-limit=32','--tmpfs','/tmp:rw,nosuid,nodev,noexec,size=64m,mode=1777',
             '--mount','type=bind,source=/mnt/l/LocalCoder,target=/var/lib/aios-project,readonly',image,'--verify-contract']
    try:
        run=subprocess.run(command,input=json.dumps(contract,ensure_ascii=False,separators=(',',':')),capture_output=True,text=True,encoding='utf-8',timeout=110)
    except subprocess.TimeoutExpired:
        subprocess.run(['wsl.exe','--distribution','Ubuntu','--exec','docker','--context','default','kill',name],capture_output=True,timeout=10)
        raise RuntimeError('isolated Rust verifier exceeded its bounded deadline')
    if run.returncode:raise RuntimeError('Rust verifier process failed: '+run.stderr[-1500:])
    reply=json.loads(run.stdout)
    if reply.get('ok') is not True:raise RuntimeError('Rust verifier rejected contract: '+json.dumps(reply))
    return reply['result']

def authorize(tool,session,verification=None):
    body=None
    for attempt in range(2):
        run=subprocess.run([PYTHON,'-B','-m','aios_rebuild.main_core.mind_runtime_gate','--goal-id','01a1e340-84ed-77c3-92f3-3eb738b89f5b'],cwd=WORKSPACE,capture_output=True,text=True,timeout=25)
        body=json.loads(run.stdout)
        if attempt==0 and body.get('reasons')==['wsl_body_request_timed_out']:continue
        break
    if body.get('allowed') is not True or body.get('authority')!='deterministic_aios_body_rust' or body.get('disposition')!='ALLOW_MIND_RUNTIME':raise PermissionError('Rust Body denied completion operation: '+json.dumps(body))
    os.chdir(ROOT); privacy=router_db_decision()
    if privacy.get('allowed') is not True:raise PermissionError('PrivacyCore denied router write: '+json.dumps(privacy))
    receipt={'schema':'opencode_body_gate_receipt_v1','source':'tool:'+tool,'session_id':session,
             'authority':body['authority'],'disposition':body['disposition'],'allowed':body['allowed'],
             'body_verdict':body,'privacy_core':privacy,'captured_at':datetime.now(timezone.utc).isoformat(timespec='milliseconds').replace('+00:00','Z')}
    if verification is not None:receipt['verification']=verification
    path=ROOT/'.opencode/receipts'/('completion-'+uuid.uuid4().hex+'-body-gate.json')
    if PrivacyCore().authorize_file_write(str(path)).get('allowed') is not True:raise PermissionError('PrivacyCore denied receipt')
    with path.open('x',encoding='utf-8') as stream:
        json.dump(receipt,stream,ensure_ascii=False,separators=(',',':'));stream.flush();os.fsync(stream.fileno())
    return path.name

def prepare(tool,binding,config=None):
    if tool not in ('aios_router_verify_task','aios_router_complete_lane'):raise ValueError('unsupported completion operation')
    if set(binding)!={'session_id','task_id','assignment_hash'}:raise ValueError('exact task binding required')
    cfg=config or json.loads((ROOT/'opencode.json').read_text(encoding='utf-8-sig'))
    command=cfg['mcp']['servers']['aios_router']['command'];channel=Mcp(command)
    try:frozen=channel.call('acceptance_contract',binding)
    finally:channel.close()
    verdict=execute(frozen['contract'],command[-1])
    if verdict['contract_sha256']!=frozen['contract_sha256']:raise RuntimeError('frozen contract changed before execution')
    return {'receipt_id':authorize(tool,binding['session_id'],verdict),'verification':verdict}

if __name__=='__main__':
    try:
        r=json.loads(sys.stdin.buffer.read(65537));print(json.dumps(prepare(r['tool'],r['binding'])))
    except Exception as error:print(json.dumps({'ok':False,'error':str(error)}));raise SystemExit(1)
