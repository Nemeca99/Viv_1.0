"""Generate bounded candidate study material in the E: sandbox only."""
from __future__ import annotations
import hashlib,json
from datetime import datetime,timezone
from pathlib import Path
from viv_internal_reflection import InternalReflection

REPORT=Path(r"L:\LocalCoder\workspace\autonomy\.tmp\bounded_worker_report.json")
SANDBOX=Path(r"E:\Viv_Sandbox\gap_corpus")
JOURNAL=Path(r"L:\LocalCoder\workspace\autonomy\.tmp\gap_corpus_journal.jsonl")

def main(max_items: int=3):
    report=json.loads(REPORT.read_text(encoding="utf-8"))
    gaps=report.get("open_gaps",[])[:max_items]
    SANDBOX.mkdir(parents=True,exist_ok=True)
    records=[]
    for index,gap in enumerate(gaps,1):
        material={"schema":"viv-gap-study-candidate-v1","gap":gap,"questions":[f"What verified facts constrain {gap}?",f"Which deterministic primitive can test {gap}?",f"What evidence would reject a proposed answer to {gap}?"],"status":"CANDIDATE_ONLY","generated_utc":datetime.now(timezone.utc).isoformat()}
        body=json.dumps(material,sort_keys=True).encode(); material["sha256"]=hashlib.sha256(body).hexdigest()
        path=SANDBOX/f"gap_{index:03d}.json"; path.write_text(json.dumps(material,indent=2)+"\n",encoding="utf-8")
        record={"source_report":str(REPORT),"gap":gap,"sandbox_path":str(path),"candidate_sha256":material["sha256"],"outcome":"OPEN_GAP_CANDIDATE","promoted":False}
        reflection=InternalReflection().reflect_loop(gap)
        record["reflection_status"]=reflection["status"]
        record["gate"]="ALLOW" if reflection["status"]=="VERIFIED" else "HOLD"
        record["reflection_receipt"]=reflection["receipt"]
        with JOURNAL.open("a",encoding="utf-8") as handle: handle.write(json.dumps(record,sort_keys=True)+"\n")
        records.append(record)
    result={"schema":"viv-gap-corpus-generation-v1","status":"PASS","items_generated":len(records),"sandbox":str(SANDBOX),"journal":str(JOURNAL),"promoted":False,"records":records}
    out=Path(r"L:\LocalCoder\workspace\autonomy\.tmp\gap_corpus_generation_report.json"); out.write_text(json.dumps(result,indent=2)+"\n",encoding="utf-8"); print(json.dumps(result))

if __name__=="__main__": main()
