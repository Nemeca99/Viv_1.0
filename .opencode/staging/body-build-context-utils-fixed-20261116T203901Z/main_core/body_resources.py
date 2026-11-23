"""Read-only hardware snapshot supplied to Rust body authority."""
from __future__ import annotations

from pathlib import Path
import re
import shutil
import subprocess
import sys

WORKSPACE_ROOT = Path(__file__).resolve().parents[2]
if str(WORKSPACE_ROOT) not in sys.path:
    sys.path.insert(0, str(WORKSPACE_ROOT))


def _reading(readings: dict, prefix: str) -> float | None:
    for name, raw in readings.items():
        if name == prefix or name.startswith(prefix + " "):
            match = re.match(r"\s*([+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?)", str(raw))
            if match is None:
                return None
            try:
                value = float(match.group(1))
            except (TypeError, ValueError):
                return None
            return value if value == value and abs(value) != float("inf") else None
    return None


def _thermal_samples(feed: dict, source: str) -> list[dict]:
    if feed.get("stale", True):
        return []
    age = feed.get("sample_age_seconds")
    readings = feed.get("readings", {})
    cpu_temp = _reading(readings, "CPU Package")
    if cpu_temp is None:
        return []
    gpu_prefixes = ("GPU Temperature",) if source == "hwinfo" else ("GPU Temp #1", "GPU Temp #2")
    samples = []
    for prefix in gpu_prefixes:
        gpu_temp = _reading(readings, prefix)
        if gpu_temp is not None:
            samples.append({
                "source": source,
                "sensor_age_seconds": age,
                "cpu_temp_c": cpu_temp,
                "gpu_temp_c": gpu_temp,
                "gpu_sensor": prefix,
            })
    return samples


def _nvidia_memory_percent() -> tuple[float | None, str]:
    """Read VRAM occupancy directly when the CSV feed has no fresh value."""
    executable = shutil.which("nvidia-smi")
    if not executable:
        return None, "unavailable:nvidia-smi-not-found"
    try:
        completed = subprocess.run(
            [executable, "--query-gpu=memory.used,memory.total",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=2, check=False,
        )
        if completed.returncode != 0 or not completed.stdout.strip():
            return None, "unavailable:nvidia-smi-query-failed"
        used_raw, total_raw = completed.stdout.splitlines()[0].split(",", 1)
        used, total = float(used_raw.strip()), float(total_raw.strip())
        if total <= 0:
            return None, "unavailable:nvidia-smi-invalid-total"
        return 100.0 * used / total, "nvidia-smi"
    except (OSError, ValueError, subprocess.SubprocessError):
        return None, "unavailable:nvidia-smi-query-error"


def collect_body_resources(*, sensor_root: Path | str | None = None,
                           workspace_root: Path | str = "L:/LocalCoder/workspace",
                           requested_threads: int = 1) -> dict:
    """Collect measurements only; thresholds and authorization stay in Rust."""
    try:
        from autonomy.hardware_sensors import body_sense_snapshot

        snapshot = body_sense_snapshot(root=sensor_root) if sensor_root else body_sense_snapshot()
        feeds = snapshot["external_sensor_logs"]
        hwinfo = feeds["hwinfo"]
        readings = hwinfo.get("readings", {})
        age = hwinfo.get("sample_age_seconds") if not hwinfo.get("stale", True) else None
        try:
            import psutil

            cpu_load_percent = float(psutil.cpu_percent(interval=0.05))
            ram_percent = float(psutil.virtual_memory().percent)
            disk = psutil.disk_usage(str(workspace_root))
            disk_free_percent = 100.0 - float(disk.percent)
            disk_free_bytes = int(disk.free)
        except (ImportError, OSError, AttributeError, ValueError):
            ram_percent = None
            disk_free_percent = None
            disk_free_bytes = None
        gpu_memory = _reading(readings, "GPU Memory Usage") if age is not None else None
        gpu_memory_source = "hwinfo" if gpu_memory is not None else ""
        if gpu_memory is None:
            gpu_memory, gpu_memory_source = _nvidia_memory_percent()
        return {
            "sensor_age_seconds": age,
            "cpu_temp_c": _reading(readings, "CPU Package"),
            "gpu_temp_c": _reading(readings, "GPU Temperature"),
            "thermal_samples": _thermal_samples(hwinfo, "hwinfo") + _thermal_samples(feeds["corsair"], "corsair"),
            "gpu_core_load_percent": _reading(readings, "GPU Core Load"),
            "gpu_memory_percent": gpu_memory,
            "gpu_memory_source": gpu_memory_source,
            "gpu_power_w": _reading(readings, "GPU Power [W]"),
            "cpu_load_percent": cpu_load_percent,
            "sample_window_seconds": 0.05,
            "ram_percent": ram_percent,
            "workspace_disk_free_percent": disk_free_percent,
            "workspace_disk_free_bytes": disk_free_bytes,
            "requested_threads": requested_threads,
            "sensor_source": "HWiNFO/Corsair CSV plus psutil",
        }
    except Exception as error:
        return {
            "sensor_age_seconds": None,
            "cpu_temp_c": None,
            "gpu_temp_c": None,
            "gpu_core_load_percent": None,
            "gpu_memory_percent": None,
            "gpu_memory_source": "unavailable:body-resource-collection-error",
            "gpu_power_w": None,
            "cpu_load_percent": None,
            "sample_window_seconds": None,
            "ram_percent": None,
            "workspace_disk_free_percent": None,
            "workspace_disk_free_bytes": None,
            "requested_threads": requested_threads,
            "sensor_source": "unavailable",
            "sensor_error": type(error).__name__,
        }
