import os
import sys
import json

sys.stdout.reconfigure(encoding="utf-8")

CONFIG_PATH = "L:\\LocalCoder\\workspace\\voice_hive_config.json"
VOICE_HIVE_DIR = "L:\\AIOS_V2\\voice_hive"

# Ensure voice hive directory exists
os.makedirs(VOICE_HIVE_DIR, exist_ok=True)

class VoiceHiveRouter:
    def __init__(self):
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            self.config = json.load(f)

    def select_voice_profile(self, target_drive: str) -> dict:
        d_clean = target_drive[:2].upper()
        profiles = self.config["voice_profiles"]
        
        if d_clean == "L:":
            selected = profiles["l_drive_sovereign_voice"]
            selected["domain"] = "L: Sovereign Core"
        else:
            selected = profiles["outer_drive_hive_voice"]
            selected["domain"] = f"{d_clean} Outer Drive Domain"
            
        print(f"[VOICE ROUTED] Domain: {selected['domain']} -> Voice Profile: '{selected['profile_name']}'")
        print(f"  ├─ Target Voice Sample: {selected['target_file']}")
        print(f"  └─ Pacing & Characteristics: {selected['pacing']}")
        
        return selected

if __name__ == "__main__":
    print("==================================================")
    print("     HViv Dual Voice Hive Domain Router          ")
    print("==================================================")
    
    router = VoiceHiveRouter()
    
    print("\n1. Testing Voice Selection for L: Drive:")
    voice_l = router.select_voice_profile("L:")
    
    print("\n2. Testing Voice Selection for Outer Drive (D: Proving Ground):")
    voice_d = router.select_voice_profile("D:")
    
    print("\n3. Testing Voice Selection for Outer Drive (C: OS Drive):")
    voice_c = router.select_voice_profile("C:")
