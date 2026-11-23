"""Evaluate epoch_10008 Rust code completion with deterministic gate repair."""
from __future__ import annotations
from datetime import datetime,timezone
import hashlib,json,re,sys,urllib.request
from pathlib import Path
HERE=Path(__file__).resolve().parent
sys.path[:0]=[str(HERE.parent),str(HERE)]
import evaluate_frozen_candidate_code_v1 as evaluator
import viv_code_learning_loop as gates
LIVE=Path(r"E:\Viv_Sandbox\playground\adapters\epoch_10001")
CANDIDATE=Path(r"F:\LocalCoder_Archive\Viv_model_candidates\epoch_10008")
RUNS=HERE/"learning"/"deepseek_candidate_runs"
SUITE=RUNS/"frozen_code_eval_v1.json"
OUT=RUNS/"candidate10008_rust_codefirst_retry.json"
API="http://127.0.0.1:1234"
def parse_signature(spec):
 m=re.search(r"pub\s+fn\s+([A-Za-z_]\w*)\s*\(",spec)
 if not m:return None
 op=spec.find("(",m.start());depth=0;close=-1
 for i in range(op,len(spec)):
  if spec[i]=="(":depth+=1
  elif spec[i]==")":
   depth-=1
   if depth==0:close=i;break
 if close<0:return None
 colon=spec.find(":",close+1)
 if colon<0:return None
 return spec[:colon].strip()+" {",spec[colon+1:].strip()
def request(payload):
 q=urllib.request.Request(API+"/v1/completions",data=json.dumps(payload).encode(),
  headers={"Content-Type":"application/json"})
 with urllib.request.urlopen(q,timeout=180) as r:return json.load(r)["choices"][0]["text"]
def sha(v):return hashlib.sha256(json.dumps(v,ensure_ascii=False,sort_keys=True,separators=(",",":")).encode()).hexdigest()
def main():
 suite=json.loads(SUITE.read_text(encoding="utf-8"));th=suite.pop("suite_sha256")
 if sha(suite)!=th:raise ValueError("frozen suite hash mismatch")
 tasks=[t for t in suite["held_out"] if t["lang"]=="rust"]
 if len(tasks)!=10:raise ValueError("unexpected frozen Rust task count")
 before=evaluator.request("/v1/status")
 if before.get("status")!="ACTIVE" or before.get("active_adapter")!=LIVE.name:raise RuntimeError(str(before))
 results=[];restored=None
 try:
  evaluator.activate(CANDIDATE)
  for index,task in enumerate(tasks,1):
   header,desc=parse_signature(task["spec"])
   attempts=[];extra=""
   for n in range(3):
    prompt=("# Implement a complete, correct standard-library Rust function.\n"
      f"# Task: {desc}\n"
      "# Include all closing braces and handle empty and boundary inputs.\n"
      f"{extra}{header}\n")
    raw=request({"model":"deepseek-coder-6.7b-base","prompt":prompt,
      "max_tokens":320,"temperature":0.0 if n==0 else 0.2,
      "stop":["\n#[cfg(test)]","\nfn main()"]})
    code=evaluator.extract_requested_function(header+raw,"rust",task["spec"])
    if not code:ok,err=False,"NO_COMPLETE_REQUESTED_FUNCTION"
    else:ok,err=gates.gate_rust(code,task["tests"])
    attempts.append({"attempt":n+1,"passed":bool(ok),"error":err[:4000],
       "header":header,"raw_completion":raw,"code":code})
    print(json.dumps({"index":index,"task":task["id"],"attempt":n+1,
      "passed":bool(ok),"error":err[:160]},ensure_ascii=False),flush=True)
    if ok:break
    raw_comment=raw[:1100].replace("\n","\n# ")
    err_comment=err[:1800].replace("\n","\n# ")
    extra=("# Previous generated body:\n# "+raw_comment+"\n"
      "# Rust compiler/test gate result:\n# "+err_comment+"\n"
      "# Correct the reported issue; return a complete function body.\n")
   results.append({"task":task["id"],"lang":"rust","first_pass":attempts[0]["passed"],
      "final_pass":attempts[-1]["passed"],"attempts":attempts})
 finally:restored=evaluator.activate(LIVE)
 summary={"rust":{"first_pass":sum(x["first_pass"] for x in results),
  "final_pass":sum(x["final_pass"] for x in results),"total":len(results)}}
 receipt={"schema":"viv_candidate10008_rust_codefirst_retry_v1",
  "created_utc":datetime.now(timezone.utc).isoformat(),"suite_sha256":th,
  "candidate":str(CANDIDATE),
  "candidate_sha256":hashlib.sha256((CANDIDATE/"adapter_model.safetensors").read_bytes()).hexdigest(),
  "max_attempts":3,"prompt_style":"code-first signature completion with exact gate feedback",
  "summary":summary,"results":results,"live_before":before,"live_restored":restored,"promoted":False}
 receipt["receipt_sha256"]=sha(receipt)
 OUT.write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
 print(json.dumps({"receipt":str(OUT),"summary":summary,
  "live_restored":restored.get("active_adapter"),"promoted":False},indent=2),flush=True)
 return 0 if len(results)==len(tasks) and restored.get("active_adapter")==LIVE.name else 1
if __name__=="__main__":raise SystemExit(main())
