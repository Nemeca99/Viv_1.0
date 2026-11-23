"""Candidate-only Rust-weighted continuation using the verified 10026 off-split corpus."""
from __future__ import annotations
from datetime import datetime, timezone
import hashlib, json, random, sys
from pathlib import Path
HERE=Path(__file__).resolve().parent
WORKSPACE=HERE.parent
sys.path[:0]=[str(WORKSPACE),str(HERE)]
import train_candidate_mixed_coding_10026 as source
import viv_sleep_trainer as trainer
from aios_rebuild.privacy_core.privacy_core import PrivacyCore
API=source.API
ROOT=source.ROOT
PARENT=ROOT/"epoch_10026"
DEST=ROOT/"epoch_10027"
NEURAL=HERE/"learning"/"neural_runs"
BASE=NEURAL/"candidate_mixed_training_10026.json"
DATA_OUT=NEURAL/"candidate_rust_weighted_training_10027.json"
RUN_OUT=NEURAL/"candidate_rust_weighted_training_run_10027.json"
SUITE=source.SUITE
SEED=20261130
LR=5e-7
RUST_REPEATS=4
PYTHON_REPEATS=1

def canon(v):
 return hashlib.sha256(json.dumps(v,ensure_ascii=False,sort_keys=True,separators=(",",":")).encode()).hexdigest()
def sha(p):
 h=hashlib.sha256()
 with p.open("rb") as f:
  for b in iter(lambda:f.read(1024*1024),b""): h.update(b)
 return h.hexdigest()
def write_new(path,value):
 auth=PrivacyCore().authorize_file_write(str(path))
 if auth.get("allowed") is not True: raise PermissionError(f"PrivacyCore denied {path}: {auth}")
 with path.open("x",encoding="utf-8",newline="\n") as f: f.write(json.dumps(value,ensure_ascii=False,indent=2)+"\n")
 return auth
