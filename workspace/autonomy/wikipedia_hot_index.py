"""Bounded first-batch Wikipedia hot index on L:; source remains read-only."""
from __future__ import annotations
import hashlib,json,sqlite3
import argparse
from pathlib import Path

SOURCE=Path(r"F:\AI_Datasets\wikipedia_deduplicated"); DB=Path(r"L:\LocalCoder\workspace\autonomy\.tmp\wikipedia_hot_index.sqlite3"); CHECKPOINT=Path(r"L:\LocalCoder\workspace\autonomy\.tmp\wikipedia_hot_checkpoint.json")
def main():
 args=argparse.ArgumentParser(); args.add_argument("--batch",default="batch_0000"); args.add_argument("--limit",type=int,default=100); ns=args.parse_args()
 files=sorted((SOURCE/ns.batch).glob("*.txt"))[:ns.limit]; excluded=[]; rows=[]
 for path in files:
  text=path.read_text(encoding="utf-8",errors="replace"); title=text.splitlines()[0].removeprefix("Title:").strip() if text.startswith("Title:") else path.stem
  if "#REDIRECT" in text[:500]: excluded.append({"path":str(path),"reason":"redirect"}); continue
  rows.append((str(path),title,text[:12000],hashlib.sha256(text.encode()).hexdigest()))
 with sqlite3.connect(DB) as conn:
  conn.execute("CREATE TABLE IF NOT EXISTS wikipedia_hot (source_path TEXT PRIMARY KEY,title TEXT,body TEXT,source_sha256 TEXT)")
  conn.executemany("INSERT OR REPLACE INTO wikipedia_hot(source_path,title,body,source_sha256) VALUES (?,?,?,?)",rows); conn.commit()
 checkpoint={"schema":"viv-wikipedia-hot-checkpoint-v1","source":str(SOURCE),"batch":ns.batch,"files_seen":len(files),"indexed":len(rows),"excluded":excluded,"next_file":files[-1].name if files else None,"db":str(DB),"source_mutated":False,"e_drive_used_for_hot_path":False}
 CHECKPOINT.write_text(json.dumps(checkpoint,indent=2)+"\n",encoding="utf-8"); print(json.dumps(checkpoint))
if __name__=="__main__": main()
