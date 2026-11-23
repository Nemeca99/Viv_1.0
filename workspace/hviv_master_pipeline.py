import os
import sys
import time
import json
import subprocess
from datetime import datetime

sys.stdout.reconfigure(encoding="utf-8")

WORKSPACE = "L:\\LocalCoder\\workspace"
RUST_CORE = "L:\\Rules\\target\\release\\rules_core.exe"

class MasterPipelineOrchestrator:
    def __init__(self):
        from hviv_domain_binding import UnifiedDomainBindingController
        from hviv_preflight_diagnostic import PreflightDiagnosticEngine
        from hviv_docker_engine import HVivDockerSubstrate
        from hviv_xtts_voice_engine import LocalXTTSVoiceEngine
        from hviv_persistent_memory import PersistentCarmaMemoryEngine
        from hviv_continuous_builder import ContinuousSelfBuildingEngine
        from hviv_adapter_compiler import QLoRAAdapterCompiler

        self.domain_ctrl = UnifiedDomainBindingController()
        self.preflight = PreflightDiagnosticEngine()
        self.docker_sub = HVivDockerSubstrate()
        self.voice_eng = LocalXTTSVoiceEngine()
        self.memory_eng = PersistentCarmaMemoryEngine()
        self.builder_eng = ContinuousSelfBuildingEngine()
        self.compiler = QLoRAAdapterCompiler()
        self.cycle_count = 0

    def run_master_pipeline_step(self, step_id: int):
        self.cycle_count = step_id
        drives = ["L:", "C:", "D:", "E:", "F:"]
        drive = drives[(step_id - 1) % len(drives)]
        ts = datetime.now().isoformat()

        print(f"\n[{ts}] [MASTER PIPELINE STEP {step_id}] Domain Target: {drive}")

        # 1. Pre-flight Self-Assessment
        diag = self.preflight.run_full_preflight_diagnostics(target_drive=drive)
        print(f"  ├─ Pre-flight Diagnostic: {diag['overall_status']}")

        # 2. Domain 1-to-1 Binding (LoRA + Viv Cloned Voice)
        binding = self.domain_ctrl.bind_drive_domain([drive])

        # 3. Viv Cloned Voice Telemetry
        self.voice_eng.speak(f"Master pipeline executing step {step_id} on domain {drive}.", target_drive=drive)

        # 4. Self-Building Cycle in Docker Sandbox
        self.builder_eng.build_and_learn_cycle(step_id)

        # 5. Anchor Trajectory to Persistent Carma SQLite Memory
        self.memory_eng.store_memory(
            domain=drive,
            category="MASTER_PIPELINE_STEP",
            actor="Viv",
            memory_text=f"Master Step {step_id} self-built & harvested into dataset on domain {drive}."
        )

        # 6. Re-compile QLoRA Dataset & Adapter Manifests
        manifest = self.compiler.compile_adapter_manifest()
        print(f"  └─ Total Harvested Dataset Trajectories: {manifest['total_trajectories']:,}")

if __name__ == "__main__":
    orchestrator = MasterPipelineOrchestrator()
    print("==================================================")
    print("  HViv AIOS V2 — MASTER PIPELINE ORCHESTRATOR    ")
    print("==================================================")
    
    # Run continuous pipeline steps
    for i in range(1, 4):
        orchestrator.run_master_pipeline_step(i)
        time.sleep(1.0)
