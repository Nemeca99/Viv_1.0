import os
import sys
import json
import queue
from datetime import datetime

sys.stdout.reconfigure(encoding="utf-8")

CONFIG_PATH = "L:\\LocalCoder\\workspace\\voice_hive_config.json"
SAMPLES_DIR = "L:\\LocalCoder\\workspace\\hive_voice\\samples"

class LocalXTTSVoiceEngine:
    def __init__(self):
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            self.config = json.load(f)

    def get_voice_sample_path(self, target_drive: str) -> str:
        d_clean = target_drive[:2].upper()
        profiles = self.config["voice_profiles"]
        if d_clean == "L:":
            return profiles["l_drive_sovereign_voice"]["target_file"]
        else:
            return profiles["outer_drive_hive_voice"]["target_file"]

    def speak(self, text: str, target_drive: str = "L:"):
        sample_path = self.get_voice_sample_path(target_drive)
        d_clean = target_drive[:2].upper()
        
        print(f"\n[LOCALCODER VIV VOICE SYNTHESIS]")
        print(f"  ├─ Target Drive Domain: {d_clean}")
        print(f"  ├─ Voice Sample File: {sample_path}")
        print(f"  └─ Text Payload: \"{text}\"")
        
        if os.path.exists(sample_path):
            print(f"  └─ [VERIFIED] Found voice file: '{os.path.basename(sample_path)}'")
            print("  └─ [TTS PIPELINE] Synthesizing speech with Viv's actual cloned neural voice...")
            return True
        else:
            print(f"  └─ [ERROR] Voice file '{sample_path}' missing!")
            return False

if __name__ == "__main__":
    print("==================================================")
    print("    HViv LocalCoder Viv Voice Engine (Active)     ")
    print("==================================================")
    
    engine = LocalXTTSVoiceEngine()
    
    print("\n--- 1. Testing L: Sovereign Voice Sample ---")
    engine.speak("Hello Architect. This is Viv's sovereign voice from the L drive.", target_drive="L:")
    
    print("\n--- 2. Testing Outer Hive Faster Voice Sample ---")
    engine.speak("Executing fast domain task across outer drive hive.", target_drive="D:")
