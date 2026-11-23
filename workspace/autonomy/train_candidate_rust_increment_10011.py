"""Build, gate, and train one small Rust-only candidate increment."""
from __future__ import annotations
from datetime import datetime, timezone
import hashlib, json, random, sys, urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
WS = HERE.parent
sys.path[:0] = [str(WS), str(HERE)]
import viv_code_learning_loop as gates
import viv_sleep_trainer as trainer

API = "http://127.0.0.1:1234"
LIVE = Path(r"E:\Viv_Sandbox\playground\adapters\epoch_10001")
ROOT = Path(r"F:\LocalCoder_Archive\Viv_model_candidates")
PARENT = ROOT / "epoch_10010"
DEST = ROOT / "epoch_10011"
RUNS = HERE / "learning" / "deepseek_candidate_runs"
DATA_OUT = RUNS / "candidate_rust_training_10011.json"
OUT = RUNS / "candidate_rust_training_run_10011.json"
SUITE = RUNS / "frozen_code_eval_v2_1.json"
SEED, LR, STEPS = 20261119, 2.5e-6, 32
EOS = "<｜end▁of▁sentence｜>"
FENCE = chr(96) * 3

# Fresh function names and task IDs, with references checked by the existing Rust gate.
EXAMPLES = [
 ("rs_clamp_slice", "pub fn clamp_slice(values: &[i32], lower: i32, upper: i32) -> Vec<i32>: clamp every value to inclusive bounds", "pub fn clamp_slice(values: &[i32], lower: i32, upper: i32) -> Vec<i32> { values.iter().map(|&x| x.clamp(lower, upper)).collect() }", "assert_eq!(clamp_slice(&[-5,0,8],-2,4),vec![-2,0,4]); assert!(clamp_slice(&[],0,1).is_empty());"),
 ("rs_count_ascii_vowels", "pub fn count_ascii_vowels(text: &str) -> usize: count ASCII vowels in either case", "pub fn count_ascii_vowels(text: &str) -> usize { text.bytes().filter(|b| matches!(b.to_ascii_lowercase(), b'a'|b'e'|b'i'|b'o'|b'u')).count() }", "assert_eq!(count_ascii_vowels(\"Viv AI\"),3); assert_eq!(count_ascii_vowels(\"xyz\"),0);"),
 ("rs_checked_prefix_sums", "pub fn checked_prefix_sums(values: &[i32]) -> Option<Vec<i32>>: return prefix sums or None on i32 overflow", "pub fn checked_prefix_sums(values: &[i32]) -> Option<Vec<i32>> { let mut sum=0i32; let mut out=Vec::with_capacity(values.len()); for &x in values { sum=sum.checked_add(x)?; out.push(sum); } Some(out) }", "assert_eq!(checked_prefix_sums(&[2,-1,4]),Some(vec![2,1,5])); assert_eq!(checked_prefix_sums(&[]),Some(vec![])); assert_eq!(checked_prefix_sums(&[i32::MAX,1]),None);"),
 ("rs_group_parity", "pub fn group_parity(values: &[i32]) -> (Vec<i32>, Vec<i32>): stable even and odd partitions", "pub fn group_parity(values: &[i32]) -> (Vec<i32>, Vec<i32>) { let mut even=Vec::new(); let mut odd=Vec::new(); for &x in values { if x%2==0 { even.push(x); } else { odd.push(x); } } (even,odd) }", "assert_eq!(group_parity(&[3,2,4,1]),(vec![2,4],vec![3,1])); assert_eq!(group_parity(&[]),(vec![],vec![]));"),
 ("rs_first_nonzero", "pub fn first_nonzero(values: &[i32]) -> Option<usize>: index of first nonzero value", "pub fn first_nonzero(values: &[i32]) -> Option<usize> { values.iter().position(|&x| x != 0) }", "assert_eq!(first_nonzero(&[0,0,-2]),Some(2)); assert_eq!(first_nonzero(&[0,0]),None);"),
 ("rs_byte_length_sum", "pub fn byte_length_sum(words: &[&str]) -> usize: total UTF-8 byte length of all strings", "pub fn byte_length_sum(words: &[&str]) -> usize { words.iter().map(|s| s.len()).sum() }", "assert_eq!(byte_length_sum(&[\"ab\",\"é\"]),4); assert_eq!(byte_length_sum(&[]),0);"),
 ("rs_unique_sorted", "pub fn unique_sorted(values: &[i32]) -> Vec<i32>: return sorted ascending distinct values", "pub fn unique_sorted(values: &[i32]) -> Vec<i32> { let mut out=values.to_vec(); out.sort_unstable(); out.dedup(); out }", "assert_eq!(unique_sorted(&[3,1,3,-1,1]),vec![-1,1,3]); assert_eq!(unique_sorted(&[]),vec![]);"),
 ("rs_duration_parts", "pub fn duration_parts(seconds: u64) -> (u64,u64,u64): convert to hours, minutes, remaining seconds", "pub fn duration_parts(seconds: u64) -> (u64,u64,u64) { (seconds/3600,(seconds%3600)/60,seconds%60) }", "assert_eq!(duration_parts(90061),(25,1,1)); assert_eq!(duration_parts(0),(0,0,0));"),
]

def canonical_hash(obj: object) -> str:
    return hashlib.sha256(json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()

def file_hash(path: Path) -> str:
    h=hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda:f.read(1024*1024),b""): h.update(block)
    return h.hexdigest()

