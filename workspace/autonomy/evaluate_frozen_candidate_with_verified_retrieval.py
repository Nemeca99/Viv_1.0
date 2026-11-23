"""Frozen held-out evaluation with retrieval from gated candidate code memory."""
from __future__ import annotations
from datetime import datetime, timezone
import hashlib, json, math, re, sys
from pathlib import Path
HERE=Path(__file__).resolve().parent
sys.path[:0]=[str(HERE.parent),str(HERE)]
import evaluate_frozen_candidate_code_v1 as evaluator
import viv_code_learning_loop as gates
LIVE=Path(r"E:\Viv_Sandbox\playground\adapters\epoch_10001")
CANDIDATE=Path(r"F:\LocalCoder_Archive\Viv_model_candidates\epoch_10008")
RUNS=HERE/"learning"/"deepseek_candidate_runs"
DATA=RUNS/"clean_function_training_v2.json"
SUITE=RUNS/"frozen_code_eval_v1.json"
TOK=re.compile(r"[a-z_][a-z_0-9]*|\d+",re.I)
FENCE=chr(96)*3
def sh(v):
 return hashlib.sha256(json.dumps(v,ensure_ascii=False,sort_keys=True,separators=(",",":")).encode()).hexdigest()
def terms(s): return set(x.lower() for x in TOK.findall(s))
def load_rows(data):
 out=[]
 for x in data["samples"]:
  lang="rust" if x["category"].startswith("rust_") else "python"
  spec=x["prompt"].split("USER: Implement:",1)[-1].split("\n\nASSISTANT:",1)[0].strip()
  code=re.sub(r"<｜end▁of▁sentence｜>\s*$","",x["completion"]).strip()
  code=re.sub(rf"^{re.escape(FENCE)}(?:python|rust)\s*|\s*{re.escape(FENCE)}$","",code,flags=re.S).strip()
  if spec and code: out.append({"id":x["id"],"lang":lang,"spec":spec,"code":code,
   "example":f"USER: Implement: {spec}\nASSISTANT:\n{code}"})
 return out
def retrieve(query,lang,rows,k=2):
 docs=[d for d in rows if d["lang"]==lang]
 q=terms(query); df={}
 for d in docs:
  for t in terms(d["spec"]): df[t]=df.get(t,0)+1
 scores=[]
 for d in docs:
  inter=q&terms(d["spec"])
  score=sum(math.log(1+(len(docs)+1)/(1+df[t])) for t in inter)+.15*len(inter)
  scores.append((score,d))
 scores.sort(key=lambda x:(x[0],x[1]["id"]),reverse=True)
 return [{"id":d["id"],"score":round(score,4),"text":d["example"]} for score,d in scores[:k] if score>0]
def main():
 data=json.loads(DATA.read_text(encoding="utf-8")); dh=data.pop("receipt_sha256")
 if sh(data)!=dh or sh(data["samples"])!=data["training_sha256"]: raise ValueError("training hash mismatch")
 suite=json.loads(SUITE.read_text(encoding="utf-8")); th=suite.pop("suite_sha256")
 if sh(suite)!=th: raise ValueError("held-out suite hash mismatch")
 rows=load_rows(data); held={t["id"] for t in suite["held_out"]}
 if held & {r["id"] for r in rows}: raise ValueError("retrieval leakage by task ID")
 before=evaluator.request("/v1/status")
 if before.get("status")!="ACTIVE" or before.get("active_adapter")!=LIVE.name: raise RuntimeError(str(before))
 results=[]; restored=None
 try:
  evaluator.activate(CANDIDATE)
  for i,task in enumerate(suite["held_out"],1):
   got=retrieve(task["spec"],task["lang"],rows); attempts=[]
   for n in range(2):
    raw=gates.propose(task,attempts,[x["text"] for x in got])
    code=evaluator.extract_requested_function(raw,task["lang"],task["spec"])
    if not code: ok,err=False,"NO_COMPLETE_REQUESTED_FUNCTION"
    else:
     gate=gates.gate_python if task["lang"]=="python" else gates.gate_rust
     ok,err=gate(code,task["tests"])
    attempts.append({"attempt":n+1,"passed":bool(ok),"error":err[:3000],"code":code,"raw_output":raw})
    print(json.dumps({"index":i,"task":task["id"],"attempt":n+1,"passed":bool(ok),
     "retrieved":[x["id"] for x in got],"error":err[:120]},ensure_ascii=False),flush=True)
    if ok: break
   results.append({"task":task["id"],"lang":task["lang"],
    "retrieved":[{"id":x["id"],"score":x["score"]} for x in got],
    "first_pass":attempts[0]["passed"],"final_pass":attempts[-1]["passed"],"attempts":attempts})
 finally: restored=evaluator.activate(LIVE)
 summary={}
 for lang in ("python","rust"):
  rr=[x for x in results if x["lang"]==lang]
  summary[lang]={"first_pass":sum(x["first_pass"] for x in rr),"final_pass":sum(x["final_pass"] for x in rr),"total":len(rr)}
 out={"schema":"viv_frozen_verified_retrieval_eval_v1","created_utc":datetime.now(timezone.utc).isoformat(),
  "dataset_sha256":dh,"suite_sha256":th,"candidate":str(CANDIDATE),
  "candidate_sha256":hashlib.sha256((CANDIDATE/"adapter_model.safetensors").read_bytes()).hexdigest(),
  "retrieval_method":"language-filtered TF-IDF word overlap","retrieval_k":2,"max_attempts":2,
  "summary":summary,"results":results,"live_before":before,"live_restored":restored,"promoted":False}
 out["receipt_sha256"]=sh(out)
 path=RUNS/f"verified_retrieval_eval_v1_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.json"
 path.write_text(json.dumps(out,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
 print(json.dumps({"receipt":str(path),"summary":summary,"live_restored":restored.get("active_adapter"),"promoted":False},indent=2),flush=True)
 return 0 if len(results)==len(suite["held_out"]) and restored.get("active_adapter")==LIVE.name else 1
if __name__=="__main__": raise SystemExit(main())
