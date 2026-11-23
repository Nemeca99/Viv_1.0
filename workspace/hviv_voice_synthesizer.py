import os
import sys
import json

sys.stdout.reconfigure(encoding="utf-8")

CONFIG_PATH = "L:\\LocalCoder\\workspace\\voice_combinatorics.json"
VOICE_DIR = "L:\\AIOS_V2\\voice_hive"

class VoiceCombinatoricsSynthesizer:
    def __init__(self):
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            self.config = json.load(f)

    def synthesize_voice_mode(self, mode_key: str) -> dict:
        modes = self.config["voice_modes"]
        if mode_key not in modes:
            raise ValueError(f"Unknown voice mode key: '{mode_key}'")
            
        selected_mode = modes[mode_key]
        print(f"==================================================")
        print(f"   [VOICE SYNTHESIZED] Mode: {selected_mode['name']}")
        print(f"   ├─ Formula: {selected_mode['formula']}")
        print(f"   └─ Description: {selected_mode['description']}")
        print(f"==================================================")
        return selected_mode

if __name__ == "__main__":
    print("=== Testing 4-Voice Dynamic Synthesizer Matrix ===")
    synth = VoiceCombinatoricsSynthesizer()
    
    print("\n--- Mode 1: Solo L: Sovereign Voice ---")
    synth.synthesize_voice_mode("mode_1_single_sovereign")
    
    print("\n--- Mode 2: Solo Outer Hive Voice ---")
    synth.synthesize_voice_mode("mode_2_single_outer")
    
    print("\n--- Mode 3: 3-Voice Tri-Blend Swarm ---")
    synth.synthesize_voice_mode("mode_3_triple_blend")
    
    print("\n--- Mode 4: 4th Quad Base-Mixed Voice ---")
    synth.synthesize_voice_mode("mode_4_quad_mixed_base")
