"""Restore verified source/runtime assets only; never copy learned state."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import sys

root = Path('L:/LocalCoder')
workspace = root/'workspace'
sys.path.insert(0, str(workspace))
from aios_rebuild.main_core.mind_runtime_gate import RuntimeBodyGuard
from aios_rebuild.privacy_core.privacy_core import PrivacyCore

source = Path('D:/L_Drive/Standalone/NN')
target = workspace/'native_nn_source'
out = root/'.opencode/evals/measured_learning_20261117'
assert not target.exists(), 'Review an existing restoration before writing'
relative_paths = sorted(path.relative_to(source) for path in (source/'nn_local').rglob('*.py') if '__pycache__' not in path.parts)
relative_paths += [Path('native/build/nn_bucket_cuda.dll'),Path('material/WebstersDictionary/dictionary.json')]
assert len(relative_paths) == 22, f'Review unexpected source inventory: {len(relative_paths)}'
assert all(path.suffix in ('.py','.dll','.json') for path in relative_paths)
guard = RuntimeBodyGuard(requested_threads=1,goal_id='01a1e340-84ed-77c3-92f3-3eb738b89f5b')
body = guard.check(force=True)
privacy = PrivacyCore()
manifest = []
for relative in relative_paths:
    destination = target/relative
    decision = privacy.authorize_file_write(str(destination))
    if decision.get('allowed') is not True:
        raise PermissionError(f'PrivacyCore denied restoration: {destination}: {decision}')
    data = (source/relative).read_bytes()
    expected = hashlib.sha256(data).hexdigest()
    destination.parent.mkdir(parents=True,exist_ok=True)
    shutil.copy2(source/relative,destination)
    actual = hashlib.sha256(destination.read_bytes()).hexdigest()
    if actual != expected:
        raise RuntimeError(f'Restored source hash mismatch: {relative}')
    manifest.append({'relative_path':relative.as_posix(),'bytes':len(data),'source_sha256':expected,'copied_sha256':actual,'privacy':decision})
report = {'schema':'viv_native_source_restoration_v1','at_utc':datetime.now(timezone.utc).isoformat(),
          'source_root':str(source),'candidate_root':str(target),'files':manifest,'body_gate':body,
          'learned_state_copied':False,'runtime_executed':False,'scope':'Exact source plus native DLL and immutable lexical source asset; C-toolkit discovery must be corrected before CUDA construction.'}
(out/'native_source_restoration.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
print(f'Verified {len(manifest)} restored files; {sum(row["bytes"] for row in manifest)} bytes; no learned-state copies')
