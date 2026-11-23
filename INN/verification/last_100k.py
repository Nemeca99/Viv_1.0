import json
from pathlib import Path
root=Path(r'F:\LocalCoder_Archive\INN_live_runs')
rows=[]
for d in root.iterdir():
 r=d/'receipt.json'
 if r.exists():
  j=json.loads(r.read_text());
  if j['steps']==100000:
   x=j['final_runtime'];rows.append((d.name,x['harvests'],x['decays'],x['bank'],x['active'],x['lifetime']))
for i,x in enumerate(sorted(rows,reverse=True)[:12],1): print(i,'\t'.join(map(str,x)))
