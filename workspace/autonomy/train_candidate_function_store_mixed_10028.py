"""Fine-tune epoch 10028 from candidate DB functions with Rust emphasis."""
from __future__ import annotations
from datetime import datetime,timezone
import hashlib,json,random,re,sqlite3,sys,urllib.request
from pathlib import Path
HERE=Path(__file__).resolve().parent; WORKSPACE=HERE.parent
sys.path[:0]=[str(WORKSPACE),str(HERE)]
import candidate_verified_function_store as store
import candidate_coding_runtime_v1 as runtime
import viv_sleep_trainer as trainer
from aios_rebuild.privacy_core.privacy_core import PrivacyCore
ROOT=Path(r'F:\LocalCoder_Archive\Viv_model_candidates'); PARENT=ROOT/'epoch_10027'; DEST=ROOT/'epoch_10028'
RUNS=HERE/'learning'/'neural_runs'; SUITE=store.SUITE_PATH
DATA_OUT=RUNS/'candidate_function_store_mixed_training_10028.json'; RUN_OUT=RUNS/'candidate_function_store_mixed_training_run_10028.json'
LEARN_RECEIPT=RUNS/'candidate_rust_offsplit_learning_10028.json'; SEED=20261201; LR=5e-7; PY_REPEATS=1; RS_REPEATS=4
EOS='<｜end▁of▁sentence｜>'; FENCE=chr(96)*3

