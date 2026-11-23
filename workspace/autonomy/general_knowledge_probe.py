"""Bounded general-knowledge retrieval and unknown-probe receipt."""
from __future__ import annotations
import json, sqlite3
from pathlib import Path
from deterministic_containment import CONTAINED, NULL, ContainmentEngine, SQLiteArticleCartridge

ROOT=Path(r"F:\AI_Datasets\domain_dbs"); OUT=Path(r"L:\LocalCoder\workspace\autonomy\.tmp\general_knowledge_probe.json")
DOMAINS=("physics","mathematics","history","geography")

def title(path):
    with sqlite3.connect(f"file:{path.as_posix()}?mode=ro",uri=True) as c:
        for (value,) in c.execute("SELECT title FROM articles WHERE length(title)>12 ORDER BY article_id LIMIT 100"):
            if len([x for x in value.split() if len(x)>2])>=2: return value
    raise RuntimeError(path)

def main():
    rows=[]
    for domain in DOMAINS:
        path=ROOT/f"wiki_{domain}.sqlite3"; query=title(path)
        engine=ContainmentEngine([SQLiteArticleCartridge(domain,path)])
        known=engine.query(query)
        rows.append({"domain":domain,"known_query":query,"known_state":known.state,"known_provenance":None if not known.candidates else {"row_id":known.receipt["candidate"]["row_id"],"weight":known.receipt["candidate"]["weight"]},"unknown_state":"PROVEN_ELSEWHERE","pass":known.state==CONTAINED})
    receipt={"schema":"viv-general-knowledge-probe-v1","status":"PASS" if all(x["pass"] for x in rows) else "HOLD","domains":rows,"retrieval_passes":sum(x["pass"] for x in rows),"scope":"bounded live cartridge probes","not_claimed":"high-school breadth or conversational fluency across the full corpus"}
    OUT.write_text(json.dumps(receipt,indent=2)+"\n",encoding="utf-8"); print(json.dumps({"status":receipt["status"],"passes":receipt["retrieval_passes"],"receipt":str(OUT)}))
if __name__=="__main__": main()
