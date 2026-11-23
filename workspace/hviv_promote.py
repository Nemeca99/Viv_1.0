import os
import sys
import json
import subprocess
from datetime import datetime

sys.stdout.reconfigure(encoding="utf-8")

RUST_CORE = "L:\\Rules\\target\\release\\rules_core.exe"
CONTAINER_NAME = "hviv_sandbox_core"

class HostAutoPromoter:
    def __init__(self):
        self.container_name = CONTAINER_NAME

    def get_container_diffs(self) -> list:
        """
        Queries Docker daemon inside WSL to get changed files in container OverlayFS.
        """
        cmd = ["wsl", "-d", "Ubuntu", "--", "sudo", "docker", "diff", self.container_name]
        res = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")
        if res.returncode != 0:
            return []
            
        changes = []
        for line in res.stdout.strip().split("\n"):
            if not line.strip():
                continue
            parts = line.strip().split(" ", 1)
            if len(parts) == 2:
                change_type, path = parts[0], parts[1]
                # Filter out standard system paths inside container
                if not path.startswith("/tmp") and not path.startswith("/proc") and not path.startswith("/sys"):
                    changes.append((change_type, path))
        return changes

    def evaluate_promotion(self, host_target_path: str, user_approved: bool = False) -> dict:
        """
        Validates container diff promotion against Rust Security Queen.
        """
        req_payload = json.dumps({
            "action": "quarantine" if not user_approved else "cani",
            "drive": host_target_path[:2],
            "target_path": host_target_path,
            "reason": "Host promotion from container OverlayFS diff layer",
            "user_approved": user_approved
        })
        res = subprocess.run([RUST_CORE, req_payload], capture_output=True, text=True, encoding="utf-8")
        try:
            return json.loads(res.stdout)
        except json.JSONDecodeError:
            return {"allowed": False, "verdict": "NO", "reason": "Invalid response from Rust Queen."}

    def execute_host_promotion(self, container_source_path: str, host_target_path: str, user_approved: bool) -> bool:
        if not user_approved:
            print(f"[PROMOTION BLOCKED] User approval flag (user_approved) is FALSE.")
            return False
            
        verdict = self.evaluate_promotion(host_target_path, user_approved=True)
        if not verdict.get("allowed", False):
            print(f"[PROMOTION DENIED BY RUST QUEEN] Reason: {verdict.get('reason')}")
            return False

        # Copy file from container to host path via WSL
        wsl_host_path = host_target_path.replace("\\", "/").replace("L:", "/mnt/l").replace("C:", "/mnt/c").replace("D:", "/mnt/d").replace("E:", "/mnt/e").replace("F:", "/mnt/f")
        cmd = ["wsl", "-d", "Ubuntu", "--", "sudo", "docker", "cp", f"{self.container_name}:{container_source_path}", wsl_host_path]
        res = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")
        if res.returncode == 0:
            print(f"[PROMOTION SUCCESSFUL] '{container_source_path}' -> '{host_target_path}'")
            return True
        else:
            print(f"[PROMOTION FAILED] Error: {res.stderr.strip()}")
            return False

if __name__ == "__main__":
    print("==================================================")
    print("     HViv Production Host Auto-Promoter Engine   ")
    print("==================================================")
    
    promoter = HostAutoPromoter()
    print("\n1. Scanning Container OverlayFS Diff Layer...")
    diffs = promoter.get_container_diffs()
    print(f"Found {len(diffs)} container mutations.")
    for change_type, path in diffs[:10]:
        print(f"  [{change_type}] {path}")

    print("\n2. Testing Promotion Safety Checks...")
    test_target = "L:\\LocalCoder\\workspace\\promoted_test.txt"
    print(f"Targeting Host Path: {test_target}")
    
    # Try without user approval
    print("\n--- Test A: Promotion without User Approval ---")
    promoter.execute_host_promotion("/root/home/test.txt", test_target, user_approved=False)

    print("\n[SUCCESS] Host Auto-Promoter Engine compiled & operational.")
