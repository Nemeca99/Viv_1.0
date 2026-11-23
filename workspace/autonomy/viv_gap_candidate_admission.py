"""Train and reload a candidate from E: gap material; never promote it."""
from __future__ import annotations
import hashlib,json,sys
from pathlib import Path
from topology_integer_rnn import TopologyIntegerRNN

SANDBOX=Path(r"E:\Viv_Sandbox\gap_corpus"); OUT=Path(r"L:\LocalCoder\workspace\autonomy\.tmp\gap_candidate_admission.json"); CANDIDATE=Path(r"L:\LocalCoder\workspace\autonomy\.tmp\gap_rnn_candidate.json")
def digest(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def vec(s):
 b=hashlib.sha256(s.encode()).digest(); return (b[0]-128,b[1]-128)
def main():
 files=sorted(SANDBOX.glob("gap_*.json"))[:3]
 model=TopologyIntegerRNN(2,2,use_gpu=True); receipts=[]
 for path in files:
  material=json.loads(path.read_text(encoding="utf-8")); route=[vec(material["gap"]),vec(material["questions"][0])]; learning=model.learn_route(route,reward=1); receipts.append({"path":str(path),"source_sha256":digest(path),"gap":material["gap"],"learning":learning.__dict__ if hasattr(learning,"__dict__") else {"transitions":learning.transitions,"reward":learning.reward,"changed_cells":learning.changed_cells,"weights_sha256":learning.weights_sha256}})
 saved=model.save_candidate(CANDIDATE,topology_sha256=digest(files[0]) if files else "none",receipt_ids=[x["source_sha256"] for x in receipts])
 reloaded=TopologyIntegerRNN.load_candidate(CANDIDATE,expected_topology_sha256=digest(files[0]) if files else "none")
 report={"schema":"viv-gap-candidate-admission-v1","status":"HOLD","training":"COMPLETED_CANDIDATE_ONLY","sources":receipts,"candidate":saved,"reload_weights_sha256":reloaded._weights_digest(),"evidence_gate":"HOLD","promotion_authorized":False,"reason":"gap material is not deterministic evidence of the missing fact"}
 OUT.write_text(json.dumps(report,indent=2)+"\n",encoding="utf-8"); print(json.dumps({"status":report["status"],"training":report["training"],"reloaded":report["candidate"]["weights_sha256"]==report["reload_weights_sha256"],"promotion_authorized":False,"receipt":str(OUT)}))
if __name__=="__main__": main()
