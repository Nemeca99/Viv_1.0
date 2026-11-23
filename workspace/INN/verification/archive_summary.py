import json
from pathlib import Path
root=Path(r'F:\LocalCoder_Archive\INN_runs_20261008')
for n in ['20261008T075018684502Z','20261008T075731811155Z','20261008T081201766279Z']:
 d=root/n
 j=json.loads((d/'receipt.json').read_text()); r=j['final_runtime']
 b=json.loads((d/'best_policy.json').read_text()) if (d/'best_policy.json').exists() else {}
 print(n,'final',r['harvests'],r['decays'],r['lifetime'],'best',b.get('probe'),b.get('steps'))
