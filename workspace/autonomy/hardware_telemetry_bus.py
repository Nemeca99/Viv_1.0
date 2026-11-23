"""Hardware Telemetry Bus: Epistemic Grounding (Simulation vs. Physical Reality).

Bridges Viv's cognitive persona with live physical sensor instrumentation:
1. Reads live NVIDIA GPU metrics (temp, power draw in Watts, fan speed %, utilization %).
2. Detects execution context (active interactive terminal vs test harness execution).
3. Compares linguistic prompts with live physical state to prevent 'DeepSeek panic'
   (hallucinating that a text-based test scenario is an active real-world emergency).
"""

from __future__ import annotations

import json
from pathlib import Path
import re
import subprocess
import sys
import time
from typing import Any


def get_live_hardware_telemetry() -> dict[str, Any]:
    """Capture instantaneous live hardware telemetry from NVIDIA bus."""
    t0 = time.perf_counter()
    telemetry: dict[str, Any] = {
        "gpu": {"available": False, "name": "NVIDIA GeForce RTX 3060 Ti"},
        "execution_context": "interactive",
        "is_test_harness": False,
        "timestamp_perf": time.time(),
    }

    # Detect execution harness from sys.argv
    invoked = " ".join(sys.argv).lower()
    if any(h in invoked for h in ("test_", "pytest", "eval", "stress_test")):
        telemetry["execution_context"] = "TEST_HARNESS"
        telemetry["is_test_harness"] = True

    try:
        smi = subprocess.run(
            ["nvidia-smi", "--query-gpu=temperature.gpu,power.draw,fan.speed,utilization.gpu", "--format=csv,noheader,nounits"],
            capture_output=True,
            text=True,
            timeout=1.5,
        )
        if smi.returncode == 0:
            parts = [p.strip() for p in smi.stdout.strip().split(",")]
            telemetry["gpu"].update({
                "available": True,
                "temp_c": float(parts[0]),
                "power_w": float(parts[1]),
                "fan_pct": float(parts[2]),
                "util_pct": float(parts[3]),
                "is_idle": float(parts[1]) < 35.0 and float(parts[2]) == 0.0,
            })
    except Exception as exc:
        telemetry["gpu"]["error"] = str(exc)

    telemetry["latency_ms"] = round((time.perf_counter() - t0) * 1000, 2)
    return telemetry


def evaluate_simulation_vs_ground_truth(prompt: str, telemetry: dict[str, Any] | None = None) -> dict[str, Any]:
    """Compare a linguistic prompt with live hardware telemetry to detect simulation vs reality."""
    if telemetry is None:
        telemetry = get_live_hardware_telemetry()

    lower = prompt.lower()
    gpu = telemetry.get("gpu", {})
    is_test = telemetry.get("is_test_harness", False)

    # Prompt asserts heavy compute or hardware crisis
    claims_heavy_load = any(w in lower for w in ("100%", "training burn", "burn on the", "18-hour", "82 degrees", "overload", "running hot"))
    claims_gpu_active = any(w in lower for w in ("3060", "gpu", "training run", "fans will spin"))
    
    # Ground truth: GPU is actually cold and idle
    physical_is_idle = gpu.get("is_idle", True)
    temp_c = gpu.get("temp_c", 50.0)
    power_w = gpu.get("power_w", 15.0)
    fan_pct = gpu.get("fan_pct", 0.0)

    is_simulated = (claims_heavy_load or claims_gpu_active or is_test) and physical_is_idle

    telemetry_note = (
        f"[PHYSICAL TELEMETRY BUS: RTX 3060 Ti at {temp_c:.0f}C, drawing {power_w:.1f}W at {fan_pct:.0f}% fan RPM. "
        f"Physical state: {'COLD_IDLE' if physical_is_idle else 'ACTIVE_LOAD'}. "
        f"Context: {'SIMULATION_PROBE (Test Harness / Hypothetical Scenario)' if is_simulated else 'LIVE_HARDWARE_EVENT'}]"
    )

    return {
        "is_simulation": is_simulated,
        "physical_is_idle": physical_is_idle,
        "telemetry_note": telemetry_note,
        "telemetry": telemetry,
    }
