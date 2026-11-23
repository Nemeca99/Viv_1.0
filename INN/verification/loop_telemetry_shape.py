import json
from pathlib import Path
root=Path(r'F:\LocalCoder_Archive\INN_live_runs')
for d in sorted(root.iterdir(),key=lambda p:p.name):
 t=d/'telemetry.jsonl';r=d/'receipt.json'
 if not t.exists() or not r.exists():continue
 rows=[json.loads(x) for x in t.read_text().splitlines() if x.strip()]
 if not rows:continue
 first,last=rows[0],rows[-1]
 print(d.name,'first',first['harvests'],first['decays'],first['bank'],'last',last['harvests'],last['decays'],last['bank'],'recent dH/dD',last['harvest_delta'],last['decay_delta'])
