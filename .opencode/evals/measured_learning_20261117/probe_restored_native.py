"""Measure restored substrate availability after Rust admission; no learning writes."""
import hashlib
import json
from pathlib import Path
import sys

root = Path('L:/LocalCoder')
workspace = root/'workspace'
sys.path.insert(0,str(workspace))
from aios_rebuild.main_core.mind_runtime_gate import RuntimeBodyGuard
body = RuntimeBodyGuard(requested_threads=1,goal_id='01a1e340-84ed-77c3-92f3-3eb738b89f5b').check(force=True)
from autonomy import terminal_neuron_learning as learner
from nn_local import cuda_backend
from nn_local.neuronizer import Neuronizer,UniversalCurriculumEngine
from nn_local.steel_brain_store import SQLiteNeuronGraphStore
assert learner.STANDALONE == workspace/'native_nn_source'
assert cuda_backend.CUDA_BIN_CANDIDATES == ()
assert Path(cuda_backend.__file__).is_relative_to(learner.STANDALONE)
manifest = json.loads((root/'.opencode/evals/measured_learning_20261117/native_source_restoration.json').read_text())
for row in manifest['files']:
    if row['relative_path'] == 'nn_local/cuda_backend.py':
        continue
    assert hashlib.sha256((learner.STANDALONE/row['relative_path']).read_bytes()).hexdigest() == row['source_sha256']
native = cuda_backend.CudaLibrary()
report = {'schema':'viv_restored_native_probe_v1','body_gate':body,'module_path':cuda_backend.__file__,
          'native_version':native.dll.nn_bucket_version().decode('utf-8'),
          'cuda_available':bool(native.dll.nn_cuda_available()),
          'classes_available':['Neuronizer','UniversalCurriculumEngine','SQLiteNeuronGraphStore'],
          'learning_executed':False,'explicit_toolkit_probes':False}
(root/'.opencode/evals/measured_learning_20261117/native_probe.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps({k:v for k,v in report.items() if k!='body_gate'},indent=2))
assert report['cuda_available'], 'CUDA unavailable; keep actual readiness failure'
