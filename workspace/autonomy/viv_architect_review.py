"""Create an explicit Architect review packet; default mode never promotes."""
from __future__ import annotations
import hashlib,json,sys
from pathlib import Path
from topology_integer_rnn import TopologyIntegerRNN

TMP=Path(r"L:\LocalCoder\workspace\autonomy\.tmp")
FILES=[TMP/"idle_learning_run_report.json",TMP/"gap_candidate_admission.json",TMP/"gap_corpus_generation_report.json",TMP/"bounded_worker_report.json"]
PACKET=TMP/"architect_review_packet.json"
def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
 approval="--approve" in sys.argv
 evidence=[]
 for path in FILES:
  if path.exists(): evidence.append({"path":str(path),"sha256":sha(path),"content":json.loads(path.read_text(encoding="utf-8"))})
 candidate=TMP/"gap_rnn_candidate.json"; verification={"exists":candidate.exists()}
 if candidate.exists():
  try:
   model=TopologyIntegerRNN.load_candidate(candidate); verification.update({"hash_valid":True,"weights_sha256":model._weights_digest()})
  except Exception as exc: verification.update({"hash_valid":False,"error":str(exc)})
 packet={"schema":"viv-architect-review-packet-v1","status":"APPROVAL_REQUESTED" if approval else "AWAITING_ARCHITECT_APPROVAL","approved":False,"evidence":evidence,"candidate_verification":verification,"promotion_target":None,"reversible":True,"fixed_network_changed":False,"authority":"Architect only"}
 if approval:
  packet["status"]="APPROVAL_RECORDED_PENDING_INDEPENDENT_PROMOTION"; packet["approved"]=True
 PACKET.write_text(json.dumps(packet,indent=2)+"\n",encoding="utf-8"); print(json.dumps({"status":packet["status"],"approved":packet["approved"],"evidence_count":len(evidence),"candidate_hash_valid":verification.get("hash_valid"),"packet":str(PACKET)}))
if __name__=="__main__": main()
