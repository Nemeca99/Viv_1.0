"""Train a fresh, Rust-only candidate batch on compiler-gated idioms."""
from __future__ import annotations
from datetime import datetime,timezone
import hashlib,json,random,re,sys,urllib.request
from pathlib import Path
HERE=Path(__file__).resolve().parent;WS=HERE.parent
sys.path[:0]=[str(WS),str(HERE)]
import viv_code_learning_loop as gates
import viv_sleep_trainer as trainer

API="http://127.0.0.1:1234";LIVE=Path(r"E:\Viv_Sandbox\playground\adapters\epoch_10001")
ROOT=Path(r"F:\LocalCoder_Archive\Viv_model_candidates");PARENT=ROOT/"epoch_10013";DEST=ROOT/"epoch_10014"
RUNS=HERE/"learning"/"deepseek_candidate_runs";SUITE=RUNS/"frozen_code_eval_v2_1.json"
DATA_OUT=RUNS/"candidate_rust_training_10014.json";OUT=RUNS/"candidate_rust_training_run_10014.json"
SEED,LR,STEPS=20261122,5e-7,32;EOS="<｜end▁of▁sentence｜>";FENCE=chr(96)*3

EXAMPLES=[
 ("safe_ratio","pub fn safe_ratio(numerator: f64, denominator: f64) -> Option<f64>: return quotient or None when denominator is zero","pub fn safe_ratio(numerator: f64, denominator: f64) -> Option<f64> { if denominator == 0.0 { None } else { Some(numerator / denominator) } }","assert_eq!(safe_ratio(5.0,2.0),Some(2.5)); assert_eq!(safe_ratio(1.0,0.0),None);"),
 ("uppercased_text","pub fn uppercased_text(text: &str) -> String: return the full Unicode uppercase mapping of every character","pub fn uppercased_text(text: &str) -> String { text.chars().flat_map(char::to_uppercase).collect() }","assert_eq!(uppercased_text(\"rust\"),\"RUST\"); let pi=char::from_u32(0x03c0).unwrap().to_string(); let expected=char::from_u32(0x03a0).unwrap().to_string(); assert_eq!(uppercased_text(&pi),expected);"),
 ("interleave_slices","pub fn interleave_slices(a: &[i32], b: &[i32]) -> Vec<i32>: alternate elements starting with a; append remaining elements in order","pub fn interleave_slices(a: &[i32], b: &[i32]) -> Vec<i32> { let mut out=Vec::with_capacity(a.len()+b.len()); for i in 0..a.len().max(b.len()) { if let Some(&x)=a.get(i) { out.push(x); } if let Some(&x)=b.get(i) { out.push(x); } } out }","assert_eq!(interleave_slices(&[1,3,5],&[2,4]),vec![1,2,3,4,5]); assert_eq!(interleave_slices(&[],&[7,8]),vec![7,8]); assert_eq!(interleave_slices(&[],&[]),vec![]);"),
 ("filter_inclusive","pub fn filter_inclusive(values: &[i32], low: i32, high: i32) -> Vec<i32>: keep values within inclusive bounds in original order","pub fn filter_inclusive(values: &[i32], low: i32, high: i32) -> Vec<i32> { values.iter().copied().filter(|&x| low <= x && x <= high).collect() }","assert_eq!(filter_inclusive(&[4,1,3,2,5],2,4),vec![4,3,2]); assert_eq!(filter_inclusive(&[],0,1),vec![]);"),
 ("first_matching_index","pub fn first_matching_index(values: &[i32], target: i32) -> Option<usize>: return index of first equal value","pub fn first_matching_index(values: &[i32], target: i32) -> Option<usize> { values.iter().position(|&x| x == target) }","assert_eq!(first_matching_index(&[4,2,4],4),Some(0)); assert_eq!(first_matching_index(&[1,2],3),None); assert_eq!(first_matching_index(&[],0),None);"),
 ("prefix_maxima","pub fn prefix_maxima(values: &[i32]) -> Vec<i32>: at each position return the maximum seen so far","pub fn prefix_maxima(values: &[i32]) -> Vec<i32> { let mut out=Vec::with_capacity(values.len()); let mut max_seen=None; for &x in values { max_seen=Some(max_seen.map_or(x,|m: i32| m.max(x))); out.push(max_seen.unwrap()); } out }","assert_eq!(prefix_maxima(&[3,1,4,2]),vec![3,3,4,4]); assert_eq!(prefix_maxima(&[]),vec![]);"),
 ("count_ascii_letters","pub fn count_ascii_letters(text: &str) -> usize: count only ASCII alphabetic bytes","pub fn count_ascii_letters(text: &str) -> usize { text.bytes().filter(|b| b.is_ascii_alphabetic()).count() }","assert_eq!(count_ascii_letters(\"Ab 2_\"),2); let accent=char::from_u32(233).unwrap().to_string(); assert_eq!(count_ascii_letters(&accent),0);"),
 ("checked_product","pub fn checked_product(values: &[i64]) -> Option<i64>: multiply all values or return None on overflow","pub fn checked_product(values: &[i64]) -> Option<i64> { values.iter().try_fold(1i64,|acc,&x| acc.checked_mul(x)) }","assert_eq!(checked_product(&[2,-3,4]),Some(-24)); assert_eq!(checked_product(&[]),Some(1)); assert_eq!(checked_product(&[i64::MAX,2]),None);"),
 ("parity_counts","pub fn parity_counts(values: &[i32]) -> (usize,usize): return counts of even and odd values","pub fn parity_counts(values: &[i32]) -> (usize,usize) { values.iter().fold((0,0),|(even,odd),&x| if x%2==0 {(even+1,odd)} else {(even,odd+1)}) }","assert_eq!(parity_counts(&[0,1,2,-3]),(2,2)); assert_eq!(parity_counts(&[]),(0,0));"),
 ("first_and_last","pub fn first_and_last(values: &[i32]) -> Option<(i32,i32)>: return first and last values or None when empty","pub fn first_and_last(values: &[i32]) -> Option<(i32,i32)> { Some((*values.first()?,*values.last()?)) }","assert_eq!(first_and_last(&[4,2,9]),Some((4,9))); assert_eq!(first_and_last(&[7]),Some((7,7))); assert_eq!(first_and_last(&[]),None);"),
]

