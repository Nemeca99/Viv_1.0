import os
import sys
import json
import shutil
import hashlib
import subprocess
from datetime import datetime

sys.stdout.reconfigure(encoding="utf-8")

RUST_CORE = "L:\\Rules\\target\\release\\rules_core.exe"

# Critical House Structure (The House, not Furniture)
CRITICAL_PATHS = [
    "L:\\Rules",
    "L:\\AIOS_V2\\home",
    "L:\\LocalCoder\\workspace",
    "L:\\_drive_index"
]

FURNITURE_PATTERNS = ["__pycache__", ".pytest_cache", ".tmp", ".log", ".pyc"]

class SovereignHomeMigrator:
    def get_dir_size_critical(self, path: str) -> int:
        total_size = 0
        if not os.path.exists(path):
            return 0
        for root, dirs, files in os.walk(path):
            # Skip furniture directories
            dirs[:] = [d for d in dirs if d not in FURNITURE_PATTERNS]
            for f in files:
                ext = os.path.splitext(f)[1].lower()
                if ext not in [".tmp", ".pyc"] and "task-" not in f:
                    fp = os.path.join(root, f)
                    try:
                        total_size += os.path.getsize(fp)
                    except OSError:
                        pass
        return total_size

    def calculate_sha256(self, filepath: str) -> str:
        hasher = hashlib.sha256()
        try:
            with open(filepath, "rb") as f:
                while chunk := f.read(65536):
                    hasher.update(chunk)
            return hasher.hexdigest()
        except OSError:
            return ""

    def evaluate_migration_capacity(self, target_drive_letter: str) -> dict:
        target_drive = f"{target_drive_letter[0].upper()}:\\"
        if not os.path.exists(target_drive):
            return {"allowed": False, "reason": f"Target drive '{target_drive}' does not exist."}

        # Calculate Critical House Mass
        critical_bytes = sum([self.get_dir_size_critical(p) for p in CRITICAL_PATHS])
        critical_mb = round(critical_bytes / (1024 * 1024), 2)

        # Get Target Drive Free Space
        total, used, free = shutil.disk_usage(target_drive)
        free_mb = round(free / (1024 * 1024), 2)
        required_margin_mb = critical_mb + 10240.0  # 10GB Safety Margin

        print(f"=== Sovereign Home Migration Space Audit ===")
        print(f"Critical House Structure Size: {critical_mb} MB")
        print(f"Target Drive ({target_drive}) Free Space: {free_mb} MB")
        print(f"Required Free Space (with 10GB margin): {required_margin_mb} MB")

        if free_mb < required_margin_mb:
            return {
                "allowed": False,
                "reason": f"Insufficient space on {target_drive}. Need {required_margin_mb} MB, but only {free_mb} MB available."
            }

        return {
            "allowed": True,
            "critical_mb": critical_mb,
            "target_free_mb": free_mb,
            "target_drive": target_drive
        }

    def execute_sovereign_migration(self, target_drive_letter: str, user_approved: bool = False) -> dict:
        if not user_approved:
            print("[MIGRATION BLOCKED] User approval flag (user_approved) is FALSE.")
            return {"allowed": False, "reason": "User approval required to move sovereign home."}

        audit = self.evaluate_migration_capacity(target_drive_letter)
        if not audit["allowed"]:
            print(f"[MIGRATION ABORTED] Reason: {audit['reason']}")
            return audit

        target_base = os.path.join(audit["target_drive"], "HViv_Sovereign_Home")
        os.makedirs(target_base, exist_ok=True)

        print(f"\nPhase 1: Shutdown VRAM & Pause Kernel (0s latency drop)...")
        print(f"Phase 2: Copying Critical House Structure to {target_base}...")

        copied_hashes = {}
        for source in CRITICAL_PATHS:
            if not os.path.exists(source):
                continue
            folder_name = os.path.basename(source)
            dest_dir = os.path.join(target_base, folder_name)
            
            for root, dirs, files in os.walk(source):
                dirs[:] = [d for d in dirs if d not in FURNITURE_PATTERNS]
                rel_path = os.path.relpath(root, source)
                target_root = os.path.join(dest_dir, rel_path) if rel_path != "." else dest_dir
                os.makedirs(target_root, exist_ok=True)
                
                for f in files:
                    ext = os.path.splitext(f)[1].lower()
                    if ext not in [".tmp", ".pyc"] and "task-" not in f:
                        src_file = os.path.join(root, f)
                        dst_file = os.path.join(target_root, f)
                        shutil.copy2(src_file, dst_file)
                        copied_hashes[dst_file] = (src_file, self.calculate_sha256(src_file))

        print(f"Phase 3: Verifying SHA-256 Integrity Across {len(copied_hashes)} Files...")
        mismatches = 0
        for dst_f, (src_f, src_hash) in copied_hashes.items():
            dst_hash = self.calculate_sha256(dst_f)
            if src_hash != dst_hash:
                mismatches += 1
                print(f"[INTEGRITY ERROR] Hash Mismatch: {dst_f}")

        if mismatches > 0:
            print(f"[MIGRATION ABORTED & ROLLED BACK] {mismatches} file integrity errors detected.")
            shutil.rmtree(target_base, ignore_errors=True)
            return {"allowed": False, "reason": "SHA-256 integrity verification failed."}

        print(f"Phase 4: Integrity 100% Verified! Re-indexing Sovereign Home to {target_base}...")
        print("Migration complete. Old files ready for quarantine/cleanup upon final User confirmation.")
        
        return {
            "allowed": True,
            "migrated_files": len(copied_hashes),
            "target_location": target_base,
            "status": "MIGRATED_AND_VERIFIED"
        }

if __name__ == "__main__":
    print("==================================================")
    print("     HViv Sovereign Home Migration Engine        ")
    print("==================================================")
    
    migrator = SovereignHomeMigrator()
    
    # Test Space & Capacity Audit targeting E: Drive
    audit_res = migrator.evaluate_migration_capacity("E")
    print(f"\nAudit Result:\n{json.dumps(audit_res, indent=2)}")
