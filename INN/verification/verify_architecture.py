import json
import math
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from inn.sheet_engine import SheetEngine

engine=SheetEngine()
errors=[]
count=0
for (sheet,address),formula in engine.cells.items():
    if not isinstance(formula,str) or not formula.startswith('='): continue
    count+=1
    expected=engine.cached.get((sheet,address),'')
    try:
        actual=engine.cell(sheet,address)
        equal=math.isclose(actual,expected,rel_tol=1e-8,abs_tol=1e-8) if isinstance(expected,(int,float)) and isinstance(actual,(int,float)) else actual==expected
        if not equal: errors.append(dict(sheet=sheet,cell=address,expected=expected,actual=actual,formula=formula))
    except Exception as error:
        errors.append(dict(sheet=sheet,cell=address,error=str(error),formula=formula))
receipt=dict(formulas=count,matched=count-len(errors),errors=errors)
changed=SheetEngine(overrides={'Pesonal!B1':0})
assert changed.cell('Training_Pipeline','E7')==0
assert changed.cell('Training_Pipeline','B13')=='BROKEN'
receipt['changed_input_recalculation']='PASS: Pesonal B1=0 propagates to E7=0 and B13=BROKEN'
(ROOT/'verification/artifacts/architecture.json').write_text(json.dumps(receipt,indent=2),encoding='utf-8')
print(json.dumps(dict(receipt,errors=errors[:20]),indent=2))
if errors: sys.exit(1)
