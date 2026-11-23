"""Single user-facing facade over Viv's grounded and gated capability paths."""
from __future__ import annotations
import hashlib, json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from grounded_rnn_answer_bridge import GroundedRNNAnswerBridge, NULL_UNLEARNED_ENTITY

ROOT=Path(r"L:\LocalCoder\workspace"); MEMORY=ROOT/"aios_rebuild"/"memory"/"persistent_memory.json"; DB=ROOT/"autonomy"/"viv_code_topology.sqlite3"; CANDIDATE=ROOT/"autonomy"/".tmp"/"rnn_candidate.json"; IDENTITY=ROOT/"autonomy"/".tmp"/"viv_identity_candidate.json"

class VivCapabilityRouter:
    def __init__(self):
        topology_hash=hashlib.sha256(DB.read_bytes()).hexdigest()
        self.bridge=GroundedRNNAnswerBridge(MEMORY,CANDIDATE,topology_sha256=topology_hash)
        self.personality={"source":"Architect-provided verified evidence only","authority":"Architect and deterministic gates","learned":False}
        if IDENTITY.exists():
            candidate=json.loads(IDENTITY.read_text(encoding="utf-8"))
            if candidate.get("status")=="CANDIDATE_ONLY":
                self.personality={"source":candidate["schema"],"evidence_count":len(candidate.get("evidence",[])),"authority":candidate["authority"],"learned":False}

    def answer(self, text: str) -> dict:
        low=text.casefold()
        if any(word in low for word in ("python", "rust", "machine code", "opcode")):
            return {"status":"CODE_PATH","answer":"Route this request through the deterministic code gate.","capabilities":["python","rust","machine_code"],"personality":self.personality}
        result=self.bridge.answer(text)
        return {"status":result["status"],"answer":result["answer"],"evidence":result.get("evidence",[]),"receipt":result["evidence_receipt"],"personality":self.personality}

if __name__=="__main__":
    import sys
    print(json.dumps(VivCapabilityRouter().answer(" ".join(sys.argv[1:])),indent=2))