def canon(x): return hashlib.sha256(json.dumps(x,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()
def sha(p):
 h=hashlib.sha256()
 with p.open('rb') as f:
  for block in iter(lambda:f.read(1024*1024),b''): h.update(block)
 return h.hexdigest()
def write_new(path,obj):
 auth=PrivacyCore().authorize_file_write(str(path))
 if auth.get('allowed') is not True: raise PermissionError(f'PrivacyCore denied {path}: {auth}')
 with path.open('x',encoding='utf-8',newline='\n') as f: f.write(json.dumps(obj,ensure_ascii=False,indent=2)+'\n')
 return auth
def rust_body(code,name):
 m=re.search(rf'\bpub\s+fn\s+{re.escape(name)}\s*\(',code)
 if not m: raise ValueError('RUST_FUNCTION_NOT_FOUND:'+name)
 opening=code.find('{',m.end())
 closing=code.rfind('}')
 if opening<0 or closing<=opening: raise ValueError('RUST_FUNCTION_BODY_INVALID:'+name)
 return code[opening+1:closing].strip()
def main():
 for p in (PARENT/'adapter_model.safetensors',store.DB_PATH,SUITE,LEARN_RECEIPT):
  if not p.is_file(): raise FileNotFoundError(p)
 for p in (DEST,DATA_OUT,RUN_OUT):
  if p.exists(): raise FileExistsError(f'Refusing overwrite: {p}')
 learn=json.loads(LEARN_RECEIPT.read_text(encoding='utf-8')); claimed=learn.pop('receipt_sha256',None)
 if canon(learn)!=claimed: raise ValueError('LEARNING_RECEIPT_HASH_MISMATCH')
 learn['receipt_sha256']=claimed
 if learn.get('accepted_count')!=5 or learn.get('live_restored') is not True or learn.get('promoted') is not False: raise ValueError('RUST_LEARNING_RECEIPT_NOT_ACCEPTABLE')
 suite=json.loads(SUITE.read_text(encoding='utf-8')); suite_hash=suite.pop('suite_sha256',None)
 if canon(suite)!=suite_hash: raise ValueError('FROZEN_SUITE_HASH_MISMATCH')
 held_ids={str(x['id']) for x in suite['held_out']}; held_names=set()
 for x in suite['held_out']:
  m=re.search(r'\b(?:pub\s+fn|def)\s+([A-Za-z_]\w*)\s*\(',x['spec'])
  if m: held_names.add((x['lang'],m.group(1)))
 dbhash=sha(store.DB_PATH); uri=store.DB_PATH.as_uri()+'?mode=ro'
 with sqlite3.connect(uri,uri=True) as db:
  if db.execute('pragma quick_check').fetchone()[0]!='ok': raise RuntimeError('CANDIDATE_STORE_QUICK_CHECK_FAILED')
  rows=db.execute('''SELECT f.function_key,f.language,f.domain,f.function_name,f.specification,
       v.version_id,v.task_id,v.source_kind,v.source_sha256,v.code,v.code_sha256,v.tests_sha256,
       v.gate_name,v.gate_status,v.gate_output,v.gate_receipt_sha256,v.admitted_utc
       FROM function_versions v JOIN functions f USING(function_key)
       WHERE v.gate_status='ALLOW' ORDER BY v.version_id''').fetchall()
  attempts=db.execute('select gate_status,count(*) from proposal_attempts group by gate_status').fetchall()
 samples=[]; seen_codes=set(); ids=set(); funcs=set()
 for row in rows:
  (key,lang,domain,name,spec,vid,task,source_kind,source_hash,code,code_hash,tests_hash,gate,status,output,receipt_hash,created)=row
  if task in held_ids or (lang,name) in held_names: raise ValueError(f'HELDOUT_OVERLAP:{task}:{name}')
  if task in ids or (lang,name) in funcs: raise ValueError(f'DUPLICATE_TRAINING_IDENTITY:{task}:{name}')
  if hashlib.sha256(code.encode()).hexdigest()!=code_hash: raise ValueError(f'CODE_HASH_MISMATCH:{vid}')
  if status!='ALLOW' or not receipt_hash: raise ValueError(f'GATE_RECORD_MISSING:{vid}')
  gr={'task_id':task,'language':lang,'function_key':key,'code_sha256':code_hash,'tests_sha256':tests_hash,'gate':gate,'status':status,'output':output,'created_utc':created}
  if canon(gr)!=receipt_hash: raise ValueError(f'GATE_RECEIPT_HASH_MISMATCH:{vid}')
  if code_hash in seen_codes: continue
  seen_codes.add(code_hash); ids.add(task); funcs.add((lang,name))
  if lang=='python':
   prompt=('SYSTEM: Write one self-contained, correct, standard-library python function. Do not depend on other top-level helpers. Return only one fenced code block; no tests or explanation.\n\nUSER: Implement: '+spec+'\n\nASSISTANT:')
   completion=f'{FENCE}python\n{code}\n{FENCE}{EOS}'
  elif lang=='rust':
   parsed=runtime.rust_signature(spec)
   if not parsed: raise ValueError('RUST_SIGNATURE_PARSE_FAILED:'+name)
   header,description=parsed; body=rust_body(code,name)
   grounding=runtime.uml_context_for_task({'spec':spec})
   uml_note='' if not grounding.get('prompt_context') else '# Deterministic UML reference:\n'+'\n'.join('# '+line for line in grounding['prompt_context'].splitlines())+'\n'
   prompt=('# Implement one self-contained, correct standard-library Rust function. Do not depend on other top-level helpers. Handle empty and boundary inputs.\n'+uml_note+f'# Task: {description}\n{header}\n')
   completion=body+'\n}\n'+EOS
  else: raise ValueError('UNEXPECTED_LANGUAGE:'+str(lang))
  samples.append({'id':f'candidate_store_v{vid}_{task}','language':lang,'domain':domain,'function_name':name,'prompt':prompt,'completion':completion,'code':code,'code_sha256':code_hash,'tests_sha256':tests_hash,'gate_name':gate,'gate_status':status,'gate_receipt_sha256':receipt_hash,'function_key':key,'version_id':vid,'source_kind':source_kind,'source_sha256':source_hash})
 counts={k:sum(x['language']==k for x in samples) for k in ('python','rust')}
 if counts.get('python')!=9 or counts.get('rust')!=5: raise ValueError('UNEXPECTED_ACCEPTED_COUNTS:'+json.dumps(counts))
 py=[x for x in samples if x['language']=='python']; rs=[x for x in samples if x['language']=='rust']
 rows_train=py*PY_REPEATS+rs*RS_REPEATS; random.Random(SEED).shuffle(rows_train)
 before=runtime.evaluator.request('/v1/status')
 if before.get('status')!='ACTIVE' or before.get('active_adapter')!=runtime.LIVE.name: raise RuntimeError('UNEXPECTED_LIVE_ADAPTER:'+json.dumps(before))
 if sha(store.DB_PATH)!=dbhash: raise RuntimeError('CANDIDATE_STORE_CHANGED_DURING_READ')
 dataset={'schema':'viv_candidate_function_store_mixed_training_v1','created_utc':datetime.now(timezone.utc).isoformat(),'candidate_store':str(store.DB_PATH),'candidate_store_sha256':dbhash,'rust_learning_receipt':str(LEARN_RECEIPT),'rust_learning_receipt_sha256':claimed,'parent_candidate':str(PARENT),'parent_sha256':sha(PARENT/'adapter_model.safetensors'),'frozen_suite_path':str(SUITE),'frozen_suite_sha256':suite_hash,'accepted_version_count':len(rows),'language_counts':counts,'repeat_policy':{'python':PY_REPEATS,'rust':RS_REPEATS},'training_rows':len(rows_train),'training_sha256':canon(rows_train),'rejected_proposal_counts':dict(attempts),'heldout_id_overlap':[],'heldout_function_name_overlap':[],'samples':samples,'live_adapter_at_build':before.get('active_adapter'),'promoted':False,'topology_write':False,'persistent_memory_write':False}
 dataset['receipt_sha256']=canon(dataset); auth=write_new(DATA_OUT,dataset)
 import torch
 from transformers import set_seed
 random.seed(SEED); torch.manual_seed(SEED); set_seed(SEED)
 if torch.cuda.is_available(): torch.cuda.manual_seed_all(SEED)
 trainer.ADAPTERS_ROOT=ROOT; trainer.RECEIPTS_FILE=ROOT/'training_receipts.jsonl'
 run={'schema':'viv_candidate_function_store_mixed_training_run_v1','created_utc':datetime.now(timezone.utc).isoformat(),'dataset':str(DATA_OUT),'dataset_receipt_sha256':dataset['receipt_sha256'],'training_sha256':dataset['training_sha256'],'candidate_store_sha256_before':dbhash,'unique_examples':len(samples),'language_counts':counts,'training_rows':len(rows_train),'seed':SEED,'learning_rate':LR,'steps_requested':len(rows_train),'parent':str(PARENT),'parent_sha256':dataset['parent_sha256'],'frozen_suite_sha256':suite_hash,'live_before':before,'privacy_authorization':auth,'promoted':False,'topology_write':False,'persistent_memory_write':False}
 quiesced=False
 try:
  state=runtime.evaluator.request('/v1/quiesce',{})
  if state.get('status')!='QUIESCED': raise RuntimeError('QUIESCE_FAILED:'+json.dumps(state))
  quiesced=True
  result=trainer.run_sleep_training(epoch=10028,steps=len(rows_train),lr=LR,parent_adapter=PARENT,training_samples=rows_train)
  if not result.get('ok'): raise RuntimeError('TRAINING_FAILED:'+json.dumps(result))
  run['training']=result; run['candidate_sha256']=sha(DEST/'adapter_model.safetensors'); run['status']='TRAINED_CANDIDATE'
 except Exception as e: run['status']='TRAINING_FAILED'; run['training_error']=f'{type(e).__name__}: {e}'
 finally:
  if quiesced:
   try: runtime.evaluator.request('/v1/resume',{'adapter_dir':str(runtime.LIVE)})
   except Exception as e: run['restore_error']=f'{type(e).__name__}: {e}'
 try:
  after=runtime.evaluator.request('/v1/status'); run['live_after']=after; run['live_restored']=after.get('status')=='ACTIVE' and after.get('active_adapter')==runtime.LIVE.name
 except Exception as e: run['live_restored']=False; run['restore_status_error']=f'{type(e).__name__}: {e}'
 run['candidate_store_sha256_after']=sha(store.DB_PATH); run['candidate_store_unchanged_during_training']=run['candidate_store_sha256_after']==dbhash
 run['receipt_sha256']=canon(run); write_new(RUN_OUT,run)
 print(json.dumps({'dataset_receipt':str(DATA_OUT),'training_receipt':str(RUN_OUT),'status':run['status'],'candidate_sha256':run.get('candidate_sha256'),'unique_examples':len(samples),'python_rows':len(py)*PY_REPEATS,'rust_rows':len(rs)*RS_REPEATS,'training_rows':len(rows_train),'live_restored':run.get('live_restored'),'active_adapter':run.get('live_after',{}).get('active_adapter'),'store_unchanged':run['candidate_store_unchanged_during_training'],'promoted':False},indent=2),flush=True)
 return 0 if run['status']=='TRAINED_CANDIDATE' and run.get('live_restored') and run['candidate_store_unchanged_during_training'] else 1
if __name__=='__main__': raise SystemExit(main())