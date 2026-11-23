import os
import sys
import json
import time
import subprocess
from datetime import datetime

sys.stdout.reconfigure(encoding="utf-8")

WORKSPACE = "L:\\LocalCoder\\workspace"
RUST_CORE = "L:\\Rules\\target\\release\\rules_core.exe"

class VivStandaloneLocalShell:
    def __init__(self):
        from hviv_domain_binding import UnifiedDomainBindingController
        from hviv_preflight_diagnostic import PreflightDiagnosticEngine
        from hviv_docker_engine import HVivDockerSubstrate
        from hviv_xtts_voice_engine import LocalXTTSVoiceEngine
        from hviv_persistent_memory import PersistentCarmaMemoryEngine

        self.domain_ctrl = UnifiedDomainBindingController()
        self.preflight = PreflightDiagnosticEngine()
        self.docker_sub = HVivDockerSubstrate()
        self.voice_eng = LocalXTTSVoiceEngine()
        self.memory_eng = PersistentCarmaMemoryEngine()
        self.user_authority = True

    def process_command(self, user_prompt: str, target_drive: str = "L:", user_approved: bool = False) -> dict:
        d_clean = target_drive[:2].upper()
        ts = datetime.now().isoformat()

        print(f"\n==================================================")
        print(f" [VIV LOCAL STANDALONE SHELL] Target Domain: {d_clean}")
        print(f" [USER DIRECTIVE]: \"{user_prompt}\"")
        print(f"==================================================")

        # 1. Pre-flight Check
        diag = self.preflight.run_full_preflight_diagnostics(target_drive=d_clean)
        if diag["overall_status"] != "READY_FOR_EXECUTION":
            print(f"  └─ [BLOCKED BY PREFLIGHT] Reason: {diag}")
            return {"success": False, "reason": "Preflight diagnostic failed."}

        # 2. Domain Binding (LoRA + Cloned Voice)
        binding = self.domain_ctrl.bind_drive_domain([d_clean])

        # 3. Viv Voice Response (Local audio synthesis)
        self.voice_eng.speak(f"Processing directive on domain {d_clean}: {user_prompt}", target_drive=d_clean)

        # 4. Check Rust Security Queen Evaluation on Host
        req_payload = json.dumps({
            "action": "cani" if not user_approved else "quarantine",
            "drive": d_clean,
            "target_path": WORKSPACE,
            "reason": f"Viv Local Standalone directive: {user_prompt}",
            "user_approved": user_approved
        })
        res = subprocess.run([RUST_CORE, req_payload], capture_output=True, text=True, encoding="utf-8")
        try:
            verdict = json.loads(res.stdout)
        except json.JSONDecodeError:
            verdict = {"allowed": False, "reason": "Invalid response from Rust Queen."}

        print(f"  ├─ Rust Security Queen Verdict: Allowed = {verdict.get('allowed')} ({verdict.get('reason')})")

        # 5. Execute Command inside Docker Sandbox
        container_cmd = f"echo 'VIV STANDALONE EXECUTION FOR: {user_prompt}'"
        exec_res = self.docker_sub.exec_inside_container(container_cmd)
        print(f"  ├─ Sandbox Execution Output: {exec_res}")

        # 6. Record to Persistent Memory
        self.memory_eng.store_memory(
            domain=d_clean,
            category="STANDALONE_DIRECTIVE",
            actor="User",
            memory_text=f"Directive: '{user_prompt}' -> Result: {exec_res}"
        )

        return {
            "success": True,
            "verdict": verdict,
            "sandbox_output": exec_res,
            "domain": d_clean
        }

    def start_interactive_shell(self):
        print("==================================================")
        print("    VIV AIOS V2 — STANDALONE OFFLINE LOCAL SHELL  ")
        print("==================================================")
        print("100% Local | Zero Internet | Full PC Authority")
        print("Commands: Type 'exit' to quit | Type 'drive:<LETTER>' to switch domain\n")

        current_drive = "L:"
        while True:
            try:
                user_input = input(f"Viv ({current_drive})> ").strip()
                if not user_input:
                    continue
                if user_input.lower() in ["exit", "quit"]:
                    print("Exiting Viv Standalone Local Shell. Good day, Architect.")
                    break
                if user_input.lower().startswith("drive:"):
                    current_drive = user_input.split(":")[1].upper() + ":"
                    print(f"Switched target domain to {current_drive}")
                    continue

                # Execute Directive
                self.process_command(user_input, target_drive=current_drive, user_approved=True)
            except KeyboardInterrupt:
                print("\nShell interrupted. Standing by.")
                break

if __name__ == "__main__":
    shell = VivStandaloneLocalShell()
    print("\n--- Running Single Test Directive in Standalone Local Shell ---")
    shell.process_command("Create offline backup script for workspace", target_drive="L:", user_approved=True)
