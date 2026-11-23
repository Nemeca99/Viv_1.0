import json
from collections import Counter
from pathlib import Path
root=Path(r'F:\LocalCoder_Archive\INN_live_runs')
for d in sorted(root.iterdir(),key=lambda p:p.name):
 r=d/'receipt.json';log=d/'training_log.jsonl'
 if not r.exists() or not log.exists():continue
 j=json.loads(r.read_text())
 if j['steps']!=100000:continue
 c=Counter();plots=Counter();stages=Counter();legal=0;actions=0
 for line in log.open():
  x=json.loads(line)['values']
  if x[22]=='ACTION':
   actions+=1;c[x[2]]+=1;plots[x[3]]+=1;stages[x[5]]+=1;legal+=int(x[27])
 print(d.name,'tools',dict(c),'plots',dict(plots),'stages',dict(stages),'legal%',round(100*legal/max(actions,1),2))
