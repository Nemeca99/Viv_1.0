import copy
import hashlib
import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from inn.engine import DEFAULT_CONFIG, LinearEngine, Simulation
from inn.farm import Farm
from inn.import_sheet import import_workbook


def compare(expected, actual, path='state'):
    if isinstance(expected, dict):
        for key, value in expected.items():
            compare(value, actual[key], f'{path}.{key}')
    elif isinstance(expected, list):
        assert len(expected) == len(actual), (path, len(expected), len(actual))
        for i, (a, b) in enumerate(zip(expected, actual)):
            compare(a, b, f'{path}[{i}]')
    elif isinstance(expected, (int, float)) and not isinstance(expected, bool):
        assert abs(expected-actual) <= 1e-8 * max(1, abs(expected)), (path, expected, actual)
    else:
        assert expected == actual, (path, expected, actual)


def parity(state, steps, seed):
    config = copy.deepcopy(state['config'] if state else DEFAULT_CONFIG)
    # Local replay history lives in checkpoints; Apps Script stores it in a separate sheet.
    reference_state = {k:v for k,v in state.items() if k != 'history'} if state else None
    input_ = dict(state=reference_state, config=config, steps=steps, seed=seed)
    reference = json.loads(subprocess.check_output(['node', str(ROOT/'verification/reference.cjs')],
                                                  input=json.dumps(input_).encode()))
    with Farm(state) as farm:
        engine = LinearEngine(config, state)
        sim = Simulation(farm, engine, state, seed)
        trace = []
        start = time.perf_counter()
        for i in range(steps):
            sim.step()
            if i % 25 == 0:
                trace.append(dict(r=copy.deepcopy(sim.r)))
        seconds = time.perf_counter() - start
        actual = sim.snapshot()
        actual['trace'] = trace
        for key in ('r', 'p', 'w', 'validity', 'loss', 'updates'):
            compare(reference[key], actual[key], key)
        for i, entry in enumerate(trace):
            compare(reference['trace'][i]['r'], entry['r'], f'trace[{i}]')
        return dict(status='PASS', steps=steps, seed=seed, seconds=seconds,
                    steps_per_second=steps/seconds, initial_tick=(state or {}).get('r',{}).get('tick',0),
                    final_tick=sim.r['tick'], harvests=sim.r['harvests'], decays=sim.r['decays'])


def main():
    folder = ROOT/'verification/artifacts'
    folder.mkdir(exist_ok=True)
    source = import_workbook(ROOT/'Integrated Neural Network Architecture.xlsx')
    with Farm() as farm:
        base = farm.call('state')
    base.update(version='8-outcomes', config=copy.deepcopy(DEFAULT_CONFIG), **LinearEngine(DEFAULT_CONFIG).state())
    expanded = copy.deepcopy(base)
    expanded['r']['bank'] = 3000
    automated = copy.deepcopy(base)
    automated['r'].update(bank=10000, next=50000, active=2, max=2)
    automated['p'][1]['active'] = 1
    automated['p'][0].update(upgrade=3, auto=1)
    inactive = copy.deepcopy(base)
    inactive['p'][1]['queue'] = ['TILL','SEED','WATER']
    receipt = dict(reference_sha256=hashlib.sha256((ROOT/'FarmScript.txt').read_bytes()).hexdigest(),
                   source=source['source'], checks=[parity(None, 3000, 1), parity(None,3000,7),
                                                parity(source,1000,1), parity(expanded,250,1),
                                                parity(automated,500,1), parity(inactive,250,1)])
    (folder/'parity.json').write_text(json.dumps(receipt, indent=2), encoding='utf-8')
    print(json.dumps(receipt, indent=2))


if __name__ == '__main__':
    main()
