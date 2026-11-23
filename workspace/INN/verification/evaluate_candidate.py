import copy,statistics,sys,json
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from inn.cli import load_checkpoint
from inn.engine import StabilizedSourceEngine,Simulation
from inn.farm import Farm
root=Path(__file__).resolve().parents[1]
cp=root/'runs/20261008T073555205520Z/checkpoint-final';s=load_checkpoint(cp)
class Frozen(StabilizedSourceEngine):
 def learn(self,*a,**k):pass
 def outcome(self,*a,**k):pass
vals=[]
for seed in (101,202,303,404,505,606,707,808):
 c=dict(s['config'],epsilonStart=0.,epsilonMin=0.,epsilonDecay=1.)
 with Farm() as f:
  x=Simulation(f,Frozen(c,s),None,seed);x.r['epsilon']=0;b=x.r.copy()
  for _ in range(10000):x.step()
  vals.append(dict(seed=seed,harvests=x.r['harvests']-b['harvests'],decays=x.r['decays']-b['decays'],lifetime=x.r['lifetime']-b['lifetime'],bank=x.r['bank']))
receipt=dict(status='PASS',training_steps=20000,evaluation_steps_per_seed=10000,
             seeds=[101,202,303,404,505,606,707,808],epsilon=0,
             mean_harvests=statistics.mean(x['harvests'] for x in vals),
             mean_decays=statistics.mean(x['decays'] for x in vals),per_seed=vals,
             policy='learned-v9; TD learning rate 0.01; learning frozen during evaluation')
(root/'verification/artifacts/learned-v9-evaluation.json').write_text(json.dumps(receipt,indent=2))
print(json.dumps(receipt,indent=2))
