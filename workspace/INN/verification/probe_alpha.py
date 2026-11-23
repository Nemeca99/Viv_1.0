import copy,statistics,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from inn.engine import SourceEngine,Simulation
from inn.farm import Farm
from inn.import_sheet import import_workbook
class Frozen(SourceEngine):
 def learn(self,*a,**k): pass
 def outcome(self,*a,**k): pass
root=Path(__file__).resolve().parents[1];s=import_workbook(root/'Integrated Neural Network Architecture.xlsx')
for alpha in (.15,.03,.01,.003):
 c=dict(s['config'],alpha=alpha)
 with Farm(s) as f:
  sim=Simulation(f,SourceEngine(c,s),s,1)
  for i in range(20000):sim.step()
  w=sim.snapshot()
 vals=[]
 for seed in (101,202,303,404):
  c2=dict(s['config'],epsilonStart=0.,epsilonMin=0.,epsilonDecay=1.)
  with Farm() as f:
   x=Simulation(f,Frozen(c2,w),None,seed);x.r['epsilon']=0;b=x.r.copy()
   for _ in range(3000):x.step()
   vals.append(x.r['harvests']-b['harvests'])
 print(alpha,vals,statistics.mean(vals),w['updates'],flush=True)
