"""Deterministic system telemetry sampler for RLE's energy term.

Reads the live HWInfo CSV (full-system) and nvidia-smi (GPU) and returns the
physical signals that feed:

    RLE = correct * exp(-(alpha*energy + beta*hops))

    energy  = CPU package power + GPU power        (watts, measured)
    thermal = coolant / core / GPU temperatures    (the entropy side)
    cooling = pump + fan RPM                        (the cost of removing the heat)

The Corsair CUE log is stale (last write 2026-11-05), but HWInfo reads the cooler's
own sensors directly, so coolant temperature and pump RPM are still live here.

Sensor indices are fixed to the current HWInfo column order and are soft-verified
against the header names on every read; a mismatch is reported rather than silently
trusted. Run:

    L:.venv/Scripts/python.exe -B L:/LocalCoder/workspace/autonomy/telemetry.py
"""
import csv
import io
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

HWINFO = Path(r"L:\LocalCoder\Hardware\hwinfo.CSV")

# (column index, expected-name fragment, output key)
SENSORS = [
    (151, "package power", "cpu_package_power_w"),
    (350, "gpu power", "gpu_power_w"),
    (97,  "core temperatures", "core_temp_avg_c"),
    (336, "coolant temperature", "coolant_temp_c"),
    (337, "pump", "pump_rpm"),
    (340, "gpu temperature", "gpu_temp_c"),
    (341, "hot spot", "gpu_hotspot_c"),
    (2,   "virtual memory", "virtual_memory_committed_mb"),
]


def _num(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _header_and_last(path):
    with open(path, "r", encoding="utf-8", errors="replace", newline="") as f:
        header_line = f.readline()
        f.seek(0, 2)
        size = f.tell()
        f.seek(max(0, size - 1048576))
        tail = f.read()
    header = next(csv.reader(io.StringIO(header_line)))
    ncols = len(header)
    # HWInfo writes the file continuously, so the final line can be a partial row.
    # Walk back from the end and return the last complete row.
    for line in reversed(tail.strip().splitlines()):
        values = next(csv.reader(io.StringIO(line)))
        if len(values) >= ncols:
            return header, values
    values = next(csv.reader(io.StringIO(tail.strip().splitlines()[-1])))
    return header, values


def nvidia_gpu():
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=power.draw,temperature.gpu,power.limit",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=10,
        )
        parts = out.stdout.strip().split(",")
        return {"gpu_w_nvidia": _num(parts[0]), "gpu_temp_c_nvidia": _num(parts[1]),
                "gpu_limit_w": _num(parts[2])}
    except Exception:
        return {}


def sample():
    header, values = _header_and_last(HWINFO)
    row = {}
    for index, fragment, key in SENSORS:
        name = header[index].strip().strip('"')
        if fragment not in name.lower():
            row.setdefault("mismatches", []).append((index, name, fragment))
            row[key] = None
        else:
            row[key] = _num(values[index])
    row.update(nvidia_gpu())
    cpu = row.get("cpu_package_power_w") or 0.0
    gpu = row.get("gpu_power_w") or 0.0
    row["energy_w"] = round(cpu + gpu, 2) if (cpu or gpu) else None
    row["sampled_at_utc"] = datetime.now(timezone.utc).isoformat()
    return row


if __name__ == "__main__":
    print(json.dumps(sample(), indent=2, default=str))
