"""Direct read-only B-tree probes for a small high-school knowledge set."""
from __future__ import annotations
import hashlib,json,sqlite3
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from grounded_rnn_answer_bridge import GroundedRNNAnswerBridge,NULL_UNLEARNED_ENTITY

ROOT=Path(r"F:\AI_Datasets\domain_dbs"); OUT=Path(r"L:\LocalCoder\workspace\autonomy\.tmp\highschool_knowledge_matrix.json")
PROBES=(
 ("physics","Rayleigh scattering"),("mathematics","Pythagorean"),
 ("history","World War II"),("geography","1910 United States census"),
)
def main():
 rows=[]
 for domain,title in PROBES:
  p=ROOT/f"wiki_{domain}.sqlite3"
  with sqlite3.connect(f"file:{p.as_posix()}?mode=ro",uri=True) as c:
   row=c.execute("SELECT article_id,title,summary FROM articles WHERE lower(title)=lower(?) LIMIT 1",(title,)).fetchone()
  rows.append({"domain":domain,"query":title,"row_id":None if not row else str(row[0]),"title":None if not row else row[1],"verified":row is not None,"source_db":str(p),"source_sha256":hashlib.sha256(p.read_bytes()).hexdigest()})
 bridge=GroundedRNNAnswerBridge(Path(r"L:\LocalCoder\workspace\aios_rebuild\memory\persistent_memory.json"),Path(r"L:\LocalCoder\workspace\autonomy\.tmp\rnn_candidate.json"),topology_sha256=hashlib.sha256(Path(r"L:\LocalCoder\workspace\autonomy\viv_code_topology.sqlite3").read_bytes()).hexdigest())
 unknown=bridge.answer("What is the unlearned entity xylophone nebula 8472?")
 receipt={"schema":"viv-highschool-knowledge-matrix-v1","status":"PASS" if all(x["verified"] for x in rows) and unknown["answer"]==NULL_UNLEARNED_ENTITY else "HOLD","probes":rows,"unknown_probe":{"answer":unknown["answer"],"fail_closed":unknown["answer"]==NULL_UNLEARNED_ENTITY},"scope":"four direct live B-tree concept probes; not a claim of complete curriculum breadth"}
 OUT.write_text(json.dumps(receipt,indent=2)+"\n",encoding="utf-8"); print(json.dumps({"status":receipt["status"],"verified":sum(x["verified"] for x in rows),"unknown_fail_closed":receipt["unknown_probe"]["fail_closed"],"receipt":str(OUT)}))
if __name__=="__main__": main()
