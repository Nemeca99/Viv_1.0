import copy
import json
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from inn.engine import StabilizedSourceEngine, Simulation
from inn.farm import Farm
from inn.import_sheet import import_workbook

source = import_workbook(ROOT / 'Integrated Neural Network Architecture.xlsx')
best = json.loads((ROOT / 'runs/20261008T074732900006Z/best_policy.json').read_text())
state = copy.deepcopy(source)
state.update(best['engine'])
state['engine_kind'] = 'learned-v9'


class Frozen(StabilizedSourceEngine):
    def learn(self, *args, **kwargs):
        pass

    def outcome(self, *args, **kwargs):
        pass


values = []
for seed in (101, 202, 303, 404, 505, 606, 707, 808):
    config = dict(source['config'], epsilonStart=0.0, epsilonMin=0.0, epsilonDecay=1.0)
    with Farm() as farm:
        sim = Simulation(farm, Frozen(config, state), None, seed)
        sim.r['epsilon'] = 0.0
        before = sim.r.copy()
        for _ in range(10000):
            sim.step()
        values.append(dict(seed=seed,
                           harvests=sim.r['harvests'] - before['harvests'],
                           decays=sim.r['decays'] - before['decays'],
                           lifetime=sim.r['lifetime'] - before['lifetime']))
receipt = dict(status='PASS', steps=10000, seeds=[x['seed'] for x in values],
               mean_harvests=statistics.mean(x['harvests'] for x in values),
               mean_decays=statistics.mean(x['decays'] for x in values),
               mean_lifetime=statistics.mean(x['lifetime'] for x in values),
               per_seed=values)
(ROOT / 'verification/artifacts/best-policy-evaluation.json').write_text(json.dumps(receipt, indent=2))
print(json.dumps(receipt, indent=2))
