import json,statistics,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from inn.engine import SourceEngine,Simulation
from inn.farm import Farm
from inn.import_sheet import import_workbook
class Frozen(SourceEngine):
 def learn(self,*a,**k):pass
 def outcome(self,*a,**k):pass
root=Path(__file__).resolve().parents[1]
s=import_workbook(root/'Integrated Neural Network Architecture.xlsx')
w=json.loads((root/'verification/artifacts/trained-100000-weights.json').read_text())
seeds=[101,202,303,404]
result=[]
for threshold in (.5,.45,.4):
 rows=[]
 for seed in seeds:
  c=dict(s['config'],epsilonStart=0.,epsilonMin=0.,epsilonDecay=1.,threshold=threshold)
  with Farm() as farm:
   sim=Simulation(farm,Frozen(c,w),None,seed);sim.r['epsilon']=0
   initial=sim.r.copy()
   for _ in range(5000):sim.step()
   rows.append(dict(seed=seed,harvests=sim.r['harvests']-initial['harvests'],decays=sim.r['decays']-initial['decays'],lifetime=sim.r['lifetime']-initial['lifetime'],bank=sim.r['bank']))
 result.append(dict(threshold=threshold,per_seed=rows,mean_harvests=statistics.mean(x['harvests'] for x in rows),mean_decays=statistics.mean(x['decays'] for x in rows)))
 print(result[-1],flush=True)
(root/'verification/artifacts/gate-threshold-sweep.json').write_text(json.dumps(result,indent=2))
