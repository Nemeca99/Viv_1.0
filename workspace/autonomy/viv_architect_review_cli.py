"""Human-readable Architect review; approval is explicit and still non-promoting."""
from __future__ import annotations
import argparse,json
from pathlib import Path

PACKET=Path(r"L:\LocalCoder\workspace\autonomy\.tmp\architect_review_packet.json")
DECISIONS=Path(r"L:\LocalCoder\workspace\autonomy\.tmp\architect_review_decisions.jsonl")

def main():
 ap=argparse.ArgumentParser(); ap.add_argument("--approve"); args=ap.parse_args()
 packet=json.loads(PACKET.read_text(encoding="utf-8"))
 candidate=packet.get("candidate_verification",{}).get("weights_sha256")
 if args.approve is None:
  print(json.dumps({"status":packet["status"],"approved":packet["approved"],"evidence_count":len(packet["evidence"]),"candidate_hash_valid":packet["candidate_verification"].get("hash_valid"),"open_gaps":sum(1 for x in packet["evidence"] if x["path"].endswith("worker_report.json"))},indent=2)); return
 expected=f"ARCHITECT_APPROVE:{candidate}"
 approved=args.approve==expected and bool(candidate)
 decision={"token_valid":approved,"approval":approved,"candidate_hash":candidate,"promoted":False,"reason":"invalid approval token" if not approved else "approval recorded; promotion requires separate gate"}
 DECISIONS.parent.mkdir(parents=True,exist_ok=True)
 with DECISIONS.open("a",encoding="utf-8") as h: h.write(json.dumps(decision,sort_keys=True)+"\n")
 print(json.dumps(decision,indent=2))
if __name__=="__main__": main()
