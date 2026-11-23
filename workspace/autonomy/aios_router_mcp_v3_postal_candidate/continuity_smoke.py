"""Bounded read-only MCP candidate test; never supplies mutation authority."""
import hashlib
import json
import queue
import subprocess
import threading
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path('L:/LocalCoder')
SOURCE = '/mnt/l/LocalCoder/workspace/autonomy/aios_router_mcp_v3_postal_candidate/src'


def main():
    authorized='--authorized' in sys.argv
    command = ['wsl.exe', '--distribution', 'Ubuntu', '--exec', 'docker', '--context', 'default',
               'run', '--rm', '--interactive', '--network=none',
               '--mount', f'type=bind,source={SOURCE},target=/build/src,readonly',
               '--mount', 'type=bind,source=/mnt/l/LocalCoder/workspace/aios_rebuild/memory/aios_router,target=/var/lib/aios-router,readonly',
               '--mount', 'type=bind,source=/mnt/l/LocalCoder/.opencode/receipts,target=/var/lib/aios-body-receipts,readonly',
               '--mount', 'type=bind,source=/mnt/f/AI_Datasets/domain_dbs,target=/var/lib/aios-wikipedia,readonly',
               'e43a1a5bd1a2', 'sh', '-c',
               'cargo build --locked --offline >&2 && exec target/debug/aios-router-mcp-v3-postal-candidate']
    if authorized:
        index=command.index('type=bind,source=/mnt/l/LocalCoder/workspace/aios_rebuild/memory/aios_router,target=/var/lib/aios-router,readonly')
        command[index]=command[index].removesuffix(',readonly')
    p = subprocess.Popen(command, cwd=ROOT, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                         stderr=subprocess.PIPE, text=True, encoding='utf-8')
    q, errors, records = queue.Queue(), [], []
    def read():
        for line in p.stdout: q.put(line)
        q.put(None)
    def stderr():
        for line in p.stderr: errors.append(line)
    threading.Thread(target=read, daemon=True).start()
    threading.Thread(target=stderr, daemon=True).start()
    def send(o):
        p.stdin.write(json.dumps(o)+'\n'); p.stdin.flush()
    def request(i, method, params):
        send({'jsonrpc':'2.0', 'id':i, 'method':method, 'params':params})
        while True:
            line=q.get(timeout=60)
            if line is None: raise RuntimeError('MCP exited: '+''.join(errors)[-3000:])
            obj=json.loads(line); records.append(obj)
            if obj.get('id')==i: return obj
    result={'scope':'candidate MCP source; live DB mounted read-only; actual F-drive Wikipedia mounted read-only'}
    try:
        result['initialize']=request(1,'initialize',{'protocolVersion':'2024-11-05','capabilities':{},'clientInfo':{'name':'continuity-readonly-smoke','version':'1'}})
        send({'jsonrpc':'2.0','method':'notifications/initialized'})
        result['catalog']=request(2,'tools/list',{})
        names=[t['name'] for t in result['catalog']['result']['tools']]
        assert all(n in names for n in ['memory_checkpoint','memory_retrieve','memory_stm'])
        result['denied_checkpoint']=request(3,'tools/call',{'name':'memory_checkpoint','arguments':{'session_id':'continuity-denied-probe','compaction_id':'denied','summary':'Must never persist without authority','previous_assistant':'','previous_user':''}})
        denied=json.loads(result['denied_checkpoint']['result']['content'][0]['text'])
        assert denied['ok'] is False and 'no fresh Body ALLOW' in denied['error'],denied
        result['wiki']=request(4,'tools/call',{'name':'memory_retrieve','arguments':{'session_id':'continuity-denied-probe','query':'Python','limit':2}})
        wiki=json.loads(result['wiki']['result']['content'][0]['text'])
        assert wiki['ok'] is True,wiki
        assert wiki['result']['order']==['ltm','stm','wikipedia'],wiki
        assert len(wiki['result']['matches'])>0,wiki
        if authorized:
            from continuity_authority import authorize,canonical
            stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
            checkpoint={'session_id':'continuity-positive-'+stamp,'compaction_id':'test-checkpoint-'+stamp,
                        'summary':'Bounded integration test: continuity checkpoint saved with real Rust Body and PrivacyCore authority. Probe token ContinuityProbe'+stamp,
                        'previous_assistant':'The candidate denied an ungated checkpoint and retrieved actual Wikipedia articles.',
                        'previous_user':'Continue until the STM/LTM foundation works as designed.'}
            result['authority']=authorize(checkpoint)
            result['checkpoint']=request(5,'tools/call',{'name':'memory_checkpoint','arguments':checkpoint})
            saved=json.loads(result['checkpoint']['result']['content'][0]['text'])
            assert saved['ok'] is True,saved
            assert saved['result']['sha256']==hashlib.sha256(canonical(checkpoint)).hexdigest(),saved
            result['stm']=request(6,'tools/call',{'name':'memory_stm','arguments':{'session_id':checkpoint['session_id']}})
            stm=json.loads(result['stm']['result']['content'][0]['text'])
            assert checkpoint['summary'] in stm['result']['checkpoint']['stm'],stm
            assert checkpoint['previous_assistant'] in stm['result']['checkpoint']['stm'],stm
            assert checkpoint['previous_user'] in stm['result']['checkpoint']['stm'],stm
            result['cross_session']=request(7,'tools/call',{'name':'memory_retrieve','arguments':{'session_id':'fresh-session-'+stamp,'query':'ContinuityProbe'+stamp,'limit':2}})
            found=json.loads(result['cross_session']['result']['content'][0]['text'])
            assert found['result']['order']==['ltm'],found
            assert found['result']['result']['matches'][0]['sha256']==saved['result']['sha256'],found
        result['result']='PASS'
    except Exception as e:
        result['result']='FAIL'; result['error']=repr(e)
    finally:
        p.stdin.close()
        try: p.wait(timeout=5)
        except subprocess.TimeoutExpired: p.terminate(); p.wait(timeout=5)
        result['records']=records; result['stderr']=errors; result['exit']=p.returncode
        path=ROOT/'.opencode/evals'/('continuity-mcp-smoke-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'.json')
        path.write_text(json.dumps(result,indent=2),encoding='utf-8')
        print(json.dumps({'result':result['result'],'evidence':str(path),'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'error':result.get('error'),'exit':p.returncode}))
    return 0 if result['result']=='PASS' else 1


if __name__=='__main__': raise SystemExit(main())
