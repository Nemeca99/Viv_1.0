import copy,json,statistics,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from inn.engine import SourceEngine,Simulation
from inn.farm import Farm
from inn.import_sheet import import_workbook
class Pos(SourceEngine):
 def learn(self,a,reward,next_items,context=None):
  if reward>0: super().learn(a,reward,next_items,context)
class Frozen(SourceEngine):
 def learn(self,*a,**k): pass
 def outcome(self,*a,**k): pass
root=Path(__file__).resolve().parents[1];s=import_workbook(root/'Integrated Neural Network Architecture.xlsx')
with Farm(s) as f:
 sim=Simulation(f,Pos(s['config'],s),s,1)
 for i in range(20000):sim.step()
 trained=sim.snapshot()
print('updates',trained['updates'])
for name,w in [('sheet',s),('positive',trained)]:
 vals=[]
 for seed in (101,202,303,404):
  c=dict(s['config'],epsilonStart=0.,epsilonMin=0.,epsilonDecay=1.)
  with Farm() as f:
   sim=Simulation(f,Frozen(c,w),None,seed);sim.r['epsilon']=0;before=sim.r.copy()
   for _ in range(3000):sim.step()
   vals.append((sim.r['harvests']-before['harvests'],sim.r['decays']-before['decays']))
 print(name,vals,statistics.mean(v[0] for v in vals))
