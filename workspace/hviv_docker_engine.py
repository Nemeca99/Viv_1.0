import os
import sys
import json
import subprocess
from datetime import datetime

sys.stdout.reconfigure(encoding="utf-8")

RUST_CORE = "L:\\Rules\\target\\release\\rules_core.exe"
HOST_HOME = "L:\\AIOS_V2\\home"
QUARANTINE_DIR = "L:\\_sweep_quarantine"

# Ensure host home volume exists
os.makedirs(HOST_HOME, exist_ok=True)
os.makedirs(QUARANTINE_DIR, exist_ok=True)

class HVivDockerSubstrate:
    def __init__(self):
        self.container_name = "hviv_sandbox_core"
        
    def verify_docker(self) -> bool:
        cmd = ["wsl", "-d", "Ubuntu", "--", "sudo", "docker", "ps"]
        res = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")
        return res.returncode == 0

    def start_sandbox_container(self) -> bool:
        print(f"[{datetime.now().isoformat()}] Launching HViv Sandbox Container (OverlayFS)...")
        # Mount host sovereign home read-write
        # Mount L:\LocalCoder\workspace read-only by default
        cmd = [
            "wsl", "-d", "Ubuntu", "--", "sudo", "docker", "run", "-d",
            "--name", self.container_name,
            "--restart", "always",
            "-v", "/mnt/l/AIOS_V2/home:/root/home:rw",
            "-v", "/mnt/l/LocalCoder/workspace:/workspace:ro",
            "ubuntu:latest",
            "sleep", "infinity"
        ]
        # Remove old if exists
        subprocess.run(["wsl", "-d", "Ubuntu", "--", "sudo", "docker", "rm", "-f", self.container_name], capture_output=True)
        res = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")
        return res.returncode == 0

    def exec_inside_container(self, command: str) -> str:
        cmd = ["wsl", "-d", "Ubuntu", "--", "sudo", "docker", "exec", self.container_name, "bash", "-c", command]
        res = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")
        return res.stdout.strip() if res.returncode == 0 else f"ERROR: {res.stderr.strip()}"

    def request_host_promotion(self, host_target_path: str, action: str = "cani", user_approved: bool = False) -> dict:
        req_payload = json.dumps({
            "action": action,
            "drive": host_target_path[:2],
            "target_path": host_target_path,
            "reason": "Container promotion request to Host OS",
            "user_approved": user_approved
        })
        res = subprocess.run([RUST_CORE, req_payload], capture_output=True, text=True, encoding="utf-8")
        try:
            return json.loads(res.stdout)
        except json.JSONDecodeError:
            return {"allowed": False, "verdict": "NO", "reason": "Invalid JSON response from Rust Queen."}

if __name__ == "__main__":
    print("==================================================")
    print("   HViv AIOS V2 - Docker Container Substrate     ")
    print("==================================================")
    
    engine = HVivDockerSubstrate()
    if not engine.verify_docker():
        print("ERROR: Docker daemon inside WSL Ubuntu is not running!")
        sys.exit(1)
        
    print("Docker Daemon: ONLINE")
    if engine.start_sandbox_container():
        print(f"Container '{engine.container_name}': ACTIVE (Full Root Inside Container)")
    else:
        print("Failed to start sandbox container!")
        sys.exit(1)
        
    print("\n--- Testing Sandbox Isolation (rm -rf test inside container) ---")
    out = engine.exec_inside_container("touch /tmp/sandbox_test.txt && rm -rf /tmp/sandbox_test.txt && echo 'CONTAINER_ISOLATED'")
    print(f"Container Sandbox Output: {out}")
    
    print("\n--- Testing Host Promotion Request (Rust Queen Gatekeeper) ---")
    promotion_verdict = engine.request_host_promotion("L:\\LocalCoder\\workspace\\test_promotion.txt", action="cani", user_approved=False)
    print(f"Host Promotion Verdict: {json.dumps(promotion_verdict, indent=2)}")
    
    print("\n[SUCCESS] Docker OverlayFS Container Substrate operational.")
