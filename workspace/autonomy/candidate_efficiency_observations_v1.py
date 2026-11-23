"""Raw efficiency observations for isolated candidate code evaluation.

No aggregate reward is computed here. Metrics retain their source and units so
the Architect's neuron-efficiency reduction can be applied without conflating
measured values with proxies.
"""
from __future__ import annotations

from collections import Counter
from contextlib import contextmanager
import json
import math
import subprocess
import sys
import threading
import time
from typing import Iterator


class GpuPowerSampler:
    """Sample NVIDIA board power with NVML and integrate samples over time."""

    def __init__(self, interval_seconds: float = 0.2) -> None:
        self.interval_seconds = interval_seconds
        self.samples: list[tuple[float, float, float | None, float | None]] = []
        self.error: str | None = None
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._handle = None
        self._nvml = None

    def _read(self) -> None:
        now = time.perf_counter()
        try:
            power_w = self._nvml.nvmlDeviceGetPowerUsage(self._handle) / 1000.0
            util = float(self._nvml.nvmlDeviceGetUtilizationRates(self._handle).gpu)
            temp = float(self._nvml.nvmlDeviceGetTemperature(
                self._handle, self._nvml.NVML_TEMPERATURE_GPU))
            self.samples.append((now, power_w, util, temp))
        except Exception as exc:  # telemetry is observational, never a gate
            self.error = f"NVML_SAMPLE_ERROR:{type(exc).__name__}:{exc}"

    def _run(self) -> None:
        while not self._stop.is_set():
            self._read()
            self._stop.wait(self.interval_seconds)
        self._read()

    def __enter__(self) -> "GpuPowerSampler":
        try:
            import pynvml
            self._nvml = pynvml
            pynvml.nvmlInit()
            self._handle = pynvml.nvmlDeviceGetHandleByIndex(0)
            self._read()
            self._thread = threading.Thread(target=self._run, daemon=True)
            self._thread.start()
        except Exception as exc:
            self.error = f"NVML_UNAVAILABLE:{type(exc).__name__}:{exc}"
        return self

    def __exit__(self, *_: object) -> None:
        if self._thread:
            self._stop.set()
            self._thread.join(timeout=2)
        if self._nvml:
            try:
                self._nvml.nvmlShutdown()
            except Exception:
                pass

    def report(self) -> dict:
        rows = sorted(self.samples)
        if not rows:
            return {"state": "UNAVAILABLE", "source": "NVML_GPU_BOARD_SENSOR",
                    "scope": "whole GPU board; not attributable to one process",
                    "error": self.error}
        energy = 0.0
        for left, right in zip(rows, rows[1:]):
            dt = max(0.0, right[0] - left[0])
            energy += (left[1] + right[1]) * 0.5 * dt
        powers = [row[1] for row in rows]
        utils = [row[2] for row in rows if row[2] is not None]
        temps = [row[3] for row in rows if row[3] is not None]
        duration = max(0.0, rows[-1][0] - rows[0][0])
        return {
            "state": "MEASURED" if len(rows) >= 2 else "SINGLE_SAMPLE",
            "source": "NVML_GPU_BOARD_SENSOR",
            "scope": "whole GPU board; not attributable to one process",
            "sample_count": len(rows), "sample_interval_seconds": self.interval_seconds,
            "duration_seconds": duration,
            "power_w_mean": sum(powers) / len(powers),
            "power_w_min": min(powers), "power_w_max": max(powers),
            "energy_joules_trapezoid": energy if len(rows) >= 2 else None,
            "gpu_utilization_percent_mean": sum(utils) / len(utils) if utils else None,
            "temperature_c_mean": sum(temps) / len(temps) if temps else None,
            "error": self.error,
        }


def output_entropy_proxy(text: str) -> dict:
    """Empirical character Shannon entropy; explicitly not model token entropy."""
    if not text:
        return {"value": 0.0, "unit": "bits_per_character", "source": "UTF8_CHARACTER_FREQUENCIES",
                "is_proxy": True, "character_count": 0}
    counts = Counter(text)
    total = len(text)
    entropy = -sum((n / total) * math.log2(n / total) for n in counts.values())
    return {"value": entropy, "unit": "bits_per_character",
            "source": "UTF8_CHARACTER_FREQUENCIES", "is_proxy": True,
            "character_count": total}


