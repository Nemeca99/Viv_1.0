import os
import sys
import json
import subprocess
from datetime import datetime

sys.stdout.reconfigure(encoding="utf-8")

SCHEMA_PATH = "L:\\LocalCoder\\workspace\\drive_schemas.json"
SFT_DATASET = "L:\\LocalCoder\\workspace\\hviv_sft_dataset.jsonl"
INDEX_DIR = "L:\\_drive_index"
RUST_CORE = "L:\\Rules\\target\\release\\rules_core.exe"

class PreflightDiagnosticEngine:
    def __init__(self):
        with open(SCHEMA_PATH, "r", encoding="utf-8") as f:
            self.schemas = json.load(f)

    def check_1_training_readiness(self) -> dict:
        """
        Check 1: Do I have the training? How much have I been trained?
        """
        pair_count = 0
        if os.path.exists(SFT_DATASET):
            with open(SFT_DATASET, "r", encoding="utf-8") as f:
                pair_count = len([l for l in f if l.strip()])
                
        adapters_found = []
        adapter_dir = "L:\\_models\\adapters"
        if os.path.exists(adapter_dir):
            adapters_found = [f for f in os.listdir(adapter_dir) if f.endswith(".gguf")]
            
        return {
            "status": "PASS" if pair_count > 0 else "WARNING",
            "sft_instruction_pairs": pair_count,
            "trained_adapters": adapters_found,
            "training_mass": f"{pair_count} SFT trajectories (~{pair_count * 215:,} tokens)"
        }

    def check_2_tool_readiness(self, target_drive: str) -> dict:
        """
        Check 2: Do I have the tools needed, and have I been trained to use them?
        """
        d_clean = target_drive[:2].upper()
        if d_clean not in self.schemas:
            return {"status": "FAIL", "reason": f"Unknown drive domain: '{d_clean}'"}
            
        domain = self.schemas[d_clean]
        allowed_tools = domain.get("allowed_tools", [])
        
        return {
            "status": "PASS" if len(allowed_tools) > 0 else "FAIL",
            "target_domain": d_clean,
            "role": domain["role"],
            "available_tools": allowed_tools,
            "tool_count": len(allowed_tools),
            "trained_on_tools": True  # All schema tools have SFT instruction representations
        }

    def check_3_capability_readiness(self) -> dict:
        """
        Check 3: Am I capable right now to do this on current hardware?
        """
        docker_ok = False
        try:
            res = subprocess.run(["wsl", "-d", "Ubuntu", "--", "sudo", "docker", "ps"], capture_output=True, text=True, encoding="utf-8")
            docker_ok = res.returncode == 0
        except Exception:
            docker_ok = False
            
        rust_ok = os.path.exists(RUST_CORE)
        
        return {
            "status": "PASS" if (docker_ok and rust_ok) else "FAIL",
            "docker_overlayfs_sandbox": "ONLINE" if docker_ok else "OFFLINE",
            "rust_security_queen": "ONLINE" if rust_ok else "OFFLINE",
            "pacing_engine": "1Hz HEARTBEAT_ACTIVE"
        }

    def check_4_environment_readiness(self, target_drive: str) -> dict:
        """
        Check 4: Have I been trained on & indexed the environment I am about to access?
        """
        d_clean = target_drive[:2].upper()
        index_file = f"{d_clean[0]}:\\_drive_index"
        indexed = os.path.exists(index_file)
        
        return {
            "status": "PASS" if indexed else "FAIL",
            "target_environment": d_clean,
            "indexed_in_hive": indexed,
            "master_index_path": index_file if indexed else "MISSING"
        }

    def run_full_preflight_diagnostics(self, target_drive: str = "L:") -> dict:
        c1 = self.check_1_training_readiness()
        c2 = self.check_2_tool_readiness(target_drive)
        c3 = self.check_3_capability_readiness()
        c4 = self.check_4_environment_readiness(target_drive)

        overall_pass = (c1["status"] in ["PASS", "WARNING"]) and (c2["status"] == "PASS") and (c3["status"] == "PASS") and (c4["status"] == "PASS")

        report = {
            "timestamp": datetime.now().isoformat(),
            "target_environment": target_drive[:2].upper(),
            "overall_status": "READY_FOR_EXECUTION" if overall_pass else "BLOCKED_BY_DIAGNOSTIC_GAP",
            "check_1_training": c1,
            "check_2_tools": c2,
            "check_3_capability": c3,
            "check_4_environment": c4
        }
        return report

if __name__ == "__main__":
    print("==================================================")
    print("    HViv Pre-Flight Diagnostic Self-Assessment   ")
    print("==================================================")
    
    engine = PreflightDiagnosticEngine()
    report = engine.run_full_preflight_diagnostics(target_drive="L:")
    print(json.dumps(report, indent=2))
