import json
import signal
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from inn.cli import main, load_checkpoint
from inn.engine import Simulation

if __name__ == '__main__':
    original = Simulation.step
    def interrupted_step(self):
        signal.raise_signal(signal.SIGINT)
        return original(self)
    Simulation.step = interrupted_step
    output = ROOT / f'verification/artifacts/stop-at-tick-{time.time_ns()}'
    try:
        main(['--fresh', '--steps', '0', '--no-latest', '--output', str(output)])
    finally:
        Simulation.step = original
    receipt = json.loads((output/'receipt.json').read_text())
    state = load_checkpoint(output/'checkpoint-final')
    assert receipt['status'] == 'interrupted' and receipt['steps'] == 1
    assert state['r']['tick'] == state['pending']['tick'] == 1
    print('PASS: SIGINT completes one tick and saves a consistent checkpoint')
