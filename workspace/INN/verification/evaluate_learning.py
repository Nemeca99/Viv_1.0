import copy,json,statistics,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from inn.engine import DEFAULT_CONFIG,SourceEngine,Simulation
from inn.farm import Farm
from inn.import_sheet import import_workbook

class Frozen(SourceEngine):
    def learn(self,*args,**kwargs): pass
    def outcome(self,*args,**kwargs): pass

started=time.perf_counter()
source=import_workbook(ROOT/'Integrated Neural Network Architecture.xlsx')
initial=dict(w=copy.deepcopy(source['w']),validity=copy.deepcopy(source['validity']))
train_state=copy.deepcopy(source)
with Farm(train_state) as farm:
    sim=Simulation(farm,SourceEngine(train_state['config'],train_state),train_state,seed=1)
    for n in range(100000):
        sim.step()
        if (n+1)%25000==0: print(f'training {n+1}/100000',flush=True)
    trained=sim.snapshot()
variants={'zero':dict(w=[dict(b=0.,x=[0.]*5,n=0,delta=0.) for _ in range(8)],validity=[[0.]*6 for _ in range(6)]),
          'sheet_checkpoint':initial,
          'after_100000_training_steps':dict(w=trained['w'],validity=trained['validity'])}
seeds=[101,202,303,404,505,606,707,808]
steps=10000
results=[]
for name,weights in variants.items():
    summary=[]
    for seed in seeds:
        config=dict(source['config'],epsilonStart=0.,epsilonMin=0.,epsilonDecay=1.)
        engine=Frozen(config,weights)
        with Farm() as farm:
            sim=Simulation(farm,engine,None,seed)
            sim.r['epsilon']=0.
            initial_r=copy.deepcopy(sim.r)
            reward=0.
            for _ in range(steps):
                event=sim.step()
                reward += event['outcome']['reward']
                reward += sum(world_event['reward'] for world_event in event['events'])
            final=sim.r
            row=dict(seed=seed,steps=steps,harvests=final['harvests']-initial_r['harvests'],
                     decays=final['decays']-initial_r['decays'],lifetime=final['lifetime']-initial_r['lifetime'],
                     bank=final['bank'],active=final['active'],max_plots=final['max'],reward=reward)
            summary.append(row)
    results.append(dict(policy=name,per_seed=summary,means={key:statistics.mean(row[key] for row in summary)
        for key in ('harvests','decays','lifetime','bank','reward')}))
    print(f'evaluated {name}: '+json.dumps(results[-1]['means']),flush=True)
receipt=dict(status='COMPLETE',training_steps=100000,evaluation_steps_per_seed=steps,seeds=seeds,
             evaluation='fresh paired farm for every seed; epsilon=0; engine learn/outcome updates frozen',
             elapsed_seconds=time.perf_counter()-started,policies=results,
             interpretation='Primary metrics are mean lifetime production, harvests, and decays. Eight seeds are an initial behavioral check, not a broad generalization claim.')
out=ROOT/'verification/artifacts/learning-evaluation.json'
out.write_text(json.dumps(receipt,indent=2))
(ROOT/'verification/artifacts/trained-100000-weights.json').write_text(json.dumps({k:trained[k] for k in ('w','validity','updates','loss')}))
print('saved '+str(out),flush=True)
