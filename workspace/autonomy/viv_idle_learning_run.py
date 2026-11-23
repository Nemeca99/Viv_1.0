"""One explicit end-to-end idle-GPU learning run; never self-starts."""
from __future__ import annotations
import json,subprocess,sys
from pathlib import Path
from viv_passive_scheduler import PassiveLearningScheduler

ROOT=Path(r"L:\LocalCoder\workspace\autonomy"); TMP=ROOT/".tmp"; FINAL=TMP/"idle_learning_run_report.json"; GAP=TMP/"bounded_worker_report.json"
def main():
 scheduler=PassiveLearningScheduler(TMP/"gpu_ownership_report.json",max_cycles=2)
 decision=scheduler.run_once(["dog name","one plus one"],explicit_launch=True,user_active=False,gpu_idle=True)
 if decision["status"]!="LEARNING_BOUNDED": raise SystemExit(decision)
 commands=["viv_gap_corpus_generator.py","viv_bounded_worker.py --launch --gpu-available --gpu-idle --max-cycles 2","viv_gap_candidate_admission.py"]
 results=[]
 for command in commands:
  args=[sys.executable,*command.split()]; result=subprocess.run(args,cwd=ROOT,capture_output=True,text=True,check=True); results.append({"command":command,"stdout":result.stdout[-2000:]})
 report={"schema":"viv-idle-learning-run-v1","status":"STOPPED_BOUNDED","scheduler":decision,"steps":results,"worker_report":str(GAP),"promoted":False,"auto_started":False,"checkpoint_lineage":"candidate receipt and reload recorded by admission step","source_network_changed":False}
 FINAL.write_text(json.dumps(report,indent=2)+"\n",encoding="utf-8"); print(json.dumps({"status":report["status"],"scheduler":decision["status"],"promoted":False,"report":str(FINAL)}))
if __name__=="__main__": main()
