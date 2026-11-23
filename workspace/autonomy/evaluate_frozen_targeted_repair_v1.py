"""Use deterministic gate errors to repair the unresolved frozen tasks."""
from __future__ import annotations
from datetime import datetime,timezone
import hashlib,json,sys,urllib.request
from pathlib import Path
HERE=Path(__file__).resolve().parent
sys.path[:0]=[str(HERE.parent),str(HERE)]
import evaluate_frozen_candidate_code_v1 as evaluator
import viv_code_learning_loop as gates
LIVE=Path(r"E:\Viv_Sandbox\playground\adapters\epoch_10001")
CANDIDATE=Path(r"F:\LocalCoder_Archive\Viv_model_candidates\epoch_10008")
RUNS=HERE/"learning"/"deepseek_candidate_runs"
SUITE=RUNS/"frozen_code_eval_v1.json"
OUT=RUNS/"targeted_repair_candidate_10008.json"
API="http://127.0.0.1:1234"
TARGETS={"hold_py_rotate_right","hold_py_merge_sorted","hold_py_balanced_brackets",
         "hold_py_longest_prefix","hold_rs_dedupe_adjacent"}
def request(payload):
 req=urllib.request.Request(API+"/v1/chat/completions",data=json.dumps(payload).encode(),
  headers={"Content-Type":"application/json"})
 with urllib.request.urlopen(req,timeout=180) as r:return json.load(r)
def sha(v):return hashlib.sha256(json.dumps(v,ensure_ascii=False,sort_keys=True,separators=(",",":")).encode()).hexdigest()
def main():
 suite=json.loads(SUITE.read_text(encoding="utf-8")); sh=suite.pop("suite_sha256")
 if hashlib.sha256(json.dumps(suite,ensure_ascii=False,sort_keys=True,separators=(",",":")).encode()).hexdigest()!=sh:
  raise ValueError("held-out suite hash mismatch")
 tasks=[t for t in suite["held_out"] if t["id"] in TARGETS]
 if {t["id"] for t in tasks}!=TARGETS:raise ValueError("target task set mismatch")
 before=evaluator.request("/v1/status")
 if before.get("status")!="ACTIVE" or before.get("active_adapter")!=LIVE.name:raise RuntimeError(str(before))
 all_results=[]; restored=None
 system="Write correct clean standard-library code. Return only one fenced code block containing exactly the requested function. Do not include tests, main, explanation, or a demonstration."
 try:
  evaluator.activate(CANDIDATE)
  for ti,task in enumerate(tasks,1):
   messages=[{"role":"system","content":system},
    {"role":"user","content":f"Implement exactly this {task['lang']} function: {task['spec']}"}]
   attempts=[]
   for n in range(3):
    payload={"model":"deepseek-coder-6.7b-base","messages":messages,
      "temperature":0.0 if n==0 else 0.25+0.1*(n-1),"max_tokens":320,
      "stop":["\nUSER:","\nSYSTEM:"]}
    raw=request(payload)["choices"][0]["message"]["content"]
    code=evaluator.extract_requested_function(raw,task["lang"],task["spec"])
    if not code:ok,err=False,"NO_COMPLETE_REQUESTED_FUNCTION"
    else:
     gate=gates.gate_python if task["lang"]=="python" else gates.gate_rust
     ok,err=gate(code,task["tests"])
    attempts.append({"attempt":n+1,"passed":bool(ok),"error":err[:4000],"raw_output":raw,"code":code})
    print(json.dumps({"task_index":ti,"task":task["id"],"attempt":n+1,
      "passed":bool(ok),"error":err[:180]},ensure_ascii=False),flush=True)
    if ok:break
    messages.extend([{"role":"assistant","content":raw},
      {"role":"user","content":("The deterministic Python/Rust gate rejected that function. "
       "Gate output follows:\n"+err[:2500]+"\n\nRevise the requested function to fix this exact failure. "
       "Keep the required function name and signature. Return only the complete fenced function.\n\n"
       f"Task: {task['spec']}")}])
   all_results.append({"task":task["id"],"lang":task["lang"],
      "first_pass":attempts[0]["passed"],"final_pass":attempts[-1]["passed"],"attempts":attempts})
 finally:restored=evaluator.activate(LIVE)
 summary={}
 for lang in ("python","rust"):
  rr=[x for x in all_results if x["lang"]==lang]
  summary[lang]={"first_pass":sum(x["first_pass"] for x in rr),
   "final_pass":sum(x["final_pass"] for x in rr),"total":len(rr)}
 receipt={"schema":"viv_frozen_targeted_error_feedback_v1","created_utc":datetime.now(timezone.utc).isoformat(),
  "suite_sha256":sh,"candidate":str(CANDIDATE),
  "candidate_sha256":hashlib.sha256((CANDIDATE/"adapter_model.safetensors").read_bytes()).hexdigest(),
  "target_tasks":sorted(TARGETS),"attempt_limit":3,"generation_order":"task last; each rejection appends exact gate output then repeats task",
  "summary":summary,"results":all_results,"live_before":before,"live_restored":restored,"promoted":False}
 receipt["receipt_sha256"]=sha(receipt)
 OUT.write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
 print(json.dumps({"receipt":str(OUT),"summary":summary,
  "live_restored":restored.get("active_adapter"),"promoted":False},indent=2),flush=True)
 return 0 if len(all_results)==len(TARGETS) and restored.get("active_adapter")==LIVE.name else 1
if __name__=="__main__":raise SystemExit(main())
