import json,time,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import inn.cli as cli
from inn.import_sheet import import_workbook
from inn.engine import SourceEngine,Simulation
from inn.farm import Farm
folder=ROOT/'verification/artifacts'/f'cli-resume-{time.time_ns()}'
folder.mkdir()
state=import_workbook(ROOT/'Integrated Neural Network Architecture.xlsx')
with Farm(state) as farm:
    sim=Simulation(farm,SourceEngine(state['config'],state),state)
    cli.checkpoint(sim,folder/'initial')
cli.ROOT=folder
first=cli.main(['--resume',str(folder/'initial'),'--steps','7'])
second=cli.main(['--steps','9'])
a=cli.load_checkpoint(first/'checkpoint-final')
b=cli.load_checkpoint(second/'checkpoint-final')
assert b['r']['tick']==state['r']['tick']+16
assert json.loads((second/'run.json').read_text())['initial_tick']==a['r']['tick']
assert len(b['history'])==2048
rows=[json.loads(s)['values'] for s in (second/'training_log.jsonl').read_text().splitlines()]
assert sum(r[22]=='ACTION' for r in rows)==9
assert b['history'][-len(rows):]==rows
receipt=dict(status='PASS',automatic_resume=True,steps=16,history_rows=len(b['history']),every_action_logged=True)
(ROOT/'verification/artifacts/cli-continuity.json').write_text(json.dumps(receipt,indent=2))
print(receipt)
