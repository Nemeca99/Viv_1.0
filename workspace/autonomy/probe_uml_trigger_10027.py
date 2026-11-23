import json,sys
from pathlib import Path
sys.path.insert(0,r'L:\LocalCoder\workspace\autonomy')
from candidate_uml_grounding_v1 import context_for_task
suite=json.loads(Path(r'L:\LocalCoder\workspace\autonomy\learning\deepseek_candidate_runs\frozen_code_eval_v2_1.json').read_text(encoding='utf-8'))
rows={x['id']:x for x in suite['held_out']}
assert context_for_task(rows['py_run_length_encode'])['applicable'] is False
assert context_for_task(rows['py_ceil_division'])['applicable'] is True
assert context_for_task(rows['py_is_divisible'])['applicable'] is True
assert context_for_task(rows['rs_ceil_division'])['applicable'] is True
print('PASS: arithmetic tasks receive UML context; character/count prose does not.')
for ident in ('py_ceil_division','py_is_divisible','py_run_length_encode','rs_ceil_division','rs_is_divisible','rs_run_length_encode'):
 row=rows[ident]; item=context_for_task(row); print(ident,'uml_context',item['applicable'])