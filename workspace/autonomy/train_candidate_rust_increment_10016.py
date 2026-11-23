"""Controlled Rust candidate run with training format matched to inference."""
from __future__ import annotations
from datetime import datetime,timezone
import hashlib,json,random,re,sys,urllib.request
from pathlib import Path
HERE=Path(__file__).resolve().parent;WS=HERE.parent
sys.path[:0]=[str(WS),str(HERE)]
import viv_code_learning_loop as gates
import viv_sleep_trainer as trainer

API="http://127.0.0.1:1234";LIVE=Path(r"E:\Viv_Sandbox\playground\adapters\epoch_10001")
ROOT=Path(r"F:\LocalCoder_Archive\Viv_model_candidates");PARENT=ROOT/"epoch_10013";DEST=ROOT/"epoch_10016"
RUNS=HERE/"learning"/"deepseek_candidate_runs";SUITE=RUNS/"frozen_code_eval_v2_1.json"
DATA_OUT=RUNS/"candidate_rust_training_10016.json";OUT=RUNS/"candidate_rust_training_run_10016.json";PREFLIGHT_OUT=RUNS/"candidate_rust_preflight_10016.json"
SEED,LR,STEPS=20261124,5e-7,32;EOS="<｜end▁of▁sentence｜>";FENCE=chr(96)*3

