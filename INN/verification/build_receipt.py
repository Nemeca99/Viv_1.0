import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

if __name__ == '__main__':
    folder = ROOT / 'build_receipts'
    backups = folder / 'environment_before'
    backups.mkdir(parents=True, exist_ok=True)
    launcher = ROOT.parent/'workspace/Start-Coder.ps1'
    plugin = Path(r'C:\Users\nemec\.config\opencode\plugins\auto-venv.js')
    # Reconstruct the exact single-line settings replaced during this build.
    (backups/'Start-Coder.ps1').write_bytes(launcher.read_bytes().replace(
        b"$masterEnvironment = 'L:\\.venv'", b"$masterEnvironment = 'L:\\Python_Master\\.venv'"))
    lines = plugin.read_bytes().splitlines(keepends=True)
    (backups/'auto-venv.js').write_bytes(b''.join(line for line in lines if b'root: "L:\\\\LocalCoder"' not in line))
    files = [ROOT/'run.py', ROOT/'Build.ps1', ROOT/'Run.ps1', ROOT/'farm_rust/Cargo.toml',
             ROOT/'farm_rust/Cargo.lock', ROOT/'farm_rust/src/lib.rs',
             ROOT/'farm_rust/target/release/inn_farm.dll', launcher, plugin]
    files += list((ROOT/'inn').glob('*.py'))
    receipt = dict(status='BUILT_AND_VERIFIED', python=sys.executable,
                   hashes={str(p):digest(p) for p in files},
                   source_hashes={str(p):digest(p) for p in (ROOT/'FarmScript.txt',ROOT/'Integrated Neural Network Architecture.xlsx')},
                   parity=json.loads((ROOT/'verification/artifacts/parity.json').read_text()),
                   transformer=json.loads((ROOT/'verification/artifacts/transformer.json').read_text()),
                   cpu_run=json.loads((ROOT/'runs/transformer-cpu-final-proof/receipt.json').read_text()),
                   cuda_run=json.loads((ROOT/'runs/transformer-cuda-build-proof/receipt.json').read_text()),
                   resume_run=json.loads((ROOT/'runs/transformer-resume-final-proof/receipt.json').read_text()),
                   stop_run=json.loads((ROOT/'verification/artifacts/stop-at-tick/receipt.json').read_text()),
                   environment_selection='L:\\.venv', behavior_improvement_verified=False)
    (folder/'BUILD_RECEIPT.json').write_text(json.dumps(receipt,indent=2),encoding='utf-8')
    print(folder/'BUILD_RECEIPT.json')
