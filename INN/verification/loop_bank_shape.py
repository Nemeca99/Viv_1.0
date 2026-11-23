import json
from pathlib import Path
root=Path(r'F:\LocalCoder_Archive\INN_live_runs')
for d in sorted(root.iterdir(),key=lambda p:p.name):
 t=d/'telemetry.jsonl'
 if not t.exists():continue
 rows=[json.loads(x) for x in t.read_text().splitlines() if x.strip()]
 if not rows:continue
 m=max(rows,key=lambda x:x['bank']); first=rows[0];last=rows[-1]
 print(d.name,'first',first['bank'],'max',m['bank'],'at',m['steps'],'last',last['bank'],'harvests',last['harvests'],'decays',last['decays'])
