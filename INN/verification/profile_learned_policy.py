import copy,json,sys
from collections import Counter
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
trained=json.loads((root/'verification/artifacts/trained-100000-weights.json').read_text())
for name,w in [('sheet',dict(w=s['w'],validity=s['validity'])),('trained100k',trained)]:
 c=dict(s['config'],epsilonStart=0.,epsilonMin=0.,epsilonDecay=1.)
 with Farm() as f:
  sim=Simulation(f,Frozen(c,w),None,101);sim.r['epsilon']=0
  tools=Counter();legal=Counter()
  for _ in range(300):
   e=sim.step();tools[e['action']['t']]+=1;legal[(e['action']['t'],e['outcome']['legal'])]+=1
  print(name,dict(tools),dict(legal),'harvest',sim.r['harvests'],'decays',sim.r['decays'],'bank',sim.r['bank'])
