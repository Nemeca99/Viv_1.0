"""Probe native code-completion prompting on the five persistent frozen failures."""
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
OUT=RUNS/"signature_completion_rust_full_v1.json"
API="http://127.0.0.1:1234"
def signature(spec,lang):
 m=re.search(r"(?:def|pub\s+fn)\s+([A-Za-z_]\w*)\s*\(",spec)
 if not m:return None
 op=spec.find("(",m.start()); depth=0; close=-1
 for i in range(op,len(spec)):
  if spec[i]=="(":depth+=1
  elif spec[i]==")":
   depth-=1
   if depth==0:close=i;break
 if close<0:return None
 colon=spec.find(":",close+1)
 if colon<0:return None
 header=spec[:colon].strip()
 desc=spec[colon+1:].strip()
 if lang=="python": return header+":",desc
 return header+" {",desc
def request(payload):
 q=urllib.request.Request(API+"/v1/completions",data=json.dumps(payload).encode(),
  headers={"Content-Type":"application/json"})
 with urllib.request.urlopen(q,timeout=180) as r:return json.load(r)
def main():
 suite=json.loads(SUITE.read_text(encoding="utf-8")); sh=suite.pop("suite_sha256")
 if hashlib.sha256(json.dumps(suite,ensure_ascii=False,sort_keys=True,separators=(",",":")).encode()).hexdigest()!=sh:
  raise ValueError("suite hash mismatch")
 tasks=[x for x in suite["held_out"] if x["lang"]=="rust"]
 before=evaluator.request("/v1/status")
 if before.get("status")!="ACTIVE" or before.get("active_adapter")!=LIVE.name:raise RuntimeError(str(before))
 results=[]
 for task in tasks:
  parsed=signature(task["spec"],task["lang"])
  if not parsed:raise ValueError(f"cannot parse signature for {task['id']}")
  header,desc=parsed
  prompt=(f"# Implement a correct standard-library {task['lang']} function for this task:\n"
      f"# {desc}\n{header}\n")
  raw=request({"model":"deepseek-coder-6.7b-base","prompt":prompt,"max_tokens":320,
    "temperature":0.0,"stop":["\n# Test code","\n// Test code","\nfn main()"]})["choices"][0]["text"]
  combined=header+("\n" if task["lang"]=="python" and not raw.startswith("\n") else "")+raw
  code=evaluator.extract_requested_function(combined,task["lang"],task["spec"])
  if not code:passed,error=False,"NO_COMPLETE_REQUESTED_FUNCTION"
  else:
   gate=gates.gate_python if task["lang"]=="python" else gates.gate_rust
   passed,error=gate(code,task["tests"])
  results.append({"task":task["id"],"lang":task["lang"],"signature_prefix":header,
   "task_description":desc,"raw_completion":raw,"completed_source":combined,
   "extracted_function":code,"passed":bool(passed),"error":error[:4000]})
  print(json.dumps({"task":task["id"],"passed":bool(passed),"error":error[:180]},ensure_ascii=False),flush=True)
 summary={}
 for lang in ("python","rust"):
  rr=[x for x in results if x["lang"]==lang]
  summary[lang]={"passed":sum(x["passed"] for x in rr),"total":len(rr)}
 out={"schema":"viv_native_signature_completion_eval_v1","created_utc":datetime.now(timezone.utc).isoformat(),
  "suite_sha256":sh,"adapter":str(LIVE),"candidate_sha256":hashlib.sha256((LIVE/"adapter_model.safetensors").read_bytes()).hexdigest(),
  "prompt_style":"code-first function-signature continuation","summary":summary,"results":results,
  "live_status":before,"promoted":False}
 out["receipt_sha256"]=hashlib.sha256(json.dumps(out,ensure_ascii=False,sort_keys=True,separators=(",",":")).encode()).hexdigest()
 OUT.write_text(json.dumps(out,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
 print(json.dumps({"receipt":str(OUT),"summary":summary,"live_adapter":before.get("active_adapter")},indent=2))
 return 0
if __name__=="__main__":raise SystemExit(main())
