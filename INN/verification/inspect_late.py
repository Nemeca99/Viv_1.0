import json
from pathlib import Path
p=Path('runs/20261008T073928861953Z/training_log.jsonl')
counts={};rows=[]
for line in p.open():
 x=json.loads(line)['values']
 if x[22]=='ACTION' and 95000 <= int(x[1])-4872 <= 100000:
  rows.append(x); counts[x[2]]=counts.get(x[2],0)+1
print('counts',counts,'actions',len(rows))
for x in rows[-120:]:
 print(x[1],x[2],x[3],x[4],x[5],'reward',x[7],'bank',x[8],'active',x[10],'decays',x[11],'valid',x[6],'legal',x[27],x[30])
