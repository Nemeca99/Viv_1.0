"""Lightweight Wikipedia corpus manifest; no source copy or mutation."""
from __future__ import annotations
import hashlib,json
from pathlib import Path

SOURCE=Path(r"F:\AI_Datasets\wikipedia_deduplicated"); HOT=Path(r"L:\LocalCoder\workspace\autonomy\.tmp\wikipedia_hot_manifest.json")
def main():
 batches=sorted(p.name for p in SOURCE.iterdir() if p.is_dir()) if SOURCE.exists() else []
 sample=[]
 for batch in batches[:3]:
  root=SOURCE/batch
  for path in sorted(root.iterdir())[:10]: sample.append({"path":str(path),"name":path.name,"is_dir":path.is_dir()})
 manifest={"schema":"viv-wikipedia-corpus-manifest-v1","source":str(SOURCE),"source_exists":SOURCE.exists(),"batch_count":len(batches),"batches_sample":batches[:10],"sample_entries":sample,"hot_path":"L:\\LocalCoder\\workspace\\autonomy\\.tmp","cold_sandbox":"E:\\Viv_Sandbox","source_mutated":False,"policy":"L active retrieval/training; E reversible sandbox; F source corpus"}
 HOT.parent.mkdir(parents=True,exist_ok=True); HOT.write_text(json.dumps(manifest,indent=2)+"\n",encoding="utf-8"); print(json.dumps({"source_exists":manifest["source_exists"],"batch_count":manifest["batch_count"],"manifest":str(HOT)}))
if __name__=="__main__": main()
