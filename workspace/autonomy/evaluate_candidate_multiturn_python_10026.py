"""Test one real two-turn code request against the Docker Python gate."""
from __future__ import annotations
from datetime import datetime, timezone
import hashlib, json, sys, urllib.request
from pathlib import Path
HERE=Path(__file__).resolve().parent
sys.path[:0]=[str(HERE.parent),str(HERE)]
import evaluate_frozen_candidate_code_v1 as evaluator
import viv_code_learning_loop as gates
LIVE=Path(r"E:\Viv_Sandbox\playground\adapters\epoch_10001")
CANDIDATE=Path(r"F:\LocalCoder_Archive\Viv_model_candidates\epoch_10026")
OUT=HERE/"learning"/"deepseek_candidate_runs"/"multiturn_candidate_10026.json"
API="http://127.0.0.1:1234"
def request(payload):
 req=urllib.request.Request(API+"/v1/chat/completions",data=json.dumps(payload).encode(),
  headers={"Content-Type":"application/json"})
 with urllib.request.urlopen(req,timeout=180) as r:return json.load(r)
def sh(v): return hashlib.sha256(json.dumps(v,ensure_ascii=False,sort_keys=True,separators=(",",":")).encode()).hexdigest()
def main():
 if OUT.exists(): raise FileExistsError(OUT)
 before=evaluator.request("/v1/status")
 if before.get("status")!="ACTIVE" or before.get("active_adapter")!=LIVE.name: raise RuntimeError(str(before))
 system="Write clean standard-library Python. Return only one fenced code block containing the requested function, with no tests or explanation."
 first_spec="def normalize_labels(labels: list[str]) -> list[str]: strip whitespace and lowercase each label, preserving order"
 user1=f"Implement: {first_spec}"
 messages=[{"role":"system","content":system},{"role":"user","content":user1}]
 restore=None; first=""; final=""; code=""; err=""; passed=False
 try:
  evaluator.activate(CANDIDATE)
  first=request({"model":"deepseek-coder-6.7b-base","messages":messages,"temperature":0.0,"max_tokens":220,
   "stop":["\nUSER:","\nSYSTEM:"]})["choices"][0]["message"]["content"]
  messages.extend([{"role":"assistant","content":first},
    {"role":"user","content":"Update your previous function to omit any label that becomes empty after stripping. Preserve the relative order of the remaining labels and keep the same function name and return type."}])
  final=request({"model":"deepseek-coder-6.7b-base","messages":messages,"temperature":0.0,"max_tokens":260,
   "stop":["\nUSER:","\nSYSTEM:"]})["choices"][0]["message"]["content"]
  follow_spec="def normalize_labels(labels: list[str]) -> list[str]: strip whitespace, lowercase, omit empty results, preserve order"
  code=evaluator.extract_requested_function(final,"python",follow_spec)
  if not code: passed,err=False,"NO_COMPLETE_REQUESTED_FUNCTION"
  else:
   tests="assert normalize_labels([' A ', 'b', ' C ']) == ['a','b','c']\nassert normalize_labels([' ', 'X', '', ' y ']) == ['x','y']\nassert normalize_labels([]) == []"
   passed,err=gates.gate_python(code,tests)
 finally: restore=evaluator.activate(LIVE)
 receipt={"schema":"viv_candidate_multiturn_code_eval_v1","created_utc":datetime.now(timezone.utc).isoformat(),
  "candidate":str(CANDIDATE),"candidate_sha256":hashlib.sha256((CANDIDATE/"adapter_model.safetensors").read_bytes()).hexdigest(),
  "initial_user_turn":user1,"assistant_turn_1":first,
  "user_followup":"Omit labels that become empty after stripping; preserve order and signature.",
  "assistant_turn_2":final,"extracted_function":code,"deterministic_gate":"python_docker",
  "gate_passed":bool(passed),"gate_error":err[:3000],"live_before":before,
  "live_restored":restore,"promoted":False}
 receipt["receipt_sha256"]=sh(receipt)
 OUT.write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
 print(json.dumps({"receipt":str(OUT),"gate_passed":passed,"active_adapter":restore.get("active_adapter"),
  "promoted":False,"error":err[:300]},indent=2))
 return 0 if passed and restore.get("active_adapter")==LIVE.name else 1
if __name__=="__main__": raise SystemExit(main())
