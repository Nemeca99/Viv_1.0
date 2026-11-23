import os
import sys
import json
import subprocess
from datetime import datetime

sys.stdout.reconfigure(encoding="utf-8")

RUST_CORE = "L:\\Rules\\target\\release\\rules_core.exe"
CONTAINER_NAME = "hviv_sandbox_core"

class AutonomousSelfBuilderEngine:
    def __init__(self):
        self.container_name = CONTAINER_NAME

    def luna_propose_feature(self, feature_name: str, python_code: str) -> dict:
        """
        Step 1: Luna writes code for a new feature inside her sandbox container.
        """
        print(f"[{datetime.now().isoformat()}] [LUNA SELF-BUILDING] Feature: '{feature_name}'")
        print(f"  ├─ Writing feature code inside Docker sandbox container ({self.container_name})...")
        
        container_file_path = f"/root/home/features/{feature_name}.py"
        
        # Create dir and file inside container
        cmd_mkdir = ["wsl", "-d", "Ubuntu", "--", "sudo", "docker", "exec", self.container_name, "mkdir", "-p", "/root/home/features"]
        subprocess.run(cmd_mkdir, capture_output=True)

        # Write code inside container using bash echo
        escaped_code = python_code.replace('"', '\\"').replace('$', '\\$')
        cmd_write = ["wsl", "-d", "Ubuntu", "--", "sudo", "docker", "exec", self.container_name, "bash", "-c", f"cat << 'EOF' > {container_file_path}\n{python_code}\nEOF"]
        res = subprocess.run(cmd_write, capture_output=True, text=True, encoding="utf-8")
        
        if res.returncode == 0:
            print(f"  └─ [SANDBOX WRITE SUCCESS] Code written to '{container_file_path}'")
            return {"success": True, "container_path": container_file_path}
        else:
            print(f"  └─ [SANDBOX WRITE FAILED] Error: {res.stderr.strip()}")
            return {"success": False, "error": res.stderr.strip()}

    def mentor_guide_and_test(self, container_file_path: str) -> dict:
        """
        Step 2: Mentor (Antigravity/User) guides and executes tests inside container.
        """
        print(f"\n[MENTOR GUIDANCE & TESTING] Testing '{container_file_path}' inside sandbox...")
        cmd_test = ["wsl", "-d", "Ubuntu", "--", "sudo", "docker", "exec", self.container_name, "python3", container_file_path]
        res = subprocess.run(cmd_test, capture_output=True, text=True, encoding="utf-8")
        
        output = res.stdout.strip()
        errors = res.stderr.strip()
        
        if res.returncode == 0:
            print(f"  ├─ Test Execution: PASSED 100%")
            print(f"  └─ Test Output: {output[:150]}")
            return {"passed": True, "output": output}
        else:
            print(f"  ├─ Test Execution: FAILED (Learning Opportunity)")
            print(f"  └─ Error Feedback: {errors[:150]}")
            return {"passed": False, "error": errors}

    def evaluate_host_promotion(self, host_target_path: str, user_approved: bool = False) -> dict:
        """
        Step 3: Evaluate if feature is ready for host promotion via Rust Queen.
        """
        print(f"\n[RUST QUEEN EVALUATION] Checking host promotion to '{host_target_path}'...")
        req_payload = json.dumps({
            "action": "cani",
            "drive": host_target_path[:2],
            "target_path": host_target_path,
            "reason": "Self-built feature promotion",
            "user_approved": user_approved
        })
        res = subprocess.run([RUST_CORE, req_payload], capture_output=True, text=True, encoding="utf-8")
        try:
            return json.loads(res.stdout)
        except json.JSONDecodeError:
            return {"allowed": False, "reason": "Invalid JSON response from Rust Queen."}

if __name__ == "__main__":
    print("==================================================")
    print("  HViv Luna Self-Guided Learning & Builder Engine")
    print("==================================================")
    
    builder = AutonomousSelfBuilderEngine()
    
    # Example: Luna writes a new system telemetry feature herself
    sample_feature_code = """
import sys
import platform

def luna_telemetry():
    print("=== Luna Self-Built Telemetry Feature ===")
    print(f"Python Substrate: {sys.version.split()[0]}")
    print(f"OS Platform: {platform.system()} {platform.release()}")
    print("Status: SELF_BUILT_AND_VERIFIED")

if __name__ == "__main__":
    luna_telemetry()
"""
    
    # 1. Luna writes feature in container
    write_res = builder.luna_propose_feature("telemetry_v1", sample_feature_code)
    
    if write_res["success"]:
        # 2. Mentor guides & tests feature
        test_res = builder.mentor_guide_and_test(write_res["container_path"])
        
        # 3. Rust Queen evaluates host promotion
        eval_res = builder.evaluate_host_promotion("L:\\LocalCoder\\workspace\\telemetry_v1.py", user_approved=False)
        print(f"  └─ Rust Queen Verdict: Allowed = {eval_res.get('allowed')} | Reason: {eval_res.get('reason')}")
