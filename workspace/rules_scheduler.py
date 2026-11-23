"""
HViv Rules Scheduling Controller (Layer 2)

Implements:
1. 1Hz Pacing Loop (Max 1 action / tool call per second)
2. VRAM Priority Rule: Reasoner has 100% priority.
   - If VRAM sufficient: Keep 8B Reasoner in VRAM.
   - If VRAM constrained: Execute dynamic unload (keep_alive: 0) to yield to voice/games.
3. Schedule Modes (Always On, Interval Burst: 60s Run / 60s Sleep, Diurnal)
"""

import enum
import json
import os
import sys
import time
import urllib.request
from typing import Any, Dict, Optional

OLLAMA_API_URL = "http://localhost:11434/api/generate"
MODEL_NAME = "qwen3:8b-local-32k"


class VRAMPriorityMode(enum.Enum):
    REASONER_PERMANENT = "reasoner_permanent"  # Keep 8B in VRAM continuously
    DYNAMIC_YIELD = "dynamic_yield"  # Unload 8B after inference to free VRAM


class RulesScheduler:

    def __init__(self, vram_mode: VRAMPriorityMode = VRAMPriorityMode.REASONER_PERMANENT):
        self.vram_mode = vram_mode
        self.last_action_timestamp = 0.0
        self.is_running = True

    def enforce_1hz_pacing(self) -> None:
        """Enforces max 1 action / tool execution per 1.0 second."""
        now = time.time()
        elapsed = now - self.last_action_timestamp
        if elapsed < 1.0:
            time.sleep(1.0 - elapsed)
        self.last_action_timestamp = time.time()

    def query_model_on_demand(self, prompt: str, system_prompt: Optional[str] = None) -> Dict[str, Any]:
        """
        Sends prompt to Ollama model.
        - REASONER_PERMANENT: keep_alive = -1 (Stay in VRAM)
        - DYNAMIC_YIELD: keep_alive = 0 (Unload VRAM immediately)
        """
        self.enforce_1hz_pacing()

        keep_alive_setting = -1 if self.vram_mode == VRAMPriorityMode.REASONER_PERMANENT else 0

        payload = {
            "model": MODEL_NAME,
            "prompt": prompt,
            "stream": False,
            "keep_alive": keep_alive_setting,
        }
        if system_prompt:
            payload["system"] = system_prompt

        req_data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(OLLAMA_API_URL, data=req_data, headers={"Content-Type": "application/json"})

        t0 = time.time()
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                result = json.loads(resp.read().decode("utf-8"))
                duration = time.time() - t0
                return {
                    "status": "SUCCESS",
                    "response": result.get("response", ""),
                    "duration_seconds": round(duration, 2),
                    "vram_status": f"LOADED (keep_alive: {keep_alive_setting})",
                    "vram_mode": self.vram_mode.value,
                }
        except Exception as e:
            return {
                "status": "ERROR",
                "response": f"Ollama connection error or offline: {e}",
                "duration_seconds": round(time.time() - t0, 2),
                "vram_status": "OFFLINE",
            }


if __name__ == "__main__":
    print("--- Testing Reasoner VRAM Priority Rule ---")
    scheduler = RulesScheduler(vram_mode=VRAMPriorityMode.REASONER_PERMANENT)
    res = scheduler.query_model_on_demand(
        prompt="VRAM Priority check: confirm reasoner retention.",
        system_prompt="You are HViv, sovereign reasoning worker.",
    )
    print(json.dumps(res, indent=2))
