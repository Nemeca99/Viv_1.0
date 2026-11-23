"""Train and receipt an isolated function-format coding candidate."""
from __future__ import annotations
from datetime import datetime, timezone
import hashlib, json, random, urllib.request
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
WORKSPACE = HERE.parent
sys.path.insert(0, str(WORKSPACE))
import viv_sleep_trainer as trainer

API = "http://127.0.0.1:1234"
LIVE = Path(r"E:\Viv_Sandbox\playground\adapters\epoch_10001")
ROOT = Path(r"F:\LocalCoder_Archive\Viv_model_candidates")
DEST = ROOT / "epoch_10008"
RUNS = HERE / "learning" / "deepseek_candidate_runs"
DATA = RUNS / "clean_function_training_v2.json"
OUT = RUNS / "clean_function_training_10008.json"
SEED, LR, STEPS = 20261116, 5e-6, 60

def req(path: str, payload: dict | None = None) -> dict:
    raw = None if payload is None else json.dumps(payload).encode()
    q = urllib.request.Request(API + path, data=raw,
        headers={"Content-Type":"application/json"} if raw else {})
    with urllib.request.urlopen(q, timeout=240) as r:
        return json.load(r)

def sha_file(path: Path) -> str:
    h=hashlib.sha256()
    with path.open("rb") as f:
        for b in iter(lambda:f.read(1024*1024),b""): h.update(b)
    return h.hexdigest()

def sha_obj(v: object) -> str:
    return hashlib.sha256(json.dumps(v,ensure_ascii=False,sort_keys=True,separators=(",",":")).encode()).hexdigest()

def main() -> int:
    if DEST.exists() or OUT.exists(): raise FileExistsError("candidate/receipt already exists")
    d=json.loads(DATA.read_text(encoding="utf-8")); rh=d.pop("receipt_sha256")
    if sha_obj(d)!=rh or sha_obj(d["samples"])!=d["training_sha256"]:
        raise ValueError("training dataset hash mismatch")
    rows=d["samples"]
    py=[x for x in rows if x["category"].startswith("python_")]
    rs=[x for x in rows if x["category"].startswith("rust_")]
    if len(py)!=30 or len(rs)!=30: raise ValueError(f"unexpected balanced sample counts {len(py)}:{len(rs)}")
    live=req("/v1/status")
    if live.get("status")!="ACTIVE" or live.get("active_adapter")!=LIVE.name:
        raise RuntimeError(f"wrong initial live adapter: {live}")
    trainer.ADAPTERS_ROOT=ROOT
    trainer.RECEIPTS_FILE=ROOT/"training_receipts.jsonl"
    print(json.dumps({"phase":"preflight","dataset_sha256":rh,"samples":len(rows),
        "python":len(py),"rust":len(rs),"parent":str(LIVE),"candidate":str(DEST),
        "lr":LR,"steps":STEPS},indent=2),flush=True)
    quiesced=False
    try:
        state=req("/v1/quiesce",{})
        if state.get("status")!="QUIESCED": raise RuntimeError(f"quiesce failed: {state}")
        quiesced=True
        import torch
        from transformers import set_seed
        random.seed(SEED); torch.manual_seed(SEED); set_seed(SEED)
        if torch.cuda.is_available(): torch.cuda.manual_seed_all(SEED)
        outcome=trainer.run_sleep_training(epoch=10008,steps=STEPS,lr=LR,
            parent_adapter=LIVE,training_samples=rows)
        if not outcome.get("ok"): raise RuntimeError(f"training failed: {outcome}")
        receipt={"schema":"viv_clean_function_candidate_training_v2",
            "created_utc":datetime.now(timezone.utc).isoformat(),"dataset":str(DATA),
            "dataset_sha256":rh,"training_sha256":sha_obj(rows),
            "python_samples":len(py),"rust_samples":len(rs),"seed":SEED,
            "learning_rate":LR,"steps_requested":STEPS,"parent":str(LIVE),
            "parent_sha256":sha_file(LIVE/"adapter_model.safetensors"),
            "candidate":str(DEST),"candidate_sha256":sha_file(DEST/"adapter_model.safetensors"),
            "training":outcome,"live_before":live,"promoted":False}
        receipt["receipt_sha256"]=sha_obj(receipt)
        OUT.write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
        print(json.dumps({"phase":"candidate_saved","path":str(DEST),
            "sha256":receipt["candidate_sha256"],"loss":outcome["receipt"]["final_loss"],
            "receipt":str(OUT)},indent=2),flush=True)
    finally:
        if quiesced: req("/v1/resume",{"adapter_dir":str(LIVE)})
    restored=req("/v1/status")
    if restored.get("status")!="ACTIVE" or restored.get("active_adapter")!=LIVE.name:
        raise RuntimeError(f"live adapter restore failed: {restored}")
    restore={"schema":"viv_candidate_live_restore_v1","created_utc":datetime.now(timezone.utc).isoformat(),
        "training_receipt":str(OUT),"restored_status":restored,"promoted":False}
    restore["receipt_sha256"]=sha_obj(restore)
    rp=RUNS/"clean_function_training_10008_restore.json"
    rp.write_text(json.dumps(restore,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({"phase":"complete","active_adapter":restored["active_adapter"],
        "restore_receipt":str(rp),"promoted":False},indent=2))
    return 0

if __name__=="__main__": raise SystemExit(main())
