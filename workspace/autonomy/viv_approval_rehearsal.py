"""Rehearse approval binding without performing promotion."""
from __future__ import annotations
import json,subprocess,sys
from pathlib import Path
from topology_integer_rnn import TopologyIntegerRNN

C=Path(r"L:\LocalCoder\workspace\autonomy\.tmp\gap_rnn_candidate.json"); OUT=Path(r"L:\LocalCoder\workspace\autonomy\.tmp\approval_rehearsal.json")
def main():
 p=json.loads(C.read_text(encoding="utf-8")); m=TopologyIntegerRNN.load_candidate(C,expected_topology_sha256=p["topology_sha256"]); token=f"ARCHITECT_PROMOTE:{m._weights_digest()}:{p['topology_sha256']}"
 valid=subprocess.run([sys.executable,str(Path(__file__).with_name("viv_promotion_transaction.py")),"--token",token],capture_output=True,text=True,check=True)
 stale=subprocess.run([sys.executable,str(Path(__file__).with_name("viv_promotion_transaction.py")),"--token",token[:-1]+"0"],capture_output=True,text=True,check=True)
 v=json.loads(valid.stdout); s=json.loads(stale.stdout); report={"schema":"viv-approval-rehearsal-v1","status":"PASS" if v["approved"] and not v["promoted"] and not s["approved"] else "HOLD","token_display_only":True,"valid_token_result":{"approved":v["approved"],"promoted":v["promoted"]},"stale_token_result":{"approved":s["approved"],"promoted":s["promoted"]},"promotion_executed":False,"reversible":True}
 OUT.write_text(json.dumps(report,indent=2)+"\n",encoding="utf-8"); print(json.dumps(report))
if __name__=="__main__": main()
