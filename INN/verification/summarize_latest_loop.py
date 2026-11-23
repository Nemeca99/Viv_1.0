import json
from pathlib import Path
root=Path(r'F:\LocalCoder_Archive\INN_live_runs')
rows=[]
for d in sorted(root.iterdir(), key=lambda p:p.name):
 r=d/'receipt.json'
 if r.exists():
  j=json.loads(r.read_text());x=j['final_runtime'];rows.append((d.name,j['steps'],x['harvests'],x['decays'],x['lifetime'],x['bank'],x['active'],j['seconds']))
for x in rows[-12:]:print('\t'.join(map(str,x)))
