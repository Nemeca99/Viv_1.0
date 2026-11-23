"""Generate and gate a second, off-split Rust transfer curriculum."""
from __future__ import annotations
from datetime import datetime, timezone
import hashlib, json, re, sqlite3, sys
from pathlib import Path

HERE=Path(__file__).resolve().parent
ROOT=HERE.parent
sys.path[:0]=[str(ROOT),str(HERE)]
import candidate_function_learning_loop as learner
import candidate_verified_function_store as store
from aios_rebuild.privacy_core.privacy_core import PrivacyCore

CANDIDATE=Path(r"F:\LocalCoder_Archive\Viv_model_candidates\epoch_10027")
OUT=HERE/"learning"/"neural_runs"/"candidate_rust_transfer_learning_10034.json"
TASKS=[
 {"name":"rotate_bytes_right","spec":"pub fn rotate_bytes_right(values: &[u8], k: usize) -> Vec<u8>: rotate right by k positions with wraparound; empty input stays empty and zero rotation preserves the input","tests":'#[cfg(test)] mod t { use super::*; #[test] fn cases(){ assert_eq!(rotate_bytes_right(&[1,2,3,4],1),vec![4,1,2,3]); assert_eq!(rotate_bytes_right(&[1,2,3],5),vec![2,3,1]); assert_eq!(rotate_bytes_right(&[1,2],0),vec![1,2]); assert_eq!(rotate_bytes_right(&[],9),Vec::<u8>::new()); } }'},
 {"name":"stable_unique_bytes","spec":"pub fn stable_unique_bytes(values: &[u8]) -> Vec<u8>: keep only the first occurrence of each byte, preserving original order; empty input returns empty","tests":'#[cfg(test)] mod t { use super::*; #[test] fn cases(){ assert_eq!(stable_unique_bytes(&[3,1,3,2,1]),vec![3,1,2]); assert_eq!(stable_unique_bytes(&[]),Vec::<u8>::new()); assert_eq!(stable_unique_bytes(&[7]),vec![7]); } }'},
 {"name":"middle_pair_mean","spec":"pub fn middle_pair_mean(sorted: &[i32]) -> Option<f64>: input is ascending; return the middle value for odd length or mean of the two middle values for even length; return None for empty input","tests":'#[cfg(test)] mod t { use super::*; #[test] fn cases(){ assert_eq!(middle_pair_mean(&[]),None); assert_eq!(middle_pair_mean(&[4]),Some(4.0)); assert_eq!(middle_pair_mean(&[1,4,9]),Some(4.0)); assert_eq!(middle_pair_mean(&[1,4,8,10]),Some(6.0)); assert_eq!(middle_pair_mean(&[-5,5]),Some(0.0)); } }'},
 {"name":"common_suffix","spec":"pub fn common_suffix(words: &[&str]) -> String: return the longest suffix shared by every word; empty input returns an empty String; if any word is empty, return empty","tests":'#[cfg(test)] mod t { use super::*; #[test] fn cases(){ assert_eq!(common_suffix(&["walking","talking","barking"]),"king"); assert_eq!(common_suffix(&["abc","xbc"]),"bc"); assert_eq!(common_suffix(&["abc","xyz"]),""); assert_eq!(common_suffix(&[]),""); assert_eq!(common_suffix(&["","abc"]),""); } }'},
 {"name":"count_sign_changes","spec":"pub fn count_sign_changes(values: &[i32]) -> usize: map values to negative, zero, or positive and count adjacent transitions between different sign classes; fewer than two values returns zero","tests":'#[cfg(test)] mod t { use super::*; #[test] fn cases(){ assert_eq!(count_sign_changes(&[-2,-1,0,0,3,-4]),3); assert_eq!(count_sign_changes(&[]),0); assert_eq!(count_sign_changes(&[0]),0); assert_eq!(count_sign_changes(&[1,2,3]),0); } }'},
 {"name":"merge_overlapping_ranges","spec":"pub fn merge_overlapping_ranges(ranges: &[(i32,i32)]) -> Vec<(i32,i32)>: sort ranges by start and merge ranges that overlap; ranges that only touch at one endpoint remain separate; empty input returns empty","tests":'#[cfg(test)] mod t { use super::*; #[test] fn cases(){ assert_eq!(merge_overlapping_ranges(&[(5,8),(1,3),(2,6),(10,12)]),vec![(1,8),(10,12)]); assert_eq!(merge_overlapping_ranges(&[]),Vec::<(i32,i32)>::new()); assert_eq!(merge_overlapping_ranges(&[(1,2),(2,4)]),vec![(1,2),(2,4)]); assert_eq!(merge_overlapping_ranges(&[(4,5)]),vec![(4,5)]); } }'},
 {"name":"ascii_word_initial_bytes","spec":"pub fn ascii_word_initial_bytes(text: &str) -> Vec<u8>: return the ASCII uppercase first byte of each nonempty whitespace-separated word; ignore words whose first byte is not ASCII alphabetic","tests":'#[cfg(test)] mod t { use super::*; #[test] fn cases(){ assert_eq!(ascii_word_initial_bytes("rust and PYTHON"),vec![b\'R\',b\'A\',b\'P\']); assert_eq!(ascii_word_initial_bytes(""),Vec::<u8>::new()); assert_eq!(ascii_word_initial_bytes("  7zip élan"),vec![b\'Z\']); } }'},
 {"name":"cumulative_products_checked","spec":"pub fn cumulative_products_checked(values: &[i32]) -> Option<Vec<i64>>: return each inclusive prefix product in i64 using checked multiplication; empty input returns Some(empty vector); return None on overflow","tests":'#[cfg(test)] mod t { use super::*; #[test] fn cases(){ assert_eq!(cumulative_products_checked(&[2,3,4]),Some(vec![2,6,24])); assert_eq!(cumulative_products_checked(&[]),Some(vec![])); assert_eq!(cumulative_products_checked(&[-2,0,7]),Some(vec![-2,0,0])); assert_eq!(cumulative_products_checked(&[i32::MAX,2,2]),Some(vec![i32::MAX as i64,(i32::MAX as i64)*2,(i32::MAX as i64)*4])); } }'},
]