@contextmanager
def measure_completion() -> Iterator[dict]:
    """Measure proposal wall time and GPU board telemetry around one completion."""
    observation: dict = {"state": "MEASURING"}
    start_wall = time.perf_counter()
    start_cpu = time.process_time()
    with GpuPowerSampler() as sampler:
        try:
            yield observation
        finally:
            observation.update({
                "wall_seconds": time.perf_counter() - start_wall,
                "process_cpu_seconds": time.process_time() - start_cpu,
                "gpu": sampler.report(),
            })


def profile_python_execution(code: str, tests: str, function_names: list[str]) -> tuple[bool, dict, str]:
    """Run candidate and tests in the existing isolated Python Docker gate.

    Dynamic steps are executed source-line events in the requested function
    and composed helpers. This Python build does not emit opcode trace events,
    so line events are reported explicitly instead of being mislabeled. The
    original deterministic tests remain the acceptance authority.
    """
    script = r'''import json, sys, time
source = __SOURCE__
tests = __TESTS__
names = set(__NAMES__)
namespace = {}
exec(compile(source, "<candidate>", "exec"), namespace)
code_objects = {getattr(namespace.get(name), "__code__", None) for name in names}
code_objects.discard(None)
counts = {"executed_source_lines": 0, "calls": 0}
def tracer(frame, event, arg):
    if event == "call" and frame.f_code in code_objects:
        counts["calls"] += 1
        return tracer
    if frame.f_code in code_objects:
        if event == "line": counts["executed_source_lines"] += 1
        return tracer
    return None
start_wall = time.perf_counter_ns()
start_cpu = time.process_time_ns()
sys.settrace(tracer)
try:
    exec(compile(tests, "<tests>", "exec"), namespace)
finally:
    sys.settrace(None)
result = {"dynamic_function_steps": counts["executed_source_lines"],
          "step_definition": "CPython executed source-line events in candidate/helper frames",
          "function_calls": counts["calls"],
          "wall_nanoseconds": time.perf_counter_ns()-start_wall,
          "process_cpu_nanoseconds": time.process_time_ns()-start_cpu}
print("__EFFICIENCY__" + json.dumps(result, sort_keys=True))
'''
    script = (script.replace("__SOURCE__", repr(code))
              .replace("__TESTS__", repr(tests))
              .replace("__NAMES__", repr(function_names)))
    cmd = ["docker", "run", "--rm", "-i", "--network", "none", "--read-only",
           "--cap-drop", "ALL", "--security-opt", "no-new-privileges", "--pids-limit", "32",
           "--memory", "256m", "--cpus", "1", "--user", "10001:10001",
           "--entrypoint", "python", "viv-vm:1", "-I", "-"]
    started = time.perf_counter()
    with GpuPowerSampler() as sampler:
        try:
            result = subprocess.run(cmd, input=script, capture_output=True, text=True, timeout=30)
        except (subprocess.TimeoutExpired, FileNotFoundError) as exc:
            return False, {"state": "PROFILE_FAILED", "error": f"{type(exc).__name__}:{exc}"}, ""
    elapsed = time.perf_counter() - started
    marker = next((line[len("__EFFICIENCY__"):]
                   for line in result.stdout.splitlines() if line.startswith("__EFFICIENCY__")), None)
    if result.returncode != 0 or marker is None:
        return False, {"state": "PROFILE_FAILED", "gate_wall_seconds": elapsed}, (result.stderr or result.stdout)[-2000:]
    data = json.loads(marker)
    data.update({"state": "MEASURED", "gate_wall_seconds": elapsed,
                 "source": "CPYTHON_LINE_TRACE_IN_DOCKER",
                 "gpu_board": sampler.report()})
    if data.get("wall_nanoseconds", 0) > 0:
        data["speed_steps_per_second"] = (
            data["dynamic_function_steps"] / (data["wall_nanoseconds"] / 1_000_000_000))
    return True, data, ""

