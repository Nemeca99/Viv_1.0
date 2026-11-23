from pathlib import Path
import hashlib

root = Path('L:/LocalCoder')
target = root / 'workspace/autonomy/terminal_neuron_learning.py'
before = root / '.opencode/evals/measured_learning_20261117/terminal_before.py'
assert hashlib.sha256(target.read_bytes()).digest() == hashlib.sha256(before.read_bytes()).digest(), 'Review concurrent source changes first'
source = target.read_text(encoding='utf-8')
start = source.index('            # Rolling Retention Gate:')
end = source.index('            print(f"Saved:', start)
assert 'shutil.move' in source[start:end] and 'shutil.rmtree' in source[start:end]
assert 'lease.commit()' not in source[start:end]
target.write_text(source[:start] + source[end:], encoding='utf-8')
print('Removed automatic archive/delete only; commit and all history retained')
