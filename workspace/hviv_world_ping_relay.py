import os
import sys
import json
import subprocess
from datetime import datetime

sys.stdout.reconfigure(encoding="utf-8")

RUST_CORE = "L:\\Rules\\target\\release\\rules_core.exe"
SCHEMA_PATH = "L:\\LocalCoder\\workspace\\drive_schemas.json"
DRIVE_MEMORY_SCRIPT = "L:\\LocalCoder\\workspace\\drive_memory_manager.py"

class WorldSignalRelay:
    def __init__(self):
        with open(SCHEMA_PATH, "r", encoding="utf-8") as f:
            self.schemas = json.load(f)

    def ping_world_signal(self, target_world_drive: str, target_script_or_exe: str, script_args: list = None, user_approved: bool = False) -> dict:
        d_clean = target_world_drive[:2].upper()
        if d_clean not in self.schemas:
            return {"allowed": False, "verdict": "NO", "reason": f"Unknown world domain: '{d_clean}'"}

        world_schema = self.schemas[d_clean]
        print(f"[{datetime.now().isoformat()}] [SIGNAL PING] -> World '{d_clean}' ({world_schema['role']})")
        print(f"  └─ Target Script/Exe: '{target_script_or_exe}'")

        # 1. Rust Security Queen Verification on L:
        req_payload = json.dumps({
            "action": "cani",
            "drive": d_clean,
            "target_path": target_script_or_exe,
            "reason": f"World Signal Ping execution trigger for {os.path.basename(target_script_or_exe)}",
            "user_approved": user_approved
        })
        res = subprocess.run([RUST_CORE, req_payload], capture_output=True, text=True, encoding="utf-8")
        try:
            verdict = json.loads(res.stdout)
        except json.JSONDecodeError:
            return {"allowed": False, "verdict": "NO", "reason": "Invalid response from Rust Queen."}

        if not verdict.get("allowed", False):
            print(f"  └─ [PING DENIED BY RUST QUEEN] Reason: {verdict.get('reason')}")
            return verdict

        # 2. Execute Script/Exe in World Context
        print(f"  └─ [PING APPROVED] Executing file in World '{d_clean}'...")
        exec_cmd = []
        ext = os.path.splitext(target_script_or_exe)[1].lower()
        
        if ext == ".py":
            exec_cmd = ["L:\\.venv\\Scripts\\python.exe", target_script_or_exe]
        elif ext in [".exe", ".bat", ".cmd"]:
            exec_cmd = [target_script_or_exe]
        elif ext == ".sh":
            exec_cmd = ["wsl", "-d", "Ubuntu", "--", "bash", target_script_or_exe]
        else:
            exec_cmd = [target_script_or_exe]

        if script_args:
            exec_cmd.extend(script_args)

        try:
            exec_res = subprocess.run(exec_cmd, capture_output=True, text=True, encoding="utf-8", timeout=10)
            output_summary = exec_res.stdout.strip()[:200] if exec_res.returncode == 0 else f"ERROR: {exec_res.stderr.strip()[:200]}"
            print(f"  └─ [EXECUTION SUCCESS] Output: {output_summary}")
            
            # 3. Log into L: Sovereign Chronicle (Queen remembers what she did to all worlds)
            from drive_memory_manager import DriveMemoryManager
            mem_mgr = DriveMemoryManager()
            mem_mgr.record_drive_memory(
                target_drive="L:",
                actor="RustQueen",
                statement=f"Executed signal ping on World '{d_clean}': {os.path.basename(target_script_or_exe)}",
                action=f"WORLD_PING_EXEC_{d_clean}"
            )
            # Also record in target world memory
            mem_mgr.record_drive_memory(
                target_drive=d_clean,
                actor=f"World_{d_clean}_Specialist",
                statement=f"File executed via signal ping: {target_script_or_exe}",
                action="LOCAL_EXEC"
            )

            verdict["execution_output"] = output_summary
            return verdict
        except Exception as e:
            return {"allowed": False, "verdict": "NO", "reason": f"Execution error: {e}"}

if __name__ == "__main__":
    print("==================================================")
    print("   HViv World Signal Ping & Execution Relay      ")
    print("==================================================")
    
    relay = WorldSignalRelay()
    
    # Test Signal Ping on D: Drive Proving Ground (.py file execution)
    test_script = "L:\\LocalCoder\\workspace\\option1_dryrun.py"
    ping_result = relay.ping_world_signal("D:", test_script, user_approved=False)
    print(f"\nFinal Ping Result:\n{json.dumps(ping_result, indent=2)}")
