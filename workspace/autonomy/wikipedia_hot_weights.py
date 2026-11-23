"""Add integer living-weight columns to the active L: Wikipedia index."""
from __future__ import annotations
import sqlite3,json
from pathlib import Path

DB=Path(r"L:\LocalCoder\workspace\autonomy\.tmp\wikipedia_hot_index.sqlite3"); OUT=Path(r"L:\LocalCoder\workspace\autonomy\.tmp\wikipedia_hot_weights_report.json")
def main():
 with sqlite3.connect(DB) as c:
  cols={row[1] for row in c.execute("PRAGMA table_info(wikipedia_hot)")}
  if "retrieval_weight" not in cols: c.execute("ALTER TABLE wikipedia_hot ADD COLUMN retrieval_weight INTEGER NOT NULL DEFAULT 1")
  if "route_credit" not in cols: c.execute("ALTER TABLE wikipedia_hot ADD COLUMN route_credit INTEGER NOT NULL DEFAULT 0")
  if "verified_count" not in cols: c.execute("ALTER TABLE wikipedia_hot ADD COLUMN verified_count INTEGER NOT NULL DEFAULT 1")
  c.commit(); count=c.execute("SELECT COUNT(*) FROM wikipedia_hot").fetchone()[0]
 report={"schema":"viv-wikipedia-hot-weights-v1","status":"PASS","rows":count,"weights":"integer","source_text_changed":False,"fixed_network_changed":False,"route_credit_initial":0,"promotion":False,"db":str(DB)}
 OUT.write_text(json.dumps(report,indent=2)+"\n",encoding="utf-8"); print(json.dumps(report))
if __name__=="__main__": main()
