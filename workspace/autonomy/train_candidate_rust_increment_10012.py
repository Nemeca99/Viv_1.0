"""Train a low-rate Rust-only branch from the strongest measured candidate."""
from __future__ import annotations
from datetime import datetime, timezone
import hashlib, json, random, re, sys, urllib.request
from pathlib import Path

HERE=Path(__file__).resolve().parent
WS=HERE.parent
sys.path[:0]=[str(WS),str(HERE)]
import viv_sleep_trainer as trainer

API="http://127.0.0.1:1234"
LIVE=Path(r"E:\Viv_Sandbox\playground\adapters\epoch_10001")
ROOT=Path(r"F:\LocalCoder_Archive\Viv_model_candidates")
PARENT=ROOT/"epoch_10008"
DEST=ROOT/"epoch_10012"
RUNS=HERE/"learning"/"deepseek_candidate_runs"
SOURCE=RUNS/"candidate_coding_training_v3.json"
SUITE=RUNS/"frozen_code_eval_v2_1.json"
DATA_OUT=RUNS/"candidate_rust_training_10012.json"
OUT=RUNS/"candidate_rust_training_run_10012.json"
SEED,LR,STEPS=20261120,1e-6,32

def obj_hash(value:object)->str:
    return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(",",":")).encode()).hexdigest()
def file_hash(path:Path)->str:
    h=hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda:stream.read(1024*1024),b""):h.update(block)
    return h.hexdigest()
def request(path:str,payload:dict|None=None)->dict:
    body=None if payload is None else json.dumps(payload).encode()
    req=urllib.request.Request(API+path,data=body,headers={"Content-Type":"application/json"} if body else {})
    with urllib.request.urlopen(req,timeout=300) as response:return json.load(response)
def function_name(text:str)->str:
    match=re.search(r"pub\s+fn\s+([A-Za-z_]\w*)\s*\(",text)
    if not match:raise ValueError("training reference has no Rust function signature")
    return match.group(1)

def main()->int:
    if DATA_OUT.exists() or OUT.exists() or DEST.exists():raise FileExistsError("epoch_10012 artifact already exists")
    source=json.loads(SOURCE.read_text(encoding="utf-8")); source_hash=source.pop("receipt_sha256")
    if obj_hash(source)!=source_hash or obj_hash(source["samples"])!=source["training_sha256"]:raise ValueError("source training receipt/hash invalid")
    suite=json.loads(SUITE.read_text(encoding="utf-8")); suite_hash=suite.pop("suite_sha256")
    if obj_hash(suite)!=suite_hash or suite_hash!=source["heldout_suite_sha256"]:raise ValueError("frozen suite hash mismatch")
    held=[x for x in suite["held_out"] if x["lang"]=="rust"]
    held_ids={x["id"] for x in held};held_names={function_name(x["spec"]) for x in held}
    samples=[x for x in source["samples"] if x["category"].startswith("rust_")]
    if len(samples)!=16 or any(not x["passed"] for x in source["gate_results"] if x["lang"]=="rust"):
        raise ValueError("expected exactly sixteen gate-passed Rust references")
    ids={x["id"] for x in samples};names={function_name(x["completion"]) for x in samples}
    if len(ids)!=16 or len(names)!=16 or ids&held_ids or names&held_names:raise ValueError("Rust training split overlap or duplicate")
    dataset={"schema":"viv_candidate_rust_training_v5","created_utc":datetime.now(timezone.utc).isoformat(),"source_dataset":str(SOURCE),"source_dataset_sha256":source_hash,"heldout_suite_sha256":suite_hash,"heldout_id_overlap":[],"heldout_function_name_overlap":[],"samples":samples,"training_sha256":obj_hash(samples)}
    dataset["receipt_sha256"]=obj_hash(dataset)
    DATA_OUT.write_text(json.dumps(dataset,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    before=request("/v1/status")
    if before.get("status")!="ACTIVE" or before.get("active_adapter")!=LIVE.name:raise RuntimeError("unexpected tutor state: "+json.dumps(before))
    if not (PARENT/"adapter_model.safetensors").is_file():raise FileNotFoundError(PARENT)
    trainer.ADAPTERS_ROOT=ROOT;trainer.RECEIPTS_FILE=ROOT/"training_receipts.jsonl"
    rows=samples*2
    run={"schema":"viv_candidate_rust_training_run_v2","created_utc":datetime.now(timezone.utc).isoformat(),"dataset":str(DATA_OUT),"dataset_sha256":dataset["receipt_sha256"],"training_sha256":obj_hash(rows),"unique_rust_samples":len(samples),"training_rows":len(rows),"steps_requested":STEPS,"learning_rate":LR,"seed":SEED,"parent":str(PARENT),"parent_sha256":file_hash(PARENT/"adapter_model.safetensors"),"heldout_suite_sha256":suite_hash,"live_before":before,"promoted":False}
    quiesced=False;error=None
    try:
        q=request("/v1/quiesce",{})
        if q.get("status")!="QUIESCED":raise RuntimeError("quiesce failed: "+json.dumps(q))
        quiesced=True
        import torch
        from transformers import set_seed
        random.seed(SEED);torch.manual_seed(SEED);set_seed(SEED)
        if torch.cuda.is_available():torch.cuda.manual_seed_all(SEED)
        trained=trainer.run_sleep_training(epoch=10012,steps=STEPS,lr=LR,parent_adapter=PARENT,training_samples=rows)
        if not trained.get("ok"):raise RuntimeError("candidate training failed: "+json.dumps(trained))
        run["training"]=trained;run["candidate_sha256"]=file_hash(DEST/"adapter_model.safetensors");run["status"]="TRAINED_CANDIDATE"
    except Exception as exc:
        error=f"{type(exc).__name__}: {exc}";run["status"]="TRAINING_FAILED";run["training_error"]=error
    finally:
        if quiesced:
            try:request("/v1/resume",{"adapter_dir":str(LIVE)})
            except Exception as exc:run["restore_error"]=f"{type(exc).__name__}: {exc}"
    try:
        after=request("/v1/status");run["live_after"]=after;run["live_restored"]=after.get("status")=="ACTIVE" and after.get("active_adapter")==LIVE.name
    except Exception as exc:run["live_restored"]=False;run["restore_status_error"]=f"{type(exc).__name__}: {exc}"
    run["receipt_sha256"]=obj_hash(run);OUT.write_text(json.dumps(run,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({"dataset":str(DATA_OUT),"unique_rust_samples":len(samples),"steps":STEPS,"learning_rate":LR,"status":run["status"],"candidate_sha256":run.get("candidate_sha256"),"live_restored":run["live_restored"],"active_adapter":run.get("live_after",{}).get("active_adapter"),"error":error,"promoted":False},indent=2),flush=True)
    return 0 if run["status"]=="TRAINED_CANDIDATE" and run["live_restored"] else 1

if __name__=="__main__":raise SystemExit(main())
