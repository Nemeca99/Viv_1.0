"""Train a separate local candidate from the verified coding curriculum."""
import hashlib
import json
from pathlib import Path

import viv_python_curriculum
import viv_sleep_trainer

HELD_OUT = {'py_dedupe', 'py_is_palindrome'}
EPOCH = 10001
PARENT = Path(r'E:\Viv_Sandbox\playground\adapters\epoch_10000')

def main():
    samples = [
        {'category': task['id'], 'prompt': 'USER: ' + task['spec'] + '\n\nASSISTANT:\n',
         'completion': task['reference'] + '\n'}
        for task in viv_python_curriculum.TASKS if task['id'] not in HELD_OUT
    ]
    data_hash = hashlib.sha256(json.dumps(samples, sort_keys=True).encode()).hexdigest()
    print(json.dumps({'samples': len(samples), 'dataset_sha256': data_hash,
                      'held_out': sorted(HELD_OUT), 'parent': str(PARENT)}), flush=True)
    result = viv_sleep_trainer.run_sleep_training(EPOCH, steps=60, parent_adapter=PARENT,
                                                   training_samples=samples)
    print(json.dumps(result), flush=True)

if __name__ == '__main__':
    main()
