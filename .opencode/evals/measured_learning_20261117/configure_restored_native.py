"""Use the restored project-local source without probing forbidden toolkit roots."""
import ast
import hashlib
import json
from pathlib import Path
import shutil

root = Path('L:/LocalCoder')
out = root/'.opencode/evals/measured_learning_20261117'
cuda = root/'workspace/native_nn_source/nn_local/cuda_backend.py'
original = cuda.read_text(encoding='utf-8')
assert hashlib.sha256(cuda.read_bytes()).hexdigest() == '5fa7aab2644d19dc426f8785deea60b02f9543bdc1c783836284c236f8bb506a'
shutil.copy2(cuda,out/'cuda_backend_original.py')
tree = ast.parse(original)
assignment = next(node for node in tree.body if isinstance(node,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='CUDA_BIN_CANDIDATES' for t in node.targets))
lines = original.splitlines(keepends=True)
updated = ''.join(lines[:assignment.lineno-1]) + 'CUDA_BIN_CANDIDATES = ()\n' + ''.join(lines[assignment.end_lineno:])
assignment.value = ast.Tuple(elts=[],ctx=ast.Load())
assert ast.dump(tree,include_attributes=False) == ast.dump(ast.parse(updated),include_attributes=False)
cuda.write_text(updated,encoding='utf-8')
configured = []
for basename in ('terminal_neuron_learning.py','wikipedia_curriculum_runner.py'):
    path = root/'workspace/autonomy'/basename
    shutil.copy2(path,out/(basename+'.before_dependency'))
    text = path.read_text(encoding='utf-8')
    tree = ast.parse(text)
    node = next(n for n in tree.body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='STANDALONE' for t in n.targets))
    lines = text.splitlines(keepends=True)
    text = ''.join(lines[:node.lineno-1]) + 'STANDALONE = WORKSPACE / "native_nn_source"\n' + ''.join(lines[node.end_lineno:])
    node.value = ast.parse('WORKSPACE / "native_nn_source"',mode='eval').body
    assert ast.dump(tree,include_attributes=False) == ast.dump(ast.parse(text),include_attributes=False)
    path.write_text(text,encoding='utf-8')
    configured.append(str(path))
report = {'schema':'viv_native_source_configuration_v1','configured':configured,
          'cuda_change':'Only CUDA_BIN_CANDIDATES set to empty: existing DLL needs no explicit toolkit directory discovery.',
          'native_computation_changed':False,'learned_state_changed':False,
          'cuda_sha256':hashlib.sha256(cuda.read_bytes()).hexdigest()}
(out/'native_source_configuration.json').write_text(json.dumps(report,indent=2)+'\n')
print('Configured project-local native source; removed explicit toolkit directory probes only')
