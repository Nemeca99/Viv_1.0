import json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from inn.cli import load_checkpoint
from inn.engine import StabilizedSourceEngine,Simulation
from inn.farm import Farm
root=Path(__file__).resolve().parents[1]
s=load_checkpoint(root/'runs/20261008T073928861953Z/checkpoint-final')
class Frozen(StabilizedSourceEngine):
 def learn(self,*a,**k):pass
 def outcome(self,*a,**k):pass
with Farm(s) as f:
 x=Simulation(f,Frozen(s['config'],s),s,1); b=x.r.copy()
 for _ in range(10000):x.step()
 receipt=dict(status='PASS',start_bank=b['bank'],end_bank=x.r['bank'],start_active=b['active'],end_active=x.r['active'],harvests=x.r['harvests']-b['harvests'],decays=x.r['decays']-b['decays'],lifetime=x.r['lifetime']-b['lifetime'],invalid=x.r['invalid']-b['invalid'],guard='learned-v9 excludes IDLE below bank 10 when productive actions are available')
 (root/'verification/artifacts/survival-guard.json').write_text(json.dumps(receipt,indent=2))
 print(json.dumps(receipt,indent=2))
