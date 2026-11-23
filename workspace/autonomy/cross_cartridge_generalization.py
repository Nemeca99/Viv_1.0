"""Cross-cartridge held-out matrix for the integer route proposer."""
from __future__ import annotations
import hashlib, json, sqlite3
from pathlib import Path
from deterministic_containment import CONTAINED, ContainmentEngine, SQLiteArticleCartridge
from topology_integer_rnn import TopologyIntegerRNN

ROOT = Path(r"F:\AI_Datasets\domain_dbs")
OUT = Path(r"L:\LocalCoder\workspace\autonomy\.tmp\cross_cartridge_generalization.json")
DOMAINS = ("physics", "comp_sci", "geography")

def digest(p: Path) -> str:
    h=hashlib.sha256()
    with p.open("rb") as f:
        for b in iter(lambda:f.read(1024*1024), b""): h.update(b)
    return h.hexdigest()

def first_title(p: Path) -> str:
    with sqlite3.connect(f"file:{p.as_posix()}?mode=ro", uri=True) as c:
        rows=c.execute("SELECT title FROM articles WHERE length(title)>8 ORDER BY article_id LIMIT 500").fetchall()
    for (title,) in rows:
        if len([token for token in title.split() if len(token) > 2]) >= 2:
            return title
    raise RuntimeError(f"no multi-term title in {p}")

def anchor(s: str) -> tuple[int,int]:
    b=hashlib.sha256(s.encode()).digest(); return (b[0]-128,b[1]-128)

def main() -> None:
    cases=[]
    for domain in DOMAINS:
        p=ROOT/f"wiki_{domain}.sqlite3"; q=first_title(p)
        engine=ContainmentEngine([SQLiteArticleCartridge(domain,p)])
        result=engine.query(q)
        if result.state != CONTAINED: raise RuntimeError({"domain": domain, "query": q, "state": result.state})
        cases.append({"domain":domain,"query":q,"state":result.state,"trace":[anchor(x) for x in result.trace[:3]],"source_sha256":digest(p)})
    rows=[]
    for seed in range(5):
        model=TopologyIntegerRNN(2,2,use_gpu=True)
        train=cases[0]; model.learn_route(train["trace"], reward=1)
        held_scores=[]
        for held in cases[1:]:
            score=model.route_score(held["trace"]); neg=model.route_score(list(reversed(held["trace"])))
            held_scores.append({"domain":held["domain"],"query":held["query"],"retrieval":"CONTAINED","held_out_score":score,"negative_score":neg,"margin":score-neg,"generalization_pass":score>neg})
        candidate=OUT.with_name(f"cross_candidate_seed{seed}.json")
        saved=model.save_candidate(candidate,topology_sha256=train["source_sha256"],receipt_ids=["cross-train",f"cross-{seed}"])
        rejected=OUT.with_name(f"cross_rejected_seed{seed}.json"); rejected.write_text(json.dumps({"status":"REJECTED","seed":seed,"routes":[x["domain"] for x in held_scores],"reason":"reversed held-out routes preserved"})+"\n",encoding="utf-8")
        rows.append({"seed":seed,"held_out":held_scores,"candidate":saved,"rejected_candidate":str(rejected)})
    margins=[x["margin"] for r in rows for x in r["held_out"]]
    receipt={"schema":"viv-cross-cartridge-generalization-v1","status":"PASS" if all(x["generalization_pass"] for r in rows for x in r["held_out"]) else "HOLD","train_cartridge":cases[0]["domain"],"held_out_cartridges":[x["domain"] for x in cases[1:]],"retrieval_only":{"all_contained":all(x["state"]==CONTAINED for x in cases)},"generalization":{"runs":rows,"positive_count":sum(x["generalization_pass"] for r in rows for x in r["held_out"]),"total":len(margins),"margin_min":min(margins),"sign_stable":all(x>0 for x in margins) or all(x<0 for x in margins)},"source_read_only":True,"rejected_candidates_preserved":True}
    OUT.write_text(json.dumps(receipt,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({"status":receipt["status"],"positive":receipt["generalization"]["positive_count"],"total":receipt["generalization"]["total"],"margin_min":receipt["generalization"]["margin_min"],"receipt":str(OUT)}))

if __name__=="__main__": main()
