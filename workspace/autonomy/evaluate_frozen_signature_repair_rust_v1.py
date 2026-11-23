"""Repair Rust code-first completions from actual deterministic gate failures."""
from __future__ import annotations
from datetime import datetime,timezone
import hashlib,json,re,sys,urllib.request
from pathlib import Path
HERE=Path(__file__).resolve().parent
sys.path[:0]=[str(HERE.parent),str(HERE)]
import evaluate_frozen_candidate_code_v1 as evaluator
import viv_code_learning_loop as gates
LIVE=Path(r"E:\Viv_Sandbox\playground\adapters\epoch_10001")
RUNS=HERE/"learning"/"deepseek_candidate_runs"
SUITE=RUNS/"frozen_code_eval_v1.json"
OUT=RUNS/"signature_repair_rust_v1.json"
API="http://127.0.0.1:1234"
TARGETS={"hold_rs_clamp","hold_rs_transpose","hold_rs_longest_prefix","hold_rs_perfect_square"}
def parse_signature(spec):
 m=re.search(r"pub\s+fn\s+([A-Za-z_]\w*)\s*\(",spec)
 if not m:return None
 op=spec.find("(",m.start());depth=0;close=-1
 for i in range(op,len(spec)):
  if spec[i]=="(":depth+=1
  elif spec[i]==")":
   depth-=1
   if depth==0:close=i;break
 colon=spec.find(":",close+1)
 if close<0 or colon<0:return None
 return spec[:colon].strip()+" {",spec[colon+1:].strip()
def request(payload):
 q=urllib.request.Request(API+"/v1/completions",data=json.dumps(payload).encode(),
  headers={"Content-Type":"application/json"})
 with urllib.request.urlopen(q,timeout=180) as r:return json.load(r)["choices"][0]["text"]
def sha(v):return hashlib.sha256(json.dumps(v,ensure_ascii=False,sort_keys=True,separators=(",",":")).encode()).hexdigest()
def main():
 suite=json.loads(SUITE.read_text(encoding="utf-8"));th=suite.pop("suite_sha256")
 if sha(suite)!=th:raise ValueError("frozen suite hash mismatch")
 tasks=[t for t in suite["held_out"] if t["id"] in TARGETS]
 if {t["id"] for t in tasks}!=TARGETS:raise ValueError("Rust repair target mismatch")
 before=evaluator.request("/v1/status")
 if before.get("status")!="ACTIVE" or before.get("active_adapter")!=LIVE.name:raise RuntimeError(str(before))
 all_results=[]
 for ti,task in enumerate(tasks,1):
  header,desc=parse_signature(task["spec"])
  attempts=[];extra=""
  for n in range(3):
   prompt=("# Implement one complete Rust function for this task.\n"
      f"# Task: {desc}\n"
      "# Use correct Rust syntax; close every block and handle boundary inputs.\n"
      f"{extra}{header}\n")
   raw=request({"model":"deepseek-coder-6.7b-base","prompt":prompt,
       "max_tokens":320,"temperature":0.0 if n==0 else 0.2,
       "stop":["\n#[cfg(test)]","\nfn main()"]})
   code=evaluator.extract_requested_function(header+raw,"rust",task["spec"])
   if not code:ok,err=False,"NO_COMPLETE_REQUESTED_FUNCTION"
   else:ok,err=gates.gate_rust(code,task["tests"])
   attempts.append({"attempt":n+1,"passed":bool(ok),"error":err[:4000],
       "header":header,"raw_completion":raw,"code":code})
   print(json.dumps({"task":task["id"],"attempt":n+1,"passed":bool(ok),
       "error":err[:160]},ensure_ascii=False),flush=True)
   if ok:break
   previous=raw[:1100].replace("\n","\n# ")
   failure=err[:1800].replace("\n","\n# ")
   extra=("# Previous generated function body:\n# "+previous+"\n"
      "# Deterministic Rust gate rejected it with:\n# "+failure+"\n"
      "# Correct this exact issue. Keep the signature and return a complete body.\n")
  all_results.append({"task":task["id"],"lang":"rust","first_pass":attempts[0]["passed"],
       "final_pass":attempts[-1]["passed"],"attempts":attempts})
 summary={"rust":{"first_pass":sum(r["first_pass"] for r in all_results),
   "final_pass":sum(r["final_pass"] for r in all_results),"total":len(all_results)}}
 receipt={"schema":"viv_native_rust_signature_error_repair_v1","created_utc":datetime.now(timezone.utc).isoformat(),
   "suite_sha256":th,"adapter":str(LIVE),"adapter_sha256":hashlib.sha256((LIVE/"adapter_model.safetensors").read_bytes()).hexdigest(),
   "max_attempts":3,"results":all_results,"summary":summary,"live_status":before,"promoted":False}
 receipt["receipt_sha256"]=sha(receipt)
 OUT.write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
 print(json.dumps({"receipt":str(OUT),"summary":summary,"active_adapter":before.get("active_adapter")},indent=2))
 return 0
if __name__=="__main__":raise SystemExit(main())
