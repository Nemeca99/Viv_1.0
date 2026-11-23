import json
from pathlib import Path
root=Path(r'F:\LocalCoder_Archive\INN_live_runs')
for d in sorted(root.iterdir(),key=lambda p:p.name)[-12:]:
 r=d/'receipt.json'
 if r.exists():
  j=json.loads(r.read_text());x=j['final_runtime'];print(d.name,j['steps'],x['harvests'],x['decays'],x['bank'],x['active'])
