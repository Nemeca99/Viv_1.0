import copy
import json
from pathlib import Path

ARCHIVE = Path(r'F:\LocalCoder_Archive\INN_live_runs')
OUT = Path(r'L:\LocalCoder\INN\seed_candidates')
OUT.mkdir(exist_ok=True)
sources = {
    'loop8-stable': ARCHIVE / '20261008T083759726020Z/checkpoint-final/state.json',
    'loop9-stable': ARCHIVE / '20261008T083856597518Z/checkpoint-final/state.json',
}
states = {name: json.loads(path.read_text()) for name, path in sources.items()}

for name, state in states.items():
    payload = dict(kind='learned-v9-seed', source=name, engine={
        'w': state['w'], 'validity': state['validity'],
        'loss': state['loss'], 'updates': state['updates']},
        evidence=dict(harvests=state['r']['harvests'], decays=state['r']['decays'],
                      lifetime=state['r']['lifetime'], bank=state['r']['bank']))
    (OUT / f'{name}.json').write_text(json.dumps(payload, indent=2))

average = copy.deepcopy(states['loop9-stable'])
for i in range(len(average['w'])):
    average['w'][i]['b'] = sum(states[name]['w'][i]['b'] for name in states) / 2
    average['w'][i]['x'] = [sum(states[name]['w'][i]['x'][j] for name in states) / 2 for j in range(5)]
    average['w'][i]['n'] = max(states[name]['w'][i]['n'] for name in states)
    average['w'][i]['delta'] = 0.0
for i in range(len(average['validity'])):
    average['validity'][i] = [sum(states[name]['validity'][i][j] for name in states) / 2 for j in range(6)]
payload = dict(kind='learned-v9-seed', source='average-loop8-loop9',
               engine={'w': average['w'], 'validity': average['validity'],
                       'loss': 0.0, 'updates': max(s['updates'] for s in states.values())},
               evidence=dict(inputs=list(sources), note='Arithmetic average of stable loop boundaries'))
(OUT / 'average-loop8-loop9.json').write_text(json.dumps(payload, indent=2))
print(json.dumps({'status': 'PASS', 'outputs': [p.name for p in OUT.glob('*.json')]}, indent=2))
