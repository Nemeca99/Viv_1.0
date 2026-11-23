"""Bounded stdio client of the configured existing MCP. No SQL writes here."""
import json
import queue
import subprocess
import sys
import threading
from pathlib import Path
from continuity_authority import authorize

ROOT=Path('L:/LocalCoder')
METHODS={'checkpoint':'memory_checkpoint','working':'memory_working','retrieve':'memory_retrieve','stm':'memory_stm','checkpoint_read':'memory_checkpoint_read'}


def call(operation,arguments):
    if operation not in METHODS: raise ValueError('unsupported continuity operation')
    config=json.loads((ROOT/'opencode.json').read_text(encoding='utf-8-sig'))
    command=config['mcp']['servers']['aios_router']['command']
    p=subprocess.Popen(command,cwd=ROOT,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,encoding='utf-8')
    q=queue.Queue(); errors=[]
    def read():
        for line in p.stdout:q.put(line)
        q.put(None)
    def stderr():
        for line in p.stderr:errors.append(line)
    threading.Thread(target=read,daemon=True).start()
    threading.Thread(target=stderr,daemon=True).start()
    def send(o):p.stdin.write(json.dumps(o)+'\n');p.stdin.flush()
    def request(i,method,params):
        send({'jsonrpc':'2.0','id':i,'method':method,'params':params})
        while True:
            try:line=q.get(timeout=40)
            except queue.Empty:raise TimeoutError('Configured MCP did not answer '+method+' '+str(params.get('name',''))+' within 40 seconds')
            if line is None:raise RuntimeError('configured MCP exited: '+''.join(errors)[-2000:])
            v=json.loads(line)
            if v.get('id')==i:
                if 'error' in v:raise RuntimeError(json.dumps(v['error']))
                return v['result']
    try:
        request(1,'initialize',{'protocolVersion':'2024-11-05','capabilities':{},'clientInfo':{'name':'localcoder-continuity-bridge','version':'1'}})
        send({'jsonrpc':'2.0','method':'notifications/initialized'})
        names=[t['name'] for t in request(2,'tools/list',{})['tools']]
        if METHODS[operation] not in names:raise RuntimeError('configured MCP lacks '+METHODS[operation])
        authority=authorize(arguments) if operation in ('checkpoint','working') else None
        reply=request(3,'tools/call',{'name':METHODS[operation],'arguments':arguments})
        if reply.get('isError'):raise RuntimeError(json.dumps(reply))
        data=json.loads(reply['content'][0]['text'])
        if data.get('ok') is not True:raise RuntimeError(json.dumps(data))
        return {'ok':True,'result':data['result'],'authority':authority}
    finally:
        p.stdin.close()
        try:p.wait(timeout=5)
        except subprocess.TimeoutExpired:p.terminate();p.wait(timeout=5)


if __name__=='__main__':
    try:
        request=json.loads(sys.stdin.buffer.read(1024*1024+1))
        print(json.dumps(call(request['operation'],request['arguments']),ensure_ascii=False))
    except Exception as error:
        print(json.dumps({'ok':False,'error':str(error)}));raise SystemExit(1)
