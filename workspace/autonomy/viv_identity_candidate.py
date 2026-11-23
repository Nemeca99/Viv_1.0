"""Candidate-only identity learning from explicit Architect evidence."""
from __future__ import annotations
import hashlib,json,subprocess,sys
from pathlib import Path

OUT=Path(r"L:\LocalCoder\workspace\autonomy\.tmp\viv_identity_candidate.json")

EVIDENCE=(
 {"claim":"Viv is the Architect's own AI/network project.","source":"Architect conversation: 'my own network my own AI'","kind":"Architect-provided"},
 {"claim":"Viv's personality is refined after capability proof.","source":"Architect conversation: personality follows capability","kind":"Architect-provided"},
 {"claim":"Identity does not grant execution authority.","source":"fixed Network and deterministic gate invariant","kind":"verified-architecture"},
)

def main():
 payload={"schema":"viv-identity-candidate-v1","status":"CANDIDATE_ONLY","authority":"Architect and deterministic gates","evidence":list(EVIDENCE),"persistent_memory_changed":False}
 body=json.dumps(payload,sort_keys=True).encode(); payload["candidate_sha256"]=hashlib.sha256(body).hexdigest()
 OUT.parent.mkdir(parents=True,exist_ok=True); OUT.write_text(json.dumps(payload,indent=2)+"\n",encoding="utf-8")
 check=json.loads(OUT.read_text(encoding="utf-8")); stored=check.pop("candidate_sha256"); reload_hash=hashlib.sha256(json.dumps(check,sort_keys=True).encode()).hexdigest()
 receipt={"status":"PASS" if stored==reload_hash and not payload["persistent_memory_changed"] else "HOLD","candidate":str(OUT),"hash_valid":stored==reload_hash,"persistent_memory_changed":False,"authority_separate":True,"evidence_count":len(EVIDENCE)}
 OUT.with_name("viv_identity_learning_receipt.json").write_text(json.dumps(receipt,indent=2)+"\n",encoding="utf-8"); print(json.dumps(receipt))
if __name__=="__main__": main()