def h(x):return hashlib.sha256(json.dumps(x,ensure_ascii=False,sort_keys=True,separators=(",",":")).encode()).hexdigest()
def fh(path):
 d=hashlib.sha256()
 with path.open('rb') as f:
  for block in iter(lambda:f.read(1024*1024),b''):d.update(block)
 return d.hexdigest()
def req(path,payload=None):
 body=None if payload is None else json.dumps(payload).encode();r=urllib.request.Request(API+path,data=body,headers={"Content-Type":"application/json"} if body else {})
 with urllib.request.urlopen(r,timeout=300) as x:return json.load(x)
def name(spec):
 m=re.search(r'pub\s+fn\s+([A-Za-z_]\w*)',spec)
 if not m:raise ValueError('Rust function name missing')
 return m.group(1)
def main():
 if DATA_OUT.exists() or OUT.exists() or DEST.exists():raise FileExistsError('epoch_10014 artifact already exists')
 suite=json.loads(SUITE.read_text(encoding='utf-8'));sh=suite.pop('suite_sha256')
 if h(suite)!=sh:raise ValueError('frozen suite receipt mismatch')
 held=[x for x in suite['held_out'] if x['lang']=='rust'];held_ids={x['id'] for x in held};held_names={name(x['spec']) for x in held}
 samples=[];gate_rows=[]
 for task_id,spec,code,checks in EXAMPLES:
  task_id='rust10014_'+task_id;fn=name(spec)
  if task_id in held_ids or fn in held_names:raise ValueError('held-out ID or function-name overlap')
  passed,error=gates.gate_rust(code,'#[cfg(test)] mod t { use super::*; #[test] fn cases(){ '+checks+' } }')
  gate_rows.append({'id':task_id,'passed':bool(passed),'error':error[:2000]})
  if not passed:raise RuntimeError(f'{task_id} Rust gate failed: {error}')
  prompt=f"SYSTEM: Implement one self-contained, correct standard-library Rust function. Return one fenced Rust code block only.\n\nUSER: Implement: {spec}\n\nASSISTANT:"
  samples.append({'id':task_id,'category':'rust_gate_verified_v2','prompt':prompt,'completion':f'{FENCE}rust\n{code}\n{FENCE}{EOS}','source_kind':'locally_authored_reference_passed_existing_gate'})
 if len(samples)!=10 or not all(x['passed'] for x in gate_rows):raise ValueError('gate count invariant failed')
 data={'schema':'viv_candidate_rust_training_v2','created_utc':datetime.now(timezone.utc).isoformat(),'parent_candidate':str(PARENT),'heldout_suite_sha256':sh,'heldout_id_overlap':[],'heldout_function_name_overlap':[],'gate_results':gate_rows,'samples':samples,'training_sha256':h(samples)};data['receipt_sha256']=h(data)
 DATA_OUT.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
 before=req('/v1/status')
 if before.get('status')!='ACTIVE' or before.get('active_adapter')!=LIVE.name:raise RuntimeError('unexpected tutor '+json.dumps(before))
 trainer.ADAPTERS_ROOT=ROOT;trainer.RECEIPTS_FILE=ROOT/'training_receipts.jsonl';rows=samples*2
 run={'schema':'viv_candidate_rust_training_run_v2','created_utc':datetime.now(timezone.utc).isoformat(),'dataset':str(DATA_OUT),'dataset_sha256':data['receipt_sha256'],'training_sha256':h(rows),'unique_rust_samples':len(samples),'training_rows':len(rows),'steps_requested':STEPS,'learning_rate':LR,'seed':SEED,'parent':str(PARENT),'parent_sha256':fh(PARENT/'adapter_model.safetensors'),'heldout_suite_sha256':sh,'live_before':before,'promoted':False}
 quiesced=False;error=None
 try:
  q=req('/v1/quiesce',{})
  if q.get('status')!='QUIESCED':raise RuntimeError('quiesce failed '+json.dumps(q))
  quiesced=True
  import torch
  from transformers import set_seed
  random.seed(SEED);torch.manual_seed(SEED);set_seed(SEED)
  if torch.cuda.is_available():torch.cuda.manual_seed_all(SEED)
  result=trainer.run_sleep_training(epoch=10014,steps=STEPS,lr=LR,parent_adapter=PARENT,training_samples=rows)
  if not result.get('ok'):raise RuntimeError('training failed '+json.dumps(result))
  run['training']=result;run['candidate_sha256']=fh(DEST/'adapter_model.safetensors');run['status']='TRAINED_CANDIDATE'
 except Exception as exc:error=f'{type(exc).__name__}: {exc}';run['status']='TRAINING_FAILED';run['training_error']=error
 finally:
  if quiesced:
   try:req('/v1/resume',{'adapter_dir':str(LIVE)})
   except Exception as exc:run['restore_error']=f'{type(exc).__name__}: {exc}'
 try:
  after=req('/v1/status');run['live_after']=after;run['live_restored']=after.get('status')=='ACTIVE' and after.get('active_adapter')==LIVE.name
 except Exception as exc:run['live_restored']=False;run['restore_status_error']=f'{type(exc).__name__}: {exc}'
 run['receipt_sha256']=h(run);OUT.write_text(json.dumps(run,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
 print(json.dumps({'dataset':str(DATA_OUT),'gated_samples':len(samples),'all_gates_passed':all(x['passed'] for x in gate_rows),'status':run['status'],'candidate_sha256':run.get('candidate_sha256'),'live_restored':run['live_restored'],'active_adapter':run.get('live_after',{}).get('active_adapter'),'error':error,'promoted':False},indent=2),flush=True)
 return 0 if run['status']=='TRAINED_CANDIDATE' and run['live_restored'] else 1
if __name__=='__main__':raise SystemExit(main())
