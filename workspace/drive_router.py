import os
import sys
import json
import subprocess

sys.stdout.reconfigure(encoding="utf-8")

SCHEMA_PATH = "L:\\LocalCoder\\workspace\\drive_schemas.json"
RUST_CORE = "L:\\Rules\\target\\release\\rules_core.exe"

class MultiDomainFusionRouter:
    def __init__(self):
        with open(SCHEMA_PATH, "r", encoding="utf-8") as f:
            self.schemas = json.load(f)

    def fuse_domains(self, target_drives: list) -> dict:
        """
        Dynamically merges LoRA adapters and tool schemas for only the target drives requested.
        """
        fused_tools = set()
        fused_loras = []
        fused_roles = []
        fused_denied = set()

        for drive in target_drives:
            d_clean = drive[:2].upper()
            if d_clean not in self.schemas:
                raise ValueError(f"Unknown drive domain: '{d_clean}'")
            
            domain = self.schemas[d_clean]
            fused_tools.update(domain["allowed_tools"])
            fused_denied.update(domain["denied_operations"])
            fused_loras.append(domain["lora_adapter"])
            fused_roles.append(f"{d_clean} ({domain['role']})")

        return {
            "active_drives": [d[:2].upper() for d in target_drives],
            "fused_roles": fused_roles,
            "fused_loras": fused_loras,
            "fused_allowed_tools": sorted(list(fused_tools)),
            "fused_denied_operations": sorted(list(fused_denied)),
        }

    def validate_fused_action(self, target_path: str, tool_name: str, active_drives: list, user_approved: bool = False) -> dict:
        fused_context = self.fuse_domains(active_drives)
        target_drive = target_path[:2].upper()

        # 1. Ensure target drive is in active fused context
        if target_drive not in fused_context["active_drives"]:
            return {
                "allowed": False,
                "verdict": "NO",
                "reason": f"Target drive '{target_drive}' is NOT loaded in current active fused context {fused_context['active_drives']}."
            }

        # 2. Check Fused Tool Schema
        if tool_name not in fused_context["fused_allowed_tools"]:
            return {
                "allowed": False,
                "verdict": "NO",
                "reason": f"Tool '{tool_name}' is NOT in fused allowed schema for {fused_context['active_drives']}."
            }

        # 3. Check Host Rust Security Queen
        req_payload = json.dumps({
            "action": "cani",
            "drive": target_drive,
            "target_path": target_path,
            "reason": f"Fused domain execution: {tool_name}",
            "user_approved": user_approved
        })
        res = subprocess.run([RUST_CORE, req_payload], capture_output=True, text=True, encoding="utf-8")
        try:
            rust_resp = json.loads(res.stdout)
            rust_resp["fused_context"] = fused_context
            return rust_resp
        except json.JSONDecodeError:
            return {"allowed": False, "verdict": "NO", "reason": "Invalid response from Rust Queen."}

if __name__ == "__main__":
    print("=== Testing Dynamic Multi-Drive Domain Fusion Router ===")
    router = MultiDomainFusionRouter()

    # Scenario 1: Access C: and L: only
    fused_cl = router.fuse_domains(["C:", "L:"])
    print(f"\nScenario 1: Fused Drives -> {fused_cl['active_drives']}")
    print(f"  ├─ Fused Roles: {fused_cl['fused_roles']}")
    print(f"  ├─ Fused LoRAs: {fused_cl['fused_loras']}")
    print(f"  └─ Fused Tools: {fused_cl['fused_allowed_tools']}")

    # Scenario 2: Access C:, L:, AND D: (Appending D:)
    fused_cld = router.fuse_domains(["C:", "L:", "D:"])
    print(f"\nScenario 2: Fused Drives (Appended D:) -> {fused_cld['active_drives']}")
    print(f"  ├─ Fused Roles: {fused_cld['fused_roles']}")
    print(f"  └─ Fused Tools: {fused_cld['fused_allowed_tools']}")

    # Scenario 3: Attempting tool on un-fused E: Drive
    test_eval = router.validate_fused_action("E:\\_sweep_quarantine\\manifest.jsonl", "quarantine_list_manifest", active_drives=["C:", "L:"])
    print(f"\nScenario 3 (Attempt E: access with C:+L: fused context):")
    print(f"  └─ Allowed: {test_eval['allowed']} | Reason: {test_eval['reason']}")
