import os
import sys
import json

sys.stdout.reconfigure(encoding="utf-8")

BINDING_CONFIG = "L:\\LocalCoder\\workspace\\domain_bindings.json"

class UnifiedDomainBindingController:
    def __init__(self):
        with open(BINDING_CONFIG, "r", encoding="utf-8") as f:
            self.bindings = json.load(f)["domain_bindings"]

    def bind_drive_domain(self, target_drives: list) -> dict:
        """
        Ensures exact 1-to-1 matching between loaded LoRA adapters and loaded Voice Profiles.
        """
        active_loras = []
        active_voices = []
        active_modes = []

        print("==================================================")
        print("    Unified LoRA + Voice 1-to-1 Domain Binding    ")
        print("==================================================")

        for drive in target_drives:
            d_clean = drive[:2].upper()
            if d_clean not in self.bindings:
                raise ValueError(f"Unknown drive domain: '{d_clean}'")
            
            b = self.bindings[d_clean]
            active_loras.append(b["lora_adapter"])
            active_voices.append(b["voice_profile"])
            active_modes.append(b["voice_mode"])
            
            print(f"[{d_clean} Domain Locked]")
            print(f"  ├─ LoRA Adapter: {b['lora_adapter']}")
            print(f"  ├─ Voice Profile: {b['voice_profile']}")
            print(f"  └─ Voice Mode: {b['voice_mode']} ({b['pacing']})")

        return {
            "active_drives": [d[:2].upper() for d in target_drives],
            "bound_loras": active_loras,
            "bound_voices": active_voices,
            "bound_modes": active_modes,
            "matched_1_to_1": len(active_loras) == len(active_voices)
        }

if __name__ == "__main__":
    controller = UnifiedDomainBindingController()
    
    print("\n--- Test A: Binding L: Sovereign Domain ---")
    controller.bind_drive_domain(["L:"])
    
    print("\n--- Test B: Binding Fused Domains (C: + L: + D:) ---")
    controller.bind_drive_domain(["C:", "L:", "D:"])
