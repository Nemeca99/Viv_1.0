import hashlib,json,sys
from datetime import datetime,timezone
from pathlib import Path
root=Path(__file__).resolve().parents[1]
def sha(path): return hashlib.sha256(path.read_bytes()).hexdigest()
expected={'FarmScript.txt':'0b236df2a87f5a3e48e09b2aefd93c139df491a39bd1639a52ef653a437e48ae','Integrated Neural Network Architecture.xlsx':'62f4aec7f14fb085838f5aa2d4cd788e81cd7b8fe25154b4e0d51aca5cebadd5'}
assert all(sha(root/name)==digest for name,digest in expected.items())
evidence={name:json.loads((root/'verification/artifacts'/name).read_text()) for name in ['source-100000.json','source-repair.json','architecture.json','cli-continuity.json','learning-evaluation.json','gate-threshold-sweep.json','learned-v9-evaluation.json','survival-guard.json']}
assert evidence['source-100000.json']['status']=='PASS'
assert evidence['source-repair.json']['original_hard_reset_matched']
assert evidence['architecture.json']['matched']==780
assert evidence['learning-evaluation.json']['status']=='COMPLETE'
assert evidence['learned-v9-evaluation.json']['status']=='PASS'
assert evidence['survival-guard.json']['status']=='PASS'
files=[*root.glob('inn/*.py'),*root.glob('*.py'),root/'README.md',root/'Run.ps1',root/'farm_rust/src/lib.rs',root/'farm_rust/target/release/inn_farm.dll']
receipt=dict(created_utc=datetime.now(timezone.utc).isoformat(),status='SOURCE_FIDELITY_VERIFIED',python=sys.executable,
 source_hashes=expected,implementation_hashes={str(p.relative_to(root)):sha(p) for p in files},
 evidence=evidence,logged_run='runs/20261008T072039584171Z',
 limitation='After 100000 extra training steps the frozen policy scored zero harvests across eight held-out seeds. Useful learning is not achieved; the source update/selection algorithm requires repair. The added neural Transformer remains experimental.',
 supersedes='BUILD_RECEIPT.json: previous default and completion claims',backup='repair_backups/20261008T020749')
(root/'build_receipts/REPAIR_RECEIPT.json').write_text(json.dumps(receipt,indent=2))
print('Repair receipt written; original source hashes unchanged.')
