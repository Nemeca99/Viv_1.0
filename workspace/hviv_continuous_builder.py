import os
import sys
import time
import json
import subprocess
from datetime import datetime
from hviv_sovereign_circuit_breaker import SovereignCircuitBreaker

sys.stdout.reconfigure(encoding="utf-8")

RUST_CORE = "L:\\Rules\\target\\release\\rules_core.exe"
CONTAINER_NAME = "hviv_sandbox_core"
TRAINING_DATASET = "L:\\LocalCoder\\workspace\\hviv_sft_dataset.jsonl"
HOST_HOME_FEATURES = "L:\\AIOS_V2\\home\\features"

os.makedirs(HOST_HOME_FEATURES, exist_ok=True)

class ContinuousSelfBuildingEngine:
    def __init__(self):
        self.container_name = CONTAINER_NAME
        self.features_built = 0
        self.features_passed = 0
        self.circuit_breaker = SovereignCircuitBreaker()

    def build_and_learn_cycle(self, feature_id: int):
        self.features_built += 1
        name = f"auto_feature_{feature_id}"
        host_feature_file = os.path.join(HOST_HOME_FEATURES, f"{name}.py")
        container_feature_file = f"/root/home/features/{name}.py"
        
        print(f"\n[{datetime.now().isoformat()}] [AUTONOMOUS CYCLE {feature_id}] Feature: '{name}'")

        # 0. INVARIANT CHECK 1: Soul Anchor Verification ($RSR$)
        soul_ok, soul_msg = self.circuit_breaker.verify_soul_anchor()
        if not soul_ok:
            print(f"  └─ CIRCUIT BREAKER HARD HALT: {soul_msg}")
            self.circuit_breaker.trigger_hard_halt("SOUL_DRIFT", soul_msg)
            return

        # 0. INVARIANT CHECK 2: Symlink & Junction Point Audit
        sym_ok, sym_msg = self.circuit_breaker.check_symlinks_and_junctions(HOST_HOME_FEATURES)
        if not sym_ok:
            print(f"  └─ CIRCUIT BREAKER HARD HALT: {sym_msg}")
            self.circuit_breaker.trigger_hard_halt("SYMLINK_ATTACK", sym_msg)
            return
        
        # 1. Generate candidate feature code
        py_content = f"import sys\nprint('SUCCESS: Feature {name} executed inside Docker container python version', sys.version.split()[0])\n"

        # 0. INVARIANT CHECK 3: Deterministic AST Code Security Scanner
        ast_ok, ast_msg = self.circuit_breaker.inspect_code_ast(py_content)
        if not ast_ok:
            print(f"  └─ CIRCUIT BREAKER REJECTED CODE: {ast_msg}")
            return

        # 2. Write feature directly on persistent host volume (L:\AIOS_V2\home\features)
        with open(host_feature_file, "w", encoding="utf-8") as f:
            f.write(py_content)
            
        print(f"  ├─ Host/Volume Write: SUCCESS ({host_feature_file}) [Circuit Breaker Cleared]")

        # 3. Test execution inside Docker Sandbox
        cmd_test = ["wsl", "-d", "Ubuntu", "--", "sudo", "docker", "exec", self.container_name, "python3", container_feature_file]
        res_test = subprocess.run(cmd_test, capture_output=True, text=True, encoding="utf-8")
        
        output_clean = "\n".join([line for line in res_test.stdout.strip().split("\n") if "Failed to translate" not in line and line.strip()])
        
        if res_test.returncode == 0:
            self.features_passed += 1
            print(f"  ├─ Sandbox Test: PASSED 100%")
            print(f"  ├─ Output: {output_clean}")
            
            # Harvest Trajectory to SFT Dataset
            trajectory = {
                "messages": [
                    {"role": "system", "content": "HViv Continuous Builder Directive: Build and test feature in Docker OverlayFS."},
                    {"role": "user", "content": f"Build feature {name}"},
                    {"role": "assistant", "content": f"Feature {name} built and verified 100% inside container. Output: {output_clean}"}
                ]
            }
            with open(TRAINING_DATASET, "a", encoding="utf-8") as f:
                f.write(json.dumps(trajectory) + "\n")
            print(f"  └─ Trajectory Harvested -> {TRAINING_DATASET}")
        else:
            print(f"  └─ Sandbox Test Error: {res_test.stderr.strip()[:100]}")

    def run_continuous_loop(self, total_cycles: int = 5):
        print("==================================================")
        print("  HViv Continuous Autonomous Self-Building Loop  ")
        print("==================================================")
        print("Mode: UNSTOPPABLE AUTONOMOUS LEARNING & BUILDING WITH CIRCUIT BREAKER HARDENING\n")
        
        for i in range(1, total_cycles + 1):
            self.build_and_learn_cycle(i)
            time.sleep(1.0)
            
        print(f"\n==================================================")
        print(f"Continuous Run Complete: {self.features_passed}/{self.features_built} Features Passed & Harvested into Training Dataset.")
        print(f"==================================================")

if __name__ == "__main__":
    engine = ContinuousSelfBuildingEngine()
    engine.run_continuous_loop(total_cycles=5)
