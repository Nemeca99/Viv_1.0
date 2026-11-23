import json
from pathlib import Path
root=Path(r'F:\LocalCoder_Archive\INN_live_runs')
for d in sorted(root.iterdir(),key=lambda p:p.name):
 r=d/'receipt.json'
 if not r.exists():continue
 j=json.loads(r.read_text())
 if j['steps']!=100000:continue
 cps=sorted(d.glob('checkpoint-*/state.json'))
 if not cps:continue
 s=json.loads(cps[-1].read_text())
 w=s['w'];print(d.name,'updates',s['updates'],'Qbias', [round(x['b'],2) for x in w[:6]],'valid', [round(s['validity'][i][i],1) for i in range(4)])
