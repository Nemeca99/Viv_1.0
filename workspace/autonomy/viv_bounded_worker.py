"""Manually launched bounded learner; never starts itself."""
from __future__ import annotations
import argparse,json
from pathlib import Path
from viv_internal_reflection import InternalReflection
from viv_passive_scheduler import PassiveLearningScheduler

REPORT=Path(r"L:\LocalCoder\workspace\autonomy\.tmp\passive_learning_report.json")
OUT=Path(r"L:\LocalCoder\workspace\autonomy\.tmp\bounded_worker_report.json")

def main():
 ap=argparse.ArgumentParser(); ap.add_argument("--report",default=str(REPORT)); ap.add_argument("--max-cycles",type=int,default=3); ap.add_argument("--gpu-available",action="store_true"); ap.add_argument("--gpu-idle",action="store_true"); ap.add_argument("--architect-active",action="store_true"); ap.add_argument("--launch",action="store_true"); args=ap.parse_args()
 if not 1<=args.max_cycles<=10: raise SystemExit("max-cycles must be 1..10")
 source=Path(args.report); data=json.loads(source.read_text(encoding="utf-8"))
 scheduler=PassiveLearningScheduler(OUT)
 decision=scheduler.run_once(data.get("gaps_seen",[]),explicit_launch=args.launch,user_active=args.architect_active,gpu_idle=args.gpu_idle and args.gpu_available)
 if decision["status"]!="LEARNING_BOUNDED":
  out={"schema":"viv-bounded-worker-report-v1","status":decision["status"],"cycles_run":0,"promoted":[],"candidates":[],"open_gaps":data.get("gaps_seen",[]),"auto_started":False}
 else:
  results=[]
  for gap in data.get("gaps_seen",[])[:args.max_cycles]:
   result=InternalReflection().reflect_loop(gap); results.append({"gap":gap,"status":result["status"],"answer":result["answer"],"receipt":result["receipt"],"rejected_hypotheses":result.get("rejected_hypotheses",[])})
  out={"schema":"viv-bounded-worker-report-v1","status":"STOPPED_BOUNDED","cycles_run":len(results),"promoted":[],"candidates":results,"open_gaps":[r["gap"] for r in results if r["status"]!="VERIFIED"],"auto_started":False}
 OUT.parent.mkdir(parents=True,exist_ok=True); OUT.write_text(json.dumps(out,indent=2)+"\n",encoding="utf-8"); print(json.dumps(out))
if __name__=="__main__": main()
