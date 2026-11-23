"""Train paired Python/Rust concepts through existing deterministic gates."""
from __future__ import annotations
from datetime import datetime,timezone
import hashlib,json,random,re,sys,urllib.request
from pathlib import Path
HERE=Path(__file__).resolve().parent; WS=HERE.parent
sys.path[:0]=[str(WS),str(HERE)]
import viv_code_learning_loop as gates
import viv_sleep_trainer as trainer

API="http://127.0.0.1:1234"; LIVE=Path(r"E:\Viv_Sandbox\playground\adapters\epoch_10001")
ROOT=Path(r"F:\LocalCoder_Archive\Viv_model_candidates");PARENT=ROOT/"epoch_10012";DEST=ROOT/"epoch_10013"
RUNS=HERE/"learning"/"deepseek_candidate_runs";SUITE=RUNS/"frozen_code_eval_v2_1.json"
DATA_OUT=RUNS/"candidate_paired_training_10013.json";OUT=RUNS/"candidate_paired_training_run_10013.json"
SEED,LR,STEPS=20261121,5e-7,40;EOS="<｜end▁of▁sentence｜>";FENCE=chr(96)*3

# Each pair teaches one shared operation; names and task IDs are not held-out tasks.
PAIRS=[
 ("count_ascii_digits","def count_ascii_digits(text: str) -> int: count ASCII decimal digits","def count_ascii_digits(text):\n    return sum('0' <= ch <= '9' for ch in text)","assert count_ascii_digits('A1b02') == 3\nassert count_ascii_digits('') == 0\nassert count_ascii_digits(chr(0x0663)) == 0",
  "pub fn count_ascii_digits(text: &str) -> usize: count ASCII decimal digits","pub fn count_ascii_digits(text: &str) -> usize { text.bytes().filter(|b| b.is_ascii_digit()).count() }","assert_eq!(count_ascii_digits(\"A1b02\"),3); assert_eq!(count_ascii_digits(\"\"),0); let other=char::from_u32(0x0663).unwrap().to_string(); assert_eq!(count_ascii_digits(&other),0);"),
 ("sum_positive_values","def sum_positive_values(values: list[int]) -> int: sum only values greater than zero","def sum_positive_values(values):\n    return sum(value for value in values if value > 0)","assert sum_positive_values([-2,3,0,4]) == 7\nassert sum_positive_values([]) == 0",
  "pub fn sum_positive_values(values: &[i32]) -> i64: sum only values greater than zero","pub fn sum_positive_values(values: &[i32]) -> i64 { values.iter().filter(|&&x| x > 0).map(|&x| x as i64).sum() }","assert_eq!(sum_positive_values(&[-2,3,0,4]),7); assert_eq!(sum_positive_values(&[]),0);"),
 ("filter_even_values","def filter_even_values(values: list[int]) -> list[int]: return even values in original order","def filter_even_values(values):\n    return [value for value in values if value % 2 == 0]","assert filter_even_values([3,2,4,1,0]) == [2,4,0]\nassert filter_even_values([]) == []",
  "pub fn filter_even_values(values: &[i32]) -> Vec<i32>: return even values in original order","pub fn filter_even_values(values: &[i32]) -> Vec<i32> { values.iter().copied().filter(|x| x % 2 == 0).collect() }","assert_eq!(filter_even_values(&[3,2,4,1,0]),vec![2,4,0]); assert_eq!(filter_even_values(&[]),vec![]);"),
 ("first_nonempty_word","def first_nonempty_word(words: list[str]) -> str | None: return the first nonempty string","def first_nonempty_word(words):\n    return next((word for word in words if word), None)","assert first_nonempty_word(['','','hi','x']) == 'hi'\nassert first_nonempty_word(['','']) is None",
  "pub fn first_nonempty_word<'a>(words: &'a [&'a str]) -> Option<&'a str>: return the first nonempty string","pub fn first_nonempty_word<'a>(words: &'a [&'a str]) -> Option<&'a str> { words.iter().copied().find(|word| !word.is_empty()) }","assert_eq!(first_nonempty_word(&[\"\",\"\",\"hi\",\"x\"]),Some(\"hi\")); assert_eq!(first_nonempty_word(&[\"\",\"\"]),None);"),
 ("count_words","def count_words(text: str) -> int: count whitespace separated words","def count_words(text):\n    return len(text.split())","assert count_words(' one\\t two\\nthree ') == 3\nassert count_words('   ') == 0",
  "pub fn count_words(text: &str) -> usize: count whitespace separated words","pub fn count_words(text: &str) -> usize { text.split_whitespace().count() }","assert_eq!(count_words(\" one\\t two\\nthree \"),3); assert_eq!(count_words(\"   \"),0);"),
 ("all_values_in_range","def all_values_in_range(values: list[int], low: int, high: int) -> bool: true when every value is within inclusive bounds","def all_values_in_range(values, low, high):\n    return all(low <= value <= high for value in values)","assert all_values_in_range([-2,0,3],-2,3)\nassert not all_values_in_range([4],-2,3)\nassert all_values_in_range([],-2,3)",
  "pub fn all_values_in_range(values: &[i32], low: i32, high: i32) -> bool: true when every value is within inclusive bounds","pub fn all_values_in_range(values: &[i32], low: i32, high: i32) -> bool { values.iter().all(|&x| low <= x && x <= high) }","assert!(all_values_in_range(&[-2,0,3],-2,3)); assert!(!all_values_in_range(&[4],-2,3)); assert!(all_values_in_range(&[],-2,3));"),
 ("is_ascii_identifier","def is_ascii_identifier(text: str) -> bool: nonempty ASCII identifier; first char letter or underscore, rest letters digits or underscore","def is_ascii_identifier(text):\n    if not text or not (text[0].isascii() and (text[0].isalpha() or text[0] == '_')):\n        return False\n    return all(ch.isascii() and (ch.isalnum() or ch == '_') for ch in text[1:])","assert is_ascii_identifier('_a2')\nassert not is_ascii_identifier('2a')\nassert not is_ascii_identifier(chr(233))\nassert not is_ascii_identifier('')",
  "pub fn is_ascii_identifier(text: &str) -> bool: nonempty ASCII identifier; first char letter or underscore, rest letters digits or underscore","pub fn is_ascii_identifier(text: &str) -> bool { let mut b=text.bytes(); match b.next() { Some(x) if x.is_ascii_alphabetic() || x==b'_' => b.all(|y| y.is_ascii_alphanumeric() || y==b'_'), _ => false } }","assert!(is_ascii_identifier(\"_a2\")); assert!(!is_ascii_identifier(\"2a\")); assert!(!is_ascii_identifier(&char::from_u32(233).unwrap().to_string())); assert!(!is_ascii_identifier(\"\"));"),
 ("checked_i32_sum","def checked_i32_sum(values: list[int]) -> int | None: sum values, returning None if the result is outside signed 32 bit range","def checked_i32_sum(values):\n    total = sum(values)\n    return total if -(2**31) <= total <= 2**31 - 1 else None","assert checked_i32_sum([2,-1,4]) == 5\nassert checked_i32_sum([]) == 0\nassert checked_i32_sum([2**31-1,1]) is None",
  "pub fn checked_i32_sum(values: &[i32]) -> Option<i32>: sum values, returning None on signed 32 bit overflow","pub fn checked_i32_sum(values: &[i32]) -> Option<i32> { values.iter().try_fold(0i32, |sum, &value| sum.checked_add(value)) }","assert_eq!(checked_i32_sum(&[2,-1,4]),Some(5)); assert_eq!(checked_i32_sum(&[]),Some(0)); assert_eq!(checked_i32_sum(&[i32::MAX,1]),None);"),
 ("count_uppercase_ascii","def count_uppercase_ascii(text: str) -> int: count uppercase ASCII letters only","def count_uppercase_ascii(text):\n    return sum('A' <= ch <= 'Z' for ch in text)","assert count_uppercase_ascii('Viv AI 3') == 3\nassert count_uppercase_ascii(chr(233)) == 0",
  "pub fn count_uppercase_ascii(text: &str) -> usize: count uppercase ASCII letters only","pub fn count_uppercase_ascii(text: &str) -> usize { text.bytes().filter(|b| b.is_ascii_uppercase()).count() }","assert_eq!(count_uppercase_ascii(\"Viv AI 3\"),3); assert_eq!(count_uppercase_ascii(&char::from_u32(233).unwrap().to_string()),0);"),
 ("longest_ascii_word","def longest_ascii_word(words: list[str]) -> str | None: longest ASCII word; ties keep first; None when empty","def longest_ascii_word(words):\n    return max(words, key=len, default=None)","assert longest_ascii_word(['cat','horse','tiger']) == 'horse'\nassert longest_ascii_word(['aa','bb']) == 'aa'\nassert longest_ascii_word([]) is None",
  "pub fn longest_ascii_word<'a>(words: &'a [&'a str]) -> Option<&'a str>: longest ASCII word; ties keep first; None when empty","pub fn longest_ascii_word<'a>(words: &'a [&'a str]) -> Option<&'a str> { let mut best=None; for &word in words { if best.map_or(true, |current: &str| word.len()>current.len()) { best=Some(word); } } best }","assert_eq!(longest_ascii_word(&[\"cat\",\"horse\",\"tiger\"]),Some(\"horse\")); assert_eq!(longest_ascii_word(&[\"aa\",\"bb\"]),Some(\"aa\")); assert_eq!(longest_ascii_word(&[]),None);"),
]

