import json
from pathlib import Path
root=Path(r'F:\LocalCoder_Archive\INN_live_runs')
for d in sorted(root.iterdir(),key=lambda p:p.name):
 b=d/'best_policy.json';r=d/'receipt.json'
 if b.exists() and r.exists():
  j=json.loads(r.read_text());q=json.loads(b.read_text()).get('probe');print(d.name,j['steps'],q)
