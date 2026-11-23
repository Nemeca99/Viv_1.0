import json
from pathlib import Path
root=Path(r'F:\LocalCoder_Archive\INN_live_runs')
rows=[]
for d in root.iterdir():
 r=d/'receipt.json'
 if r.exists():
  j=json.loads(r.read_text());x=j['final_runtime'];rows.append((d.name,j['steps'],x['harvests'],x['decays'],x['bank'],x['active'],x['lifetime']))
for x in sorted(rows,reverse=True)[:25]:print('\t'.join(map(str,x)))
