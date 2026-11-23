"""Compile, run, and emit native object code from a passing epoch_10008 Rust answer."""
from __future__ import annotations
from datetime import datetime, timezone
import hashlib,json,subprocess
from pathlib import Path
ROOT=Path(r"L:\LocalCoder\workspace")
RUNS=ROOT/"autonomy"/"learning"/"deepseek_candidate_runs"
EVAL=RUNS/"frozen_eval_v1_20261111T035551Z.json"
ADAPTER=Path(r"F:\LocalCoder_Archive\Viv_model_candidates\epoch_10008")
OUT=Path(r"F:\LocalCoder_Archive\Viv_model_candidates\compiled_machine_proofs\epoch_10008_rs_merge_sorted")
def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
 if OUT.exists(): raise FileExistsError(OUT)
 d=json.loads(EVAL.read_text(encoding="utf-8")); rh=d.pop("receipt_sha256")
 canon=json.dumps(d,ensure_ascii=False,sort_keys=True,separators=(",",":")).encode()
 if hashlib.sha256(canon).hexdigest()!=rh: raise ValueError("frozen eval receipt hash mismatch")
 if d["adapter_sha256"]!=sha(ADAPTER/"adapter_model.safetensors"): raise ValueError("candidate adapter hash mismatch")
 row=next((x for x in d["results"] if x["task"]=="hold_rs_merge_sorted" and x["passed"]),None)
 if not row: raise ValueError("no passing Rust generated answer in receipt")
 code=row["code"].strip()
 OUT.mkdir(parents=True)
 src=OUT/"generated_merge_sorted.rs"; tests=OUT/"generated_merge_sorted_tests.rs"
 binary=OUT/"generated_merge_sorted_tests.exe"; obj=OUT/"generated_merge_sorted.obj"
 src.write_text(code+"\n",encoding="utf-8")
 tests.write_text(code+"""
#[cfg(test)]
mod tests {
 use super::merge_sorted;
 #[test]
 fn cases() {
  assert_eq!(merge_sorted(&[1,3,5], &[2,4,6]), vec![1,2,3,4,5,6]);
  assert_eq!(merge_sorted(&[], &[1,2]), vec![1,2]);
  assert_eq!(merge_sorted(&[1,1], &[1,2]), vec![1,1,1,2]);
  assert_eq!(merge_sorted(&[], &[]), Vec::<i32>::new());
 }
}
fn main() {
 assert_eq!(merge_sorted(&[1,3,5], &[2,4,6]), vec![1,2,3,4,5,6]);
}
""",encoding="utf-8")
 comp=subprocess.run(["rustc","--test","--edition","2021",str(tests),"-o",str(binary)],capture_output=True,text=True,timeout=90)
 run=subprocess.run([str(binary)],capture_output=True,text=True,timeout=30) if comp.returncode==0 else None
 emit=subprocess.run(["rustc","--crate-type","lib","--emit=obj","--edition","2021",str(src),"-o",str(obj)],capture_output=True,text=True,timeout=90)
 passed=bool(comp.returncode==0 and run and run.returncode==0 and emit.returncode==0 and obj.is_file() and obj.stat().st_size>0)
 receipt={"schema":"viv_candidate10008_native_machine_code_proof_v1",
  "created_utc":datetime.now(timezone.utc).isoformat(),"eval_receipt":str(EVAL),
  "eval_receipt_sha256":rh,"adapter":str(ADAPTER),"adapter_sha256":sha(ADAPTER/"adapter_model.safetensors"),
  "task":row["task"],"model_generated_rust":code,
  "compile_test_exit":comp.returncode,"compile_test_stderr":comp.stderr[-3000:],
  "run_test_exit":None if run is None else run.returncode,
  "run_test_stdout":"" if run is None else run.stdout[-3000:],
  "run_test_stderr":"" if run is None else run.stderr[-3000:],
  "emit_object_exit":emit.returncode,"emit_object_stderr":emit.stderr[-3000:],
  "object_path":str(obj) if obj.exists() else None,
  "object_size":obj.stat().st_size if obj.exists() else 0,
  "object_sha256":sha(obj) if obj.exists() else None,"passed":passed,"promoted":False}
 receipt["receipt_sha256"]=hashlib.sha256(json.dumps(receipt,ensure_ascii=False,sort_keys=True,separators=(",",":")).encode()).hexdigest()
 rp=OUT/"receipt.json"; rp.write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
 print(json.dumps({"passed":passed,"compile_test_exit":comp.returncode,
  "run_test_exit":receipt["run_test_exit"],"emit_object_exit":emit.returncode,
  "object_size":receipt["object_size"],"object_sha256":receipt["object_sha256"],
  "receipt":str(rp)},indent=2))
 return 0 if passed else 1
if __name__=="__main__": raise SystemExit(main())
