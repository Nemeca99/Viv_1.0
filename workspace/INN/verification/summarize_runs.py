import json
from pathlib import Path

rows = []
for folder in Path('runs').iterdir():
    if not folder.is_dir():
        continue
    receipt = folder / 'receipt.json'
    if receipt.exists():
        data = json.loads(receipt.read_text())
        runtime = data['final_runtime']
        rows.append((folder.name, data['steps'], runtime['harvests'], runtime['decays'],
                     runtime['bank'], runtime['active'], runtime['lifetime'], 'complete'))
        continue
    checkpoints = sorted(folder.glob('checkpoint-*/state.json'))
    if checkpoints:
        data = json.loads(checkpoints[-1].read_text())
        runtime = data['r']
        rows.append((folder.name, checkpoints[-1].parent.name, runtime['harvests'], runtime['decays'],
                     runtime['bank'], runtime['active'], runtime['lifetime'], 'running/incomplete'))
for row in sorted(rows, reverse=True)[:30]:
    print('\t'.join(map(str, row)))
