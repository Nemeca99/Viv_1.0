"""Independent, reversible Architect promotion transaction."""
from __future__ import annotations
import argparse,hashlib,json
from pathlib import Path
from topology_integer_rnn import TopologyIntegerRNN

CANDIDATE=Path(r"L:\LocalCoder\workspace\autonomy\.tmp\gap_rnn_candidate.json")
DECISIONS=Path(r"L:\LocalCoder\workspace\autonomy\.tmp\promotion_decisions.jsonl")
def main():
 ap=argparse.ArgumentParser(); ap.add_argument("--token",default=""); args=ap.parse_args()
 payload=json.loads(CANDIDATE.read_text(encoding="utf-8")); model=TopologyIntegerRNN.load_candidate(CANDIDATE,expected_topology_sha256=payload["topology_sha256"]); weight_hash=model._weights_digest(); expected=f"ARCHITECT_PROMOTE:{weight_hash}:{payload['topology_sha256']}"; valid=args.token==expected
 decision={"schema":"viv-promotion-decision-v1","approved":valid,"promoted":False,"reversible":True,"candidate_weights_sha256":weight_hash,"parent_topology_sha256":payload["topology_sha256"],"token_bound":expected[:24]+"...","reason":"missing_or_invalid_architect_token" if not valid else "approval_verified_pending_separate_promotion_executor"}
 DECISIONS.parent.mkdir(parents=True,exist_ok=True)
 with DECISIONS.open("a",encoding="utf-8") as h: h.write(json.dumps(decision,sort_keys=True)+"\n")
 print(json.dumps(decision))
if __name__=="__main__": main()
