import json
from pathlib import Path
root=Path(r'F:\LocalCoder_Archive\INN_live_runs')
prev=None
for d in sorted(root.iterdir(), key=lambda p:p.name):
 r=d/'receipt.json'
 if not r.exists():continue
 j=json.loads(r.read_text());x=j['final_runtime']
 if j['steps']!=100000:continue
 vals=(x['harvests'],x['decays'],x['lifetime'],x['bank'],x['active'])
 delta=tuple(vals[i]-prev[i] for i in range(3)) if prev else vals[:3]
 print(d.name, 'delta harvest/decay/life',delta,'cumulative',vals)
 prev=vals