def main():
 for p in (BASE,SUITE,PARENT/"adapter_model.safetensors"):
  if not p.is_file(): raise FileNotFoundError(p)
 for p in (DEST,DATA_OUT,RUN_OUT):
  if p.exists(): raise FileExistsError(f"Refusing overwrite: {p}")
 suite=json.loads(SUITE.read_text(encoding="utf-8")); suite_hash=suite.pop("suite_sha256",None)
 if source.canonical_hash(suite)!=suite_hash: raise ValueError("FROZEN_SUITE_HASH_MISMATCH")
 held_ids={str(r["id"]) for r in suite["held_out"]}
 import re
 held_names={(r["lang"],re.search(r"\b(?:def|pub\s+fn)\s+([A-Za-z_]\w*)\s*\(",r["spec"]).group(1)) for r in suite["held_out"]}
 base=json.loads(BASE.read_text(encoding="utf-8")); claimed=base.pop("receipt_sha256",None)
 if canon(base)!=claimed: raise ValueError("BASE_DATASET_RECEIPT_HASH_MISMATCH")
 base["receipt_sha256"]=claimed
 if base.get("frozen_suite_sha256")!=suite_hash or base.get("promoted") is not False: raise ValueError("BASE_DATASET_LINEAGE_INVALID")
 # Revalidate every source receipt and every deterministic gate before reusing samples.
 verified_sources=[]
 for item in base["source_receipts"]:
  path=Path(item["path"]); env,digest=source.validate_source(path,suite_hash)
  if digest!=item["file_sha256"] or env["receipt_sha256"]!=item["receipt_sha256"]: raise ValueError("SOURCE_MANIFEST_HASH_MISMATCH:"+path.name)
  verified_sources.append({"path":str(path),"file_sha256":digest,"receipt_sha256":env["receipt_sha256"],"sample_count":len(env["samples"])})
 samples=base["samples"]
 py=[r for r in samples if r.get("language")=="python"]
 rs=[r for r in samples if r.get("language")=="rust"]
 if len(py)!=13 or len(rs)!=28: raise ValueError(f"UNEXPECTED_COUNTS:py={len(py)} rust={len(rs)}")
 ids=set(); names=set()
 for r in samples:
  lang=r["language"]; ident=str(r["id"]); name=str(r["function_name"])
  if ident in held_ids or (lang,name) in held_names: raise ValueError("HELDOUT_OVERLAP:"+ident)
  if ident in ids or (lang,name) in names: raise ValueError("DUPLICATE_TRAIN_SAMPLE:"+ident)
  ids.add(ident); names.add((lang,name))
  code=source.code_from_sample(r,lang)
  if hashlib.sha256(code.encode()).hexdigest()!=r.get("code_sha256"): raise ValueError("CODE_HASH_MISMATCH:"+ident)
 rows=py*PYTHON_REPEATS+rs*RUST_REPEATS
 random.Random(SEED).shuffle(rows)
 before=source.request("/v1/status")
 if before.get("status")!="ACTIVE" or before.get("active_adapter")!=source.LIVE.name: raise RuntimeError("UNEXPECTED_LIVE_ADAPTER:"+json.dumps(before))
 dataset={"schema":"viv_candidate_rust_weighted_gate_accepted_training_v1","created_utc":datetime.now(timezone.utc).isoformat(),"parent_candidate":str(PARENT),"parent_sha256":sha(PARENT/"adapter_model.safetensors"),"base_training_dataset":str(BASE),"base_dataset_receipt_sha256":claimed,"frozen_suite_path":str(SUITE),"frozen_suite_sha256":suite_hash,"source_receipts":verified_sources,"source_samples":len(samples),"language_counts":{"python":len(py),"rust":len(rs)},"repeat_policy":{"python":PYTHON_REPEATS,"rust":RUST_REPEATS},"training_rows":len(rows),"training_sha256":canon(rows),"heldout_id_overlap":[],"heldout_function_name_overlap":[],"samples":samples,"live_adapter_at_build":before.get("active_adapter"),"promoted":False,"topology_write":False,"persistent_memory_write":False}
 dataset["receipt_sha256"]=canon(dataset)
 auth=write_new(DATA_OUT,dataset)
 import torch
 from transformers import set_seed
 random.seed(SEED); torch.manual_seed(SEED); set_seed(SEED)
 if torch.cuda.is_available(): torch.cuda.manual_seed_all(SEED)
 trainer.ADAPTERS_ROOT=ROOT; trainer.RECEIPTS_FILE=ROOT/"training_receipts.jsonl"
 run={"schema":"viv_candidate_rust_weighted_training_run_v1","created_utc":datetime.now(timezone.utc).isoformat(),"dataset":str(DATA_OUT),"dataset_receipt_sha256":dataset["receipt_sha256"],"training_sha256":dataset["training_sha256"],"source_samples":len(samples),"language_counts":dataset["language_counts"],"training_rows":len(rows),"seed":SEED,"learning_rate":LR,"steps_requested":len(rows),"parent":str(PARENT),"parent_sha256":dataset["parent_sha256"],"frozen_suite_sha256":suite_hash,"live_before":before,"privacy_authorization":auth,"promoted":False,"topology_write":False,"persistent_memory_write":False}
 quiesced=False
 try:
  state=source.request("/v1/quiesce",{})
  if state.get("status")!="QUIESCED": raise RuntimeError("QUIESCE_FAILED:"+json.dumps(state))
  quiesced=True
  result=trainer.run_sleep_training(epoch=10027,steps=len(rows),lr=LR,parent_adapter=PARENT,training_samples=rows)
  if not result.get("ok"): raise RuntimeError("TRAINING_FAILED:"+json.dumps(result))
  run["training"]=result; run["candidate_sha256"]=sha(DEST/"adapter_model.safetensors"); run["status"]="TRAINED_CANDIDATE"
 except Exception as e:
  run["status"]="TRAINING_FAILED"; run["training_error"]=f"{type(e).__name__}: {e}"
 finally:
  if quiesced:
   try: source.request("/v1/resume",{"adapter_dir":str(source.LIVE)})
   except Exception as e: run["restore_error"]=f"{type(e).__name__}: {e}"
 try:
  after=source.request("/v1/status"); run["live_after"]=after; run["live_restored"]=after.get("status")=="ACTIVE" and after.get("active_adapter")==source.LIVE.name
 except Exception as e: run["live_restored"]=False; run["restore_status_error"]=f"{type(e).__name__}: {e}"
 run["receipt_sha256"]=canon(run); write_new(RUN_OUT,run)
 print(json.dumps({"dataset_receipt":str(DATA_OUT),"training_receipt":str(RUN_OUT),"status":run["status"],"candidate_sha256":run.get("candidate_sha256"),"samples":len(samples),"python_rows":len(py)*PYTHON_REPEATS,"rust_rows":len(rs)*RUST_REPEATS,"training_rows":len(rows),"live_restored":run.get("live_restored"),"active_adapter":run.get("live_after",{}).get("active_adapter"),"promoted":False},indent=2),flush=True)
 return 0 if run["status"]=="TRAINED_CANDIDATE" and run.get("live_restored") else 1
if __name__=="__main__": raise SystemExit(main())