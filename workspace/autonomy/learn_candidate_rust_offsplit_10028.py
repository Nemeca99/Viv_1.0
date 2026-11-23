"""Generate Rust-only off-split proposals through the existing candidate DB gate."""
from __future__ import annotations
from datetime import datetime,timezone
import hashlib,json,re,sys
from pathlib import Path
HERE=Path(__file__).resolve().parent
ROOT=HERE.parent
sys.path[:0]=[str(ROOT),str(HERE)]
import candidate_function_learning_loop as learner
import candidate_verified_function_store as store
from aios_rebuild.privacy_core.privacy_core import PrivacyCore
CANDIDATE=Path(r'F:\LocalCoder_Archive\Viv_model_candidates\epoch_10027')
OUT=HERE/'learning'/'neural_runs'/'candidate_rust_offsplit_learning_10028.json'
TASKS=[
 {'name':'checked_factorial','spec':'pub fn checked_factorial(n: u32) -> Option<u64>: return n factorial using checked multiplication; return None if the result overflows u64; 0 factorial is 1','tests':'#[cfg(test)] mod t { use super::*; #[test] fn cases(){ assert_eq!(checked_factorial(0),Some(1)); assert_eq!(checked_factorial(1),Some(1)); assert_eq!(checked_factorial(5),Some(120)); assert_eq!(checked_factorial(30),None); } }'},
 {'name':'fibonacci_checked','spec':'pub fn fibonacci_checked(n: u32) -> Option<u64>: return the nth Fibonacci number with F(0)=0 and F(1)=1; return None if addition overflows u64','tests':'#[cfg(test)] mod t { use super::*; #[test] fn cases(){ assert_eq!(fibonacci_checked(0),Some(0)); assert_eq!(fibonacci_checked(1),Some(1)); assert_eq!(fibonacci_checked(10),Some(55)); assert_eq!(fibonacci_checked(94),None); } }'},
 {'name':'is_prime','spec':'pub fn is_prime(n: u64) -> bool: determine whether n is prime; values below 2 are not prime; avoid overflow for large u64 inputs','tests':'#[cfg(test)] mod t { use super::*; #[test] fn cases(){ assert!(!is_prime(0)); assert!(!is_prime(1)); assert!(is_prime(2)); assert!(is_prime(97)); assert!(!is_prime(100)); assert!(!is_prime(u64::MAX)); } }'},
 {'name':'greatest_common_divisor','spec':'pub fn greatest_common_divisor(a: u64, b: u64) -> u64: return the nonnegative greatest common divisor using Euclid; define gcd(0,0) as 0','tests':'#[cfg(test)] mod t { use super::*; #[test] fn cases(){ assert_eq!(greatest_common_divisor(0,0),0); assert_eq!(greatest_common_divisor(0,12),12); assert_eq!(greatest_common_divisor(54,24),6); assert_eq!(greatest_common_divisor(17,13),1); } }'},
 {'name':'integer_square_root','spec':'pub fn integer_square_root(n: u64) -> u64: return floor(sqrt(n)) exactly without floating point and without overflow','tests':'#[cfg(test)] mod t { use super::*; #[test] fn cases(){ assert_eq!(integer_square_root(0),0); assert_eq!(integer_square_root(1),1); assert_eq!(integer_square_root(15),3); assert_eq!(integer_square_root(16),4); assert_eq!(integer_square_root(u64::MAX),u32::MAX as u64); } }'},
 {'name':'parse_binary_u32','spec':'pub fn parse_binary_u32(text: &str) -> Option<u32>: parse a nonempty string containing only 0 and 1 as base two; return None for empty input, invalid characters, or overflow','tests':'#[cfg(test)] mod t { use super::*; #[test] fn cases(){ assert_eq!(parse_binary_u32("0"),Some(0)); assert_eq!(parse_binary_u32("101101"),Some(45)); assert_eq!(parse_binary_u32(""),None); assert_eq!(parse_binary_u32("102"),None); assert_eq!(parse_binary_u32("111111111111111111111111111111111"),None); } }'},
 {'name':'sum_decimal_digits','spec':'pub fn sum_decimal_digits(n: u64) -> u64: return the sum of the base ten digits; zero returns zero','tests':'#[cfg(test)] mod t { use super::*; #[test] fn cases(){ assert_eq!(sum_decimal_digits(0),0); assert_eq!(sum_decimal_digits(7),7); assert_eq!(sum_decimal_digits(12345),15); assert_eq!(sum_decimal_digits(u64::MAX),87); } }'},
 {'name':'checked_product','spec':'pub fn checked_product(values: &[i64]) -> Option<i64>: return the product using checked multiplication; the empty slice returns Some(1), and overflow returns None','tests':'#[cfg(test)] mod t { use super::*; #[test] fn cases(){ assert_eq!(checked_product(&[]),Some(1)); assert_eq!(checked_product(&[2,3,4]),Some(24)); assert_eq!(checked_product(&[-2,3]),Some(-6)); assert_eq!(checked_product(&[i64::MAX,2]),None); } }'},
]
def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
 if OUT.exists(): raise FileExistsError(f'Refusing overwrite: {OUT}')
 adapter=CANDIDATE/'adapter_model.safetensors'
 if not adapter.is_file(): raise FileNotFoundError(adapter)
 suite=json.loads((store.SUITE_PATH).read_text(encoding='utf-8')); suite.pop('suite_sha256',None)
 held=set()
 for row in suite['held_out']:
  m=re.search(r'\b(?:pub\s+fn|def)\s+([A-Za-z_]\w*)\s*\(',row['spec'])
  if m: held.add((row['lang'],m.group(1)))
 existing={}
 dburi=store.DB_PATH.as_uri()+'?mode=ro'
 import sqlite3
 with sqlite3.connect(dburi,uri=True) as db:
  existing={(r[0],r[1]) for r in db.execute('select language,function_name from functions')}
 for t in TASKS:
  if ('rust',t['name']) in held or ('rust',t['name']) in existing: raise ValueError('TASK_NAME_COLLISION:'+t['name'])
 before_hash=sha(store.DB_PATH); topology=HERE/'viv_code_topology.sqlite3'; memory=ROOT/'aios_rebuild'/'memory'/'persistent_memory.json'
 topology_hash=sha(topology); memory_hash=sha(memory); candidate_hash=sha(adapter)
 before=learner.model_runtime.evaluator.request('/v1/status')
 if before.get('status')!='ACTIVE' or before.get('active_adapter')!=learner.LIVE.name: raise RuntimeError('UNEXPECTED_LIVE_ADAPTER:'+json.dumps(before))
 outcomes=[]
 for t in TASKS:
  task={'id':'candidate_rust_general_10028_'+t['name'],'lang':'rust','spec':t['spec'],'tests':t['tests']}
  result=learner.learn_one(task,domain='rust.core',candidate=CANDIDATE)
  outcomes.append({'task':task,'result':result})
  print(json.dumps({'task':task['id'],'state':result['state'],'proposals':result.get('proposal_count'),'code_sha256':result.get('code_sha256')},ensure_ascii=False),flush=True)
 after=learner.model_runtime.evaluator.request('/v1/status')
 payload={'schema':'viv_candidate_rust_offsplit_learning_v1','created_utc':datetime.now(timezone.utc).isoformat(),'candidate':str(CANDIDATE),'candidate_sha256':candidate_hash,'suite_sha256':store.canonical_hash(suite),'source':'DeepSeek candidate proposals admitted only after existing Rust compiler/test gate ALLOW','tasks':outcomes,'accepted_count':sum(x['result']['state'].startswith('ADMITTED') for x in outcomes),'rejected_or_unadmitted_count':sum(not x['result']['state'].startswith('ADMITTED') for x in outcomes),'candidate_store_path':str(store.DB_PATH),'candidate_store_sha256_before':before_hash,'candidate_store_sha256_after':sha(store.DB_PATH),'topology_sha256_before_after':topology_hash,'persistent_memory_sha256_before_after':memory_hash,'live_before':before,'live_after':after,'live_restored':after.get('status')=='ACTIVE' and after.get('active_adapter')==learner.LIVE.name,'promoted':False,'topology_write':False,'persistent_memory_write':False}
 payload['receipt_sha256']=store.canonical_hash(payload)
 decision=PrivacyCore().authorize_file_write(str(OUT))
 if decision.get('allowed') is not True: raise PermissionError(f'PrivacyCore denied receipt: {decision}')
 with OUT.open('x',encoding='utf-8',newline='\n') as f: f.write(json.dumps(payload,ensure_ascii=False,indent=2)+'\n')
 print(json.dumps({'receipt':str(OUT),'accepted':payload['accepted_count'],'unadmitted':payload['rejected_or_unadmitted_count'],'store_changed':payload['candidate_store_sha256_before']!=payload['candidate_store_sha256_after'],'live_restored':payload['live_restored'],'promoted':False},indent=2),flush=True)
 return 0 if payload['live_restored'] else 1
if __name__=='__main__': raise SystemExit(main())