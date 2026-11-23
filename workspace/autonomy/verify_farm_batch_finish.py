"""Check the live GPU handoff's paused finish without running an optimizer."""
import hashlib
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from viv_autonomy import Store, worker_alive
from autonomy.farm_gpu_phase import gpu_training_phase, ollama


def snapshot():
    store = Store()
    state = ROOT / 'autonomy/inn_hive_state.json'
    return {'at': time.time(), 'enabled': store.get('enabled'),
            'worker_alive': worker_alive(),
            'gpu_training_active': store.get('gpu_training_active'),
            'phase': store.get('farm_gpu_phase'),
            'farm_sha256': hashlib.sha256(state.read_bytes()).hexdigest(),
            'resident_models': ollama('ps').get('models', [])}


def main():
    before = snapshot()
    if before['enabled'] or before['worker_alive']:
        raise RuntimeError('Pause the farm and wait for its current cycle before this check')
    # Exercise real pause, inference lock, unload, and final cleanup. No training.
    with gpu_training_phase():
        pass
    observations = []
    for _ in range(3):
        observations.append(snapshot())
        time.sleep(2)
    passed = all(not row['enabled'] and not row['worker_alive']
                 and not row['gpu_training_active']
                 and row['phase']['stage'] == 'paused'
                 and not row['resident_models']
                 and row['farm_sha256'] == before['farm_sha256']
                 for row in observations)
    receipt = {'schema': 'farm_batch_finish_check_v1', 'before': before,
               'observations': observations, 'passed': passed,
               'scope': 'Real handoff cleanup and stationary farm; no optimizer or new candidate run.'}
    path = ROOT / 'autonomy/learning/farm_batch_finish_verification.json'
    path.write_text(json.dumps(receipt, indent=2), encoding='utf-8')
    print(json.dumps({'passed': passed, 'receipt': str(path)}))
    if not passed:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
