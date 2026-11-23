"""Longer isolated follow-on training from epoch_10008, preserving the live adapter."""
from __future__ import annotations
from datetime import datetime, timezone
import hashlib,json,random,urllib.request
from pathlib import Path
import sys
HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE.parent))
import viv_sleep_trainer as trainer
API="http://127.0.0.1:1234"
LIVE=Path(r"E:\Viv_Sandbox\playground\adapters\epoch_10001")
PARENT=Path(r"F:\LocalCoder_Archive\Viv_model_candidates\epoch_10008")
ROOT=Path(r"F:\LocalCoder_Archive\Viv_model_candidates")
DEST=ROOT/"epoch_10009"
RUNS=HERE/"learning"/"deepseek_candidate_runs"
DATA=RUNS/"clean_function_training_v2.json"
OUT=RUNS/"clean_function_training_10009.json"
SEED,LR,STEPS=20261117,1e-5,120
def req(path,payload=None):
 raw=None if payload is None else json.dumps(payload).encode()
 q=urllib.request.Request(API+path,data=raw,headers={"Content-Type":"application/json"} if raw else {})
 with urllib.request.urlopen(q,timeout=240) as r:return json.load(r)
def sha_file(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def sh(v):return hashlib.sha256(json.dumps(v,ensure_ascii=False,sort_keys=True,separators=(",",":")).encode()).hexdigest()
def main():
 if DEST.exists() or OUT.exists():raise FileExistsError("candidate/receipt path exists")
 d=json.loads(DATA.read_text(encoding="utf-8")); rh=d.pop("receipt_sha256")
 if sh(d)!=rh or sh(d["samples"])!=d["training_sha256"]:raise ValueError("dataset hash mismatch")
 rows=d["samples"]
 if len(rows)!=60 or sum(x["category"].startswith("python_") for x in rows)!=30 or sum(x["category"].startswith("rust_") for x in rows)!=30:
  raise ValueError("unexpected corpus balance")
 before=req("/v1/status")
 if before.get("status")!="ACTIVE" or before.get("active_adapter")!=LIVE.name:raise RuntimeError(str(before))
 trainer.ADAPTERS_ROOT=ROOT;trainer.RECEIPTS_FILE=ROOT/"training_receipts.jsonl"
 print(json.dumps({"phase":"preflight","dataset_sha256":rh,"unique_rows":len(rows),
  "training_rows":len(rows)*2,"parent":str(PARENT),"candidate":str(DEST),
  "learning_rate":LR,"steps":STEPS},indent=2),flush=True)
 quiesced=False
 try:
  state=req("/v1/quiesce",{})
  if state.get("status")!="QUIESCED":raise RuntimeError(f"quiesce failed {state}")
  quiesced=True
  import torch
  from transformers import set_seed
  random.seed(SEED);torch.manual_seed(SEED);set_seed(SEED)
  if torch.cuda.is_available():torch.cuda.manual_seed_all(SEED)
  training_rows=rows*2
  outcome=trainer.run_sleep_training(epoch=10009,steps=STEPS,lr=LR,
       parent_adapter=PARENT,training_samples=training_rows)
  if not outcome.get("ok"):raise RuntimeError(str(outcome))
  receipt={"schema":"viv_clean_function_candidate_training_v3","created_utc":datetime.now(timezone.utc).isoformat(),
   "dataset":str(DATA),"dataset_sha256":rh,"unique_training_sha256":sh(rows),
   "repeated_training_sha256":sh(training_rows),"unique_rows":len(rows),"training_rows":len(training_rows),
   "seed":SEED,"learning_rate":LR,"steps_requested":STEPS,
   "parent":str(PARENT),"parent_sha256":sha_file(PARENT/"adapter_model.safetensors"),
   "candidate":str(DEST),"candidate_sha256":sha_file(DEST/"adapter_model.safetensors"),
   "training":outcome,"live_before":before,"promoted":False}
  receipt["receipt_sha256"]=sh(receipt)
  OUT.write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
  print(json.dumps({"phase":"candidate_saved","candidate_sha256":receipt["candidate_sha256"],
   "loss":outcome["receipt"]["final_loss"],"receipt":str(OUT)},indent=2),flush=True)
 finally:
  if quiesced:req("/v1/resume",{"adapter_dir":str(LIVE)})
 restored=req("/v1/status")
 if restored.get("status")!="ACTIVE" or restored.get("active_adapter")!=LIVE.name:
  raise RuntimeError(f"live adapter not restored {restored}")
 restore={"schema":"viv_candidate_live_restore_v1","training_receipt":str(OUT),
  "created_utc":datetime.now(timezone.utc).isoformat(),"restored_status":restored,"promoted":False}
 restore["receipt_sha256"]=sh(restore)
 rp=RUNS/"clean_function_training_10009_restore.json";rp.write_text(json.dumps(restore,indent=2)+"\n",encoding="utf-8")
 print(json.dumps({"phase":"complete","active_adapter":restored["active_adapter"],
  "restore_receipt":str(rp),"promoted":False},indent=2))
 return 0
if __name__=="__main__":raise SystemExit(main())
