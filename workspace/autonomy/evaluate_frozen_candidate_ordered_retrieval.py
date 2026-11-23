"""Frozen eval: place retrieved gated demonstrations before the requested task."""
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
FENCE=chr(96)*3
TOK=re.compile(r"[a-z_][a-z_0-9]*|\d+",re.I)
STOP={"def","pub","fn","int","str","bool","list","vec","return","values","value","text","input","output","the","a","an","and","or","of","to","with","is","in","if","only","function","implement","python","rust","none","option"}
def sha(v):
 return hashlib.sha256(json.dumps(v,ensure_ascii=False,sort_keys=True,separators=(",",":")).encode()).hexdigest()
def terms(text): return {x.lower() for x in TOK.findall(text)}-STOP
def load_examples(data):
 rows=[]; seen=set()
 for x in data["samples"]:
  lang="rust" if x["category"].startswith("rust_") else "python"
  spec=x["prompt"].split("USER: Implement:",1)[-1].split("\n\nASSISTANT:",1)[0].strip()
  code=re.sub(r"<｜end▁of▁sentence｜>\s*$","",x["completion"]).strip()
  code=re.sub(rf"^{re.escape(FENCE)}(?:python|rust)\s*|\s*{re.escape(FENCE)}$","",code,flags=re.S).strip()
  key=(lang,x["id"],hashlib.sha256(code.encode()).hexdigest())
  if spec and code and key not in seen:
   seen.add(key); rows.append({"id":x["id"],"lang":lang,"spec":spec,"code":code,
      "text":f"Task: {spec}\nReference implementation:\n{FENCE}{lang}\n{code}\n{FENCE}"})
 return rows
def retrieve(query,lang,rows,k=2):
 docs=[x for x in rows if x["lang"]==lang]; q=terms(query); df={}
 for d in docs:
  for t in terms(d["spec"]): df[t]=df.get(t,0)+1
 ranked=[]
 for d in docs:
  common=q&terms(d["spec"])
  score=sum(math.log(1+(len(docs)+1)/(1+df[w])) for w in common)
  if score>=1.0: ranked.append((score,d))
 ranked.sort(key=lambda p:(p[0],p[1]["id"]),reverse=True)
 out=[]; used=set()
 for score,d in ranked:
  if d["id"] in used: continue
  used.add(d["id"]); out.append({"id":d["id"],"score":round(score,3),"text":d["text"]})
  if len(out)==k: break
 return out
def main():
 data=json.loads(DATA.read_text(encoding="utf-8")); dh=data.pop("receipt_sha256")
 if sha(data)!=dh or sha(data["samples"])!=data["training_sha256"]: raise ValueError("training corpus hash failure")
 suite=json.loads(SUITE.read_text(encoding="utf-8")); th=suite.pop("suite_sha256")
 if sha(suite)!=th: raise ValueError("held-out suite hash failure")
 rows=load_examples(data)
 if {x["id"] for x in rows}&{x["id"] for x in suite["held_out"]}: raise ValueError("training/test leakage")
 before=evaluator.request("/v1/status")
 if before.get("status")!="ACTIVE" or before.get("active_adapter")!=LIVE.name: raise RuntimeError(str(before))
 result=[]; restored=None
 system="Write clean, standard-library code. Return only one fenced code block containing exactly the requested function. Do not copy a demonstration verbatim unless it solves the task. Do not include tests, main, or explanation."
 try:
  evaluator.activate(CANDIDATE)
  for i,task in enumerate(suite["held_out"],1):
   examples=retrieve(task["spec"],task["lang"],rows)
   messages=[{"role":"system","content":system}]
   if examples:
    messages.append({"role":"user","content":"Verified reference examples from different tasks. Use them only to recall syntax and patterns:\n\n"+"\n\n---\n\n".join(x["text"] for x in examples)})
   messages.append({"role":"user","content":f"Implement: {task['spec']}\n\nReturn only the requested {task['lang']} function."})
   response=evaluator.request("/v1/chat/completions",{"model":"deepseek-coder-6.7b-base",
       "messages":messages,"max_tokens":320,"temperature":0.0,
       "stop":["\nUSER:","\nSYSTEM:"]},timeout=180)
   raw=response["choices"][0]["message"]["content"]
   code=evaluator.extract_requested_function(raw,task["lang"],task["spec"])
   if not code: passed,error=False,"NO_COMPLETE_REQUESTED_FUNCTION"
   else:
    gate=gates.gate_python if task["lang"]=="python" else gates.gate_rust
    passed,error=gate(code,task["tests"])
   result.append({"task":task["id"],"lang":task["lang"],"passed":bool(passed),
       "error":error[:3000],"code":code,"raw_output":raw,
       "retrieved":[{"id":x["id"],"score":x["score"]} for x in examples]})
   print(json.dumps({"index":i,"task":task["id"],"passed":bool(passed),
       "retrieved":[x["id"] for x in examples],"error":error[:150]},ensure_ascii=False),flush=True)
 finally: restored=evaluator.activate(LIVE)
 summary={}
 for lang in ("python","rust"):
  rr=[x for x in result if x["lang"]==lang]
  summary[lang]={"passed":sum(x["passed"] for x in rr),"total":len(rr)}
 out={"schema":"viv_frozen_candidate_ordered_retrieval_eval_v1",
  "created_utc":datetime.now(timezone.utc).isoformat(),"dataset_sha256":dh,"suite_sha256":th,
  "candidate":str(CANDIDATE),"candidate_sha256":hashlib.sha256((CANDIDATE/"adapter_model.safetensors").read_bytes()).hexdigest(),
  "retrieval_method":"deduplicated language-filtered IDF term overlap; examples precede target task",
  "retrieval_k":2,"by_language":summary,"results":result,"live_before":before,
  "live_restored":restored,"promoted":False}
 out["receipt_sha256"]=sha(out)
 path=RUNS/f"ordered_retrieval_eval_v1_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.json"
 path.write_text(json.dumps(out,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
 print(json.dumps({"receipt":str(path),"by_language":summary,
  "live_restored":restored.get("active_adapter"),"promoted":False},indent=2),flush=True)
 return 0 if len(result)==len(suite["held_out"]) and restored.get("active_adapter")==LIVE.name else 1
if __name__=="__main__": raise SystemExit(main())