EXAMPLES=[
 ("checked_remainder","pub fn checked_remainder(value: i32, divisor: i32) -> Option<i32>: return the remainder, or None when divisor is zero","pub fn checked_remainder(value: i32, divisor: i32) -> Option<i32> { if divisor == 0 { None } else { Some(value % divisor) } }","assert_eq!(checked_remainder(7,3),Some(1)); assert_eq!(checked_remainder(-7,3),Some(-1)); assert_eq!(checked_remainder(7,0),None);"),
 ("adjacent_pair_sums","pub fn adjacent_pair_sums(values: &[i32]) -> Vec<i32>: return the sum of each neighboring pair","pub fn adjacent_pair_sums(values: &[i32]) -> Vec<i32> { values.windows(2).map(|pair| pair[0]+pair[1]).collect() }","assert_eq!(adjacent_pair_sums(&[2,5,1]),vec![7,6]); assert_eq!(adjacent_pair_sums(&[4]),vec![]); assert_eq!(adjacent_pair_sums(&[]),vec![]);"),
 ("prefix_products","pub fn prefix_products(values: &[i32]) -> Vec<i64>: return cumulative products from left to right","pub fn prefix_products(values: &[i32]) -> Vec<i64> { values.iter().scan(1i64,|acc,&x| { *acc *= i64::from(x); Some(*acc) }).collect() }","assert_eq!(prefix_products(&[2,3,4]),vec![2,6,24]); assert_eq!(prefix_products(&[3,0,-2]),vec![3,0,0]); assert_eq!(prefix_products(&[]),vec![]);"),
 ("stable_unique_values","pub fn stable_unique_values(values: &[i32]) -> Vec<i32>: keep only the first occurrence of each value and preserve order","pub fn stable_unique_values(values: &[i32]) -> Vec<i32> { let mut seen=std::collections::HashSet::new(); values.iter().copied().filter(|x| seen.insert(*x)).collect() }","assert_eq!(stable_unique_values(&[3,1,3,2,1]),vec![3,1,2]); assert_eq!(stable_unique_values(&[]),vec![]);"),
 ("optional_bounds","pub fn optional_bounds(values: &[i32]) -> Option<(i32,i32)>: return minimum and maximum, or None for empty input","pub fn optional_bounds(values: &[i32]) -> Option<(i32,i32)> { Some((*values.iter().min()?,*values.iter().max()?)) }","assert_eq!(optional_bounds(&[4,-2,8,1]),Some((-2,8))); assert_eq!(optional_bounds(&[5]),Some((5,5))); assert_eq!(optional_bounds(&[]),None);"),
 ("rotate_right_one","pub fn rotate_right_one(values: &[i32]) -> Vec<i32>: move the last value to the front; empty input remains empty","pub fn rotate_right_one(values: &[i32]) -> Vec<i32> { if values.is_empty() { return Vec::new(); } let mut out=values.to_vec(); out.rotate_right(1); out }","assert_eq!(rotate_right_one(&[1,2,3]),vec![3,1,2]); assert_eq!(rotate_right_one(&[8]),vec![8]); assert_eq!(rotate_right_one(&[]),vec![]);"),
 ("collapse_inner_spaces","pub fn collapse_inner_spaces(text: &str) -> String: trim and replace every whitespace run with one ASCII space","pub fn collapse_inner_spaces(text: &str) -> String { text.split_whitespace().collect::<Vec<_>>().join(\" \") }","assert_eq!(collapse_inner_spaces(\"  alpha\\t beta  gamma\\n\"),\"alpha beta gamma\"); assert_eq!(collapse_inner_spaces(\"   \"),\"\");"),
 ("uppercase_word_initials","pub fn uppercase_word_initials(text: &str) -> String: concatenate each word's first Unicode character in uppercase","pub fn uppercase_word_initials(text: &str) -> String { text.split_whitespace().filter_map(|word| word.chars().next()).flat_map(char::to_uppercase).collect() }","assert_eq!(uppercase_word_initials(\"north star\"),\"NS\"); assert_eq!(uppercase_word_initials(\"\"),\"\");"),
 ("increment_first","pub fn increment_first(values: &[i32]) -> Vec<i32>: add one to the first element when present and preserve the rest","pub fn increment_first(values: &[i32]) -> Vec<i32> { let mut out=values.to_vec(); if let Some(first)=out.first_mut() { *first+=1; } out }","assert_eq!(increment_first(&[4,2]),vec![5,2]); assert_eq!(increment_first(&[9]),vec![10]); assert_eq!(increment_first(&[]),vec![]);"),
 ("merge_sorted_lists","pub fn merge_sorted_lists(a: &[i32], b: &[i32]) -> Vec<i32>: merge two ascending slices, preserving duplicates","pub fn merge_sorted_lists(a: &[i32], b: &[i32]) -> Vec<i32> { let mut out=Vec::with_capacity(a.len()+b.len()); let (mut i,mut j)=(0,0); while i<a.len() && j<b.len() { if a[i]<=b[j] { out.push(a[i]); i+=1; } else { out.push(b[j]); j+=1; } } out.extend_from_slice(&a[i..]); out.extend_from_slice(&b[j..]); out }","assert_eq!(merge_sorted_lists(&[1,4,7],&[2,4,8]),vec![1,2,4,4,7,8]); assert_eq!(merge_sorted_lists(&[],&[2]),vec![2]); assert_eq!(merge_sorted_lists(&[],&[]),vec![]);"),
 ("maximum_rise","pub fn maximum_rise(values: &[i32]) -> Option<i32>: return the largest later-minus-earlier difference, or None with fewer than two values","pub fn maximum_rise(values: &[i32]) -> Option<i32> { if values.len()<2 { return None; } let mut low=values[0]; let mut best=i32::MIN; for &x in &values[1..] { best=best.max(x-low); low=low.min(x); } Some(best) }","assert_eq!(maximum_rise(&[7,2,9,4]),Some(7)); assert_eq!(maximum_rise(&[8,5,1]),Some(-3)); assert_eq!(maximum_rise(&[1]),None); assert_eq!(maximum_rise(&[]),None);"),
 ("every_nth_value","pub fn every_nth_value(values: &[i32], step: usize) -> Option<Vec<i32>>: return values at indices 0, step, 2*step and so on; None when step is zero","pub fn every_nth_value(values: &[i32], step: usize) -> Option<Vec<i32>> { if step==0 { return None; } Some(values.iter().step_by(step).copied().collect()) }","assert_eq!(every_nth_value(&[1,2,3,4,5],2),Some(vec![1,3,5])); assert_eq!(every_nth_value(&[7],4),Some(vec![7])); assert_eq!(every_nth_value(&[],1),Some(vec![])); assert_eq!(every_nth_value(&[1],0),None);"),
 ("is_non_decreasing","pub fn is_non_decreasing(values: &[i32]) -> bool: return whether every value is at least the previous one","pub fn is_non_decreasing(values: &[i32]) -> bool { values.windows(2).all(|pair| pair[0]<=pair[1]) }","assert!(is_non_decreasing(&[1,1,3])); assert!(!is_non_decreasing(&[1,3,2])); assert!(is_non_decreasing(&[])); assert!(is_non_decreasing(&[4]));"),
 ("pair_sums_above","pub fn pair_sums_above(values: &[i32], floor: i32) -> Vec<i32>: sum each neighboring pair only when both values exceed floor","pub fn pair_sums_above(values: &[i32], floor: i32) -> Vec<i32> { values.windows(2).filter(|pair| pair[0]>floor && pair[1]>floor).map(|pair| pair[0]+pair[1]).collect() }","assert_eq!(pair_sums_above(&[3,5,2,8],2),vec![8]); assert_eq!(pair_sums_above(&[1,2],0),vec![3]); assert_eq!(pair_sums_above(&[],0),vec![]);"),
 ("first_maximum_index","pub fn first_maximum_index(values: &[i32]) -> Option<usize>: return the first index of the largest value, or None when empty","pub fn first_maximum_index(values: &[i32]) -> Option<usize> { let (&first,rest)=values.split_first()?; let (mut best_i,mut best_v)=(0,first); for (i,&v) in rest.iter().enumerate() { if v>best_v { best_i=i+1; best_v=v; } } Some(best_i) }","assert_eq!(first_maximum_index(&[2,9,9,1]),Some(1)); assert_eq!(first_maximum_index(&[-5,-2]),Some(1)); assert_eq!(first_maximum_index(&[]),None);"),
 ("pairwise_gaps","pub fn pairwise_gaps(values: &[i32]) -> Vec<i32>: return each next value minus its immediate predecessor","pub fn pairwise_gaps(values: &[i32]) -> Vec<i32> { values.windows(2).map(|pair| pair[1]-pair[0]).collect() }","assert_eq!(pairwise_gaps(&[2,7,4]),vec![5,-3]); assert_eq!(pairwise_gaps(&[9]),vec![]); assert_eq!(pairwise_gaps(&[]),vec![]);"),
 ("chunks_of_two","pub fn chunks_of_two(values: &[i32]) -> Vec<(i32,i32)>: return consecutive non-overlapping pairs and ignore one trailing value","pub fn chunks_of_two(values: &[i32]) -> Vec<(i32,i32)> { values.chunks_exact(2).map(|pair| (pair[0],pair[1])).collect() }","assert_eq!(chunks_of_two(&[1,2,3,4,5]),vec![(1,2),(3,4)]); assert_eq!(chunks_of_two(&[8]),vec![]); assert_eq!(chunks_of_two(&[]),vec![]);"),
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
def rust_signature(spec):
 m=re.search(r'pub\s+fn\s+[A-Za-z_]\w*\s*\(',spec)
 if not m:raise ValueError('Rust function signature missing')
 paren=spec.find('(',m.start());depth=0;close=-1
 for index in range(paren,len(spec)):
  if spec[index]=='(':depth+=1
  elif spec[index]==')':
   depth-=1
   if depth==0:close=index;break
 colon=spec.find(':',close+1)
 if close<0 or colon<0:raise ValueError('Rust function signature boundary missing')
 return spec[:colon].strip()+' {',spec[colon+1:].strip()

def main():
 if DATA_OUT.exists() or OUT.exists() or PREFLIGHT_OUT.exists() or DEST.exists():raise FileExistsError('epoch_10016 artifact already exists')
 suite=json.loads(SUITE.read_text(encoding='utf-8'));sh=suite.pop('suite_sha256')
 if h(suite)!=sh:raise ValueError('frozen suite receipt mismatch')
 held=[x for x in suite['held_out'] if x['lang']=='rust'];held_ids={x['id'] for x in held};held_names={name(x['spec']) for x in held}
 samples=[];gate_rows=[]
 for task_id,spec,code,checks in EXAMPLES:
  task_id='rust10016_'+task_id;fn=name(spec)
  if task_id in held_ids or fn in held_names:raise ValueError('held-out ID or function-name overlap')
  passed,error=gates.gate_rust(code,'#[cfg(test)] mod t { use super::*; #[test] fn cases(){ '+checks+' } }')
  gate_rows.append({'id':task_id,'passed':bool(passed),'error':error[:2000]})
  print(json.dumps({'preflight_task':task_id,'passed':bool(passed),'error':error[:180]},ensure_ascii=False),flush=True)
  if not passed:continue
  header,description=rust_signature(spec)
  if not code.startswith(header):raise ValueError(f'{task_id} reference signature does not match spec')
  prompt=("# Implement one self-contained, correct standard-library Rust function. Do not depend on other top-level helpers. Handle empty and boundary inputs.\n"
          f"# Task: {description}\n{header}\n")
  completion=code[len(header):]
  samples.append({'id':task_id,'category':'rust_gate_verified_v2','prompt':prompt,'completion':completion+EOS,'source_kind':'locally_authored_reference_passed_existing_gate','format_contract':'candidate_coding_runtime_v1_rust_signature_prefix'})
 preflight={'schema':'viv_candidate_rust_preflight_v1','created_utc':datetime.now(timezone.utc).isoformat(),'parent':str(PARENT),'heldout_suite_sha256':sh,'gate_results':gate_rows,'unique_samples':len(samples),'all_gates_passed':all(x['passed'] for x in gate_rows)};preflight['receipt_sha256']=h(preflight)
 PREFLIGHT_OUT.write_text(json.dumps(preflight,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
 if len(samples)!=len(EXAMPLES) or not all(x['passed'] for x in gate_rows):raise ValueError('gate count invariant failed')
 data={'schema':'viv_candidate_rust_training_v2','created_utc':datetime.now(timezone.utc).isoformat(),'parent_candidate':str(PARENT),'heldout_suite_sha256':sh,'heldout_id_overlap':[],'heldout_function_name_overlap':[],'gate_results':gate_rows,'samples':samples,'training_prompt_contract':'matched to candidate_coding_runtime_v1 Rust proposer: code-comment task prefix plus function signature; completion begins after opening brace and contains the function body/closing brace','training_sha256':h(samples)};data['receipt_sha256']=h(data)
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
  result=trainer.run_sleep_training(epoch=10016,steps=STEPS,lr=LR,parent_adapter=PARENT,training_samples=rows)
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
