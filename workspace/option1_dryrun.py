import os
import json
import sys
import subprocess
from datetime import datetime

# UTF-8 stdout
sys.stdout.reconfigure(encoding="utf-8")

DRIVE = "L:\\"
QUARANTINE_DIR = "L:\\_sweep_quarantine"
RUST_CORE = "L:\\Rules\\target\\release\\rules_core.exe"

print(f"=== Option 1: Controlled Maintenance Scan on {DRIVE} ===")
print(f"Timestamp: {datetime.now().isoformat()}")

candidate_extensions = [".pyc", ".tmp", ".log", ".bak"]
candidate_dirs = ["__pycache__", ".pytest_cache"]

print("\nScanning drive index and workspace for candidates...")

stale_files = []
total_bytes = 0

for root, dirs, files in os.walk("L:\\LocalCoder\\workspace"):
    # Skip protected paths
    if "_sweep_quarantine" in root or "Rules" in root or ".git" in root:
        continue
        
    for d in dirs:
        if d in candidate_dirs:
            full_dir = os.path.join(root, d)
            for r, _, f_list in os.walk(full_dir):
                for f in f_list:
                    fp = os.path.join(r, f)
                    try:
                        sz = os.path.getsize(fp)
                        stale_files.append((fp, sz))
                        total_bytes += sz
                    except OSError:
                        pass
                        
    for f in files:
        ext = os.path.splitext(f)[1].lower()
        if ext in candidate_extensions and "task-" not in f:
            fp = os.path.join(root, f)
            try:
                sz = os.path.getsize(fp)
                stale_files.append((fp, sz))
                total_bytes += sz
            except OSError:
                pass

print(f"\n--- Scan Complete ---")
print(f"Total Candidate Files Found: {len(stale_files)}")
print(f"Total Reclaimable Space: {total_bytes / (1024 * 1024):.2f} MB")

print("\n--- Rust Core Dry-Run Security Evaluation ---")
sample_files = stale_files[:5]
for fp, sz in sample_files:
    req_payload = json.dumps({
        "action": "cani",
        "drive": "L:",
        "target_path": fp,
        "reason": "Routine Python cache maintenance scan",
        "user_approved": False
    })
    cmd = [RUST_CORE, req_payload]
    res = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")
    print(f"Target: {os.path.basename(fp)} -> Rust Verdict: {res.stdout.strip()}")

proposal = {
    "timestamp": datetime.now().isoformat(),
    "drive": DRIVE,
    "candidate_count": len(stale_files),
    "total_reclaimable_mb": round(total_bytes / (1024 * 1024), 2),
    "sample_targets": [fp for fp, _ in sample_files],
    "user_approved": False,
    "status": "AWAITING_USER_APPROVAL"
}

with open("L:\\LocalCoder\\workspace\\maintenance_proposal.json", "w", encoding="utf-8") as f:
    json.dump(proposal, f, indent=2)

print("\nProposal saved to: L:\\LocalCoder\\workspace\\maintenance_proposal.json")
print("Status: AWAITING USER APPROVAL (Prime Law 1)")