def h(obj):return hashlib.sha256(json.dumps(obj,ensure_ascii=False,sort_keys=True,separators=(",",":")).encode()).hexdigest()
def fh(path):
 d=hashlib.sha256()
 with path.open('rb') as f:
  for block in iter(lambda:f.read(1024*1024),b''):d.update(block)
 return d.hexdigest()
def req(path,payload=None):
 data=None if payload is None else json.dumps(payload).encode();r=urllib.request.Request(API+path,data=data,headers={"Content-Type":"application/json"} if data else {})
 with urllib.request.urlopen(r,timeout=300) as x:return json.load(x)
def name(spec,lang):
 m=re.search((r'def\s+([A-Za-z_]\w*)' if lang=='python' else r'pub\s+fn\s+([A-Za-z_]\w*)'),spec)
 if not m:raise ValueError('missing function name')
 return m.group(1)

def main():
 if DATA_OUT.exists() or OUT.exists() or DEST.exists():raise FileExistsError('epoch_10013 output exists')
 suite=json.loads(SUITE.read_text(encoding='utf-8'));sh=suite.pop('suite_sha256')
 if h(suite)!=sh:raise ValueError('held-out suite receipt mismatch')
 held_ids={x['id'] for x in suite['held_out']};held_names={lang:{name(x['spec'],lang) for x in suite['held_out'] if x['lang']==lang} for lang in ('python','rust')}
 samples=[];gates_seen=[]
 for base,ps,pc,pt,rs,rc,rt in PAIRS:
  if name(ps,'python') in held_names['python'] or name(rs,'rust') in held_names['rust']:raise ValueError('held-out function-name overlap')
  for lang,spec,code,tests in [('python',ps,pc,pt),('rust',rs,rc,rt)]:
   task_id=f"pair_{base}_{'py' if lang=='python' else 'rs'}"
   if task_id in held_ids:raise ValueError('held-out task ID overlap')
   if lang=='python':passed,error=gates.gate_python(code,tests)
   else:passed,error=gates.gate_rust(code,"#[cfg(test)] mod t { use super::*; #[test] fn cases(){ "+tests+" } }")
   gates_seen.append({'id':task_id,'lang':lang,'passed':bool(passed),'error':error[:1500]})
   if not passed:raise RuntimeError(f'{task_id} gate failed: {error}')
   prompt=f"SYSTEM: Implement one self-contained standard-library {lang} function. Return one fenced code block only.\n\nUSER: Implement: {spec}\n\nASSISTANT:"
   samples.append({'id':task_id,'category':f'{lang}_paired_gate_verified_v1','prompt':prompt,'completion':f'{FENCE}{lang}\n{code}\n{FENCE}{EOS}','pair_id':base,'source_kind':'paired_local_reference_passed_existing_gate'})
 if len(samples)!=20 or any(not x['passed'] for x in gates_seen):raise ValueError('paired gate acceptance/count invariant failed')
 data={'schema':'viv_candidate_paired_training_v1','created_utc':datetime.now(timezone.utc).isoformat(),'parent_candidate':str(PARENT),'heldout_suite_sha256':sh,'python_unique':10,'rust_unique':10,'heldout_id_overlap':[],'heldout_function_name_overlap':[],'gate_results':gates_seen,'samples':samples,'training_sha256':h(samples)};data['receipt_sha256']=h(data)
 DATA_OUT.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
 before=req('/v1/status')
 if before.get('status')!='ACTIVE' or before.get('active_adapter')!=LIVE.name:raise RuntimeError('unexpected tutor: '+json.dumps(before))
 trainer.ADAPTERS_ROOT=ROOT;trainer.RECEIPTS_FILE=ROOT/'training_receipts.jsonl';rows=samples*2
 run={'schema':'viv_candidate_paired_training_run_v1','created_utc':datetime.now(timezone.utc).isoformat(),'dataset':str(DATA_OUT),'dataset_sha256':data['receipt_sha256'],'training_sha256':h(rows),'unique_samples':20,'training_rows':len(rows),'steps_requested':STEPS,'learning_rate':LR,'seed':SEED,'parent':str(PARENT),'parent_sha256':fh(PARENT/'adapter_model.safetensors'),'heldout_suite_sha256':sh,'live_before':before,'promoted':False}
 quiesced=False;error=None
 try:
  q=req('/v1/quiesce',{})
  if q.get('status')!='QUIESCED':raise RuntimeError('quiesce failed '+json.dumps(q))
  quiesced=True
  import torch
  from transformers import set_seed
  random.seed(SEED);torch.manual_seed(SEED);set_seed(SEED)
  if torch.cuda.is_available():torch.cuda.manual_seed_all(SEED)
  result=trainer.run_sleep_training(epoch=10013,steps=STEPS,lr=LR,parent_adapter=PARENT,training_samples=rows)
  if not result.get('ok'):raise RuntimeError('trainer failed '+json.dumps(result))
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
 print(json.dumps({'dataset':str(DATA_OUT),'paired_examples':10,'languages':['python','rust'],'all_gates_passed':len(gates_seen),'training_status':run['status'],'steps':STEPS,'learning_rate':LR,'candidate_sha256':run.get('candidate_sha256'),'live_restored':run['live_restored'],'active_adapter':run.get('live_after',{}).get('active_adapter'),'error':error,'promoted':False},indent=2),flush=True)
 return 0 if run['status']=='TRAINED_CANDIDATE' and run['live_restored'] else 1
if __name__=='__main__':raise SystemExit(main())
