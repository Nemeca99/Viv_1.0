from __future__ import annotations
import hashlib,hmac,json,os
from pathlib import Path
from typing import Any,Mapping

def _path(root:Path,transaction_id:str)->Path:
    return Path(root).resolve()/(hashlib.sha256(transaction_id.encode()).hexdigest().upper()+'.json')
def _write_descriptor(descriptor:int,value:Mapping[str,Any])->None:
    with os.fdopen(descriptor,'w',encoding='utf-8') as stream:json.dump(dict(value),stream,sort_keys=True,separators=(',',':'));stream.write('\n');stream.flush();os.fsync(stream.fileno())
def claim(root:Path,*,transaction_id:str,bundle_sha256:str)->dict[str,Any]:
    Path(root).resolve().mkdir(parents=True,exist_ok=True);path=_path(root,transaction_id);record={'schema':'VIV_DURABLE_EFFECT_LIFECYCLE_V1','state':'CLAIMED','transaction_id':transaction_id,'bundle_sha256':bundle_sha256}
    try:descriptor=os.open(str(path),os.O_CREAT|os.O_EXCL|os.O_WRONLY)
    except FileExistsError:
        existing=json.loads(path.read_text())
        return {'state':'HOLD','reason':'HOLD_RECOVERY_REQUIRED' if existing.get('state')=='CLAIMED' else 'HOLD_EFFECT_ALREADY_EXECUTED','record':existing}
    _write_descriptor(descriptor,record);return {'state':'PASS','reason':'PASS_EFFECT_CLAIMED','record':record}
def inspect(root:Path,transaction_id:str)->dict[str,Any]:
    path=_path(root,transaction_id)
    if not path.exists():return {'state':'HOLD','reason':'HOLD_EFFECT_NOT_CLAIMED'}
    record=json.loads(path.read_text())
    if record.get('state')=='CLAIMED':return {'state':'HOLD','reason':'HOLD_RECOVERY_REQUIRED','record':record}
    return {'state':'HOLD','reason':'HOLD_EFFECT_ALREADY_EXECUTED','record':record}
def complete(root:Path,*,transaction_id:str,effect_receipt:Mapping[str,Any],seal:str,cpu_hmac_key:bytes)->dict[str,Any]:
    path=_path(root,transaction_id)
    if not path.exists():return {'state':'HOLD','reason':'HOLD_EFFECT_NOT_CLAIMED'}
    current=json.loads(path.read_text())
    # The filename, persisted claim and CPU receipt must name the same typed
    # transaction before any completion replaces the preserved claim evidence.
    if current.get('schema')!='VIV_DURABLE_EFFECT_LIFECYCLE_V1' or current.get('transaction_id')!=transaction_id:
        return {'state':'HOLD','reason':'HOLD_EFFECT_CLAIM_INVALID'}
    if current.get('state')!='CLAIMED':return {'state':'HOLD','reason':'HOLD_EFFECT_ALREADY_EXECUTED','record':current}
    expected=hmac.new(cpu_hmac_key,json.dumps(dict(effect_receipt),sort_keys=True,separators=(',',':')).encode(),hashlib.sha256).hexdigest().upper()
    if not hmac.compare_digest(expected,str(seal).upper()):return {'state':'HOLD','reason':'HOLD_EFFECT_RECEIPT_SEAL_INVALID'}
    mismatch=[]
    if effect_receipt.get('schema')!='VIV_CPU_EFFECT_RECEIPT_V1':mismatch.append('schema')
    if str(effect_receipt.get('transaction_id',''))!=transaction_id:mismatch.append('transaction_id')
    if str(effect_receipt.get('bundle_sha256','')).upper()!=str(current.get('bundle_sha256','')).upper():mismatch.append('bundle_sha256')
    if effect_receipt.get('executed') is not True:mismatch.append('executed')
    result_sha=str(effect_receipt.get('result_sha256','')).upper()
    if len(result_sha)!=64 or any(c not in '0123456789ABCDEF' for c in result_sha):mismatch.append('result_sha256')
    if mismatch:return {'state':'HOLD','reason':'HOLD_EFFECT_RECEIPT_BINDING_MISMATCH','mismatched_fields':sorted(mismatch)}
    completed={**current,'state':'EXECUTED','result_sha256':result_sha,'effect_receipt_sha256':hashlib.sha256(json.dumps(dict(effect_receipt),sort_keys=True,separators=(',',':')).encode()).hexdigest().upper()}
    temporary=path.with_suffix('.tmp');temporary.write_text(json.dumps(completed,sort_keys=True,separators=(',',':'))+'\n',encoding='utf-8')
    with temporary.open('r+b') as stream:stream.flush();os.fsync(stream.fileno())
    temporary.replace(path)
    return {'state':'PASS','reason':'PASS_EFFECT_EXECUTION_RECORDED','record':completed}
