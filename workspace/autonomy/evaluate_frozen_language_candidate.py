"""Evaluate one language half of the frozen 100-task suite on a candidate."""
from __future__ import annotations
from datetime import datetime,timezone
import json,os,sys,uuid
from pathlib import Path
HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE))
import candidate_coding_runtime_v1 as runtime
SUITE=HERE/"learning"/"deepseek_candidate_runs"/"frozen_code_eval_v2_1.json"
CANDIDATE=Path(os.environ.get("VIV_CODE_CANDIDATE",r"F:\LocalCoder_Archive\Viv_model_candidates\epoch_10012"))
LANG=os.environ.get("VIV_CODE_EVAL_LANG","python").lower()
LIVE=runtime.LIVE
RUNS=HERE/"learning"/"deepseek_candidate_runs"
def main()->int:
    if LANG not in ("python","rust"):raise ValueError("language must be python or rust")
    envelope=json.loads(SUITE.read_text(encoding="utf-8"));suite_hash=envelope.pop("suite_sha256")
    if runtime.canonical_hash(envelope)!=suite_hash:raise ValueError("frozen suite hash mismatch")
    tasks=[x for x in envelope["held_out"] if x["lang"]==LANG]
    if len(tasks)!=50:raise ValueError(f"expected 50 {LANG} tasks, got {len(tasks)}")
    before=runtime.evaluator.request("/v1/status")
    if before.get("status")!="ACTIVE" or before.get("active_adapter")!=LIVE.name:raise RuntimeError("unexpected tutor state: "+json.dumps(before))
    results=[];restored=None
    try:
        runtime.evaluator.activate(CANDIDATE)
        for task in tasks:results.append(runtime.run_task(task,CANDIDATE))
    finally:restored=runtime.evaluator.activate(LIVE)
    score={"first_pass":sum(x["first_pass"] for x in results),"final_pass":sum(x["final_pass"] for x in results),"total":len(results)}
    payload={"schema":"viv_candidate_frozen_language_eval_v1","created_utc":datetime.now(timezone.utc).isoformat(),"language":LANG,"suite_path":str(SUITE),"suite_sha256":suite_hash,"candidate_path":str(CANDIDATE),"candidate_sha256":runtime.sha256(CANDIDATE/"adapter_model.safetensors"),"runtime_prompt_sha256":runtime.sha256(Path(runtime.__file__).resolve()),"evaluator_script_sha256":runtime.sha256(Path(__file__).resolve()),"generation":{"temperature":runtime.GENERATION_TEMPERATURE,"do_sample":runtime.GENERATION_TEMPERATURE>0.05},"attempt_limit":runtime.MAX_ATTEMPTS,"score":score,"results":results,"live_before":before,"live_restored":restored,"promoted":False,"topology_write":False,"persistent_memory_write":False}
    payload["receipt_sha256"]=runtime.canonical_hash(payload)
    target=RUNS/f"candidate_{LANG}_eval_{CANDIDATE.name}_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')}_{uuid.uuid4().hex[:8]}.json"
    target.write_text(json.dumps(payload,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({"receipt":str(target),"language":LANG,"candidate_sha256":payload["candidate_sha256"],"score":score,"live_restored":restored.get("active_adapter"),"promoted":False},indent=2),flush=True)
    return 0 if restored.get("active_adapter")==LIVE.name else 1
if __name__=="__main__":raise SystemExit(main())
