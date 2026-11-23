"""Exact-target adapter to the existing Rust Body and PrivacyCore authorities."""
import hashlib
import json
import subprocess
import sys
import os
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

ROOT=Path('L:/LocalCoder')
WORKSPACE=ROOT/'workspace'
sys.path.insert(0,str(WORKSPACE))
from aios_rebuild.privacy_core.privacy_core import PrivacyCore

TARGET=WORKSPACE/'aios_rebuild/memory/aios_router/continuity.sqlite3'
PYTHON=Path('L:/.venv/Scripts/python.exe')
FIELDS=('session_id','compaction_id','summary','previous_assistant','previous_user')


def canonical(checkpoint):
    if set(checkpoint)=={'session_id','context_id','content'}:
        if not all(isinstance(v,str) for v in checkpoint.values()): raise ValueError('working context fields must be strings')
        return json.dumps(checkpoint,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode('utf-8')
    if set(checkpoint)!=set(FIELDS) or not all(isinstance(checkpoint[k],str) for k in FIELDS):
        raise ValueError('exact checkpoint fields required')
    # Match serde's struct field order and compact UTF-8 encoding exactly.
    return json.dumps({k:checkpoint[k] for k in FIELDS},ensure_ascii=False,separators=(',',':')).encode('utf-8')


def authorize(checkpoint):
    payload=canonical(checkpoint)
    if not checkpoint['session_id'].strip() or len(payload)>1024*1024:
        raise ValueError('invalid checkpoint size or session')
    command=[str(PYTHON),'-B','-m','aios_rebuild.main_core.mind_runtime_gate','--goal-id','01a1e340-84ed-77c3-92f3-3eb738b89f5b']
    body=None
    for attempt in range(2):
        run=subprocess.run(command,cwd=WORKSPACE,capture_output=True,text=True,timeout=25)
        body=json.loads(run.stdout)
        if attempt==0 and body.get('reasons')==['wsl_body_request_timed_out']:
            continue
        break
    if not(body.get('allowed') is True and body.get('authority')=='deterministic_aios_body_rust'
           and body.get('disposition')=='ALLOW_MIND_RUNTIME'):
        raise PermissionError('Rust Body denied continuity write: '+json.dumps(body))
    # The existing memory writer runs PrivacyCore from the authorized project
    # root, encompassing both workspace data and .opencode authority receipts.
    os.chdir(ROOT)
    core=PrivacyCore()
    checked=[]
    for path in [TARGET,*[Path(str(TARGET)+suffix) for suffix in ('-wal','-shm','-journal')]]:
        raw=core.authorize_file_write(str(path))
        if raw.get('allowed') is not True or not isinstance(raw.get('reason'),str):
            raise PermissionError('PrivacyCore denied '+str(path)+': '+json.dumps(raw))
        checked.append({'path':str(path),'raw':raw})
    privacy={'schema':'continuity_privacy_decision_v1','authority':'PrivacyCore.authorize_file_write',
             'target_path':str(TARGET),'allowed':True,'checked_paths':checked}
    tool='memory_checkpoint' if 'compaction_id' in checkpoint else 'memory_working'
    receipt={'schema':'opencode_body_gate_receipt_v1','source':'tool:aios_router_'+tool,
             'session_id':checkpoint['session_id'],'authority':body['authority'],'allowed':body['allowed'],
             'disposition':body['disposition'],'body_verdict':body,'privacy_core':privacy,
             'checkpoint_sha256':hashlib.sha256(payload).hexdigest(),
             'captured_at':datetime.now(timezone.utc).isoformat(timespec='milliseconds').replace('+00:00','Z')}
    dest=ROOT/'.opencode/receipts'/('continuity-'+uuid4().hex+'-body-gate.json')
    raw=core.authorize_file_write(str(dest))
    if raw.get('allowed') is not True: raise PermissionError('PrivacyCore denied authority receipt')
    with dest.open('x',encoding='utf-8') as stream:
        json.dump(receipt,stream,ensure_ascii=False,separators=(',',':'))
        stream.flush()
        os.fsync(stream.fileno())
    return {'receipt_id':dest.name,'checkpoint_sha256':receipt['checkpoint_sha256']}


if __name__=='__main__':
    try:
        request=json.loads(sys.stdin.buffer.read(1024*1024+1))
        print(json.dumps(authorize(request)))
    except Exception as error:
        print(json.dumps({'ok':False,'error':str(error)}))
        raise SystemExit(1)
