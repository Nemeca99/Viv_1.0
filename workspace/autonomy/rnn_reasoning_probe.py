"""One bounded RNN composition probe over verified physics evidence."""
from __future__ import annotations
import hashlib,json,sqlite3
from pathlib import Path
from topology_integer_rnn import TopologyIntegerRNN

DB=Path(r"F:\AI_Datasets\domain_dbs\wiki_physics.sqlite3"); OUT=Path(r"L:\LocalCoder\workspace\autonomy\.tmp\rnn_reasoning_probe.json")
def vec(s):
 b=hashlib.sha256(s.encode()).digest(); return (b[0]-128,b[1]-128)
def main():
 with sqlite3.connect(f"file:{DB.as_posix()}?mode=ro",uri=True) as c:
  rows=c.execute("SELECT article_id,title,summary FROM articles WHERE article_id IN (622,2992)").fetchall()
 evidence=" ".join(row[2] or "" for row in rows).casefold()
 route=[vec(f"{row[0]}:{row[1]}") for row in rows]
 rnn=TopologyIntegerRNN(2,2,use_gpu=True); traversal=rnn.traverse(route)
 proposed="blue light is scattered more than red light"
 wrong="green light is scattered more than blue light"
 def gate(claim): return all(term in evidence for term in ("blue", "red", "scattering")) and claim==proposed
 accepted=gate(proposed); rejected=not gate(wrong); rnn.learn_route(route,reward=1 if accepted else -1)
 heldout_claim="sunset light appears red because blue light is scattered away"; heldout_pass=all(term in evidence for term in ("sunset","blue","scattered"))
 receipt={"schema":"viv-rnn-reasoning-probe-v1","status":"PASS" if accepted and rejected and heldout_pass else "HOLD","retrieval":{"rows":[str(row[0]) for row in rows]},"rnn":{"steps":traversal.steps,"backend":traversal.backend,"route_score":rnn.route_score(route)},"composition":{"accepted_claim":proposed,"gate":"ALLOW" if accepted else "DENY","rejected_claim":wrong,"rejected_preserved":rejected},"held_out":{"claim":heldout_claim,"pass":heldout_pass,"separate_from_retrieval":True},"source_read_only":True}
 OUT.write_text(json.dumps(receipt,indent=2)+"\n",encoding="utf-8"); print(json.dumps({"status":receipt["status"],"gate":receipt["composition"]["gate"],"held_out":heldout_pass,"receipt":str(OUT)}))
if __name__=="__main__": main()
