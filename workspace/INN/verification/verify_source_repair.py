import copy
import json
from pathlib import Path
import subprocess
import sys
import time
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from inn.cli import checkpoint,load_checkpoint
from inn.engine import SourceEngine,Simulation
from inn.farm import Farm
from inn.import_sheet import import_workbook
from verify import compare

state=import_workbook(ROOT/'Integrated Neural Network Architecture.xlsx')
reference=json.loads(subprocess.check_output(['node',str(ROOT/'verification/reference.cjs')],
    input=json.dumps(dict(state=state,steps=2000,seed=1,capture=True)).encode()))
with Farm(state) as farm:
    sim=Simulation(farm,SourceEngine(state['config'],state),state)
    rows=[]
    for _ in range(2000): rows.extend(sim.step()['rows'])
    assert len(rows)==len(reference['logs'])
    for i,(actual,expected) in enumerate(zip(rows,reference['logs'])):
        for j,(a,b) in enumerate(zip(actual,expected)):
            if j==24 and a and b: compare(json.loads(b),json.loads(a),f'row {i} next')
            else: compare(b,a,f'row {i} column {j}')
    for key in ('r','p','w','validity','loss','updates'): compare(reference[key],sim.snapshot()[key],key)
    saved=ROOT/f'verification/artifacts/source-resume-{time.time_ns()}'
    checkpoint(sim,saved)
    for _ in range(1000): sim.step()
    expected=sim.snapshot()
loaded=load_checkpoint(saved)
with Farm(loaded) as farm:
    sim=Simulation(farm,SourceEngine(loaded['config'],loaded),loaded)
    for _ in range(1000): sim.step()
    compare(expected,sim.snapshot())
receipt=dict(status='PASS',source_steps=2000,log_rows=len(rows),log_columns=31,
             all_action_transition_world_rows_match=True,source_resume_steps=1000)
reference=json.loads(subprocess.check_output(['node',str(ROOT/'verification/reference.cjs')],
    input=json.dumps(dict(mode='replay',rows=state['history'],config=state['config'],seed=1)).encode()))
with Farm() as farm:
    sim=Simulation(farm,SourceEngine(state['config']))
    sim.replay(state['history'])
    for key in ('w','validity','loss','updates','replayed'): compare(reference[key],sim.snapshot()[key],key)
receipt['original_replay_transitions_matched']=reference['replayed']
reference=json.loads(subprocess.check_output(['node',str(ROOT/'verification/reference.cjs')],
    input=json.dumps(dict(mode='reset',state=state,rows=state['history'],seed=1)).encode()))
with Farm(state) as farm:
    sim=Simulation(farm,SourceEngine(state['config'],state),state)
    reset_rows=sim.reset(state['history'],1)
    for key in ('r','p','w','validity','loss','updates','replayed','frontier','logNext'):
        compare(reference['state'][key],sim.snapshot()[key],key)
    reset_rows[-1][0]='reset-proof'
    compare(reference['rows'],reset_rows,'reset rows')
receipt['original_hard_reset_matched']=True
(ROOT/'verification/artifacts/source-repair.json').write_text(json.dumps(receipt,indent=2))
print(json.dumps(receipt,indent=2))
