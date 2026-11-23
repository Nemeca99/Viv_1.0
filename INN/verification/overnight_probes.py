import json
from pathlib import Path
root=Path(r'F:\LocalCoder_Archive\INN_live_runs')
for d in sorted(root.iterdir(),key=lambda p:p.name):
 r=d/'receipt.json';b=d/'best_policy.json'
 if not r.exists():continue
 j=json.loads(r.read_text())
 if j['steps']!=1000000:continue
 x=j['final_runtime'];q=json.loads(b.read_text()).get('probe') if b.exists() else None
 print(d.name,'harvest',x['harvests'],'decay',x['decays'],'bank',x['bank'],'active',x['active'],'probe',q)
