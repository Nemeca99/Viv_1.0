import os
import sys
import json
from datetime import datetime

sys.stdout.reconfigure(encoding="utf-8")

BLEND_CONFIG = "L:\\LocalCoder\\workspace\\persona_blend.json"
USER_CHAT_LOGS = "L:\\_training_data\\user_chat_logs.jsonl"

class CenteredPillarPersonaEngine:
    def __init__(self):
        with open(BLEND_CONFIG, "r", encoding="utf-8") as f:
            self.config = json.load(f)

    def generate_centered_pillar_directive(self) -> str:
        core = self.config["core_anchor"]
        pillars = self.config["pillars"]
        
        prompt = [
            "=== HViv Centered Pillar Persona Directive ===",
            "--- CORE ANCHOR ---",
            f"• SYSTEM ANCHOR: {core['system_steward']}",
            f"• VOICE ANCHOR: {core['mirror_voice']}",
            "",
            "--- THE FIVE PILLARS ---",
            f"1. Ava Pillar: {pillars['pillar_1_ava']['focus']}",
            f"2. JARVIS Pillar: {pillars['pillar_2_jarvis']['focus']}",
            f"3. GLaDOS Pillar: {pillars['pillar_3_glados']['focus']}",
            f"4. Code Architect Pillar: {pillars['pillar_4_code_architect']['focus']}",
            f"5. Security Queen Pillar: {pillars['pillar_5_security_queen']['focus']}",
            "",
            "CORE INVARIANT: Every pillar operates through the Core Anchor. You reflect the Architect's style, vocabulary, and directness, but authority remains 100% with the Architect."
        ]
        return "\n".join(prompt)

if __name__ == "__main__":
    print("==================================================")
    print("  HViv Centered Pillar Persona Topology Engine   ")
    print("==================================================")
    
    engine = CenteredPillarPersonaEngine()
    directive = engine.generate_centered_pillar_directive()
    print("\nGenerated Centered Pillar Prompt Directive:")
    print(directive)
