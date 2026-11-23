import hashlib,json,re
from pathlib import Path
root=Path(r'L:\LocalCoder\workspace\autonomy\learning\deepseek_candidate_runs')
suite=json.loads((root/'frozen_code_eval_v2_1.json').read_text(encoding='utf-8'))
claimed=suite.pop('suite_sha256')
def canon(x): return hashlib.sha256(json.dumps(x,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()
assert canon(suite)==claimed
held_ids={str(x['id']) for x in suite['held_out']}
held_names={(x['lang'],re.search(r'\b(?:pub\s+fn|def)\s+([A-Za-z_]\w*)\s*\(',x['spec']).group(1)) for x in suite['held_out']}
base=json.loads((Path(r'L:\LocalCoder\workspace\autonomy\learning\neural_runs')/'candidate_mixed_training_10026.json').read_text(encoding='utf-8'))
used_ids=set(base['sample_ids']); used_names={(x['language'],x['function_name']) for x in base['samples']}
print('suite_hash',claimed,'existing_training',len(used_ids),'rust',base['language_counts']['rust'])
for p in sorted(root.glob('candidate_rust_training_*.json')):
 try:
  d=json.loads(p.read_text(encoding='utf-8')); h=d.pop('receipt_sha256',None); valid_hash=canon(d)==h
  d['receipt_sha256']=h; samples=d.get('samples',[]); gates=d.get('gate_results',[])
  gate_ok=bool(samples) and len(gates)==len(samples) and all(g.get('passed') is True for g in gates)
  suite_ok=d.get('heldout_suite_sha256')==claimed and not d.get('heldout_id_overlap') and not d.get('heldout_function_name_overlap')
  fresh=[]; excluded=[]
  for s in samples:
   ident=str(s.get('id')); m=re.search(r'\bpub\s+fn\s+([A-Za-z_]\w*)\s*\(',str(s.get('prompt',''))); name=m.group(1) if m else ''
   code=str(s.get('prompt',''))+str(s.get('completion',''))
   code=re.sub(r'<｜end▁of▁sentence｜>$','',code).rstrip()
   codehash=hashlib.sha256(code.encode()).hexdigest()
   reason=[]
   if ident in held_ids or ('rust',name) in held_names: reason.append('heldout')
   if ident in used_ids or ('rust',name) in used_names: reason.append('duplicate_current')
   if codehash!=s.get('code_sha256'): reason.append('code_hash')
   if reason: excluded.append((ident,name,','.join(reason)))
   else: fresh.append((ident,name))
  eligible=valid_hash and gate_ok and suite_ok
  print(p.name,'hash',valid_hash,'gate',gate_ok,'suite',suite_ok,'rows',len(samples),'fresh',len(fresh) if eligible else 0,'names',fresh if eligible else [],'excluded',len(excluded))
 except Exception as e: print(p.name,'ERROR',repr(e))