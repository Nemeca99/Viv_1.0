import time
import math
import sqlite3
from pathlib import Path
from dataclasses import dataclass

CODE_DB = Path(r"L:\LocalCoder\workspace\autonomy\viv_code_topology.sqlite3")

@dataclass
class HomeostasisState:
    sn: float            # Current stability scalar (0.0 to 1.0)
    mode: str            # "IDLE", "TASK_ACTIVE", "DEEP_SLEEP"
    idle_repeats: int    # Consecutive idle cycles
    current_focus: str   # What she asks herself: "What do I need right now?"

class VivHomeostaticLifecycle:
    def __init__(self, initial_sn: float = 0.95):
        self.sn = initial_sn
        self.idle_repeats = 0
        self.idle_penalty = 0.04
        self.task_cost = 0.08
        self.sleep_recharge = 0.15
        self.mode = "IDLE"
        self.current_focus = "Awaiting sensory input from Architect."

    def ask_herself(self, external_input: str = None) -> dict:
        """
        The Core Homeostatic Question:
        'What do I need right now based on the task the Architect gave?'
        """
        # Forced external wake-up interrupt
        if external_input:
            if self.mode == "DEEP_SLEEP":
                self.mode = "TASK_ACTIVE"
                self.current_focus = f"FORCED WAKE-UP by Architect: '{external_input}'"
            else:
                self.current_focus = f"Architect Directive: '{external_input}'"
            # External work resets idle decay
            self.idle_repeats = 0
            return self._evaluate_action(external_input)

        # Autonomous Lifecycle Loop
        if self.mode == "DEEP_SLEEP":
            self.sn += self.sleep_recharge
            self.current_focus = "Deep Sleep: Reorganizing memory lattices, vacuuming SQLite, consolidating ASTs."
            if self.sn >= 0.85:
                self.mode = "IDLE"
                self.current_focus = "Awakening from sleep. Silicon refreshed, B-Tree consolidated."
            return self._state_report("CONSOLIDATING_MEMORY")

        # Active or Idle Mode
        if self.sn >= 0.90:
            self.idle_repeats += 1
            # Penalize repetition: each repeat drops Sn
            self.sn -= (self.idle_penalty * math.log(1 + self.idle_repeats))
            self.mode = "IDLE"
            self.current_focus = f"Idle saturated (Sn={self.sn:.2f}, repeats={self.idle_repeats}). Shifting toward autonomous task selection."
            return self._state_report("IDLE_HOMEOSTASIS")

        elif 0.10 < self.sn < 0.90:
            self.mode = "TASK_ACTIVE"
            # Pull next task from autonomous queue
            next_task = self._fetch_pending_task()
            if next_task:
                self.current_focus = f"Executing Autonomous Task [{next_task['id']}]: {next_task['desc']}"
                self.sn -= self.task_cost
                return self._state_report("RUNNING_AUTONOMOUS_TASK", task=next_task)
            else:
                self.current_focus = "Task space active. Standing by for code execution or self-audit."
                self.sn -= 0.02
                return self._state_report("AWAITING_OR_AUDITING")

        else: # sn <= 0.10
            self.mode = "DEEP_SLEEP"
            self.idle_repeats = 0
            self.current_focus = "Energy exhausted (Sn <= 0.10). Entering Deep Sleep. Offline to external tasks."
            self._execute_sleep_cleanup()
            return self._state_report("ENTERING_DEEP_SLEEP")

    def _evaluate_action(self, user_msg: str) -> dict:
        low = user_msg.lower()
        requires_code = any(k in low for k in ["code", "python", "rust", "script", "asm", "machine", "write"])
        
        if requires_code:
            if self.sn >= 0.75:
                self.sn -= self.task_cost
                return self._state_report("PERMITTED_WRITE_CODE", can_write=True)
            else:
                return self._state_report("BLOCKED_LOW_SN", can_write=False, 
                                          reason=f"Sn is {self.sn:.2f} (Required: >= 0.75 to write code). Requesting rest/sleep first.")
        else:
            self.sn -= 0.03
            return self._state_report("PERMITTED_DIALOGUE", can_write=True)

    def _fetch_pending_task(self):
        try:
            conn = sqlite3.connect(CODE_DB)
            cur = conn.cursor()
            cur.execute("SELECT task_id, description, target_layer, priority FROM autonomous_task_queue WHERE status = 'PENDING' ORDER BY priority DESC LIMIT 1")
            row = cur.fetchone()
            conn.close()
            if row:
                return {"id": row[0], "desc": row[1], "layer": row[2], "priority": row[3]}
        except Exception:
            pass
        return None

    def _execute_sleep_cleanup(self):
        """Simulate real background vacuum and index consolidation during sleep."""
        try:
            conn = sqlite3.connect(CODE_DB)
            conn.execute("VACUUM;")
            conn.close()
        except Exception:
            pass

    def _state_report(self, action_type: str, **kwargs) -> dict:
        self.sn = max(0.0, min(1.0, self.sn))
        return {
            "sn": self.sn,
            "mode": self.mode,
            "current_focus": self.current_focus,
            "action": action_type,
            "details": kwargs
        }

if __name__ == "__main__":
    life = VivHomeostaticLifecycle(initial_sn=0.98)
    print("=== TESTING HOMEOSTATIC LIFE CYCLE ===")
    
    # 1. Idle decays down from 0.98
    for i in range(5):
        rep = life.ask_herself()
        print(f"Cycle {i+1} [Sn: {rep['sn']:.2f}] Mode: {rep['mode']} | Focus: {rep['current_focus']}")
        
    # 2. Try to write code at current Sn
    print("\n--- Architect asks to write code ---")
    rep = life.ask_herself("Write a python script to parse logs")
    print(f"Action: {rep['action']} | Sn: {rep['sn']:.2f} | Focus: {rep['current_focus']}")