def request(path: str, payload: dict | None = None) -> dict:
    raw=None if payload is None else json.dumps(payload).encode()
    req=urllib.request.Request(API+path,data=raw,headers={"Content-Type":"application/json"} if raw else {})
    with urllib.request.urlopen(req,timeout=300) as r: return json.load(r)

def main() -> int:
    if DATA_OUT.exists() or OUT.exists() or DEST.exists(): raise FileExistsError("epoch_10011 output already exists")
    suite=json.loads(SUITE.read_text(encoding="utf-8")); suite_hash=suite.pop("suite_sha256")
    if canonical_hash(suite)!=suite_hash: raise ValueError("held-out suite receipt hash mismatch")
    rust_held=[row for row in suite["held_out"] if row["lang"]=="rust"]
    held_ids={row["id"] for row in rust_held}
    held={row["spec"].split("(")[0].split()[-1] for row in rust_held}
    samples=[]; gate_log=[]
    for task_id,spec,code,checks in EXAMPLES:
        name=spec.split("(")[0].split()[-1]
        if task_id in held_ids or name in held:
            raise ValueError(f"held-out overlap: {task_id}/{name}")
        tests="#[cfg(test)] mod t { use super::*; #[test] fn cases(){ "+checks+" } }"
        passed,error=gates.gate_rust(code,tests)
        gate_log.append({"id":task_id,"passed":bool(passed),"error":error[:2000]})
        if not passed: raise RuntimeError(f"Rust reference failed gate: {task_id}: {error}")
        prompt=f"SYSTEM: You write correct standard-library Rust functions. Return only one fenced code block, no tests or explanation.\n\nUSER: Implement: {spec}\n\nASSISTANT:"
        samples.append({"id":task_id,"category":"rust_gate_verified_v4","prompt":prompt,"completion":f"{FENCE}rust\n{code}\n{FENCE}{EOS}","source_kind":"locally_authored_reference_passed_existing_gate"})
    data={"schema":"viv_candidate_rust_training_v4","created_utc":datetime.now(timezone.utc).isoformat(),"parent_candidate":str(PARENT),"heldout_suite_sha256":suite_hash,"heldout_function_name_overlap":[],"heldout_id_overlap":[],"gate_results":gate_log,"samples":samples,"training_sha256":canonical_hash(samples)}
    data["receipt_sha256"]=canonical_hash(data)
    DATA_OUT.write_text(json.dumps(data,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    before=request("/v1/status")
    if before.get("status")!="ACTIVE" or before.get("active_adapter")!=LIVE.name: raise RuntimeError("live tutor state mismatch: "+json.dumps(before))
    trainer.ADAPTERS_ROOT=ROOT; trainer.RECEIPTS_FILE=ROOT/"training_receipts.jsonl"
    rows=samples*4
    training={"schema":"viv_candidate_rust_training_run_v1","created_utc":datetime.now(timezone.utc).isoformat(),"dataset":str(DATA_OUT),"dataset_sha256":data["receipt_sha256"],"training_sha256":canonical_hash(rows),"unique_rust_samples":len(samples),"training_rows":len(rows),"steps_requested":STEPS,"learning_rate":LR,"seed":SEED,"parent":str(PARENT),"parent_sha256":file_hash(PARENT/"adapter_model.safetensors"),"heldout_suite_sha256":suite_hash,"live_before":before,"promoted":False}
    quiesced=False; error=None; outcome=None
    try:
        q=request("/v1/quiesce",{})
        if q.get("status")!="QUIESCED": raise RuntimeError("quiesce failed: "+json.dumps(q))
        quiesced=True
        import torch
        from transformers import set_seed
        random.seed(SEED); torch.manual_seed(SEED); set_seed(SEED)
        if torch.cuda.is_available(): torch.cuda.manual_seed_all(SEED)
        outcome=trainer.run_sleep_training(epoch=10011,steps=STEPS,lr=LR,parent_adapter=PARENT,training_samples=rows)
        if not outcome.get("ok"): raise RuntimeError("trainer failed: "+json.dumps(outcome))
        training["candidate_sha256"]=file_hash(DEST/"adapter_model.safetensors"); training["training"]=outcome; training["status"]="TRAINED_CANDIDATE"
    except Exception as exc:
        error=f"{type(exc).__name__}: {exc}"; training["status"]="TRAINING_FAILED"; training["training_error"]=error
    finally:
        if quiesced:
            try: request("/v1/resume",{"adapter_dir":str(LIVE)})
            except Exception as exc: training["restore_error"]=f"{type(exc).__name__}: {exc}"
    try:
        restored=request("/v1/status"); training["live_restored"]=restored.get("status")=="ACTIVE" and restored.get("active_adapter")==LIVE.name; training["live_after"]=restored
    except Exception as exc: training["live_restored"]=False; training["restore_status_error"]=f"{type(exc).__name__}: {exc}"
    training["receipt_sha256"]=canonical_hash(training); OUT.write_text(json.dumps(training,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({"dataset":str(DATA_OUT),"gate_passed":len(gate_log),"training_receipt":str(OUT),"status":training["status"],"candidate_sha256":training.get("candidate_sha256"),"live_restored":training["live_restored"],"active_adapter":training.get("live_after",{}).get("active_adapter"),"training_error":error,"promoted":False},indent=2),flush=True)
    return 0 if training["status"]=="TRAINED_CANDIDATE" and training["live_restored"] else 1

if __name__=="__main__": raise SystemExit(main())