def sha(p:Path)->str: return hashlib.sha256(p.read_bytes()).hexdigest()

def main()->int:
 if OUT.exists(): raise FileExistsError(f"Refusing overwrite: {OUT}")
 adapter=CANDIDATE/"adapter_model.safetensors"
 if not adapter.is_file(): raise FileNotFoundError(adapter)
 suite=json.loads(store.SUITE_PATH.read_text(encoding="utf-8")); sh=suite.pop("suite_sha256",None)
 if sh!=store.canonical_hash(suite): raise ValueError("FROZEN_SUITE_HASH_MISMATCH")
 held_ids={str(t["id"]) for t in suite["held_out"]}; held_names=set()
 for t in suite["held_out"]:
  m=re.search(r"\b(?:pub\s+fn|def)\s+([A-Za-z_]\w*)\s*\(",t["spec"])
  if m: held_names.add((t["lang"],m.group(1)))
 with sqlite3.connect(store.DB_PATH.as_uri()+"?mode=ro",uri=True) as db:
  if db.execute("PRAGMA quick_check").fetchone()[0]!="ok": raise RuntimeError("CANDIDATE_STORE_QUICK_CHECK_FAILED")
  existing={(r[0],r[1]) for r in db.execute("SELECT language,function_name FROM functions")}
 for t in TASKS:
  tid="candidate_rust_transfer_10034_"+t["name"]
  if tid in held_ids or ("rust",t["name"]) in held_names or ("rust",t["name"]) in existing:
   raise ValueError("TASK_OR_FUNCTION_COLLISION:"+t["name"])
 before_store=sha(store.DB_PATH); topology=HERE/"viv_code_topology.sqlite3"
 memory=ROOT/"aios_rebuild"/"memory"/"persistent_memory.json"
 topology_hash,memory_hash=sha(topology),sha(memory); candidate_hash=sha(adapter)
 live_before=learner.model_runtime.evaluator.request("/v1/status")
 if live_before.get("status")!="ACTIVE" or live_before.get("active_adapter")!=learner.LIVE.name:
  raise RuntimeError("UNEXPECTED_LIVE_ADAPTER:"+json.dumps(live_before))
 outcomes=[]
 for spec in TASKS:
  task={"id":"candidate_rust_transfer_10034_"+spec["name"],"lang":"rust","spec":spec["spec"],"tests":spec["tests"]}
  result=learner.learn_one(task,domain="rust.transfer",candidate=CANDIDATE)
  outcomes.append({"task":task,"result":result})
  print(json.dumps({"task":task["id"],"state":result["state"],"proposal_count":result.get("proposal_count"),"code_sha256":result.get("code_sha256")}),flush=True)
 live_after=learner.model_runtime.evaluator.request("/v1/status")
 payload={"schema":"viv_candidate_rust_transfer_learning_v1","created_utc":datetime.now(timezone.utc).isoformat(),
  "candidate":str(CANDIDATE),"candidate_sha256":candidate_hash,"frozen_suite_sha256":sh,
  "source":"candidate-generated proposals; deterministic Rust gate; only ALLOW examples trainable",
  "tasks":outcomes,"accepted_count":sum(x["result"]["state"].startswith("ADMITTED") for x in outcomes),
  "unadmitted_count":sum(not x["result"]["state"].startswith("ADMITTED") for x in outcomes),
  "candidate_store_sha256_before":before_store,"candidate_store_sha256_after":sha(store.DB_PATH),
  "topology_sha256_before":topology_hash,"topology_sha256_after":sha(topology),
  "persistent_memory_sha256_before":memory_hash,"persistent_memory_sha256_after":sha(memory),
  "live_before":live_before,"live_after":live_after,
  "live_restored":live_after.get("status")=="ACTIVE" and live_after.get("active_adapter")==learner.LIVE.name,
  "promoted":False,"topology_write":False,"persistent_memory_write":False}
 payload["receipt_sha256"]=store.canonical_hash(payload)
 auth=PrivacyCore().authorize_file_write(str(OUT))
 if auth.get("allowed") is not True: raise PermissionError(f"PrivacyCore denied receipt: {auth}")
 with OUT.open("x",encoding="utf-8",newline="\n") as f: f.write(json.dumps(payload,ensure_ascii=False,indent=2)+"\n")
 print(json.dumps({"receipt":str(OUT),"accepted":payload["accepted_count"],"unadmitted":payload["unadmitted_count"],"live_restored":payload["live_restored"],"promoted":False},indent=2),flush=True)
 return 0 if payload["live_restored"] else 1

if __name__=="__main__": raise SystemExit(main())
